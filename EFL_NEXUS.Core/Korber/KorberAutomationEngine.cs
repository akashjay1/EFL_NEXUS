using System.IO;
using System.Text.RegularExpressions;
using EflNexus.Core.Infrastructure;
using OpenQA.Selenium;
using OpenQA.Selenium.Support.UI;

namespace EflNexus.Core.Korber;

/// <summary>
/// Full GDN/GRN automation engine (single-shot + queue + retries + diagnostics) ported 1:1 from korber_tool.py.
/// </summary>
public sealed class KorberAutomationEngine
{
    public const int StepRetries = 10;
    public const int StepRetryDelaySeconds = 2;
    public const int DiscrepancyMaxRefreshRetries = 5;
    public const int DiscrepancyRefreshRetryDelaySeconds = 2;
    public const int AddGdnDetailMaxRefreshRetries = 20;
    public const int AddGdnDetailRefreshRetryDelaySeconds = 2;

    private sealed record KorberStep(string Name, string StatusText, Action Func, int Retries = StepRetries);

    public string ProfileName { get; }
    public IWebDriver? Driver { get; private set; }

    public List<KorberQueueItem> Queue { get; } = [];
    public bool QueueRunning { get; private set; }
    public bool FlowActive { get; private set; }
    public KorberFlowRequest? FlowRequest { get; private set; }
    public string FlowError { get; private set; } = "";

    private volatile bool _flowStopRequested;
    private Action<bool, string>? _flowOnComplete;
    private readonly object _queueLock = new();

    public event Action<string>? StatusChanged;
    public event Action<bool>? ProgressActiveChanged;
    public event Action<bool>? ControlsEnabledChanged;
    public event Action<KorberQueueItem>? QueueItemUpdated;
    public event Action<string>? FlowErrorDialogRequested;
    public event Action<string>? QueueFinishedDialogRequested;

    public KorberAutomationEngine(string profileName = "default")
    {
        ProfileName = profileName;
    }

    private void SetStatus(string text)
        => StatusChanged?.Invoke(text);

    public bool RunFlow(KorberFlowRequest request, Action<bool, string>? onComplete = null)
    {
        if (FlowActive || QueueRunning)
            return false;

        if (request.DocType == "GDN")
        {
            if (string.IsNullOrWhiteSpace(request.DeliveryLocation) || request.DeliveryLocation.Trim() == "-")
                request.DeliveryLocation = "N/A";
            if (string.IsNullOrWhiteSpace(request.SealNumber) || request.SealNumber.Trim() == "-")
                request.SealNumber = "N/A";

            if (string.IsNullOrWhiteSpace(request.WarehouseId) ||
                string.IsNullOrWhiteSpace(request.ClientCode) ||
                string.IsNullOrWhiteSpace(request.GatePassNumber) ||
                string.IsNullOrWhiteSpace(request.DeliveryLocation) ||
                string.IsNullOrWhiteSpace(request.SealNumber))
            {
                return false;
            }
        }
        else
        {
            if (string.IsNullOrWhiteSpace(request.WarehouseId) || string.IsNullOrWhiteSpace(request.GatePassNumber))
                return false;
        }

        FlowActive = true;
        _flowOnComplete = onComplete;
        _flowStopRequested = false;
        FlowError = "";
        FlowRequest = request;

        ControlsEnabledChanged?.Invoke(false);
        ProgressActiveChanged?.Invoke(true);
        SetStatus($"Opening browser for {request.DocType}...");

        Task.Run(() => RunFlowWorker(request));
        return true;
    }

    private void RunFlowWorker(KorberFlowRequest request)
    {
        try
        {
            PrepareAndExecuteFlow(request);
        }
        catch (Exception exc)
        {
            FinishFlow(false, $"{request.DocType} stopped before completion: {exc.Message}");
        }
    }

    private void FinishFlow(bool completed, string detail)
    {
        var cb = _flowOnComplete;
        _flowOnComplete = null;
        Exception? persistenceError = null;

        try
        {
            cb?.Invoke(completed, detail);
        }
        catch (Exception exc)
        {
            persistenceError = exc;
        }
        finally
        {
            FlowActive = false;
            FlowRequest = null;
        }

        ProgressActiveChanged?.Invoke(false);
        ControlsEnabledChanged?.Invoke(true);
        if (persistenceError is not null)
            SetStatus($"{detail}. Could not save inbox run state: {persistenceError.Message}");
    }

