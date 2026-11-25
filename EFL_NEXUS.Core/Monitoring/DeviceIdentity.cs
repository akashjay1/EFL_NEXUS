using System.IO;
using System.Net;
using System.Security.Cryptography;
using System.Text.Json;
using Microsoft.Win32;
using EflNexus.Core.Infrastructure;

namespace EflNexus.Core.Monitoring;

public static class DeviceIdentity
{
    public static string DefaultSupabaseUrl =>
        Environment.GetEnvironmentVariable("EFL_NEXUS_SUPABASE_URL") is { Length: > 0 } u
            ? u
            : "https://wykmgymitdxkqbpywpzh.supabase.co";

    public static string DefaultSupabaseKey =>
        Environment.GetEnvironmentVariable("EFL_NEXUS_SUPABASE_KEY") is { Length: > 0 } k
            ? k
            : "sb_publishable_4kmXj_vznXL8qyK5hFXeoQ_eSGi3xkR";

    public static string IdentityPath()
        => Path.Combine(MonitoringSecurity.ProgramDataRoot, "EFL_NEXUS_Monitoring", "installation.json");

    public static string UserIdentityPath()
        => Path.Combine(MonitoringSecurity.UserMonitoringDir(), "installation.json");

    public static string MachineBinding()
    {
        using var hklm = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, RegistryView.Registry64);
        using var key = hklm.OpenSubKey(@"SOFTWARE\Microsoft\Cryptography", writable: false)
            ?? throw new InvalidOperationException("Cannot open Windows Cryptography registry key.");
        return key.GetValue("MachineGuid")?.ToString()
            ?? throw new InvalidOperationException("MachineGuid value missing.");
    }

    public static string ReadIdentity(string? path = null)
    {
        if (path is not null)
        {
            if (!File.Exists(path))
                throw new FileNotFoundException($"Identity file not found at {path}", path);
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            var binding = doc.RootElement.TryGetProperty("machine_binding", out var mb) ? mb.GetString() : null;
            if (binding != MachineBinding())
                throw new InvalidOperationException("Shared identity belongs to another Windows installation. Run setup again.");
            var uuidVal = Guid.Parse(doc.RootElement.GetProperty("installation_uuid").GetString() ?? "").ToString();
            if (MonitoringSecurity.DummyIds.Contains(uuidVal))
                throw new FileNotFoundException("Identity file contains dummy UUID");
            return uuidVal;
        }

        string[] targets = [IdentityPath(), UserIdentityPath()];
        var currentBinding = MachineBinding();
        foreach (var target in targets)
        {
            if (!File.Exists(target)) continue;
            try
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(target));
                var binding = doc.RootElement.TryGetProperty("machine_binding", out var mb) ? mb.GetString() : null;
                if (binding != currentBinding) continue;
                var uuidVal = Guid.Parse(doc.RootElement.GetProperty("installation_uuid").GetString() ?? "").ToString();
                if (MonitoringSecurity.DummyIds.Contains(uuidVal)) continue;
                return uuidVal;
            }
            catch { }
        }
        throw new FileNotFoundException("Valid identity file not found");
    }

    public static string GetOrCreateIdentity(string? path = null)
    {
        try { return ReadIdentity(path); } catch { }

        var value = Guid.NewGuid().ToString();
        var record = new { installation_uuid = value, machine_binding = MachineBinding() };
        var json = JsonSerializer.Serialize(record);
        string[] targets = path is not null ? [path] : [IdentityPath(), UserIdentityPath()];

        foreach (var target in targets)
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                File.WriteAllText(target, json);
                return value;
            }
            catch { }
        }
        return value;
    }

    public static bool AutoRegisterMachine(string? url = null, string? key = null, bool force = false)
    {
        if (!force)
        {
            var existing = MonitoringSecurity.LoadMachineCredential();
            if (existing is not null
                && existing.TryGetValue("credential_id", out var ecid)
                && !string.IsNullOrEmpty(ecid)
                && !MonitoringSecurity.DummyIds.Contains(ecid))
            {
                MonitoringSecurity.SetMachineActive(true);
                return true;
            }
        }

        var targetUrl = url ?? DefaultSupabaseUrl;
        var targetKey = key ?? DefaultSupabaseKey;
        string instId;
        try { instId = GetOrCreateIdentity(); }
        catch { return false; }

        var credId = Guid.NewGuid().ToString();
        var credSecret = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();
        var host = Dns.GetHostName();
        var deviceName = host.Length > 120 ? host[..120] : host;

        using var client = new CloudClient(targetUrl, targetKey);
        try
        {
            var res = client.Post("device-enroll", new
            {
                auto_register = true,
                device_name = deviceName,
                installation_uuid = instId,
                credential_id = credId,
                secret = credSecret
            });

            var machineRecord = new Dictionary<string, string?>(StringComparer.Ordinal)
            {
                ["url"] = client.Url,
                ["key"] = client.Key,
                ["device_id"] = res.TryGetValue("device_id", out var dEl) ? dEl.GetString() : null,
                ["credential_id"] = credId,
                ["secret"] = credSecret,
                ["installation_uuid"] = instId
            };
            MonitoringSecurity.SaveMachineCredential(machineRecord);
            MonitoringSecurity.SetMachineActive(true);
            return true;
        }
        catch (CloudErrorException ex) when (ex.Status == 403)
        {
            // Revoked installation: stay installed, just don't monitor. Uninstall is an explicit admin request.
            return false;
        }
        catch
        {
            return false;
        }
    }

    public static (string InstallationUuid, string? CredentialId) Provision(string? provisioningSource = null)
    {
        if (!Win32Interop.IsUserAnAdmin())
            throw new UnauthorizedAccessException("Shared device setup requires Windows administrator approval.");

        var idPath = IdentityPath();
        var parentDir = Path.GetDirectoryName(idPath)!;
        Directory.CreateDirectory(parentDir);

        var parentInfo = new DirectoryInfo(parentDir);
        if (parentInfo.Attributes.HasFlag(FileAttributes.ReparsePoint))
            throw new InvalidOperationException("Shared identity directory must not be a link.");

        MonitoringSecurity.ApplyProgramDataAcl(parentDir, isDirectory: true);

        using var mutex = new Mutex(false, @"Global\EFL_NEXUS_Monitoring_Setup");
        bool acquired = false;
        try
        {
            acquired = mutex.WaitOne(5000);
        }
        catch (AbandonedMutexException)
        {
            acquired = true;
        }

        if (!acquired)
            throw new TimeoutException("Another shared device setup is in progress.");

        var tempFile = Path.Combine(parentDir, Guid.NewGuid() + ".tmp");
        try
        {
            if (File.Exists(idPath) && new FileInfo(idPath).Attributes.HasFlag(FileAttributes.ReparsePoint))
                throw new InvalidOperationException("Identity file must not be a link.");

            string? instId = null;
            if (File.Exists(idPath))
            {
                MonitoringSecurity.ApplyProgramDataAcl(idPath, isDirectory: false);
                try { instId = ReadIdentity(idPath); } catch { instId = null; }
            }

            if (string.IsNullOrEmpty(instId))
            {
                instId = Guid.NewGuid().ToString();
                var json = JsonSerializer.Serialize(new { installation_uuid = instId, machine_binding = MachineBinding() });
                File.WriteAllText(tempFile, json);
                File.Move(tempFile, idPath, overwrite: true);
                MonitoringSecurity.ApplyProgramDataAcl(idPath, isDirectory: false);

                var staleCred = Path.Combine(parentDir, "credential.enc");
                try { if (File.Exists(staleCred)) File.Delete(staleCred); } catch { }
            }

            string? sourceFile = null;
            Dictionary<string, string>? data = null;
            if (!string.IsNullOrWhiteSpace(provisioningSource))
            {
                if (File.Exists(provisioningSource))
                {
                    sourceFile = provisioningSource;
                    data = JsonSerializer.Deserialize<Dictionary<string, string>>(File.ReadAllText(provisioningSource));
                }
                else
                {
                    try { data = JsonSerializer.Deserialize<Dictionary<string, string>>(provisioningSource); } catch { }
                }
            }
            else
            {
                var autoPath = Path.Combine(parentDir, "provisioning.json");
                if (File.Exists(autoPath))
                {
                    sourceFile = autoPath;
                    data = JsonSerializer.Deserialize<Dictionary<string, string>>(File.ReadAllText(autoPath));
                }
            }

            if (data is not null)
            {
                string[] required = ["url", "key", "enrollment_id", "code", "installation_uuid"];
                var missing = required.Where(r => !data.ContainsKey(r)).ToArray();
                if (missing.Length > 0)
                    throw new ArgumentException($"Invalid provisioning data, missing: {string.Join(", ", missing)}");
                if (Guid.Parse(data["installation_uuid"]).ToString() != instId)
                    throw new ArgumentException("Provisioning payload installation UUID does not match this machine");
                var code = data["code"];
                if (code.Length != 64 || !code.All(c => Uri.IsHexDigit(c)))
                    throw new ArgumentException("Invalid enrollment code format");

                var credId = Guid.NewGuid().ToString();
                var credSecret = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();
                using var client = new CloudClient(data["url"], data["key"]);
                var res = client.Post("device-enroll", new
                {
                    enrollment_id = data["enrollment_id"],
                    code,
                    installation_uuid = instId,
                    credential_id = credId,
                    secret = credSecret
                });

                MonitoringSecurity.SaveMachineCredential(new Dictionary<string, string?>(StringComparer.Ordinal)
                {
                    ["url"] = client.Url,
                    ["key"] = client.Key,
                    ["device_id"] = res.TryGetValue("device_id", out var devEl) ? devEl.GetString() : null,
                    ["credential_id"] = credId,
                    ["secret"] = credSecret,
                    ["installation_uuid"] = instId
                });
                MonitoringSecurity.SetMachineActive(true, Path.Combine(parentDir, "monitoring_active.token"));

                if (sourceFile is not null && File.Exists(sourceFile))
                {
                    try
                    {
                        var len = new FileInfo(sourceFile).Length;
                        using (var fs = new FileStream(sourceFile, FileMode.Open, FileAccess.ReadWrite))
                        {
                            fs.Write(new byte[len], 0, (int)Math.Min(len, int.MaxValue));
                            fs.Flush(true);
                        }
                        File.Delete(sourceFile);
                    }
                    catch { }
                }

                return (instId, credId);
            }

            if (AutoRegisterMachine())
            {
                var cred = MonitoringSecurity.LoadMachineCredential(Path.Combine(parentDir, "credential.enc"));
                if (cred is not null && cred.TryGetValue("credential_id", out var cid) && !string.IsNullOrEmpty(cid))
                    return (instId, cid);
            }

            return (instId, null);
        }
        finally
        {
            if (File.Exists(tempFile))
            {
                try { File.Delete(tempFile); } catch { }
            }
            if (acquired)
            {
                try { mutex.ReleaseMutex(); } catch { }
            }
        }
    }
}
