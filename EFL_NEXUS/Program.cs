using System.IO;
using System.Windows;
using EflNexus.App.Browsers;
using EflNexus.App.Windows;
using EflNexus.Core.Infrastructure;
using EflNexus.Core.Monitoring;
using EflNexus.Core.PendingJobs;

namespace EflNexus.App;

public static class Program
{
    [STAThread]
    public static int Main(string[] args)
    {
        EncodingInit.EnsureRegistered();

        if (args.Length >= 1 && args[0] == "--provision-monitoring")
        {
            try
            {
                DeviceIdentity.Provision(args.Length > 1 ? args[1] : null);
                return 0;
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"Provisioning failed: {ex.Message}");
                return 1;
            }
        }

        if (args.Length == 4 && args[0] == "--whatsapp-browser" && int.TryParse(args[3], out int parentPid))
        {
            var app = CreateApp();
            var win = new WhatsAppBrowserWindow(args[1], args[2], parentPid);
            app.MainWindow = win;
            app.ShutdownMode = ShutdownMode.OnMainWindowClose;
            win.Show();
            return app.Run();
        }

        if (args.Length >= 2 && args[0] == "--internal-browser")
        {
            var resultPath = args[1];
            var startUrl = args.Length > 2 ? args[2] : GrabberSettingsAndPaths.DefaultLoginUrl;
            var user = PopEnvVar("EFL_NEXUS_GRABBER_USER");
            var pass = PopEnvVar("EFL_NEXUS_GRABBER_PASS");
            var reconUrl = PopEnvVar("EFL_NEXUS_GRABBER_RECON_URL", GrabberSettingsAndPaths.DefaultReconciliationUrl);
            var refreshSec = GrabberSettingsAndPaths.ParseRefreshSeconds(
                PopEnvVar("EFL_NEXUS_GRABBER_REFRESH_SECONDS", GrabberSettingsAndPaths.DefaultRefreshSeconds.ToString()),
                GrabberSettingsAndPaths.DefaultRefreshSeconds);

            var app = CreateApp();
            var win = new InternalPortalBrowserWindow(resultPath, startUrl, user, pass, reconUrl, refreshSec);
            app.MainWindow = win;
            app.ShutdownMode = ShutdownMode.OnMainWindowClose;
            win.Show();
            return app.Run();
        }

        if (args.Length >= 2 && args[0] == "--loading-history-browser")
        {
            var startUrl = args[1];
            var user = PopEnvVar("EFL_NEXUS_KORBER_USER");
            var pass = PopEnvVar("EFL_NEXUS_KORBER_PASS");
            var stopAtGatepass = PopEnvVar("EFL_NEXUS_LOADING_HISTORY_STOP_AT_GATEPASS") == "1";
            var gatepass = args.Length > 2 && !string.IsNullOrWhiteSpace(args[2])
                ? args[2]
                : PopEnvVar("EFL_NEXUS_KORBER_GATEPASS");
            var jobId = args.Length > 3 && !string.IsNullOrWhiteSpace(args[3])
                ? args[3]
                : PopEnvVar("EFL_NEXUS_KORBER_JOB_ID");
            var client = args.Length > 4 && !string.IsNullOrWhiteSpace(args[4])
                ? args[4]
                : PopEnvVar("EFL_NEXUS_KORBER_CLIENT");
            var pageCode = args.Length > 5 && !string.IsNullOrWhiteSpace(args[5])
                ? args[5]
                : PopEnvVar("EFL_NEXUS_KORBER_PAGE_CODE", "1992");
            var reportName = args.Length > 6 && !string.IsNullOrWhiteSpace(args[6])
                ? args[6]
                : PopEnvVar("EFL_NEXUS_KORBER_REPORT_NAME", "Loading History Report");

            var app = CreateApp();
            var win = new LoadingHistoryBrowserWindow(startUrl, user, pass, gatepass, jobId, client, stopAtGatepass, pageCode, reportName);
            app.MainWindow = win;
            app.ShutdownMode = ShutdownMode.OnMainWindowClose;
            win.Show();
            return app.Run();
        }

        // Standard Desktop Launch
        Win32Interop.SetAppUserModelIdSafe("efl.nexus.app.unified");

        var desktopApp = CreateApp();
        SplashWindow? splash = null;
        try
        {
            splash = new SplashWindow();
            splash.Show();
            splash.SetStatus("Loading application modules...", 10);

            splash.SetStatus("Initializing application...", 30);
            var mainWindow = new MainWindow(splash);

            desktopApp.MainWindow = mainWindow;
            desktopApp.ShutdownMode = ShutdownMode.OnMainWindowClose;

            splash.SetStatus("Preparing dashboard...", 95);
            mainWindow.Show();
            mainWindow.WindowState = WindowState.Maximized;
            splash.Finish();
            splash = null;

            return desktopApp.Run();
        }
        catch (Exception ex)
        {
            try { splash?.Close(); } catch { }
            System.Windows.MessageBox.Show(
                $"Failed to start EFL NEXUS:\n{ex.Message}",
                "EFL NEXUS Startup Error",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
            return 1;
        }
    }

    private static App CreateApp()
    {
        var app = new App();
        app.InitializeComponent();
        return app;
    }

    private static string PopEnvVar(string name, string fallback = "")
    {
        var val = Environment.GetEnvironmentVariable(name);
        if (val is not null)
            Environment.SetEnvironmentVariable(name, null);
        return string.IsNullOrWhiteSpace(val) ? fallback : val;
    }
}
