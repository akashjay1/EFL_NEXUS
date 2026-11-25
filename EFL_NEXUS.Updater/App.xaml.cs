using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows;

namespace EflNexus.Updater;

public partial class App : Application
{
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    private static extern int SetCurrentProcessExplicitAppUserModelID(string appId);

    private static readonly string CrashLogPath = Path.Combine(Path.GetTempPath(), "efl_nexus_updater_crash.log");

    private static void LogCrash(string msg)
    {
        try
        {
            File.AppendAllText(CrashLogPath, $"{DateTime.Now:ddd MMM dd HH:mm:ss yyyy} {msg}{Environment.NewLine}");
        }
        catch { }
    }

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        AppDomain.CurrentDomain.UnhandledException += (_, ex) =>
            LogCrash("UNHANDLED EXCEPTION:\n" + ex.ExceptionObject);

        try
        {
            var args = UpdateRunner.ParseArgs(e.Args);
            LogCrash($"Parsed args: {string.Join(", ", args.Select(kv => $"{kv.Key}={kv.Value}"))}");

            args.TryGetValue("url", out var url);
            args.TryGetValue("version", out var newVersion);
            args.TryGetValue("pid", out var pidStr);
            args.TryGetValue("appdir", out var appDir);

            if (string.IsNullOrWhiteSpace(url) || string.IsNullOrWhiteSpace(newVersion) || string.IsNullOrWhiteSpace(appDir))
            {
                LogCrash($"Missing required args. url='{url}' version='{newVersion}' appdir='{appDir}'");
                Shutdown(1);
                return;
            }

            int? pid = int.TryParse(pidStr, NumberStyles.Integer, CultureInfo.InvariantCulture, out int p) ? p : null;

            try { SetCurrentProcessExplicitAppUserModelID("efl.nexus.updater"); } catch { }

            var window = new MainWindow(url, newVersion, pid, appDir);
            MainWindow = window;
            window.Show();
        }
        catch (Exception ex)
        {
            LogCrash($"UNHANDLED EXCEPTION:\n{ex}");
            MessageBox.Show($"Updater crashed. Details written to:\n{CrashLogPath}", "Update Error", MessageBoxButton.OK, MessageBoxImage.Error);
            Shutdown(1);
        }
    }
}
