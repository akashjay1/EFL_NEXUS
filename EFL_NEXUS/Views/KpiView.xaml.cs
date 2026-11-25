using System.Globalization;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using EflNexus.Core.Infrastructure;
using EflNexus.Core.Kpi;
using MediaBrushes = System.Windows.Media.Brushes;
using MediaColor = System.Windows.Media.Color;

namespace EflNexus.App.Views;

public partial class KpiView : System.Windows.Controls.UserControl
{
    public const string MsgSuccessColor = "#059669";
    public const string MsgErrorColor = "#DC2626";
    public const string MsgInfoColor = "#0284C7";
    public const string MsgWarningColor = "#D97706";
    private const string MsgMutedColor = "#64748B";
    private const string AuroraCyanHex = "#00E5FF";

    private sealed record KpiActivityEntry(string Timestamp, string Category, string Level, string Message);

    private static readonly object ActivityLogLock = new();
    private static readonly List<KpiActivityEntry> SharedActivityLogs = [];

    private static readonly SolidColorBrush InputTextBrush = new(MediaColor.FromRgb(0x0F, 0x17, 0x2A));
    private static readonly SolidColorBrush PlaceholderBrush = new(MediaColor.FromRgb(0x94, 0xA3, 0xB8));
    private static readonly SolidColorBrush InputBorderBrush = new(MediaColor.FromRgb(0xCB, 0xD5, 0xE1));
    private static readonly SolidColorBrush InputFocusBorderBrush = new(MediaColor.FromRgb(0x00, 0xB7, 0xFF));
    private static readonly SolidColorBrush CardBorderBrush = new(MediaColor.FromRgb(0xE2, 0xE8, 0xF0));
    private static readonly SolidColorBrush SubmitBg = new(MediaColor.FromRgb(0x10, 0xB9, 0x81));
    private static readonly SolidColorBrush DeleteBg = new(MediaColor.FromRgb(0xEF, 0x44, 0x44));
    private static readonly SolidColorBrush SiteCountBg = new(MediaColor.FromRgb(0xF8, 0xFA, 0xFC));
    private static readonly SolidColorBrush DayTotalBg = new(MediaColor.FromRgb(0xEC, 0xFD, 0xF5));
    private static readonly SolidColorBrush DayTotalBorder = new(MediaColor.FromRgb(0xA7, 0xF3, 0xD0));
    private static readonly SolidColorBrush DayTotalFg = new(MediaColor.FromRgb(0x06, 0x5F, 0x46));
    private static readonly SolidColorBrush LogTsBrush = new(MediaColor.FromRgb(0x94, 0xA3, 0xB8));
    private static readonly SolidColorBrush LogCatBrush = new(MediaColor.FromRgb(0x02, 0x84, 0xC7));
    private static readonly SolidColorBrush LogMsgBrush = new(MediaColor.FromRgb(0x1E, 0x29, 0x3B));
    private static readonly SolidColorBrush LogSuccessBrush = new(MediaColor.FromRgb(0x16, 0xA3, 0x4A));
    private static readonly SolidColorBrush LogErrorBrush = new(MediaColor.FromRgb(0xDC, 0x26, 0x26));
    private static readonly SolidColorBrush LogWarnBrush = new(MediaColor.FromRgb(0xD9, 0x77, 0x06));
    private static readonly SolidColorBrush LogInfoBrush = new(MediaColor.FromRgb(0x25, 0x63, 0xEB));

    private sealed class PlaceholderInput
    {
        public System.Windows.Controls.TextBox Box { get; }
        public string Placeholder { get; }
        public bool IsNumeric { get; }
        private bool _hasPlaceholder;
        private bool _isFocused;

        public PlaceholderInput(string placeholder, double width, bool isNumeric = false)
        {
            Placeholder = placeholder;
            IsNumeric = isNumeric;
            Box = new System.Windows.Controls.TextBox
            {
                Width = width,
                Height = 28,
                FontFamily = new System.Windows.Media.FontFamily("Segoe UI"),
                FontSize = 13,
                Padding = new Thickness(6, 2, 6, 2),
                Background = MediaBrushes.White,
                BorderBrush = InputBorderBrush,
                BorderThickness = new Thickness(1),
                VerticalContentAlignment = VerticalAlignment.Center
            };

            Box.GotFocus += (_, _) =>
            {
                _isFocused = true;
                Box.BorderBrush = InputFocusBorderBrush;
                if (_hasPlaceholder)
                {
                    Box.Text = string.Empty;
                    Box.Foreground = InputTextBrush;
                    _hasPlaceholder = false;
                }
            };

            Box.LostFocus += (_, _) =>
            {
                _isFocused = false;
                Box.BorderBrush = InputBorderBrush;
                if (!string.IsNullOrEmpty(Placeholder) && string.IsNullOrWhiteSpace(Box.Text))
                    ShowPlaceholder();
            };

            Box.TextChanged += (_, _) =>
            {
                if (!string.IsNullOrEmpty(Placeholder) && !_isFocused && !_hasPlaceholder && string.IsNullOrWhiteSpace(Box.Text))
                    ShowPlaceholder();
            };

            if (isNumeric)
            {
                Box.PreviewTextInput += (_, e) =>
                {
                    if (!string.IsNullOrEmpty(e.Text) && e.Text.Any(c => !char.IsDigit(c)))
                        e.Handled = true;
                };
                System.Windows.DataObject.AddPastingHandler(Box, (_, e) =>
                {
                    if (e.DataObject.GetDataPresent(typeof(string)))
                    {
                        var text = (string)e.DataObject.GetData(typeof(string))!;
                        if (text.Any(c => !char.IsDigit(c)))
                            e.CancelCommand();
                    }
                    else
                    {
                        e.CancelCommand();
                    }
                });
            }

            if (!string.IsNullOrEmpty(placeholder))
                ShowPlaceholder();
        }

        private void ShowPlaceholder()
        {
            _hasPlaceholder = true;
            Box.Text = Placeholder;
            Box.Foreground = PlaceholderBrush;
        }

        public void SetProgrammatic(string value)
        {
            _hasPlaceholder = false;
            Box.Foreground = InputTextBrush;
            Box.Text = value ?? string.Empty;
        }

        public string GetValue() => _hasPlaceholder ? string.Empty : (Box.Text ?? string.Empty).Trim();
        public bool IsFilled => !string.IsNullOrEmpty(GetValue());

        public void Reset()
        {
            if (!string.IsNullOrEmpty(Placeholder))
                ShowPlaceholder();
            else
            {
                _hasPlaceholder = false;
                Box.Foreground = InputTextBrush;
                Box.Text = string.Empty;
            }
        }
    }

    private sealed class KpiRowControls
    {
        public string Label { get; init; } = string.Empty;
        public PlaceholderInput Entry { get; init; } = null!;
        public List<PlaceholderInput> ExtraEntries { get; init; } = [];
        public string[] CountFields { get; init; } = ["load_count"];
        public System.Windows.Controls.ComboBox? StatusCombo { get; init; }
        public TextBlock SiteCountText { get; init; } = null!;
        public TextBlock DayTotalText { get; init; } = null!;
        public string? PendingEventId { get; set; }
        public string? StartedJobId { get; set; }
        public KpiLogRecord? PendingCounts { get; set; }
    }

    private readonly KpiOutbox _outbox;
    private readonly Dictionary<string, KpiRowControls> _rowsTop = new(StringComparer.Ordinal);
    private readonly Dictionary<string, KpiRowControls> _rowsBottom = new(StringComparer.Ordinal);
    private readonly DispatcherTimer _autoRefreshTimer;
    private readonly DispatcherTimer _msgClearTimer;
    private readonly object _syncGuard = new();
    private readonly SemaphoreSlim _refreshSemaphore = new(1, 1);

    private string _userId = string.Empty;
    private string _userCode = string.Empty;
    private bool _profileConfigured;
    private DateTime _selectedDate = KpiTracking.KpiNow();
    private DateTime _calendarViewMonth;
    private string _currentWarehouse = KpiTracking.DefaultWarehouse;
    private GoogleSheetsManager? _gsManager;
    private bool _closed;
    private bool _updating;
    private bool _isPastDate;
    private bool _downloadInProgress;
    private bool _syncRunning;
    private bool _suppressWarehouseEvent;
    private bool _logExpanded = true;

    private IReadOnlyList<IReadOnlyList<string>> _sheet1Cache = [];
    private IReadOnlyList<IReadOnlyList<string>> _sheet2Cache = [];
    private long _cacheTicks;
    private const long CacheTtlMs = 5000;

