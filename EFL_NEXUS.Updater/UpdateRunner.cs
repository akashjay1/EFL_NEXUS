using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Net.Http;

namespace EflNexus.Updater;

public static class UpdateRunner
{
    public static readonly HashSet<string> UserPreserveFiles = new(StringComparer.OrdinalIgnoreCase)
    {
        "templates.xlsx",
        "variance_templates.xlsx",
        "efl_users.json",
        "sent_log.xlsx",
        "reconciliation_queue.json",
        ".load_reconciliation_tool_settings.json",
        ".efl_records_cache.json",
        "packing_list_config.json",
        "app_config.json",
        "release_notes_state.json"
    };

    public static readonly HashSet<string> SkippedConfigFiles = new(StringComparer.OrdinalIgnoreCase)
    {
        "config.json",
        ".env",
        "credential.enc",
        "machine_credential.enc",
        "provisioning.json"
    };

    public static Dictionary<string, string> ParseArgs(IReadOnlyList<string> args)
    {
        var dict = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        for (int i = 0; i < args.Count; i++)
        {
            var arg = args[i];
            if (arg.StartsWith("--", StringComparison.Ordinal))
            {
                var key = arg[2..];
                if (i + 1 < args.Count && !args[i + 1].StartsWith("--", StringComparison.Ordinal))
                {
                    dict[key] = args[i + 1];
                }
            }
        }
        return dict;
    }

    public static void CleanupStaleOldUpdater(string appDir, string? currentExeName, Action<string>? log = null)
    {
        if (string.IsNullOrWhiteSpace(appDir) || string.IsNullOrWhiteSpace(currentExeName))
            return;
        var stale = Path.Combine(appDir, currentExeName + ".old");
        try
        {
            if (File.Exists(stale))
            {
                File.Delete(stale);
                log?.Invoke($"Cleaned up stale {stale} from a previous update.");
            }
        }
        catch (Exception ex)
        {
            log?.Invoke($"WARNING Could not clean up stale {stale}: {ex.Message}");
        }
    }

    public static async Task<string> DownloadFileAsync(
        string url,
        Action<long, long, double, double>? onProgress = null,
        CancellationToken cancellationToken = default)
    {
        using var http = new HttpClient();
        using var response = await http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        response.EnsureSuccessStatusCode();

        long totalSize = response.Content.Headers.ContentLength ?? 0;
        var tempZip = Path.Combine(Path.GetTempPath(), $"efl_nexus_update_{Guid.NewGuid():N}.zip");
        var sw = Stopwatch.StartNew();
        long lastReportMs = -1000;
        long downloaded = 0;

        await using var sourceStream = await response.Content.ReadAsStreamAsync(cancellationToken);
        await using (var destStream = new FileStream(tempZip, FileMode.Create, FileAccess.Write, FileShare.None, 8192, useAsync: true))
        {
            var buffer = new byte[8192];
            int read;
            while ((read = await sourceStream.ReadAsync(buffer, cancellationToken)) > 0)
            {
                await destStream.WriteAsync(buffer.AsMemory(0, read), cancellationToken);
                downloaded += read;

                long nowMs = sw.ElapsedMilliseconds;
                if (nowMs - lastReportMs >= 200 || (totalSize > 0 && downloaded == totalSize))
                {
                    lastReportMs = nowMs;
                    double elapsed = Math.Max(0.001, sw.Elapsed.TotalSeconds);
                    double speedMb = (downloaded / (1024.0 * 1024.0)) / elapsed;
                    double pct = totalSize > 0 ? 30.0 * ((double)downloaded / totalSize) : 0.0;
                    onProgress?.Invoke(downloaded, totalSize, speedMb, pct);
                }
            }
        }

        return tempZip;
    }

    public static string ExtractZip(string zipPath)
    {
        var tempDir = Path.Combine(Path.GetTempPath(), $"efl_nexus_extract_{Guid.NewGuid():N}");
        Directory.CreateDirectory(tempDir);
        ZipFile.ExtractToDirectory(zipPath, tempDir, overwriteFiles: true);
        return tempDir;
    }

    public static void TerminateMainApp(int? pid, Action<string>? log = null)
    {
        if (pid.HasValue && pid.Value > 0)
        {
            try
            {
                using var proc = Process.GetProcessById(pid.Value);
                try
                {
                    using var killer = Process.Start(new ProcessStartInfo
                    {
                        FileName = "taskkill",
                        Arguments = $"/F /PID {pid.Value}",
                        CreateNoWindow = true,
                        UseShellExecute = false
                    });
                    killer?.WaitForExit(3000);
                }
                catch
                {
                    try { proc.Kill(entireProcessTree: true); } catch { }
                }

                if (proc.WaitForExit(10_000))
                {
                    log?.Invoke("Confirmed main app process exited.");
                    return;
                }
            }
            catch
            {
                log?.Invoke("Main app process already exited or inaccessible.");
            }
        }
        else
        {
            try
            {
                using var killer = Process.Start(new ProcessStartInfo
                {
                    FileName = "taskkill",
                    Arguments = "/F /IM EFL_NEXUS.exe",
                    CreateNoWindow = true,
                    UseShellExecute = false
                });
                killer?.WaitForExit(3000);
            }
            catch { }
        }

        log?.Invoke("Waiting briefly for file handles to release.");
        Thread.Sleep(2000);
    }