    private void PrepareAndExecuteFlow(KorberFlowRequest request)
    {
        if (Driver is not null)
        {
            try { Driver.Quit(); } catch { }
            Driver = null;
        }

        var ctx = new Dictionary<string, object?>(StringComparer.Ordinal);
        List<KorberStep> steps;
        try
        {
            steps = request.DocType == "GDN"
                ? BuildGdnSteps(request.WarehouseId, request.ClientCode, request.GatePassNumber, request.DeliveryLocation, request.SealNumber, ctx)
                : BuildGrnSteps(request.WarehouseId, request.GatePassNumber);
        }
        catch (Exception e)
        {
            FlowError = $"Failed ({request.DocType}) while preparing steps: {e.Message}";
            if (_flowStopRequested)
            {
                FinishFlow(false, "Browser session stopped");
                return;
            }
            ProgressActiveChanged?.Invoke(false);
            SetStatus($"Failed ({request.DocType}) while preparing steps");
            ReportError("preparing steps", e);
            return;
        }

        for (int i = 0; i < steps.Count; i++)
        {
            if (_flowStopRequested)
            {
                FinishFlow(false, "Browser session stopped");
                return;
            }

            var step = steps[i];
            SetStatus(step.StatusText);
            try
            {
                RunStepWithRetry(step.Name, step.Func, step.Retries);
            }
            catch (Exception e)
            {
                if (_flowStopRequested)
                {
                    FinishFlow(false, "Browser session stopped");
                    return;
                }
                FlowError = $"Failed ({request.DocType}) during {step.Name}: {e.Message}";
                ProgressActiveChanged?.Invoke(false);
                SetStatus($"Failed ({request.DocType}) during: {step.Name}");
                ReportError(step.Name, e);
                return;
            }
        }

        if (_flowStopRequested)
        {
            FinishFlow(false, "Browser session stopped");
            return;
        }

        string detail;
        if (request.DocType == "GDN")
        {
            var gdnNumber = ctx.TryGetValue("gdn_number", out var gn) ? gn?.ToString() ?? "" : "";
            detail = $"GDN {gdnNumber} completed and printed";
        }
        else
        {
            detail = "GRN created and printed";
        }

        SetStatus(detail);
        FinishFlow(true, detail);
    }

    public KorberQueueItem AddToQueue(KorberFlowRequest request)
    {
        var item = new KorberQueueItem
        {
            DocType = request.DocType,
            WarehouseId = request.WarehouseId.Trim(),
            ClientCode = request.ClientCode.Trim(),
            GatePassNumber = request.GatePassNumber.Trim(),
            DeliveryLocation = string.IsNullOrWhiteSpace(request.DeliveryLocation) || request.DeliveryLocation.Trim() == "-"
                ? "N/A" : request.DeliveryLocation.Trim(),
            SealNumber = string.IsNullOrWhiteSpace(request.SealNumber) || request.SealNumber.Trim() == "-"
                ? "N/A" : request.SealNumber.Trim(),
            Status = KorberQueueStatus.Queued
        };

        int count;
        lock (_queueLock)
        {
            Queue.Add(item);
            count = Queue.Count;
        }
        SetStatus($"Added {item.DocType} (Gate Pass {item.GatePassNumber}) to queue — {count} item(s) queued");
        return item;
    }

    public bool ClearQueue()
    {
        if (QueueRunning)
            return false;
        lock (_queueLock)
        {
            Queue.Clear();
        }
        SetStatus("Queue cleared");
        return true;
    }

    public string StopQueueItem(KorberQueueItem item)
    {
        if (item.Status == KorberQueueStatus.Queued)
        {
            item.StopRequested = true;
            UpdateQueueItemStatus(item, KorberQueueStatus.Stopped);
            SetStatus($"Skipped {item.DocType} {item.GatePassNumber} (was queued)");
            return "Skipped";
        }
        if (item.Status == KorberQueueStatus.Running)
        {
            item.StopRequested = true;
            SetStatus($"Stop requested for {item.DocType} {item.GatePassNumber} — stopping after current step...");
            return "Stopping";
        }
        return $"AlreadyFinished:{item.Status}";
    }

    private void UpdateQueueItemStatus(KorberQueueItem item, KorberQueueStatus status)
    {
        item.Status = status;
        QueueItemUpdated?.Invoke(item);
    }

