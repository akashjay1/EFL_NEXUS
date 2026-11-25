using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Net.Sockets;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Shapes;
using System.Windows.Threading;
using EflNexus.App.Controllers;
using EflNexus.App.Dialogs;
using EflNexus.App.Views;
using EflNexus.App.Windows;
using EflNexus.Core.Infrastructure;
using EflNexus.Core.Kpi;
using EflNexus.Core.Monitoring;
using EflNexus.Core.OutlookEmail;
using EflNexus.Core.PendingJobs;
using KorberAuditShip.Models;
using KorberAuditShip.Services;
using KorberAuditShip.ViewModels;
using KorberAuditShip.Views;
using MediaColor = System.Windows.Media.Color;
using MediaPoint = System.Windows.Point;
using MediaSize = System.Windows.Size;
using Path = System.IO.Path;
using SolidBrush = System.Windows.Media.SolidColorBrush;

namespace EflNexus.App;

public partial class MainWindow : Window
{
    public const string GithubUser = "akashjay1";
    public const string GithubRepo = "EFL_NEXUS";

    private const double SidebarWidthExpanded = 230;
    private const double SidebarWidthCollapsed = 64;

    private static readonly (string Key, string Icon, string Label)[] NavItems =
    [
        ("dashboard", "🏠", "Dashboard"),
        ("tool1", "🔧", "Korber Automation"),
        ("tool2", "⚡", "Load Reconciliation"),
        ("tool3", "📧", "Outlook Email Sender"),
        ("tool4", "👥", "User KPI"),
        ("tool5", "🚚", "Korber AuditShip"),
        ("tool6", "🔗", "Pending Jobs"),
        ("packinglist", "📋", "Packing List Generator"),
        ("whatsapp", "WA", "WhatsApp"),
        ("settings", "⚙", "Settings")
    ];

    private static readonly Dictionary<string, string> ToolDisplayNames = new(StringComparer.Ordinal)
    {
        ["tool1"] = "Korber Automation",
        ["tool2"] = "Load Reconciliation",
        ["tool3"] = "Outlook Email Sender",
        ["tool4"] = "User KPI",
        ["tool5"] = "Korber AuditShip",
        ["tool6"] = "Pending Jobs",
        ["packinglist"] = "Packing List Generator",
        ["whatsapp"] = "WhatsApp"
    };

    private static readonly SolidBrush SidebarBgBrush = new(MediaColor.FromRgb(0x0B, 0x14, 0x20));
    private static readonly SolidBrush SidebarBgHoverBrush = new(MediaColor.FromRgb(0x13, 0x23, 0x3A));
    private static readonly SolidBrush SidebarBgActiveBrush = new(MediaColor.FromRgb(0x16, 0x2E, 0x4C));
    private static readonly SolidBrush SidebarActiveAccentBrush = new(MediaColor.FromRgb(0x00, 0xE5, 0xFF));
    private static readonly SolidBrush SidebarFgBrush = new(MediaColor.FromRgb(0x94, 0xA3, 0xB8));
    private static readonly SolidBrush SidebarFgActiveBrush = new(Colors.White);

    private static readonly SolidBrush SidebarOnlineBg = new(MediaColor.FromRgb(0x10, 0x1D, 0x2D));
    private static readonly SolidBrush SidebarOfflineBg = new(MediaColor.FromRgb(0x26, 0x14, 0x18));
    private static readonly SolidBrush SidebarOnlineFg = new(MediaColor.FromRgb(0x49, 0xCF, 0x9E));
    private static readonly SolidBrush SidebarOfflineFg = new(MediaColor.FromRgb(0xEF, 0x44, 0x44));

    private sealed class NavButtonRefs
    {
        public required Grid Row { get; init; }
        public required Border Accent { get; init; }
        public TextBlock? IconLabel { get; init; }
        public required TextBlock Label { get; init; }
    }

    private static readonly HttpClient UpdateHttp = new() { Timeout = TimeSpan.FromSeconds(5) };

    private readonly ConfigStore _configStore;
    private readonly Dictionary<string, Grid> _pageHosts = new(StringComparer.Ordinal);
    private readonly Dictionary<string, NavButtonRefs> _navButtons = new(StringComparer.Ordinal);
    private readonly CancellationTokenSource _networkCts = new();
    private readonly DispatcherTimer _spinnerTimer;
    private readonly DispatcherTimer _presenceUiTimer;
    private readonly bool _enableBackgroundServices;

    private DashboardView? _dashboardView;
    private SettingsView? _settingsView;
    private KorberToolView? _tool1View;
    private ReconciliationView? _tool2View;
    private OutlookEmailView? _tool3View;
    private KpiView? _tool4View;
    private KorberAuditShipView? _tool5View;
    private PendingJobsView? _tool6View;
    private PackingListView? _packingListView;
    private WhatsAppController? _whatsappController;
    private WhatsAppView? _whatsappView;

    private string? _tool1Error;
    private string? _tool2Error;
    private string? _tool3Error;
    private string? _tool4Error;
    private string? _tool5Error;
    private string? _tool6Error;
    private string? _packingListError;
    private string? _whatsappError;

    private MonitoringService? _monitoringService;
    private readonly List<MonitoringService> _retiringServices = [];
    private string _presenceStatus = "Tracking disabled.";
    private readonly string _presenceDeviceName = OperatorPresence.DeviceName();
    private bool _screenStreamerStarted;
    private bool _inputHooksAttached;

    private Dictionary<(string JobId, string Warehouse), string>? _jobAssignments;
    private JobMapEntry? _activeReconciliationJob;

    private string _activePage = "dashboard";
    private bool _sidebarCollapsed;
    private bool _isOnline = true;
    private double _spinnerAngle;
    private bool _spinnerRunning;
    private bool _closing;
    private bool _readyToClose;

    public string ActivePage => _activePage;

    public MainWindow() : this(null, null, true)
    {
    }

    public MainWindow(SplashWindow? splash = null) : this(splash, null, true)
    {
    }

