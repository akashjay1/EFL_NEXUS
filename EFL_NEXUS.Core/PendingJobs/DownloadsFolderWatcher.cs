using System.IO;
using System.Text.Json;

namespace EflNexus.Core.PendingJobs;

/// <summary>
/// Watches the Windows Downloads folder while Loading History runs and organizes completed spreadsheets into
/// {Downloads}/{job_id}_{gatepass}_{client}/ (1:1 parity with watch_downloads in website_data_grabber.py).
/// </summary>
public sealed class DownloadsFolderWatcher : IDisposable
{
    private readonly LoadingHistoryBridge _bridge;
    private readonly string _defaultGatepass;
    private readonly string _defaultJobId;
    private readonly string _defaultClient;
    private readonly CancellationTokenSource _cts = new();
    private Thread? _thread;

    public DownloadsFolderWatcher(
        LoadingHistoryBridge bridge,
        string defaultGatepass = "",
        string defaultJobId = "",
        string defaultClient = "")
    {
        _bridge = bridge;
        _defaultGatepass = defaultGatepass;
        _defaultJobId = defaultJobId;
        _defaultClient = defaultClient;
    }

    public void Start()
    {
        if (_thread is not null)
            return;
        _thread = new Thread(WatchLoop)
        {
            Name = "Downloads Folder Watcher",
            IsBackground = true
        };
        _thread.Start();
    }

    private void WatchLoop()
    {
        var downloadsDir = Path.GetFullPath(GrabberSettingsAndPaths.GetDownloadsFolder());
        var initialFiles = new Dictionary<string, DateTime>(StringComparer.OrdinalIgnoreCase);
        try
        {
            foreach (var f in Directory.EnumerateFiles(downloadsDir))
                initialFiles[Path.GetFullPath(f)] = File.GetLastWriteTimeUtc(f);
        }
        catch { }

        var movedFiles = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        while (!_cts.IsCancellationRequested)
        {
            if (_cts.Token.WaitHandle.WaitOne(500))
                break;

            try
            {
                foreach (var filePath in Directory.EnumerateFiles(downloadsDir))
                {
                    if (_cts.IsCancellationRequested)
                        break;

                    var ext = Path.GetExtension(filePath).ToLowerInvariant();
                    if (ext is not (".xlsx" or ".xls" or ".csv"))
                        continue;

                    var resolvedFile = Path.GetFullPath(filePath);
                    if (movedFiles.Contains(resolvedFile))
                        continue;

                    if (initialFiles.TryGetValue(resolvedFile, out var initTime))
                    {
                        try
                        {
                            if (File.GetLastWriteTimeUtc(filePath) <= initTime)
                                continue;
                        }
                        catch { continue; }
                    }

                    if (File.Exists(filePath + ".crdownload"))
                        continue;

                    var stem = Path.GetFileNameWithoutExtension(filePath);
                    bool hasActiveCr = Directory.EnumerateFiles(downloadsDir, "*.crdownload")
                        .Any(cr => Path.GetFileName(cr).StartsWith(stem, StringComparison.OrdinalIgnoreCase));
                    if (hasActiveCr)
                        continue;

                    try
                    {
                        var info1 = new FileInfo(filePath);
                        if (info1.Length == 0)
                            continue;
                        Thread.Sleep(300);
                        var info2 = new FileInfo(filePath);
                        if (info1.Length != info2.Length)
                            continue;
                        using var stream = new FileStream(filePath, FileMode.Open, FileAccess.Read, FileShare.None);
                    }
                    catch { continue; }

                    var activeGp = _bridge.get_gatepass();
                    if (string.IsNullOrEmpty(activeGp)) activeGp = _defaultGatepass;
                    var activeJid = _bridge.get_job_id();
                    if (string.IsNullOrEmpty(activeJid)) activeJid = _defaultJobId;
                    var activeCli = _bridge.get_client();
                    if (string.IsNullOrEmpty(activeCli)) activeCli = _defaultClient;

                    if (string.IsNullOrEmpty(activeJid) || string.IsNullOrEmpty(activeCli))
                    {
                        var pMap = GrabberSettingsAndPaths.LoadPersistedJobMap();
                        if (!string.IsNullOrEmpty(activeGp))
                        {
                            foreach (var m in pMap.Values)
                            {
                                if (string.Equals(GrabberSettingsAndPaths.Clean(m.Gatepass), activeGp, StringComparison.Ordinal))
                                {
                                    if (string.IsNullOrEmpty(activeJid)) activeJid = GrabberSettingsAndPaths.Clean(m.JobId);
                                    if (string.IsNullOrEmpty(activeCli)) activeCli = GrabberSettingsAndPaths.Clean(m.Client);
                                    break;
                                }
                            }
                        }
                    }

                    var destFolder = Path.GetFullPath(GrabberSettingsAndPaths.GetJobDownloadFolder(activeJid, activeGp, activeCli));
                    if (string.Equals(destFolder.TrimEnd(Path.DirectorySeparatorChar), downloadsDir.TrimEnd(Path.DirectorySeparatorChar), StringComparison.OrdinalIgnoreCase))
                    {
                        movedFiles.Add(resolvedFile);
                        continue;
                    }

                    var destPath = Path.GetFullPath(GrabberSettingsAndPaths.GetUniqueDownloadPath(Path.GetFileName(filePath), destFolder));
                    try
                    {
                        File.Move(filePath, destPath);
                        movedFiles.Add(destPath);

                        try
                        {
                            var ev = new DownloadEventPayload
                            {
                                Action = "file_downloaded",
                                Filename = Path.GetFileName(destPath),
                                Path = destPath,
                                Folder = new DirectoryInfo(Path.GetDirectoryName(destPath)!).Name,
                                FolderPath = Path.GetDirectoryName(destPath)!,
                                Size = new FileInfo(destPath).Length,
                                Time = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0,
                                JobId = activeJid,
                                Gatepass = activeGp,
                                Client = activeCli
                            };
                            GrabberSettingsAndPaths.WriteJsonAtomic(GrabberSettingsAndPaths.DownloadEventFilePath, JsonSerializer.Serialize(ev));
                        }
                        catch { }
                    }
                    catch { }
                }
            }
            catch { }
        }
    }

    public void Dispose()
    {
        _cts.Cancel();
        try { _thread?.Join(1000); } catch { }
        _cts.Dispose();
    }
}
