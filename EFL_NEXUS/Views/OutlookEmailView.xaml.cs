using System.Diagnostics;
using System.IO;
using System.Threading.Channels;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using EflNexus.App.Dialogs;
using EflNexus.App.Helpers;
using EflNexus.Core.Infrastructure;
using EflNexus.Core.OutlookEmail;
using MediaColor = System.Windows.Media.Color;

namespace EflNexus.App.Views;

public partial class OutlookEmailView : System.Windows.Controls.UserControl
{
    public const string DefaultBodyText = "Dear all,\n\nFYI.";

    private static readonly SolidColorBrush BrushPrimaryBg = new(MediaColor.FromRgb(0x0B, 0x14, 0x20));
    private static readonly SolidColorBrush BrushPrimaryFg = new(Colors.White);
    private static readonly SolidColorBrush BrushSecondaryBg = new(MediaColor.FromRgb(0xE2, 0xE8, 0xF0));
    private static readonly SolidColorBrush BrushSecondaryFg = new(MediaColor.FromRgb(0x0F, 0x17, 0x2A));

    private static readonly SolidColorBrush TagTime = new(MediaColor.FromRgb(0x64, 0x74, 0x8B));
    private static readonly SolidColorBrush TagSuccess = new(MediaColor.FromRgb(0x16, 0xA3, 0x4A));
    private static readonly SolidColorBrush TagQueued = new(MediaColor.FromRgb(0x7C, 0x3A, 0xED));
    private static readonly SolidColorBrush TagSending = new(MediaColor.FromRgb(0xD9, 0x77, 0x06));
    private static readonly SolidColorBrush TagError = new(MediaColor.FromRgb(0xDC, 0x26, 0x26));
    private static readonly SolidColorBrush TagInfo = new(MediaColor.FromRgb(0x02, 0x84, 0xC7));
    private static readonly SolidColorBrush TagLabel = new(MediaColor.FromRgb(0x47, 0x55, 0x69));
    private static readonly SolidColorBrush TagVal = new(MediaColor.FromRgb(0x0F, 0x17, 0x2A));
    private static readonly SolidColorBrush TagSep = new(MediaColor.FromRgb(0xCB, 0xD5, 0xE1));
    private static readonly SolidColorBrush StatusReadyText = new(MediaColor.FromRgb(0x33, 0x41, 0x55));

    private sealed record LogCardRefs(Run StatusRun, Paragraph SepParagraph);

    private sealed record SendQueueJob(
        string ToAddr,
        string CcAddr,
        string Subject,
        string Body,
        List<string> AttachmentPaths,
        bool IncludeSig,
        string? SendType,
        string GatePassNum,
        string WarehouseName,
        int CardId);

    private readonly ConfigStore _configStore;
    private readonly OutlookComClient _outlook = new();
    private readonly TemplateStore _templateStore;
    private readonly SentLogStore _sentLog;
    private readonly List<string> _attachmentPaths = [];
    private readonly Channel<SendQueueJob> _sendQueue = Channel.CreateUnbounded<SendQueueJob>();
    private readonly Dictionary<int, LogCardRefs> _logCards = [];
    private readonly DispatcherTimer _toastTimer;

    private string? _subjectBeforeType;
    private string? _lastPrefix;
    private string _selectedType = string.Empty;
    private int _sessionDispatchCount;
    private int _queuedPendingCount;
    private int _cardIdCounter;
    private bool _queueWorkerStarted;
    private bool _suppressTemplateSelection;

    public Action? OnOpenSettings { get; set; }

    /// <summary>Raised on the UI thread after a GDN/GRN mail is sent: (sendType, gatepass, warehouse).</summary>
    public Action<string, string, string>? OnGatepassSent { get; set; }

    public OutlookEmailView()
        : this(null, null)
    {
    }

    public OutlookEmailView(ConfigStore? configStore, Action? onOpenSettings = null)
    {
        InitializeComponent();
        _configStore = configStore ?? new ConfigStore();
        OnOpenSettings = onOpenSettings;
        _templateStore = new TemplateStore();
        _sentLog = new SentLogStore(_configStore);

        _toastTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(4500) };
        _toastTimer.Tick += (_, _) =>
        {
            _toastTimer.Stop();
            ToastText.Text = string.Empty;
        };

