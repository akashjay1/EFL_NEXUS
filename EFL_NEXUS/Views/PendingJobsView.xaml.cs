using System.Collections.ObjectModel;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using EflNexus.Core.Infrastructure;
using EflNexus.Core.Korber;
using EflNexus.Core.PendingJobs;
using Drawing = System.Drawing;
using MediaColor = System.Windows.Media.Color;
using WinForms = System.Windows.Forms;

namespace EflNexus.App.Views;

public sealed class PendingJobRowItem
{
    public string AssignedUser { get; set; } = "";
    public string JobId { get; set; } = "";
    public string Client { get; set; } = "";
    public string Status { get; set; } = "";
    public string StatusTag { get; set; } = "other";
    public PortalJobRecord Record { get; set; } = new();
}

public partial class PendingJobsView : System.Windows.Controls.UserControl
{
    private static readonly SolidColorBrush BadgeActiveBrush = new(MediaColor.FromRgb(0x16, 0xA3, 0x4A));
    private static readonly SolidColorBrush BadgeMutedBrush = new(MediaColor.FromRgb(0x64, 0x74, 0x8B));

    private static readonly string[] IntervalChoices = ["5s", "10s", "15s", "30s", "60s", "120s", "Off"];

    private readonly ConfigStore _configStore;
    private readonly ObservableCollection<PendingJobRowItem> _rows = [];
    private readonly List<PortalJobRecord> _records = [];
    private readonly Dictionary<(string JobId, string Warehouse), string> _jobAssignments = [];
    private readonly HashSet<string> _seenPendingIds = new(StringComparer.OrdinalIgnoreCase);

    private readonly WinForms.Panel _reconciliationPanel;
    private readonly WinForms.Label _reconciliationPlaceholderLabel;
    private readonly WinForms.Panel _loadingHistoryPanel;
    private readonly WinForms.Label _loadingHistoryPlaceholderLabel;

    private readonly DispatcherTimer _pollTimer;
    private readonly DispatcherTimer _internalEmbedTimer;
    private readonly DispatcherTimer _lhEmbedTimer;

    private Process? _browserProcess;
    private IntPtr _browserHwnd = IntPtr.Zero;
    private Process? _loadingHistoryProcess;
    private IntPtr _loadingHistoryHwnd = IntPtr.Zero;
    private int _browserEmbedAttempts;
    private int _loadingHistoryEmbedAttempts;
    private bool _isViewVisible = true;
    private bool _suppressRefreshCombo;

    private long _liveResultBaselineTicks;
    private double _lastLoadingHistoryTime;
    private double _lastDownloadTime;
    private string? _jobsObservedAtIso;

    private string _loginUrl;
    private string _username;
    private string _password;
    private string _reconciliationUrl;
    private int _refreshSeconds;
    private bool _soundEnabled;
    private string _soundPath;
    private string _activeJobId = "";
    private string _activeGatepass = "";
    private string _activeClient = "";

    public Action? OnOpenSettings { get; set; }
    public Action<PortalJobRecord>? OnJobStarted { get; set; }
    public Action<PortalJobRecord>? OnCreateGatepass { get; set; }
    public Action<IReadOnlyList<Dictionary<string, object?>>>? OnJobsChanged { get; set; }

    public IReadOnlyList<PortalJobRecord> Records => _records;
    public string ActiveJobId => _activeJobId;
    public string ActiveGatepass => _activeGatepass;
    public string CurrentStatus => StatusText.Text;

    public PendingJobsView()
        : this(null, null, null, null, null)
    {
    }

    public PendingJobsView(
        ConfigStore? configStore,
        Action? onOpenSettings = null,
        Action<PortalJobRecord>? onJobStarted = null,
        Action<PortalJobRecord>? onCreateGatepass = null,
        Action<IReadOnlyList<Dictionary<string, object?>>>? onJobsChanged = null)
    {
        InitializeComponent();

        _configStore = configStore ?? new ConfigStore();
        OnOpenSettings = onOpenSettings;
        OnJobStarted = onJobStarted;
        OnCreateGatepass = onCreateGatepass;
        OnJobsChanged = onJobsChanged;

        SettingsBtn.Visibility = OnOpenSettings is not null ? Visibility.Visible : Visibility.Collapsed;

        // Build WinForms host panels with matching placeholders so HWND creation & Z-order never glitch
        _reconciliationPanel = new WinForms.Panel
        {
            BackColor = Drawing.Color.FromArgb(0xE2, 0xE8, 0xF0),
            Dock = WinForms.DockStyle.Fill
        };
        _reconciliationPlaceholderLabel = new WinForms.Label
        {
            Text = "The Reconciliation browser will appear here after you click Open Both Browsers.",
            Dock = WinForms.DockStyle.Fill,
            TextAlign = Drawing.ContentAlignment.MiddleCenter,
            BackColor = Drawing.Color.FromArgb(0xE2, 0xE8, 0xF0),
            ForeColor = Drawing.Color.FromArgb(0x64, 0x74, 0x8B),
            Font = new Drawing.Font("Segoe UI", 10F)
        };
        _reconciliationPanel.Controls.Add(_reconciliationPlaceholderLabel);
        _reconciliationPanel.Resize += (_, _) => ResizeInternalBrowser();
        ReconciliationBrowserHost.Child = _reconciliationPanel;

        _loadingHistoryPanel = new WinForms.Panel
        {
            BackColor = Drawing.Color.FromArgb(0xE2, 0xE8, 0xF0),
            Dock = WinForms.DockStyle.Fill
        };
        _loadingHistoryPlaceholderLabel = new WinForms.Label
        {
            Text = "Loading History will open here and stop at the Gate Pass entry page.",
            Dock = WinForms.DockStyle.Fill,
            TextAlign = Drawing.ContentAlignment.MiddleCenter,
            BackColor = Drawing.Color.FromArgb(0xE2, 0xE8, 0xF0),
            ForeColor = Drawing.Color.FromArgb(0x64, 0x74, 0x8B),
            Font = new Drawing.Font("Segoe UI", 10F)
        };
        _loadingHistoryPanel.Controls.Add(_loadingHistoryPlaceholderLabel);
        _loadingHistoryPanel.Resize += (_, _) => ResizeLoadingHistoryBrowser();
        LoadingHistoryBrowserHost.Child = _loadingHistoryPanel;

        // Load initial settings
        _loginUrl = _configStore.Get("data_grabber_login_url", GrabberSettingsAndPaths.DefaultLoginUrl);
        if (string.IsNullOrWhiteSpace(_loginUrl))
            _loginUrl = GrabberSettingsAndPaths.DefaultLoginUrl;

        _username = _configStore.Get("data_grabber_user", GrabberSettingsAndPaths.DefaultPortalUsername);
        _password = GrabberSettingsAndPaths.LoadSavedPassword();

        _reconciliationUrl = _configStore.Get("data_grabber_reconciliation_url", GrabberSettingsAndPaths.DefaultReconciliationUrl);
        if (string.IsNullOrWhiteSpace(_reconciliationUrl))
            _reconciliationUrl = GrabberSettingsAndPaths.DefaultReconciliationUrl;

        _refreshSeconds = GrabberSettingsAndPaths.ParseRefreshSeconds(
            _configStore.Get("data_grabber_refresh_seconds", GrabberSettingsAndPaths.DefaultRefreshSeconds.ToString()),
            GrabberSettingsAndPaths.DefaultRefreshSeconds);

        _soundEnabled = _configStore.GetBool("data_grabber_sound_enabled", true);
        _soundPath = _configStore.Get("data_grabber_sound_path", "");

        // Initialize baseline IPC timestamps so stale events from prior runs don't re-fire
        _lastLoadingHistoryTime = ReadTimestampFromJson(GrabberSettingsAndPaths.LoadingHistoryEventFilePath);
        _lastDownloadTime = ReadTimestampFromJson(GrabberSettingsAndPaths.DownloadEventFilePath);

        JobsGrid.ItemsSource = _rows;

        _suppressRefreshCombo = true;
        foreach (var opt in IntervalChoices)
            RefreshCombo.Items.Add(opt);
        _suppressRefreshCombo = false;

        SetRefreshInterval(_refreshSeconds.ToString(), save: false);
        SetSoundEnabled(_soundEnabled, save: false);

        SetStatus(
            !string.IsNullOrWhiteSpace(_username) && !string.IsNullOrEmpty(_password)
                ? "Ready. Click 'Open Both Browsers' to launch Reconciliation and Loading History."
                : "Enter portal credentials in Settings to automatically sign in and open Reconciliation.");

        _pollTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(750) };
        _pollTimer.Tick += (_, _) => PollIpcEvents();
        _pollTimer.Start();

