using KorberAuditShip.Models;

namespace KorberAuditShip.Services;

/// <summary>
/// Callback delegate to notify UI about critical 300-second Körber popups
/// ("Device ID Error" or "Workflow Engine Error").
/// </summary>
public delegate void CriticalPopupHandler(string title, string message);

/// <summary>
/// Implements all Körber One Mobile Web automation workflows:
/// Opening/connecting Edge to WH &gt; EFL &gt; OUTBOUND, Load Audit EFL loop,
/// Shipping EFL loop, recovery/cancel sequences, and critical popup handling.
/// </summary>
public sealed class KorberAutomationService
{
    private readonly IBrowserSessionFactory _browserFactory;
    private readonly object _sessionLock = new();
    private IBrowserSession? _activeSession;
    private bool _criticalPopupActive;

    public KorberAutomationService(IBrowserSessionFactory browserFactory)
    {
        _browserFactory = browserFactory;
    }

    public bool HasActiveBrowser
    {
        get
        {
            lock (_sessionLock)
            {
                return _activeSession is not null;
            }
        }
    }

    public void AttachExistingSessionForTesting(IBrowserSession session)
    {
        lock (_sessionLock)
        {
            _activeSession = session;
        }
    }

    public void ForceCloseBrowser()
    {
        IBrowserSession? toClose;
        lock (_sessionLock)
        {
            toClose = _activeSession;
            _activeSession = null;
        }

        try
        {
            toClose?.Quit();
        }
        catch
        {
            // ignore errors on forced stop
        }
    }