        RichTextTableHelper.ConfigureFlatParagraphSpacing(MessageRichBox);
        RichTextTableHelper.SetPlainText(MessageRichBox, DefaultBodyText);
        ConfigureActivityDocument();

        RefreshTemplateDropdown();
        RefreshCounts();
        PopulateRecentActivityLogs();
    }

    private void ConfigureActivityDocument()
    {
        var style = new Style(typeof(Paragraph));
        style.Setters.Add(new Setter(Block.MarginProperty, new Thickness(0, 1, 0, 1)));
        ActivityRichBox.Resources[typeof(Paragraph)] = style;
        ActivityRichBox.Document = new FlowDocument();
    }

    public void RefreshCounts()
    {
        _ = Task.Run(async () =>
        {
            var counts = await _sentLog.GetCountsAsync();
            var text = $"GDN sent: {counts.Gdn}    GRN sent: {counts.Grn}";
            _ = Dispatcher.BeginInvoke(() => CountsText.Text = text);
        });
    }

    public void RefreshTemplates(string? selectName = null) => RefreshTemplateDropdown(selectName);

    public void RefreshAfterClearCache()
    {
        RefreshCounts();
        RefreshTemplateDropdown();
    }

    public void OpenRecordsWindow()
    {
        string sheetUrl = _configStore.GetSheetUrl();
        if (string.IsNullOrWhiteSpace(sheetUrl))
        {
            System.Windows.MessageBox.Show(
                Window.GetWindow(this),
                "Please set your Google Sheet URL in ⚙ Settings first.",
                "Missing URL",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
            return;
        }

        _ = Task.Run(() => _sentLog.GetCountsAsync());
        try
        {
            Process.Start(new ProcessStartInfo(sheetUrl) { UseShellExecute = true });
        }
        catch (Exception ex)
        {
            System.Windows.MessageBox.Show(
                Window.GetWindow(this),
                $"Could not open the web browser:\n\n{ex.Message}",
                "Browser Error",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
        }
    }

    private void PopulateRecentActivityLogs()
    {
        _ = Task.Run(() =>
        {
            var records = _sentLog.GetRecentRecords(limit: 4);
            if (records.Count == 0)
                return;

            Dispatcher.BeginInvoke(() =>
            {
                for (int i = records.Count - 1; i >= 0; i--)
                {
                    var r = records[i];
                    AppendActivityLog(
                        status: "HISTORY",
                        gatePass: string.IsNullOrEmpty(r.Number) ? "N/A" : r.Number,
                        warehouse: string.IsNullOrEmpty(r.Warehouse) ? "General" : r.Warehouse,
                        sendType: r.Type,
                        subject: $"{r.Warehouse} {r.Type} - {r.Number}".Trim());
                }
            });
        });
    }

    private void RefreshTemplateDropdown(string? selectName = null)
    {
        _suppressTemplateSelection = true;
        try
        {
            var names = _templateStore.GetNames();
            var items = new List<string> { TemplateStore.Placeholder };
            items.AddRange(names);
            TemplateCombo.ItemsSource = items;

            if (!string.IsNullOrEmpty(selectName) && names.Contains(selectName))
            {
                TemplateCombo.SelectedItem = selectName;
                _suppressTemplateSelection = false;
                ApplySelectedTemplate();
            }
            else
            {
                TemplateCombo.SelectedIndex = 0;
            }
        }
        finally
        {
            _suppressTemplateSelection = false;
        }
    }

    private void TemplateCombo_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!_suppressTemplateSelection)
            ApplySelectedTemplate();
    }

    private void ApplySelectedTemplate()
    {
        string? name = TemplateCombo.SelectedItem?.ToString();
        if (string.IsNullOrEmpty(name) || name == TemplateStore.Placeholder)
            return;

        var template = _templateStore.GetTemplate(name);
        if (template is null)
            return;

        ToBox.Text = template.To;
        CcBox.Text = template.Cc;

        if (!string.IsNullOrEmpty(_selectedType))
            ApplySubjectPrefix(_selectedType);
    }

    private void AddTemplate_Click(object sender, RoutedEventArgs e)
    {
        var owner = Window.GetWindow(this);
        var dlg = new AddTemplateDialog(owner, (name, toAddr, ccAddr) =>
        {
            _templateStore.AddOrUpdateTemplate(name, toAddr, ccAddr);
            RefreshTemplateDropdown(name);
        });
        dlg.ShowDialog();
    }

    private string BuildSubjectPrefix(string typeName)
    {
        string? templateName = TemplateCombo.SelectedItem?.ToString();
        if (!string.IsNullOrEmpty(templateName) && templateName != TemplateStore.Placeholder)
            return $"{templateName} {typeName} - ";
        return $"{typeName} - ";
    }

    private void ApplySubjectPrefix(string typeName)
    {
        string currentText = SubjectBox.Text ?? string.Empty;
        string numberPart = (!string.IsNullOrEmpty(_lastPrefix) && currentText.StartsWith(_lastPrefix, StringComparison.Ordinal))
            ? currentText[_lastPrefix.Length..]
            : string.Empty;
        string prefix = BuildSubjectPrefix(typeName);
        SubjectBox.Text = prefix + numberPart;
        _lastPrefix = prefix;
    }

    private void SelectType(string? typeName)
    {
        bool turningOff = typeName is not null && _selectedType == typeName;
        string newType = turningOff ? string.Empty : (typeName ?? string.Empty);
        _selectedType = newType;

        if (!string.IsNullOrEmpty(newType))
        {
            _subjectBeforeType ??= SubjectBox.Text ?? string.Empty;
            ApplySubjectPrefix(newType);
        }
        else
        {
            if (_subjectBeforeType is not null)
                SubjectBox.Text = _subjectBeforeType;
            _subjectBeforeType = null;
            _lastPrefix = null;
        }

        UpdateTypeButtonVisuals();
    }

    private void UpdateTypeButtonVisuals()
    {
        ApplyToggleStyle(GdnTypeBtn, _selectedType == SentLogStore.SendTypeGdn);
        ApplyToggleStyle(GrnTypeBtn, _selectedType == SentLogStore.SendTypeGrn);
    }

    private static void ApplyToggleStyle(System.Windows.Controls.Button btn, bool active)
    {
        btn.Background = active ? BrushPrimaryBg : BrushSecondaryBg;
        btn.Foreground = active ? BrushPrimaryFg : BrushSecondaryFg;
    }

    private void SelectGdn_Click(object sender, RoutedEventArgs e) => SelectType(SentLogStore.SendTypeGdn);
    private void SelectGrn_Click(object sender, RoutedEventArgs e) => SelectType(SentLogStore.SendTypeGrn);
    private void ClearType_Click(object sender, RoutedEventArgs e) => SelectType(null);

    private void Settings_Click(object sender, RoutedEventArgs e)
    {
        if (OnOpenSettings is not null)
        {
            OnOpenSettings();
        }
        else
        {
            var dlg = new EmailSettingsDialog(Window.GetWindow(this), _configStore, RefreshCounts);
            dlg.ShowDialog();
        }
    }

    private void ViewRecords_Click(object sender, RoutedEventArgs e) => OpenRecordsWindow();

    private void MessageRichBox_PreviewKeyDown(object sender, System.Windows.Input.KeyEventArgs e)
    {
        if (e.Key == Key.V && (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control)
        {
            if (RichTextTableHelper.TryPasteExcelOrText(MessageRichBox))
                e.Handled = true;
        }
    }

    private void AttachFiles_Click(object sender, RoutedEventArgs e)
    {
        var dlg = new Microsoft.Win32.OpenFileDialog
        {
            Title = "Select PDF and/or Excel files to attach",
            Multiselect = true,
            Filter = "PDF and Excel files|*.pdf;*.xlsx;*.xls|PDF files|*.pdf|Excel files|*.xlsx;*.xls|All files|*.*"
        };
        if (dlg.ShowDialog(Window.GetWindow(this)) != true)
            return;

        foreach (var path in dlg.FileNames)
        {
            if (!_attachmentPaths.Contains(path, StringComparer.OrdinalIgnoreCase))
                _attachmentPaths.Add(path);
        }
        RefreshAttachmentList();
    }

    private void RemoveSelectedAttachment_Click(object sender, RoutedEventArgs e)
    {
        var indices = AttachmentsListBox.SelectedItems
            .Cast<object>()
            .Select(item => AttachmentsListBox.Items.IndexOf(item))
            .Where(idx => idx >= 0)
            .OrderByDescending(idx => idx)
            .ToList();

        if (indices.Count == 0)
            return;

        foreach (int idx in indices)
            _attachmentPaths.RemoveAt(idx);
        RefreshAttachmentList();
    }

    private void ClearAttachments_Click(object sender, RoutedEventArgs e) => ClearAttachments();

    private void ClearAttachments()
    {
        _attachmentPaths.Clear();
        RefreshAttachmentList();
    }

    private void RefreshAttachmentList()
    {
        AttachmentsListBox.Items.Clear();
        foreach (var path in _attachmentPaths)
            AttachmentsListBox.Items.Add(Path.GetFileName(path));
    }

    private (string ToAddr, string CcAddr, string Subject, string Body) GatherFields()
    {
        string toAddr = RecipientHelpers.NormalizeRecipients((ToBox.Text ?? string.Empty).Trim());
        string ccAddr = RecipientHelpers.NormalizeRecipients((CcBox.Text ?? string.Empty).Trim());
        string subject = (SubjectBox.Text ?? string.Empty).Trim();
        string body = RichTextTableHelper.GetPlainText(MessageRichBox);
        return (toAddr, ccAddr, subject, body);
    }

    private bool ValidateFields(string toAddr, string subject)
    {
        var owner = Window.GetWindow(this);
        if (string.IsNullOrEmpty(toAddr))
        {
            System.Windows.MessageBox.Show(owner, "Please enter at least one 'To:' recipient.", "Missing recipient", MessageBoxButton.OK, MessageBoxImage.Warning);
            return false;
        }
        if (string.IsNullOrEmpty(subject))
        {
            var res = System.Windows.MessageBox.Show(owner, "The subject line is empty. Send anyway?", "No subject", MessageBoxButton.YesNo, MessageBoxImage.Question);
            if (res != MessageBoxResult.Yes)
                return false;
        }
        return true;
    }

    private void PreviewEmail_Click(object sender, RoutedEventArgs e)
    {
        var (toAddr, ccAddr, subject, body) = GatherFields();
        if (!ValidateFields(toAddr, subject))
            return;

        bool includeSig = IncludeSignatureCheck.IsChecked == true;
        var attachments = _attachmentPaths.ToList();

        _ = Task.Run(async () =>
        {
            try
            {
                await _outlook.PreviewAsync(toAddr, ccAddr, subject, body, attachments, includeSig);
            }
            catch (Exception ex)
            {
                _ = Dispatcher.BeginInvoke(() =>
                    System.Windows.MessageBox.Show(
                        Window.GetWindow(this),
                        $"Could not open the preview in Outlook:\n\n{ex.Message}",
                        "Outlook error",
                        MessageBoxButton.OK,
                        MessageBoxImage.Error));
            }
        });
    }

    private void SendEmail_Click(object sender, RoutedEventArgs e)
    {
        var (toAddr, ccAddr, subject, body) = GatherFields();
        if (!ValidateFields(toAddr, subject))
            return;

        string attachmentSummary = _attachmentPaths.Count > 0
            ? string.Join("\n", _attachmentPaths.Select(p => $"  - {Path.GetFileName(p)}"))
            : "  (none)";
        string? sendType = string.IsNullOrEmpty(_selectedType) ? null : _selectedType;
        string confirmText =
            $"To: {toAddr}\n" +
            $"CC: {(string.IsNullOrEmpty(ccAddr) ? "(none)" : ccAddr)}\n" +
            $"Subject: {(string.IsNullOrEmpty(subject) ? "(none)" : subject)}\n" +
            $"Type: {(sendType ?? "(none)")}\n" +
            $"Attachments:\n{attachmentSummary}\n\n" +
            "Add to send queue?";

        if (System.Windows.MessageBox.Show(Window.GetWindow(this), confirmText, "Confirm send", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes)
            return;

        string? templateName = TemplateCombo.SelectedItem?.ToString();
        var (gatePassNum, warehouseName) = ExtractGatePassAndWarehouse(sendType, subject, templateName);
        var attachmentsCopy = _attachmentPaths.ToList();
        bool includeSig = IncludeSignatureCheck.IsChecked == true;

        int cardId = CreateLogCard(gatePassNum, warehouseName, sendType, subject, toAddr, ccAddr, attachmentsCopy);

        int depth = Interlocked.Increment(ref _queuedPendingCount);
        ActivityStatusDot.Foreground = TagQueued;
        ActivityStatusText.Text = $"Queue: {depth} email(s) pending";
        ActivityStatusText.Foreground = TagQueued;

        _sendQueue.Writer.TryWrite(new SendQueueJob(
            toAddr, ccAddr, subject, body, attachmentsCopy, includeSig, sendType, gatePassNum, warehouseName, cardId));
        StartQueueWorker();
        ResetAfterSend();
    }

    private void StartQueueWorker()
    {
        if (_queueWorkerStarted)
            return;
        _queueWorkerStarted = true;
        _ = Task.Run(async () =>
        {
            await foreach (var job in _sendQueue.Reader.ReadAllAsync())
            {
                await ProcessSendJobAsync(job);
            }
        });
    }

    private async Task ProcessSendJobAsync(SendQueueJob job)
    {
        int remainingBefore = Math.Max(0, Interlocked.Decrement(ref _queuedPendingCount));
        await Dispatcher.InvokeAsync(() =>
        {
            UpdateLogCardStatus(job.CardId, "SENDING");
            ActivityStatusDot.Foreground = TagSending;
            ActivityStatusText.Foreground = TagSending;
            ActivityStatusText.Text = remainingBefore > 0
                ? $"Sending... ({remainingBefore} more queued)"
                : "Sending mail...";
        });

        try
        {
            await _outlook.SendAsync(job.ToAddr, job.CcAddr, job.Subject, job.Body, job.AttachmentPaths, job.IncludeSig);

            bool cloudLogged = false;
            if (!string.IsNullOrEmpty(job.SendType))
            {
                await _sentLog.LogSendAsync(job.SendType, job.Subject);
                cloudLogged = !string.IsNullOrWhiteSpace(_configStore.GetWebappUrl());
            }

            await Dispatcher.InvokeAsync(() =>
            {
                UpdateLogCardStatus(job.CardId, "SUCCESS", cloudLogged);
                _sessionDispatchCount++;
                ActivityKpiText.Text = $"Session: {_sessionDispatchCount}";
                RefreshCounts();
                ShowSendSuccessToast(job.GatePassNum, job.WarehouseName);

                if (!string.IsNullOrEmpty(job.SendType))
                {
                    try { OnGatepassSent?.Invoke(job.SendType, job.GatePassNum, job.WarehouseName); }
                    catch (Exception kpiEx)
                    {
                        System.Diagnostics.Debug.WriteLine($"KPI capture failed: {kpiEx.Message}");
                    }
                }

                int remaining = Volatile.Read(ref _queuedPendingCount);
                if (remaining > 0)
                {
                    ActivityStatusDot.Foreground = TagQueued;
                    ActivityStatusText.Text = $"Queue: {remaining} email(s) pending";
                    ActivityStatusText.Foreground = TagQueued;
                }
                else
                {
                    ActivityStatusDot.Foreground = TagSuccess;
                    ActivityStatusText.Text = "System Ready";
                    ActivityStatusText.Foreground = StatusReadyText;
                }
            });
        }
        catch (Exception ex)
        {
            string err = ex.Message;
            await Dispatcher.InvokeAsync(() =>
            {
                UpdateLogCardStatus(job.CardId, "FAILED", errorDetails: err);
                int remaining = Volatile.Read(ref _queuedPendingCount);
                if (remaining > 0)
                {
                    ActivityStatusDot.Foreground = TagQueued;
                    ActivityStatusText.Text = $"Queue: {remaining} email(s) pending";
                    ActivityStatusText.Foreground = TagQueued;
                }
                else
                {
                    ActivityStatusDot.Foreground = TagError;
                    ActivityStatusText.Text = "Send Failed";
                    ActivityStatusText.Foreground = TagError;
                }
                System.Windows.MessageBox.Show(Window.GetWindow(this), $"Could not send email:\n\n{err}", "Outlook Send Error", MessageBoxButton.OK, MessageBoxImage.Error);
            });
        }
    }

    private void ResetAfterSend()
    {
        ToBox.Text = string.Empty;
        CcBox.Text = string.Empty;
        SubjectBox.Text = string.Empty;
        RefreshTemplateDropdown();
        ClearAttachments();
        _subjectBeforeType = null;
        SelectType(null);
    }

    private void ShowSendSuccessToast(string gatePass, string warehouse)
    {
        ToastText.Text = $"✓ Sent: {gatePass} ({warehouse})";
        _toastTimer.Stop();
        _toastTimer.Start();
    }

    private static (string GatePass, string Warehouse) ExtractGatePassAndWarehouse(string? sendType, string subject, string? templateName)
    {
        string warehouse = "General / Direct";
        if (!string.IsNullOrWhiteSpace(templateName) && templateName != TemplateStore.Placeholder)
            warehouse = templateName.Trim();

        string gatePass = string.Empty;
        if (!string.IsNullOrEmpty(sendType))
        {
            var (numberPart, typePart) = SentLogStore.SplitSubject(sendType, subject);
            if (!string.IsNullOrWhiteSpace(numberPart))
                gatePass = numberPart.Trim();
            if (warehouse == "General / Direct" && !string.IsNullOrWhiteSpace(typePart))
            {
                string cleanedWh = typePart.Replace(sendType, "").Trim().TrimEnd('-').Trim();
                if (!string.IsNullOrEmpty(cleanedWh))
                    warehouse = cleanedWh;
            }
        }

        if (string.IsNullOrEmpty(gatePass))
        {
            int dashIdx = subject.IndexOf(" - ", StringComparison.Ordinal);
            if (dashIdx >= 0)
            {
                gatePass = subject[(dashIdx + 3)..].Trim();
                string prefixPart = subject[..dashIdx].Trim();
                if (warehouse == "General / Direct" && !string.IsNullOrEmpty(prefixPart))
                    warehouse = prefixPart;
            }
            else
            {
                gatePass = string.IsNullOrWhiteSpace(subject) ? "N/A" : subject.Trim();
            }
        }

        return (string.IsNullOrEmpty(gatePass) ? "N/A" : gatePass, string.IsNullOrEmpty(warehouse) ? "General / Direct" : warehouse);
    }

    private void ClearLog_Click(object sender, RoutedEventArgs e)
    {
        _logCards.Clear();
        ActivityRichBox.Document.Blocks.Clear();
    }

    private int CreateLogCard(
        string gatePass,
        string warehouse,
        string? sendType,
        string subject,
        string toAddr,
        string ccAddr,
        IReadOnlyList<string> attachments)
    {
        _cardIdCounter++;
        int cid = _cardIdCounter;
        var doc = ActivityRichBox.Document;
        string nowStr = DateTime.Now.ToString("HH:mm:ss");

        var headerPara = new Paragraph { Margin = new Thickness(0, 2, 0, 1) };
        headerPara.Inlines.Add(new Run($"[{nowStr}] ") { Foreground = TagTime, FontSize = 11, FontWeight = FontWeights.Bold });
        var statusRun = new Run("⏳ Queued") { Foreground = TagQueued, FontSize = 12, FontWeight = FontWeights.Bold };
        headerPara.Inlines.Add(statusRun);
        doc.Blocks.Add(headerPara);

        AddMetadataRow(doc, "  • Gate Pass No : ", gatePass, TagInfo, FontWeights.Bold);
        AddMetadataRow(doc, "  • Warehouse    : ", warehouse, TagVal, FontWeights.Bold);
        if (!string.IsNullOrEmpty(sendType))
            AddMetadataRow(doc, "  • Type         : ", sendType, TagVal, FontWeights.Normal);
        if (!string.IsNullOrEmpty(subject))
            AddMetadataRow(doc, "  • Subject      : ", subject, TagVal, FontWeights.Normal);
        if (!string.IsNullOrEmpty(toAddr))
        {
            string summary = toAddr;
            if (!string.IsNullOrEmpty(ccAddr))
            {
                int ccCount = ccAddr.Split(';', StringSplitOptions.RemoveEmptyEntries).Count(s => !string.IsNullOrWhiteSpace(s));
                summary += $" (+{ccCount} CC)";
            }
            AddMetadataRow(doc, "  • Recipients   : ", summary, TagVal, FontWeights.Normal);
        }

        string attText = attachments.Count > 0 ? $"{attachments.Count} file(s) attached" : "None";
        AddMetadataRow(doc, "  • Attachments  : ", attText, TagVal, FontWeights.Normal);

        var sepPara = new Paragraph(new Run(new string('─', 46)) { Foreground = TagSep })
        {
            Margin = new Thickness(0, 2, 0, 4)
        };
        doc.Blocks.Add(sepPara);
        ActivityRichBox.ScrollToEnd();

        _logCards[cid] = new LogCardRefs(statusRun, sepPara);
        return cid;
    }

    private void UpdateLogCardStatus(int cid, string newStatus, bool cloudLogged = true, string? errorDetails = null)
    {
        if (!_logCards.TryGetValue(cid, out var card))
            return;

        if (newStatus == "SENDING")
        {
            card.StatusRun.Text = "📤 Sending mail...";
            card.StatusRun.Foreground = TagSending;
        }
        else if (newStatus == "SUCCESS")
        {
            card.StatusRun.Text = "✓ SUCCESSFULLY SENT";
            card.StatusRun.Foreground = TagSuccess;

            string cloudTxt = cloudLogged ? "✓ Synced to Google Sheet & Excel" : "Saved to local sent_log.xlsx";
            var p = new Paragraph { Margin = new Thickness(0, 1, 0, 1) };
            p.Inlines.Add(new Run("  • Cloud Sync   : ") { Foreground = TagLabel, FontSize = 11, FontWeight = FontWeights.Bold });
            p.Inlines.Add(new Run(cloudTxt) { Foreground = TagSuccess, FontSize = 12, FontWeight = FontWeights.Bold });
            ActivityRichBox.Document.Blocks.InsertBefore(card.SepParagraph, p);
        }
        else if (newStatus == "FAILED")
        {
            card.StatusRun.Text = "✗ SEND FAILED";
            card.StatusRun.Foreground = TagError;

            if (!string.IsNullOrEmpty(errorDetails))
            {
                var p = new Paragraph { Margin = new Thickness(0, 1, 0, 1) };
                p.Inlines.Add(new Run("  • Error Details: ") { Foreground = TagLabel, FontSize = 11, FontWeight = FontWeights.Bold });
                p.Inlines.Add(new Run(errorDetails) { Foreground = TagError, FontSize = 12, FontWeight = FontWeights.Bold });
                ActivityRichBox.Document.Blocks.InsertBefore(card.SepParagraph, p);
            }
        }
        else
        {
            card.StatusRun.Text = newStatus;
            card.StatusRun.Foreground = TagInfo;
        }

        ActivityRichBox.ScrollToEnd();
    }

    private void AppendActivityLog(string status, string gatePass, string warehouse, string? sendType, string? subject)
    {
        var doc = ActivityRichBox.Document;
        string nowStr = DateTime.Now.ToString("HH:mm:ss");

        var headerPara = new Paragraph { Margin = new Thickness(0, 2, 0, 1) };
        headerPara.Inlines.Add(new Run($"[{nowStr}] ") { Foreground = TagTime, FontSize = 11, FontWeight = FontWeights.Bold });

        var (labelText, labelBrush) = status switch
        {
            "SUCCESS" => ("✓ SUCCESSFULLY SENT", TagSuccess),
            "SENDING" => ("⏳ Sending mail...", TagSending),
            "FAILED" => ("✗ SEND FAILED", TagError),
            "HISTORY" => ("● PREVIOUS DISPATCH", TagInfo),
            _ => (status, TagInfo)
        };
        headerPara.Inlines.Add(new Run(labelText) { Foreground = labelBrush, FontSize = 12, FontWeight = FontWeights.Bold });
        doc.Blocks.Add(headerPara);

        AddMetadataRow(doc, "  • Gate Pass No : ", gatePass, TagInfo, FontWeights.Bold);
        AddMetadataRow(doc, "  • Warehouse    : ", warehouse, TagVal, FontWeights.Bold);
        if (!string.IsNullOrEmpty(sendType))
            AddMetadataRow(doc, "  • Type         : ", sendType, TagVal, FontWeights.Normal);
        if (!string.IsNullOrEmpty(subject))
            AddMetadataRow(doc, "  • Subject      : ", subject, TagVal, FontWeights.Normal);

        var sepPara = new Paragraph(new Run(new string('─', 46)) { Foreground = TagSep })
        {
            Margin = new Thickness(0, 2, 0, 4)
        };
        doc.Blocks.Add(sepPara);
        ActivityRichBox.ScrollToEnd();
    }

    private static void AddMetadataRow(FlowDocument doc, string label, string value, System.Windows.Media.Brush valueBrush, FontWeight weight)
    {
        var p = new Paragraph { Margin = new Thickness(0, 1, 0, 1) };
        p.Inlines.Add(new Run(label) { Foreground = TagLabel, FontSize = 11, FontWeight = FontWeights.Bold });
        p.Inlines.Add(new Run(value) { Foreground = valueBrush, FontSize = 11, FontWeight = weight });
        doc.Blocks.Add(p);
    }
}
