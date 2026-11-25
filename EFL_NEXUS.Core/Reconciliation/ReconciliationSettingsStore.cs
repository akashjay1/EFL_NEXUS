using System.IO;
using System.Text.Json;

namespace EflNexus.Core.Reconciliation;

public static class ReconciliationSettingsStore
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };

    public static string SettingsFilePath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
        ".load_reconciliation_tool_settings.json");

    public static ReconciliationSettingsData Load(string? customPath = null)
    {
        var path = customPath ?? SettingsFilePath;
        try
        {
            if (File.Exists(path))
            {
                var json = File.ReadAllText(path);
                var data = JsonSerializer.Deserialize<ReconciliationSettingsData>(json);
                if (data is not null)
                    return data;
            }
        }
        catch { }
        return new ReconciliationSettingsData();
    }

    public static void Save(ReconciliationSettingsData data, string? customPath = null)
    {
        var path = customPath ?? SettingsFilePath;
        try
        {
            var json = JsonSerializer.Serialize(data, JsonOptions);
            File.WriteAllText(path, json);
        }
        catch { }
    }
}
