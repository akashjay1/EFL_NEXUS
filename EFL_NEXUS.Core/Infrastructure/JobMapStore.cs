using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace EflNexus.Core.Infrastructure;

public sealed class JobMapEntry
{
    [JsonPropertyName("job_id")]
    public string JobId { get; set; } = "";

    [JsonPropertyName("warf_id")]
    public string WarfId { get; set; } = "";

    [JsonPropertyName("gatepass")]
    public string Gatepass { get; set; } = "";

    [JsonPropertyName("client")]
    public string Client { get; set; } = "";

    [JsonPropertyName("status")]
    public string Status { get; set; } = "";

    [JsonPropertyName("warehouse")]
    public string Warehouse { get; set; } = "";
}

public static class JobMapStore
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };

    public static string JobMapFilePath => Path.Combine(AppPaths.LocalAppDataDir, "website_grabber_job_map.json");

    public static Dictionary<string, JobMapEntry> LoadPersistedJobMap(string? customPath = null)
    {
        var path = customPath ?? JobMapFilePath;
        if (!File.Exists(path))
            return new Dictionary<string, JobMapEntry>(StringComparer.Ordinal);
        try
        {
            var json = File.ReadAllText(path);
            var parsed = JsonSerializer.Deserialize<Dictionary<string, JobMapEntry>>(json);
            return parsed ?? new Dictionary<string, JobMapEntry>(StringComparer.Ordinal);
        }
        catch
        {
            return new Dictionary<string, JobMapEntry>(StringComparer.Ordinal);
        }
    }

    public static void UpdatePersistedJobMap(IEnumerable<JobMapEntry> records, string? customPath = null)
    {
        var list = records?.ToList();
        if (list is null || list.Count == 0)
            return;

        var path = customPath ?? JobMapFilePath;
        var existing = LoadPersistedJobMap(path);
        var changed = false;

        foreach (var r in list)
        {
            var jid = (r.JobId ?? "").Trim();
            var wid = (r.WarfId ?? "").Trim();
            var item = new JobMapEntry
            {
                JobId = jid,
                WarfId = wid,
                Gatepass = (r.Gatepass ?? "").Trim(),
                Client = (r.Client ?? "").Trim(),
                Status = (r.Status ?? "").Trim(),
                Warehouse = (r.Warehouse ?? "").Trim()
            };
            if (!string.IsNullOrEmpty(jid))
            {
                existing[jid.ToLowerInvariant()] = item;
                changed = true;
            }
            if (!string.IsNullOrEmpty(wid))
            {
                existing[wid.ToLowerInvariant()] = item;
                changed = true;
            }
        }

        if (changed)
        {
            try
            {
                var dir = Path.GetDirectoryName(Path.GetFullPath(path));
                if (!string.IsNullOrEmpty(dir))
                    Directory.CreateDirectory(dir);
                File.WriteAllText(path, JsonSerializer.Serialize(existing, JsonOptions));
            }
            catch { }
        }
    }
}
