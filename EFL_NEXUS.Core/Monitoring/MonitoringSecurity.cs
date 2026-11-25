using System.IO;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using EflNexus.Core.Infrastructure;

namespace EflNexus.Core.Monitoring;

public static class MonitoringSecurity
{
    public static readonly HashSet<string> DummyIds = new(StringComparer.OrdinalIgnoreCase)
    {
        "a0000000-0000-4000-8000-000000000011",
        "c0000000-0000-4000-8000-000000000021",
        "275f7586-a64c-4b95-aed2-0ec853ba724c"
    };

    private const string HardenedSddl = "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;GRGX;;;BU)";

    public static string ProgramDataRoot =>
        Environment.GetEnvironmentVariable("PROGRAMDATA") is { Length: > 0 } pd ? pd : @"C:\ProgramData";

    public static string MachineCredentialPath()
        => Path.Combine(ProgramDataRoot, "EFL_NEXUS_Monitoring", "credential.enc");

    public static string UserMonitoringDir()
    {
        var ov = Environment.GetEnvironmentVariable("EFL_USER_MONITORING_DIR");
        if (!string.IsNullOrWhiteSpace(ov))
            return ov;
        var lad = Environment.GetEnvironmentVariable("LOCALAPPDATA") ?? "";
        return Path.Combine(lad, "EFL_NEXUS", "Monitoring");
    }

    public static string UserCredentialPath()
        => Path.Combine(UserMonitoringDir(), "credential.enc");

    public static string ActivationTokenPath()
        => Path.Combine(ProgramDataRoot, "EFL_NEXUS_Monitoring", "monitoring_active.token");

    public static string UserActivationTokenPath()
        => Path.Combine(UserMonitoringDir(), "monitoring_active.token");

    public static void SetMachineActive(bool active = true, string? path = null)
    {
        var targets = path is not null
            ? new[] { path }
            : [ActivationTokenPath(), UserActivationTokenPath()];

        foreach (var target in targets)
        {
            if (active)
            {
                try
                {
                    Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                    File.WriteAllText(target, "ACTIVE", Encoding.UTF8);
                }
                catch { }
            }
            else
            {
                try
                {
                    if (File.Exists(target))
                        File.Delete(target);
                }
                catch { }
            }
        }
    }

    public static bool IsMachineActive(string? path = null)
    {
        if (path is not null)
            return File.Exists(path);
        return File.Exists(ActivationTokenPath()) || File.Exists(UserActivationTokenPath());
    }

    internal static void ApplyProgramDataAcl(string path, bool isDirectory)
    {
        try
        {
            var resolved = Path.GetFullPath(path);
            var rootResolved = Path.GetFullPath(ProgramDataRoot);
            if (!resolved.StartsWith(rootResolved, StringComparison.OrdinalIgnoreCase))
                return;

            var admins = new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null);
            if (isDirectory)
            {
                var ds = new DirectorySecurity();
                ds.SetSecurityDescriptorSddlForm(HardenedSddl);
                ds.SetOwner(admins);
                new DirectoryInfo(resolved).SetAccessControl(ds);
            }
            else
            {
                var fs = new FileSecurity();
                fs.SetSecurityDescriptorSddlForm(HardenedSddl);
                fs.SetOwner(admins);
                new FileInfo(resolved).SetAccessControl(fs);
            }
        }
        catch { }
    }

    public static void SaveMachineCredential(Dictionary<string, string?> record, string? path = null)
    {
        var payload = JsonSerializer.SerializeToUtf8Bytes(record);
        var encrypted = ProtectedData.Protect(payload, null, DataProtectionScope.LocalMachine);

        var targets = path is not null
            ? new[] { path }
            : [MachineCredentialPath(), UserCredentialPath()];

        bool saved = false;
        foreach (var target in targets)
        {
            try
            {
                var dir = Path.GetDirectoryName(target)!;
                Directory.CreateDirectory(dir);
                var tmpPath = Path.Combine(dir, $"{Path.GetFileNameWithoutExtension(target)}_{Guid.NewGuid():N}.tmp");
                using (var fs = new FileStream(tmpPath, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                {
                    fs.Write(encrypted, 0, encrypted.Length);
                    fs.Flush(true);
                }
                File.Move(tmpPath, target, overwrite: true);
                saved = true;
                ApplyProgramDataAcl(target, isDirectory: false);
            }
            catch { }
        }

        if (!saved && path is null)
            throw new UnauthorizedAccessException("Could not save machine credential to either user or machine path.");
    }

    public static Dictionary<string, string?>? LoadMachineCredential(string? path = null)
    {
        var candidates = path is not null
            ? new[] { path }
            : [MachineCredentialPath(), UserCredentialPath()];

        foreach (var target in candidates)
        {
            if (!File.Exists(target))
                continue;
            try
            {
                var encrypted = File.ReadAllBytes(target);
                var decrypted = ProtectedData.Unprotect(encrypted, null, DataProtectionScope.LocalMachine);
                using var doc = JsonDocument.Parse(decrypted);
                var dict = new Dictionary<string, string?>(StringComparer.Ordinal);
                foreach (var prop in doc.RootElement.EnumerateObject())
                {
                    dict[prop.Name] = prop.Value.ValueKind == JsonValueKind.Null ? null : prop.Value.GetString() ?? prop.Value.GetRawText();
                }

                dict.TryGetValue("credential_id", out var credId);
                dict.TryGetValue("installation_uuid", out var instUuid);
                dict.TryGetValue("device_id", out var devId);
                if ((credId is not null && DummyIds.Contains(credId))
                    || (instUuid is not null && DummyIds.Contains(instUuid))
                    || (devId is not null && DummyIds.Contains(devId)))
                {
                    continue;
                }
                return dict;
            }
            catch { }
        }
        return null;
    }

    public static void DeleteMachineCredential(string? path = null)
    {
        var targets = path is not null
            ? new[] { path }
            : [UserCredentialPath(), MachineCredentialPath()];
        foreach (var target in targets)
        {
            try
            {
                if (File.Exists(target))
                    File.Delete(target);
            }
            catch { }
        }
    }

    public static string Target(string url, string credentialId)
    {
        var digest = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(url + "/" + credentialId))).ToLowerInvariant();
        return "EFL_NEXUS:cloud-v2:" + digest;
    }

    public static void Save(string url, Dictionary<string, string?> record)
    {
        var credId = record["credential_id"] ?? "";
        var json = JsonSerializer.Serialize(record);
        CredentialManager.Write(Target(url, credId), credId, json, CredentialManager.CredPersistLocalMachine);
    }

    public static Dictionary<string, string?> Load(string url, string credentialId)
    {
        var rec = CredentialManager.Read(Target(url, credentialId))
            ?? throw new KeyNotFoundException("Credential not found in Windows Credential Manager.");
        using var doc = JsonDocument.Parse(rec.Secret);
        var dict = new Dictionary<string, string?>(StringComparer.Ordinal);
        foreach (var prop in doc.RootElement.EnumerateObject())
            dict[prop.Name] = prop.Value.ValueKind == JsonValueKind.Null ? null : prop.Value.GetString() ?? prop.Value.GetRawText();
        return dict;
    }

    public static void Delete(string url, string credentialId)
        => CredentialManager.Delete(Target(url, credentialId));

    public static Dictionary<string, string?> Pending(IReadOnlyDictionary<string, string?> enrollment)
    {
        var dict = new Dictionary<string, string?>(enrollment, StringComparer.Ordinal)
        {
            ["credential_id"] = Guid.NewGuid().ToString(),
            ["secret"] = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant()
        };
        return dict;
    }
}
