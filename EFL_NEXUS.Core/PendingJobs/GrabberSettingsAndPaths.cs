using System.Globalization;
using System.IO;
using System.Media;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using EflNexus.Core.Infrastructure;
using Microsoft.Win32;

namespace EflNexus.Core.PendingJobs;

/// <summary>
/// Settings, Windows Credential Manager, IPC JSON paths, folder organization, and portal table extraction
/// (1:1 parity with website_data_grabber.py).
/// </summary>
public static partial class GrabberSettingsAndPaths
{
    public const string DefaultLoginUrl = "https://active.efl3plofc.com/login";
    public const string DefaultPortalUsername = "lka-3plcssops5@efl.global";
    public const string DefaultPortalPassword = "theekshana@efl";
    public const string DefaultReconciliationUrl = "https://active.efl3plofc.com/clerk-dashboard?job_type=OUTBOUND";
    public const int DefaultRefreshSeconds = 5;
    public const string WindowsCredentialTarget = "EFL_NEXUS:WebsiteDataGrabber";

    private static readonly JsonSerializerOptions IndentedJsonOptions = new() { WriteIndented = true };

    [DllImport("winmm.dll", EntryPoint = "mciSendStringW", CharSet = CharSet.Unicode)]
    private static extern int MciSendString(string command, StringBuilder? buffer, int bufferSize, IntPtr hwndCallback);

    [GeneratedRegex(@"[^\d]")]
    private static partial Regex NonDigitsRegex();

    [GeneratedRegex(@"[^a-z0-9]")]
    private static partial Regex NonAlphaNumLowerRegex();

    [GeneratedRegex(@"^\d+$")]
    private static partial Regex DigitsOnlyRegex();

    [GeneratedRegex(@"[<>:""/\\|?*\x00-\x1f]")]
    private static partial Regex InvalidDirCharsRegex();

    [GeneratedRegex(@"\s+")]
    private static partial Regex MultiSpaceRegex();

    [GeneratedRegex(@"_+")]
    private static partial Regex MultiUnderscoreRegex();

    [GeneratedRegex(@"[<>:""/\\|?*]")]
    private static partial Regex InvalidFilenameCharsRegex();

    public static string ResultFilePath => Path.Combine(AppPaths.LocalAppDataDir, "website_grabber_results.json");
    public static string BrowserLogFilePath => Path.Combine(AppPaths.LocalAppDataDir, "website_grabber_browser.log");
    public static string CommandFilePath => Path.Combine(AppPaths.LocalAppDataDir, "website_grabber_command.json");
    public static string DownloadEventFilePath => Path.Combine(AppPaths.LocalAppDataDir, "website_grabber_downloads.json");
    public static string LoadingHistoryEventFilePath => Path.Combine(AppPaths.LocalAppDataDir, "website_grabber_loading_history.json");
    public static string LoadingHistoryCommandFilePath => Path.Combine(AppPaths.LocalAppDataDir, "loading_history_command.json");
    public static string JobMapFilePath => JobMapStore.JobMapFilePath;

    public static bool PlayNotificationSound(string? soundPath = null)
    {
        if (!OperatingSystem.IsWindows())
            return false;

        ThreadPool.QueueUserWorkItem(_ =>
        {
            try
            {
                string? target = null;
                if (!string.IsNullOrWhiteSpace(soundPath) && File.Exists(soundPath))
                    target = soundPath;
                if (target is null)
                {
                    var bundled = AppPaths.ResolveResourcePath(Path.Combine("assets", "pending_alert.mp3"));
                    if (File.Exists(bundled))
                        target = bundled;
                }

                if (target is not null && File.Exists(target))
                {
                    var absStr = Path.GetFullPath(target);
                    MciSendString("stop nexus_pending_alert", null, 0, IntPtr.Zero);
                    MciSendString("close nexus_pending_alert", null, 0, IntPtr.Zero);

                    int ret = MciSendString($"open \"{absStr}\" type mpegvideo alias nexus_pending_alert", null, 0, IntPtr.Zero);
                    if (ret != 0)
                        ret = MciSendString($"open \"{absStr}\" alias nexus_pending_alert", null, 0, IntPtr.Zero);

                    if (ret == 0)
                    {
                        MciSendString("play nexus_pending_alert from 0", null, 0, IntPtr.Zero);
                        return;
                    }
                }

                try { SystemSounds.Asterisk.Play(); } catch { }
            }
            catch { }
        });
        return true;
    }