    public Action? OnOpenSettings { get; set; }
    public Action<KpiSyncResult>? OnKpiStatus { get; set; }
    public Action<Dictionary<(string JobId, string Warehouse), string>>? OnAssignmentsChanged { get; set; }
    public Action? OnReconciliationQueueUpdated { get; set; }

    public KpiView()
        : this(null, null, null, null, null)
    {
    }

    public KpiView(
        KpiUserProfile? profile,
        Action? onOpenSettings = null,
        string? outboxPath = null,
        Action<KpiSyncResult>? onKpiStatus = null,
        Action<Dictionary<(string JobId, string Warehouse), string>>? onAssignmentsChanged = null)
    {
        InitializeComponent();

        _outbox = new KpiOutbox(outboxPath);
        OnOpenSettings = onOpenSettings;
        OnKpiStatus = onKpiStatus;
        OnAssignmentsChanged = onAssignmentsChanged;

        if (profile is not null)
        {
            _userId = profile.UserId;
            _userCode = profile.UserCode;
            _profileConfigured = !string.IsNullOrEmpty(_userId) && !string.IsNullOrEmpty(_userCode);
        }
        else
        {
            var saved = KpiProfile.LoadSavedProfile();
            if (saved is not null)
            {
                _userId = saved.UserId;
                _userCode = saved.UserCode;
                _profileConfigured = true;
            }
            else
            {
                var store = new ConfigStore();
                _userId = store.Get("kpi_user_id") ?? string.Empty;
                _userCode = store.Get("kpi_user_code") ?? string.Empty;
                _profileConfigured = !string.IsNullOrEmpty(_userId) && !string.IsNullOrEmpty(_userCode);
            }
        }

        _calendarViewMonth = new DateTime(_selectedDate.Year, _selectedDate.Month, 1);

        _msgClearTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(3000) };
        _msgClearTimer.Tick += (_, _) =>
        {
            _msgClearTimer.Stop();
            ClearMessage();
        };

