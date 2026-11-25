using System.Diagnostics;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using EflNexus.App.Dialogs;
using EflNexus.Core.Infrastructure;
using EflNexus.Core.Korber;
using EflNexus.Core.OutlookEmail;
using EflNexus.Core.PendingJobs;
using MediaColor = System.Windows.Media.Color;
using OpenFileDialog = Microsoft.Win32.OpenFileDialog;
using SolidBrush = System.Windows.Media.SolidColorBrush;
using UserControl = System.Windows.Controls.UserControl;

namespace EflNexus.App.Views;

public partial class SettingsView : UserControl
{
    private static readonly SolidBrush MintBrush = new(MediaColor.FromRgb(0x49, 0xCF, 0x9E));
    private static readonly SolidBrush AmberBrush = new(MediaColor.FromRgb(0xF5, 0x9E, 0x0B));
    private static readonly SolidBrush ErrorBrush = new(MediaColor.FromRgb(0xDC, 0x26, 0x26));
    private static readonly SolidBrush MutedBrush = new(MediaColor.FromRgb(0x64, 0x74, 0x8B));

    private ConfigStore _configStore;
    private bool _korberPassVisible;
    private bool _auditShipPassVisible;
    private bool _grabberPassVisible;

    public Action? OnCheckUpdatesRequested { get; set; }
    public Action<KpiUserProfile>? OnKpiProfileSaved { get; set; }
    public Action? OnOpenPresenceSettingsRequested { get; set; }
    public Action<string, string, string, string, string, bool, string>? OnTool6SettingsChanged { get; set; }
    public Action? OnGoogleSheetsSaved { get; set; }
    public Action? OnCacheCleared { get; set; }

    public SettingsView() : this(null)
    {
    }

    public SettingsView(ConfigStore? configStore)
    {
        InitializeComponent();
        _configStore = configStore ?? new ConfigStore();
        LoadFromConfigStore();
    }

    public void Configure(ConfigStore configStore)
    {
        _configStore = configStore;
        LoadFromConfigStore();
    }