    public static int ParseRefreshSeconds(object? value, int defaultSeconds = DefaultRefreshSeconds)
    {
        if (value is null)
            return defaultSeconds;
        var cleaned = (value.ToString() ?? "").Trim().ToLowerInvariant();
        if (cleaned is "off" or "manual" or "none" or "disable" or "disabled" or "0")
            return 0;
        var digits = NonDigitsRegex().Replace(cleaned, "");
        if (string.IsNullOrEmpty(digits))
            return defaultSeconds;
        return int.TryParse(digits, NumberStyles.Integer, CultureInfo.InvariantCulture, out int parsed)
            ? Math.Max(0, parsed)
            : defaultSeconds;
    }

    public static string LoadSavedPassword()
    {
        try
        {
            var rec = CredentialManager.Read(WindowsCredentialTarget);
            return !string.IsNullOrEmpty(rec?.Secret) ? rec.Secret : DefaultPortalPassword;
        }
        catch
        {
            return DefaultPortalPassword;
        }
    }

    public static void SavePassword(string password, string username)
        => CredentialManager.Write(WindowsCredentialTarget, username, password, CredentialManager.CredPersistLocalMachine);

    public static void ClearSavedPassword()
    {
        try { CredentialManager.Delete(WindowsCredentialTarget); } catch { }
    }

    public static Dictionary<string, JobMapEntry> LoadPersistedJobMap(string? customPath = null)
        => JobMapStore.LoadPersistedJobMap(customPath);

    public static void UpdatePersistedJobMap(IEnumerable<PortalJobRecord> records, string? customPath = null)
    {
        var entries = records
            .Where(r => r is not null)
            .Select(r => new JobMapEntry
            {
                JobId = r.JobId ?? "",
                WarfId = r.WarfId ?? "",
                Gatepass = r.Gatepass ?? "",
                Client = r.Client ?? "",
                Status = r.Status ?? "",
                Warehouse = r.Warehouse ?? ""
            });
        JobMapStore.UpdatePersistedJobMap(entries, customPath);
    }

    public static string GetDownloadsFolder()
    {
        if (OperatingSystem.IsWindows())
        {
            try
            {
                using var key = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders");
                var val = key?.GetValue("{374DE290-123F-4565-9164-39C4925E467B}") as string;
                if (!string.IsNullOrWhiteSpace(val) && Directory.Exists(val))
                    return val;
            }
            catch { }
        }

        var fallback = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads");
        Directory.CreateDirectory(fallback);
        return fallback;
    }

    public static string GetJobDownloadFolder(
        string jobId = "",
        string gatepass = "",
        string client = "",
        string? baseFolder = null)
    {
        var baseDownloads = string.IsNullOrWhiteSpace(baseFolder) ? GetDownloadsFolder() : baseFolder;

        static string CleanComponent(string? val)
        {
            var s = (val ?? "").Trim();
            s = InvalidDirCharsRegex().Replace(s, "_");
            s = MultiSpaceRegex().Replace(s, "_");
            s = MultiUnderscoreRegex().Replace(s, "_");
            return s.Trim(' ', '.', '_');
        }

        static bool IsNa(string value)
            => value.ToUpperInvariant() is "NA" or "N_A" or "NONE" or "-" or "_";

        var cleanJob = CleanComponent(jobId);
        var cleanGp = CleanComponent(gatepass);
        var cleanClient = CleanComponent(client);

        if (!string.IsNullOrEmpty(cleanJob) && DigitsOnlyRegex().IsMatch(cleanJob))
        {
            var jobMap = LoadPersistedJobMap();
            if (jobMap.TryGetValue(cleanJob.ToLowerInvariant(), out var mapped))
            {
                var realJ = CleanComponent(mapped.JobId);
                if (!string.IsNullOrEmpty(realJ) && !DigitsOnlyRegex().IsMatch(realJ))
                    cleanJob = realJ;
                if (string.IsNullOrEmpty(cleanGp) || IsNa(cleanGp))
                    cleanGp = CleanComponent(mapped.Gatepass);
                if (string.IsNullOrEmpty(cleanClient) || IsNa(cleanClient))
                    cleanClient = CleanComponent(mapped.Client);
            }
        }

        var parts = new List<string>();
        if (!string.IsNullOrEmpty(cleanJob))
        {
            if (DigitsOnlyRegex().IsMatch(cleanJob) && string.IsNullOrEmpty(cleanGp) && string.IsNullOrEmpty(cleanClient))
                parts.Add($"JOB_{cleanJob}");
            else
                parts.Add(cleanJob);
        }

        if (!string.IsNullOrEmpty(cleanGp) && !IsNa(cleanGp))
            parts.Add(cleanGp);

        if (!string.IsNullOrEmpty(cleanClient) && !IsNa(cleanClient))
            parts.Add(cleanClient);

        var targetDir = parts.Count > 0
            ? Path.Combine(baseDownloads, string.Join("_", parts))
            : baseDownloads;

        Directory.CreateDirectory(targetDir);
        return targetDir;
    }

