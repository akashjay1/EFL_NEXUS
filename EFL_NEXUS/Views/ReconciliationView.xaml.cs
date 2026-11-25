using System.Diagnostics;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Documents;
using EflNexus.App.Dialogs;
using EflNexus.Core.Infrastructure;
using EflNexus.Core.Reconciliation;
using Control = System.Windows.Controls.Control;
using MediaBrushes = System.Windows.Media.Brushes;
using MediaColor = System.Windows.Media.Color;
using MediaFontFamily = System.Windows.Media.FontFamily;
using SolidBrush = System.Windows.Media.SolidColorBrush;
using UserControl = System.Windows.Controls.UserControl;
using WpfBinding = System.Windows.Data.Binding;

namespace EflNexus.App.Views;

public partial class ReconciliationView : UserControl
{
    private const int PreviewMaxRows = 200;

    private bool _rememberSettings;
    private bool _darkMode;
    private bool _suppressColumnSelectionEvents;

    private List<string> _historyColumns = [];
    private List<string> _planColumns = [];
    private TabularDataset? _historyDfLoaded;
    private TabularDataset? _planDfLoaded;

    private readonly List<TransformConfig> _historyTransforms = [];
    private readonly List<TransformConfig> _planTransforms = [];

    private readonly List<DataGridTextColumn> _historyGridColumns = [];
    private readonly List<DataGridTextColumn> _planGridColumns = [];

    public string? LastOutputFile { get; set; }
    public string? LastReportJobId { get; set; }
    private JobMapEntry? _activeJobContext;
    public JobMapEntry? ActiveJobContext
    {
        get => _activeJobContext;
        set
        {
            _activeJobContext = value;
            UpdatePrimaryKeyColumnsForActiveJob();
        }
    }
    public Action? OnEmbeddedExit { get; set; }

    public string GetEffectiveJobId()
    {
        var queueJob = (QueueCombo.SelectedItem?.ToString() ?? QueueCombo.Text ?? "").Trim();
        if (!string.IsNullOrEmpty(queueJob))
            return queueJob;

        var activeJob = (_activeJobContext?.JobId ?? "").Trim();
        if (!string.IsNullOrEmpty(activeJob))
            return activeJob;

        var reportJob = (LastReportJobId ?? "").Trim();
        if (!string.IsNullOrEmpty(reportJob))
            return reportJob;

        return string.Empty;
    }

    public bool IsActiveJobOut() => ReconciliationEngine.IsOutJobId(GetEffectiveJobId());

    public void UpdatePrimaryKeyColumnsForActiveJob()
    {
        bool isOut = IsActiveJobOut();
        var jobId = GetEffectiveJobId();

        if (HistoryLoadIdLabel is not null)
            HistoryLoadIdLabel.Text = isOut ? "🔑 Primary Key (Order Number):" : "🔑 Primary Key (Load ID):";
        if (PlanLoadIdLabel is not null)
            PlanLoadIdLabel.Text = isOut ? "🔑 Primary Key (Order Number):" : "🔑 Primary Key (Load ID):";

        if (_historyDfLoaded is not null && _historyColumns.Count > 0)
        {
            var (targetPk, _) = ReconciliationEngine.AutoSelectColumns(_historyColumns, isOut);
            if (!string.IsNullOrEmpty(targetPk) && _historyColumns.Contains(targetPk))
            {
                var current = HistoryLoadIdCombo.SelectedItem?.ToString();
                if (!string.Equals(current, targetPk, StringComparison.Ordinal))
                {
                    _suppressColumnSelectionEvents = true;
                    try
                    {
                        HistoryLoadIdCombo.SelectedItem = targetPk;
                    }
                    finally
                    {
                        _suppressColumnSelectionEvents = false;
                    }
                    HighlightPreviewColumns("history");
                    AddLog($"📌 {(isOut ? "OUT job detected" : "Job updated")} ({(string.IsNullOrEmpty(jobId) ? "N/A" : jobId)}): Set Loading History Primary Key to '{targetPk}'", "INFO");
                }
            }
        }

        if (_planDfLoaded is not null && _planColumns.Count > 0)
        {
            var (targetPk, _) = ReconciliationEngine.AutoSelectColumns(_planColumns, isOut);
            if (!string.IsNullOrEmpty(targetPk) && _planColumns.Contains(targetPk))
            {
                var current = PlanLoadIdCombo.SelectedItem?.ToString();
                if (!string.Equals(current, targetPk, StringComparison.Ordinal))
                {
                    _suppressColumnSelectionEvents = true;
                    try
                    {
                        PlanLoadIdCombo.SelectedItem = targetPk;
                    }
                    finally
                    {
                        _suppressColumnSelectionEvents = false;
                    }
                    HighlightPreviewColumns("plan");
                    AddLog($"📌 {(isOut ? "OUT job detected" : "Job updated")} ({(string.IsNullOrEmpty(jobId) ? "N/A" : jobId)}): Set Load Plan Primary Key to '{targetPk}'", "INFO");
                }
            }
        }
    }

    public bool IsEmbedded
    {
        get => SettingsBtn.Visibility != Visibility.Visible;
        set => SettingsBtn.Visibility = value ? Visibility.Collapsed : Visibility.Visible;
    }

    public ReconciliationView()
    {
        InitializeComponent();

        OutputFolderBox.Text = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            "Desktop");
        ArchiveFolderBox.Text = @"C:\Reconciliation\Archive";

        var saved = ReconciliationSettingsStore.Load();
        _rememberSettings = saved.RememberSettings;
        _darkMode = saved.DarkMode;

        if (_rememberSettings)
        {
            if (!string.IsNullOrWhiteSpace(saved.OutputFolder))
                OutputFolderBox.Text = saved.OutputFolder;
            if (!string.IsNullOrWhiteSpace(saved.ArchiveFolder))
                ArchiveFolderBox.Text = saved.ArchiveFolder;
            if (saved.ArchiveAfterProcessing.HasValue)
                ArchiveCheck.IsChecked = saved.ArchiveAfterProcessing.Value;
            if (saved.AutoOpenFile.HasValue)
                AutoOpenCheck.IsChecked = saved.AutoOpenFile.Value;
            if (saved.VerboseLogging.HasValue)
                VerboseLogCheck.IsChecked = saved.VerboseLogging.Value;
        }

