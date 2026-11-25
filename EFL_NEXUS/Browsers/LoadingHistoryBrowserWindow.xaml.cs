using System.IO;
using System.Windows;
using EflNexus.Core.Infrastructure;
using EflNexus.Core.PendingJobs;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.Wpf;

namespace EflNexus.App.Browsers;

public partial class LoadingHistoryBrowserWindow : Window
{
    private readonly string _startUrl;
    private readonly string _username;
    private readonly string _password;
    private readonly string _gatepass;
    private readonly string _jobId;
    private readonly string _client;
    private readonly bool _stopAtGatepass;
    private readonly string _pageCode;
    private readonly string _reportName;

    private LoadingHistoryBridge? _bridge;
    private DownloadsFolderWatcher? _watcher;
    private CoreWebView2Environment? _env;

    public LoadingHistoryBrowserWindow(
        string startUrl,
        string username,
        string password,
        string gatepass = "",
        string jobId = "",
        string client = "",
        bool stopAtGatepass = false,
        string pageCode = "1992",
        string reportName = "Loading History Report")
    {
        InitializeComponent();
        var (resolvedGp, resolvedJid, resolvedCli, resolvedPageCode, resolvedReportName) = LoadingHistoryBridge.ResolveInitialContext(
            gatepass, jobId, client, stopAtGatepass, pageCode, reportName);

        _startUrl = startUrl;
        _username = username;
        _password = password;
        _gatepass = resolvedGp;
        _jobId = resolvedJid;
        _client = resolvedCli;
        _stopAtGatepass = stopAtGatepass;
        _pageCode = resolvedPageCode;
        _reportName = resolvedReportName;

        if (_pageCode == "2598")
            Title = "EFL NEXUS — Inventory by Gatepass";
        else
            Title = "EFL NEXUS — Loading History";

        App.TrySetWindowIcon(this);
        Loaded += OnLoaded;
        Closing += (_, _) =>
        {
            try { _watcher?.Dispose(); } catch { }
            try { WebView.Dispose(); } catch { }
        };
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrWhiteSpace(_startUrl) ||
            string.IsNullOrWhiteSpace(_username) ||
            string.IsNullOrWhiteSpace(_password))
        {
            System.Windows.MessageBox.Show(
                this,
                "Körber URL, username, and password are required for Loading History.",
                "Missing Credentials",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
            Close();
            return;
        }

        try
        {
            _bridge = new LoadingHistoryBridge(_gatepass, _jobId, _client, _stopAtGatepass, _pageCode, _reportName);
            _watcher = new DownloadsFolderWatcher(_bridge, _gatepass, _jobId, _client);
            _watcher.Start();

            var profileDir = Path.Combine(AppPaths.LocalAppDataDir, "webview_loading_history_profile");
            Directory.CreateDirectory(profileDir);

            _env = await CoreWebView2Environment.CreateAsync(userDataFolder: profileDir);
            var opts = _env.CreateCoreWebView2ControllerOptions();
            opts.IsInPrivateModeEnabled = true;

            await WebView.EnsureCoreWebView2Async(_env, opts);

            WebView.CoreWebView2.AddHostObjectToScript("eflNexus", _bridge);
            await WebView.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(PendingJobsScripts.BuildPyWebViewShimJs());

            WebView.CoreWebView2.NewWindowRequested += OnNewWindowRequested;
            WebView.CoreWebView2.NavigationCompleted += async (_, _) =>
            {
                try
                {
                    if (WebView.CoreWebView2 is null)
                        return;
                    await WebView.CoreWebView2.ExecuteScriptAsync(PendingJobsScripts.BuildPyWebViewShimJs());
                    await WebView.CoreWebView2.ExecuteScriptAsync(
                        PendingJobsScripts.BuildLoadingHistoryAutomationScript(_username, _password, _gatepass, _stopAtGatepass, _pageCode, _reportName));
                }
                catch { }
            };

            WebView.CoreWebView2.Navigate(_startUrl);
        }
        catch (Exception ex)
        {
            System.Windows.MessageBox.Show(
                this,
                $"Could not initialize Loading History browser:\n{ex.Message}",
                "EFL NEXUS — Browser Error",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
            Close();
        }
    }

    private async void OnNewWindowRequested(object? sender, CoreWebView2NewWindowRequestedEventArgs e)
    {
        if (_env is null)
            return;

        // Keep report exports opened via target=_blank inside the same authenticated session profile.
        var deferral = e.GetDeferral();
        try
        {
            var popupWebView = new WebView2();
            var popup = new Window
            {
                Title = _pageCode == "2598" ? "EFL NEXUS — Inventory by Gatepass Export" : "EFL NEXUS — Loading History Export",
                Width = 980,
                Height = 700,
                WindowStartupLocation = WindowStartupLocation.CenterOwner,
                Owner = this,
                Content = popupWebView
            };
            App.TrySetWindowIcon(popup);
            popup.Closing += (_, _) =>
            {
                try { popupWebView.Dispose(); } catch { }
            };
            popup.Show();

            var opts = _env.CreateCoreWebView2ControllerOptions();
            opts.IsInPrivateModeEnabled = true;
            await popupWebView.EnsureCoreWebView2Async(_env, opts);

            e.NewWindow = popupWebView.CoreWebView2;
            e.Handled = true;
        }
        catch
        {
            e.Handled = true;
        }
        finally
        {
            deferral.Complete();
        }
    }
}