    public static string GetUniqueDownloadPath(string filename, string? folder = null)
    {
        var targetFolder = string.IsNullOrWhiteSpace(folder) ? GetDownloadsFolder() : folder;
        Directory.CreateDirectory(targetFolder);

        var cleanName = InvalidFilenameCharsRegex().Replace(filename ?? "", "_").Trim();
        if (string.IsNullOrEmpty(cleanName))
            cleanName = "downloaded_file";

        var baseName = Path.GetFileNameWithoutExtension(cleanName);
        var suffix = Path.GetExtension(cleanName);
        var candidate = Path.Combine(targetFolder, cleanName);
        int counter = 1;
        while (File.Exists(candidate))
        {
            candidate = Path.Combine(targetFolder, $"{baseName} ({counter}){suffix}");
            counter++;
        }
        return candidate;
    }

    public static void WriteResultsAtomic(string path, List<string> jobIds, List<PortalJobRecord>? records = null)
    {
        var dir = Path.GetDirectoryName(Path.GetFullPath(path));
        if (!string.IsNullOrEmpty(dir))
            Directory.CreateDirectory(dir);

        var payload = new PortalResultsPayload
        {
            JobIds = jobIds,
            Records = records is { Count: > 0 } ? records : null
        };

        var json = JsonSerializer.Serialize(payload);
        var tempPath = Path.Combine(dir ?? ".", $".tmp_{Guid.NewGuid():N}.json");
        File.WriteAllText(tempPath, json, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));