    public bool RunQueue()
    {
        if (QueueRunning || FlowActive)
            return false;

        lock (_queueLock)
        {
            if (!Queue.Any(it => it.Status == KorberQueueStatus.Queued))
                return false;
        }

        QueueRunning = true;
        ControlsEnabledChanged?.Invoke(false);
        ProgressActiveChanged?.Invoke(true);
        SetStatus("Starting queue...");
        Task.Run(RunQueueWorker);
        return true;
    }

    private void RunQueueWorker()
    {
        if (Driver is null)
        {
            try
            {
                SetStatus("Opening browser...");
                Driver = KorberLoginBot.OpenNewBrowser(headless: false, profileName: ProfileName);
            }
            catch (Exception e)
            {
                SetStatus("Failed to open browser");
                FinishQueueRun();
                FlowErrorDialogRequested?.Invoke($"Could not start the queue: {e.Message}");
                return;
            }
        }

        int successCount = 0, failCount = 0, stoppedCount = 0, processedCount = 0;

        while (true)
        {
            KorberQueueItem? item;
            lock (_queueLock)
            {
                item = Queue.FirstOrDefault(it => it.Status == KorberQueueStatus.Queued);
            }
            if (item is null)
                break;

            processedCount++;

            if (item.StopRequested)
            {
                UpdateQueueItemStatus(item, KorberQueueStatus.Stopped);
                stoppedCount++;
                continue;
            }

            UpdateQueueItemStatus(item, KorberQueueStatus.Running);
            SetStatus($"[{item.DocType} {item.GatePassNumber}] Opening new tab...");

            try
            {
                KorberWebActions.OpenNewTabAndEnsureLogin(Driver);
            }
            catch
            {
                UpdateQueueItemStatus(item, KorberQueueStatus.Failed);
                failCount++;
                continue;
            }

            var ctx = new Dictionary<string, object?>(StringComparer.Ordinal);
            try
            {
                var steps = item.DocType == "GDN"
                    ? BuildGdnSteps(item.WarehouseId, item.ClientCode, item.GatePassNumber, item.DeliveryLocation, item.SealNumber, ctx)
                    : BuildGrnSteps(item.WarehouseId, item.GatePassNumber);

                bool wasStopped = false;
                for (int i = 2; i < steps.Count; i++)
                {
                    if (item.StopRequested)
                    {
                        wasStopped = true;
                        break;
                    }
                    var step = steps[i];
                    SetStatus($"[{item.DocType} {item.GatePassNumber}] {step.StatusText}");
                    RunStepWithRetry(step.Name, step.Func, step.Retries);
                }

                if (wasStopped)
                {
                    UpdateQueueItemStatus(item, KorberQueueStatus.Stopped);
                    stoppedCount++;
                }
                else
                {
                    UpdateQueueItemStatus(item, KorberQueueStatus.Done);
                    successCount++;
                }
            }
            catch
            {
                UpdateQueueItemStatus(item, KorberQueueStatus.Failed);
                failCount++;
                var safeGpChars = item.GatePassNumber.Where(char.IsLetterOrDigit).ToArray();
                var safeGp = safeGpChars.Length > 0 ? new string(safeGpChars) : "item";
                CaptureDiagnostics($"queue_{item.DocType}_{safeGp}");
            }
        }

        SetStatus($"Queue finished — {successCount} succeeded, {failCount} failed, {stoppedCount} stopped");
        FinishQueueRun();
        if (processedCount > 0)
        {
            QueueFinishedDialogRequested?.Invoke(
                $"{successCount} succeeded, {failCount} failed, {stoppedCount} stopped out of {processedCount} item(s).");
        }
    }

    private void FinishQueueRun()
    {
        QueueRunning = false;
        ProgressActiveChanged?.Invoke(false);
        ControlsEnabledChanged?.Invoke(true);
    }

    public void TerminateSession()
    {
        SetStatus("Terminating browser session...");
        lock (_queueLock)
        {
            foreach (var item in Queue)
            {
                if (item.Status is KorberQueueStatus.Queued or KorberQueueStatus.Running)
                    item.StopRequested = true;
            }
        }
        _flowStopRequested = true;

        if (Driver is not null)
        {
            try { Driver.Quit(); } catch { }
            Driver = null;
        }

        SetStatus("Browser session terminated — click Create GDN, Create GRN, or Run Queue to start a new one");
    }

