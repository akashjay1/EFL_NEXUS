using System.IO;
using System.Windows;
using EflNexus.Core.Infrastructure;
using EflNexus.Core.PendingJobs;
using Microsoft.Web.WebView2.Core;

namespace EflNexus.App.Browsers;

public partial class InternalPortalBrowserWindow : Window
{
    private readonly string _resultPath;
    private readonly string _startUrl;
    private readonly string _username;
    private readonly string _password;
    private readonly string _reconciliationUrl;
    private readonly int _refreshSeconds;
    private PortalResultsBridge? _bridge;

    public InternalPortalBrowserWindow(
        string resultPath,
        string startUrl,
        string username,
        string password,
        string reconciliationUrl,
        int refreshSeconds)
    {
        InitializeComponent();
        _resultPath = string.IsNullOrWhiteSpace(resultPath) ? GrabberSettingsAndPaths.ResultFilePath : resultPath;
        _startUrl = string.IsNullOrWhiteSpace(startUrl) ? GrabberSettingsAndPaths.DefaultLoginUrl : startUrl;
        _username = username ?? "";
        _password = password ?? "";
        _reconciliationUrl = string.IsNullOrWhiteSpace(reconciliationUrl)
            ? GrabberSettingsAndPaths.DefaultReconciliationUrl
            : reconciliationUrl;
        _refreshSeconds = Math.Max(0, refreshSeconds);

        App.TrySetWindowIcon(this);
        Loaded += OnLoaded;
        Closing += (_, _) =>
        {
            try { WebView.Dispose(); } catch { }
        };
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        try
        {
            _bridge = new PortalResultsBridge(GrabberSettingsAndPaths.CommandFilePath, _resultPath);

            var profileDir = Path.Combine(AppPaths.LocalAppDataDir, "webview_internal_profile");
            Directory.CreateDirectory(profileDir);

            var env = await CoreWebView2Environment.CreateAsync(userDataFolder: profileDir);
            var opts = env.CreateCoreWebView2ControllerOptions();
            opts.IsInPrivateModeEnabled = true;

            await WebView.EnsureCoreWebView2Async(env, opts);

            WebView.CoreWebView2.AddHostObjectToScript("eflNexus", _bridge);
            await WebView.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(PendingJobsScripts.BuildPyWebViewShimJs());
            await WebView.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(
                PendingJobsScripts.BuildInternalBrowserOverlayScript(_reconciliationUrl, _refreshSeconds));
            var autoLoginScript = PendingJobsScripts.BuildPortalAutoLoginScript(_username, _password, _reconciliationUrl);
            if (!string.IsNullOrWhiteSpace(autoLoginScript))
            {
                await WebView.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(autoLoginScript);
            }

            WebView.CoreWebView2.NavigationCompleted += async (_, _) =>
            {
                try
                {
                    if (WebView.CoreWebView2 is null)
                        return;
                    await WebView.CoreWebView2.ExecuteScriptAsync(PendingJobsScripts.BuildPyWebViewShimJs());
                    await WebView.CoreWebView2.ExecuteScriptAsync(
                        PendingJobsScripts.BuildInternalBrowserOverlayScript(_reconciliationUrl, _refreshSeconds));
                    if (!string.IsNullOrWhiteSpace(autoLoginScript))
                    {
                        await WebView.CoreWebView2.ExecuteScriptAsync(autoLoginScript);
                    }
                }
                catch { }
            };

            WebView.CoreWebView2.Navigate(_startUrl);
        }
        catch (Exception ex)
        {
            System.Windows.MessageBox.Show(
                this,
                $"Could not initialize Reconciliation Browser:\n{ex.Message}",
                "EFL NEXUS — Browser Error",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
            Close();
        }
    }
}