        _internalEmbedTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(100) };
        _internalEmbedTimer.Tick += (_, _) => FindAndEmbedInternalBrowserTick();

        _lhEmbedTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(100) };
        _lhEmbedTimer.Tick += (_, _) => FindAndEmbedLoadingHistoryTick();
    }

    public void SetStatus(string text)
    {
        StatusText.Text = text ?? string.Empty;
    }

    public void SetConnectionSettings(
        string loginUrl,
        string username,
        string password,
        string reconciliationUrl,
        string refreshSeconds = "5",
        bool soundEnabled = true,
        string soundPath = "")
    {
        _loginUrl = string.IsNullOrWhiteSpace(loginUrl) ? GrabberSettingsAndPaths.DefaultLoginUrl : loginUrl.Trim();
        _username = (username ?? string.Empty).Trim();
        _password = password ?? string.Empty;
        _reconciliationUrl = string.IsNullOrWhiteSpace(reconciliationUrl)
            ? GrabberSettingsAndPaths.DefaultReconciliationUrl
            : reconciliationUrl.Trim();
        _soundPath = (soundPath ?? string.Empty).Trim();

        SetRefreshInterval(refreshSeconds, save: false);
        SetSoundEnabled(soundEnabled, save: false);

        SetStatus(
            !string.IsNullOrEmpty(_username) && !string.IsNullOrEmpty(_password)
                ? "Ready. Click 'Open Both Browsers' to launch Reconciliation and Loading History."
                : "Enter portal credentials in Settings to automatically sign in and open Reconciliation.");
    }

    public void SetJobAssignments(IReadOnlyDictionary<(string JobId, string Warehouse), string> assignments)
    {
        _jobAssignments.Clear();
        foreach (var kv in assignments)
        {
            var key = ((kv.Key.JobId ?? string.Empty).Trim().ToLowerInvariant(),
                       (kv.Key.Warehouse ?? string.Empty).Trim().ToLowerInvariant());
            _jobAssignments[key] = kv.Value ?? string.Empty;
        }

        if (_records.Count > 0)
        {
            var byId = _records.ToDictionary(r => (r.JobId ?? string.Empty).ToLowerInvariant(), r => r);
            var selectedIds = GetSelectedJobIds();

            _rows.Clear();
            foreach (var rec in _records)
                _rows.Add(BuildRowItem(rec));
            RestoreSelection(selectedIds);
        }

        PublishJobSnapshot();
    }

    public void SetRefreshInterval(string secondsOrLabel, bool save = true)
    {
        int parsed = GrabberSettingsAndPaths.ParseRefreshSeconds(secondsOrLabel, GrabberSettingsAndPaths.DefaultRefreshSeconds);
        _refreshSeconds = parsed;

        string display = parsed > 0 ? $"{parsed}s" : "Off";
        _suppressRefreshCombo = true;
        RefreshCombo.Text = display;
        _suppressRefreshCombo = false;

        if (parsed > 0)
        {
            AutoRefreshBadge.Text = $"⚡ Auto-Refresh: {parsed}s";
            AutoRefreshBadge.Foreground = BadgeActiveBrush;
        }
        else
        {
            AutoRefreshBadge.Text = "⏸ Auto-Refresh: Off";
            AutoRefreshBadge.Foreground = BadgeMutedBrush;
        }

        if (save)
            _configStore.SaveKeyValues(("data_grabber_refresh_seconds", parsed.ToString()));

        if (IsProcessRunning(_browserProcess))
            SendBrowserCommand("set_refresh_interval", seconds: parsed);
    }

    public void SetSoundEnabled(bool enabled, bool save = true)
    {
        _soundEnabled = enabled;
        SoundBtn.Content = enabled ? "🔔 Sound: On" : "🔕 Sound: Off";
        SoundBtn.Foreground = enabled ? BadgeActiveBrush : BadgeMutedBrush;

        if (save)
            _configStore.SaveKeyValues(("data_grabber_sound_enabled", enabled ? "True" : "False"));
    }

    public void SetBrowserVisible(bool visible)
    {
        _isViewVisible = visible;
        ReconciliationBrowserHost.Visibility = visible ? Visibility.Visible : Visibility.Collapsed;
        LoadingHistoryBrowserHost.Visibility = visible ? Visibility.Visible : Visibility.Collapsed;

        SetEmbeddedWindowVisible(_browserHwnd, visible);
        SetEmbeddedWindowVisible(_loadingHistoryHwnd, visible);

        if (visible)
        {
            Dispatcher.BeginInvoke(DispatcherPriority.Loaded, new Action(() =>
            {
                ResizeInternalBrowser();
                ResizeLoadingHistoryBrowser();
            }));
        }
    }

    public void SetLoadingHistoryVisible(bool visible)
    {
        LoadingHistoryBrowserHost.Visibility = visible ? Visibility.Visible : Visibility.Collapsed;
        SetEmbeddedWindowVisible(_loadingHistoryHwnd, visible);
        if (visible)
            ResizeLoadingHistoryBrowser();
    }

    public void CloseBrowser()
    {
        _pollTimer.Stop();
        _internalEmbedTimer.Stop();
        _lhEmbedTimer.Stop();

        TerminateProcessSafe(ref _browserProcess);
        _browserHwnd = IntPtr.Zero;
        _reconciliationPlaceholderLabel.Visible = true;

        TerminateProcessSafe(ref _loadingHistoryProcess);
        _loadingHistoryHwnd = IntPtr.Zero;
        _loadingHistoryPlaceholderLabel.Visible = true;
        _loadingHistoryEmbedAttempts = 0;
    }

    public void StartBrowsers()
    {
        var loginUrl = (_loginUrl ?? "").Trim();
        if (!loginUrl.StartsWith("https://", StringComparison.OrdinalIgnoreCase) &&
            !loginUrl.StartsWith("http://", StringComparison.OrdinalIgnoreCase))
        {
            System.Windows.MessageBox.Show(
                Window.GetWindow(this),
                "Enter the full authorised login URL, including https://.",
                "Login URL required",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
            return;
        }

        var user = (_username ?? "").Trim();
        var pass = _password ?? "";
        if (string.IsNullOrEmpty(user) || string.IsNullOrEmpty(pass))
        {
            if (OnOpenSettings is not null)
            {
                var res = System.Windows.MessageBox.Show(
                    Window.GetWindow(this),
                    "Tool 6 username/email and password are required. Would you like to open Settings now to configure them?",
                    "Credentials required",
                    MessageBoxButton.YesNo,
                    MessageBoxImage.Question);
                if (res == MessageBoxResult.Yes)
                    OnOpenSettings.Invoke();
            }
            else
            {
                System.Windows.MessageBox.Show(
                    Window.GetWindow(this),
                    "Please configure the Tool 6 username/email and password in Settings before opening the browser.",
                    "Credentials required",
                    MessageBoxButton.OK,
                    MessageBoxImage.Warning);
            }
            return;
        }

        SaveCredentials(showSuccess: false);

        if (IsProcessRunning(_browserProcess))
        {
            SetStatus("Both portal browsers are open side by side.");
            SetBrowserVisible(true);
            if (!IsProcessRunning(_loadingHistoryProcess))
                StartLoadingHistoryBrowser(stopAtGatepass: true);
            else
                SetLoadingHistoryVisible(true);
            return;
        }

        try
        {
            var exePath = AppPaths.ResolveAppExecutable();
            if (string.IsNullOrWhiteSpace(exePath) || !File.Exists(exePath))
                throw new FileNotFoundException("Unable to locate EFL_NEXUS executable to launch internal browser.");

            _liveResultBaselineTicks = File.Exists(GrabberSettingsAndPaths.ResultFilePath)
                ? File.GetLastWriteTimeUtc(GrabberSettingsAndPaths.ResultFilePath).Ticks
                : 0;

            ClearJobConsole();

            var logPath = GrabberSettingsAndPaths.BrowserLogFilePath;
            Directory.CreateDirectory(Path.GetDirectoryName(logPath)!);
            try { File.WriteAllText(logPath, string.Empty, new UTF8Encoding(false)); } catch { }

            var psi = new ProcessStartInfo
            {
                FileName = exePath,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = false
            };
            psi.ArgumentList.Add("--internal-browser");
            psi.ArgumentList.Add(GrabberSettingsAndPaths.ResultFilePath);
            psi.ArgumentList.Add(loginUrl);

            psi.Environment["EFL_NEXUS_GRABBER_USER"] = user;
            psi.Environment["EFL_NEXUS_GRABBER_PASS"] = pass;
            psi.Environment["EFL_NEXUS_GRABBER_RECON_URL"] = _reconciliationUrl;
            psi.Environment["EFL_NEXUS_GRABBER_REFRESH_SECONDS"] = _refreshSeconds.ToString();

            _browserProcess = new Process { StartInfo = psi, EnableRaisingEvents = true };
            _browserProcess.OutputDataReceived += (_, e) => AppendBrowserLogLine(logPath, e.Data);
            _browserProcess.ErrorDataReceived += (_, e) => AppendBrowserLogLine(logPath, e.Data);

            if (!_browserProcess.Start())
                throw new InvalidOperationException("Failed to start internal browser process.");

            _browserProcess.BeginOutputReadLine();
            _browserProcess.BeginErrorReadLine();

            SetStatus("Internal browser opened. Logging in and opening Reconciliation automatically…");
            _browserEmbedAttempts = 0;
            _browserHwnd = IntPtr.Zero;
            _internalEmbedTimer.Start();

            StartLoadingHistoryBrowser(stopAtGatepass: true);
            _pollTimer.Interval = TimeSpan.FromMilliseconds(750);
            if (!_pollTimer.IsEnabled)
                _pollTimer.Start();
        }
        catch (Exception ex)
        {
            System.Windows.MessageBox.Show(
                Window.GetWindow(this),
                $"Could not start the internal browser: {ex.Message}",
                "Internal browser unavailable",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
        }
    }

    public void RestartBrowser()
    {
        SetStatus("Restarting internal browser...");
        TerminateProcessSafe(ref _browserProcess);
        _browserHwnd = IntPtr.Zero;
        _reconciliationPlaceholderLabel.Visible = true;
        TerminateProcessSafe(ref _loadingHistoryProcess);
        _loadingHistoryHwnd = IntPtr.Zero;
        _loadingHistoryPlaceholderLabel.Visible = true;
        _browserEmbedAttempts = 0;
        _loadingHistoryEmbedAttempts = 0;

        var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(150) };
        timer.Tick += (_, _) =>
        {
            timer.Stop();
            StartBrowsers();
        };
        timer.Start();
    }

    public void StartLoadingHistoryBrowser(
        string gatepass = "",
        string jobId = "",
        string client = "",
        bool stopAtGatepass = false,
        string pageCode = "",
        string reportName = "")
    {
        var gp = GrabberSettingsAndPaths.Clean(gatepass);
        var jid = GrabberSettingsAndPaths.Clean(jobId);
        var cli = GrabberSettingsAndPaths.Clean(client);
        var pCode = GrabberSettingsAndPaths.Clean(pageCode);
        var rName = GrabberSettingsAndPaths.Clean(reportName);

        if (stopAtGatepass)
        {
            gp = "";
            jid = "";
            cli = "";
        }

        if (!stopAtGatepass && (string.IsNullOrEmpty(gp) || string.IsNullOrEmpty(cli)) && !string.IsNullOrEmpty(jid))
        {
            var matched = _records.FirstOrDefault(r => string.Equals(GrabberSettingsAndPaths.Clean(r.JobId), jid, StringComparison.OrdinalIgnoreCase));
            if (matched is not null)
            {
                if (string.IsNullOrEmpty(gp)) gp = GrabberSettingsAndPaths.Clean(matched.Gatepass);
                if (string.IsNullOrEmpty(cli)) cli = GrabberSettingsAndPaths.Clean(matched.Client);
            }
        }

        if (!stopAtGatepass && (string.IsNullOrEmpty(gp) || string.IsNullOrEmpty(cli) || string.IsNullOrEmpty(jid)))
        {
            try
            {
                var persisted = GrabberSettingsAndPaths.LoadPersistedJobMap();
                if (!string.IsNullOrEmpty(jid) && persisted.TryGetValue(jid.ToLowerInvariant(), out var mapped))
                {
                    if (string.IsNullOrEmpty(gp)) gp = GrabberSettingsAndPaths.Clean(mapped.Gatepass);
                    if (string.IsNullOrEmpty(cli)) cli = GrabberSettingsAndPaths.Clean(mapped.Client);
                }
                else if (!string.IsNullOrEmpty(gp))
                {
                    foreach (var m in persisted.Values)
                    {
                        if (string.Equals(GrabberSettingsAndPaths.Clean(m.Gatepass), gp, StringComparison.Ordinal))
                        {
                            if (string.IsNullOrEmpty(jid)) jid = GrabberSettingsAndPaths.Clean(m.JobId);
                            if (string.IsNullOrEmpty(cli)) cli = GrabberSettingsAndPaths.Clean(m.Client);
                            break;
                        }
                    }
                }
            }
            catch { }
        }

        if (!stopAtGatepass)
        {
            if (string.IsNullOrEmpty(gp) && !string.IsNullOrEmpty(_activeGatepass)) gp = _activeGatepass;
            if (string.IsNullOrEmpty(jid) && !string.IsNullOrEmpty(_activeJobId)) jid = _activeJobId;
            if (string.IsNullOrEmpty(cli) && !string.IsNullOrEmpty(_activeClient)) cli = _activeClient;
        }

        if (string.IsNullOrEmpty(pCode))
        {
            if (jid.StartsWith("IN", StringComparison.OrdinalIgnoreCase))
            {
                pCode = "2598";
                rName = "Inventory by gatepass";
            }
            else
            {
                pCode = "1992";
                rName = "Loading History Report";
            }
        }
        else if (string.IsNullOrEmpty(rName))
        {
            rName = pCode == "2598" ? "Inventory by gatepass" : "Loading History Report";
        }

        if (LoadingHistoryHeaderTitle is not null)
        {
            LoadingHistoryHeaderTitle.Text = pCode == "2598"
                ? "Inventory by Gatepass — enter Gate Pass manually"
                : "Loading History — enter Gate Pass manually";
        }

        if (IsProcessRunning(_loadingHistoryProcess))
        {
            SetLoadingHistoryVisible(true);
            if (!string.IsNullOrEmpty(gp))
            {
                SendLoadingHistoryCommand("query_and_export", gp, jid, cli, pCode, rName);
                string reportDisplay = pCode == "2598" ? "Inventory by Gatepass" : "Loading History";
                SetStatus($"Entering Gate Pass '{gp}' in {reportDisplay}, querying and exporting…");
            }
            else if (stopAtGatepass)
            {
                SetStatus("Körber browser is open side by side.");
            }
            else
            {
                string reportDisplay = pCode == "2598" ? "Inventory by Gatepass" : "Loading History";
                SetStatus($"Körber {reportDisplay} is already open.");
            }
            return;
        }

        try
        {
            var korberCreds = KorberLoginBot.GetCredentials();
            if (string.IsNullOrWhiteSpace(korberCreds.Username) || string.IsNullOrWhiteSpace(korberCreds.Password))
                throw new InvalidOperationException("Körber credentials are not configured. Add them in Settings before downloading Loading History.");

            var exePath = AppPaths.ResolveAppExecutable();
            if (string.IsNullOrWhiteSpace(exePath) || !File.Exists(exePath))
                throw new FileNotFoundException("Unable to locate EFL_NEXUS executable.");

            var psi = new ProcessStartInfo
            {
                FileName = exePath,
                UseShellExecute = false
            };
            psi.ArgumentList.Add("--loading-history-browser");
            psi.ArgumentList.Add(korberCreds.KorberUrl);
            if (!string.IsNullOrEmpty(gp)) psi.ArgumentList.Add(gp);
            if (!string.IsNullOrEmpty(jid)) psi.ArgumentList.Add(jid);
            if (!string.IsNullOrEmpty(cli)) psi.ArgumentList.Add(cli);
            if (!string.IsNullOrEmpty(pCode)) psi.ArgumentList.Add(pCode);
            if (!string.IsNullOrEmpty(rName)) psi.ArgumentList.Add(rName);

            psi.Environment["EFL_NEXUS_KORBER_USER"] = korberCreds.Username;
            psi.Environment["EFL_NEXUS_KORBER_PASS"] = korberCreds.Password;
            if (stopAtGatepass) psi.Environment["EFL_NEXUS_LOADING_HISTORY_STOP_AT_GATEPASS"] = "1";
            if (!string.IsNullOrEmpty(gp)) psi.Environment["EFL_NEXUS_KORBER_GATEPASS"] = gp;
            if (!string.IsNullOrEmpty(jid)) psi.Environment["EFL_NEXUS_KORBER_JOB_ID"] = jid;
            if (!string.IsNullOrEmpty(cli)) psi.Environment["EFL_NEXUS_KORBER_CLIENT"] = cli;
            if (!string.IsNullOrEmpty(pCode)) psi.Environment["EFL_NEXUS_KORBER_PAGE_CODE"] = pCode;
            if (!string.IsNullOrEmpty(rName)) psi.Environment["EFL_NEXUS_KORBER_REPORT_NAME"] = rName;

            _loadingHistoryProcess = Process.Start(psi)
                ?? throw new InvalidOperationException("Failed to start Loading History browser.");

            _loadingHistoryEmbedAttempts = 0;
            _loadingHistoryHwnd = IntPtr.Zero;
            _lhEmbedTimer.Start();

            if (stopAtGatepass)
            {
                SetStatus("Opening Reconciliation and Loading History side by side…");
            }
            else
            {
                string reportDisplay = pCode == "2598" ? "Inventory by Gatepass" : "Loading History";
                string ctxNote = !string.IsNullOrEmpty(gp) ? $" for gate pass {gp}" : "";
                SetStatus($"Opening lightweight Körber {reportDisplay} browser{ctxNote}…");
            }
        }
        catch (Exception ex)
        {
            System.Windows.MessageBox.Show(
                Window.GetWindow(this),
                $"Could not open Körber Loading History: {ex.Message}",
                "Loading History",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
            SetStatus("Could not open Körber Loading History.");
        }
    }

    private void SaveCredentials(bool showSuccess)
    {
        var loginUrl = (_loginUrl ?? "").Trim();
        var user = (_username ?? "").Trim();
        var pass = _password ?? "";

        if ((!loginUrl.StartsWith("https://", StringComparison.OrdinalIgnoreCase) &&
             !loginUrl.StartsWith("http://", StringComparison.OrdinalIgnoreCase)) ||
            string.IsNullOrEmpty(user) || string.IsNullOrEmpty(pass))
        {
            if (showSuccess)
            {
                System.Windows.MessageBox.Show(
                    Window.GetWindow(this),
                    "Enter a valid login URL, username/email, and password first.",
                    "Incomplete credentials",
                    MessageBoxButton.OK,
                    MessageBoxImage.Warning);
            }
            return;
        }

        try
        {
            GrabberSettingsAndPaths.SavePassword(pass, user);
        }
        catch (Exception ex)
        {
            System.Windows.MessageBox.Show(
                Window.GetWindow(this),
                $"Windows Credential Manager could not save Tool 6 password: {ex.Message}",
                "Credential save failed",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
            return;
        }

        _configStore.SaveKeyValues(
            ("data_grabber_login_url", loginUrl),
            ("data_grabber_user", user),
            ("data_grabber_reconciliation_url", (_reconciliationUrl ?? "").Trim()),
            ("data_grabber_refresh_seconds", _refreshSeconds.ToString()));

        if (showSuccess)
            SetStatus("Credentials saved securely for this Windows user.");
    }

    private void ClearJobConsole()
    {
        _records.Clear();
        _rows.Clear();
    }

    private void PollIpcEvents()
    {
        bool browserLive = IsProcessRunning(_browserProcess);
        _pollTimer.Interval = TimeSpan.FromMilliseconds(browserLive ? 750 : 1500);

        if (browserLive && File.Exists(GrabberSettingsAndPaths.ResultFilePath))
        {
            try
            {
                var writeTicks = File.GetLastWriteTimeUtc(GrabberSettingsAndPaths.ResultFilePath).Ticks;
                if (writeTicks > _liveResultBaselineTicks)
                {
                    var payload = JsonSerializer.Deserialize<PortalResultsPayload>(
                        File.ReadAllText(GrabberSettingsAndPaths.ResultFilePath));
                    if (payload?.Records is { Count: > 0 } recs)
                    {
                        if (!RecordsEqual(_records, recs))
                            ShowResults(recs);
                    }
                    else if (payload?.JobIds is { Count: > 0 } ids)
                    {
                        var converted = ids.Select(id => new PortalJobRecord { JobId = id, Status = "Unknown" }).ToList();
                        if (!RecordsEqual(_records, converted))
                            ShowResults(converted);
                    }
                }
            }
            catch { }
        }

        if (File.Exists(GrabberSettingsAndPaths.DownloadEventFilePath))
        {
            try
            {
                var dl = JsonSerializer.Deserialize<DownloadEventPayload>(
                    File.ReadAllText(GrabberSettingsAndPaths.DownloadEventFilePath));
                if (dl is not null && dl.Time > _lastDownloadTime)
                {
                    _lastDownloadTime = dl.Time;
                    var folder = (dl.Folder ?? "").Trim();
                    if (string.IsNullOrEmpty(folder) && !string.IsNullOrEmpty(dl.Path))
                        folder = Path.GetFileName(Path.GetDirectoryName(dl.Path) ?? "") ?? "";
                    var locText = !string.IsNullOrEmpty(folder) && !folder.Equals("downloads", StringComparison.OrdinalIgnoreCase)
                        ? $"folder '{folder}'"
                        : "Downloads folder";
                    SetStatus($"✓ Downloaded '{dl.Filename}' (saved to {locText})");
                }
            }
            catch { }
        }

        if (File.Exists(GrabberSettingsAndPaths.LoadingHistoryEventFilePath))
        {
            try
            {
                var ev = JsonSerializer.Deserialize<LoadingHistoryEventPayload>(
                    File.ReadAllText(GrabberSettingsAndPaths.LoadingHistoryEventFilePath));
                if (ev is not null &&
                    (ev.Action == "open_loading_history" || ev.Action == "download_loading_history") &&
                    ev.Time > _lastLoadingHistoryTime)
                {
                    _lastLoadingHistoryTime = ev.Time;
                    StartLoadingHistoryBrowser(
                        ev.Gatepass,
                        ev.JobId,
                        ev.Client,
                        stopAtGatepass: false,
                        ev.PageCode ?? "",
                        ev.ReportName ?? "");
                }
            }
            catch { }
        }
    }

    private void ShowResults(IEnumerable<PortalJobRecord> items, bool playSoundAlert = true)
    {
        var nextRecords = new List<PortalJobRecord>();
        foreach (var item in items)
        {
            var jid = GrabberSettingsAndPaths.Clean(item.JobId);
            if (string.IsNullOrEmpty(jid))
                continue;
            nextRecords.Add(new PortalJobRecord
            {
                JobId = jid,
                Status = GrabberSettingsAndPaths.NormalizeReconciliationStatus(item.Status),
                Client = GrabberSettingsAndPaths.Clean(item.Client),
                Warehouse = GrabberSettingsAndPaths.Clean(item.Warehouse),
                Gatepass = GrabberSettingsAndPaths.Clean(item.Gatepass),
                Seal = GrabberSettingsAndPaths.Clean(item.Seal),
                DeliveryLocation = GrabberSettingsAndPaths.Clean(item.DeliveryLocation),
                WarfId = GrabberSettingsAndPaths.Clean(item.WarfId)
            });
        }

        _records.Clear();
        _records.AddRange(nextRecords);
        _jobsObservedAtIso = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffZ");
        PublishJobSnapshot();

        var selectedIds = GetSelectedJobIds();
        _rows.Clear();
        foreach (var r in _records)
            _rows.Add(BuildRowItem(r));
        RestoreSelection(selectedIds);

        int pendingCount = _records.Count(r => r.Status == "Pending");
        int inProgressCount = _records.Count(r => r.Status == "In Progress");
        int otherCount = _records.Count - pendingCount - inProgressCount;

        var parts = new List<string>();
        if (pendingCount > 0) parts.Add($"{pendingCount} Pending");
        if (inProgressCount > 0) parts.Add($"{inProgressCount} In Progress");
        if (otherCount > 0) parts.Add($"{otherCount} Other");
        var breakdown = parts.Count > 0 ? $" ({string.Join(", ", parts)})" : "";
        SetStatus($"Collected {_records.Count} Job ID(s){breakdown}. Browser remains open; close it when finished.");

        var currentPending = _records
            .Where(r => r.Status == "Pending" && !string.IsNullOrWhiteSpace(r.JobId))
            .Select(r => r.JobId.Trim())
            .ToHashSet(StringComparer.OrdinalIgnoreCase);

        bool hasNewPending = currentPending.Any(id => !_seenPendingIds.Contains(id));
        if (playSoundAlert && hasNewPending && _soundEnabled)
            GrabberSettingsAndPaths.PlayNotificationSound(string.IsNullOrWhiteSpace(_soundPath) ? null : _soundPath);

        _seenPendingIds.Clear();
        foreach (var id in currentPending)
            _seenPendingIds.Add(id);
    }

    private PendingJobRowItem BuildRowItem(PortalJobRecord rec)
    {
        var tag = rec.Status switch
        {
            "Pending" => "pending",
            "In Progress" => "in_progress",
            "Completed" => "completed",
            _ => "other"
        };

        return new PendingJobRowItem
        {
            AssignedUser = GetAssignedUser(rec),
            JobId = rec.JobId,
            Client = rec.Client,
            Status = rec.Status,
            StatusTag = tag,
            Record = rec
        };
    }

    private string GetAssignedUser(PortalJobRecord record)
    {
        var key = ((record.JobId ?? "").Trim().ToLowerInvariant(),
                   (record.Warehouse ?? "").Trim().ToLowerInvariant());
        return _jobAssignments.TryGetValue(key, out var owner) ? owner : "";
    }

    private void PublishJobSnapshot()
    {
        if (OnJobsChanged is null || string.IsNullOrEmpty(_jobsObservedAtIso))
            return;

        var snapshot = _records
            .Where(r => !string.IsNullOrEmpty(r.JobId))
            .Select(r => new Dictionary<string, object?>(StringComparer.Ordinal)
            {
                ["job_id"] = r.JobId,
                ["warehouse"] = r.Warehouse ?? "",
                ["client"] = r.Client ?? "",
                ["status"] = r.Status ?? "",
                ["assigned_user"] = GetAssignedUser(r),
                ["observed_at"] = _jobsObservedAtIso
            })
            .ToList();

        OnJobsChanged.Invoke(snapshot);
    }

    private void FindAndEmbedInternalBrowserTick()
    {
        if (_browserProcess is null)
        {
            _internalEmbedTimer.Stop();
            return;
        }

        if (_browserProcess.HasExited)
        {
            int code = _browserProcess.ExitCode;
            _browserProcess = null;
            _browserHwnd = IntPtr.Zero;
            _internalEmbedTimer.Stop();

            string detail = ReadTailLog(GrabberSettingsAndPaths.BrowserLogFilePath);
            string msg = $"The internal browser helper process terminated unexpectedly (exit code {code}).";
            if (!string.IsNullOrWhiteSpace(detail))
                msg += $"\n\nDiagnostic Output:\n{detail}";

            SetStatus($"Internal browser closed unexpectedly (exit code {code}).");
            System.Windows.MessageBox.Show(Window.GetWindow(this), msg, "Internal Browser Error", MessageBoxButton.OK, MessageBoxImage.Error);
            return;
        }

        if (_browserHwnd != IntPtr.Zero)
        {
            _internalEmbedTimer.Stop();
            return;
        }

        var hwnd = FindBrowserWindowForPid(_browserProcess.Id, "Reconciliation Browser");
        if (hwnd != IntPtr.Zero)
        {
            try
            {
                if (_reconciliationPanel.Handle == IntPtr.Zero)
                    return;
                Win32Interop.AttachChildWindow(hwnd, _reconciliationPanel.Handle);
                _browserHwnd = hwnd;
                _reconciliationPlaceholderLabel.Visible = false;
                ResizeInternalBrowser();
                Win32Interop.ShowWindow(hwnd, _isViewVisible ? Win32Interop.SW_SHOW : Win32Interop.SW_HIDE);
                _internalEmbedTimer.Stop();
                return;
            }
            catch (Exception ex)
            {
                SetStatus($"Could not embed the internal browser: {ex.Message}");
                _internalEmbedTimer.Stop();
                return;
            }
        }

        _browserEmbedAttempts++;
        if (_browserEmbedAttempts >= 150)
        {
            _internalEmbedTimer.Stop();
            SetStatus("The internal browser did not become available for embedding. It may be running as a floating window.");
        }
    }

    private void FindAndEmbedLoadingHistoryTick()
    {
        if (_loadingHistoryProcess is null)
        {
            _lhEmbedTimer.Stop();
            return;
        }

        if (_loadingHistoryProcess.HasExited)
        {
            _loadingHistoryProcess = null;
            _loadingHistoryHwnd = IntPtr.Zero;
            _lhEmbedTimer.Stop();
            SetStatus("The Loading History browser closed unexpectedly.");
            return;
        }

        if (_loadingHistoryHwnd != IntPtr.Zero)
        {
            _lhEmbedTimer.Stop();
            return;
        }

        var hwnd = FindBrowserWindowForPid(_loadingHistoryProcess.Id, "Loading History");
        if (hwnd != IntPtr.Zero)
        {
            try
            {
                if (_loadingHistoryPanel.Handle == IntPtr.Zero)
                    return;
                Win32Interop.AttachChildWindow(hwnd, _loadingHistoryPanel.Handle);
                _loadingHistoryHwnd = hwnd;
                _loadingHistoryPlaceholderLabel.Visible = false;
                ResizeLoadingHistoryBrowser();
                Win32Interop.ShowWindow(hwnd, _isViewVisible ? Win32Interop.SW_SHOW : Win32Interop.SW_HIDE);
                SetStatus("Reconciliation and Loading History are open side by side.");
                _lhEmbedTimer.Stop();
                return;
            }
            catch (Exception ex)
            {
                SetStatus($"Could not embed Loading History: {ex.Message}");
                _lhEmbedTimer.Stop();
                return;
            }
        }

        _loadingHistoryEmbedAttempts++;
        if (_loadingHistoryEmbedAttempts >= 150)
        {
            _lhEmbedTimer.Stop();
            SetStatus("Loading History did not become available for embedding.");
        }
    }

    private static IntPtr FindBrowserWindowForPid(int pid, string titleHint)
    {
        var wins = Win32Interop.FindWindowsForPid(pid);
        foreach (var (hwnd, title, visible) in wins)
        {
            if (visible && (title.Contains(titleHint, StringComparison.OrdinalIgnoreCase) ||
                            title.Contains("EFL NEXUS", StringComparison.OrdinalIgnoreCase)))
            {
                return hwnd;
            }
        }
        return IntPtr.Zero;
    }

    private void ResizeInternalBrowser()
    {
        if (_browserHwnd == IntPtr.Zero)
            return;
        try
        {
            int w = Math.Max(1, _reconciliationPanel.ClientSize.Width);
            int h = Math.Max(1, _reconciliationPanel.ClientSize.Height);
            Win32Interop.MoveWindow(_browserHwnd, 0, 0, w, h, true);
        }
        catch { }
    }

    private void ResizeLoadingHistoryBrowser()
    {
        if (_loadingHistoryHwnd == IntPtr.Zero)
            return;
        try
        {
            int w = Math.Max(1, _loadingHistoryPanel.ClientSize.Width);
            int h = Math.Max(1, _loadingHistoryPanel.ClientSize.Height);
            Win32Interop.MoveWindow(_loadingHistoryHwnd, 0, 0, w, h, true);
        }
        catch { }
    }

    private static void SetEmbeddedWindowVisible(IntPtr hwnd, bool visible)
    {
        if (hwnd == IntPtr.Zero)
            return;
        try { Win32Interop.ShowWindow(hwnd, visible ? Win32Interop.SW_SHOW : Win32Interop.SW_HIDE); }
        catch { }
    }

    private void StartSelectedJob()
    {
        if (JobsGrid.SelectedItem is not PendingJobRowItem row)
        {
            System.Windows.MessageBox.Show(
                Window.GetWindow(this),
                "Please select a job from the list first.",
                "Select Job",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
            return;
        }

        var jobId = (row.JobId ?? "").Trim();
        if (string.IsNullOrEmpty(jobId))
            return;

        string gp = (row.Record.Gatepass ?? "").Trim();
        string cli = (row.Record.Client ?? "").Trim();
        if (string.IsNullOrEmpty(gp))
        {
            try
            {
                var persisted = GrabberSettingsAndPaths.LoadPersistedJobMap();
                if (persisted.TryGetValue(jobId.ToLowerInvariant(), out var mapped))
                {
                    gp = (mapped.Gatepass ?? "").Trim();
                    if (string.IsNullOrEmpty(cli))
                        cli = (mapped.Client ?? "").Trim();
                }
            }
            catch { }
        }

        _activeJobId = jobId;
        _activeGatepass = gp;
        _activeClient = cli;

        if (!IsProcessRunning(_browserProcess))
        {
            var res = System.Windows.MessageBox.Show(
                Window.GetWindow(this),
                $"The internal browser is not currently running.\n\nWould you like to open it now to start job '{jobId}'?",
                "Browser Not Open",
                MessageBoxButton.YesNo,
                MessageBoxImage.Question);
            if (res == MessageBoxResult.Yes)
            {
                StartBrowsers();
                if (SendBrowserCommand("start_job", jobId: jobId, gatepass: gp, client: cli))
                    NotifyJobStarted(row.Record);
            }
            return;
        }

        if (SendBrowserCommand("start_job", jobId: jobId, gatepass: gp, client: cli))
        {
            SetStatus($"Sent Start request for Job ID '{jobId}' to the portal browser...");
            NotifyJobStarted(row.Record);
        }
    }

    private void NotifyJobStarted(PortalJobRecord source)
    {
        if (OnJobStarted is null)
            return;

        try
        {
            var rec = new PortalJobRecord
            {
                JobId = source.JobId,
                Client = source.Client,
                Status = source.Status,
                Warehouse = source.Warehouse,
                Gatepass = source.Gatepass,
                Seal = source.Seal,
                DeliveryLocation = source.DeliveryLocation,
                WarfId = source.WarfId
            };

            var persisted = GrabberSettingsAndPaths.LoadPersistedJobMap();
            if (persisted.TryGetValue(rec.JobId.ToLowerInvariant(), out var mapped))
            {
                if (string.IsNullOrEmpty(rec.Client)) rec.Client = mapped.Client;
                if (string.IsNullOrEmpty(rec.Warehouse)) rec.Warehouse = mapped.Warehouse;
                if (string.IsNullOrEmpty(rec.Gatepass)) rec.Gatepass = mapped.Gatepass;
            }

            OnJobStarted.Invoke(rec);
        }
        catch (Exception ex)
        {
            SetStatus($"Start dispatched; KPI needs attention: {ex.Message}");
        }
    }

    private void CreateGatepassForSelectedJob()
    {
        if (JobsGrid.SelectedItem is not PendingJobRowItem row)
        {
            System.Windows.MessageBox.Show(
                Window.GetWindow(this),
                "Please select a job from the list first.",
                "Select Job",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
            return;
        }

        var jobId = (row.JobId ?? "").Trim();
        if (string.IsNullOrEmpty(jobId))
            return;

        var rec = new PortalJobRecord
        {
            JobId = row.Record.JobId,
            Client = row.Record.Client,
            Status = row.Record.Status,
            Warehouse = row.Record.Warehouse,
            Gatepass = row.Record.Gatepass,
            Seal = row.Record.Seal,
            DeliveryLocation = row.Record.DeliveryLocation,
            WarfId = row.Record.WarfId
        };

        if (jobId.StartsWith("OUT_", StringComparison.OrdinalIgnoreCase))
        {
            if (string.IsNullOrWhiteSpace(rec.DeliveryLocation) || rec.DeliveryLocation.Trim() == "-")
                rec.DeliveryLocation = "N/A";
            if (string.IsNullOrWhiteSpace(rec.Seal) || rec.Seal.Trim() == "-")
                rec.Seal = "N/A";
        }

        if (OnCreateGatepass is not null)
        {
            OnCreateGatepass.Invoke(rec);
        }
        else
        {
            System.Windows.MessageBox.Show(
                Window.GetWindow(this),
                $"Job: {rec.JobId}\nWH: {rec.Warehouse}\nClient: {rec.Client}\nGatepass: {rec.Gatepass}",
                "Create Gatepass",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
        }
    }

    private void DownloadSelectedJobFiles()
    {
        if (JobsGrid.SelectedItem is not PendingJobRowItem row)
        {
            System.Windows.MessageBox.Show(
                Window.GetWindow(this),
                "Please select a job from the list first.",
                "Select Job",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
            return;
        }

        var jobId = (row.JobId ?? "").Trim();
        if (string.IsNullOrEmpty(jobId))
            return;

        var gatepass = row.Record.Gatepass ?? "";
        var client = row.Record.Client ?? "";

        if (!IsProcessRunning(_browserProcess))
        {
            var res = System.Windows.MessageBox.Show(
                Window.GetWindow(this),
                $"The internal browser is not currently running.\n\nWould you like to open it now to view and download files for job '{jobId}'?",
                "Browser Not Open",
                MessageBoxButton.YesNo,
                MessageBoxImage.Question);
            if (res == MessageBoxResult.Yes)
            {
                StartBrowsers();
                SendBrowserCommand("start_job", jobId: jobId, gatepass: gatepass, client: client);
                var delay = new DispatcherTimer { Interval = TimeSpan.FromSeconds(2) };
                delay.Tick += (_, _) =>
                {
                    delay.Stop();
                    SendBrowserCommand("download_job_files", jobId: jobId, gatepass: gatepass, client: client);
                };
                delay.Start();
            }
            return;
        }

        if (SendBrowserCommand("download_job_files", jobId: jobId, gatepass: gatepass, client: client))
        {
            var folderName = new DirectoryInfo(GrabberSettingsAndPaths.GetJobDownloadFolder(jobId, gatepass, client)).Name;
            SetStatus($"Requested file download for Job ID '{jobId}' (saving to folder '{folderName}')...");
        }
    }

    private void DownloadSelectedJobLoadingHistory()
    {
        if (JobsGrid.SelectedItem is not PendingJobRowItem row)
        {
            System.Windows.MessageBox.Show(
                Window.GetWindow(this),
                "Please select a job from the list first.",
                "Select Job",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
            return;
        }

        var jobId = (row.JobId ?? "").Trim();
        if (string.IsNullOrEmpty(jobId))
            return;

        var gatepass = (row.Record.Gatepass ?? "").Trim();
        var client = (row.Record.Client ?? "").Trim();

        if (string.IsNullOrEmpty(gatepass))
        {
            var persisted = GrabberSettingsAndPaths.LoadPersistedJobMap();
            if (persisted.TryGetValue(jobId.ToLowerInvariant(), out var mapped))
            {
                gatepass = (mapped.Gatepass ?? "").Trim();
                if (string.IsNullOrEmpty(client))
                    client = (mapped.Client ?? "").Trim();
            }
        }

        string pageCode = jobId.StartsWith("IN", StringComparison.OrdinalIgnoreCase) ? "2598" : "1992";
        string reportName = jobId.StartsWith("IN", StringComparison.OrdinalIgnoreCase) ? "Inventory by gatepass" : "Loading History Report";

        if (string.IsNullOrEmpty(gatepass))
        {
            string reportTitle = pageCode == "2598" ? "Inventory by Gatepass" : "Loading History";
            System.Windows.MessageBox.Show(
                Window.GetWindow(this),
                $"No Gate Pass is associated with Job ID '{jobId}'.\nPlease enter the Gate Pass manually in the {reportTitle} browser.",
                "Gate Pass Not Found",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
            return;
        }

        StartLoadingHistoryBrowser(gatepass, jobId, client, stopAtGatepass: false, pageCode, reportName);
    }

    private void OpenSelectedJobFolder()
    {
        string jobId = "", gatepass = "", client = "";
        if (JobsGrid.SelectedItem is PendingJobRowItem row)
        {
            jobId = (row.JobId ?? "").Trim();
            gatepass = (row.Record.Gatepass ?? "").Trim();
            client = (row.Record.Client ?? "").Trim();
        }

        var targetDir = GrabberSettingsAndPaths.GetJobDownloadFolder(jobId, gatepass, client);
        try
        {
            Process.Start(new ProcessStartInfo(Path.GetFullPath(targetDir)) { UseShellExecute = true });
            SetStatus($"Opened folder: {new DirectoryInfo(targetDir).Name}");
        }
        catch (Exception ex)
        {
            System.Windows.MessageBox.Show(
                Window.GetWindow(this),
                $"Could not open directory {targetDir}: {ex.Message}",
                "Open Folder Error",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
        }
    }

    private void CopyRows(IReadOnlyList<PendingJobRowItem> rows)
    {
        var lines = new List<string>();
        foreach (var r in rows)
        {
            var cols = new List<string>();
            if (!string.IsNullOrEmpty(r.AssignedUser))
                cols.Add(r.AssignedUser);
            cols.Add(r.JobId);
            if (!string.IsNullOrEmpty(r.Client))
                cols.Add(r.Client);
            cols.Add(r.Status);
            lines.Add(string.Join("\t", cols));
        }

        if (lines.Count > 0)
        {
            System.Windows.Clipboard.SetText(string.Join("\n", lines));
            SetStatus($"Copied {lines.Count} row(s) to clipboard.");
        }
    }

    private void ExportCsv()
    {
        if (_records.Count == 0)
        {
            System.Windows.MessageBox.Show(
                Window.GetWindow(this),
                "Run the grabber first.",
                "No results",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
            return;
        }

        var dlg = new Microsoft.Win32.SaveFileDialog
        {
            Title = "Export Job IDs & Status",
            DefaultExt = ".csv",
            Filter = "CSV files (*.csv)|*.csv",
            FileName = "reconciliation_job_ids.csv"
        };
        if (dlg.ShowDialog() != true)
            return;

        bool hasOwner = _records.Any(r => !string.IsNullOrEmpty(GetAssignedUser(r)));
        bool hasClient = _records.Any(r => !string.IsNullOrEmpty(r.Client));

        var sb = new StringBuilder();
        var headers = new List<string>();
        if (hasOwner) headers.Add("Assigned User");
        headers.Add("Job ID");
        if (hasClient) headers.Add("Client");
        headers.Add("Reconciliation Status");
        sb.AppendLine(string.Join(",", headers.Select(CsvEscape)));

        foreach (var r in _records)
        {
            var cells = new List<string>();
            if (hasOwner) cells.Add(GetAssignedUser(r));
            cells.Add(r.JobId);
            if (hasClient) cells.Add(r.Client);
            cells.Add(r.Status);
            sb.AppendLine(string.Join(",", cells.Select(CsvEscape)));
        }

        File.WriteAllText(dlg.FileName, sb.ToString(), new UTF8Encoding(encoderShouldEmitUTF8Identifier: true));
        SetStatus($"Exported {_records.Count} Job ID(s) to {dlg.FileName}.");
    }

    private bool SendBrowserCommand(
        string action,
        string? jobId = null,
        string? gatepass = null,
        string? client = null,
        int? seconds = null,
        string? url = null)
    {
        try
        {
            var payload = new Dictionary<string, object?>
            {
                ["action"] = action,
                ["timestamp"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0
            };
            if (jobId is not null) payload["job_id"] = jobId;
            if (gatepass is not null) payload["gatepass"] = gatepass;
            if (client is not null) payload["client"] = client;
            if (seconds.HasValue) payload["seconds"] = seconds.Value;
            if (url is not null) payload["url"] = url;

            GrabberSettingsAndPaths.WriteJsonAtomic(
                GrabberSettingsAndPaths.CommandFilePath,
                JsonSerializer.Serialize(payload));
            return true;
        }
        catch (Exception ex)
        {
            System.Windows.MessageBox.Show(
                Window.GetWindow(this),
                $"Could not send command to browser: {ex.Message}",
                "Command Error",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
            return false;
        }
    }

    private bool SendLoadingHistoryCommand(
        string action,
        string gatepass,
        string jobId,
        string client,
        string pageCode = "",
        string reportName = "")
    {
        try
        {
            var payload = new Dictionary<string, object?>
            {
                ["action"] = action,
                ["timestamp"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0,
                ["gatepass"] = gatepass,
                ["job_id"] = jobId,
                ["client"] = client
            };
            if (!string.IsNullOrEmpty(pageCode)) payload["page_code"] = pageCode;
            if (!string.IsNullOrEmpty(reportName)) payload["report_name"] = reportName;
            GrabberSettingsAndPaths.WriteJsonAtomic(
                GrabberSettingsAndPaths.LoadingHistoryCommandFilePath,
                JsonSerializer.Serialize(payload));
            return true;
        }
        catch (Exception ex)
        {
            System.Windows.MessageBox.Show(
                Window.GetWindow(this),
                $"Could not send command to Loading History browser: {ex.Message}",
                "Command Error",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
            return false;
        }
    }

    private HashSet<string> GetSelectedJobIds()
        => JobsGrid.SelectedItems
            .OfType<PendingJobRowItem>()
            .Select(r => r.JobId)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);

    private void RestoreSelection(HashSet<string> selectedIds)
    {
        if (selectedIds.Count == 0)
            return;
        foreach (var item in _rows)
        {
            if (selectedIds.Contains(item.JobId))
                JobsGrid.SelectedItems.Add(item);
        }
    }

    private static bool RecordsEqual(List<PortalJobRecord> a, List<PortalJobRecord> b)
    {
        if (a.Count != b.Count)
            return false;
        for (int i = 0; i < a.Count; i++)
        {
            if (!string.Equals(a[i].JobId, b[i].JobId, StringComparison.Ordinal) ||
                !string.Equals(a[i].Client, b[i].Client, StringComparison.Ordinal) ||
                !string.Equals(a[i].Status, b[i].Status, StringComparison.Ordinal) ||
                !string.Equals(a[i].Warehouse, b[i].Warehouse, StringComparison.Ordinal) ||
                !string.Equals(a[i].Gatepass, b[i].Gatepass, StringComparison.Ordinal))
            {
                return false;
            }
        }
        return true;
    }

    private static bool IsProcessRunning(Process? p)
    {
        if (p is null) return false;
        try { return !p.HasExited; }
        catch { return false; }
    }

    private static void TerminateProcessSafe(ref Process? process)
    {
        var p = process;
        process = null;
        if (p is null) return;
        try
        {
            if (!p.HasExited)
            {
                p.CloseMainWindow();
                if (!p.WaitForExit(1000))
                    p.Kill(true);
            }
        }
        catch
        {
            try { p.Kill(true); } catch { }
        }
        finally
        {
            try { p.Dispose(); } catch { }
        }
    }

    private static double ReadTimestampFromJson(string filePath)
    {
        if (!File.Exists(filePath)) return 0.0;
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(filePath));
            if (doc.RootElement.TryGetProperty("time", out var tEl) && tEl.TryGetDouble(out double ts))
                return ts;
        }
        catch { }
        return 0.0;
    }

    private static readonly object LogAppendLock = new();

    private static void AppendBrowserLogLine(string path, string? line)
    {
        if (string.IsNullOrEmpty(line))
            return;
        try
        {
            lock (LogAppendLock)
                File.AppendAllText(path, line + Environment.NewLine, Encoding.UTF8);
        }
        catch { }
    }

    private static string ReadTailLog(string path)
    {
        try
        {
            if (!File.Exists(path)) return "";
            var lines = File.ReadAllLines(path);
            return string.Join(Environment.NewLine, lines.TakeLast(10)).Trim();
        }
        catch
        {
            return "";
        }
    }

    private static string CsvEscape(string? val)
    {
        var s = val ?? "";
        if (s.Contains('"') || s.Contains(',') || s.Contains('\n') || s.Contains('\r'))
            return "\"" + s.Replace("\"", "\"\"") + "\"";
        return s;
    }

    // ------------------------------------------------------------------
    // WPF Event Handlers
    // ------------------------------------------------------------------
    private void RunBtn_Click(object sender, RoutedEventArgs e) => StartBrowsers();
    private void RestartBtn_Click(object sender, RoutedEventArgs e) => RestartBrowser();
    private void SettingsBtn_Click(object sender, RoutedEventArgs e) => OnOpenSettings?.Invoke();

    private void RefreshCombo_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_suppressRefreshCombo)
            return;
        if (RefreshCombo.SelectedItem is string val)
            SetRefreshInterval(val, save: true);
    }

    private void RefreshCombo_KeyDown(object sender, System.Windows.Input.KeyEventArgs e)
    {
        if (e.Key == Key.Enter)
            SetRefreshInterval(RefreshCombo.Text, save: true);
    }

    private void RefreshCombo_LostFocus(object sender, RoutedEventArgs e)
    {
        if (!_suppressRefreshCombo)
            SetRefreshInterval(RefreshCombo.Text, save: true);
    }

    private void SoundBtn_Click(object sender, RoutedEventArgs e)
    {
        SetSoundEnabled(!_soundEnabled, save: true);
    }

    private void BackBtn_Click(object sender, RoutedEventArgs e)
    {
        if (IsProcessRunning(_browserProcess))
        {
            SendBrowserCommand("go_back");
            SetStatus("Navigating back to the previous page...");
        }
        else
        {
            System.Windows.MessageBox.Show(Window.GetWindow(this), "Open the internal browser first.", "Browser Not Open", MessageBoxButton.OK, MessageBoxImage.Information);
        }
    }

    private void ReloadBtn_Click(object sender, RoutedEventArgs e)
    {
        if (IsProcessRunning(_browserProcess))
        {
            SendBrowserCommand("reload");
            SetStatus("Reloading portal browser...");
        }
        else
        {
            System.Windows.MessageBox.Show(Window.GetWindow(this), "Open the internal browser first.", "Browser Not Open", MessageBoxButton.OK, MessageBoxImage.Information);
        }
    }

    private void HomeBtn_Click(object sender, RoutedEventArgs e)
    {
        var target = string.IsNullOrWhiteSpace(_reconciliationUrl) ? GrabberSettingsAndPaths.DefaultReconciliationUrl : _reconciliationUrl;
        if (IsProcessRunning(_browserProcess))
        {
            SendBrowserCommand("go_home", url: target);
            SetStatus("Navigating to Reconciliation dashboard...");
        }
        else
        {
            System.Windows.MessageBox.Show(Window.GetWindow(this), "Open the internal browser first.", "Browser Not Open", MessageBoxButton.OK, MessageBoxImage.Information);
        }
    }

    private void ExportCsvBtn_Click(object sender, RoutedEventArgs e) => ExportCsv();

    private void CopyBtn_Click(object sender, RoutedEventArgs e)
    {
        if (_rows.Count == 0)
        {
            System.Windows.MessageBox.Show(Window.GetWindow(this), "Run the grabber first.", "No results", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }
        CopyRows(_rows);
    }

    private void JobsGrid_PreviewKeyDown(object sender, System.Windows.Input.KeyEventArgs e)
    {
        if (e.Key == Key.C && (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control)
        {
            var selected = JobsGrid.SelectedItems.OfType<PendingJobRowItem>().ToList();
            if (selected.Count > 0)
                CopyRows(selected);
            e.Handled = true;
        }
        else if (e.Key == Key.Enter)
        {
            StartSelectedJob();
            e.Handled = true;
        }
    }

    private void JobsGrid_MouseDoubleClick(object sender, MouseButtonEventArgs e)
    {
        if (JobsGrid.SelectedItem is PendingJobRowItem)
            StartSelectedJob();
    }

    private void JobsGrid_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (JobsGrid.SelectedItem is PendingJobRowItem row)
        {
            var jobId = (row.JobId ?? "").Trim();
            if (jobId.StartsWith("IN", StringComparison.OrdinalIgnoreCase))
            {
                DownloadLoadingHistoryBtn.Content = "📥 Download Inventory by Gatepass";
                if (LoadingHistoryHeaderTitle is not null)
                    LoadingHistoryHeaderTitle.Text = "Inventory by Gatepass — enter Gate Pass manually";
                return;
            }
        }
        DownloadLoadingHistoryBtn.Content = "📥 Download Loading History";
        if (LoadingHistoryHeaderTitle is not null)
            LoadingHistoryHeaderTitle.Text = "Loading History — enter Gate Pass manually";
    }

    private void StartRowBtn_Click(object sender, RoutedEventArgs e)
    {
        if (sender is System.Windows.Controls.Button { DataContext: PendingJobRowItem row })
        {
            JobsGrid.SelectedItem = row;
            StartSelectedJob();
        }
    }

    private void CreateGatepassBtn_Click(object sender, RoutedEventArgs e) => CreateGatepassForSelectedJob();
    private void DownloadExcelBtn_Click(object sender, RoutedEventArgs e) => DownloadSelectedJobFiles();
    private void DownloadLoadingHistoryBtn_Click(object sender, RoutedEventArgs e) => DownloadSelectedJobLoadingHistory();
    private void OpenFolderBtn_Click(object sender, RoutedEventArgs e) => OpenSelectedJobFolder();

    private void ReconciliationBrowserHost_SizeChanged(object sender, SizeChangedEventArgs e) => ResizeInternalBrowser();
    private void LoadingHistoryBrowserHost_SizeChanged(object sender, SizeChangedEventArgs e) => ResizeLoadingHistoryBrowser();
}
