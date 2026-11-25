using System.ComponentModel;
using System.IO;
using System.Windows;
using System.Windows.Media.Imaging;

namespace EflNexus.Updater;

public partial class MainWindow : Window
{
    private readonly string _url;
    private readonly string _newVersion;
    private readonly int? _pid;
    private readonly string _appDir;
    private readonly string _logPath;
    private string? _downloadPath;
    private string? _tempDir;
    private bool _closingAllowed;

    public MainWindow(string url, string newVersion, int? pid, string appDir)
    {
        InitializeComponent();
        _url = url;
        _newVersion = newVersion;
        _pid = pid;
        _appDir = appDir;
        _logPath = Path.Combine(appDir, "updater.log");

        HeaderText.Text = $"Update to version {_newVersion}";
        WriteLog($"INFO Updater started: url={_url} version={_newVersion} pid={_pid} appdir={_appDir}");

        var currentExe = Environment.ProcessPath is { Length: > 0 } p ? Path.GetFileName(p) : "updater.exe";
        UpdateRunner.CleanupStaleOldUpdater(_appDir, currentExe, WriteLog);

        TryLoadIcon();
        Closing += MainWindow_Closing;
        Loaded += MainWindow_Loaded;
    }

    private void TryLoadIcon()
    {
        foreach (var iconName in new[] { "icon_2.ico", "icon.ico", "favicon.ico" })
        {
            var candidate = Path.Combine(_appDir, iconName);
            if (!File.Exists(candidate))
                candidate = Path.Combine(AppContext.BaseDirectory, iconName);
            if (File.Exists(candidate))
            {
                try
                {
                    Icon = BitmapFrame.Create(new Uri(candidate, UriKind.Absolute));
                    break;
                }
                catch { }
            }
        }
    }

    private void WriteLog(string message)
    {
        try
        {
            var dir = Path.GetDirectoryName(_logPath);
            if (!string.IsNullOrEmpty(dir))
                Directory.CreateDirectory(dir);
            File.AppendAllText(_logPath, $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} {message}{Environment.NewLine}");
        }
        catch { }
    }

    private void UpdateStatus(string message, double? value = null)
    {
        WriteLog($"INFO STATUS: {message}" + (value.HasValue ? $" ({value.Value:0}%)" : ""));
        Dispatcher.Invoke(() =>
        {
            StatusText.Text = message;
            if (value.HasValue)
                UpdateProgress.Value = value.Value;
        });
    }

    private async void MainWindow_Loaded(object sender, RoutedEventArgs e)
    {
        await Task.Run(RunUpdateAsync);
    }

    private async Task RunUpdateAsync()
    {
        try
        {
            UpdateStatus("Downloading update...", 0);
            _downloadPath = await UpdateRunner.DownloadFileAsync(_url, (downloaded, total, speedMb, pct) =>
            {
                double dlMb = downloaded / (1024.0 * 1024.0);
                string text = total > 0
                    ? $"{dlMb:0.0}MB / {total / (1024.0 * 1024.0):0.0}MB   •   {speedMb:0.0} MB/s"
                    : $"{dlMb:0.0}MB downloaded   •   {speedMb:0.0} MB/s";
                Dispatcher.Invoke(() =>
                {
                    SizeText.Text = text;
                    if (total > 0)
                        UpdateProgress.Value = pct;
                });
            });

            Dispatcher.Invoke(() => SizeText.Text = "");
            UpdateStatus("Download complete.", 30);

            UpdateStatus("Extracting files...", 40);
            _tempDir = UpdateRunner.ExtractZip(_downloadPath);
            UpdateStatus("Extraction complete.", 60);

            UpdateStatus("Closing the main application...", 70);
            UpdateRunner.TerminateMainApp(_pid, WriteLog);

            UpdateStatus("Installing new files...", 80);
            var runningSelf = Environment.ProcessPath is { Length: > 0 } ep ? Path.GetFileName(ep) : "updater.exe";
            UpdateRunner.CopyNewFiles(_tempDir, _appDir, runningSelf, WriteLog);

            // Written LAST after copy succeeded
            UpdateStatus("Updating version file...", 90);
            var versionPath = Path.Combine(_appDir, "version.txt");
            File.WriteAllText(versionPath, _newVersion.Trim());
            WriteLog($"INFO Wrote version.txt -> {_newVersion.Trim()} at {versionPath}");

            UpdateStatus("Starting the updated application...", 100);
            UpdateRunner.RestartMainApp(_appDir);
            WriteLog("INFO Update completed successfully.");

            Dispatcher.Invoke(() =>
            {
                _closingAllowed = true;
                Close();
            });
        }
        catch (Exception ex)
        {
            WriteLog($"ERROR UPDATE FAILED: {ex}");
            Dispatcher.Invoke(() =>
            {
                MessageBox.Show(
                    this,
                    $"{ex.Message}\n\nDetails were written to updater.log next to the app.",
                    "Update failed",
                    MessageBoxButton.OK,
                    MessageBoxImage.Error);
                _closingAllowed = true;
                Close();
            });
        }
        finally
        {
            try { if (!string.IsNullOrEmpty(_downloadPath) && File.Exists(_downloadPath)) File.Delete(_downloadPath); } catch { }
            try { if (!string.IsNullOrEmpty(_tempDir) && Directory.Exists(_tempDir)) Directory.Delete(_tempDir, recursive: true); } catch { }
        }
    }

    private void MainWindow_Closing(object? sender, CancelEventArgs e)
    {
        if (!_closingAllowed && _downloadPath is not null)
        {
            e.Cancel = true;
            MessageBox.Show(
                this,
                "The update is already running and cannot be cancelled.",
                "Update in progress",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
        }
    }

    private void CancelBtn_Click(object sender, RoutedEventArgs e)
    {
        if (_downloadPath is null)
        {
            _closingAllowed = true;
            Close();
        }
        else
        {
            MessageBox.Show(
                this,
                "The update is already running and cannot be cancelled.",
                "Update in progress",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
        }
    }
}
