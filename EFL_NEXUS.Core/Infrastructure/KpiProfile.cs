using System.IO;
using System.Text.Json;

namespace EflNexus.Core.Infrastructure;

public sealed record KpiUserProfile(string UserId, string UserCode);

public static class KpiProfile
{
    public static Dictionary<string, JsonElement> LoadRegisteredUsers(string? usersPath = null)
    {
        var path = usersPath ?? AppPaths.ResolveResourcePath("efl_users.json");
        try
        {
            var text = File.ReadAllText(path);
            using var doc = JsonDocument.Parse(text);
            if (!doc.RootElement.TryGetProperty("users", out var usersEl) || usersEl.ValueKind != JsonValueKind.Object)
                throw new InvalidDataException("Invalid user list");
            var map = new Dictionary<string, JsonElement>(StringComparer.Ordinal);
            foreach (var p in usersEl.EnumerateObject())
                map[p.Name] = p.Value.Clone();
            return map;
        }
        catch (Exception ex)
        {
            throw new InvalidOperationException("The registered KPI user list could not be loaded.", ex);
        }
    }

    public static KpiUserProfile ValidateProfile(string? userId, string? userCode, string? usersPath = null)
    {
        var uid = (userId ?? string.Empty).Trim();
        var code = (userCode ?? string.Empty).Trim();
        if (string.IsNullOrEmpty(uid) || string.IsNullOrEmpty(code))
            throw new ArgumentException("Enter both KPI User ID and User Code.");

        var users = LoadRegisteredUsers(usersPath);
        foreach (var registeredId in users.Keys)
        {
            if (string.Equals(registeredId, uid, StringComparison.OrdinalIgnoreCase))
                return new KpiUserProfile(registeredId, code);
        }

        throw new ArgumentException("KPI User ID was not found in the registered user list.");
    }

    public static KpiUserProfile? LoadSavedProfile(string? configPath = null, string? usersPath = null)
    {
        var store = new ConfigStore(configPath);
        try
        {
            var uid = store.Get("kpi_user_id");
            var code = store.Get("kpi_user_code");
            return ValidateProfile(uid, code, usersPath);
        }
        catch
        {
            return null;
        }
    }

    public static string ExportFilename(string userId, DateTime startDate, DateTime endDate)
    {
        var chars = userId.Select(c => char.IsLetterOrDigit(c) || c == '-' || c == '_' ? c : '_').ToArray();
        var safeId = new string(chars).Trim('_', '-');
        if (string.IsNullOrEmpty(safeId))
            safeId = "User";
        return $"KPI_{safeId}_{startDate:yyyy-MM-dd}_to_{endDate:yyyy-MM-dd}.xlsx";
    }
}