        ApplyTheme();
        RefreshJobQueue();
        AddLog("ℹ️ Application started. Select files and click Run Reconciliation.", "INFO");
    }

    public void SaveSettings()
    {
        var data = new ReconciliationSettingsData
        {
            RememberSettings = _rememberSettings,
            DarkMode = _darkMode,
            OutputFolder = OutputFolderBox.Text ?? string.Empty,
            ArchiveFolder = ArchiveFolderBox.Text ?? string.Empty,
            ArchiveAfterProcessing = ArchiveCheck.IsChecked == true,
            AutoOpenFile = AutoOpenCheck.IsChecked == true,
            VerboseLogging = VerboseLogCheck.IsChecked == true
        };
        ReconciliationSettingsStore.Save(data);
    }

    public void OpenSettingsDialog()
    {
        var owner = Window.GetWindow(this);
        var dlg = new ReconciliationSettingsDialog(
            owner,
            _rememberSettings,
            _darkMode,
            remember =>
            {
                _rememberSettings = remember;
                SaveSettings();
            },
            dark =>
            {
                _darkMode = dark;
                ApplyTheme();
                SaveSettings();
            });
        dlg.ShowDialog();
    }

    public void ApplyTheme()
    {
        var bg = new SolidBrush(_darkMode ? MediaColor.FromRgb(0x0B, 0x14, 0x20) : MediaColor.FromRgb(0xFA, 0xF8, 0xF2));
        var panelBg = new SolidBrush(_darkMode ? MediaColor.FromRgb(0x13, 0x23, 0x3A) : MediaColor.FromRgb(0xFF, 0xFF, 0xFF));
        var fg = new SolidBrush(_darkMode ? MediaColor.FromRgb(0xEC, 0xEC, 0xEC) : MediaColor.FromRgb(0x0F, 0x17, 0x2A));
        var subtleFg = new SolidBrush(_darkMode ? MediaColor.FromRgb(0x94, 0xA3, 0xB8) : MediaColor.FromRgb(0x64, 0x74, 0x8B));
        var entryBg = new SolidBrush(_darkMode ? MediaColor.FromRgb(0x16, 0x2E, 0x4C) : MediaColor.FromRgb(0xFF, 0xFF, 0xFF));
        var altRow = new SolidBrush(_darkMode ? MediaColor.FromRgb(0x0F, 0x1B, 0x2D) : MediaColor.FromRgb(0xF8, 0xFA, 0xFC));
        var headingBg = new SolidBrush(_darkMode ? MediaColor.FromRgb(0x16, 0x2E, 0x4C) : MediaColor.FromRgb(0xE2, 0xE8, 0xF0));
        var statusBarBg = new SolidBrush(_darkMode ? MediaColor.FromRgb(0x13, 0x23, 0x3A) : MediaColor.FromRgb(0xF1, 0xF5, 0xF9));

        Background = bg;
        RootGrid.Background = bg;

        foreach (var grp in new[] { QueueGroup, FilesGroup, OutputGroup, OptionsGroup, PreviewGroup, LogGroup })
            grp.Foreground = fg;

        foreach (var tb in new[] { HistoryPathBox, PlanPathBox, PlanDivideBox, OutputFolderBox, ArchiveFolderBox })
        {
            tb.Background = entryBg;
            tb.Foreground = fg;
        }

        foreach (var lbl in new[] { QueueHintText, HistoryInfoText, PlanInfoText, PlanDivideHintText, HistoryPreviewCountText, PlanPreviewCountText, FooterText })
            lbl.Foreground = subtleFg;

        StatusText.Foreground = fg;
        ArchiveCheck.Foreground = fg;
        AutoOpenCheck.Foreground = fg;
        VerboseLogCheck.Foreground = fg;
        HistorySplitCheck.Foreground = fg;
        PlanSplitCheck.Foreground = fg;
        PlanDivideCheck.Foreground = fg;
        PreviewStatusBorder.Background = statusBarBg;
        PreviewStatusText.Foreground = fg;

        foreach (var grid in new[] { HistoryPreviewGrid, PlanPreviewGrid })
        {
            grid.Background = panelBg;
            grid.RowBackground = panelBg;
            grid.AlternatingRowBackground = altRow;
            grid.Foreground = fg;

            var headerStyle = new Style(typeof(DataGridColumnHeader));
            headerStyle.Setters.Add(new Setter(Control.BackgroundProperty, headingBg));
            headerStyle.Setters.Add(new Setter(Control.ForegroundProperty, fg));
            headerStyle.Setters.Add(new Setter(Control.PaddingProperty, new Thickness(6, 4, 6, 4)));
            headerStyle.Setters.Add(new Setter(Control.HorizontalContentAlignmentProperty, System.Windows.HorizontalAlignment.Left));
            grid.ColumnHeaderStyle = headerStyle;
        }

        HighlightPreviewColumns("history");
        HighlightPreviewColumns("plan");
    }

    public void AddLog(string message, string level = "INFO")
    {
        var timestamp = DateTime.Now.ToString("HH:mm:ss");
        var entry = $"[{timestamp}] {message}";
        var color = level switch
        {
            "SUCCESS" => MediaColor.FromRgb(0x2E, 0xCC, 0x71),
            "WARNING" => MediaColor.FromRgb(0xF1, 0xC4, 0x0F),
            "ERROR" => MediaColor.FromRgb(0xE7, 0x4C, 0x3C),
            "DEBUG" => MediaColor.FromRgb(0x34, 0x98, 0xDB),
            _ => MediaColor.FromRgb(0xEC, 0xF0, 0xF1)
        };

        void Append()
        {
            var run = new Run(entry) { Foreground = new SolidBrush(color) };
            LogRichText.Document.Blocks.Add(new Paragraph(run));
            LogRichText.ScrollToEnd();
        }

        if (Dispatcher.CheckAccess())
            Append();
        else
            Dispatcher.BeginInvoke(Append);
    }

    private void ClearLog_Click(object sender, RoutedEventArgs e)
    {
        LogRichText.Document.Blocks.Clear();
        AddLog("📋 Log cleared", "INFO");
    }

    public void RefreshJobQueue()
    {
        try
        {
            var currentJob = (QueueCombo.SelectedItem?.ToString() ?? QueueCombo.Text ?? "").Trim();
            var pending = ReconciliationQueue.ListPendingJobs();
            var jobIds = pending.Select(e => e.JobId).ToList();
            QueueCombo.ItemsSource = jobIds;

            var selected = ReconciliationQueue.ChoosePendingJob(pending, currentJob);
            QueueCombo.SelectedItem = string.IsNullOrEmpty(selected) ? null : selected;

            AddLog($"Queued jobs refreshed: {jobIds.Count} pending", "INFO");
            if (!string.IsNullOrEmpty(selected) && !string.Equals(selected, currentJob, StringComparison.OrdinalIgnoreCase))
                AddLog($"Automatically selected next queued Job ID: {selected}", "INFO");
        }
        catch (Exception ex)
        {
            AddLog($"Could not refresh queued jobs: {ex.Message}", "WARNING");
        }
    }

    private void QueueCombo_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        var jobId = (QueueCombo.SelectedItem?.ToString() ?? "").Trim();
        if (!string.IsNullOrEmpty(jobId))
            AddLog($"Selected queued Job ID: {jobId}", "INFO");

        UpdatePrimaryKeyColumnsForActiveJob();
    }

    private void RefreshQueue_Click(object sender, RoutedEventArgs e) => RefreshJobQueue();

    private void ClearQueue_Click(object sender, RoutedEventArgs e)
    {
        var owner = Window.GetWindow(this);
        var pendingCount = ReconciliationQueue.ListPendingJobs().Count;
        if (pendingCount == 0)
        {
            ShowMsg(owner, "Queue Empty", "There are no queued jobs to clear.", MessageBoxImage.Information);
            return;
        }

        var res = owner is not null && owner.IsVisible
            ? System.Windows.MessageBox.Show(owner, $"Remove all {pendingCount} pending job(s) from the queue?\n\nThis cannot be undone.", "Clear Reconciliation Queue", MessageBoxButton.YesNo, MessageBoxImage.Question)
            : System.Windows.MessageBox.Show($"Remove all {pendingCount} pending job(s) from the queue?\n\nThis cannot be undone.", "Clear Reconciliation Queue", MessageBoxButton.YesNo, MessageBoxImage.Question);

        if (res != MessageBoxResult.Yes)
            return;

        int removed = ReconciliationQueue.ClearQueue();
        QueueCombo.SelectedItem = null;
        RefreshJobQueue();
        AddLog($"Cleared {removed} queued job(s)", "WARNING");
    }

    public (string Client, string JobId, string Gatepass) GetVarianceJobDetails()
    {
        var selectedQueueJob = (QueueCombo.SelectedItem?.ToString() ?? "").Trim();
        var reportJob = !string.IsNullOrEmpty(LastOutputFile) && !string.IsNullOrEmpty(LastReportJobId)
            ? LastReportJobId
            : "";
        var activeJob = (ActiveJobContext?.JobId ?? "").Trim();

        var jobId = !string.IsNullOrEmpty(selectedQueueJob)
            ? selectedQueueJob
            : (!string.IsNullOrEmpty(reportJob) ? reportJob : activeJob);

        if (string.IsNullOrEmpty(jobId))
            return ("", "", "");

        string client = "";
        string gatepass = "";
        if (ActiveJobContext is not null &&
            string.Equals(ActiveJobContext.JobId.Trim(), jobId, StringComparison.OrdinalIgnoreCase))
        {
            client = ActiveJobContext.Client.Trim();
            gatepass = ActiveJobContext.Gatepass.Trim();
        }

        if (string.IsNullOrEmpty(client) || string.IsNullOrEmpty(gatepass))
        {
            var map = JobMapStore.LoadPersistedJobMap();
            if (map.TryGetValue(jobId.ToLowerInvariant(), out var record))
            {
                if (string.IsNullOrEmpty(client)) client = record.Client.Trim();
                if (string.IsNullOrEmpty(gatepass)) gatepass = record.Gatepass.Trim();
            }
        }

        return (client, jobId, gatepass);
    }

    public string GetVarianceSubject()
    {
        var (client, jobId, gatepass) = GetVarianceJobDetails();
        return (!string.IsNullOrEmpty(client) && !string.IsNullOrEmpty(jobId) && !string.IsNullOrEmpty(gatepass))
            ? $"{client} - {jobId} - {gatepass}"
            : string.Empty;
    }

    private void SendVariance_Click(object sender, RoutedEventArgs e)
    {
        var selectedJob = (QueueCombo.SelectedItem?.ToString() ?? "").Trim();
        var reportJob = LastReportJobId ?? "";
        var attachment = LastOutputFile;
        if (!string.IsNullOrEmpty(selectedJob) &&
            !string.Equals(selectedJob, reportJob, StringComparison.OrdinalIgnoreCase))
        {
            attachment = null;
        }

        var dlg = new SendVarianceDialog(
            Window.GetWindow(this),
            attachment,
            _darkMode,
            GetVarianceJobDetails,
            AddLog);
        dlg.ShowDialog();
    }

    private void OpenSettings_Click(object sender, RoutedEventArgs e) => OpenSettingsDialog();

    private void BrowseHistory_Click(object sender, RoutedEventArgs e)
    {
        var dlg = new Microsoft.Win32.OpenFileDialog
        {
            Title = "Select Loading History File",
            Filter = "Excel files (*.xlsx;*.xls;*.xlsm;*.xlsb)|*.xlsx;*.xls;*.xlsm;*.xlsb|All files (*.*)|*.*"
        };
        if (dlg.ShowDialog(Window.GetWindow(this)) != true)
            return;

        LoadExcelInput("history", dlg.FileName);
    }

    private void BrowsePlan_Click(object sender, RoutedEventArgs e)
    {
        var dlg = new Microsoft.Win32.OpenFileDialog
        {
            Title = "Select Load Plan File",
            Filter = "Excel files (*.xlsx;*.xls;*.xlsm;*.xlsb)|*.xlsx;*.xls;*.xlsm;*.xlsb|All files (*.*)|*.*"
        };
        if (dlg.ShowDialog(Window.GetWindow(this)) != true)
            return;

        LoadExcelInput("plan", dlg.FileName);
    }

    private void LoadExcelInput(string fileType, string filePath)
    {
        bool isHistory = fileType == "history";
        var displayName = Path.GetFileName(filePath);
        if (displayName.Length > 50)
            displayName = displayName[..25] + "..." + displayName[^10..];

        var sizeStr = FormatFileSize(filePath);
        if (isHistory)
        {
            HistoryPathBox.Text = filePath;
            HistoryInfoText.Text = $"📄 {displayName} ({sizeStr})";
            AddLog($"📂 Selected History file: {Path.GetFileName(filePath)}", "INFO");
        }
        else
        {
            PlanPathBox.Text = filePath;
            PlanInfoText.Text = $"📄 {displayName} ({sizeStr})";
            AddLog($"📂 Selected Plan file: {Path.GetFileName(filePath)}", "INFO");
        }

        ErrorText.Text = string.Empty;

        var (valid, msg) = ExcelReaderHelper.ValidateExcelFile(filePath);
        if (!valid)
        {
            ErrorText.Text = $"⚠️ {msg}";
            AddLog($"⚠️ {(isHistory ? "History" : "Plan")} file validation failed: {msg}", "WARNING");
            return;
        }

        try
        {
            var df = ExcelReaderHelper.ReadExcel(filePath);
            if (df.IsEmpty || df.ColumnCount == 0)
            {
                AddLog("⚠️ File appears to be empty", "WARNING");
                ErrorText.Text = "⚠️ Could not read columns from file";
                return;
            }

            var cols = df.Columns.ToList();
            bool isOut = IsActiveJobOut();
            var (autoLoadId, autoQty) = ReconciliationEngine.AutoSelectColumns(cols, isOut);

            if (isHistory)
            {
                _historyTransforms.Clear();
                _historyDfLoaded = df;
                _historyColumns = cols;
                if (HistoryLoadIdLabel is not null)
                    HistoryLoadIdLabel.Text = isOut ? "🔑 Primary Key (Order Number):" : "🔑 Primary Key (Load ID):";
                SetColumnCombos("history", cols, autoLoadId, autoQty);
                HistorySplitCombo.SelectedItem = null;
                HistoryConcatBtn.IsEnabled = true;
                if (HistorySplitCheck.IsChecked == true)
                    HistorySplitCombo.IsEnabled = true;
                AddLog($"✅ Loaded {cols.Count} columns: {string.Join(", ", cols.Take(5))}{(cols.Count > 5 ? "..." : "")}", "INFO");
                AddLog($"📊 Loaded {cols.Count} columns from History file", "INFO");
                if (isOut)
                    AddLog($"📌 OUT job detected ({GetEffectiveJobId()}): Set Primary Key to '{autoLoadId}' instead of Load Id", "INFO");
                PopulatePreview("history");
                AddLog("👁️ Loading History preview updated", "INFO");
            }
            else
            {
                _planTransforms.Clear();
                _planDfLoaded = df;
                _planColumns = cols;
                if (PlanLoadIdLabel is not null)
                    PlanLoadIdLabel.Text = isOut ? "🔑 Primary Key (Order Number):" : "🔑 Primary Key (Load ID):";
                SetColumnCombos("plan", cols, autoLoadId, autoQty);
                PlanSplitCombo.SelectedItem = null;
                PlanConcatBtn.IsEnabled = true;
                if (PlanSplitCheck.IsChecked == true)
                    PlanSplitCombo.IsEnabled = true;
                AddLog($"✅ Loaded {cols.Count} columns: {string.Join(", ", cols.Take(5))}{(cols.Count > 5 ? "..." : "")}", "INFO");
                AddLog($"📊 Loaded {cols.Count} columns from Plan file", "INFO");
                if (isOut)
                    AddLog($"📌 OUT job detected ({GetEffectiveJobId()}): Set Primary Key to '{autoLoadId}' instead of Load Id", "INFO");
                PopulatePreview("plan");
                AddLog("👁️ Load Plan preview updated", "INFO");
            }
        }
        catch (Exception ex)
        {
            AddLog($"⚠️ Could not read column names: {ex.Message}", "WARNING");
            ErrorText.Text = "⚠️ Could not read columns from file";
        }
    }

    private void SetColumnCombos(string fileType, List<string> cols, string selectedLoadId, string selectedQty)
    {
        _suppressColumnSelectionEvents = true;
        try
        {
            if (fileType == "history")
            {
                HistoryLoadIdCombo.ItemsSource = cols;
                HistoryQtyCombo.ItemsSource = cols;
                HistorySplitCombo.ItemsSource = cols;
                HistoryLoadIdCombo.SelectedItem = cols.Contains(selectedLoadId) ? selectedLoadId : null;
                HistoryQtyCombo.SelectedItem = cols.Contains(selectedQty) ? selectedQty : null;
            }
            else
            {
                PlanLoadIdCombo.ItemsSource = cols;
                PlanQtyCombo.ItemsSource = cols;
                PlanSplitCombo.ItemsSource = cols;
                PlanLoadIdCombo.SelectedItem = cols.Contains(selectedLoadId) ? selectedLoadId : null;
                PlanQtyCombo.SelectedItem = cols.Contains(selectedQty) ? selectedQty : null;
            }
        }
        finally
        {
            _suppressColumnSelectionEvents = false;
        }
    }

    private void HistoryColCombo_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!_suppressColumnSelectionEvents)
            HighlightPreviewColumns("history");
    }

    private void PlanColCombo_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!_suppressColumnSelectionEvents)
            HighlightPreviewColumns("plan");
    }

    private void PopulatePreview(string fileType)
    {
        bool isHistory = fileType == "history";
        var grid = isHistory ? HistoryPreviewGrid : PlanPreviewGrid;
        var df = isHistory ? _historyDfLoaded : _planDfLoaded;
        var countText = isHistory ? HistoryPreviewCountText : PlanPreviewCountText;
        var gridCols = isHistory ? _historyGridColumns : _planGridColumns;

        grid.ItemsSource = null;
        grid.Columns.Clear();
        gridCols.Clear();

        if (df is null || df.IsEmpty)
        {
            countText.Text = "No data loaded";
            return;
        }

        for (int c = 0; c < df.ColumnCount; c++)
        {
            var colName = df.Columns[c];
            int dataMax = colName.Length;
            int inspectRows = Math.Min(df.RowCount, PreviewMaxRows);
            for (int r = 0; r < inspectRows; r++)
            {
                var sLen = TabularDataset.CellToString(df.Rows[r][c]).Length;
                if (sLen > dataMax) dataMax = sLen;
            }
            double headerW = colName.Length * 7.2 + 24;
            double dataW = Math.Min(220, dataMax * 6.8 + 18);
            double width = Math.Max(60, Math.Max(headerW, dataW));

            var col = new DataGridTextColumn
            {
                Header = colName,
                Binding = new WpfBinding($"[{c}]"),
                Width = new DataGridLength(width, DataGridLengthUnitType.Pixel)
            };
            grid.Columns.Add(col);
            gridCols.Add(col);
        }

        int shown = Math.Min(PreviewMaxRows, df.RowCount);
        var previewRows = new List<string[]>(shown);
        for (int r = 0; r < shown; r++)
        {
            var src = df.Rows[r];
            var vals = new string[df.ColumnCount];
            for (int c = 0; c < df.ColumnCount; c++)
                vals[c] = c < src.Length ? TabularDataset.CellToString(src[c]) : string.Empty;
            previewRows.Add(vals);
        }

        grid.ItemsSource = previewRows;
        countText.Text = df.RowCount > shown
            ? $"Showing {shown} of {df.RowCount} rows"
            : $"{df.RowCount} rows";

        HighlightPreviewColumns(fileType);
    }

    private void HighlightPreviewColumns(string fileType)
    {
        bool isHistory = fileType == "history";
        var cols = isHistory ? _historyColumns : _planColumns;
        var gridCols = isHistory ? _historyGridColumns : _planGridColumns;
        var loadIdCol = isHistory
            ? (HistoryLoadIdCombo.SelectedItem?.ToString() ?? "")
            : (PlanLoadIdCombo.SelectedItem?.ToString() ?? "");
        var qtyCol = isHistory
            ? (HistoryQtyCombo.SelectedItem?.ToString() ?? "")
            : (PlanQtyCombo.SelectedItem?.ToString() ?? "");

        if (gridCols.Count == 0 || cols.Count == 0)
            return;

        var fg = new SolidBrush(_darkMode ? MediaColor.FromRgb(0xEC, 0xEC, 0xEC) : MediaColor.FromRgb(0x0F, 0x17, 0x2A));
        var amberBg = new SolidBrush(MediaColor.FromRgb(0xF5, 0x9E, 0x0B));
        var greenBg = new SolidBrush(MediaColor.FromRgb(0x10, 0xB9, 0x81));

        for (int i = 0; i < gridCols.Count && i < cols.Count; i++)
        {
            var colName = cols[i];
            if (colName == loadIdCol && colName == qtyCol && !string.IsNullOrEmpty(colName))
            {
                gridCols[i].Header = MakeBadgeHeader($"🔑🔢 {colName}", amberBg);
            }
            else if (colName == loadIdCol && !string.IsNullOrEmpty(loadIdCol))
            {
                gridCols[i].Header = MakeBadgeHeader($"🔑 {colName}", amberBg);
            }
            else if (colName == qtyCol && !string.IsNullOrEmpty(qtyCol))
            {
                gridCols[i].Header = MakeBadgeHeader($"🔢 {colName}", greenBg);
            }
            else
            {
                gridCols[i].Header = new TextBlock
                {
                    Text = colName,
                    Foreground = fg,
                    FontFamily = new MediaFontFamily("Segoe UI"),
                    FontSize = 12
                };
            }
        }
    }

    private static Border MakeBadgeHeader(string text, SolidBrush bg)
        => new()
        {
            Background = bg,
            CornerRadius = new CornerRadius(3),
            Padding = new Thickness(7, 2, 7, 2),
            Child = new TextBlock
            {
                Text = text,
                Foreground = MediaBrushes.White,
                FontWeight = FontWeights.Bold,
                FontFamily = new MediaFontFamily("Segoe UI"),
                FontSize = 11
            }
        };

    private void HistoryPreviewGrid_SelectionChanged(object sender, SelectionChangedEventArgs e)
        => UpdatePreviewRowStatus(isHistory: true);

    private void PlanPreviewGrid_SelectionChanged(object sender, SelectionChangedEventArgs e)
        => UpdatePreviewRowStatus(isHistory: false);

    private void UpdatePreviewRowStatus(bool isHistory)
    {
        var grid = isHistory ? HistoryPreviewGrid : PlanPreviewGrid;
        if (grid.SelectedItem is not string[] values || grid.SelectedIndex < 0)
            return;

        var cols = isHistory ? _historyColumns : _planColumns;
        var loadIdCol = isHistory
            ? (HistoryLoadIdCombo.SelectedItem?.ToString() ?? "")
            : (PlanLoadIdCombo.SelectedItem?.ToString() ?? "");
        var qtyCol = isHistory
            ? (HistoryQtyCombo.SelectedItem?.ToString() ?? "")
            : (PlanQtyCombo.SelectedItem?.ToString() ?? "");
        var source = isHistory ? "Loading History" : "Load Plan";

        var pairs = new List<string>();
        for (int i = 0; i < cols.Count && i < values.Length; i++)
        {
            var col = cols[i];
            var marker = col == loadIdCol ? "🔑 " : (col == qtyCol ? "🔢 " : "");
            pairs.Add($"{marker}{col}: {values[i]}");
        }

        PreviewStatusText.Text = $"📌 {source} — Row {grid.SelectedIndex + 1}: " + string.Join(" | ", pairs);
    }

    private void RefreshHistoryPreview_Click(object sender, RoutedEventArgs e)
    {
        if (_historyDfLoaded is null)
        {
            ShowMsg(Window.GetWindow(this), "No Data", "Please load a Loading History file first.", MessageBoxImage.Information);
            return;
        }
        PopulatePreview("history");
        AddLog("🔄 Loading History preview refreshed", "INFO");
    }

    private void RefreshPlanPreview_Click(object sender, RoutedEventArgs e)
    {
        if (_planDfLoaded is null)
        {
            ShowMsg(Window.GetWindow(this), "No Data", "Please load a Load Plan file first.", MessageBoxImage.Information);
            return;
        }
        PopulatePreview("plan");
        AddLog("🔄 Load Plan preview refreshed", "INFO");
    }

    private void HistorySplitCheck_Changed(object sender, RoutedEventArgs e)
    {
        bool enabled = HistorySplitCheck.IsChecked == true;
        HistorySplitCombo.IsEnabled = enabled;
        HistoryConfigureSplitBtn.IsEnabled = enabled;
        if (enabled)
            HistorySplitCombo.ItemsSource = _historyColumns;
        else
            HistorySplitCombo.SelectedItem = null;
    }

    private void PlanSplitCheck_Changed(object sender, RoutedEventArgs e)
    {
        bool enabled = PlanSplitCheck.IsChecked == true;
        PlanSplitCombo.IsEnabled = enabled;
        PlanConfigureSplitBtn.IsEnabled = enabled;
        if (enabled)
            PlanSplitCombo.ItemsSource = _planColumns;
        else
            PlanSplitCombo.SelectedItem = null;
    }

    private void PlanDivideCheck_Changed(object sender, RoutedEventArgs e)
    {
        bool enabled = PlanDivideCheck.IsChecked == true;
        PlanDivideBox.IsEnabled = enabled;
        if (enabled && string.IsNullOrWhiteSpace(PlanDivideBox.Text))
            PlanDivideBox.Text = "1";
    }

    private void HistoryConfigureSplit_Click(object sender, RoutedEventArgs e) => ConfigureSplit("history");
    private void PlanConfigureSplit_Click(object sender, RoutedEventArgs e) => ConfigureSplit("plan");

    private void ConfigureSplit(string fileType)
    {
        var owner = Window.GetWindow(this);
        bool isHistory = fileType == "history";
        var df = isHistory ? _historyDfLoaded : _planDfLoaded;
        var splitCol = isHistory
            ? (HistorySplitCombo.SelectedItem?.ToString() ?? "")
            : (PlanSplitCombo.SelectedItem?.ToString() ?? "");

        if (string.IsNullOrEmpty(splitCol))
        {
            ShowMsg(owner, "Warning", "Please select a column to split", MessageBoxImage.Warning);
            return;
        }
        if (df is null)
        {
            ShowMsg(owner, "Error", "Please load a file first", MessageBoxImage.Error);
            return;
        }

        int colIdx = df.IndexOfColumn(splitCol);
        if (colIdx < 0)
        {
            ShowMsg(owner, "Error", $"Column '{splitCol}' not found", MessageBoxImage.Error);
            return;
        }

        var colData = df.Rows.Select(r => colIdx < r.Length ? TabularDataset.CellToString(r[colIdx]) : string.Empty).ToList();
        var title = $"Split {(isHistory ? "History" : "Plan")} Column: {splitCol}";
        var dlg = new TextToColumnsDialog(owner, title, colData, splitCol, _darkMode);
        if (dlg.ShowDialog() != true || dlg.Widths.Count == 0)
            return;

        AddLog($"✅ {(isHistory ? "History" : "Plan")} text-to-columns configured: {dlg.Widths.Count} columns", "SUCCESS");
        AddLog($"   Widths: [{string.Join(", ", dlg.Widths)}]", "INFO");

        var newDf = ReconciliationEngine.ApplyTextToColumns(df, splitCol, dlg.Widths, isHistory ? "History" : "Plan", AddLog);
        var cfg = new TransformConfig
        {
            Type = "split",
            Column = splitCol,
            Widths = dlg.Widths.ToList()
        };

        var newCols = newDf.Columns.ToList();
        var part2 = $"{splitCol}_part_2";
        var autoLoadId = newCols.Contains(part2)
            ? part2
            : (newCols.Count > 1 ? newCols[1] : (newCols.FirstOrDefault() ?? ""));

        if (isHistory)
        {
            _historyTransforms.Add(cfg);
            _historyDfLoaded = newDf;
            _historyColumns = newCols;
            var currentQty = HistoryQtyCombo.SelectedItem?.ToString() ?? "";
            SetColumnCombos("history", newCols, autoLoadId, newCols.Contains(currentQty) ? currentQty : "");
            PopulatePreview("history");
            AddLog("👁️ Loading History preview updated with split columns at beginning", "INFO");
        }
        else
        {
            _planTransforms.Add(cfg);
            _planDfLoaded = newDf;
            _planColumns = newCols;
            var currentQty = PlanQtyCombo.SelectedItem?.ToString() ?? "";
            SetColumnCombos("plan", newCols, autoLoadId, newCols.Contains(currentQty) ? currentQty : "");
            PopulatePreview("plan");
            AddLog("👁️ Load Plan preview updated with split columns at beginning", "INFO");
        }
    }

    private void HistoryConcat_Click(object sender, RoutedEventArgs e) => OpenConcatenateDialog("history");
    private void PlanConcat_Click(object sender, RoutedEventArgs e) => OpenConcatenateDialog("plan");

    private void OpenConcatenateDialog(string fileType)
    {
        var owner = Window.GetWindow(this);
        bool isHistory = fileType == "history";
        var df = isHistory ? _historyDfLoaded : _planDfLoaded;
        if (df is null || df.IsEmpty)
        {
            ShowMsg(owner, "Error", "Please load a file first", MessageBoxImage.Error);
            return;
        }

        var friendly = isHistory ? "Loading History" : "Load Plan";
        var dlg = new ConcatenateColumnsDialog(owner, $"Concatenate Columns - {friendly}", df, _darkMode);
        if (dlg.ShowDialog() != true || dlg.ResultConfig is null)
            return;

        var cfg = dlg.ResultConfig;
        var newDf = ReconciliationEngine.ApplyColumnConcatenation(
            df, cfg.Columns, cfg.Separator, cfg.NewColumnName, cfg.DropOriginals, friendly, AddLog);
        var newCols = newDf.Columns.ToList();

        if (isHistory)
        {
            _historyTransforms.Add(cfg);
            _historyDfLoaded = newDf;
            _historyColumns = newCols;
            var qty = HistoryQtyCombo.SelectedItem?.ToString() ?? "";
            var split = HistorySplitCombo.SelectedItem?.ToString() ?? "";
            SetColumnCombos("history", newCols, cfg.NewColumnName, newCols.Contains(qty) ? qty : "");
            HistorySplitCombo.SelectedItem = newCols.Contains(split) ? split : null;
            PopulatePreview("history");
            AddLog("👁️ Loading History preview updated with concatenated column at beginning", "INFO");
        }
        else
        {
            _planTransforms.Add(cfg);
            _planDfLoaded = newDf;
            _planColumns = newCols;
            var qty = PlanQtyCombo.SelectedItem?.ToString() ?? "";
            var split = PlanSplitCombo.SelectedItem?.ToString() ?? "";
            SetColumnCombos("plan", newCols, cfg.NewColumnName, newCols.Contains(qty) ? qty : "");
            PlanSplitCombo.SelectedItem = newCols.Contains(split) ? split : null;
            PopulatePreview("plan");
            AddLog("👁️ Load Plan preview updated with concatenated column at beginning", "INFO");
        }
    }

    private void BrowseOutputFolder_Click(object sender, RoutedEventArgs e)
    {
        var dlg = new Microsoft.Win32.OpenFolderDialog { Title = "Select Output Folder" };
        if (dlg.ShowDialog(Window.GetWindow(this)) == true)
        {
            OutputFolderBox.Text = dlg.FolderName;
            AddLog($"📁 Output folder set to: {dlg.FolderName}", "INFO");
        }
    }

    private void BrowseArchiveFolder_Click(object sender, RoutedEventArgs e)
    {
        var dlg = new Microsoft.Win32.OpenFolderDialog { Title = "Select Archive Folder" };
        if (dlg.ShowDialog(Window.GetWindow(this)) == true)
        {
            ArchiveFolderBox.Text = dlg.FolderName;
            AddLog($"📁 Archive folder set to: {dlg.FolderName}", "INFO");
        }
    }

    private void ClearAll_Click(object sender, RoutedEventArgs e)
    {
        QueueCombo.SelectedItem = null;
        HistoryPathBox.Text = string.Empty;
        PlanPathBox.Text = string.Empty;
        HistoryInfoText.Text = "No file selected";
        PlanInfoText.Text = "No file selected";
        ErrorText.Text = string.Empty;

        if (HistoryLoadIdLabel is not null)
            HistoryLoadIdLabel.Text = "🔑 Primary Key (Load ID):";
        if (PlanLoadIdLabel is not null)
            PlanLoadIdLabel.Text = "🔑 Primary Key (Load ID):";

        _suppressColumnSelectionEvents = true;
        try
        {
            HistoryLoadIdCombo.ItemsSource = null;
            HistoryQtyCombo.ItemsSource = null;
            HistorySplitCombo.ItemsSource = null;
            PlanLoadIdCombo.ItemsSource = null;
            PlanQtyCombo.ItemsSource = null;
            PlanSplitCombo.ItemsSource = null;
        }
        finally
        {
            _suppressColumnSelectionEvents = false;
        }

        HistorySplitCheck.IsChecked = false;
        PlanSplitCheck.IsChecked = false;
        PlanDivideCheck.IsChecked = false;
        PlanDivideBox.Text = "1";
        PlanDivideBox.IsEnabled = false;

        _historyColumns.Clear();
        _planColumns.Clear();
        _historyTransforms.Clear();
        _planTransforms.Clear();
        _historyDfLoaded = null;
        _planDfLoaded = null;

        HistoryConcatBtn.IsEnabled = false;
        PlanConcatBtn.IsEnabled = false;
        HistorySplitCombo.IsEnabled = false;
        PlanSplitCombo.IsEnabled = false;
        HistoryConfigureSplitBtn.IsEnabled = false;
        PlanConfigureSplitBtn.IsEnabled = false;

        OutputFolderBox.Text = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            "Desktop");
        ArchiveFolderBox.Text = @"C:\Reconciliation\Archive";

        ReconProgressBar.Value = 0;
        StatusText.Text = "Ready";
        RunBtn.IsEnabled = true;

        HistoryPreviewGrid.ItemsSource = null;
        HistoryPreviewGrid.Columns.Clear();
        _historyGridColumns.Clear();
        PlanPreviewGrid.ItemsSource = null;
        PlanPreviewGrid.Columns.Clear();
        _planGridColumns.Clear();

        HistoryPreviewCountText.Text = "No data loaded";
        PlanPreviewCountText.Text = "No data loaded";
        PreviewStatusText.Text = "👆 Click a row in either preview below to see its values here";

        LogRichText.Document.Blocks.Clear();
        AddLog("📋 Log cleared", "INFO");
        AddLog("🧹 All fields cleared", "INFO");
    }

    private async void RunReconciliation_Click(object sender, RoutedEventArgs e)
    {
        var owner = Window.GetWindow(this);
        var historyPath = (HistoryPathBox.Text ?? "").Trim();
        var planPath = (PlanPathBox.Text ?? "").Trim();
        var historyLoadIdCol = (HistoryLoadIdCombo.SelectedItem?.ToString() ?? "").Trim();
        var historyQtyCol = (HistoryQtyCombo.SelectedItem?.ToString() ?? "").Trim();
        var planLoadIdCol = (PlanLoadIdCombo.SelectedItem?.ToString() ?? "").Trim();
        var planQtyCol = (PlanQtyCombo.SelectedItem?.ToString() ?? "").Trim();

        if (string.IsNullOrEmpty(historyPath))
        {
            ErrorText.Text = "⚠️ Please select a Loading History file";
            ShowMsg(owner, "Error", "Please select a Loading History file", MessageBoxImage.Error);
            return;
        }
        if (string.IsNullOrEmpty(planPath))
        {
            ErrorText.Text = "⚠️ Please select a Load Plan file";
            ShowMsg(owner, "Error", "Please select a Load Plan file", MessageBoxImage.Error);
            return;
        }
        if (string.IsNullOrEmpty(historyLoadIdCol))
        {
            ErrorText.Text = "⚠️ Please select a Load ID column for History file";
            ShowMsg(owner, "Error", "Please select a Load ID column for the History file", MessageBoxImage.Error);
            return;
        }
        if (string.IsNullOrEmpty(historyQtyCol))
        {
            ErrorText.Text = "⚠️ Please select a Quantity column for History file";
            ShowMsg(owner, "Error", "Please select a Quantity column for the History file", MessageBoxImage.Error);
            return;
        }
        if (string.IsNullOrEmpty(planLoadIdCol))
        {
            ErrorText.Text = "⚠️ Please select a Load ID column for Plan file";
            ShowMsg(owner, "Error", "Please select a Load ID column for the Plan file", MessageBoxImage.Error);
            return;
        }
        if (string.IsNullOrEmpty(planQtyCol))
        {
            ErrorText.Text = "⚠️ Please select a Quantity column for Plan file";
            ShowMsg(owner, "Error", "Please select a Quantity column for the Plan file", MessageBoxImage.Error);
            return;
        }

        bool hSplitOn = HistorySplitCheck.IsChecked == true;
        if (hSplitOn && !_historyTransforms.Any(t => t.Type == "split") &&
            string.IsNullOrWhiteSpace(HistorySplitCombo.SelectedItem?.ToString()))
        {
            ErrorText.Text = "⚠️ Please select a column to split for History";
            ShowMsg(owner, "Error", "Please select a column to split for the History file", MessageBoxImage.Error);
            return;
        }

        bool pSplitOn = PlanSplitCheck.IsChecked == true;
        if (pSplitOn && !_planTransforms.Any(t => t.Type == "split") &&
            string.IsNullOrWhiteSpace(PlanSplitCombo.SelectedItem?.ToString()))
        {
            ErrorText.Text = "⚠️ Please select a column to split for Plan";
            ShowMsg(owner, "Error", "Please select a column to split for the Plan file", MessageBoxImage.Error);
            return;
        }

        bool divideOn = PlanDivideCheck.IsChecked == true;
        double divideVal = 1.0;
        if (divideOn)
        {
            if (!double.TryParse((PlanDivideBox.Text ?? "").Trim(), out divideVal))
            {
                ErrorText.Text = "⚠️ Please enter a valid number to divide Plan Qty by";
                ShowMsg(owner, "Error", "Please enter a valid number to divide the Plan Quantity by", MessageBoxImage.Error);
                return;
            }
            if (divideVal == 0)
            {
                ErrorText.Text = "⚠️ Divide value cannot be zero";
                ShowMsg(owner, "Error", "The number to divide Plan Qty by cannot be zero", MessageBoxImage.Error);
                return;
            }
        }

        foreach (var (fp, ft) in new[] { (historyPath, "History"), (planPath, "Plan") })
        {
            var (valid, msg) = ExcelReaderHelper.ValidateExcelFile(fp);
            if (!valid)
            {
                ErrorText.Text = $"⚠️ {ft} file: {msg}";
                ShowMsg(owner, "Error", $"Invalid {ft} file:\n{msg}", MessageBoxImage.Error);
                return;
            }
        }

        ErrorText.Text = string.Empty;

        try
        {
            using var p = Process.Start(new ProcessStartInfo("taskkill", "/F /IM EXCEL.EXE")
            {
                CreateNoWindow = true,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true
            });
            p?.WaitForExit(1500);
            AddLog("📌 Closed any open Excel instances", "DEBUG");
        }
        catch { }

        var request = new ReconciliationRequest
        {
            HistoryFilePath = historyPath,
            PlanFilePath = planPath,
            HistoryLoadIdCol = historyLoadIdCol,
            HistoryQtyCol = historyQtyCol,
            PlanLoadIdCol = planLoadIdCol,
            PlanQtyCol = planQtyCol,
            HistorySplitEnabled = hSplitOn,
            PlanSplitEnabled = pSplitOn,
            HistoryTransforms = _historyTransforms.ToList(),
            PlanTransforms = _planTransforms.ToList(),
            PlanDivideEnabled = divideOn,
            PlanDivideValue = divideVal,
            OutputFolder = (OutputFolderBox.Text ?? "").Trim(),
            ArchiveFolder = (ArchiveFolderBox.Text ?? "").Trim(),
            ArchiveFiles = ArchiveCheck.IsChecked == true,
            QueuedJobId = (QueueCombo.SelectedItem?.ToString() ?? _activeJobContext?.JobId ?? "").Trim()
        };

        bool autoOpen = AutoOpenCheck.IsChecked == true;
        RunBtn.IsEnabled = false;
        AddLog("🚀 Starting reconciliation process...", "INFO");

        try
        {
            var result = await Task.Run(() => ReconciliationEngine.ExecuteReconciliation(
                request,
                (pct, status) => Dispatcher.BeginInvoke(() =>
                {
                    ReconProgressBar.Value = pct;
                    StatusText.Text = status;
                }),
                AddLog));

            LastOutputFile = result.OutputFilePath;
            LastReportJobId = result.SelectedJobId;

            if (!string.IsNullOrEmpty(result.SelectedJobId) && result.FormattingSucceeded)
            {
                var current = (QueueCombo.SelectedItem?.ToString() ?? "").Trim();
                if (string.Equals(current, result.SelectedJobId, StringComparison.OrdinalIgnoreCase))
                    QueueCombo.SelectedItem = null;
                RefreshJobQueue();
            }

            if (autoOpen && File.Exists(result.OutputFilePath))
            {
                try
                {
                    Process.Start(new ProcessStartInfo(result.OutputFilePath) { UseShellExecute = true });
                    AddLog("📂 Opened result file", "INFO");
                }
                catch
                {
                    AddLog("⚠️ Could not auto-open file", "WARNING");
                }
            }

            ShowMsg(owner, "Success", result.SummaryText, MessageBoxImage.Information);
        }
        catch (Exception ex)
        {
            var msg = $"An error occurred:\n{ex.Message}";
            AddLog($"❌ {msg}", "ERROR");
            ErrorText.Text = $"⚠️ {ex.Message}";
            ShowMsg(owner, "Error", msg, MessageBoxImage.Error);
        }
        finally
        {
            RunBtn.IsEnabled = true;
            StatusText.Text = "Ready";
        }
    }

    private void Exit_Click(object sender, RoutedEventArgs e)
    {
        SaveSettings();
        if (IsEmbedded)
            OnEmbeddedExit?.Invoke();
        else
            Window.GetWindow(this)?.Close();
    }

    private static string FormatFileSize(string path)
    {
        long size = new FileInfo(path).Length;
        if (size < 1024) return $"{size} B";
        if (size < 1024 * 1024) return $"{size / 1024.0:F1} KB";
        return $"{size / (1024.0 * 1024.0):F1} MB";
    }

    private static void ShowMsg(Window? owner, string title, string text, MessageBoxImage icon)
    {
        if (owner is not null && owner.IsVisible)
            System.Windows.MessageBox.Show(owner, text, title, MessageBoxButton.OK, icon);
        else
            System.Windows.MessageBox.Show(text, title, MessageBoxButton.OK, icon);
    }
}