    private List<KorberStep> BuildGrnSteps(string warehouseId, string gatePassNumber)
    {
        return
        [
            new("opening browser", "Opening browser...",
                () => Driver = KorberLoginBot.OpenNewBrowser(headless: false, profileName: ProfileName)),
            new("logging in", "Logging in...",
                () => KorberLoginBot.Login(Driver!)),
            new("opening GRN page", "Opening GRN page...",
                () => KorberWebActions.NavigateToGrn(Driver!)),
            new("filling form", "Filling form...",
                () => KorberWebActions.FillGrnForm(Driver!, warehouseId, gatePassNumber)),
            new("submitting query", "Submitting query...",
                () => KorberWebActions.ClickQueryButton(Driver!)),
            new("setting page size to 100", "Setting page size...",
                () => KorberWebActions.SetPageSize(Driver!, "100")),
            new("clicking select all", "Selecting all rows...",
                () => KorberWebActions.ClickSelectAllCheckbox(Driver!)),
            new("clicking Create GRN @ GatePass", "Creating GRN @ GatePass...",
                () =>
                {
                    KorberWebActions.ClickCreateGrnAtGatepass(Driver!);
                    ResolveQuantityDiscrepancyAfterCreateGrn();
                }),
            new("clicking GRN Details", "Opening GRN Details (can take a while)...",
                () => KorberWebActions.ClickGrnDetailsButton(Driver!, 10), Retries: 8),
            new("clicking Send GRN", "Sending GRN...",
                () =>
                {
                    if (!KorberWebActions.ClickSendGrnButton(Driver!))
                        SetStatus("Send GRN not detected — skipping to Print GRN - SKU...");
                }),
            new("checking for an OK confirmation dialog", "Checking for confirmation dialog...",
                () => KorberWebActions.ClickOkIfPresent(Driver!)),
            new("clicking Print GRN - SKU", "Printing GRN - SKU...",
                () => KorberWebActions.ClickPrintGrnSku(Driver!)),
            new("waiting for the GRN report to render", "Generating GRN report...",
                () => KorberWebActions.WaitForGrnReport(Driver!)),
            new("beeping after GRN report renders", "GRN report ready...",
                KorberWebActions.PlayCompletionBeep)
        ];
    }

