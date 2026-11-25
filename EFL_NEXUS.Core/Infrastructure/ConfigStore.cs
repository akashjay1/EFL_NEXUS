using System.IO;
using System.Text.Json;

namespace EflNexus.Core.Infrastructure;

/// <summary>
/// Manages persistent JSON settings in config.json (1:1 parity with Python ConfigStore).
/// </summary>
public sealed class ConfigStore
{
    public static string DefaultConfigPath => Path.Combine(AppPaths.AppDir, "config.json");
    public static string FallbackConfigPath => Path.Combine(AppPaths.LocalAppDataDir, "config.json");

    public string FilePath { get; private set; }
    public Dictionary<string, string> Config { get; private set; }

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true
    };

    public ConfigStore(string? path = null)
    {
        FilePath = string.IsNullOrWhiteSpace(path) ? DefaultConfigPath : path;
        Config = Load();
    }

    public Dictionary<string, string> Load()
    {
        var loaded = TryReadDictionary(FilePath);
        if (loaded is not null)
            return loaded;

        if (string.Equals(Path.GetFullPath(FilePath), Path.GetFullPath(DefaultConfigPath), StringComparison.OrdinalIgnoreCase))
        {
            var fallback = TryReadDictionary(FallbackConfigPath);
            if (fallback is not null)
                return fallback;
        }

        return new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["webapp_url"] = "",
            ["sheet_url"] = "",
            ["korber_user"] = "",
            ["korber_pass"] = "",
            ["korber_url"] = "https://lopwaprodweb.koerbercloud.com/core/Default.html"
        };
    }

    private static Dictionary<string, string>? TryReadDictionary(string path)
    {
        if (!File.Exists(path))
            return null;
        try
        {
            var text = File.ReadAllText(path);
            using var doc = JsonDocument.Parse(text);
            if (doc.RootElement.ValueKind != JsonValueKind.Object)
                return null;
            var dict = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var prop in doc.RootElement.EnumerateObject())
            {
                dict[prop.Name] = prop.Value.ValueKind switch
                {
                    JsonValueKind.String => prop.Value.GetString() ?? "",
                    JsonValueKind.True => "True",
                    JsonValueKind.False => "False",
                    JsonValueKind.Number => prop.Value.GetRawText(),
                    JsonValueKind.Null => "",
                    _ => prop.Value.GetRawText()
                };
            }
            return dict;
        }
        catch
        {
            return null;
        }
    }

    public void Reload()
    {
        Config = Load();
    }

    public bool Save(
        string? webappUrl = null,
        string? sheetUrl = null,
        string? korberUser = null,
        string? korberPass = null,
        string? korberUrl = null,
        IReadOnlyDictionary<string, string?>? extra = null)
    {
        if (webappUrl is not null) Config["webapp_url"] = webappUrl.Trim();
        if (sheetUrl is not null) Config["sheet_url"] = sheetUrl.Trim();
        if (korberUser is not null) Config["korber_user"] = korberUser.Trim();
        if (korberPass is not null) Config["korber_pass"] = korberPass;
        if (korberUrl is not null) Config["korber_url"] = korberUrl.Trim();

        if (extra is not null)
        {
            foreach (var (k, v) in extra)
            {
                if (v is null)
                    Config[k] = "";
                else
                    Config[k] = k.EndsWith("_pass", StringComparison.Ordinal) ? v : v.Trim();
            }
        }

        if (TryWriteJson(FilePath, Config))
            return true;

        try
        {
            if (string.Equals(Path.GetFullPath(FilePath), Path.GetFullPath(DefaultConfigPath), StringComparison.OrdinalIgnoreCase))
            {
                if (!string.Equals(Path.GetFullPath(FallbackConfigPath), Path.GetFullPath(FilePath), StringComparison.OrdinalIgnoreCase))
                {
                    if (TryWriteJson(FallbackConfigPath, Config))
                    {
                        FilePath = FallbackConfigPath;
                        return true;
                    }
                }
            }
        }
        catch { }

        return false;
    }

    public bool SaveKeyValues(params (string Key, string? Value)[] pairs)
    {
        var dict = new Dictionary<string, string?>(StringComparer.Ordinal);
        foreach (var (k, v) in pairs)
            dict[k] = v;
        return Save(extra: dict);
    }

    private static bool TryWriteJson(string path, Dictionary<string, string> data)
    {
        try
        {
            var dir = Path.GetDirectoryName(Path.GetFullPath(path));
            if (!string.IsNullOrEmpty(dir))
                Directory.CreateDirectory(dir);
            var json = JsonSerializer.Serialize(data, JsonOptions);
            File.WriteAllText(path, json);
            return true;
        }
        catch
        {
            return false;
        }
    }

    public string Get(string key, string fallback = "")
        => Config.TryGetValue(key, out var val) && val is not null ? val : fallback;

    public bool GetBool(string key, bool fallback = false)
    {
        if (!Config.TryGetValue(key, out var val) || string.IsNullOrWhiteSpace(val))
            return fallback;
        var norm = val.Trim().ToLowerInvariant();
        return norm switch
        {
            "true" or "1" or "yes" => true,
            "false" or "0" or "no" => false,
            _ => fallback
        };
    }

    public string GetWebappUrl() => Get("webapp_url");
    public string GetSheetUrl() => Get("sheet_url");
    public string GetKorberUser() => NonEmptyOrEnv(Get("korber_user"), "KORBER_USER");
    public string GetKorberPass() => NonEmptyOrEnv(Get("korber_pass"), "KORBER_PASS", trim: false);
    public string GetKorberUrl() => NonEmptyOrEnv(Get("korber_url"), "KORBER_URL", "https://lopwaprodweb.koerbercloud.com/core/Default.html");
    public string GetAuditshipUser() => NonEmptyOrEnv(Get("auditship_user"), "AUDITSHIP_USER");
    public string GetAuditshipPass() => NonEmptyOrEnv(Get("auditship_pass"), "AUDITSHIP_PASS", trim: false);
    public string GetAuditshipForkId() => NonEmptyOrEnv(Get("auditship_fork_id"), "AUDITSHIP_FORK_ID");

    private static string NonEmptyOrEnv(string value, string envName, string fallback = "", bool trim = true)
    {
        var v = trim ? value.Trim() : value;
        if (!string.IsNullOrEmpty(v))
            return v;
        var env = Environment.GetEnvironmentVariable(envName) ?? "";
        env = trim ? env.Trim() : env;
        return !string.IsNullOrEmpty(env) ? env : fallback;
    }
}
