using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace EflNexus.Core.Infrastructure;

public sealed class ReconciliationQueueEntry
{
    [JsonPropertyName("job_id")]
    public string JobId { get; set; } = "";

    [JsonPropertyName("task_type")]
    public string TaskType { get; set; } = "";

    [JsonPropertyName("user_id")]
    public string UserId { get; set; } = "";

    [JsonPropertyName("submitted_at")]
    public string SubmittedAt { get; set; } = "";

    public ReconciliationQueueEntry Clone() => new()
    {
        JobId = JobId,
        TaskType = TaskType,
        UserId = UserId,
        SubmittedAt = SubmittedAt
    };
}

internal sealed class ReconciliationQueuePayload
{
    [JsonPropertyName("version")]
    public int Version { get; set; } = 1;

    [JsonPropertyName("pending")]
    public List<ReconciliationQueueEntry> Pending { get; set; } = [];
}

public static class ReconciliationQueue
{
    private static readonly object QueueLock = new();
    private static readonly Regex InvalidFolderChars = new(@"[<>:""/\\|?*\x00-\x1f]", RegexOptions.Compiled);
    private static readonly HashSet<string> WindowsReservedNames = new(StringComparer.OrdinalIgnoreCase)
    {
        "CON", "PRN", "AUX", "NUL",
        "COM1","COM2","COM3","COM4","COM5","COM6","COM7","COM8","COM9",
        "LPT1","LPT2","LPT3","LPT4","LPT5","LPT6","LPT7","LPT8","LPT9"
    };

    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };

    public static string GetQueueFile()
        => Path.Combine(AppPaths.LocalAppDataDir, "reconciliation_queue.json");

    private static List<ReconciliationQueueEntry> ReadQueueUnsafe(string queueFile)
    {
        if (!File.Exists(queueFile))
            return [];
        try
        {
            var json = File.ReadAllText(queueFile);
            var payload = JsonSerializer.Deserialize<ReconciliationQueuePayload>(json);
            if (payload?.Pending is null)
                return [];
            return payload.Pending
                .Where(e => e is not null && !string.IsNullOrWhiteSpace(e.JobId))
                .ToList();
        }
        catch
        {
            return [];
        }
    }

    private static void WriteQueueUnsafe(string queueFile, List<ReconciliationQueueEntry> entries)
    {
        var dir = Path.GetDirectoryName(Path.GetFullPath(queueFile))!;
        Directory.CreateDirectory(dir);
        var payload = new ReconciliationQueuePayload { Version = 1, Pending = entries };
        var json = JsonSerializer.Serialize(payload, JsonOptions);
        var tempFile = Path.Combine(dir, $"reconciliation_queue_{Guid.NewGuid():N}.tmp");
        try
        {
            File.WriteAllText(tempFile, json);
            File.Move(tempFile, queueFile, overwrite: true);
        }
        finally
        {
            if (File.Exists(tempFile))
            {
                try { File.Delete(tempFile); } catch { }
            }
        }
    }

    public static List<ReconciliationQueueEntry> ListPendingJobs(string? queueFile = null)
    {
        var path = queueFile ?? GetQueueFile();
        lock (QueueLock)
        {
            return ReadQueueUnsafe(path).Select(e => e.Clone()).ToList();
        }
    }

    public static ReconciliationQueueEntry EnqueueJob(
        string jobId,
        string taskType,
        string userId,
        string? submittedAt = null,
        string? queueFile = null)
    {
        var cleanJobId = (jobId ?? string.Empty).Trim();
        if (string.IsNullOrEmpty(cleanJobId))
            throw new ArgumentException("Job ID cannot be blank", nameof(jobId));

        var path = queueFile ?? GetQueueFile();
        lock (QueueLock)
        {
            var entries = ReadQueueUnsafe(path);
            foreach (var entry in entries)
            {
                if (string.Equals(entry.JobId.Trim(), cleanJobId, StringComparison.OrdinalIgnoreCase))
                    return entry.Clone();
            }

            var added = new ReconciliationQueueEntry
            {
                JobId = cleanJobId,
                TaskType = (taskType ?? string.Empty).Trim().TrimEnd(':'),
                UserId = (userId ?? string.Empty).Trim(),
                SubmittedAt = submittedAt ?? DateTime.Now.ToString("yyyy-MM-ddTHH:mm:ss")
            };
            entries.Add(added);
            WriteQueueUnsafe(path, entries);
            return added.Clone();
        }
    }

    public static bool CompleteJob(string jobId, string? queueFile = null)
    {
        var cleanJobId = (jobId ?? string.Empty).Trim();
        if (string.IsNullOrEmpty(cleanJobId))
            return false;

        var path = queueFile ?? GetQueueFile();
        lock (QueueLock)
        {
            var entries = ReadQueueUnsafe(path);
            var remaining = entries
                .Where(e => !string.Equals(e.JobId.Trim(), cleanJobId, StringComparison.OrdinalIgnoreCase))
                .ToList();
            if (remaining.Count == entries.Count)
                return false;
            WriteQueueUnsafe(path, remaining);
            return true;
        }
    }

    public static int ClearQueue(string? queueFile = null)
    {
        var path = queueFile ?? GetQueueFile();
        lock (QueueLock)
        {
            var entries = ReadQueueUnsafe(path);
            if (entries.Count > 0 || File.Exists(path))
                WriteQueueUnsafe(path, []);
            return entries.Count;
        }
    }

    public static string SafeJobFolderName(string jobId)
    {
        var folderName = InvalidFolderChars.Replace((jobId ?? string.Empty).Trim(), "_").TrimEnd(' ', '.');
        if (string.IsNullOrEmpty(folderName) || folderName is "." or "..")
            folderName = "job";
        var basePart = folderName.Split('.', 2)[0];
        if (WindowsReservedNames.Contains(basePart))
            folderName = "_" + folderName;
        return folderName;
    }

    public static bool IsReconciliationTask(string? taskType)
    {
        var normalized = (taskType ?? string.Empty).Trim().TrimEnd(':').ToLowerInvariant();
        return normalized is "gdn reconciliation" or "grn reconciliation";
    }

    public static string GetReconciliationOutputFolder(string baseFolder, string jobId)
        => Path.Combine(baseFolder, SafeJobFolderName(jobId));

    public static string ChoosePendingJob(IEnumerable<ReconciliationQueueEntry> entries, string currentJobId = "")
    {
        var jobIds = entries
            .Select(e => e.JobId.Trim())
            .Where(id => !string.IsNullOrEmpty(id))
            .ToList();
        var currentLookup = (currentJobId ?? string.Empty).Trim();
        foreach (var id in jobIds)
        {
            if (string.Equals(id, currentLookup, StringComparison.OrdinalIgnoreCase))
                return id;
        }
        return jobIds.Count > 0 ? jobIds[0] : string.Empty;
    }
}