    private List<KorberStep> BuildGdnSteps(
        string warehouseId,
        string clientCode,
        string gatePassNumber,
        string deliveryLocation,
        string sealNumber,
        Dictionary<string, object?> ctx)
    {
        return
        [
            new("opening browser", "Opening browser...",
                () => Driver = KorberLoginBot.OpenNewBrowser(headless: false, profileName: ProfileName)),
            new("logging in", "Logging in...",
                () => KorberLoginBot.Login(Driver!)),
            new("opening GDN page", "Opening GDN page...",
                () => KorberWebActions.NavigateToGdn(Driver!)),
            new("filling form", "Filling form...",
                () => KorberWebActions.FillGdnForm(Driver!, warehouseId, clientCode, gatePassNumber)),
            new("submitting query", "Submitting query...",
                () => ctx["query_li"] = KorberWebActions.ClickQueryButton(Driver!)),
            new("waiting for results page to load", "Loading results...",
                () => KorberWebActions.WaitForQueryResults(Driver!, ctx.GetValueOrDefault("query_li") as IWebElement)),
            new("clicking Add GDN", "Adding GDN...",
                () => ctx["add_gdn_link"] = KorberWebActions.ClickAddGdn(Driver!)),
            new("waiting for the Add GDN detail page to load", "Loading detail page...",
                () => KorberWebActions.WaitForAddGdnPage(Driver!, ctx.GetValueOrDefault("add_gdn_link") as IWebElement)),
            new("pausing after the Add GDN detail page loads", "Waiting for page to settle...",
                () => Thread.Sleep(2000)),
            new("capturing the auto-generated GDN number", "Reading GDN number...",
                () => ctx["gdn_number"] = KorberWebActions.CaptureGdnNumber(Driver!)),
            new("re-filling Warehouse ID on the detail page", "Filling Warehouse ID again...",
                () => KorberWebActions.FillWarehouseId(Driver!, warehouseId)),
            new("pausing after Warehouse ID is changed", "Waiting after Warehouse ID change...",
                () => Thread.Sleep(3000)),
            new("re-filling Client Code on the detail page", "Filling Client Code again...",
                () => KorberWebActions.FillClientCode(Driver!, clientCode)),
            new("re-filling Gate Pass Number on the detail page", "Filling Gate Pass Number again...",
                () => KorberWebActions.FillGatePassNumber(Driver!, gatePassNumber)),
            new("filling Delivery Location on the detail page", "Filling Delivery Location...",
                () => KorberWebActions.FillDeliveryLocation(Driver!, deliveryLocation)),
            new("filling Seal No. on the detail page", "Filling Seal No...",
                () => KorberWebActions.FillSealNumber(Driver!, sealNumber)),
            new("clicking Insert", "Inserting...",
                () => ctx["insert_link"] = KorberWebActions.ClickInsertButton(Driver!)),
            new("waiting for the page after Insert to load", "Loading next page...",
                () => KorberWebActions.WaitForInsertResult(Driver!, ctx.GetValueOrDefault("insert_link") as IWebElement)),
            new("clicking ADD GDN DETAIL", "Adding GDN detail...",
                () =>
                {
                    WaitForAddGdnDetailButton();
                    KorberWebActions.ClickAddGdnDetail(Driver!);
                }),
            new("clicking Add All to GDN", "Adding all to GDN...",
                () => KorberWebActions.ClickAddAllToGdn(Driver!)),
            new("checking for an OK confirmation dialog", "Checking for confirmation dialog...",
                () => KorberWebActions.ClickOkIfPresent(Driver!)),
            new("clicking Send", "Sending...",
                () => KorberWebActions.ClickSendButton(Driver!)),
            new("clicking Back twice", "Navigating back...",
                () =>
                {
                    for (int i = 0; i < 2; i++)
                    {
                        SetStatus($"Clicking Back ({i + 1}/2)...");
                        for (int attempt = 0; attempt < 3; attempt++)
                        {
                            try
                            {
                                KorberWebActions.ClickBackButton(Driver!);
                                break;
                            }
                            catch (Exception ex) when (KorberWebActions.IsRetryableException(ex))
                            {
                                SetStatus("Back click didn't register yet, retrying...");
                                Thread.Sleep(1500);
                            }
                        }
                        Thread.Sleep(500);
                    }
                }),
            new("clicking the GDN number row", "Opening GDN row...",
                () => KorberWebActions.ClickGdnNumberLink(Driver!, ctx["gdn_number"]?.ToString() ?? "")),
            new("clicking PRINT GDN - SKU", "Printing GDN - SKU...",
                () => KorberWebActions.ClickPrintGdnSku(Driver!)),
            new("waiting for the GDN report to render", "Generating GDN PDF...",
                () => KorberWebActions.WaitForGdnReport(Driver!)),
            new("beeping after GDN report renders", "GDN PDF ready...",
                KorberWebActions.PlayCompletionBeep)
        ];
    }

    private void RunStepWithRetry(string stepName, Action func, int retries = StepRetries)
    {
        Exception? lastExc = null;
        for (int attempt = 0; attempt <= retries; attempt++)
        {
            if (FlowActive && _flowStopRequested)
                throw new OperationCanceledException("Browser session stopped");

            if (Driver is not null)
                KorberWebActions.WaitForLoadingToDisappear(Driver);

            try
            {
                func();
                return;
            }
            catch (Exception e) when (KorberWebActions.IsRetryableException(e))
            {
                lastExc = e;
                CaptureDiagnostics($"retry_{stepName}");
                if (attempt < retries)
                {
                    SetStatus($"Slow response, retrying... (attempt {attempt + 2}/{retries + 1})");
                    Thread.Sleep(StepRetryDelaySeconds * 1000);
                }
            }
        }
        if (lastExc is not null)
            throw lastExc;
    }

    private void ResolveQuantityDiscrepancyAfterCreateGrn()
    {
        var settleWait = new WebDriverWait(Driver!, TimeSpan.FromSeconds(10));
        try
        {
            settleWait.Until(d =>
                KorberWebActions.IsGrnDetailsButtonAvailable(d) ||
                KorberWebActions.CheckForQuantityDiscrepancyError(d));
        }
        catch (WebDriverTimeoutException)
        {
            return;
        }

        if (KorberWebActions.IsGrnDetailsButtonAvailable(Driver!))
            return;

        KorberWebActions.PlayErrorBeep();
        CaptureDiagnostics("create_grn_system_error");
        SetStatus("System error detected — refreshing page...");

        for (int attempt = 0; attempt < DiscrepancyMaxRefreshRetries; attempt++)
        {
            try { KorberWebActions.ClickRefreshPageButton(Driver!); } catch { }
            Thread.Sleep(DiscrepancyRefreshRetryDelaySeconds * 1000);
            KorberWebActions.WaitForLoadingToDisappear(Driver!);

            try
            {
                settleWait.Until(d =>
                    KorberWebActions.IsGrnDetailsButtonAvailable(d) ||
                    !KorberWebActions.CheckForQuantityDiscrepancyError(d));
            }
            catch (WebDriverTimeoutException) { }

            if (KorberWebActions.IsGrnDetailsButtonAvailable(Driver!))
            {
                SetStatus("GRN Details button available — continuing...");
                return;
            }

            if (!KorberWebActions.CheckForQuantityDiscrepancyError(Driver!))
                continue;

            SetStatus($"Still seeing system error, refreshing again... (attempt {attempt + 2}/{DiscrepancyMaxRefreshRetries})");
        }

        throw new InvalidOperationException(
            $"'Create GRN @ GatePass' system error persisted after {DiscrepancyMaxRefreshRetries} refresh attempts");
    }