    public async Task<WorkflowResult> OpenBrowserToOutboundAsync(
        IReadOnlyList<AuditShipRow> rows,
        KorberCredentials credentials,
        Action<string>? statusCallback,
        CriticalPopupHandler? criticalPopupCallback,
        CancellationToken ct)
    {
        var selectedWhId = SpreadsheetService.GetValidatedFirstWarehouseId(rows);
        IBrowserSession? driver = null;

        try
        {
            ForceCloseBrowser();

            driver = await _browserFactory.OpenOrAttachAsync(statusCallback, ct).ConfigureAwait(false);
            lock (_sessionLock)
            {
                _activeSession = driver;
            }

            statusCallback?.Invoke("Opening site...");
            driver.Navigate(KorberSelectors.KorberUrl);
            await WaitDomReadyAsync(driver, TimeSpan.FromSeconds(10), ct).ConfigureAwait(false);
            ApplyVisualScale(driver);
            await CheckForkScreenRepeatedAsync(driver, 3, credentials.ForkId, ct).ConfigureAwait(false);

            statusCallback?.Invoke("Entering login details...");
            await SafeTypeRequiredAsync(driver, KorberSelectors.InitialLoginUsernameXPaths, credentials.Username, "Username", 5, ct).ConfigureAwait(false);
            await SafeTypeRequiredAsync(driver, ["//input[@type='password']"], credentials.Password, "Password", 5, ct).ConfigureAwait(false);
            await SafeClickRequiredAsync(driver, KorberSelectors.InitialLoginButtonXPaths, "Login Button", 5, ct).ConfigureAwait(false);

            await WaitLoadingApplicationsFinishedAsync(driver, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
            await WaitDomReadyAsync(driver, TimeSpan.FromSeconds(8), ct).ConfigureAwait(false);
            ApplyVisualScale(driver);
            await CheckForkScreenRepeatedAsync(driver, 3, credentials.ForkId, ct).ConfigureAwait(false);

            statusCallback?.Invoke("Waiting for home page...");
            await WaitUntilHomePageReadyAsync(driver, TimeSpan.FromSeconds(30), criticalPopupCallback, statusCallback, ct).ConfigureAwait(false);
            ApplyVisualScale(driver);

            statusCallback?.Invoke("Opening menu...");
            await OpenHamburgerMenuAsync(driver, criticalPopupCallback, statusCallback, ct).ConfigureAwait(false);

            statusCallback?.Invoke("Opening Korber One Mobile...");
            await SafeClickRequiredAsync(driver, KorberSelectors.KorberMobileXPaths, "Korber One Mobile", 5, ct).ConfigureAwait(false);
            await SafeClickOptionalAsync(driver, KorberSelectors.MobileLoginXPaths, 3, ct).ConfigureAwait(false);

            await WaitDomReadyAsync(driver, TimeSpan.FromSeconds(6), ct).ConfigureAwait(false);
            ApplyVisualScale(driver);
            await CheckForkScreenRepeatedAsync(driver, 3, credentials.ForkId, ct).ConfigureAwait(false);

            statusCallback?.Invoke("Checking for Cancel / Invalid Option popup before warehouse selection...");
            await CancelSubmitSequenceWithoutQuitAsync(driver, credentials, statusCallback, criticalPopupCallback, 25, ct).ConfigureAwait(false);
            await ClickOkPopupIfPresentAsync(driver, TimeSpan.FromSeconds(2), ct).ConfigureAwait(false);

            statusCallback?.Invoke($"Selecting warehouse from Aligned Data Table: {selectedWhId}");
            await ClickWarehouseThenOutboundFastAsync(driver, selectedWhId, credentials.ForkId, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);

            var readyMsg = $"Browser ready at {selectedWhId} > EFL > OUTBOUND.";
            statusCallback?.Invoke(readyMsg);
            return new WorkflowResult(true, $"Browser opened and stopped at {selectedWhId} > EFL > OUTBOUND.");
        }
        catch (OperationCanceledException)
        {
            ForceCloseBrowser();
            return new WorkflowResult(false, "Stopped by BOT STOP.");
        }
        catch (Exception ex)
        {
            if (!ct.IsCancellationRequested)
                statusCallback?.Invoke($"Error: {ex.Message}");
            ForceCloseBrowser();
            return new WorkflowResult(false, ct.IsCancellationRequested ? "Stopped by BOT STOP." : ex.Message);
        }
    }

    public async Task<WorkflowResult> RunLoadAuditLoopAsync(
        IReadOnlyList<AuditShipRow> rows,
        KorberCredentials credentials,
        Action<string>? statusCallback,
        Action<int, string>? rowStatusCallback,
        CriticalPopupHandler? criticalPopupCallback,
        CancellationToken ct)
    {
        if (rows.Count == 0)
            return new WorkflowResult(false, "No row data available. Upload Excel first.");

        var driver = GetVerifiedActiveSession();
        if (driver is null)
            return new WorkflowResult(false, "Browser session is closed. Click Open Browser again.");

        try
        {
            await WaitDomReadyAsync(driver, TimeSpan.FromSeconds(5), ct).ConfigureAwait(false);
            ApplyVisualScale(driver);
            await CheckForkScreenRepeatedAsync(driver, 2, credentials.ForkId, ct).ConfigureAwait(false);

            await EnsureOutboundMenuReadyAsync(driver, rows, credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);

            if (!ScreenHasAny(driver, KorberSelectors.LoadIdAliases))
            {
                statusCallback?.Invoke("Opening Load Audit EFL...");
                await ClickAndWaitTransitionAsync(
                    driver,
                    "Load Audit EFL",
                    ["LOAD ID", "Enter the Load ID", "Scan your Fork identifier", "EQUIPMENT-ZONE"],
                    TimeSpan.FromSeconds(15),
                    optional: false,
                    credentials.ForkId,
                    ct).ConfigureAwait(false);
                await CheckForkScreenRepeatedAsync(driver, 3, credentials.ForkId, ct).ConfigureAwait(false);
            }

            var doneCount = 0;
            var skippedCount = 0;
            var totalRows = rows.Count;

            for (var i = 0; i < totalRows; i++)
            {
                var outcome = await ProcessOneLoadAuditRowAsync(
                    driver,
                    rows[i],
                    i + 1,
                    totalRows,
                    credentials,
                    statusCallback,
                    rowStatusCallback,
                    criticalPopupCallback,
                    ct).ConfigureAwait(false);

                if (outcome == RowStepOutcome.Done)
                    doneCount++;
                else
                    skippedCount++;
            }

            await ClickCancelToMainMenuAsync(
                driver,
                "Load Audit complete. Clicking Cancel once to return to main menu...",
                KorberSelectors.LoadIdAliases,
                criticalPopupCallback,
                statusCallback,
                ct).ConfigureAwait(false);

            statusCallback?.Invoke($"Load Audit finished. Done: {doneCount}, Skipped: {skippedCount}. Returned to main menu.");
            return new WorkflowResult(
                true,
                $"Load Audit finished | Done: {doneCount} | Skipped: {skippedCount} | Returned to main menu",
                doneCount,
                skippedCount);
        }
        catch (OperationCanceledException)
        {
            return new WorkflowResult(false, "Stopped by BOT STOP.");
        }
        catch (Exception ex)
        {
            return new WorkflowResult(false, ct.IsCancellationRequested ? "Stopped by BOT STOP." : ex.Message);
        }
    }

    public async Task<WorkflowResult> RunShippingLoopAsync(
        IReadOnlyList<AuditShipRow> rows,
        string sealNumber,
        KorberCredentials credentials,
        Action<string>? statusCallback,
        Action<int, string>? rowStatusCallback,
        CriticalPopupHandler? criticalPopupCallback,
        CancellationToken ct)
    {
        if (rows.Count == 0)
            return new WorkflowResult(false, "No row data available. Upload Excel first.");

        var driver = GetVerifiedActiveSession();
        if (driver is null)
            return new WorkflowResult(false, "Browser session is closed. Click Open Browser again.");

        try
        {
            await WaitDomReadyAsync(driver, TimeSpan.FromSeconds(5), ct).ConfigureAwait(false);
            ApplyVisualScale(driver);
            await CheckForkScreenRepeatedAsync(driver, 2, credentials.ForkId, ct).ConfigureAwait(false);

            await EnsureOutboundMenuReadyAsync(driver, rows, credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
            await EnsureShippingEflOpenAsync(driver, credentials.ForkId, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);

            var doneCount = 0;
            var skippedCount = 0;
            var totalRows = rows.Count;

            for (var i = 0; i < totalRows; i++)
            {
                var outcome = await ProcessOneShippingRowAsync(
                    driver,
                    rows[i],
                    i + 1,
                    totalRows,
                    sealNumber,
                    credentials,
                    statusCallback,
                    rowStatusCallback,
                    criticalPopupCallback,
                    ct).ConfigureAwait(false);

                if (outcome == RowStepOutcome.Done)
                    doneCount++;
                else
                    skippedCount++;
            }

            statusCallback?.Invoke("Shipping complete. Clicking Cancel once to return to main menu...");
            await ClickCancelToMainMenuAsync(
                driver,
                "Shipping complete. Clicking Cancel once to return to main menu...",
                KorberSelectors.ShippingLoadIdAliases,
                criticalPopupCallback,
                statusCallback,
                ct).ConfigureAwait(false);

            statusCallback?.Invoke($"Shipping finished. Done: {doneCount}, Skipped: {skippedCount}. Returned to main menu.");
            return new WorkflowResult(
                true,
                $"Shipping finished | Done: {doneCount} | Skipped: {skippedCount} | Returned to main menu",
                doneCount,
                skippedCount);
        }
        catch (OperationCanceledException)
        {
            return new WorkflowResult(false, "Stopped by BOT STOP.");
        }
        catch (Exception ex)
        {
            return new WorkflowResult(false, ct.IsCancellationRequested ? "Stopped by BOT STOP." : ex.Message);
        }
    }

    public async Task<WorkflowResult> CloseBrowserAsync(
        KorberCredentials? credentials,
        Action<string>? statusCallback,
        CriticalPopupHandler? criticalPopupCallback,
        CancellationToken ct)
    {
        var driver = GetVerifiedActiveSession();
        if (driver is null)
            return new WorkflowResult(false, "No open browser");

        try
        {
            await WaitDomReadyAsync(driver, TimeSpan.FromSeconds(5), ct).ConfigureAwait(false);
            ApplyVisualScale(driver);
            if (credentials is not null)
                await FastLoginIfNeededAsync(driver, credentials, statusCallback, 15, ct).ConfigureAwait(false);

            for (var step = 1; step <= 25; step++)
            {
                ct.ThrowIfCancellationRequested();

                if (IsFinalSubmitVisible(driver))
                {
                    statusCallback?.Invoke("Final Submit screen found. Clicking Submit if possible...");
                    if (ClickFinalSubmit(driver))
                    {
                        await WaitDomReadyAsync(driver, TimeSpan.FromSeconds(5), ct).ConfigureAwait(false);
                        await SleepSmallAsync(driver, 200, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
                        return new WorkflowResult(true, "Close sequence completed");
                    }

                    statusCallback?.Invoke("Final Submit button not required or not clickable. Ignoring and closing browser anyway...");
                    return new WorkflowResult(true, "Close sequence completed without optional final submit");
                }

                statusCallback?.Invoke($"Close sequence: clicking Cancel/back step {step}...");
                if (!await ClickAnyCancelOnceAsync(driver, ct).ConfigureAwait(false))
                {
                    if (IsFinalSubmitVisible(driver))
                    {
                        ClickFinalSubmit(driver);
                        return new WorkflowResult(true, "Close sequence completed");
                    }

                    return new WorkflowResult(true, "Cancel button was not found. Closing browser without optional final submit");
                }

                await SleepSmallAsync(driver, 250, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
            }

            return new WorkflowResult(false, "Close sequence stopped: too many Cancel steps");
        }
        catch (OperationCanceledException)
        {
            return new WorkflowResult(false, "Stopped by BOT STOP");
        }
        catch (Exception ex)
        {
            return new WorkflowResult(false, ex.Message);
        }
        finally
        {
            ForceCloseBrowser();
        }
    }

    private IBrowserSession? GetVerifiedActiveSession()
    {
        lock (_sessionLock)
        {
            if (_activeSession is null)
                return null;

            if (!_activeSession.IsAlive)
            {
                _activeSession.Quit();
                _activeSession = null;
                return null;
            }

            return _activeSession;
        }
    }

    private async Task<RowStepOutcome> ProcessOneLoadAuditRowAsync(
        IBrowserSession driver,
        AuditShipRow row,
        int rowNo,
        int totalRows,
        KorberCredentials credentials,
        Action<string>? statusCallback,
        Action<int, string>? rowStatusCallback,
        CriticalPopupHandler? criticalPopupCallback,
        CancellationToken ct)
    {
        var loadId = row.LoadId.Trim();
        var gatePassId = row.GatePassId.Trim();
        var doorLocation = row.DoorLocation.Trim();

        async Task<RowStepOutcome> SkipWithErrorAsync(string? rawMessage)
        {
            var msg = string.IsNullOrWhiteSpace(rawMessage) ? "ERROR" : rawMessage.Trim().ToUpperInvariant();
            statusCallback?.Invoke($"Row {rowNo}/{totalRows}: {msg}. Clicking OK and moving to next Load ID.");

            var okClicked = await ClickOkIfErrorAsync(driver, TimeSpan.FromSeconds(6), criticalPopupCallback, statusCallback, ct).ConfigureAwait(false);
            if (!okClicked)
                throw new InvalidOperationException($"Row {rowNo}/{totalRows}: {msg} popup appeared, but OK button could not be clicked");

            rowStatusCallback?.Invoke(row.RowIndex, msg);
            await WaitUntilErrorClosedAndLoadIdReadyAsync(driver, TimeSpan.FromSeconds(30), credentials.ForkId, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
            return RowStepOutcome.Skipped;
        }

        async Task<bool> CheckAfterSubmitAsync(string[] nextAliases, string nextName, int timeoutSeconds = 8)
        {
            var (result, message) = await WaitForErrorOrNextScreenAsync(driver, nextAliases, TimeSpan.FromSeconds(timeoutSeconds), statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
            if (result == "error")
            {
                await SkipWithErrorAsync(message).ConfigureAwait(false);
                return false;
            }

            if (result == "timeout")
                throw new TimeoutException($"Row {rowNo}/{totalRows}: {nextName} screen did not appear after Submit");

            return true;
        }

        statusCallback?.Invoke($"Row {rowNo}/{totalRows}: LOAD ID -> {loadId}");
        await WaitScreenAnyAsync(driver, KorberSelectors.LoadIdAliases, "LOAD ID", TimeSpan.FromSeconds(25), credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        await QuickFillAndSubmitAsync(driver, loadId, "Load ID", credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        if (!await CheckAfterSubmitAsync(KorberSelectors.GatePassAliases, "GATE PASS ID").ConfigureAwait(false))
            return RowStepOutcome.Skipped;

        statusCallback?.Invoke($"Row {rowNo}/{totalRows}: GATE PASS ID -> {gatePassId}");
        await WaitScreenAnyAsync(driver, KorberSelectors.GatePassAliases, "GATE PASS ID", TimeSpan.FromSeconds(25), credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        await QuickFillAndSubmitAsync(driver, gatePassId, "Gate Pass ID", credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        if (!await CheckAfterSubmitAsync(KorberSelectors.LocationAliases, "LOCATION").ConfigureAwait(false))
            return RowStepOutcome.Skipped;

        statusCallback?.Invoke($"Row {rowNo}/{totalRows}: LOCATION -> {doorLocation}");
        await WaitScreenAnyAsync(driver, KorberSelectors.LocationAliases, "LOCATION", TimeSpan.FromSeconds(25), credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        await QuickFillAndSubmitAsync(driver, doorLocation, "Location", credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);

        var (ynResult, ynMessage) = await WaitForErrorNextOrLoadingIssueAsync(driver, KorberSelectors.YesNoAliases, TimeSpan.FromSeconds(10), statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        if (ynResult == "error")
            return await SkipWithErrorAsync(ynMessage).ConfigureAwait(false);

        if (ynResult == "loading_issue")
        {
            statusCallback?.Invoke($"Row {rowNo}/{totalRows}: Loading issue screen found. Submitting and moving to next Load ID.");
            await QuickClickSubmitAsync(driver, credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
            // Preserves exact typo "Loding Issue" used by KORBER AuditShip reports
            rowStatusCallback?.Invoke(row.RowIndex, "Loding Issue");
            await WaitUntilErrorClosedAndLoadIdReadyAsync(driver, TimeSpan.FromSeconds(35), credentials.ForkId, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
            return RowStepOutcome.Skipped;
        }

        if (ynResult == "timeout")
            throw new TimeoutException($"Row {rowNo}/{totalRows}: Y or N screen did not appear after Submit");

        statusCallback?.Invoke($"Row {rowNo}/{totalRows}: Y or N -> N");
        await WaitScreenAnyAsync(driver, KorberSelectors.YesNoAliases, "Y or N", TimeSpan.FromSeconds(25), credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        await QuickFillAndSubmitAsync(driver, "N", "Y or N", credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        if (!await CheckAfterSubmitAsync(KorberSelectors.ConfirmAliases, "ENTER:Confirm", 10).ConfigureAwait(false))
            return RowStepOutcome.Skipped;

        statusCallback?.Invoke($"Row {rowNo}/{totalRows}: ENTER:Confirm -> Submit");
        await WaitScreenAnyAsync(driver, KorberSelectors.ConfirmAliases, "ENTER:Confirm", TimeSpan.FromSeconds(30), credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        await QuickClickSubmitAsync(driver, credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);

        var (finalResult, finalMessage) = await WaitForErrorOrNextScreenAsync(driver, KorberSelectors.LoadIdAliases, TimeSpan.FromSeconds(12), statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        if (finalResult == "error")
            return await SkipWithErrorAsync(finalMessage).ConfigureAwait(false);

        if (finalResult == "timeout")
            throw new TimeoutException($"Row {rowNo}/{totalRows}: LOAD ID screen did not return after final Submit");

        rowStatusCallback?.Invoke(row.RowIndex, "Done");
        return RowStepOutcome.Done;
    }

    private async Task<RowStepOutcome> ProcessOneShippingRowAsync(
        IBrowserSession driver,
        AuditShipRow row,
        int rowNo,
        int totalRows,
        string sealNumber,
        KorberCredentials credentials,
        Action<string>? statusCallback,
        Action<int, string>? rowStatusCallback,
        CriticalPopupHandler? criticalPopupCallback,
        CancellationToken ct)
    {
        var loadId = row.LoadId.Trim();
        var gatePassId = row.GatePassId.Trim();
        var doorLocation = row.DoorLocation.Trim();

        async Task<RowStepOutcome> SkipWithErrorAsync(string? rawMessage)
        {
            var msg = string.IsNullOrWhiteSpace(rawMessage) ? "ERROR" : rawMessage.Trim().ToUpperInvariant();
            statusCallback?.Invoke($"Row {rowNo}/{totalRows}: {msg}. Clicking OK and moving to next Load ID.");

            var okClicked = await ClickOkIfErrorAsync(driver, TimeSpan.FromSeconds(6), criticalPopupCallback, statusCallback, ct).ConfigureAwait(false);
            if (!okClicked)
                throw new InvalidOperationException($"Row {rowNo}/{totalRows}: {msg} popup appeared, but OK button could not be clicked");

            rowStatusCallback?.Invoke(row.RowIndex, msg);
            await WaitUntilErrorClosedAndLoadIdReadyAsync(driver, TimeSpan.FromSeconds(30), credentials.ForkId, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
            return RowStepOutcome.Skipped;
        }

        async Task<bool> CheckAfterSubmitAsync(string[] nextAliases, string nextName, int timeoutSeconds = 8)
        {
            var (result, message) = await WaitForErrorOrNextScreenAsync(driver, nextAliases, TimeSpan.FromSeconds(timeoutSeconds), statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
            if (result == "error")
            {
                await SkipWithErrorAsync(message).ConfigureAwait(false);
                return false;
            }

            if (result == "timeout")
                throw new TimeoutException($"Row {rowNo}/{totalRows}: {nextName} screen did not appear after Submit");

            return true;
        }

        statusCallback?.Invoke($"Shipping row {rowNo}/{totalRows}: LOAD ID -> {loadId}");
        await WaitScreenAnyAsync(driver, KorberSelectors.ShippingLoadIdAliases, "LOAD ID", TimeSpan.FromSeconds(25), credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        await QuickFillAndSubmitAsync(driver, loadId, "Load ID", credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        if (!await CheckAfterSubmitAsync(KorberSelectors.GatePassAliases, "GATE PASS ID").ConfigureAwait(false))
            return RowStepOutcome.Skipped;

        statusCallback?.Invoke($"Shipping row {rowNo}/{totalRows}: GATE PASS ID -> {gatePassId}");
        await WaitScreenAnyAsync(driver, KorberSelectors.GatePassAliases, "GATE PASS ID", TimeSpan.FromSeconds(25), credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        await QuickFillAndSubmitAsync(driver, gatePassId, "Gate Pass ID", credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        if (!await CheckAfterSubmitAsync(KorberSelectors.LocationAliases, "LOCATION").ConfigureAwait(false))
            return RowStepOutcome.Skipped;

        statusCallback?.Invoke($"Shipping row {rowNo}/{totalRows}: LOCATION -> {doorLocation}");
        await WaitScreenAnyAsync(driver, KorberSelectors.LocationAliases, "LOCATION", TimeSpan.FromSeconds(25), credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        await QuickFillAndSubmitAsync(driver, doorLocation, "Location", credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        if (!await CheckAfterSubmitAsync(KorberSelectors.CarrierAliases, "CARRIER NAME").ConfigureAwait(false))
            return RowStepOutcome.Skipped;

        statusCallback?.Invoke($"Shipping row {rowNo}/{totalRows}: CARRIER NAME -> DEFAULT");
        await WaitScreenAnyAsync(driver, KorberSelectors.CarrierAliases, "CARRIER NAME", TimeSpan.FromSeconds(25), credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        await QuickFillAndSubmitAsync(driver, "DEFAULT", "Carrier Name", credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        if (!await CheckAfterSubmitAsync(KorberSelectors.ProNumberAliases, "PRO NUMBER").ConfigureAwait(false))
            return RowStepOutcome.Skipped;

        statusCallback?.Invoke($"Shipping row {rowNo}/{totalRows}: PRO NUMBER -> {loadId}");
        await WaitScreenAnyAsync(driver, KorberSelectors.ProNumberAliases, "PRO NUMBER", TimeSpan.FromSeconds(25), credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        await QuickFillAndSubmitAsync(driver, loadId, "PRO Number", credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        if (!await CheckAfterSubmitAsync(KorberSelectors.SealNumberAliases, "SEAL NUMBER").ConfigureAwait(false))
            return RowStepOutcome.Skipped;

        statusCallback?.Invoke($"Shipping row {rowNo}/{totalRows}: SEAL NUMBER -> {sealNumber}");
        await WaitScreenAnyAsync(driver, KorberSelectors.SealNumberAliases, "SEAL NUMBER", TimeSpan.FromSeconds(25), credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        await QuickFillAndSubmitAsync(driver, sealNumber, "Seal Number", credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        if (!await CheckAfterSubmitAsync(KorberSelectors.ShippingConfirmAliases, "ENTER:Confirm", 10).ConfigureAwait(false))
            return RowStepOutcome.Skipped;

        statusCallback?.Invoke($"Shipping row {rowNo}/{totalRows}: ENTER:Confirm -> Submit");
        await WaitScreenAnyAsync(driver, KorberSelectors.ShippingConfirmAliases, "ENTER:Confirm", TimeSpan.FromSeconds(30), credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        await QuickClickSubmitAsync(driver, credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);

        var (finalResult, finalMessage) = await WaitForErrorOrNextScreenAsync(driver, KorberSelectors.ShippingLoadIdAliases, TimeSpan.FromSeconds(12), statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        if (finalResult == "error")
            return await SkipWithErrorAsync(finalMessage).ConfigureAwait(false);

        if (finalResult == "timeout")
            throw new TimeoutException($"Row {rowNo}/{totalRows}: LOAD ID screen did not return after final Submit");

        rowStatusCallback?.Invoke(row.RowIndex, "Done");
        return RowStepOutcome.Done;
    }

    private async Task EnsureOutboundMenuReadyAsync(
        IBrowserSession driver,
        IReadOnlyList<AuditShipRow> rows,
        KorberCredentials credentials,
        Action<string>? statusCallback,
        CriticalPopupHandler? criticalPopupCallback,
        CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        await FastLoginIfNeededAsync(driver, credentials, statusCallback, 15, ct).ConfigureAwait(false);

        if (PageHasAnyText(driver, KorberSelectors.OutboundSubmenuTexts))
            return;

        if (PageHasAnyText(driver, ["Home Page"]))
        {
            statusCallback?.Invoke("Home Page detected. Opening Korber One Mobile in the existing browser...");
            await OpenHamburgerMenuAsync(driver, criticalPopupCallback, statusCallback, ct).ConfigureAwait(false);
            await SafeClickRequiredAsync(driver, KorberSelectors.KorberMobileXPaths, "Korber One Mobile", 5, ct).ConfigureAwait(false);
            await SafeClickOptionalAsync(driver, KorberSelectors.MobileLoginXPaths, 3, ct).ConfigureAwait(false);
            await SleepSmallAsync(driver, 50, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
            await WaitDomReadyAsync(driver, TimeSpan.FromSeconds(6), ct).ConfigureAwait(false);
            ApplyVisualScale(driver);
            await CheckForkScreenRepeatedAsync(driver, 3, credentials.ForkId, ct).ConfigureAwait(false);
            statusCallback?.Invoke("Korber One Mobile login step completed in the existing browser.");
        }

        if (PageHasAnyText(driver, KorberSelectors.OutboundSubmenuTexts))
            return;

        var selectedWhId = SpreadsheetService.GetValidatedFirstWarehouseId(rows);
        statusCallback?.Invoke($"Preparing {selectedWhId} > EFL > OUTBOUND in the existing browser...");

        if (PageHasAnyText(driver, SpreadsheetService.ValidWarehouses) ||
            !PageHasAnyText(driver, ["EFL", "INBOUND", "INVENTORY", "OUTBOUND", "Main"]))
        {
            if (PageHasAnyText(driver, SpreadsheetService.ValidWarehouses) ||
                !PageHasAnyText(driver, ["INBOUND", "INVENTORY", "OUTBOUND"]))
            {
                await ClickWarehouseAsync(driver, selectedWhId, statusCallback, criticalPopupCallback, credentials.ForkId, ct).ConfigureAwait(false);
                await WaitForAnyTextAsync(driver, ["EFL", "INBOUND", "INVENTORY", "OUTBOUND"], TimeSpan.FromSeconds(8), statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
            }
        }

        if (!PageHasAnyText(driver, KorberSelectors.OutboundSubmenuTexts))
        {
            await ClickAndWaitTransitionAsync(
                driver,
                "EFL",
                ["INBOUND", "INVENTORY", "OUTBOUND"],
                TimeSpan.FromSeconds(6),
                optional: true,
                credentials.ForkId,
                ct).ConfigureAwait(false);

            await ClickAndWaitTransitionAsync(
                driver,
                "OUTBOUND",
                KorberSelectors.OutboundSubmenuTexts,
                TimeSpan.FromSeconds(15),
                optional: false,
                credentials.ForkId,
                ct).ConfigureAwait(false);
        }

        statusCallback?.Invoke("OUTBOUND menu is ready in the existing browser.");
    }

    private async Task EnsureShippingEflOpenAsync(
        IBrowserSession driver,
        string forkId,
        Action<string>? statusCallback,
        CriticalPopupHandler? criticalPopupCallback,
        CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        if (IsRfTextEntryVisible(driver) && ScreenHasAny(driver, ["LOAD ID", "Enter the Load ID"]))
            return;

        statusCallback?.Invoke("Clicking Shipping EFL first...");
        await ClickAndWaitTransitionAsync(
            driver,
            "Shipping EFL",
            ["LOAD ID", "Enter the Load ID", "Scan your Fork identifier", "EQUIPMENT-ZONE"],
            TimeSpan.FromSeconds(15),
            optional: false,
            forkId,
            ct).ConfigureAwait(false);

        await CheckForkScreenRepeatedAsync(driver, 3, forkId, ct).ConfigureAwait(false);

        var deadline = DateTime.UtcNow.AddSeconds(12);
        while (DateTime.UtcNow < deadline)
        {
            ct.ThrowIfCancellationRequested();
            if (IsRfTextEntryVisible(driver) && ScreenHasAny(driver, ["LOAD ID", "Enter the Load ID"]))
                return;
            await SleepSmallAsync(driver, 50, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        }

        throw new TimeoutException("Shipping EFL opened, but LOAD ID input box did not appear");
    }

    private async Task ClickWarehouseThenOutboundFastAsync(
        IBrowserSession driver,
        string whId,
        string forkId,
        Action<string>? statusCallback,
        CriticalPopupHandler? criticalPopupCallback,
        CancellationToken ct)
    {
        await ClickWarehouseAsync(driver, whId, statusCallback, criticalPopupCallback, forkId, ct).ConfigureAwait(false);
        await WaitForAnyTextAsync(driver, ["EFL", "INBOUND", "INVENTORY", "OUTBOUND"], TimeSpan.FromSeconds(60), statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);

        statusCallback?.Invoke("Warehouse opened. Clicking EFL...");
        await ClickAndWaitTransitionAsync(
            driver,
            "EFL",
            ["INBOUND", "INVENTORY", "OUTBOUND"],
            TimeSpan.FromSeconds(12),
            optional: true,
            forkId,
            ct).ConfigureAwait(false);

        await CheckForkScreenRepeatedAsync(driver, 3, forkId, ct).ConfigureAwait(false);
        statusCallback?.Invoke("Clicking OUTBOUND...");
        await ClickAndWaitTransitionAsync(
            driver,
            "OUTBOUND",
            KorberSelectors.OutboundSubmenuTexts,
            TimeSpan.FromSeconds(15),
            optional: false,
            forkId,
            ct).ConfigureAwait(false);

        await CheckForkScreenRepeatedAsync(driver, 3, forkId, ct).ConfigureAwait(false);
        ApplyVisualScale(driver);
    }

    private async Task ClickWarehouseAsync(
        IBrowserSession driver,
        string whId,
        Action<string>? statusCallback,
        CriticalPopupHandler? criticalPopupCallback,
        string forkId,
        CancellationToken ct)
    {
        var normalizedWh = AuditShipRow.NormalizeValue(whId);
        if (!SpreadsheetService.ValidWarehouses.Contains(normalizedWh, StringComparer.Ordinal))
            throw new InvalidOperationException($"Invalid WH Id in Excel: {whId}. Use one of: {string.Join(", ", SpreadsheetService.ValidWarehouses)}");

        var ready = await WaitForMainWarehouseScreenAsync(driver, TimeSpan.FromSeconds(180), forkId, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        if (!ready)
            throw new TimeoutException("Warehouse Main screen not ready. Main warehouse options were not visible.");

        statusCallback?.Invoke($"{normalizedWh} visible. Clicking warehouse immediately...");
        var oldVisibleText = NormalizeScreenText(driver.GetVisibleBodyText());

        var clicked = false;
        var clickEnd = DateTime.UtcNow.AddSeconds(20);
        while (DateTime.UtcNow < clickEnd)
        {
            ct.ThrowIfCancellationRequested();
            await HandleCriticalKorberPopupAsync(driver, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
            try
            {
                if (Convert.ToBoolean(driver.ExecuteScript(KorberSelectors.ClickWarehouseJs, normalizedWh)))
                {
                    clicked = true;
                    break;
                }
            }
            catch
            {
                // retry until clickEnd
            }

            await SleepSmallAsync(driver, 50, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        }

        if (!clicked)
        {
            string[] fallbackXPaths =
            [
                KorberSelectors.XPathTextExact(normalizedWh),
                $"//*[self::div or self::span or self::button or self::a][normalize-space()='{normalizedWh}']"
            ];
            var fallbackEnd = DateTime.UtcNow.AddSeconds(10);
            while (DateTime.UtcNow < fallbackEnd && !clicked)
            {
                ct.ThrowIfCancellationRequested();
                if (driver.TryDoubleClickVisibleByXPaths(fallbackXPaths))
                {
                    clicked = true;
                    break;
                }

                await SleepSmallAsync(driver, 50, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
            }
        }

        if (!clicked)
            throw new InvalidOperationException($"Warehouse click failed after Main appeared: {normalizedWh}");

        statusCallback?.Invoke($"{normalizedWh} clicked. Waiting for next menu...");

        var nextEnd = DateTime.UtcNow.AddSeconds(60);
        string[] nextMenuWords = ["EFL", "INBOUND", "INVENTORY", "OUTBOUND"];
        while (DateTime.UtcNow < nextEnd)
        {
            ct.ThrowIfCancellationRequested();
            await HandleCriticalKorberPopupAsync(driver, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
            await WaitDomReadyAsync(driver, TimeSpan.FromSeconds(2), ct).ConfigureAwait(false);
            ApplyVisualScale(driver);
            await CheckForkScreenRepeatedAsync(driver, 1, forkId, ct).ConfigureAwait(false);

            var currentVisible = NormalizeScreenText(driver.GetVisibleBodyText());
            if (nextMenuWords.Any(w => currentVisible.Contains(w, StringComparison.Ordinal)))
                return;

            if (!string.IsNullOrEmpty(currentVisible) &&
                currentVisible != oldVisibleText &&
                !currentVisible.Contains("MAIN", StringComparison.Ordinal))
            {
                return;
            }

            await SleepSmallAsync(driver, 50, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        }

        throw new TimeoutException($"{normalizedWh} was clicked, but the next menu did not appear");
    }

    private async Task<bool> WaitForMainWarehouseScreenAsync(
        IBrowserSession driver,
        TimeSpan timeout,
        string forkId,
        Action<string>? statusCallback,
        CriticalPopupHandler? criticalPopupCallback,
        CancellationToken ct)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            ct.ThrowIfCancellationRequested();
            await HandleCriticalKorberPopupAsync(driver, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
            await WaitDomReadyAsync(driver, TimeSpan.FromSeconds(2), ct).ConfigureAwait(false);
            ApplyVisualScale(driver);
            await CheckForkScreenRepeatedAsync(driver, 1, forkId, ct).ConfigureAwait(false);

            try
            {
                // Cast string[] to object so C# array covariance does not flatten it into params args
                var found = driver.ExecuteScript(
                    KorberSelectors.FindVisibleMainWarehouseJs,
                    (object)SpreadsheetService.ValidWarehouses.ToArray())?.ToString() ?? string.Empty;
                if (!string.IsNullOrEmpty(found))
                {
                    statusCallback?.Invoke($"Main menu warehouse options visible. Found {found}.");
                    return true;
                }
            }
            catch
            {
                // ignore
            }

            statusCallback?.Invoke("Waiting for Main warehouse menu...");
            await SleepSmallAsync(driver, 50, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        }

        return false;
    }

    private async Task ClickAndWaitTransitionAsync(
        IBrowserSession driver,
        string label,
        string[] nextTexts,
        TimeSpan timeout,
        bool optional,
        string forkId,
        CancellationToken ct)
    {
        if (ScreenHasAny(driver, nextTexts))
            return;

        var oldSource = driver.GetPageSource();
        await CheckForkScreenRepeatedAsync(driver, 2, forkId, ct).ConfigureAwait(false);

        var clicked = false;
        var exactEnd = DateTime.UtcNow.AddSeconds(Math.Min(timeout.TotalSeconds, 8));
        while (DateTime.UtcNow < exactEnd)
        {
            ct.ThrowIfCancellationRequested();
            try
            {
                if (Convert.ToBoolean(driver.ExecuteScript(KorberSelectors.ClickRfMenuButtonExactJs, label)))
                {
                    clicked = true;
                    break;
                }
            }
            catch
            {
                // continue to retry or XPath fallback
            }

            await Task.Delay(KorberSelectors.PollSleepMs, ct).ConfigureAwait(false);
        }

        if (!clicked)
        {
            string[] xpaths =
            [
                KorberSelectors.XPathTextExact(label),
                KorberSelectors.XPathTextContains(label),
                $"//div[contains(@class,'tile') and contains(normalize-space(), '{label}')]",
                $"//div[contains(@class,'card') and contains(normalize-space(), '{label}')]",
                $"//button[contains(normalize-space(), '{label}')]",
                $"//a[contains(normalize-space(), '{label}')]",
                $"//span[contains(normalize-space(), '{label}')]"
            ];
            var fallbackEnd = DateTime.UtcNow + timeout;
            while (DateTime.UtcNow < fallbackEnd)
            {
                ct.ThrowIfCancellationRequested();
                if (driver.TryClickVisibleByXPaths(xpaths))
                {
                    clicked = true;
                    break;
                }

                await Task.Delay(KorberSelectors.PollSleepMs, ct).ConfigureAwait(false);
            }
        }

        if (!clicked)
        {
            var jsEnd = DateTime.UtcNow + timeout;
            while (DateTime.UtcNow < jsEnd)
            {
                ct.ThrowIfCancellationRequested();
                try
                {
                    if (Convert.ToBoolean(driver.ExecuteScript(KorberSelectors.ClickByVisibleTextJs, label)))
                    {
                        clicked = true;
                        break;
                    }
                }
                catch
                {
                    // retry
                }

                await Task.Delay(KorberSelectors.PollSleepMs, ct).ConfigureAwait(false);
            }
        }

        await CheckForkScreenRepeatedAsync(driver, 2, forkId, ct).ConfigureAwait(false);

        if (!clicked)
        {
            if (!optional)
                throw new InvalidOperationException($"Required click failed: {label}");
            return;
        }

        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            ct.ThrowIfCancellationRequested();
            if (ScreenHasAny(driver, nextTexts))
                return;
            if (!string.IsNullOrEmpty(oldSource) && driver.GetPageSource() != oldSource && nextTexts.Length == 0)
                return;
            await Task.Delay(KorberSelectors.PollSleepMs, ct).ConfigureAwait(false);
        }

        if (!optional)
            throw new TimeoutException($"Required tile did not open: {label}");
    }

    private async Task CancelSubmitSequenceWithoutQuitAsync(
        IBrowserSession driver,
        KorberCredentials credentials,
        Action<string>? statusCallback,
        CriticalPopupHandler? criticalPopupCallback,
        int maxSteps,
        CancellationToken ct)
    {
        await WaitDomReadyAsync(driver, TimeSpan.FromSeconds(5), ct).ConfigureAwait(false);
        ApplyVisualScale(driver);

        if (await ClickOkPopupIfPresentAsync(driver, TimeSpan.FromSeconds(2), ct).ConfigureAwait(false))
            statusCallback?.Invoke("Invalid Option popup found. OK clicked. Continuing...");

        if (VisibleRfMenuButtonExists(driver, ["EFL", "INBOUND", "INVENTORY", "OUTBOUND"]))
        {
            statusCallback?.Invoke("RF main menu is already visible. Skipping Cancel/Submit recovery.");
            return;
        }

        var cancelSeen = VisibleTextExists(driver, ["F1:Cancel", "Cancel"]);
        var finalSeen = IsFinalSubmitVisible(driver);
        if (!cancelSeen && !finalSeen)
            return;

        statusCallback?.Invoke("Cancel/Submit recovery screen detected. Running recovery before warehouse selection...");

        for (var i = 1; i <= maxSteps; i++)
        {
            ct.ThrowIfCancellationRequested();

            if (await ClickOkPopupIfPresentAsync(driver, TimeSpan.FromSeconds(1), ct).ConfigureAwait(false))
            {
                statusCallback?.Invoke("Invalid Option popup found. OK clicked. Continuing to warehouse...");
                return;
            }

            if (IsFinalSubmitVisible(driver))
            {
                statusCallback?.Invoke("Final Submit screen found. Clicking Submit before warehouse selection...");
                if (!ClickFinalSubmit(driver))
                {
                    statusCallback?.Invoke("Final Submit button not required or not clickable. Ignoring and continuing normal Open Browser process...");
                    return;
                }

                await WaitDomReadyAsync(driver, TimeSpan.FromSeconds(5), ct).ConfigureAwait(false);
                ApplyVisualScale(driver);
                await SleepSmallAsync(driver, 200, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);

                if (await ClickOkPopupIfPresentAsync(driver, TimeSpan.FromSeconds(3), ct).ConfigureAwait(false))
                    statusCallback?.Invoke("Invalid Option popup found after Submit. OK clicked. Continuing to warehouse...");

                return;
            }

            if (!VisibleTextExists(driver, ["F1:Cancel", "Cancel"]))
                return;

            statusCallback?.Invoke($"Recovery: clicking Cancel/back step {i}...");
            var clicked = await ClickAnyCancelOnceAsync(driver, ct).ConfigureAwait(false);
            await HandleCriticalKorberPopupAsync(driver, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);

            if (!clicked)
            {
                if (await ClickOkPopupIfPresentAsync(driver, TimeSpan.FromSeconds(2), ct).ConfigureAwait(false))
                    return;

                if (IsFinalSubmitVisible(driver) && ClickFinalSubmit(driver))
                {
                    await ClickOkPopupIfPresentAsync(driver, TimeSpan.FromSeconds(3), ct).ConfigureAwait(false);
                    return;
                }

                return;
            }

            await SleepSmallAsync(driver, 200, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        }

        throw new InvalidOperationException("Cancel/Submit recovery stopped: too many Cancel steps");
    }

    private async Task ClickCancelToMainMenuAsync(
        IBrowserSession driver,
        string initialStatusMessage,
        string[] loadIdScreenAliases,
        CriticalPopupHandler? criticalPopupCallback,
        Action<string>? statusCallback,
        CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        statusCallback?.Invoke(initialStatusMessage);

        await WaitScreenAnyAsync(driver, loadIdScreenAliases, "LOAD ID", TimeSpan.FromSeconds(15), null, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);

        var clicked = await ClickAnyCancelOnceAsync(driver, ct).ConfigureAwait(false);
        if (!clicked)
            throw new InvalidOperationException("Could not click Cancel after Load Audit completion");

        await WaitForAnyTextAsync(driver, ["OUTBOUND", "OrderPick EFL", "Loading EFL", "Shipping EFL", "Load Audit EFL"], TimeSpan.FromSeconds(10), statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        statusCallback?.Invoke("Returned to main menu after clicking Cancel.");
    }

    private async Task<bool> ClickAnyCancelOnceAsync(IBrowserSession driver, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        try
        {
            var clicked = Convert.ToBoolean(driver.ExecuteScript(KorberSelectors.ClickAnyCancelOnceJs));
            if (clicked)
            {
                await WaitDomReadyAsync(driver, TimeSpan.FromSeconds(5), ct).ConfigureAwait(false);
                ApplyVisualScale(driver);
                await Task.Delay(100, ct).ConfigureAwait(false);
                return true;
            }
        }
        catch
        {
            // ignore and try visible text / F1 fallback
        }

        try
        {
            if (Convert.ToBoolean(driver.ExecuteScript(KorberSelectors.ClickByVisibleTextJs, "F1:Cancel")) ||
                Convert.ToBoolean(driver.ExecuteScript(KorberSelectors.ClickByVisibleTextJs, "Cancel")))
            {
                await WaitDomReadyAsync(driver, TimeSpan.FromSeconds(5), ct).ConfigureAwait(false);
                ApplyVisualScale(driver);
                return true;
            }
        }
        catch
        {
            // ignore and try F1 fallback
        }

        try
        {
            driver.SendF1Key();
            await WaitDomReadyAsync(driver, TimeSpan.FromSeconds(5), ct).ConfigureAwait(false);
            ApplyVisualScale(driver);
            return true;
        }
        catch
        {
            return false;
        }
    }

    private async Task WaitLoadingApplicationsFinishedAsync(
        IBrowserSession driver,
        Action<string>? statusCallback,
        CriticalPopupHandler? criticalPopupCallback,
        CancellationToken ct)
    {
        while (true)
        {
            ct.ThrowIfCancellationRequested();
            var outcome = await HandleCriticalKorberPopupAsync(driver, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
            if (outcome == CriticalPopupOutcome.WorkflowEngineDownClosed)
                throw new InvalidOperationException("Adwantage Workflow Engine is Down.");

            var visible = NormalizeScreenText(driver.GetVisibleBodyText());
            if (!visible.Contains("LOADING APPLICATIONS", StringComparison.Ordinal))
                return;

            statusCallback?.Invoke("Waiting until all Korber applications are loaded...");
            await Task.Delay(500, ct).ConfigureAwait(false);
        }
    }

    private async Task WaitUntilHomePageReadyAsync(
        IBrowserSession driver,
        TimeSpan timeout,
        CriticalPopupHandler? criticalPopupCallback,
        Action<string>? statusCallback,
        CancellationToken ct)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (true)
        {
            ct.ThrowIfCancellationRequested();
            var outcome = await HandleCriticalKorberPopupAsync(driver, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
            if (outcome == CriticalPopupOutcome.WorkflowEngineDownClosed)
                throw new InvalidOperationException("Adwantage Workflow Engine is Down.");

            var visible = NormalizeScreenText(driver.GetVisibleBodyText());
            if (visible.Contains("HOME PAGE", StringComparison.Ordinal))
                return;

            var loadingApps = visible.Contains("LOADING APPLICATIONS", StringComparison.Ordinal) ||
                              (visible.Contains("LOADING", StringComparison.Ordinal) && visible.Contains("APPLICATIONS", StringComparison.Ordinal));
            if (loadingApps)
            {
                await Task.Delay(500, ct).ConfigureAwait(false);
                continue;
            }

            if (DateTime.UtcNow >= deadline)
                break;

            await Task.Delay(250, ct).ConfigureAwait(false);
        }

        if (!driver.IsAnyXPathVisible([KorberSelectors.XPathTextExact("Home Page"), KorberSelectors.XPathTextContains("Home Page")]))
            throw new TimeoutException("Home Page did not become visible");
    }

    private async Task OpenHamburgerMenuAsync(
        IBrowserSession driver,
        CriticalPopupHandler? criticalPopupCallback,
        Action<string>? statusCallback,
        CancellationToken ct)
    {
        await WaitUntilHomePageReadyAsync(driver, TimeSpan.FromSeconds(30), criticalPopupCallback, statusCallback, ct).ConfigureAwait(false);

        if (driver.TryClickVisibleByXPaths(KorberSelectors.HamburgerMenuXPaths) &&
            await WaitForAnyVisibleAsync(driver, KorberSelectors.HamburgerOpenVerifyXPaths, TimeSpan.FromSeconds(3), ct).ConfigureAwait(false))
        {
            return;
        }

        var deadline = DateTime.UtcNow.AddSeconds(15);
        while (DateTime.UtcNow < deadline)
        {
            ct.ThrowIfCancellationRequested();
            try
            {
                driver.ExecuteScript(KorberSelectors.HamburgerFallbackPointsJs);
            }
            catch
            {
                // ignore
            }

            if (driver.IsAnyXPathVisible(KorberSelectors.HamburgerOpenVerifyXPaths))
                return;

            await Task.Delay(KorberSelectors.PollSleepMs, ct).ConfigureAwait(false);
        }

        throw new InvalidOperationException("Hamburger menu could not be opened after Home Page appeared");
    }

    private async Task FastLoginIfNeededAsync(
        IBrowserSession driver,
        KorberCredentials credentials,
        Action<string>? statusCallback,
        int timeoutSeconds,
        CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        if (!IsLoginScreenVisible(driver))
            return;

        statusCallback?.Invoke("Workspace login screen detected. Signing in on the existing browser...");
        await SafeTypeRequiredAsync(driver, KorberSelectors.LoginUsernameXPaths, credentials.Username, "Username", 5, ct).ConfigureAwait(false);
        await SafeTypeRequiredAsync(driver, KorberSelectors.LoginPasswordXPaths, credentials.Password, "Password", 5, ct).ConfigureAwait(false);
        await SafeClickRequiredAsync(driver, KorberSelectors.FastLoginButtonXPaths, "Login Button", 5, ct).ConfigureAwait(false);

        var deadline = DateTime.UtcNow.AddSeconds(timeoutSeconds);
        while (DateTime.UtcNow < deadline)
        {
            ct.ThrowIfCancellationRequested();
            if (!IsLoginScreenVisible(driver))
            {
                await WaitDomReadyAsync(driver, TimeSpan.FromSeconds(6), ct).ConfigureAwait(false);
                ApplyVisualScale(driver);
                statusCallback?.Invoke("Workspace login completed.");
                return;
            }
            await Task.Delay(50, ct).ConfigureAwait(false);
        }

        throw new TimeoutException("Workspace login screen was detected, but login did not complete");
    }

    private async Task QuickFillAndSubmitAsync(
        IBrowserSession driver,
        string value,
        string fieldName,
        KorberCredentials credentials,
        Action<string>? statusCallback,
        CriticalPopupHandler? criticalPopupCallback,
        CancellationToken ct)
    {
        await QuickTypeActiveInputAsync(driver, value, fieldName, credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        await QuickClickSubmitAsync(driver, credentials, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
    }

    private async Task QuickTypeActiveInputAsync(
        IBrowserSession driver,
        string value,
        string fieldName,
        KorberCredentials credentials,
        Action<string>? statusCallback,
        CriticalPopupHandler? criticalPopupCallback,
        CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        await FastLoginIfNeededAsync(driver, credentials, statusCallback, 15, ct).ConfigureAwait(false);
        await HandleCriticalKorberPopupAsync(driver, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);

        var targetValue = value ?? string.Empty;
        var filled = false;
        try
        {
            var actual = driver.ExecuteScript(KorberSelectors.QuickFillActiveInputJs, targetValue)?.ToString() ?? "NOT_FOUND";
            filled = actual != "NOT_FOUND" && actual.Trim() == targetValue.Trim();
        }
        catch
        {
            filled = false;
        }

        if (!filled && !driver.TryFallbackTypeRfInput(targetValue))
            throw new InvalidOperationException($"{fieldName} textbox not found or typing failed.");
    }

    private async Task QuickClickSubmitAsync(
        IBrowserSession driver,
        KorberCredentials credentials,
        Action<string>? statusCallback,
        CriticalPopupHandler? criticalPopupCallback,
        CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        await FastLoginIfNeededAsync(driver, credentials, statusCallback, 15, ct).ConfigureAwait(false);
        var critical = await HandleCriticalKorberPopupAsync(driver, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        if (critical == CriticalPopupOutcome.WorkflowEngineDownClosed)
            throw new InvalidOperationException("Adwantage Workflow Engine is Down.");

        try
        {
            if (Convert.ToBoolean(driver.ExecuteScript(KorberSelectors.QuickClickSubmitJs)))
            {
                await WaitDomReadyAsync(driver, TimeSpan.FromSeconds(3), ct).ConfigureAwait(false);
                return;
            }
        }
        catch
        {
            // ignore
        }

        if (driver.TryFallbackClickRfSubmit())
        {
            await WaitDomReadyAsync(driver, TimeSpan.FromSeconds(3), ct).ConfigureAwait(false);
            return;
        }

        try
        {
            driver.SendEnterKeyToActiveElement();
            await WaitDomReadyAsync(driver, TimeSpan.FromSeconds(3), ct).ConfigureAwait(false);
        }
        catch
        {
            throw new InvalidOperationException("Submit button click failed");
        }
    }

    private async Task WaitScreenAnyAsync(
        IBrowserSession driver,
        string[] aliases,
        string screenName,
        TimeSpan timeout,
        KorberCredentials? credentials,
        Action<string>? statusCallback,
        CriticalPopupHandler? criticalPopupCallback,
        CancellationToken ct)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            ct.ThrowIfCancellationRequested();
            if (credentials is not null)
                await FastLoginIfNeededAsync(driver, credentials, statusCallback, 15, ct).ConfigureAwait(false);

            await WaitDomReadyAsync(driver, TimeSpan.FromSeconds(4), ct).ConfigureAwait(false);
            ApplyVisualScale(driver);
            await CheckForkScreenRepeatedAsync(driver, 2, credentials?.ForkId ?? string.Empty, ct).ConfigureAwait(false);

            if (VisibleScreenHasAny(driver, aliases) || ScreenHasAny(driver, aliases))
                return;

            statusCallback?.Invoke($"Waiting for {screenName}...");
            await SleepSmallAsync(driver, KorberSelectors.PollSleepMs, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        }

        throw new TimeoutException($"{screenName} not visible");
    }

    private async Task<(string Result, string Message)> WaitForErrorOrNextScreenAsync(
        IBrowserSession driver,
        string[] nextAliases,
        TimeSpan timeout,
        Action<string>? statusCallback,
        CriticalPopupHandler? criticalPopupCallback,
        CancellationToken ct)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            ct.ThrowIfCancellationRequested();
            var errorMsg = GetVisibleErrorMessage(driver);
            if (!string.IsNullOrEmpty(errorMsg))
                return ("error", errorMsg);

            if (VisibleScreenHasAny(driver, nextAliases))
                return ("next", string.Empty);

            await SleepSmallAsync(driver, KorberSelectors.PollSleepMs, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        }

        return ("timeout", string.Empty);
    }

    private async Task<(string Result, string Message)> WaitForErrorNextOrLoadingIssueAsync(
        IBrowserSession driver,
        string[] nextAliases,
        TimeSpan timeout,
        Action<string>? statusCallback,
        CriticalPopupHandler? criticalPopupCallback,
        CancellationToken ct)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            ct.ThrowIfCancellationRequested();
            var errorMsg = GetVisibleErrorMessage(driver);
            if (!string.IsNullOrEmpty(errorMsg))
                return ("error", errorMsg);

            if (IsLoadAuditLoadingIssueScreen(driver))
                return ("loading_issue", "Loding Issue");

            if (VisibleScreenHasAny(driver, nextAliases))
                return ("next", string.Empty);

            await SleepSmallAsync(driver, KorberSelectors.PollSleepMs, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        }

        return ("timeout", string.Empty);
    }

    private async Task<bool> ClickOkIfErrorAsync(
        IBrowserSession driver,
        TimeSpan timeout,
        CriticalPopupHandler? criticalPopupCallback,
        Action<string>? statusCallback,
        CancellationToken ct)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            ct.ThrowIfCancellationRequested();
            try
            {
                if (Convert.ToBoolean(driver.ExecuteScript(KorberSelectors.ClickErrorOkJs)))
                {
                    await WaitDomReadyAsync(driver, TimeSpan.FromSeconds(5), ct).ConfigureAwait(false);
                    await Task.Delay(120, ct).ConfigureAwait(false);
                    return true;
                }
            }
            catch
            {
                // fallback to XPath below
            }

            if (driver.TryClickVisibleByXPaths(KorberSelectors.ErrorOkXPaths))
            {
                await WaitDomReadyAsync(driver, TimeSpan.FromSeconds(5), ct).ConfigureAwait(false);
                await Task.Delay(50, ct).ConfigureAwait(false);
                return true;
            }

            await SleepSmallAsync(driver, 50, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        }

        return false;
    }

    private async Task<bool> ClickOkPopupIfPresentAsync(IBrowserSession driver, TimeSpan timeout, CancellationToken ct)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            ct.ThrowIfCancellationRequested();
            var screen = GetScreenText(driver);
            if (screen.Contains("ERROR", StringComparison.Ordinal) &&
                (screen.Contains("INVALID OPTION", StringComparison.Ordinal) || screen.Contains("OK", StringComparison.Ordinal)))
            {
                if (await ClickOkIfErrorAsync(driver, TimeSpan.FromSeconds(1.5), null, null, ct).ConfigureAwait(false))
                {
                    await WaitDomReadyAsync(driver, TimeSpan.FromSeconds(5), ct).ConfigureAwait(false);
                    ApplyVisualScale(driver);
                    await Task.Delay(150, ct).ConfigureAwait(false);
                    return true;
                }
            }

            if (driver.TryClickVisibleByXPaths(KorberSelectors.GenericOkXPaths))
            {
                await WaitDomReadyAsync(driver, TimeSpan.FromSeconds(5), ct).ConfigureAwait(false);
                ApplyVisualScale(driver);
                await Task.Delay(150, ct).ConfigureAwait(false);
                return true;
            }

            await Task.Delay(50, ct).ConfigureAwait(false);
        }

        return false;
    }

    private async Task WaitUntilErrorClosedAndLoadIdReadyAsync(
        IBrowserSession driver,
        TimeSpan timeout,
        string forkId,
        Action<string>? statusCallback,
        CriticalPopupHandler? criticalPopupCallback,
        CancellationToken ct)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            ct.ThrowIfCancellationRequested();
            if (!string.IsNullOrEmpty(GetVisibleErrorMessage(driver)))
            {
                await ClickOkIfErrorAsync(driver, TimeSpan.FromSeconds(1.5), criticalPopupCallback, statusCallback, ct).ConfigureAwait(false);
                await Task.Delay(100, ct).ConfigureAwait(false);
                continue;
            }

            await WaitDomReadyAsync(driver, TimeSpan.FromSeconds(4), ct).ConfigureAwait(false);
            ApplyVisualScale(driver);
            await CheckForkScreenRepeatedAsync(driver, 2, forkId, ct).ConfigureAwait(false);

            if (IsRfTextEntryVisible(driver) &&
                VisibleScreenHasAny(driver, ["LOAD ID", "Enter the Load ID", "Load Audit EFL", "Shipping EFL"]))
            {
                return;
            }

            statusCallback?.Invoke("Waiting for next LOAD ID screen after error OK...");
            await SleepSmallAsync(driver, 50, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        }

        throw new TimeoutException("LOAD ID screen did not become ready after clicking Error OK");
    }

    public async Task<CriticalPopupOutcome> HandleCriticalKorberPopupAsync(
        IBrowserSession driver,
        Action<string>? statusCallback,
        CriticalPopupHandler? criticalPopupCallback,
        CancellationToken ct)
    {
        if (_criticalPopupActive)
            return CriticalPopupOutcome.None;

        var visibleText = NormalizeScreenText(driver.GetVisibleBodyText());
        if (string.IsNullOrEmpty(visibleText))
            return CriticalPopupOutcome.None;

        if (visibleText.Contains("THE KOERBER ONE USER HAS CHANGED FOR THIS TERMINAL", StringComparison.Ordinal))
        {
            _criticalPopupActive = true;
            try
            {
                await SafeClickOptionalAsync(driver, KorberSelectors.DismissXPaths, 4, ct).ConfigureAwait(false);
                const string title = "Device ID Error";
                const string message = "Your device ID is being used by another user. Please contact the System Team.";
                criticalPopupCallback?.Invoke(title, message);
                await WaitSecondsWithStopAsync(
                    KorberSelectors.CriticalPopupWaitSeconds,
                    statusCallback,
                    "Device ID is used by another user.",
                    ct).ConfigureAwait(false);
                return CriticalPopupOutcome.DeviceIdWaitCompleted;
            }
            finally
            {
                _criticalPopupActive = false;
            }
        }

        if (visibleText.Contains("ADVANTAGE WORKFLOW ENGINE IS DOWN", StringComparison.Ordinal) ||
            visibleText.Contains("ADWANTAGE WORKFLOW ENGINE IS DOWN", StringComparison.Ordinal) ||
            visibleText.Contains("WORKFLOW ENGINE IS DOWN", StringComparison.Ordinal))
        {
            _criticalPopupActive = true;
            try
            {
                await SafeClickOptionalAsync(driver, KorberSelectors.DismissXPaths, 4, ct).ConfigureAwait(false);
                const string title = "Workflow Engine Error";
                const string message = "Adwantage Workflow Engine is Down.Please contact the System Team.";
                criticalPopupCallback?.Invoke(title, message);
                await WaitSecondsWithStopAsync(
                    KorberSelectors.CriticalPopupWaitSeconds,
                    statusCallback,
                    "Workflow Engine is down.",
                    ct).ConfigureAwait(false);
                ForceCloseBrowser();
                return CriticalPopupOutcome.WorkflowEngineDownClosed;
            }
            finally
            {
                _criticalPopupActive = false;
            }
        }

        return CriticalPopupOutcome.None;
    }

    private static async Task WaitSecondsWithStopAsync(
        int totalSeconds,
        Action<string>? statusCallback,
        string prefixMessage,
        CancellationToken ct)
    {
        for (var remaining = totalSeconds; remaining > 0; remaining--)
        {
            ct.ThrowIfCancellationRequested();
            statusCallback?.Invoke($"{prefixMessage} Waiting {remaining} seconds...");
            await Task.Delay(1000, ct).ConfigureAwait(false);
        }
    }

    private async Task CheckForkScreenRepeatedAsync(IBrowserSession driver, int repeat, string forkId, CancellationToken ct)
    {
        if (string.IsNullOrWhiteSpace(forkId))
            return;

        for (var i = 0; i < repeat; i++)
        {
            ct.ThrowIfCancellationRequested();
            var handled = await HandleForkIdentifierIfPresentAsync(driver, forkId, ct).ConfigureAwait(false);
            if (handled)
                await Task.Delay(30, ct).ConfigureAwait(false);
        }
    }

    private async Task<bool> HandleForkIdentifierIfPresentAsync(IBrowserSession driver, string forkId, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        string[] forkTextXPaths =
        [
            KorberSelectors.XPathTextContains("Scan your Fork identifier"),
            KorberSelectors.XPathTextExact("EQUIPMENT-ZONE")
        ];

        if (!driver.IsAnyXPathVisible(forkTextXPaths))
            return false;

        if (!driver.TryTypeVisibleByXPaths(KorberSelectors.ForkInputXPaths, forkId))
            return false;

        if (!driver.TryClickVisibleByXPaths(KorberSelectors.ForkSubmitXPaths))
        {
            try
            {
                driver.SendEnterKeyToActiveElement();
            }
            catch
            {
                // ignore
            }
        }

        await Task.Delay(30, ct).ConfigureAwait(false);
        return true;
    }

    private async Task SleepSmallAsync(
        IBrowserSession driver,
        int milliseconds,
        Action<string>? statusCallback,
        CriticalPopupHandler? criticalPopupCallback,
        CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        var critical = await HandleCriticalKorberPopupAsync(driver, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        if (critical == CriticalPopupOutcome.WorkflowEngineDownClosed)
            throw new InvalidOperationException("Adwantage Workflow Engine is Down.");

        var delayMs = Math.Clamp(milliseconds, 1, 200);
        await Task.Delay(delayMs, ct).ConfigureAwait(false);
    }

    private static async Task WaitDomReadyAsync(IBrowserSession driver, TimeSpan timeout, CancellationToken ct)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            ct.ThrowIfCancellationRequested();
            var state = driver.GetReadyState();
            if (state is "interactive" or "complete")
                return;
            await Task.Delay(KorberSelectors.PollSleepMs, ct).ConfigureAwait(false);
        }
    }

    private static void ApplyVisualScale(IBrowserSession driver)
    {
        try
        {
            driver.ExecuteScript(KorberSelectors.BuildVisualScaleScript(KorberSelectors.VisualScale));
        }
        catch
        {
            // ignore visual scaling failure
        }
    }

    private static async Task SafeTypeRequiredAsync(
        IBrowserSession driver,
        IEnumerable<string> xpaths,
        string value,
        string name,
        int timeoutSeconds,
        CancellationToken ct)
    {
        var deadline = DateTime.UtcNow.AddSeconds(timeoutSeconds);
        while (DateTime.UtcNow < deadline)
        {
            ct.ThrowIfCancellationRequested();
            if (driver.TryTypeVisibleByXPaths(xpaths, value))
                return;
            await Task.Delay(KorberSelectors.PollSleepMs, ct).ConfigureAwait(false);
        }

        throw new InvalidOperationException($"Required typing failed: {name}");
    }

    private static async Task SafeClickRequiredAsync(
        IBrowserSession driver,
        IEnumerable<string> xpaths,
        string name,
        int timeoutSeconds,
        CancellationToken ct)
    {
        var deadline = DateTime.UtcNow.AddSeconds(timeoutSeconds);
        while (DateTime.UtcNow < deadline)
        {
            ct.ThrowIfCancellationRequested();
            if (driver.TryClickVisibleByXPaths(xpaths))
                return;
            await Task.Delay(KorberSelectors.PollSleepMs, ct).ConfigureAwait(false);
        }

        throw new InvalidOperationException($"Required click failed: {name}");
    }

    private static async Task SafeClickOptionalAsync(
        IBrowserSession driver,
        IEnumerable<string> xpaths,
        int timeoutSeconds,
        CancellationToken ct)
    {
        var deadline = DateTime.UtcNow.AddSeconds(timeoutSeconds);
        while (DateTime.UtcNow < deadline)
        {
            ct.ThrowIfCancellationRequested();
            if (driver.TryClickVisibleByXPaths(xpaths))
                return;
            await Task.Delay(KorberSelectors.PollSleepMs, ct).ConfigureAwait(false);
        }
    }

    private static async Task<bool> WaitForAnyVisibleAsync(
        IBrowserSession driver,
        IEnumerable<string> xpaths,
        TimeSpan timeout,
        CancellationToken ct)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            ct.ThrowIfCancellationRequested();
            if (driver.IsAnyXPathVisible(xpaths))
                return true;
            await Task.Delay(KorberSelectors.PollSleepMs, ct).ConfigureAwait(false);
        }

        return false;
    }

    private async Task<bool> WaitForAnyTextAsync(
        IBrowserSession driver,
        IEnumerable<string> texts,
        TimeSpan timeout,
        Action<string>? statusCallback,
        CriticalPopupHandler? criticalPopupCallback,
        CancellationToken ct)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            ct.ThrowIfCancellationRequested();
            if (PageHasAnyText(driver, texts))
                return true;
            await SleepSmallAsync(driver, KorberSelectors.PollSleepMs, statusCallback, criticalPopupCallback, ct).ConfigureAwait(false);
        }

        return false;
    }

    public static string NormalizeScreenText(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return string.Empty;

        var cleaned = value.Replace('\u00A0', ' ').ToUpperInvariant();
        return string.Join(' ', cleaned.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
    }

    public static string GetScreenText(IBrowserSession driver)
    {
        var visible = driver.GetVisibleBodyText();
        var src = driver.GetPageSource();
        return NormalizeScreenText($"{visible}\n{src}");
    }

    public static bool ScreenHasAny(IBrowserSession driver, IEnumerable<string> aliases)
    {
        var screen = GetScreenText(driver);
        return aliases.Any(a => screen.Contains(NormalizeScreenText(a), StringComparison.Ordinal));
    }

    public static bool VisibleScreenHasAny(IBrowserSession driver, IEnumerable<string> aliases)
    {
        var visible = NormalizeScreenText(driver.GetVisibleBodyText());
        return aliases.Any(a => visible.Contains(NormalizeScreenText(a), StringComparison.Ordinal));
    }

    public static bool PageHasAnyText(IBrowserSession driver, IEnumerable<string> texts)
    {
        var src = driver.GetPageSource();
        var body = driver.GetVisibleBodyText();
        var combined = $"{src}\n{body}";
        return texts.Any(t => combined.Contains(t, StringComparison.OrdinalIgnoreCase));
    }

    public static string GetVisibleErrorMessage(IBrowserSession driver)
    {
        try
        {
            var raw = driver.ExecuteScript(KorberSelectors.GetVisibleErrorMessageJs)?.ToString() ?? string.Empty;
            return raw.Trim().ToUpperInvariant();
        }
        catch
        {
            return string.Empty;
        }
    }

    private static bool IsLoginScreenVisible(IBrowserSession driver)
    {
        try
        {
            return Convert.ToBoolean(driver.ExecuteScript(KorberSelectors.IsLoginScreenVisibleJs));
        }
        catch
        {
            var screen = GetScreenText(driver);
            return screen.Contains("SIGN IN", StringComparison.Ordinal) &&
                   screen.Contains("USER NAME", StringComparison.Ordinal) &&
                   screen.Contains("PASSWORD", StringComparison.Ordinal) &&
                   screen.Contains("LOGIN", StringComparison.Ordinal);
        }
    }

    private static bool IsRfTextEntryVisible(IBrowserSession driver)
    {
        try
        {
            return Convert.ToBoolean(driver.ExecuteScript(KorberSelectors.IsRfTextEntryVisibleJs));
        }
        catch
        {
            return false;
        }
    }

    private static bool IsLoadAuditLoadingIssueScreen(IBrowserSession driver)
    {
        try
        {
            return Convert.ToBoolean(driver.ExecuteScript(KorberSelectors.IsLoadingIssueScreenJs));
        }
        catch
        {
            return false;
        }
    }

    private static bool VisibleTextExists(IBrowserSession driver, IEnumerable<string> texts)
    {
        try
        {
            var upperSrc = (driver.GetPageSource() + "\n" + driver.GetVisibleBodyText()).ToUpperInvariant();
            return texts.Any(t => upperSrc.Contains(t.ToUpperInvariant(), StringComparison.Ordinal));
        }
        catch
        {
            return false;
        }
    }

    private static bool VisibleRfMenuButtonExists(IBrowserSession driver, string[] labels)
    {
        try
        {
            var normalized = labels.Select(l => l.Trim().ToUpperInvariant()).ToArray();
            return Convert.ToBoolean(driver.ExecuteScript(KorberSelectors.VisibleRfMenuButtonExistsJs, (object)normalized));
        }
        catch
        {
            return false;
        }
    }

    private static bool IsFinalSubmitVisible(IBrowserSession driver)
    {
        try
        {
            return Convert.ToBoolean(driver.ExecuteScript(KorberSelectors.FinalSubmitVisibleJs));
        }
        catch
        {
            return false;
        }
    }

    private static bool ClickFinalSubmit(IBrowserSession driver)
    {
        try
        {
            return Convert.ToBoolean(driver.ExecuteScript(KorberSelectors.ClickFinalSubmitJs));
        }
        catch
        {
            return false;
        }
    }

}