    internal MainWindow(SplashWindow? splash, ConfigStore? configStoreOverride, bool enableBackgroundServices)
    {
        InitializeComponent();
        App.TrySetWindowIcon(this);
        _enableBackgroundServices = enableBackgroundServices;

        if (splash is null)
            WindowState = WindowState.Maximized;

        splash?.SetStatus("Preparing the interface...", 40);

        _configStore = configStoreOverride ?? new ConfigStore();
        LoadSidebarLogo();
        SidebarVersionText.Text = $"v{AppPaths.ReadAppVersion()}";

        _spinnerTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(75) };
        _spinnerTimer.Tick += (_, _) => RenderSpinnerFrame();

        _presenceUiTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(1000) };
        _presenceUiTimer.Tick += (_, _) => RefreshPresenceStatusLabel();

        splash?.SetStatus("Building navigation and dashboard...", 60);

        MapPageHosts();
        BuildSidebarNav();
        BuildStaticPages();

        ShowPage("dashboard");

        splash?.SetStatus("Starting background services...", 90);

        if (_enableBackgroundServices)
        {
            ScheduleAfter(250, StartWhatsAppController);
            _ = Task.Run(() => NetworkMonitorLoopAsync(_networkCts.Token));
            ScheduleAfter(150, StartBackgroundWarmup);
            ScheduleAfter(600, PrewarmTool4);
            ScheduleAfter(800, CheckReleaseNotesOnStartup);
            ScheduleAfter(2000, () => CheckForUpdates(silent: true));
            ScheduleAfter(300, StartPresenceTracking);
            _presenceUiTimer.Start();
        }
    }

    private void ScheduleAfter(int delayMs, Action action)
    {
        var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(delayMs) };
        timer.Tick += (_, _) =>
        {
            timer.Stop();
            if (!_closing)
                action();
        };
        timer.Start();
    }

    private void CheckReleaseNotesOnStartup()
    {
        if (ReleaseNotesManager.ShouldShowOnStartup())
        {
            ReleaseNotesManager.ShowReleaseNotes(this);
        }
    }

    private void SidebarVersionText_Click(object sender, MouseButtonEventArgs e)
    {
        ReleaseNotesManager.ShowReleaseNotes(this, force: true);
    }

    private void LoadSidebarLogo()
    {
        try
        {
            var iconPath = AppPaths.ResolveResourcePath("icon_2.ico");
            if (!File.Exists(iconPath))
                iconPath = AppPaths.ResolveResourcePath("icon.ico");
            if (!File.Exists(iconPath))
                return;

            var bmp = new BitmapImage();
            bmp.BeginInit();
            bmp.CacheOption = BitmapCacheOption.OnLoad;
            bmp.DecodePixelWidth = 24;
            bmp.UriSource = new Uri(iconPath, UriKind.Absolute);
            bmp.EndInit();
            bmp.Freeze();

            BrandLogoImage.Source = bmp;
            BrandLogoImage.Visibility = Visibility.Visible;
            BrandLogoCollapsedImage.Source = bmp;
        }
        catch { }
    }

    private void MapPageHosts()
    {
        _pageHosts["dashboard"] = PageDashboardHost;
        _pageHosts["tool1"] = PageTool1Host;
        _pageHosts["tool2"] = PageTool2Host;
        _pageHosts["tool3"] = PageTool3Host;
        _pageHosts["tool4"] = PageTool4Host;
        _pageHosts["tool5"] = PageTool5Host;
        _pageHosts["tool6"] = PageTool6Host;
        _pageHosts["packinglist"] = PagePackingListHost;
        _pageHosts["whatsapp"] = PageWhatsappHost;
        _pageHosts["settings"] = PageSettingsHost;
    }

    private void BuildSidebarNav()
    {
        NavItemsPanel.Children.Clear();
        _navButtons.Clear();

        foreach (var (key, icon, label) in NavItems)
        {
            _navButtons[key] = CreateNavButton(key, icon, label);
            NavItemsPanel.Children.Add(_navButtons[key].Row);
        }

        BrandExpandedPanel.Visibility = _sidebarCollapsed ? Visibility.Collapsed : Visibility.Visible;
        BrandCollapsedPanel.Visibility = _sidebarCollapsed ? Visibility.Visible : Visibility.Collapsed;
        bool hasLogo = BrandLogoCollapsedImage.Source is not null;
        BrandLogoCollapsedImage.Visibility = hasLogo ? Visibility.Visible : Visibility.Collapsed;
        BrandCollapsedText.Visibility = hasLogo ? Visibility.Collapsed : Visibility.Visible;

        SidebarStatusBox.Visibility = _sidebarCollapsed ? Visibility.Collapsed : Visibility.Visible;
        CollapseToggleText.Text = _sidebarCollapsed ? "▶" : "◀   Collapse";
        CollapseToggleText.HorizontalAlignment = _sidebarCollapsed
            ? System.Windows.HorizontalAlignment.Center
            : System.Windows.HorizontalAlignment.Left;

        ApplyNetworkStatusToSidebar();
        RefreshNavHighlight();

        if (_whatsappController is not null)
            RefreshWhatsAppBadge(_whatsappController);
    }

    private NavButtonRefs CreateNavButton(string key, string icon, string label)
    {
        var row = new Grid
        {
            Background = SidebarBgBrush,
            Cursor = System.Windows.Input.Cursors.Hand,
            Margin = new Thickness(8, 3, 8, 3)
        };
        row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(3) });
        if (_sidebarCollapsed)
        {
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        }
        else
        {
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        }

        var accent = new Border { Background = SidebarBgBrush };
        Grid.SetColumn(accent, 0);
        row.Children.Add(accent);

        TextBlock? iconLbl = null;
        TextBlock textLbl;

        if (_sidebarCollapsed)
        {
            textLbl = new TextBlock
            {
                Text = icon,
                Foreground = SidebarFgBrush,
                FontFamily = new System.Windows.Media.FontFamily("Segoe UI"),
                FontSize = key == "whatsapp" ? 11 : 15,
                TextAlignment = TextAlignment.Center,
                HorizontalAlignment = System.Windows.HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center,
                Padding = new Thickness(6, 9, 6, 9)
            };
            Grid.SetColumn(textLbl, 1);
            row.Children.Add(textLbl);
        }
        else
        {
            iconLbl = new TextBlock
            {
                Text = icon,
                Foreground = SidebarFgBrush,
                FontFamily = new System.Windows.Media.FontFamily("Segoe UI"),
                FontSize = 14,
                Width = 32,
                TextAlignment = TextAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center,
                Padding = new Thickness(0, 9, 0, 9)
            };
            Grid.SetColumn(iconLbl, 1);
            row.Children.Add(iconLbl);

            textLbl = new TextBlock
            {
                Text = label,
                Foreground = SidebarFgBrush,
                FontFamily = new System.Windows.Media.FontFamily("Segoe UI"),
                FontSize = 12,
                FontWeight = FontWeights.Bold,
                VerticalAlignment = VerticalAlignment.Center,
                Padding = new Thickness(6, 9, 6, 9)
            };
            Grid.SetColumn(textLbl, 2);
            row.Children.Add(textLbl);
        }

        var refs = new NavButtonRefs
        {
            Row = row,
            Accent = accent,
            IconLabel = iconLbl,
            Label = textLbl
        };

        row.MouseLeftButtonUp += (_, _) => ShowPage(key);
        row.MouseEnter += (_, _) =>
        {
            if (_activePage != key)
            {
                row.Background = SidebarBgHoverBrush;
                if (iconLbl is not null) iconLbl.Foreground = SidebarFgActiveBrush;
                textLbl.Foreground = SidebarFgActiveBrush;
            }
        };
        row.MouseLeave += (_, _) =>
        {
            if (_activePage != key)
            {
                row.Background = SidebarBgBrush;
                if (iconLbl is not null) iconLbl.Foreground = SidebarFgBrush;
                textLbl.Foreground = SidebarFgBrush;
            }
        };

        return refs;
    }

    private void RefreshNavHighlight()
    {
        foreach (var (key, refs) in _navButtons)
        {
            bool active = string.Equals(key, _activePage, StringComparison.Ordinal);
            refs.Row.Background = active ? SidebarBgActiveBrush : SidebarBgBrush;
            refs.Accent.Background = active ? SidebarActiveAccentBrush : SidebarBgBrush;
            var fg = active ? SidebarFgActiveBrush : SidebarFgBrush;
            if (refs.IconLabel is not null)
                refs.IconLabel.Foreground = fg;
            refs.Label.Foreground = fg;
        }
    }

    private void CollapseToggle_Click(object sender, MouseButtonEventArgs e)
    {
        _sidebarCollapsed = !_sidebarCollapsed;
        SidebarColumn.Width = new GridLength(_sidebarCollapsed ? SidebarWidthCollapsed : SidebarWidthExpanded);
        BuildSidebarNav();
    }

    private void CollapseToggle_MouseEnter(object sender, System.Windows.Input.MouseEventArgs e)
    {
        CollapseToggleBtn.Background = SidebarBgHoverBrush;
        CollapseToggleText.Foreground = SidebarFgActiveBrush;
    }

    private void CollapseToggle_MouseLeave(object sender, System.Windows.Input.MouseEventArgs e)
    {
        CollapseToggleBtn.Background = SidebarBgBrush;
        CollapseToggleText.Foreground = SidebarFgBrush;
    }

    private void BuildStaticPages()
    {
        _dashboardView = new DashboardView
        {
            OnNavigateRequested = ShowPage
        };
        _dashboardView.SetOnlineStatus(_isOnline);
        PageDashboardHost.Children.Add(_dashboardView);

        _settingsView = new SettingsView(_configStore)
        {
            OnCheckUpdatesRequested = () => CheckForUpdates(silent: false),
            OnKpiProfileSaved = profile =>
            {
                _tool4View?.SetProfile(profile);
                RefreshPresenceContext();
            },
            OnOpenPresenceSettingsRequested = () =>
            {
                var dlg = new PresenceSettingsDialog(this, _monitoringService);
                dlg.ShowDialog();
            },
            OnTool6SettingsChanged = (loginUrl, username, password, reconUrl, refreshSec, soundEnabled, soundPath) =>
            {
                _tool6View?.SetConnectionSettings(loginUrl, username, password, reconUrl, refreshSec, soundEnabled, soundPath);
            },
            OnGoogleSheetsSaved = () =>
            {
                _tool3View?.RefreshCounts();
            },
            OnCacheCleared = () =>
            {
                _tool3View?.RefreshAfterClearCache();
            }
        };
        _settingsView.UpdatePresenceStatus(_presenceStatus);
        PageSettingsHost.Children.Add(_settingsView);
    }

    public void ShowPage(string key)
    {
        if (!_pageHosts.ContainsKey(key))
            return;

        _activePage = key;
        RefreshPresenceContext();
        RefreshNavHighlight();

        _whatsappView?.SetVisible(key == "whatsapp");
        if (key != "tool6")
            _tool6View?.SetBrowserVisible(false);

        bool loaded = key switch
        {
            "tool1" => _tool1View is not null || _tool1Error is not null,
            "tool2" => _tool2View is not null || _tool2Error is not null,
            "tool3" => _tool3View is not null || _tool3Error is not null,
            "tool4" => _tool4View is not null || _tool4Error is not null,
            "tool5" => _tool5View is not null || _tool5Error is not null,
            "tool6" => _tool6View is not null || _tool6Error is not null,
            "packinglist" => _packingListView is not null || _packingListError is not null,
            "whatsapp" => _whatsappView is not null || _whatsappError is not null,
            _ => true
        };

        ActivateHost(key);

        if (!loaded)
        {
            ShowLoadingOverlay(key);
            ScheduleAfter(50, () => DeferredToolLoad(key));
            return;
        }

        if (key == "tool2" && _tool2View is not null)
        {
            try { _tool2View.RefreshJobQueue(); } catch { }
        }
        else if (key == "tool6")
        {
            _tool6View?.SetBrowserVisible(true);
        }
    }

    private void ActivateHost(string key)
    {
        foreach (var (k, host) in _pageHosts)
            host.Visibility = string.Equals(k, key, StringComparison.Ordinal) ? Visibility.Visible : Visibility.Collapsed;
    }

    private void DeferredToolLoad(string key)
    {
        switch (key)
        {
            case "tool1": EnsureTool1(); break;
            case "tool2": EnsureTool2(); break;
            case "tool3": EnsureTool3(); break;
            case "tool4": EnsureTool4(); break;
            case "tool5": EnsureTool5(); break;
            case "tool6": EnsureTool6(); break;
            case "packinglist": EnsurePackingList(); break;
            case "whatsapp": EnsureWhatsApp(); break;
        }
        HideLoadingOverlay();
    }

    private void ShowLoadingOverlay(string key)
    {
        var toolName = ToolDisplayNames.GetValueOrDefault(key, "Module");
        LoadingTitleText.Text = $"Loading {toolName}...";
        _spinnerAngle = 0;
        _spinnerRunning = true;
        RenderSpinnerFrame();
        LoadingOverlay.Visibility = Visibility.Visible;
        _spinnerTimer.Start();
    }

    private void HideLoadingOverlay()
    {
        _spinnerRunning = false;
        _spinnerTimer.Stop();
        LoadingOverlay.Visibility = Visibility.Collapsed;
        SpinnerCanvas.Children.Clear();
    }

    private void RenderSpinnerFrame()
    {
        if (!_spinnerRunning)
            return;

        SpinnerCanvas.Children.Clear();
        const double size = 52;
        const double cx = size / 2.0;
        const double cy = size / 2.0;
        const double r = size / 2.0 - 5.0;
        const int segments = 12;
        const double segAngle = 360.0 / segments;

        for (int i = 0; i < segments; i++)
        {
            double startDeg = _spinnerAngle + i * segAngle;
            double endDeg = startDeg + segAngle - 4.0;
            double alpha = Math.Max(0.06, 1.0 - (i / (double)segments) * 0.92);
            var strokeColor = BlendHex(0x16, 0x2E, 0x4C, 0xFA, 0xF8, 0xF2, alpha);

            double startRad = startDeg * Math.PI / 180.0;
            double endRad = endDeg * Math.PI / 180.0;

            var p1 = new MediaPoint(cx + r * Math.Cos(startRad), cy - r * Math.Sin(startRad));
            var p2 = new MediaPoint(cx + r * Math.Cos(endRad), cy - r * Math.Sin(endRad));

            var fig = new PathFigure { StartPoint = p1, IsClosed = false };
            fig.Segments.Add(new ArcSegment(p2, new MediaSize(r, r), 0, false, SweepDirection.Counterclockwise, true));
            var geom = new PathGeometry();
            geom.Figures.Add(fig);

            var path = new System.Windows.Shapes.Path
            {
                Data = geom,
                Stroke = new SolidBrush(strokeColor),
                StrokeThickness = 4,
                StrokeStartLineCap = PenLineCap.Flat,
                StrokeEndLineCap = PenLineCap.Flat
            };
            SpinnerCanvas.Children.Add(path);
        }

        _spinnerAngle = (_spinnerAngle - 30) % 360;
    }

    private static MediaColor BlendHex(byte r1, byte g1, byte b1, byte r2, byte g2, byte b2, double alpha)
    {
        byte r = (byte)(r1 * alpha + r2 * (1.0 - alpha));
        byte g = (byte)(g1 * alpha + g2 * (1.0 - alpha));
        byte b = (byte)(b1 * alpha + b2 * (1.0 - alpha));
        return MediaColor.FromRgb(r, g, b);
    }

    internal void EnsureTool1()
    {
        if (_tool1View is not null || _tool1Error is not null)
            return;
        try
        {
            _tool1View = new KorberToolView
            {
                OpenWhatsAppInboxCallback = OpenWhatsAppInbox
            };
            PageTool1Host.Children.Clear();
            PageTool1Host.Children.Add(_tool1View);
        }
        catch (Exception ex)
        {
            _tool1Error = ex.ToString();
            _tool1View = null;
            ShowToolError(PageTool1Host, "Tool 1: Korber Automation", _tool1Error);
        }
    }

    internal void EnsureTool2()
    {
        if (_tool2View is not null || _tool2Error is not null)
            return;
        try
        {
            _tool2View = new ReconciliationView
            {
                IsEmbedded = true,
                ActiveJobContext = _activeReconciliationJob,
                OnEmbeddedExit = () => ShowPage("dashboard")
            };
            PageTool2Host.Children.Clear();
            PageTool2Host.Children.Add(_tool2View);
        }
        catch (Exception ex)
        {
            _tool2Error = ex.ToString();
            _tool2View = null;
            ShowToolError(PageTool2Host, "Tool 2: Load Reconciliation", _tool2Error);
        }
    }

    internal void EnsureTool3()
    {
        if (_tool3View is not null || _tool3Error is not null)
            return;
        try
        {
            _tool3View = new OutlookEmailView(_configStore, () => ShowPage("settings"))
            {
                OnGatepassSent = (sendType, gatepass, warehouse) =>
                {
                    EnsureTool4();
                    _tool4View?.RecordSentGatepass(sendType, gatepass, warehouse);
                }
            };
            PageTool3Host.Children.Clear();
            PageTool3Host.Children.Add(_tool3View);
        }
        catch (Exception ex)
        {
            _tool3Error = ex.ToString();
            _tool3View = null;
            ShowToolError(PageTool3Host, "Tool 3: Outlook Email Sender", _tool3Error);
        }
    }

    private void PrewarmTool4()
    {
        if (_tool4View is null && _tool4Error is null)
        {
            try { EnsureTool4(); } catch { }
        }
    }

    internal void EnsureTool4()
    {
        if (_tool4View is not null || _tool4Error is not null)
            return;
        try
        {
            var profile = KpiProfile.LoadSavedProfile(_configStore.FilePath);
            _tool4View = new KpiView(
                profile,
                onOpenSettings: () => ShowPage("settings"),
                onKpiStatus: OnKpiStatus,
                onAssignmentsChanged: OnJobAssignmentsChanged);
            _tool4View.OnReconciliationQueueUpdated = () => _tool2View?.RefreshJobQueue();
            PageTool4Host.Children.Clear();
            PageTool4Host.Children.Add(_tool4View);
        }
        catch (Exception ex)
        {
            _tool4Error = ex.ToString();
            _tool4View = null;
            ShowToolError(PageTool4Host, "Tool 4: User KPI", _tool4Error);
        }
    }

    internal void EnsureTool5()
    {
        if (_tool5View is not null || _tool5Error is not null)
            return;
        try
        {
            Func<KorberCredentials?>? resolver = null;
            Action<string, string, string>? saver = null;

            if (_configStore != null)
            {
                resolver = () =>
                {
                    var u = _configStore.GetAuditshipUser();
                    var p = _configStore.GetAuditshipPass();
                    var f = _configStore.GetAuditshipForkId();
                    if (string.IsNullOrWhiteSpace(f)) f = u;
                    return (!string.IsNullOrWhiteSpace(u) && !string.IsNullOrWhiteSpace(p))
                        ? new KorberCredentials(u, p, f, "EFL NEXUS Settings")
                        : null;
                };
                saver = (u, p, f) =>
                {
                    _configStore.SaveKeyValues(
                        ("auditship_user", u),
                        ("auditship_pass", p),
                        ("auditship_fork_id", f));
                };
            }

            var credentialService = new CredentialService(resolver, saver);
            var spreadsheetService = new SpreadsheetService();
            var pdfExportService = new PdfExportService();
            var browserFactory = new EdgeBrowserService();
            var automationService = new KorberAutomationService(browserFactory);

            _tool5View = new KorberAuditShipView();
            var dialogService = new WpfDialogService(this);

            var viewModel = new MainViewModel(
                spreadsheetService,
                pdfExportService,
                credentialService,
                automationService,
                dialogService);

            _tool5View.DataContext = viewModel;

            PageTool5Host.Children.Clear();
            PageTool5Host.Children.Add(_tool5View);
        }
        catch (Exception ex)
        {
            _tool5Error = ex.ToString();
            _tool5View = null;
            ShowToolError(PageTool5Host, "Tool 5: Korber AuditShip", _tool5Error);
        }
    }

    internal void EnsureTool6()
    {
        if (_tool6View is not null || _tool6Error is not null)
            return;
        try
        {
            _tool6View = new PendingJobsView(
                _configStore,
                onOpenSettings: () => ShowPage("settings"),
                onJobStarted: PrefillKpiForJob,
                onCreateGatepass: CreateGatepassForJob,
                onJobsChanged: OnReconciliationJobsChanged);
            if (_jobAssignments is not null)
                _tool6View.SetJobAssignments(_jobAssignments);
            _tool6View.SetBrowserVisible(_activePage == "tool6");
            PageTool6Host.Children.Clear();
            PageTool6Host.Children.Add(_tool6View);
        }
        catch (Exception ex)
        {
            _tool6Error = ex.ToString();
            _tool6View = null;
            ShowToolError(PageTool6Host, "Tool 6: Pending Jobs", _tool6Error);
        }
    }

    internal void EnsurePackingList()
    {
        if (_packingListView is not null || _packingListError is not null)
            return;
        try
        {
            _packingListView = new PackingListView();
            PagePackingListHost.Children.Clear();
            PagePackingListHost.Children.Add(_packingListView);
        }
        catch (Exception ex)
        {
            _packingListError = ex.ToString();
            _packingListView = null;
            ShowToolError(PagePackingListHost, "Packing List Generator", _packingListError);
        }
    }

    private void StartWhatsAppController()
    {
        if (_whatsappController is not null)
            return;
        try
        {
            _whatsappController = new WhatsAppController(Dispatcher, onChange: RefreshWhatsAppBadge);
            RefreshWhatsAppBadge(_whatsappController);
        }
        catch (Exception ex)
        {
            _whatsappError = ex.ToString();
        }
    }

    private void RefreshWhatsAppBadge(WhatsAppController controller)
    {
        if (!_navButtons.TryGetValue("whatsapp", out var refs))
            return;

        long count = controller.NewCount + controller.GrnNewCount;
        refs.Label.Text = _sidebarCollapsed
            ? $"WA {count}"
            : $"WhatsApp ({count})\n{controller.State}";
    }

    internal void EnsureWhatsApp()
    {
        if (_whatsappView is not null)
            return;
        StartWhatsAppController();
        if (_whatsappController is null)
        {
            ShowToolError(PageWhatsappHost, "WhatsApp", _whatsappError ?? "Could not open inbox storage.");
            return;
        }

        try
        {
            _whatsappView = new WhatsAppView(_whatsappController);
            _whatsappView.SetVisible(_activePage == "whatsapp");
            PageWhatsappHost.Children.Clear();
            PageWhatsappHost.Children.Add(_whatsappView);
        }
        catch (Exception ex)
        {
            _whatsappError = ex.ToString();
            _whatsappView = null;
            ShowToolError(PageWhatsappHost, "WhatsApp", _whatsappError);
        }
    }

    public void OpenWhatsAppInbox()
    {
        EnsureWhatsApp();
        ShowPage("whatsapp");
        _whatsappView?.ShowInbox();
    }

    private static void ShowToolError(Grid host, string toolName, string errorText)
    {
        host.Children.Clear();
        var border = new Border
        {
            Background = Brushes.White,
            BorderBrush = new SolidBrush(MediaColor.FromRgb(0xEF, 0x44, 0x44)),
            BorderThickness = new Thickness(1),
            Padding = new Thickness(24),
            Margin = new Thickness(40)
        };
        var dock = new DockPanel();
        var title = new TextBlock
        {
            Text = $"⚠️  {toolName} could not start",
            FontFamily = new System.Windows.Media.FontFamily("Segoe UI"),
            FontSize = 18,
            FontWeight = FontWeights.Bold,
            Foreground = new SolidBrush(MediaColor.FromRgb(0xB9, 0x1C, 0x1C))
        };
        DockPanel.SetDock(title, Dock.Top);
        dock.Children.Add(title);

        var sub = new TextBlock
        {
            Text = "A required dependency or module error occurred. Technical details below:",
            FontFamily = new System.Windows.Media.FontFamily("Segoe UI"),
            FontSize = 13,
            Foreground = new SolidBrush(MediaColor.FromRgb(0x64, 0x74, 0x8B)),
            Margin = new Thickness(0, 6, 0, 12)
        };
        DockPanel.SetDock(sub, Dock.Top);
        dock.Children.Add(sub);

        var tb = new System.Windows.Controls.TextBox
        {
            Text = errorText,
            IsReadOnly = true,
            TextWrapping = TextWrapping.Wrap,
            VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
            FontFamily = new System.Windows.Media.FontFamily("Consolas"),
            FontSize = 12,
            Background = new SolidBrush(MediaColor.FromRgb(0xF8, 0xFA, 0xFC)),
            Foreground = new SolidBrush(MediaColor.FromRgb(0x0F, 0x17, 0x2A)),
            Padding = new Thickness(10)
        };
        dock.Children.Add(tb);

        border.Child = dock;
        host.Children.Add(border);
    }

    private void CreateGatepassForJob(PortalJobRecord record)
    {
        var jobId = (record.JobId ?? string.Empty).Trim();
        if (!jobId.StartsWith("OUT_", StringComparison.OrdinalIgnoreCase) &&
            !jobId.StartsWith("IN_", StringComparison.OrdinalIgnoreCase))
        {
            System.Windows.MessageBox.Show(this, $"Job ID '{jobId}' must start with 'OUT_' or 'IN_'.", "Create Gatepass", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        Dispatcher.BeginInvoke(() =>
        {
            EnsureTool1();
            var lanes = _tool1View?.GetLanes();
            var laneA = lanes is not null && lanes.TryGetValue("Lane A", out var l) ? l : null;
            if (laneA is null)
            {
                System.Windows.MessageBox.Show(this, "Korber Automation (Tool 1) could not be loaded.", "Tool 1 Unavailable", MessageBoxButton.OK, MessageBoxImage.Error);
                return;
            }

            if (jobId.StartsWith("OUT_", StringComparison.OrdinalIgnoreCase))
            {
                var deliv = (record.DeliveryLocation ?? string.Empty).Trim();
                if (string.IsNullOrEmpty(deliv) || deliv == "-") deliv = "N/A";
                var seal = (record.Seal ?? string.Empty).Trim();
                if (string.IsNullOrEmpty(seal) || seal == "-") seal = "N/A";

                laneA.PrefillGdn(
                    warehouse: record.Warehouse ?? string.Empty,
                    client: record.Client ?? string.Empty,
                    gatepass: record.Gatepass ?? string.Empty,
                    deliveryLocation: deliv,
                    seal: seal);
            }
            else
            {
                laneA.PrefillGrn(
                    warehouse: record.Warehouse ?? string.Empty,
                    gatepass: record.Gatepass ?? string.Empty);
            }

            ShowPage("tool1");
        });
    }

    private void PrefillKpiForJob(PortalJobRecord record)
    {
        var jobId = (record.JobId ?? string.Empty).Trim();
        var mapped = new JobMapEntry
        {
            JobId = jobId,
            WarfId = record.WarfId ?? string.Empty,
            Client = (record.Client ?? string.Empty).Trim(),
            Gatepass = (record.Gatepass ?? string.Empty).Trim(),
            Warehouse = (record.Warehouse ?? string.Empty).Trim(),
            Status = record.Status ?? string.Empty
        };

        _activeReconciliationJob = mapped;
        if (_tool2View is not null)
        {
            var prev = _tool2View.LastReportJobId;
            if (!string.IsNullOrEmpty(prev) && !string.Equals(prev, jobId, StringComparison.OrdinalIgnoreCase))
            {
                _tool2View.LastOutputFile = null;
                _tool2View.LastReportJobId = null;
            }
            _tool2View.ActiveJobContext = mapped;
        }

        if (!jobId.StartsWith("OUT_", StringComparison.OrdinalIgnoreCase) &&
            !jobId.StartsWith("IN_", StringComparison.OrdinalIgnoreCase))
        {
            return;
        }

        var profile = KpiProfile.LoadSavedProfile(_configStore.FilePath);
        Dispatcher.BeginInvoke(() =>
        {
            EnsureTool4();
            if (_tool4View is null)
            {
                _tool6View?.SetStatus($"Start dispatched: {jobId} | KPI unavailable; open User KPI for details");
                return;
            }

            string state;
            try
            {
                state = _tool4View.RecordStartedJob(mapped, profile);
            }
            catch (Exception ex)
            {
                _tool6View?.SetStatus($"Start dispatched: {jobId} | KPI capture failed: {ex.Message}");
                _tool4View.ShowMessage($"KPI capture failed: {ex.Message}", KpiView.MsgErrorColor, 15000);
                ShowPage("tool4");
                return;
            }

            if (_tool6View is not null)
            {
                var label = state switch
                {
                    "ready" => "ready for Submit",
                    "synced" => "saved",
                    "pending" => "pending sync",
                    "needs_warehouse" => "select warehouse",
                    "needs_profile" => "configure profile",
                    "conflict" => "already assigned",
                    _ => state
                };
                _tool6View.SetStatus($"Start dispatched: {jobId} | KPI {label}");
            }

            if (!string.Equals(state, "ignored", StringComparison.Ordinal))
                ShowPage("tool4");
        });
    }

    private void OnJobAssignmentsChanged(Dictionary<(string JobId, string Warehouse), string> assignments)
    {
        _jobAssignments = new Dictionary<(string JobId, string Warehouse), string>(assignments);
        _tool6View?.SetJobAssignments(_jobAssignments);
    }

    private void OnReconciliationJobsChanged(IReadOnlyList<Dictionary<string, object?>> records)
    {
        if (_jobAssignments is null)
            return;
        _monitoringService?.UpdateReconciliationJobs(records);
    }

    private void OnKpiStatus(KpiSyncResult result)
    {
        if (_tool6View is null)
            return;

        if (!string.IsNullOrEmpty(result.Error))
        {
            _tool6View.SetStatus($"KPI needs attention: {result.Error}");
            return;
        }

        if (result.State == "cancelled" && result.Removed == 0)
        {
            _tool6View.SetStatus($"KPI pending retry cancelled: {result.Record.JobId} ({result.Record.Warehouse}); no saved entry found");
            return;
        }

        var label = result.State switch
        {
            "synced" => "saved",
            "cancelled" => "deleted",
            _ => $"already assigned by {result.Owner}"
        };
        _tool6View.SetStatus($"KPI {label}: {result.Record.JobId} ({result.Record.Warehouse})");
    }

    private async Task NetworkMonitorLoopAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            bool online = false;
            foreach (var (host, port) in new[] { ("1.1.1.1", 53), ("8.8.8.8", 53), ("www.google.com", 80) })
            {
                try
                {
                    using var tcp = new TcpClient();
                    using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
                    timeoutCts.CancelAfter(1800);
                    await tcp.ConnectAsync(host, port, timeoutCts.Token).ConfigureAwait(false);
                    online = true;
                    break;
                }
                catch { }
            }

            if (_isOnline != online && !_closing)
            {
                try
                {
                    await Dispatcher.InvokeAsync(() => ApplyNetworkStatus(online));
                }
                catch { }
            }

            try { await Task.Delay(4000, ct).ConfigureAwait(false); } catch { break; }
        }
    }

    private void ApplyNetworkStatus(bool isOnline)
    {
        _isOnline = isOnline;
        _dashboardView?.SetOnlineStatus(isOnline);
        ApplyNetworkStatusToSidebar();
    }

    private void ApplyNetworkStatusToSidebar()
    {
        SidebarStatusBox.Background = _isOnline ? SidebarOnlineBg : SidebarOfflineBg;
        SidebarStatusText.Foreground = _isOnline ? SidebarOnlineFg : SidebarOfflineFg;
        SidebarStatusText.Text = _isOnline ? "● System Online" : "● System Offline";
    }

    private void StartBackgroundWarmup()
    {
        _ = Task.Run(async () =>
        {
            try
            {
                var store = new SentLogStore(_configStore);
                store.SortLocalRecords();
                await store.GetCountsAsync().ConfigureAwait(false);
            }
            catch { }
        });
    }

    private void StartPresenceTracking()
    {
        if (!MonitoringAuth.IsMonitoringAuthorized())
        {
            _presenceStatus = "Cloud integration is awaiting desktop validation.";
            RefreshPresenceStatusLabel();
            return;
        }

        if (string.Equals(_configStore.Get("cloud_monitoring_enabled", "true"), "false", StringComparison.OrdinalIgnoreCase))
        {
            _presenceStatus = "Cloud monitoring disabled in configuration.";
            RefreshPresenceStatusLabel();
            return;
        }

        if (_monitoringService is { IsAlive: true })
        {
            RefreshPresenceContext();
            return;
        }

        try
        {
            _monitoringService = new MonitoringService(_configStore.FilePath, AppPaths.ReadAppVersion());
            RefreshPresenceContext();
            _monitoringService.Start();

            try
            {
                ScreenStreamService.Instance.Start();
                _screenStreamerStarted = true;
            }
            catch { }

            if (!_inputHooksAttached)
            {
                _inputHooksAttached = true;
                PreviewKeyDown += (_, _) => _monitoringService?.Interact();
                PreviewMouseDown += (_, _) => _monitoringService?.Interact();
                PreviewMouseWheel += (_, _) => _monitoringService?.Interact();
            }
        }
        catch
        {
            _presenceStatus = "Cloud monitoring unavailable; application remains available.";
            RefreshPresenceStatusLabel();
        }
    }

    private void RefreshPresenceContext()
    {
        if (_monitoringService is null)
            return;
        var profile = KpiProfile.LoadSavedProfile(_configStore.FilePath);
        var title = NavItems.FirstOrDefault(n => n.Key == _activePage).Label ?? "Dashboard";
        _monitoringService.UpdateContext(OperatorPresence.PresenceIdentity(profile, _presenceDeviceName), title);
    }

    private void RefreshPresenceStatusLabel()
    {
        if (_closing || _settingsView is null)
            return;
        var status = _monitoringService?.Status() ?? _presenceStatus;
        _settingsView.UpdatePresenceStatus(status);
    }

    public void CheckForUpdates(bool silent = false)
    {
        if (!_isOnline)
        {
            if (!silent)
            {
                System.Windows.MessageBox.Show(
                    this,
                    "Cannot check for updates while system is offline. Please check your internet connection.",
                    "Network Offline",
                    MessageBoxButton.OK,
                    MessageBoxImage.Warning);
            }
            return;
        }

        _ = CheckForUpdatesWorkerAsync(silent);
    }

    private async Task CheckForUpdatesWorkerAsync(bool silent)
    {
        var apiUrl = $"https://api.github.com/repos/{GithubUser}/{GithubRepo}/releases/latest";
        var currentVersion = AppPaths.ReadAppVersion();

        try
        {
            using var req = new HttpRequestMessage(HttpMethod.Get, apiUrl);
            req.Headers.UserAgent.ParseAdd("EFL-Nexus-Updater");
            using var resp = await UpdateHttp.SendAsync(req).ConfigureAwait(false);
            resp.EnsureSuccessStatusCode();

            var json = await resp.Content.ReadAsStringAsync().ConfigureAwait(false);
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;

            var latestVersion = (root.TryGetProperty("tag_name", out var tagEl) ? tagEl.GetString() : "") ?? "";
            latestVersion = latestVersion.Trim().TrimStart('v', 'V');

            if (root.TryGetProperty("body", out var bEl))
            {
                var bodyNotes = bEl.GetString();
                if (!string.IsNullOrWhiteSpace(bodyNotes))
                {
                    ReleaseNotesManager.SaveDownloadedNotes(bodyNotes);
                }
            }

            string? bestPatchUrl = null;
            int bestPatchBuild = -1;
            string? fullZipUrl = null;

            int currentBuild = int.TryParse(AppPaths.ReadBuildNumber(), out var b) ? b : 0;

            if (root.TryGetProperty("assets", out var assetsEl) && assetsEl.ValueKind == JsonValueKind.Array)
            {
                foreach (var asset in assetsEl.EnumerateArray())
                {
                    var name = asset.TryGetProperty("name", out var nEl) ? nEl.GetString() : "";
                    if (string.IsNullOrEmpty(name) || !name.EndsWith(".zip", StringComparison.OrdinalIgnoreCase))
                        continue;

                    var url = asset.TryGetProperty("browser_download_url", out var uEl) ? uEl.GetString() : null;
                    if (string.IsNullOrEmpty(url))
                        continue;

                    var patchMatch = System.Text.RegularExpressions.Regex.Match(
                        name,
                        @"^EFL_Nexus_Patch_v(?<ver>[^_]+)_b(?<bld>\d+)\.zip$",
                        System.Text.RegularExpressions.RegexOptions.IgnoreCase);

                    if (patchMatch.Success)
                    {
                        var patchVer = patchMatch.Groups["ver"].Value;
                        if (int.TryParse(patchMatch.Groups["bld"].Value, out var pBuild))
                        {
                            if (string.Equals(patchVer, latestVersion, StringComparison.OrdinalIgnoreCase) && pBuild > bestPatchBuild)
                            {
                                bestPatchBuild = pBuild;
                                bestPatchUrl = url;
                            }
                        }
                    }
                    else if (fullZipUrl == null)
                    {
                        fullZipUrl = url;
                    }
                }
            }

            var downloadUrl = bestPatchUrl ?? fullZipUrl;

            if (string.IsNullOrEmpty(downloadUrl))
            {
                if (!silent)
                {
                    await Dispatcher.InvokeAsync(() =>
                        System.Windows.MessageBox.Show(this, "No .zip asset found in the latest GitHub release.", "Update Error", MessageBoxButton.OK, MessageBoxImage.Error));
                }
                return;
            }

            bool isHotfixUpdate = string.Equals(latestVersion, currentVersion, StringComparison.OrdinalIgnoreCase)
                                  && bestPatchBuild > currentBuild;

            if (IsNewerVersion(latestVersion, currentVersion) || isHotfixUpdate)
            {
                var updateLabel = isHotfixUpdate
                    ? $"v{latestVersion} Build {bestPatchBuild} (Hotfix)"
                    : $"v{latestVersion}" + (bestPatchBuild >= 0 ? $" (Build {bestPatchBuild})" : "");

                await Dispatcher.InvokeAsync(() => PromptUpdate(updateLabel, latestVersion, currentVersion, currentBuild, downloadUrl));
            }
            else if (!silent)
            {
                var buildInfo = currentBuild > 0 ? $" (Build {currentBuild})" : "";
                await Dispatcher.InvokeAsync(() =>
                    System.Windows.MessageBox.Show(this, $"You are running the latest version (v{currentVersion}{buildInfo}).", "Up to Date", MessageBoxButton.OK, MessageBoxImage.Information));
            }
        }
        catch (Exception ex)
        {
            if (!silent)
            {
                await Dispatcher.InvokeAsync(() =>
                    System.Windows.MessageBox.Show(this, $"Could not check for updates:\n{ex.Message}", "Update Error", MessageBoxButton.OK, MessageBoxImage.Error));
            }
        }
    }

    public static bool IsNewerVersion(string latestVersion, string currentVersion)
    {
        if (Version.TryParse(latestVersion, out var latest) && Version.TryParse(currentVersion, out var current))
            return latest > current;
        return string.Compare(latestVersion, currentVersion, StringComparison.OrdinalIgnoreCase) > 0;
    }

    private void PromptUpdate(string targetLabel, string latestVersion, string currentVersion, int currentBuild, string downloadUrl)
    {
        var buildInfo = currentBuild > 0 ? $" (Build {currentBuild})" : "";
        var answer = System.Windows.MessageBox.Show(
            this,
            $"A new version ({targetLabel}) is available!\n\nCurrent Version: v{currentVersion}{buildInfo}\n\nWould you like to download and update now?",
            "Update Available",
            MessageBoxButton.YesNo,
            MessageBoxImage.Question);
        if (answer != MessageBoxResult.Yes)
            return;

        var updaterExe = Path.Combine(AppPaths.AppDir, "updater.exe");
        if (!File.Exists(updaterExe))
        {
            System.Windows.MessageBox.Show(this, "updater.exe was not found in the application directory.", "Update Error", MessageBoxButton.OK, MessageBoxImage.Error);
            return;
        }

        var psi = new ProcessStartInfo
        {
            FileName = updaterExe,
            UseShellExecute = true
        };
        psi.ArgumentList.Add("--url");
        psi.ArgumentList.Add(downloadUrl);
        psi.ArgumentList.Add("--version");
        psi.ArgumentList.Add(latestVersion);
        psi.ArgumentList.Add("--pid");
        psi.ArgumentList.Add(Environment.ProcessId.ToString());
        psi.ArgumentList.Add("--appdir");
        psi.ArgumentList.Add(AppPaths.AppDir);

        Process.Start(psi);
        Close();
        System.Windows.Application.Current?.Shutdown(0);
    }

    private void Window_Closing(object? sender, CancelEventArgs e)
    {
        if (_readyToClose)
            return;

        if (!_closing)
        {
            _closing = true;
            _spinnerTimer.Stop();
            _presenceUiTimer.Stop();
            _networkCts.Cancel();

            if (_monitoringService is not null)
                _monitoringService.Stop();
            foreach (var retiring in _retiringServices)
                retiring.Stop();

            if (_screenStreamerStarted)
            {
                try { ScreenStreamService.Instance.Stop(); } catch { }
            }

            try { _whatsappView?.Shutdown(); } catch { }
            try { _whatsappController?.Shutdown(); } catch { }
            try { _tool2View?.SaveSettings(); } catch { }
            try { _tool4View?.Close(); } catch { }
            try { _tool5View?.Shutdown(); } catch { }
            try { _tool6View?.CloseBrowser(); } catch { }
            try { _tool1View?.TerminateAllSessions(); } catch { }
        }

        bool anyAlive = (_monitoringService?.IsAlive == true) || _retiringServices.Any(s => s.IsAlive);
        if (!anyAlive)
        {
            _readyToClose = true;
            return;
        }

        e.Cancel = true;
        long deadlineTicks = Environment.TickCount64 + 1500;
        var waitTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(50) };
        waitTimer.Tick += (_, _) =>
        {
            bool stillAlive = (_monitoringService?.IsAlive == true) || _retiringServices.Any(s => s.IsAlive);
            if (!stillAlive || Environment.TickCount64 >= deadlineTicks)
            {
                waitTimer.Stop();
                _readyToClose = true;
                Close();
            }
        };
        waitTimer.Start();
    }
}