    private void WaitForAddGdnDetailButton()
    {
        KorberWebActions.WaitForLoadingToDisappear(Driver!);
        if (KorberWebActions.IsAddGdnDetailButtonAvailable(Driver!))
            return;

        SetStatus("ADD GDN DETAIL button not showing yet — refreshing page...");
        CaptureDiagnostics("add_gdn_detail_missing");

        for (int attempt = 0; attempt < AddGdnDetailMaxRefreshRetries; attempt++)
        {
            try { KorberWebActions.ClickRefreshPageButton(Driver!); } catch { }
            Thread.Sleep(AddGdnDetailRefreshRetryDelaySeconds * 1000);
            KorberWebActions.WaitForLoadingToDisappear(Driver!);

            if (KorberWebActions.IsAddGdnDetailButtonAvailable(Driver!))
            {
                SetStatus("ADD GDN DETAIL button available — continuing...");
                return;
            }

            SetStatus($"Still no ADD GDN DETAIL button, refreshing again... (attempt {attempt + 2}/{AddGdnDetailMaxRefreshRetries})");
        }

        throw new InvalidOperationException(
            $"ADD GDN DETAIL button did not appear after {AddGdnDetailMaxRefreshRetries} refresh attempts");
    }

    public (string? ScreenshotPath, string? HtmlPath) CaptureDiagnostics(string label)
    {
        if (Driver is null)
            return (null, null);

        var timestamp = DateTime.Now.ToString("yyyy-MM-dd_HH-mm-ss");
        var safeLabel = Regex.Replace(label ?? "", @"[^A-Za-z0-9_-]+", "_").Trim('_');
        if (string.IsNullOrEmpty(safeLabel))
            safeLabel = "issue";

        var diagDir = Path.Combine(AppPaths.AppDir, "diagnostics");
        try { Directory.CreateDirectory(diagDir); }
        catch { diagDir = "."; }

        var basePath = Path.Combine(diagDir, $"korber_issue_{timestamp}_{safeLabel}");
        string? screenshotPath = null;
        string? htmlPath = null;

        try
        {
            if (Driver is ITakesScreenshot ts)
            {
                screenshotPath = basePath + ".png";
                ts.GetScreenshot().SaveAsFile(screenshotPath);
            }
        }
        catch { screenshotPath = null; }

        try
        {
            htmlPath = basePath + ".html";
            File.WriteAllText(htmlPath, Driver.PageSource);
        }
        catch { htmlPath = null; }

        return (screenshotPath, htmlPath);
    }

    private void ReportError(string step, Exception e)
    {
        var errType = e.GetType().Name;
        var firstLine = (e.Message ?? "").Trim().Split(["\r\n", "\n"], StringSplitOptions.RemoveEmptyEntries).FirstOrDefault();
        var errMsg = string.IsNullOrEmpty(firstLine) ? "(no message provided)" : firstLine;

        var (screenshotPath, htmlPath) = CaptureDiagnostics($"final_{step}");
        var details = $"Failed during step: {step}\n\nException type: {errType}\nMessage: {errMsg}";
        details += $"\n\n(Already retried {StepRetries} extra time(s) automatically before giving up.)";
        if (!string.IsNullOrEmpty(screenshotPath))
            details += $"\n\nScreenshot saved: {screenshotPath}";
        if (!string.IsNullOrEmpty(htmlPath))
            details += $"\nPage HTML saved: {htmlPath}";

        FinishFlow(false, FlowError);
        FlowErrorDialogRequested?.Invoke(details);
    }
}