        for (int attempt = 0; attempt < 5; attempt++)
        {
            try
            {
                File.Move(tempPath, path, overwrite: true);
                break;
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                if (attempt == 4)
                {
                    try { if (File.Exists(tempPath)) File.Delete(tempPath); } catch { }
                    throw;
                }
                Thread.Sleep(50);
            }
        }
    }

    public static void WriteJsonAtomic(string path, string json)
    {
        var dir = Path.GetDirectoryName(Path.GetFullPath(path));
        if (!string.IsNullOrEmpty(dir))
            Directory.CreateDirectory(dir);

        var tempPath = Path.Combine(dir ?? ".", $".tmp_{Guid.NewGuid():N}.json");
        File.WriteAllText(tempPath, json, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
        for (int attempt = 0; attempt < 5; attempt++)
        {
            try
            {
                File.Move(tempPath, path, overwrite: true);
                break;
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                if (attempt == 4)
                {
                    try { if (File.Exists(tempPath)) File.Delete(tempPath); } catch { }
                    throw;
                }
                Thread.Sleep(30);
            }
        }
    }

    public static string Clean(string? value)
    {
        var replaced = (value ?? "").Replace('\u00A0', ' ');
        return string.Join(" ", replaced.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
    }

    public static string Normalise(string? value)
        => NonAlphaNumLowerRegex().Replace(Clean(value).ToLowerInvariant(), "");

    public static string NormalizeReconciliationStatus(string? raw)
    {
        var cleanVal = Clean(raw);
        var lowered = cleanVal.ToLowerInvariant();
        if (string.IsNullOrEmpty(lowered))
            return "Unknown";
        if (lowered.Contains("pending", StringComparison.Ordinal))
            return "Pending";
        if (lowered.Contains("progress", StringComparison.Ordinal))
            return "In Progress";
        if (lowered.Contains("complete", StringComparison.Ordinal) || lowered.Contains("done", StringComparison.Ordinal))
            return "Completed";
        return CultureInfo.InvariantCulture.TextInfo.ToTitleCase(cleanVal.ToLowerInvariant());
    }

    public static List<PortalJobRecord> ExtractJobsWithStatus(
        IReadOnlyList<string> headers,
        IReadOnlyList<IReadOnlyList<string>> rows,
        string requestedHeader = "",
        bool includeClient = false,
        bool includeDetails = false)
    {
        var wanted = Normalise(requestedHeader);
        var normalHeaders = headers.Select(Normalise).ToList();

        int column = -1;
        if (!string.IsNullOrEmpty(wanted))
            column = normalHeaders.FindIndex(h => h == wanted);

        if (column < 0)
        {
            column = normalHeaders.FindIndex(h =>
                h is "jobid" or "jobnumber" or "jobno" or "job" or "job#");
        }
        if (column < 0)
            return [];

        int clientCol = normalHeaders.FindIndex(h =>
            h is "client" or "customer" or "clientname" or "account" || h.Contains("client", StringComparison.Ordinal));
        int whCol = normalHeaders.FindIndex(h =>
            h is "wh" or "warehouse" or "warehouseid" or "whid" || h.StartsWith("wh", StringComparison.Ordinal));
        int gpCol = normalHeaders.FindIndex(h =>
            h is "gatepass" or "gatepassno" or "gatepassnumber" or "gatepassid" or "gp" or "gpno" || h.Contains("gatepass", StringComparison.Ordinal));
        int sealCol = normalHeaders.FindIndex(h =>
            h is "sealnumber" or "sealno" or "seal" or "seal#" || h.Contains("seal", StringComparison.Ordinal));
        int deliveryCol = normalHeaders.FindIndex(h =>
            h is "deliverylocation" or "delivery" or "destination" or "deliveryto" || h.Contains("delivery", StringComparison.Ordinal));
        int statusCol = normalHeaders.FindIndex(h =>
            h is "reconciliationstatus" or "status" or "reconstatus" or "jobstatus" or "state"
            || h.Contains("reconciliation", StringComparison.Ordinal)
            || h.Contains("status", StringComparison.Ordinal));

        var records = new List<PortalJobRecord>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (var row in rows)
        {
            if (column >= row.Count)
                continue;
            var value = Clean(row[column]);
            if (string.IsNullOrEmpty(value) || !seen.Add(value))
                continue;

            var clientVal = clientCol >= 0 && clientCol < row.Count ? Clean(row[clientCol]) : "";
            var whVal = whCol >= 0 && whCol < row.Count ? Clean(row[whCol]) : "";
            var gpVal = gpCol >= 0 && gpCol < row.Count ? Clean(row[gpCol]) : "";
            var sealVal = sealCol >= 0 && sealCol < row.Count ? Clean(row[sealCol]) : "";
            var delivVal = deliveryCol >= 0 && deliveryCol < row.Count ? Clean(row[deliveryCol]) : "";

            var rawStatus = statusCol >= 0 && statusCol < row.Count ? row[statusCol] : "";
            if (string.IsNullOrEmpty(Clean(rawStatus)))
            {
                rawStatus = row.FirstOrDefault(cell => NormalizeReconciliationStatus(cell) is "Pending" or "In Progress") ?? "";
            }

            var rec = new PortalJobRecord
            {
                JobId = value,
                Status = NormalizeReconciliationStatus(rawStatus)
            };
            if (includeClient || includeDetails)
                rec.Client = clientVal;
            if (includeDetails)
            {
                rec.Warehouse = whVal;
                rec.Gatepass = gpVal;
                rec.Seal = sealVal;
                rec.DeliveryLocation = delivVal;
            }
            records.Add(rec);
        }

        return records;
    }

    public static List<string> JobIdsFromRows(
        IReadOnlyList<string> headers,
        IReadOnlyList<IReadOnlyList<string>> rows,
        string requestedHeader = "",
        string? requiredStatus = null)
    {
        var wanted = Normalise(requestedHeader);
        var normalHeaders = headers.Select(Normalise).ToList();

        int column = !string.IsNullOrEmpty(wanted) ? normalHeaders.FindIndex(h => h == wanted) : -1;
        if (column < 0)
            column = normalHeaders.FindIndex(h => h is "jobid" or "jobnumber" or "jobno");
        if (column < 0)
            return [];

        int statusCol = -1;
        if (!string.IsNullOrEmpty(requiredStatus))
        {
            statusCol = normalHeaders.FindIndex(h => h == "reconciliationstatus");
            if (statusCol < 0)
                return [];
        }

        var found = new List<string>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (var row in rows)
        {
            if (column >= row.Count || (statusCol >= 0 && statusCol >= row.Count))
                continue;
            if (statusCol >= 0 && !string.Equals(Clean(row[statusCol]), requiredStatus, StringComparison.OrdinalIgnoreCase))
                continue;
            var value = Clean(row[column]);
            if (!string.IsNullOrEmpty(value) && seen.Add(value))
                found.Add(value);
        }

        return found;
    }

    public static string SerializeIndented<T>(T value) => JsonSerializer.Serialize(value, IndentedJsonOptions);
}