    public void LoadFromConfigStore()
    {
        VersionPillText.Text = $"v{AppPaths.ReadAppVersion()} (Current)";

        // KPI Profile
        KpiUserIdBox.Text = _configStore.Get("kpi_user_id");
        KpiUserCodeBox.Text = _configStore.Get("kpi_user_code");
        var kpiProfile = KpiProfile.LoadSavedProfile(_configStore.FilePath);
        SetPill(KpiStatusText, kpiProfile is not null);

        // Körber Cloud
        var kbUser = _configStore.GetKorberUser();
        var kbPass = _configStore.GetKorberPass();
        var kbUrl = _configStore.GetKorberUrl();
        KorberUserBox.Text = kbUser;
        SetPasswordField(KorberPassBox, KorberPassPlainBox, _korberPassVisible, kbPass);
        KorberUrlBox.Text = kbUrl;
        SetPill(KorberStatusText, !string.IsNullOrEmpty(kbUser) && !string.IsNullOrEmpty(kbPass));

        // AuditShip
        var asUser = _configStore.GetAuditshipUser();
        var asPass = _configStore.GetAuditshipPass();
        var asFork = _configStore.GetAuditshipForkId();
        AuditShipUserBox.Text = asUser;
        SetPasswordField(AuditShipPassBox, AuditShipPassPlainBox, _auditShipPassVisible, asPass);
        AuditShipForkBox.Text = asFork;
        SetPill(AuditShipStatusText, !string.IsNullOrEmpty(asUser) && !string.IsNullOrEmpty(asPass) && !string.IsNullOrEmpty(asFork));

        // Pending Jobs (Tool 6)
        var grabLogin = _configStore.Get("data_grabber_login_url", GrabberSettingsAndPaths.DefaultLoginUrl);
        if (string.IsNullOrWhiteSpace(grabLogin))
            grabLogin = GrabberSettingsAndPaths.DefaultLoginUrl;
        var grabUser = _configStore.Get("data_grabber_user", GrabberSettingsAndPaths.DefaultPortalUsername);
        var grabPass = GrabberSettingsAndPaths.LoadSavedPassword();
        var grabRecon = _configStore.Get("data_grabber_reconciliation_url", GrabberSettingsAndPaths.DefaultReconciliationUrl);
        if (string.IsNullOrWhiteSpace(grabRecon))
            grabRecon = GrabberSettingsAndPaths.DefaultReconciliationUrl;
        var grabRefresh = _configStore.Get("data_grabber_refresh_seconds", GrabberSettingsAndPaths.DefaultRefreshSeconds.ToString());
        if (string.IsNullOrWhiteSpace(grabRefresh))
            grabRefresh = GrabberSettingsAndPaths.DefaultRefreshSeconds.ToString();
        bool grabSoundEnabled = !string.Equals(_configStore.Get("data_grabber_sound_enabled", "True"), "False", StringComparison.OrdinalIgnoreCase);
        var grabSoundPath = _configStore.Get("data_grabber_sound_path", "");

        GrabberLoginUrlBox.Text = grabLogin;
        GrabberUserBox.Text = grabUser;
        SetPasswordField(GrabberPassBox, GrabberPassPlainBox, _grabberPassVisible, grabPass);
        GrabberReconUrlBox.Text = grabRecon;
        GrabberRefreshSecBox.Text = grabRefresh;
        GrabberSoundEnabledCheck.IsChecked = grabSoundEnabled;
        GrabberSoundPathBox.Text = grabSoundPath;
        SetPill(GrabberStatusText, !string.IsNullOrEmpty(grabUser) && !string.IsNullOrEmpty(grabPass));

        // Google Sheets
        var webappUrl = _configStore.GetWebappUrl();
        var sheetUrl = _configStore.GetSheetUrl();
        WebappUrlBox.Text = webappUrl;
        SheetUrlBox.Text = sheetUrl;
        bool gsConfigured = !string.IsNullOrWhiteSpace(webappUrl) && !string.IsNullOrWhiteSpace(sheetUrl);
        SetPill(GsheetStatusText, gsConfigured);

        // System Diagnostics
        DiagRuntimeText.Text = $".NET {Environment.Version} (64-bit)";
        DiagAppDirText.Text = AppPaths.AppDir;
        DiagKorberStatusText.Text = !string.IsNullOrEmpty(kbUser) && !string.IsNullOrEmpty(kbPass)
            ? $"{kbUser} (Configured)"
            : string.IsNullOrEmpty(kbUser) ? "Needs Setup" : "Password Missing";
        DiagSyncStatusText.Text = gsConfigured ? "Configured" : "Unconfigured";
    }

    public void UpdatePresenceStatus(string status)
        => PresenceStatusText.Text = status;

    private static void SetPill(TextBlock pillText, bool configured)
    {
        pillText.Text = configured ? "● Configured" : "● Needs Setup";
        pillText.Foreground = configured ? MintBrush : AmberBrush;
    }

    private static void SetPasswordField(PasswordBox pwdBox, System.Windows.Controls.TextBox plainBox, bool plainVisible, string value)
    {
        pwdBox.Password = value;
        plainBox.Text = value;
        pwdBox.Visibility = plainVisible ? Visibility.Collapsed : Visibility.Visible;
        plainBox.Visibility = plainVisible ? Visibility.Visible : Visibility.Collapsed;
    }

    private static string ReadPasswordField(PasswordBox pwdBox, System.Windows.Controls.TextBox plainBox, bool plainVisible)
        => plainVisible ? plainBox.Text : pwdBox.Password;

    private static bool TogglePasswordField(PasswordBox pwdBox, System.Windows.Controls.TextBox plainBox, System.Windows.Controls.Button toggleBtn, bool currentVisible)
    {
        if (currentVisible)
        {
            pwdBox.Password = plainBox.Text;
            plainBox.Visibility = Visibility.Collapsed;
            pwdBox.Visibility = Visibility.Visible;
            toggleBtn.Content = "👁 Show";
            return false;
        }
        else
        {
            plainBox.Text = pwdBox.Password;
            pwdBox.Visibility = Visibility.Collapsed;
            plainBox.Visibility = Visibility.Visible;
            toggleBtn.Content = "🔒 Hide";
            return true;
        }
    }