    public static void CopyNewFiles(
        string extractedRoot,
        string appDir,
        string? runningSelfExeName = null,
        Action<string>? log = null)
    {
        if (!Directory.Exists(appDir))
            Directory.CreateDirectory(appDir);

        var topEntries = Directory.GetFileSystemEntries(extractedRoot);
        log?.Invoke($"Top-level entries in extracted zip: [{string.Join(", ", topEntries.Select(Path.GetFileName))}]");

        var sourceDir = extractedRoot;
        if (topEntries.Length == 1 && Directory.Exists(topEntries[0]))
        {
            var singleName = Path.GetFileName(topEntries[0]);
            log?.Invoke($"Zip has a single top-level folder '{singleName}' -- flattening.");
            sourceDir = topEntries[0];
        }

        var entries = Directory.GetFileSystemEntries(sourceDir);
        if (!entries.Any(e => string.Equals(Path.GetFileName(e), "version.txt", StringComparison.OrdinalIgnoreCase)))
        {
            log?.Invoke("WARNING Expected version.txt not found at copy source.");
        }

        foreach (var src in entries)
        {
            var itemName = Path.GetFileName(src);
            if (SkippedConfigFiles.Contains(itemName))
            {
                log?.Invoke($"Skipping user config file '{itemName}' during update to preserve user settings.");
                continue;
            }

            var dst = Path.Combine(appDir, itemName);
            if (UserPreserveFiles.Contains(itemName) && File.Exists(dst))
            {
                log?.Invoke($"Keeping existing user file '{dst}'.");
                continue;
            }

            if (!string.IsNullOrEmpty(runningSelfExeName)
                && string.Equals(itemName, runningSelfExeName, StringComparison.OrdinalIgnoreCase)
                && File.Exists(src))
            {
                ReplaceSelf(src, dst, log);
            }
            else
            {
                CopyWithRetry(src, dst, attempts: 5, delayMs: 1000, log: log);
            }
            log?.Invoke($"Copied {src} -> {dst}");
        }
    }

    private static void ReplaceSelf(string src, string dst, Action<string>? log)
    {
        var oldPath = dst + ".old";
        try
        {
            if (File.Exists(oldPath))
                File.Delete(oldPath);
        }
        catch (Exception ex)
        {
            log?.Invoke($"WARNING Could not remove stale {oldPath}: {ex.Message}");
        }

        try
        {
            if (File.Exists(dst))
            {
                File.Move(dst, oldPath, overwrite: true);
                log?.Invoke($"Renamed running updater {dst} -> {oldPath} to free up the path");
            }
        }
        catch (Exception ex)
        {
            log?.Invoke($"WARNING Could not rename current updater exe out of the way: {ex.Message}");
        }

        CopyWithRetry(src, dst, attempts: 5, delayMs: 1000, log: log);
    }

    private static void CopyWithRetry(string src, string dst, int attempts, int delayMs, Action<string>? log)
    {
        for (int i = 0; i < attempts; i++)
        {
            try
            {
                if (Directory.Exists(src))
                    CopyDirectoryRecursive(src, dst);
                else
                {
                    var dstDir = Path.GetDirectoryName(dst);
                    if (!string.IsNullOrEmpty(dstDir))
                        Directory.CreateDirectory(dstDir);
                    File.Copy(src, dst, overwrite: true);
                }
                return;
            }
            catch (Exception ex) when (ex is UnauthorizedAccessException or IOException)
            {
                log?.Invoke($"WARNING Locked on attempt {i + 1}/{attempts} copying {dst}: {ex.Message}");
                if (i == attempts - 1)
                    throw;
                Thread.Sleep(delayMs);
            }
        }
    }

    private static void CopyDirectoryRecursive(string sourceDir, string targetDir)
    {
        Directory.CreateDirectory(targetDir);
        foreach (var file in Directory.GetFiles(sourceDir))
        {
            var destFile = Path.Combine(targetDir, Path.GetFileName(file));
            File.Copy(file, destFile, overwrite: true);
        }
        foreach (var dir in Directory.GetDirectories(sourceDir))
        {
            var destSub = Path.Combine(targetDir, Path.GetFileName(dir));
            CopyDirectoryRecursive(dir, destSub);
        }
    }

    public static void RestartMainApp(string appDir)
    {
        var mainExe = Path.Combine(appDir, "EFL_NEXUS.exe");
        if (!File.Exists(mainExe))
            mainExe = Path.Combine(appDir, "EFL_Nexus.exe");
        if (!File.Exists(mainExe))
            throw new FileNotFoundException("EFL_NEXUS.exe not found after update.");

        var psi = new ProcessStartInfo
        {
            FileName = mainExe,
            WorkingDirectory = appDir,
            UseShellExecute = true
        };
        psi.ArgumentList.Add("--just-updated");

        Process.Start(psi);
    }
}