        _autoRefreshTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(60) };
        _autoRefreshTimer.Tick += (_, _) => AutoRefreshTick();

        if (OnOpenSettings is not null)
            SettingsBtn.Visibility = Visibility.Visible;

        ConfigureActivityLogDoc();
        UpdateUserLabels();
        UpdateDateDisplay();
        PopulateWarehouseCombo(_currentWarehouse);
        BuildTaskRows();
        PopulateInitialLogs();

        _autoRefreshTimer.Start();
        Dispatcher.BeginInvoke(DispatcherPriority.Background, new Action(() => InitGoogleSheetsAsync()));

        var identity = _profileConfigured ? $"{_userId} ({_userCode})" : "profile setup in Settings";
        AddActivityLog("SYSTEM", $"User KPI ready for {identity}", "INFO");
    }

    private void ConfigureActivityLogDoc()
    {
        var style = new Style(typeof(Paragraph));
        style.Setters.Add(new Setter(Block.MarginProperty, new Thickness(0, 1, 0, 1)));
        LogRichBox.Resources[typeof(Paragraph)] = style;
        LogRichBox.Document = new FlowDocument { PageWidth = 4000 };
    }

    private void UpdateUserLabels()
    {
        UserLabelText.Text = string.IsNullOrEmpty(_userId) ? "Not configured" : _userId;
        UserCodeText.Text = _userCode ?? string.Empty;
    }

    private void UpdateDateDisplay()
    {
        DateDisplayText.Text = _selectedDate.ToString("dd-MM-yyyy", CultureInfo.InvariantCulture);
    }

    private static Dictionary<string, JobMapEntry> LoadJobMap() => JobMapStore.LoadPersistedJobMap();

    private void PopulateWarehouseCombo(string? selectedValue)
    {
        _suppressWarehouseEvent = true;
        try
        {
            var choices = KpiTracking.WarehouseOptions(LoadJobMap());
            var extra = KpiTracking.Warehouse(selectedValue);
            if (!string.IsNullOrEmpty(extra) && !choices.Contains(extra))
                choices.Add(extra);

            WarehouseCombo.ItemsSource = choices;
            var target = string.IsNullOrEmpty(extra) ? _currentWarehouse : extra;
            if (!choices.Contains(target) && !string.IsNullOrEmpty(target))
            {
                choices.Add(target);
                WarehouseCombo.ItemsSource = choices.ToList();
            }
            WarehouseCombo.SelectedItem = target;
        }
        finally
        {
            _suppressWarehouseEvent = false;
        }
    }

    private void BuildTaskRows()
    {
        TopRowsHost.Children.Clear();
        BottomRowsHost.Children.Clear();
        _rowsTop.Clear();
        _rowsBottom.Clear();

        (string Label, string[] Options)[] topConfigs =
        [
            ("GDN Reconciliation:", ["New", "Revise", "Separate"]),
            ("GRN Reconciliation:", ["New", "Revise", "Separate"]),
            ("GDN Creation:", ["New", "Revise", "Separate"]),
            ("GRN Creation:", ["New", "Revise", "Separate"]),
            ("Load Plan or Asn:", ["New", "Revise", "Separate"])
        ];

        foreach (var (label, opts) in topConfigs)
        {
            var (ctrl, panel) = MakeRow(label, hasExtraCounts: false, hasLpCount: false, dropdownOptions: opts, lpOnly: false);
            _rowsTop[label] = ctrl;
            TopRowsHost.Children.Add(panel);
        }

        (string Label, bool HasLp)[] bottomConfigs =
        [
            ("Load Audit:", false),
            ("Shipping:", false),
            ("Load Transfer:", true),
            ("Allocation:", false),
            ("Backorders:", false)
        ];

        foreach (var (label, hasLp) in bottomConfigs)
        {
            bool lpOnly = label is "Allocation:" or "Backorders:";
            var (ctrl, panel) = MakeRow(label, hasExtraCounts: true, hasLpCount: hasLp, dropdownOptions: null, lpOnly: lpOnly);
            _rowsBottom[label] = ctrl;
            BottomRowsHost.Children.Add(panel);
        }
    }

    private (KpiRowControls Controls, FrameworkElement Element) MakeRow(
        string labelText,
        bool hasExtraCounts,
        bool hasLpCount,
        string[]? dropdownOptions,
        bool lpOnly)
    {
        var grid = new Grid { Margin = new Thickness(4, 4, 4, 4) };
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(160) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

        var lbl = new TextBlock
        {
            Text = labelText,
            FontFamily = new System.Windows.Media.FontFamily("Segoe UI"),
            FontSize = 12,
            FontWeight = FontWeights.Bold,
            Foreground = InputTextBrush,
            VerticalAlignment = VerticalAlignment.Center
        };
        Grid.SetColumn(lbl, 0);
        grid.Children.Add(lbl);

        var rightPanel = new StackPanel
        {
            Orientation = System.Windows.Controls.Orientation.Horizontal,
            Margin = new Thickness(10, 0, 0, 0),
            VerticalAlignment = VerticalAlignment.Center
        };

        var entry = new PlaceholderInput("Enter Job ID", 150);
        entry.Box.Margin = new Thickness(0, 0, 6, 0);
        rightPanel.Children.Add(entry.Box);

        var extraEntries = new List<PlaceholderInput>();
        System.Windows.Controls.ComboBox? statusCombo = null;

        if (hasExtraCounts)
        {
            var e1 = new PlaceholderInput(lpOnly ? "LP Count" : "Load ID Count", 104, isNumeric: true);
            e1.Box.Margin = new Thickness(0, 0, 6, 0);
            rightPanel.Children.Add(e1.Box);
            extraEntries.Add(e1);

            if (hasLpCount)
            {
                var e2 = new PlaceholderInput("LP Count", 100, isNumeric: true);
                e2.Box.Margin = new Thickness(0, 0, 6, 0);
                rightPanel.Children.Add(e2.Box);
                extraEntries.Add(e2);
            }
        }
        else if (dropdownOptions is not null)
        {
            statusCombo = new System.Windows.Controls.ComboBox
            {
                Width = 96,
                Height = 28,
                FontFamily = new System.Windows.Media.FontFamily("Segoe UI"),
                FontSize = 12,
                Padding = new Thickness(6, 2, 6, 2),
                IsEditable = false,
                Margin = new Thickness(0, 0, 6, 0),
                ItemsSource = dropdownOptions,
                SelectedItem = "New",
                VerticalContentAlignment = VerticalAlignment.Center
            };
            rightPanel.Children.Add(statusCombo);
        }

        var rowControls = new KpiRowControls
        {
            Label = labelText,
            Entry = entry,
            ExtraEntries = extraEntries,
            CountFields = lpOnly ? ["lp_count"] : (hasLpCount ? ["load_count", "lp_count"] : ["load_count"]),
            StatusCombo = statusCombo,
            SiteCountText = new TextBlock
            {
                Text = labelText == "Load Transfer:" ? "0-0" : "0",
                FontFamily = new System.Windows.Media.FontFamily("Segoe UI"),
                FontSize = 12,
                FontWeight = FontWeights.Bold,
                Foreground = InputTextBrush,
                HorizontalAlignment = System.Windows.HorizontalAlignment.Center,
                Width = 54,
                TextAlignment = TextAlignment.Center
            },
            DayTotalText = new TextBlock
            {
                Text = "...",
                FontFamily = new System.Windows.Media.FontFamily("Segoe UI"),
                FontSize = 12,
                FontWeight = FontWeights.Bold,
                Foreground = DayTotalFg,
                HorizontalAlignment = System.Windows.HorizontalAlignment.Center,
                Width = 54,
                TextAlignment = TextAlignment.Center
            }
        };

        var submitBtn = new System.Windows.Controls.Button
        {
            Content = "Submit",
            Width = 66,
            Height = 28,
            Background = SubmitBg,
            Foreground = MediaBrushes.White,
            FontFamily = new System.Windows.Media.FontFamily("Segoe UI"),
            FontSize = 12,
            FontWeight = FontWeights.Bold,
            BorderThickness = new Thickness(0),
            Cursor = System.Windows.Input.Cursors.Hand,
            Margin = new Thickness(3, 0, 3, 0)
        };
        submitBtn.Click += (_, _) => HandleSubmit(rowControls, isBottom: hasExtraCounts);
        rightPanel.Children.Add(submitBtn);

        var deleteBtn = new System.Windows.Controls.Button
        {
            Content = "Delete",
            Width = 66,
            Height = 28,
            Background = DeleteBg,
            Foreground = MediaBrushes.White,
            FontFamily = new System.Windows.Media.FontFamily("Segoe UI"),
            FontSize = 12,
            FontWeight = FontWeights.Bold,
            BorderThickness = new Thickness(0),
            Cursor = System.Windows.Input.Cursors.Hand,
            Margin = new Thickness(3, 0, 3, 0)
        };
        deleteBtn.Click += (_, _) => HandleDelete(rowControls, isBottom: hasExtraCounts);
        rightPanel.Children.Add(deleteBtn);

        var siteBadge = new Border
        {
            Background = SiteCountBg,
            BorderBrush = CardBorderBrush,
            BorderThickness = new Thickness(1),
            Padding = new Thickness(6, 2, 6, 2),
            Margin = new Thickness(8, 0, 0, 0),
            Child = new StackPanel
            {
                HorizontalAlignment = System.Windows.HorizontalAlignment.Center,
                Children =
                {
                    new TextBlock
                    {
                        Text = "Site count",
                        FontSize = 9.5,
                        Foreground = PlaceholderBrush,
                        HorizontalAlignment = System.Windows.HorizontalAlignment.Center
                    },
                    rowControls.SiteCountText
                }
            }
        };
        rightPanel.Children.Add(siteBadge);

        var dayBadge = new Border
        {
            Background = DayTotalBg,
            BorderBrush = DayTotalBorder,
            BorderThickness = new Thickness(1),
            Padding = new Thickness(6, 2, 6, 2),
            Margin = new Thickness(6, 0, 0, 0),
            Child = new StackPanel
            {
                HorizontalAlignment = System.Windows.HorizontalAlignment.Center,
                Children =
                {
                    new TextBlock
                    {
                        Text = "Day total",
                        FontSize = 9.5,
                        Foreground = PlaceholderBrush,
                        HorizontalAlignment = System.Windows.HorizontalAlignment.Center
                    },
                    rowControls.DayTotalText
                }
            }
        };
        rightPanel.Children.Add(dayBadge);

        Grid.SetColumn(rightPanel, 1);
        grid.Children.Add(rightPanel);
        return (rowControls, grid);
    }

    public void SetProfile(KpiUserProfile? profile)
    {
        string oldUser = _userId;
        _profileConfigured = profile is not null && !string.IsNullOrEmpty(profile.UserId) && !string.IsNullOrEmpty(profile.UserCode);
        if (profile is not null && _profileConfigured)
        {
            _userId = profile.UserId;
            _userCode = profile.UserCode;
        }
        else
        {
            _userId = string.Empty;
            _userCode = string.Empty;
        }

        UpdateUserLabels();
        if (!string.Equals(oldUser, _userId, StringComparison.Ordinal))
        {
            AddActivityLog("PROFILE", $"Operator profile changed to {_userId} ({_userCode})", "INFO");
            ResetAllRows();
        }

        _cacheTicks = 0;
        if (_gsManager?.Connected == true)
            RefreshAllCounts();
    }

    public bool PrefillReconciliationJob(string jobId, string section, string warehouseId = "", string? eventId = null)
    {
        if (!_rowsTop.TryGetValue(section, out var row))
            return false;

        row.Entry.SetProgrammatic(jobId);
        if (row.StatusCombo is not null)
            row.StatusCombo.SelectedItem = "New";

        SelectWarehouse(warehouseId);
        row.PendingEventId = eventId;
        row.StartedJobId = jobId;

        AddActivityLog("TASK", $"Job {jobId} prefilled into '{section.TrimEnd(':')}' from Tool 6", "INFO");
        return true;
    }

    public string RecordStartedJob(JobMapEntry record, KpiUserProfile? profile)
    {
        string jobId = (record.JobId ?? string.Empty).Trim();
        string? section = jobId.StartsWith("OUT_", StringComparison.OrdinalIgnoreCase)
            ? "GDN Reconciliation:"
            : jobId.StartsWith("IN_", StringComparison.OrdinalIgnoreCase)
                ? "GRN Reconciliation:"
                : null;
        if (section is null)
            return "ignored";

        string site = KpiTracking.ResolveWarehouse(jobId, record.Warehouse, LoadJobMap());
        GoToToday();
        ResetRowsSilent();
        BodyScrollViewer.ScrollToTop();
        PrefillReconciliationJob(jobId, section, site);

        if (profile is null || string.IsNullOrEmpty(profile.UserId) || string.IsNullOrEmpty(profile.UserCode))
        {
            ShowMessage("Configure your KPI profile in Settings, then review and click Submit", MsgWarningColor, 10000);
            return "needs_profile";
        }
        if (string.IsNullOrEmpty(site))
        {
            ShowMessage("Select the job warehouse, then click Submit", MsgWarningColor, 10000);
            return "needs_warehouse";
        }

        ShowMessage($"Job {jobId} | Warehouse: {site} | Review and click Submit", MsgInfoColor, 10000);
        return "ready";
    }

    public void ShowMessage(string text, string colorHex = MsgInfoColor, int durationMs = 3000)
    {
        if (_closed)
            return;

        if (!Dispatcher.CheckAccess())
        {
            Dispatcher.BeginInvoke(() => ShowMessage(text, colorHex, durationMs));
            return;
        }

        var brush = ParseBrush(colorHex, MsgInfoColor);
        MsgLabel.Text = text;
        MsgLabel.Foreground = brush;
        MsgIcon.Text = string.Equals(colorHex, MsgSuccessColor, StringComparison.OrdinalIgnoreCase)
            ? "✓"
            : string.Equals(colorHex, MsgErrorColor, StringComparison.OrdinalIgnoreCase)
                ? "✕"
                : "✦";
        MsgIcon.Foreground = brush;

        _msgClearTimer.Stop();
        _msgClearTimer.Interval = TimeSpan.FromMilliseconds(Math.Max(250, durationMs));
        _msgClearTimer.Start();
    }

    private void ClearMessage()
    {
        if (_closed)
            return;
        MsgLabel.Text = "Ready";
        MsgLabel.Foreground = ParseBrush(MsgMutedColor, MsgMutedColor);
        MsgIcon.Text = "✦";
        MsgIcon.Foreground = ParseBrush(AuroraCyanHex, AuroraCyanHex);
        _msgClearTimer.Stop();
    }

    private static SolidColorBrush ParseBrush(string hex, string fallback)
    {
        try
        {
            return new SolidColorBrush((MediaColor)System.Windows.Media.ColorConverter.ConvertFromString(hex));
        }
        catch
        {
            return new SolidColorBrush((MediaColor)System.Windows.Media.ColorConverter.ConvertFromString(fallback));
        }
    }

    public void Close()
    {
        if (_closed)
            return;
        _closed = true;
        _autoRefreshTimer.Stop();
        _msgClearTimer.Stop();
        HideWarehouseLoading();
    }

    private void Settings_Click(object sender, RoutedEventArgs e) => OnOpenSettings?.Invoke();

    #region DatePicker

    private void DateChip_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        if (CalendarPopup.IsOpen)
        {
            CalendarPopup.IsOpen = false;
        }
        else
        {
            _calendarViewMonth = new DateTime(_selectedDate.Year, _selectedDate.Month, 1);
            RenderCalendar();
            CalendarPopup.IsOpen = true;
        }
    }

    private void DateChip_MouseEnter(object sender, System.Windows.Input.MouseEventArgs e)
        => DateChipBorder.Background = SiteCountBg;

    private void DateChip_MouseLeave(object sender, System.Windows.Input.MouseEventArgs e)
        => DateChipBorder.Background = MediaBrushes.White;

    private void PrevMonth_MouseDown(object sender, MouseButtonEventArgs e)
    {
        _calendarViewMonth = _calendarViewMonth.AddMonths(-1);
        RenderCalendar();
    }

    private void NextMonth_MouseDown(object sender, MouseButtonEventArgs e)
    {
        _calendarViewMonth = _calendarViewMonth.AddMonths(1);
        RenderCalendar();
    }

    private void TodayBtn_Click(object sender, RoutedEventArgs e) => GoToToday();
    private void PopupToday_Click(object sender, RoutedEventArgs e) => GoToToday();

    private void GoToToday()
    {
        var now = KpiTracking.KpiNow();
        _calendarViewMonth = new DateTime(now.Year, now.Month, 1);
        ApplyDateSelection(now);
    }

    private void ApplyDateSelection(DateTime dateObj)
    {
        _selectedDate = dateObj;
        UpdateDateDisplay();
        CalendarPopup.IsOpen = false;

        var today = KpiTracking.KpiNow().Date;
        _isPastDate = dateObj.Date < today;
        if (_isPastDate)
        {
            ShowMessage("Past date selected (View Only)", MsgWarningColor, 3000);
            DateModeText.Text = "VIEW ONLY";
        }
        else
        {
            ClearMessage();
            DateModeText.Text = string.Empty;
        }

        _cacheTicks = 0;
        ClearCounts();
        RefreshAllCounts();
    }

    private void RenderCalendar()
    {
        CalendarDaysGrid.Children.Clear();
        CalendarMonthText.Text = _calendarViewMonth.ToString("MMMM yyyy", CultureInfo.InvariantCulture);

        int year = _calendarViewMonth.Year;
        int month = _calendarViewMonth.Month;
        int daysInMonth = DateTime.DaysInMonth(year, month);
        int firstDowMondayZero = ((int)new DateTime(year, month, 1).DayOfWeek + 6) % 7;
        var today = KpiTracking.KpiNow().Date;

        for (int i = 0; i < firstDowMondayZero; i++)
            CalendarDaysGrid.Children.Add(new Border());

        for (int day = 1; day <= daysInMonth; day++)
        {
            var d = new DateTime(year, month, day);
            bool isToday = d.Date == today;
            bool isSelected = d.Date == _selectedDate.Date;

            var bg = isSelected
                ? ParseBrush("#0B1420", "#0B1420")
                : isToday
                    ? ParseBrush("#E0F2FE", "#E0F2FE")
                    : MediaBrushes.White;
            var fg = isSelected
                ? MediaBrushes.White
                : isToday
                    ? ParseBrush("#0284C7", "#0284C7")
                    : InputTextBrush;

            var dayBorder = new Border
            {
                Background = bg,
                BorderBrush = (isToday && !isSelected) ? InputFocusBorderBrush : MediaBrushes.Transparent,
                BorderThickness = new Thickness(isToday && !isSelected ? 1 : 0),
                Margin = new Thickness(1),
                Padding = new Thickness(0, 4, 0, 4),
                Cursor = System.Windows.Input.Cursors.Hand,
                Child = new TextBlock
                {
                    Text = day.ToString(CultureInfo.InvariantCulture),
                    Foreground = fg,
                    FontSize = 12,
                    FontWeight = isSelected ? FontWeights.Bold : FontWeights.Normal,
                    HorizontalAlignment = System.Windows.HorizontalAlignment.Center
                }
            };

            dayBorder.MouseLeftButtonDown += (_, _) => ApplyDateSelection(d);
            if (!isSelected)
            {
                dayBorder.MouseEnter += (_, _) => dayBorder.Background = ParseBrush("#F1F5F9", "#F1F5F9");
                dayBorder.MouseLeave += (_, _) => dayBorder.Background = bg;
            }
            CalendarDaysGrid.Children.Add(dayBorder);
        }
    }

    #endregion

    #region Warehouse

    private void WarehouseCombo_DropDownOpened(object? sender, EventArgs e)
    {
        var current = WarehouseCombo.SelectedItem?.ToString();
        PopulateWarehouseCombo(current);
    }

    private void SelectWarehouse(string? value, bool reset = false)
    {
        string normalized = KpiTracking.Warehouse(value);
        if (string.IsNullOrEmpty(normalized))
            return;

        bool changed = !string.Equals(normalized, _currentWarehouse, StringComparison.Ordinal);
        _currentWarehouse = normalized;
        PopulateWarehouseCombo(normalized);

        if (changed)
        {
            ShowWarehouseLoading(normalized);
            _cacheTicks = 0;
            if (reset)
                ResetRowsSilent();
            ClearCounts();
            Dispatcher.BeginInvoke(DispatcherPriority.Background, new Action(() => RefreshAllCounts()));
        }
    }

    private void WarehouseCombo_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_suppressWarehouseEvent)
            return;

        var pending = _rowsTop.Values
            .Where(r => !string.IsNullOrEmpty(r.PendingEventId) && r.Entry.IsFilled)
            .Select(r => (r.Label, r.PendingEventId!))
            .ToList();

        var drafts = _rowsTop.Values
            .Where(r => !string.IsNullOrEmpty(r.StartedJobId)
                        && string.IsNullOrEmpty(r.PendingEventId)
                        && string.Equals(r.Entry.GetValue(), r.StartedJobId, StringComparison.Ordinal))
            .Select(r => (r.Label, r.StartedJobId!, r.StatusCombo?.SelectedItem?.ToString() ?? "New"))
            .ToList();

        string value = WarehouseCombo.SelectedItem?.ToString() ?? string.Empty;
        if (string.IsNullOrEmpty(value))
            return;

        SelectWarehouse(value, reset: true);

        foreach (var (label, jobId, status) in drafts)
        {
            PrefillReconciliationJob(jobId, label, value);
            if (_rowsTop.TryGetValue(label, out var row) && row.StatusCombo is not null)
                row.StatusCombo.SelectedItem = status;
        }

        foreach (var (label, eventId) in pending)
        {
            var item = _outbox.Get(eventId);
            if (item is not null && item.State is "needs_warehouse" or "needs_profile")
                PrefillReconciliationJob(item.JobId, label, value, eventId);
        }

        ShowMessage($"Warehouse: {value}", MsgInfoColor, 2000);
    }

    private void ShowWarehouseLoading(string site)
    {
        WarehouseLoadingText.Text = $"Loading {(string.IsNullOrEmpty(site) ? "warehouse" : site)}...";
        WarehouseLoadingOverlay.Visibility = Visibility.Visible;
    }

    private void HideWarehouseLoading((DateTime Date, string UserId, string Warehouse)? snapshot = null)
    {
        if (snapshot is not null && (snapshot.Value.Date.Date != _selectedDate.Date
            || !string.Equals(snapshot.Value.UserId, _userId, StringComparison.Ordinal)
            || !string.Equals(snapshot.Value.Warehouse, _currentWarehouse, StringComparison.Ordinal)))
        {
            return;
        }
        WarehouseLoadingOverlay.Visibility = Visibility.Collapsed;
    }

    #endregion

    #region Google Sheets & Outbox Sync

    private void InitGoogleSheetsAsync()
    {
        if (_closed)
            return;
        ShowMessage("Connecting to Google Sheets...", MsgInfoColor, 60000);
        _ = Task.Run(() =>
        {
            bool connected = false;
            try
            {
                var mgr = new GoogleSheetsManager(GoogleSheetsManager.DefaultSpreadsheetUrl);
                connected = mgr.Connect();
                _gsManager = mgr;
            }
            catch
            {
                connected = false;
            }

            if (!_closed)
            {
                Dispatcher.BeginInvoke(() =>
                {
                    if (connected) OnConnected();
                    else OnDisconnected();
                });
            }
        });
    }

    private void OnConnected()
    {
        ShowMessage("Connected to Google Sheets!", MsgSuccessColor, 2500);
        AddActivityLog("CONNECT", "Connected to Google Sheets successfully", "SUCCESS");
        RefreshAllCounts();
        SyncPendingAsync();
    }

    private void OnDisconnected()
    {
        ShowMessage("Failed to connect to Google Sheets", MsgErrorColor, 5000);
        AddActivityLog("CONNECT", "Failed to connect to Google Sheets", "ERROR");
    }

    private void AutoRefreshTick()
    {
        if (_closed)
            return;
        if (_gsManager?.Connected == true)
        {
            SyncPendingAsync();
            _cacheTicks = 0;
            RefreshAllCounts();
        }
        else
        {
            InitGoogleSheetsAsync();
        }
    }

    private void SyncPendingAsync()
    {
        if (_closed || _gsManager is null || !_gsManager.Connected || _gsManager.Worksheet1 is null || _gsManager.Worksheet2 is null)
            return;

        lock (_syncGuard)
        {
            if (_syncRunning)
                return;
            _syncRunning = true;
        }

        var mgr = _gsManager;
        var jobMap = LoadJobMap();
        _ = Task.Run(() =>
        {
            try
            {
                OutboxSynchronizer.SyncOutbox(
                    _outbox,
                    new Sheet1Log(mgr.Worksheet1, jobMap),
                    HandleOutboxSaved,
                    () => _closed,
                    new Sheet2Log(mgr.Worksheet2, jobMap));
            }
            catch
            {
            }
            finally
            {
                lock (_syncGuard)
                    _syncRunning = false;
            }
        });
    }

    private void HandleOutboxSaved(KpiSyncResult result)
    {
        var rec = result.Record;
        if (result.State == "synced" && ReconciliationQueue.IsReconciliationTask(rec.Task))
        {
            try
            {
                ReconciliationQueue.EnqueueJob(rec.JobId, rec.Task, rec.UserId);
                Dispatcher.BeginInvoke(() => OnReconciliationQueueUpdated?.Invoke());
            }
            catch
            {
            }
        }

        if (_closed)
            return;

        Dispatcher.BeginInvoke(() =>
        {
            if (result.State == "synced")
            {
                ShowMessage($"KPI saved: {rec.JobId} ({rec.Warehouse})", MsgSuccessColor, 5000);
            }
            else if (result.State == "cancelled")
            {
                string msg = result.Removed > 0
                    ? $"KPI deleted: {rec.JobId} ({rec.Warehouse})"
                    : $"No saved entry found for {rec.JobId} in {rec.Warehouse}; pending retries cancelled";
                ShowMessage(msg, result.Removed > 0 ? MsgSuccessColor : MsgInfoColor, 8000);
            }
            else
            {
                ShowMessage(string.IsNullOrEmpty(result.Error) ? $"KPI: already assigned by {result.Owner}" : result.Error, MsgWarningColor, 5000);
            }

            AddActivityLog("KPI", $"{rec.JobId} | {rec.Warehouse} | {result.State}", "INFO");
            OnKpiStatus?.Invoke(result);
            _cacheTicks = 0;
            RefreshAllCounts();
        });
    }

    #endregion

    #region Count Calculation & Refresh

    private void ClearCounts()
    {
        foreach (var row in _rowsTop.Values)
        {
            row.SiteCountText.Text = "0";
            row.DayTotalText.Text = "...";
        }
        foreach (var (label, row) in _rowsBottom)
        {
            row.SiteCountText.Text = label == "Load Transfer:" ? "0-0" : "0";
            row.DayTotalText.Text = "...";
        }
    }

    private void RefreshAllCounts()
    {
        if (_gsManager is null || !_gsManager.Connected || _gsManager.Worksheet1 is null || _gsManager.Worksheet2 is null)
        {
            bool wasOverlay = WarehouseLoadingOverlay.Visibility == Visibility.Visible;
            HideWarehouseLoading();
            if (wasOverlay)
                ShowMessage("KPI counts are unavailable while Google Sheets is offline.", MsgWarningColor, 5000);
            return;
        }

        if (_updating)
            return;

        var snapshot = (_selectedDate, _userId, _currentWarehouse);
        var topKeys = _rowsTop.Keys.ToList();
        var bottomKeys = _rowsBottom.Keys.ToList();
        var mgr = _gsManager;
        _updating = true;

        _ = Task.Run(async () =>
        {
            await _refreshSemaphore.WaitAsync();
            _updating = true;
            try
            {
                IReadOnlyList<IReadOnlyList<string>> values1;
                IReadOnlyList<IReadOnlyList<string>> values2;

                if (Environment.TickCount64 - _cacheTicks < CacheTtlMs && _sheet1Cache.Count > 0 && _sheet2Cache.Count > 0)
                {
                    values1 = _sheet1Cache;
                    values2 = _sheet2Cache;
                }
                else
                {
                    var t1 = Task.Run(() => new Sheet1Log(mgr.Worksheet1!).Read());
                    var t2 = Task.Run(() => new Sheet2Log(mgr.Worksheet2!).Read());
                    var all = Task.WhenAll(t1, t2);
                    var completed = await Task.WhenAny(all, Task.Delay(15000));
                    if (completed != all)
                        throw new TimeoutException("Google Sheets refresh timed out");

                    await all;
                    values1 = t1.Result;
                    values2 = t2.Result;
                    _sheet1Cache = values1;
                    _sheet2Cache = values2;
                    _cacheTicks = Environment.TickCount64;
                }

                var counts = CalculateCounts(values1, values2, snapshot.Item1, snapshot.Item2, snapshot.Item3, topKeys, bottomKeys);
                if (!_closed)
                {
                    await Dispatcher.InvokeAsync(() =>
                        UpdateCountsUi(values1, snapshot.Item1, snapshot.Item2, snapshot.Item3, counts));
                }
            }
            catch (Exception ex)
            {
                if (!_closed)
                    _ = Dispatcher.BeginInvoke(() => ShowMessage($"Could not refresh KPI counts: {ex.Message}", MsgErrorColor, 5000));
            }
            finally
            {
                _updating = false;
                _refreshSemaphore.Release();
                if (!_closed)
                {
                    _ = Dispatcher.BeginInvoke(() =>
                    {
                        if (snapshot._selectedDate.Date != _selectedDate.Date
                            || !string.Equals(snapshot._userId, _userId, StringComparison.Ordinal)
                            || !string.Equals(snapshot._currentWarehouse, _currentWarehouse, StringComparison.Ordinal))
                        {
                            RefreshAllCounts();
                        }
                        else
                        {
                            HideWarehouseLoading(snapshot);
                        }
                    });
                }
            }
        });
    }

    private sealed record CalculatedCounts(
        Dictionary<string, int> TopSite,
        Dictionary<string, int> TopDay,
        Dictionary<string, (int Load, int Lp)> BottomSite,
        Dictionary<string, (int Load, int Lp)> BottomDay);

    private static CalculatedCounts CalculateCounts(
        IReadOnlyList<IReadOnlyList<string>> values1,
        IReadOnlyList<IReadOnlyList<string>> values2,
        DateTime selectedDate,
        string userId,
        string site,
        IReadOnlyList<string> topLabels,
        IReadOnlyList<string> bottomLabels)
    {
        string dateStr = selectedDate.ToString("dd-MM-yyyy", CultureInfo.InvariantCulture);
        var jobMap = LoadJobMap();
        var records1 = KpiTracking.LogRecords(values1, jobMap).ToList();
        var records2 = KpiTracking.Sheet2Records(values2, jobMap).ToList();

        var topSite = new Dictionary<string, int>(StringComparer.Ordinal);
        var topDay = new Dictionary<string, int>(StringComparer.Ordinal);
        foreach (var label in topLabels)
        {
            var sources = new List<string> { label };
            if (label is "GDN Creation:" or "GRN Creation:")
                sources.Add(label.Replace("Creation", "Reconciliation", StringComparison.Ordinal));

            topSite[label] = sources.Sum(task => CountSheet1Task(records1, task, userId, dateStr, site));
            topDay[label] = sources.Sum(task => CountSheet1Task(records1, task, userId, dateStr, null));
        }

        var bottomSite = new Dictionary<string, (int Load, int Lp)>(StringComparer.Ordinal);
        var bottomDay = new Dictionary<string, (int Load, int Lp)>(StringComparer.Ordinal);
        foreach (var label in bottomLabels)
        {
            bottomSite[label] = SumSheet2Task(records2, label, userId, dateStr, site);
            bottomDay[label] = SumSheet2Task(records2, label, userId, dateStr, null);
        }

        return new CalculatedCounts(topSite, topDay, bottomSite, bottomDay);
    }

    private static int CountSheet1Task(
        IReadOnlyList<KpiLogRecord> records,
        string taskName,
        string userId,
        string dateStr,
        string? warehouseId)
    {
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var seenEvents = new HashSet<string>(StringComparer.Ordinal);
        string taskNorm = KpiTracking.Norm(taskName);
        string userNorm = KpiTracking.Norm(userId);
        string? whNorm = warehouseId is null ? null : KpiTracking.Norm(warehouseId);

        foreach (var r in records)
        {
            if (KpiTracking.Norm(r.Task) != taskNorm || KpiTracking.Norm(r.UserId) != userNorm)
                continue;
            if (whNorm is not null && KpiTracking.Norm(r.Warehouse) != whNorm)
                continue;
            string day = KpiTracking.ParseTimestampDate(r.Timestamp);
            if (!string.IsNullOrEmpty(dateStr) && day != dateStr)
                continue;

            string identity = KpiTracking.RecordIdentity(r);
            if (seen.Contains(identity) || (!string.IsNullOrEmpty(r.EventId) && seenEvents.Contains(r.EventId)))
                continue;
            seen.Add(identity);
            if (!string.IsNullOrEmpty(r.EventId))
                seenEvents.Add(r.EventId);
        }

        return seen.Count;
    }

    private static (int Load, int Lp) SumSheet2Task(
        IReadOnlyList<KpiLogRecord> records,
        string taskName,
        string userId,
        string dateStr,
        string? warehouseId)
    {
        var seen = new HashSet<string>(StringComparer.Ordinal);
        int loadSum = 0;
        int lpSum = 0;
        string taskNorm = KpiTracking.Norm(taskName);
        string userNorm = KpiTracking.Norm(userId);
        string? whNorm = warehouseId is null ? null : KpiTracking.Norm(warehouseId);

        foreach (var r in records)
        {
            if (KpiTracking.Norm(r.Task) != taskNorm || KpiTracking.Norm(r.UserId) != userNorm)
                continue;
            if (whNorm is not null && KpiTracking.Norm(r.Warehouse) != whNorm)
                continue;
            string day = KpiTracking.ParseTimestampDate(r.Timestamp);
            if (!string.IsNullOrEmpty(dateStr) && day != dateStr)
                continue;

            string identity = KpiTracking.RecordIdentity(r);
            if (!seen.Add(identity))
                continue;

            loadSum += KpiTracking.CountValue(r.LoadCount) ?? 0;
            lpSum += KpiTracking.CountValue(r.LpCount) ?? 0;
        }

        return (loadSum, lpSum);
    }

    private void UpdateCountsUi(
        IReadOnlyList<IReadOnlyList<string>> values1,
        DateTime selectedDate,
        string userId,
        string site,
        CalculatedCounts counts)
    {
        if (_closed)
            return;

        OnAssignmentsChanged?.Invoke(KpiTracking.JobAssignments(values1, LoadJobMap()));

        string dateStr = selectedDate.ToString("dd-MM-yyyy", CultureInfo.InvariantCulture);
        string currentStr = _selectedDate.ToString("dd-MM-yyyy", CultureInfo.InvariantCulture);
        if (KpiTracking.Norm(userId) != KpiTracking.Norm(_userId)
            || KpiTracking.Norm(site) != KpiTracking.Norm(_currentWarehouse)
            || dateStr != currentStr)
        {
            return;
        }

        foreach (var (label, row) in _rowsTop)
        {
            row.SiteCountText.Text = counts.TopSite[label].ToString(CultureInfo.InvariantCulture);
            row.DayTotalText.Text = counts.TopDay[label].ToString(CultureInfo.InvariantCulture);
        }

        foreach (var (label, row) in _rowsBottom)
        {
            var (load, lp) = counts.BottomSite[label];
            row.SiteCountText.Text = label == "Load Transfer:"
                ? $"{load}-{lp}"
                : (label is "Allocation:" or "Backorders:" ? lp : load).ToString(CultureInfo.InvariantCulture);

            var (dayLoad, dayLp) = counts.BottomDay[label];
            row.DayTotalText.Text = label == "Load Transfer:"
                ? $"{dayLoad}-{dayLp}"
                : (label is "Allocation:" or "Backorders:" ? dayLp : dayLoad).ToString(CultureInfo.InvariantCulture);
        }

        AddActivityLog("SYNC", $"Counts refreshed for {dateStr} ({(string.IsNullOrEmpty(site) ? "Select warehouse" : site)})", "INFO");
    }

    #endregion

    #region Row Submit / Delete / Reset

    private void ResetRowsSilent()
    {
        foreach (var row in _rowsTop.Values.Concat(_rowsBottom.Values))
        {
            row.Entry.Reset();
            if (row.StatusCombo is not null)
                row.StatusCombo.SelectedItem = "New";
            foreach (var extra in row.ExtraEntries)
                extra.Reset();
            row.PendingEventId = null;
            row.StartedJobId = null;
            row.PendingCounts = null;
        }
    }

    private void ResetAllRows()
    {
        if (_isPastDate)
            return;
        ResetRowsSilent();
        ShowMessage("All rows reset", MsgInfoColor, 1500);
        Dispatcher.BeginInvoke(DispatcherPriority.Background, new Action(RefreshAllCounts));
    }

    private (bool IsValid, List<string> Missing) ValidateRowFields(KpiRowControls row, bool isBottom)
    {
        if (_isPastDate)
            return (false, ["Date is in the past - View Only mode"]);

        var missing = new List<string>();
        if (!row.Entry.IsFilled)
            missing.Add("Job ID");

        if (string.IsNullOrWhiteSpace(WarehouseCombo.SelectedItem?.ToString()))
            missing.Add("Warehouse");

        if (!isBottom)
        {
            if (row.StatusCombo is null || string.IsNullOrWhiteSpace(row.StatusCombo.SelectedItem?.ToString()))
                missing.Add("Job Status");
        }
        else
        {
            if (row.ExtraEntries.Count == 0)
            {
                missing.Add("Load ID Count");
            }
            else
            {
                for (int i = 0; i < Math.Min(row.CountFields.Length, row.ExtraEntries.Count); i++)
                {
                    if (!row.ExtraEntries[i].IsFilled)
                        missing.Add(row.CountFields[i] == "lp_count" ? "LP Count" : "Load ID Count");
                }
            }
        }

        return (missing.Count == 0, missing);
    }

    private void HandleSubmit(KpiRowControls row, bool isBottom)
    {
        var (valid, missing) = ValidateRowFields(row, isBottom);
        if (!valid)
        {
            ShowMessage("Required: " + string.Join(", ", missing), MsgErrorColor, 3000);
            return;
        }
        if (!_profileConfigured)
        {
            ShowMessage("Configure your KPI profile in Settings", MsgWarningColor, 3000);
            return;
        }
        if (_gsManager is null || !_gsManager.Connected)
        {
            ShowMessage("Offline - Cannot submit", MsgErrorColor, 3000);
            return;
        }

        string jobId = row.Entry.GetValue();
        string wh = WarehouseCombo.SelectedItem?.ToString() ?? string.Empty;
        string status = row.StatusCombo?.SelectedItem?.ToString() ?? string.Empty;
        string ts = KpiTracking.RegistrationTimestamp();

        if (isBottom)
        {
            string loadCount = "";
            string lpCount = "";
            for (int i = 0; i < Math.Min(row.CountFields.Length, row.ExtraEntries.Count); i++)
            {
                if (row.CountFields[i] == "load_count")
                    loadCount = row.ExtraEntries[i].GetValue();
                else if (row.CountFields[i] == "lp_count")
                    lpCount = row.ExtraEntries[i].GetValue();
            }

            var prev = row.PendingCounts;
            KpiLogRecord rec;
            if (prev is not null
                && prev.JobId == jobId
                && prev.Warehouse == wh
                && prev.UserId == _userId
                && prev.UserCode == _userCode
                && prev.LoadCount == loadCount
                && prev.LpCount == lpCount)
            {
                rec = prev;
            }
            else
            {
                rec = new KpiLogRecord
                {
                    Timestamp = ts,
                    Task = row.Label,
                    JobId = jobId,
                    LoadCount = loadCount,
                    LpCount = lpCount,
                    UserId = _userId,
                    UserCode = _userCode,
                    Warehouse = KpiTracking.Warehouse(wh),
                    EventId = Guid.NewGuid().ToString()
                };
                row.PendingCounts = rec;
            }

            _ = Task.Run(() =>
            {
                if (SaveToSheet2(rec))
                {
                    Dispatcher.BeginInvoke(() =>
                    {
                        bool unchanged = _userId == rec.UserId
                            && _userCode == rec.UserCode
                            && KpiTracking.Norm(_currentWarehouse) == KpiTracking.Norm(rec.Warehouse)
                            && row.Entry.GetValue() == rec.JobId;
                        if (unchanged)
                            ResetAllRows();
                    });
                }
            });
        }
        else
        {
            if (SaveToSheet1(row.Label, jobId, status, wh, row.PendingEventId, ts))
                ResetAllRows();
        }
    }

    private bool SaveToSheet1(string section, string jobId, string status, string siteRaw, string? eventId, string timestamp)
    {
        if (_isPastDate)
        {
            ShowMessage("Cannot save - Past date (View Only)", MsgWarningColor, 2000);
            return false;
        }
        if (!_profileConfigured)
        {
            ShowMessage("Configure your KPI profile in Settings", MsgWarningColor, 5000);
            return false;
        }
        if (_gsManager is null || !_gsManager.Connected)
        {
            ShowMessage("Offline - Cannot submit manually", MsgErrorColor, 3000);
            return false;
        }

        string site = KpiTracking.Warehouse(siteRaw);
        if (string.IsNullOrEmpty(site))
        {
            ShowMessage("Select a warehouse", MsgWarningColor, 3000);
            return false;
        }

        try
        {
            KpiLogRecord item;
            if (!string.IsNullOrEmpty(eventId))
            {
                var existing = _outbox.Get(eventId);
                if (existing is null
                    || KpiTracking.Norm(existing.JobId) != KpiTracking.Norm(jobId)
                    || KpiTracking.Norm(existing.Task) != KpiTracking.Norm(section)
                    || KpiTracking.Norm(existing.Status) != KpiTracking.Norm(string.IsNullOrEmpty(status) ? "New" : status))
                {
                    throw new InvalidOperationException("Keep the original job and status when resolving a pending entry.");
                }
                item = _outbox.Resolve(eventId, site, _userId, _userCode);
            }
            else
            {
                item = _outbox.Capture(jobId, section, site, _userId, _userCode,
                    string.IsNullOrEmpty(status) ? "New" : status, timestamp);
            }

            if (item.Duplicate)
            {
                ShowMessage($"Already submitted ({item.Status}) in {(string.IsNullOrEmpty(item.Warehouse) ? "Unassigned" : item.Warehouse)} by {(string.IsNullOrEmpty(item.UserId) ? "another user" : item.UserId)}", MsgWarningColor, 5000);
                return false;
            }
            if (KpiTracking.Norm(item.UserId) != KpiTracking.Norm(_userId) || item.State == "conflict")
            {
                ShowMessage(string.IsNullOrEmpty(item.Error) ? $"Already assigned by {item.UserId}" : item.Error, MsgWarningColor, 5000);
                return false;
            }

            ShowMessage($"KPI {(item.State == "synced" ? "saved" : "pending sync")}: {item.JobId}",
                item.State == "synced" ? MsgSuccessColor : MsgInfoColor, 5000);
            SyncPendingAsync();
            return true;
        }
        catch (Exception ex)
        {
            ShowMessage(ex.Message, MsgErrorColor, 5000);
            AddActivityLog("KPI", $"Submission failed: {ex.Message}", "ERROR");
            return false;
        }
    }

    private bool SaveToSheet2(KpiLogRecord record)
    {
        if (_isPastDate || !_profileConfigured)
        {
            ShowMessage("Configure your KPI profile and select today before saving", MsgWarningColor, 5000);
            return false;
        }
        if (_gsManager is null || !_gsManager.Connected || _gsManager.Worksheet2 is null)
        {
            ShowMessage("Offline - Cannot save", MsgErrorColor, 3000);
            return false;
        }
        if (string.IsNullOrEmpty(record.Warehouse))
        {
            ShowMessage("Select a warehouse", MsgWarningColor, 3000);
            return false;
        }

        bool captured = false;
        var current = record;
        try
        {
            lock (_outbox.MutationLock)
            {
                current = _outbox.CaptureCounts(record);
                captured = true;
                if (_outbox.Get(current.EventId)?.State != "synced")
                {
                    var owner = new Sheet2Log(_gsManager.Worksheet2, LoadJobMap()).AppendOnce(current);
                    if (KpiTracking.Norm(owner) != KpiTracking.Norm(current.UserId))
                        throw new InvalidOperationException($"This KPI event belongs to {owner}.");
                    _outbox.Mark(current.EventId, "synced");
                }
            }

            Dispatcher.BeginInvoke(() =>
            {
                ShowMessage($"Saved [{current.Warehouse}]: {current.JobId}", MsgSuccessColor, 3000);
                _cacheTicks = 0;
                RefreshAllCounts();
            });
            return true;
        }
        catch (Exception ex)
        {
            if (captured)
            {
                lock (_outbox.MutationLock)
                {
                    var item = _outbox.Get(current.EventId);
                    if (item is not null && item.State != "cancelled")
                        _outbox.Mark(current.EventId, "pending", ex.Message);
                }
            }
            ShowMessage($"Save failed: {ex.Message}", MsgErrorColor, 5000);
            return false;
        }
    }

    private void HandleDelete(KpiRowControls row, bool isBottom)
    {
        var (valid, missing) = ValidateRowFields(row, isBottom);
        if (!valid)
        {
            ShowMessage("Required: " + string.Join(", ", missing), MsgErrorColor, 3000);
            return;
        }

        string jobId = row.Entry.GetValue();
        string site = WarehouseCombo.SelectedItem?.ToString() ?? string.Empty;

        if (isBottom)
        {
            string uid = _userId;
            _ = Task.Run(() =>
            {
                if (DeleteFromSheet2(jobId, row.Label, site, uid))
                {
                    Dispatcher.BeginInvoke(() =>
                    {
                        if (KpiTracking.Norm(site) == KpiTracking.Norm(_currentWarehouse)
                            && uid == _userId
                            && row.Entry.GetValue() == jobId)
                        {
                            ResetAllRows();
                        }
                    });
                }
            });
            return;
        }

        if (!_profileConfigured)
        {
            ShowMessage("Configure your KPI profile in Settings", MsgWarningColor, 5000);
            return;
        }

        string status = row.StatusCombo?.SelectedItem?.ToString() ?? string.Empty;
        string userId = _userId;
        string userCode = _userCode;

        _ = Task.Run(() =>
        {
            try
            {
                _outbox.RequestDelete(new KpiLogRecord
                {
                    JobId = jobId,
                    Task = row.Label,
                    Warehouse = site,
                    Status = status,
                    UserId = userId,
                    UserCode = userCode
                });
                Dispatcher.BeginInvoke(() =>
                {
                    ShowMessage($"Deletion pending sync: {jobId}", MsgInfoColor, 5000);
                    SyncPendingAsync();
                    if (KpiTracking.Norm(site) == KpiTracking.Norm(_currentWarehouse)
                        && userId == _userId
                        && userCode == _userCode
                        && row.Entry.GetValue() == jobId)
                    {
                        ResetAllRows();
                    }
                });
            }
            catch (Exception ex)
            {
                ShowMessage($"Delete failed: {ex.Message}", MsgErrorColor, 5000);
            }
        });
    }

    private bool DeleteFromSheet2(string jobId, string section, string site, string userId)
    {
        if (_isPastDate || !_profileConfigured)
            return false;
        if (_gsManager is null || !_gsManager.Connected || _gsManager.Worksheet2 is null)
        {
            ShowMessage("Offline - Cannot delete", MsgErrorColor, 3000);
            return false;
        }

        var rec = new KpiLogRecord
        {
            JobId = jobId,
            Task = section,
            Warehouse = string.IsNullOrEmpty(site) ? _currentWarehouse : site,
            UserId = userId
        };

        try
        {
            var log = new Sheet2Log(_gsManager.Worksheet2, LoadJobMap());
            int removed;
            lock (_outbox.MutationLock)
            {
                removed = log.Delete(rec);
                _outbox.Cancel(rec);
            }

            Dispatcher.BeginInvoke(() =>
            {
                ShowMessage(
                    removed > 0
                        ? $"Deleted [{rec.Warehouse}]: {jobId}"
                        : "No matching entry owned by this operator in the selected warehouse",
                    removed > 0 ? MsgSuccessColor : MsgWarningColor,
                    5000);
                _cacheTicks = 0;
                RefreshAllCounts();
            });
            return removed > 0;
        }
        catch (Exception ex)
        {
            ShowMessage($"Delete failed: {ex.Message}", MsgErrorColor, 5000);
            return false;
        }
    }

    #endregion

    #region Footer Actions (Refresh & Download KPI)

    private void Refresh_Click(object sender, RoutedEventArgs e)
    {
        ShowMessage("Refreshing...", MsgInfoColor, 1500);
        _cacheTicks = 0;
        if (!_isPastDate)
            ResetAllRows();
        else
            ShowMessage("View Only - Refreshing counts", MsgInfoColor, 1500);

        if (_gsManager?.Connected == true)
        {
            RefreshAllCounts();
            ShowMessage("Refreshed", MsgSuccessColor, 1500);
        }
        else
        {
            ShowMessage("Reconnecting...", MsgInfoColor, 3000);
            _ = Task.Run(() =>
            {
                _gsManager ??= new GoogleSheetsManager(GoogleSheetsManager.DefaultSpreadsheetUrl);
                bool ok = _gsManager.Connect();
                Dispatcher.BeginInvoke(() =>
                {
                    if (ok)
                    {
                        _cacheTicks = 0;
                        RefreshAllCounts();
                        ShowMessage("Connected & Refreshed", MsgSuccessColor, 2000);
                    }
                    else
                    {
                        ShowMessage("Connection failed", MsgErrorColor, 3000);
                    }
                });
            });
        }

        _autoRefreshTimer.Stop();
        _autoRefreshTimer.Start();
    }

    private void Download_Click(object sender, RoutedEventArgs e)
    {
        if (!_profileConfigured)
        {
            ShowMessage("Configure your KPI profile in Settings before downloading", MsgWarningColor, 5000);
            return;
        }
        if (_gsManager is null || !_gsManager.Connected || _gsManager.Worksheet1 is null || _gsManager.Worksheet2 is null)
        {
            ShowMessage("Offline - Cannot download", MsgErrorColor, 3000);
            return;
        }
        if (_downloadInProgress)
        {
            ShowMessage("Download already in progress", MsgWarningColor, 3000);
            return;
        }

        _downloadInProgress = true;
        DownloadBtn.IsEnabled = false;
        ShowMessage("Downloading all warehouses - fetching data...", MsgInfoColor, 60000);

        var store = new ConfigStore();
        string cfgCode = store.Get("kpi_user_code")?.Trim() ?? string.Empty;
        string cfgId = store.Get("kpi_user_id")?.Trim() ?? string.Empty;
        if (!string.IsNullOrEmpty(cfgCode))
            _userCode = cfgCode;
        if (!string.IsNullOrEmpty(cfgId))
            _userId = cfgId;

        var snapshot = (_userId, _userCode, _selectedDate);
        var mgr = _gsManager;
        _ = Task.Run(() =>
        {
            try
            {
                var v1 = new Sheet1Log(mgr.Worksheet1!).Read();
                var v2 = new Sheet2Log(mgr.Worksheet2!).Read();
                var jobMap = LoadJobMap();

                Dispatcher.BeginInvoke(() =>
                {
                    var picker = new Microsoft.Win32.OpenFolderDialog
                    {
                        Title = "Select folder to save KPI Excel (all warehouses)"
                    };
                    if (picker.ShowDialog(Window.GetWindow(this)) != true || string.IsNullOrWhiteSpace(picker.FolderName))
                    {
                        FinishDownload("Download cancelled", MsgWarningColor);
                        return;
                    }

                    string folder = picker.FolderName;
                    ShowMessage("Writing Excel for all warehouses...", MsgInfoColor, 60000);
                    _ = Task.Run(() =>
                    {
                        try
                        {
                            var res = KpiExcelExporter.GenerateUserExport(
                                folder, snapshot._userId, snapshot._userCode, snapshot._selectedDate, v1, v2, jobMap);
                            Dispatcher.BeginInvoke(() =>
                            {
                                FinishDownload(
                                    res.Success ? $"All warehouses saved: {Path.GetFileName(res.OutputPath)}" : res.Message,
                                    res.Success ? MsgSuccessColor : MsgErrorColor);
                            });
                            AddActivityLog("EXPORT", $"{res.Message} {res.OutputPath} | {string.Join(", ", res.Details)}", res.Success ? "SUCCESS" : "ERROR");
                        }
                        catch (Exception ex)
                        {
                            Dispatcher.BeginInvoke(() => FinishDownload($"Export failed: {ex.Message}", MsgErrorColor));
                        }
                    });
                });
            }
            catch (Exception ex)
            {
                Dispatcher.BeginInvoke(() => FinishDownload($"Download failed: {ex.Message}", MsgErrorColor));
            }
        });
    }

    private void FinishDownload(string message, string colorHex)
    {
        _downloadInProgress = false;
        DownloadBtn.IsEnabled = true;
        ShowMessage(message, colorHex, 8000);
    }

    #endregion

    #region Activity Log

    public void AddActivityLog(string category, string message, string level = "INFO")
    {
        string ts = KpiTracking.KpiNow().ToString("HH:mm:ss", CultureInfo.InvariantCulture);
        var entry = new KpiActivityEntry(ts, category, level, message);
        int count;
        lock (ActivityLogLock)
        {
            SharedActivityLogs.Add(entry);
            if (SharedActivityLogs.Count > 200)
                SharedActivityLogs.RemoveAt(0);
            count = SharedActivityLogs.Count;
        }

        if (!_closed)
            Dispatcher.BeginInvoke(() => AppendLogEntryToUi(entry, count));
    }

    private void PopulateInitialLogs()
    {
        List<KpiActivityEntry> snapshot;
        lock (ActivityLogLock)
            snapshot = SharedActivityLogs.ToList();

        foreach (var entry in snapshot)
            AppendLogEntryToUi(entry, snapshot.Count);
    }

    private void AppendLogEntryToUi(KpiActivityEntry entry, int totalCount)
    {
        if (_closed)
            return;

        string catPadded = (entry.Category.Length > 7 ? entry.Category[..7] : entry.Category).PadRight(7);
        string lvlPadded = (entry.Level.Length > 7 ? entry.Level[..7] : entry.Level).PadRight(7);
        var lvlBrush = entry.Level switch
        {
            "SUCCESS" => LogSuccessBrush,
            "ERROR" => LogErrorBrush,
            "WARN" => LogWarnBrush,
            _ => LogInfoBrush
        };

        var p = new Paragraph { Margin = new Thickness(0, 1, 0, 1) };
        p.Inlines.Add(new Run($"{entry.Timestamp} ") { Foreground = LogTsBrush });
        p.Inlines.Add(new Run($"[{catPadded}] ") { Foreground = LogCatBrush, FontWeight = FontWeights.Bold });
        p.Inlines.Add(new Run($"[{lvlPadded}] ") { Foreground = lvlBrush, FontWeight = FontWeights.Bold });
        p.Inlines.Add(new Run(entry.Message) { Foreground = LogMsgBrush });

        LogRichBox.Document.Blocks.Add(p);
        LogRichBox.ScrollToEnd();
        LogCountBadge.Text = $"{totalCount} event{(totalCount == 1 ? "" : "s")}";
    }

    private void ToggleLog_Click(object sender, RoutedEventArgs e)
    {
        if (_logExpanded)
        {
            LogRichBox.Visibility = Visibility.Collapsed;
            LogToggleBtn.Content = "▸ Show";
            _logExpanded = false;
        }
        else
        {
            LogRichBox.Visibility = Visibility.Visible;
            LogToggleBtn.Content = "▾ Hide";
            _logExpanded = true;
        }
    }

    private void CopyLog_Click(object sender, RoutedEventArgs e)
    {
        List<string> lines;
        lock (ActivityLogLock)
            lines = SharedActivityLogs.Select(l => $"[{l.Timestamp}] [{l.Category}] [{l.Level}] {l.Message}").ToList();

        if (lines.Count == 0)
        {
            ShowMessage("Activity log is empty", MsgInfoColor, 1500);
            return;
        }

        System.Windows.Clipboard.SetText(string.Join("\n", lines));
        ShowMessage("Activity log copied to clipboard", MsgSuccessColor, 2000);
    }

    private void ClearLog_Click(object sender, RoutedEventArgs e)
    {
        lock (ActivityLogLock)
            SharedActivityLogs.Clear();

        LogRichBox.Document.Blocks.Clear();
        LogCountBadge.Text = "0 events";
        AddActivityLog("SYSTEM", "Activity log cleared", "INFO");
    }

    #endregion
}