    private static void ShowTemporaryMessage(TextBlock label, string text, SolidBrush color, int durationMs = 3500)
    {
        label.Text = text;
        label.Foreground = color;
        var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(durationMs) };
        timer.Tick += (_, _) =>
        {
            timer.Stop();
            if (label.Text == text)
                label.Text = string.Empty;
        };
        timer.Start();
    }

    private void CheckUpdates_Click(object sender, RoutedEventArgs e)
        => OnCheckUpdatesRequested?.Invoke();

    private void OpenPresenceSettings_Click(object sender, RoutedEventArgs e)
        => OnOpenPresenceSettingsRequested?.Invoke();

    private void SaveKpiProfile_Click(object sender, RoutedEventArgs e)
    {
        KpiUserProfile validated;
        try
        {
            validated = KpiProfile.ValidateProfile(KpiUserIdBox.Text, KpiUserCodeBox.Text);
        }
        catch (Exception ex)
        {
            KpiMsgText.Text = ex.Message;
            KpiMsgText.Foreground = ErrorBrush;
            return;
        }

        var snapshot = new Dictionary<string, string>(_configStore.Config, StringComparer.Ordinal);
        if (!_configStore.SaveKeyValues(("kpi_user_id", validated.UserId), ("kpi_user_code", validated.UserCode)))
        {
            _configStore.Config.Clear();
            foreach (var kv in snapshot)
                _configStore.Config[kv.Key] = kv.Value;
            KpiMsgText.Text = "Could not save KPI profile. Check file access.";
            KpiMsgText.Foreground = ErrorBrush;
            return;
        }

        KpiUserIdBox.Text = validated.UserId;
        SetPill(KpiStatusText, true);
        KpiMsgText.Text = "KPI profile saved.";
        KpiMsgText.Foreground = MintBrush;
        OnKpiProfileSaved?.Invoke(validated);
    }

    private void ToggleKorberPass_Click(object sender, RoutedEventArgs e)
        => _korberPassVisible = TogglePasswordField(KorberPassBox, KorberPassPlainBox, KorberToggleBtn, _korberPassVisible);

    private void SaveKorberSettings_Click(object sender, RoutedEventArgs e)
    {
        var owner = Window.GetWindow(this);
        var user = (KorberUserBox.Text ?? string.Empty).Trim();
        var pwd = ReadPasswordField(KorberPassBox, KorberPassPlainBox, _korberPassVisible).Trim();
        var url = (KorberUrlBox.Text ?? string.Empty).Trim();
        if (string.IsNullOrEmpty(url))
            url = KorberLoginBot.DefaultKorberUrl;

        if (string.IsNullOrEmpty(user) || string.IsNullOrEmpty(pwd))
        {
            System.Windows.MessageBox.Show(owner, "Please enter both User Name and Password for Körber Cloud.", "Incomplete Credentials", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        _configStore.Save(korberUser: user, korberPass: pwd, korberUrl: url);
        try { KorberLoginBot.SaveCredentials(user, pwd, url); } catch { }

        SetPill(KorberStatusText, true);
        DiagKorberStatusText.Text = $"{user} (Configured)";
        ShowTemporaryMessage(KorberMsgText, "✓ Credentials saved successfully!", MintBrush);
    }

    private void ToggleAuditShipPass_Click(object sender, RoutedEventArgs e)
        => _auditShipPassVisible = TogglePasswordField(AuditShipPassBox, AuditShipPassPlainBox, AuditShipToggleBtn, _auditShipPassVisible);

    private void SaveAuditShipSettings_Click(object sender, RoutedEventArgs e)
    {
        var owner = Window.GetWindow(this);
        var user = (AuditShipUserBox.Text ?? string.Empty).Trim();
        var pwd = ReadPasswordField(AuditShipPassBox, AuditShipPassPlainBox, _auditShipPassVisible).Trim();
        var fork = (AuditShipForkBox.Text ?? string.Empty).Trim();

        if (string.IsNullOrEmpty(user) || string.IsNullOrEmpty(pwd) || string.IsNullOrEmpty(fork))
        {
            System.Windows.MessageBox.Show(owner, "Please enter User Name, Password, and Fork ID for Korber AuditShip.", "Incomplete Credentials", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        if (!_configStore.SaveKeyValues(("auditship_user", user), ("auditship_pass", pwd), ("auditship_fork_id", fork)))
        {
            System.Windows.MessageBox.Show(owner, "AuditShip credentials could not be saved. Check access to config.json.", "Save Failed", MessageBoxButton.OK, MessageBoxImage.Error);
            return;
        }

        SetPill(AuditShipStatusText, true);
        ShowTemporaryMessage(AuditShipMsgText, "✓ Credentials saved successfully!", MintBrush);
    }

    private void ToggleGrabberPass_Click(object sender, RoutedEventArgs e)
        => _grabberPassVisible = TogglePasswordField(GrabberPassBox, GrabberPassPlainBox, GrabberToggleBtn, _grabberPassVisible);

    private void BrowseGrabberSound_Click(object sender, RoutedEventArgs e)
    {
        var dlg = new OpenFileDialog
        {
            Title = "Select Pending Notification Sound",
            Filter = "Audio Files|*.mp3;*.wav;*.wma;*.ogg|All Files|*.*"
        };
        if (dlg.ShowDialog(Window.GetWindow(this)) == true)
            GrabberSoundPathBox.Text = dlg.FileName;
    }

    private void TestGrabberSound_Click(object sender, RoutedEventArgs e)
    {
        var customPath = (GrabberSoundPathBox.Text ?? string.Empty).Trim();
        GrabberSettingsAndPaths.PlayNotificationSound(string.IsNullOrEmpty(customPath) ? null : customPath);
    }

    private void SaveGrabberSettings_Click(object sender, RoutedEventArgs e)
    {
        var owner = Window.GetWindow(this);
        var loginUrl = (GrabberLoginUrlBox.Text ?? string.Empty).Trim();
        var username = (GrabberUserBox.Text ?? string.Empty).Trim();
        var password = ReadPasswordField(GrabberPassBox, GrabberPassPlainBox, _grabberPassVisible);
        var reconUrl = (GrabberReconUrlBox.Text ?? string.Empty).Trim();
        var refreshSeconds = (GrabberRefreshSecBox.Text ?? string.Empty).Trim();
        if (string.IsNullOrEmpty(refreshSeconds))
            refreshSeconds = "5";
        bool soundEnabled = GrabberSoundEnabledCheck.IsChecked == true;
        var soundPath = (GrabberSoundPathBox.Text ?? string.Empty).Trim();

        if ((!loginUrl.StartsWith("https://", StringComparison.OrdinalIgnoreCase) && !loginUrl.StartsWith("http://", StringComparison.OrdinalIgnoreCase)) ||
            (!reconUrl.StartsWith("https://", StringComparison.OrdinalIgnoreCase) && !reconUrl.StartsWith("http://", StringComparison.OrdinalIgnoreCase)))
        {
            System.Windows.MessageBox.Show(owner, "Enter complete https:// login and reconciliation URLs for Tool 6.", "Invalid URL", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        if (string.IsNullOrEmpty(username) || string.IsNullOrEmpty(password))
        {
            System.Windows.MessageBox.Show(owner, "Enter the Tool 6 username/email and password.", "Incomplete credentials", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        try
        {
            GrabberSettingsAndPaths.SavePassword(password, username);
        }
        catch (Exception ex)
        {
            System.Windows.MessageBox.Show(owner, $"Tool 6 credentials could not be saved in Windows Credential Manager: {ex.Message}", "Save Failed", MessageBoxButton.OK, MessageBoxImage.Error);
            return;
        }

        _configStore.SaveKeyValues(
            ("data_grabber_login_url", loginUrl),
            ("data_grabber_user", username),
            ("data_grabber_reconciliation_url", reconUrl),
            ("data_grabber_refresh_seconds", refreshSeconds),
            ("data_grabber_sound_enabled", soundEnabled ? "True" : "False"),
            ("data_grabber_sound_path", soundPath));

        SetPill(GrabberStatusText, true);
        ShowTemporaryMessage(GrabberMsgText, "✓ Tool 6 settings saved securely!", MintBrush);
        OnTool6SettingsChanged?.Invoke(loginUrl, username, password, reconUrl, refreshSeconds, soundEnabled, soundPath);
    }

    private void ClearGrabberCredentials_Click(object sender, RoutedEventArgs e)
    {
        var owner = Window.GetWindow(this);
        var res = System.Windows.MessageBox.Show(
            owner,
            "Remove the saved Tool 6 username and password from this computer?",
            "Clear Tool 6 credentials",
            MessageBoxButton.YesNo,
            MessageBoxImage.Question);
        if (res != MessageBoxResult.Yes)
            return;

        try
        {
            GrabberSettingsAndPaths.ClearSavedPassword();
            _configStore.SaveKeyValues(("data_grabber_user", ""));
        }
        catch (Exception ex)
        {
            System.Windows.MessageBox.Show(owner, $"Tool 6 credentials could not be removed: {ex.Message}", "Clear Failed", MessageBoxButton.OK, MessageBoxImage.Error);
            return;
        }

        GrabberUserBox.Text = string.Empty;
        SetPasswordField(GrabberPassBox, GrabberPassPlainBox, _grabberPassVisible, string.Empty);
        SetPill(GrabberStatusText, false);
        GrabberMsgText.Text = "Saved Tool 6 credentials removed.";
        GrabberMsgText.Foreground = MutedBrush;

        OnTool6SettingsChanged?.Invoke(
            (GrabberLoginUrlBox.Text ?? string.Empty).Trim(),
            string.Empty,
            string.Empty,
            (GrabberReconUrlBox.Text ?? string.Empty).Trim(),
            (GrabberRefreshSecBox.Text ?? string.Empty).Trim(),
            GrabberSoundEnabledCheck.IsChecked == true,
            (GrabberSoundPathBox.Text ?? string.Empty).Trim());
    }

    private void SaveGsheetSettings_Click(object sender, RoutedEventArgs e)
    {
        var webappUrl = (WebappUrlBox.Text ?? string.Empty).Trim();
        var sheetUrl = (SheetUrlBox.Text ?? string.Empty).Trim();
        _configStore.Save(webappUrl: webappUrl, sheetUrl: sheetUrl);

        bool configured = !string.IsNullOrEmpty(webappUrl) && !string.IsNullOrEmpty(sheetUrl);
        SetPill(GsheetStatusText, configured);
        DiagSyncStatusText.Text = configured ? "Configured" : "Unconfigured";
        ShowTemporaryMessage(GsheetMsgText, "✓ Settings saved successfully!", MintBrush);
        OnGoogleSheetsSaved?.Invoke();
    }

    private void OpenGoogleSheet_Click(object sender, RoutedEventArgs e)
    {
        var owner = Window.GetWindow(this);
        var sheetUrl = (SheetUrlBox.Text ?? string.Empty).Trim();
        if (string.IsNullOrEmpty(sheetUrl))
            sheetUrl = _configStore.GetSheetUrl();

        if (string.IsNullOrEmpty(sheetUrl))
        {
            System.Windows.MessageBox.Show(owner, "Please enter and save your Google Sheet URL first.", "Missing URL", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        _ = Task.Run(async () =>
        {
            try
            {
                var store = new SentLogStore(_configStore);
                await store.GetCountsAsync();
            }
            catch { }
        });

        try
        {
            Process.Start(new ProcessStartInfo(sheetUrl) { UseShellExecute = true });
        }
        catch (Exception ex)
        {
            System.Windows.MessageBox.Show(owner, $"Could not open browser:\n\n{ex.Message}", "Browser Error", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private void OpenClearCache_Click(object sender, RoutedEventArgs e)
    {
        var dlg = new ClearCacheDialog(Window.GetWindow(this), AppPaths.AppDir, OnCacheCleared);
        dlg.ShowDialog();
    }
}
