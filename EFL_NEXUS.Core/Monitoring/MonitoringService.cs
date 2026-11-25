using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Text.Json;
using EflNexus.Core.Infrastructure;

namespace EflNexus.Core.Monitoring;

public sealed class MonitoringService : IDisposable
{
    public const int HeartbeatIntervalSeconds = 15;
    public const int DisconnectedTimeoutSeconds = 90;
    public const int IdleThresholdSeconds = 300;

    private readonly string _configPath;
    private readonly string _version;
    private readonly int _intervalSeconds;
    private readonly ConcurrentQueue<(string Command, string Value)> _commands = new();
    private readonly ManualResetEventSlim _stopping = new(false);
    private readonly ManualResetEventSlim _shutdownPersisted = new(false);
    private readonly object _jobsLock = new();

    private Thread? _thread;
    private Thread? _shutdownWriter;
    private long _lastInteractionTicks = Stopwatch.GetTimestamp();
    private string _module = "Dashboard";
    private string? _journalPath;
    private string? _sessionId;
    private List<Dictionary<string, object?>>? _reconciliationJobs;
    private double _jobsDueTime;

    public string Message { get; private set; } = "Cloud monitoring disabled.";
    public string InstallationUuid { get; private set; } = string.Empty;

    public MonitoringService(string configPath, string version, int intervalSeconds = HeartbeatIntervalSeconds)
    {
        _configPath = configPath;
        _version = version;
        _intervalSeconds = Math.Max(10, intervalSeconds);
    }

    public string Status() => Message;

    public void Interact() => Interlocked.Exchange(ref _lastInteractionTicks, Stopwatch.GetTimestamp());

    public void UpdateContext(object? _identity, string module) => _module = module;

    public void UpdateReconciliationJobs(IEnumerable<IDictionary<string, object?>> records)
    {
        lock (_jobsLock)
        {
            _reconciliationJobs = records.Select(r => new Dictionary<string, object?>(r, StringComparer.Ordinal)).ToList();
        }
    }

    public void Enroll(string value) => _commands.Enqueue(("enroll", value));

    public void Start()
    {
        if (_thread is null)
        {
            _thread = new Thread(Run) { Name = "cloud-monitoring", IsBackground = true };
            _thread.Start();
        }
    }

    public bool IsAlive => _stopping.IsSet ? (_shutdownWriter?.IsAlive == true) : (_thread?.IsAlive == true);

    public void Stop()
    {
        if (_stopping.IsSet) return;
        _stopping.Set();
        if (!string.IsNullOrEmpty(_journalPath) && !string.IsNullOrEmpty(_sessionId))
        {
            var jPath = _journalPath;
            var sid = _sessionId;
            _shutdownWriter = new Thread(() =>
            {
                try
                {
                    using var journal = new OfflineQueue(jPath, timeoutSeconds: 1);
                    journal.Append(sid, "closed", new { });
                    _shutdownPersisted.Set();
                }
                catch
                {
                    Message = "Shutdown journal unavailable; next launch must recover an unclean session.";
                }
            })
            {
                Name = "cloud-close-journal",
                IsBackground = true
            };
            _shutdownWriter.Start();
        }
    }

    private (string OperatorName, string IdentitySource) CurrentOperatorIdentity()
    {
        var profile = KpiProfile.LoadSavedProfile(_configPath);
        if (profile is not null)
            return (profile.UserId, "KPI Profile");
        return (Dns.GetHostName(), "Device Fallback");
    }

    private void Run()
    {
        OfflineQueue? outbox = null;
        CloudClient? client = null;
        FileStream? lease = null;
        string? leasePath = null;

        try
        {
            var root = Path.Combine(Environment.GetEnvironmentVariable("LOCALAPPDATA") ?? "", "EFL_NEXUS", "Monitoring");
            Directory.CreateDirectory(root);
            var settingsPath = Path.Combine(root, "connection.json");

            try
            {
                InstallationUuid = DeviceIdentity.ReadIdentity();
            }
            catch (Exception ex)
            {
                Message = $"Machine identity error: {ex.Message}";
                return;
            }

            outbox = new OfflineQueue(Path.Combine(root, "outbox.sqlite3"));
            var session = Guid.NewGuid().ToString();
            leasePath = Path.Combine(root, session + ".lock");
            lease = new FileStream(leasePath, FileMode.Create, FileAccess.ReadWrite, FileShare.None);
            lease.WriteByte((byte)'1');
            lease.Flush();

            // Clean up unclosed sessions from earlier crashes
            foreach (var oldSid in outbox.ListUnclosedSessions())
            {
                var oldLockPath = Path.Combine(root, oldSid + ".lock");
                try
                {
                    using (var oldLease = new FileStream(oldLockPath, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None))
                    {
                        outbox.Append(oldSid, "unclean", new { });
                    }
                    try { File.Delete(oldLockPath); } catch { }
                }
                catch { }
            }

            var machineCred = MonitoringSecurity.LoadMachineCredential();
            if (machineCred is null && DeviceIdentity.AutoRegisterMachine())
                machineCred = MonitoringSecurity.LoadMachineCredential();

            Dictionary<string, string?>? connection = null;
            if (machineCred is not null)
            {
                connection = ToConnection(machineCred);
            }
            else if (File.Exists(settingsPath))
            {
                try { connection = ReadStringDict(File.ReadAllText(settingsPath)); } catch { connection = null; }
            }

            if (connection is null)
                Message = "Cloud monitoring waiting for machine provisioning.";

            bool active = false;
            (string OperatorName, string IdentitySource, string Module)? previous = null;
            int failures = 0;
            double due = 0;
            bool rejected = false;
            var sw = Stopwatch.StartNew();
            Dictionary<string, string?>? lastCredential = null;

            while (true)
            {
                if (_stopping.IsSet)
                    break;

                if (_commands.TryDequeue(out var cmd) && cmd.Command == "enroll")
                {
                    if (active && !rejected)
                    {
                        Message = "Restart EFL NEXUS before replacing an active enrollment.";
                    }
                    else
                    {
                        try
                        {
                            var data = ReadStringDict(cmd.Value) ?? throw new ArgumentException("Invalid JSON");
                            string[] requiredKeys = ["url", "key", "enrollment_id", "code", "installation_uuid"];
                            if (data.Count != requiredKeys.Length || requiredKeys.Any(k => !data.ContainsKey(k)))
                                throw new ArgumentException("Invalid enrollment fields");
                            if (Guid.Parse(data["installation_uuid"] ?? "").ToString() != InstallationUuid)
                                throw new ArgumentException("Wrong installation");
                            var code = data["code"] ?? "";
                            if (code.Length != 64 || !code.All(Uri.IsHexDigit))
                                throw new ArgumentException("Invalid enrollment code");

                            using var candidate = new CloudClient(data["url"] ?? "", data["key"] ?? "");
                            var record = MonitoringSecurity.Pending(new Dictionary<string, string?>
                            {
                                ["enrollment_id"] = data["enrollment_id"],
                                ["code"] = code,
                                ["installation_uuid"] = data["installation_uuid"]
                            });
                            try
                            {
                                var full = new Dictionary<string, string?>(record, StringComparer.Ordinal)
                                {
                                    ["url"] = candidate.Url,
                                    ["key"] = candidate.Key
                                };
                                MonitoringSecurity.SaveMachineCredential(full);
                                MonitoringSecurity.SetMachineActive(true);
                                machineCred = MonitoringSecurity.LoadMachineCredential();
                            }
                            catch
                            {
                                MonitoringSecurity.Save(candidate.Url, record);
                            }

                            var newConn = new Dictionary<string, string?>(StringComparer.Ordinal)
                            {
                                ["url"] = candidate.Url,
                                ["key"] = candidate.Key,
                                ["credential_id"] = record["credential_id"],
                                ["secret"] = record["secret"],
                                ["pending"] = "true"
                            };
                            WriteConnectionAtomic(settingsPath, newConn);
                            connection = newConn;
                            client?.Dispose();
                            client = null;
                            rejected = false;
                            due = 0;
                        }
                        catch
                        {
                            Message = "Enrollment could not be saved. Check shared identity and enrollment details.";
                        }
                    }
                }

                if (connection is null && !rejected)
                {
                    machineCred = MonitoringSecurity.LoadMachineCredential();
                    if (machineCred is null)
                    {
                        try
                        {
                            if (DeviceIdentity.AutoRegisterMachine())
                                machineCred = MonitoringSecurity.LoadMachineCredential();
                        }
                        catch { }
                    }
                    if (machineCred is not null)
                    {
                        connection = ToConnection(machineCred);
                        Message = "Cloud monitoring provisioned.";
                    }
                }

                if (connection is not null && !rejected)
                {
                    client ??= new CloudClient(connection["url"] ?? "", connection["key"] ?? "");
                    if (sw.Elapsed.TotalSeconds >= due)
                    {
                        try
                        {
                            var credential = machineCred
                                ?? (connection.TryGetValue("secret", out var sec) && !string.IsNullOrEmpty(sec)
                                    ? connection
                                    : MonitoringSecurity.Load(connection["url"] ?? "", connection["credential_id"] ?? ""));
                            lastCredential = credential;

                            if (connection.TryGetValue("pending", out var pend) && pend == "true")
                            {
                                var enrollRes = client.Post("device-enroll", credential);
                                connection["pending"] = "false";
                                if (enrollRes.TryGetValue("device_id", out var devEl))
                                {
                                    var devId = devEl.GetString();
                                    connection["device_id"] = devId;
                                    if (machineCred is not null)
                                    {
                                        machineCred["device_id"] = devId;
                                        try
                                        {
                                            MonitoringSecurity.SaveMachineCredential(machineCred);
                                            MonitoringSecurity.SetMachineActive(true);
                                        }
                                        catch { }
                                    }
                                }
                                WriteConnectionAtomic(settingsPath, connection);
                            }

                            if (!active)
                            {
                                var current = CurrentOperatorIdentity();
                                outbox.Create(session, connection["credential_id"] ?? "", new
                                {
                                    operator_name = current.OperatorName,
                                    identity_source = current.IdentitySource,
                                    device_name = Dns.GetHostName(),
                                    module = _module,
                                    app_version = _version
                                });
                                _journalPath = Path.Combine(root, "outbox.sqlite3");
                                _sessionId = session;
                                previous = (current.OperatorName, current.IdentitySource, _module);
                                active = true;
                            }

                            outbox.ReportGap(session);

                            foreach (var (sid, cid) in outbox.ListActiveLaunches())
                            {
                                List<JsonElement> batch;
                                try
                                {
                                    batch = outbox.Batch(sid);
                                }
                                catch (ExpiredHistoryException)
                                {
                                    outbox.ArchiveExpired(sid);
                                    if (sid == session)
                                    {
                                        session = Guid.NewGuid().ToString();
                                        var current = CurrentOperatorIdentity();
                                        outbox.Create(session, connection["credential_id"] ?? "", new
                                        {
                                            operator_name = current.OperatorName,
                                            identity_source = current.IdentitySource,
                                            device_name = Dns.GetHostName(),
                                            module = _module,
                                            app_version = _version
                                        });
                                        _sessionId = session;
                                        previous = (current.OperatorName, current.IdentitySource, _module);
                                    }
                                    outbox.ReportGap(session);
                                    continue;
                                }

                                if (batch.Count == 0 && sid != session)
                                    continue;

                                try
                                {
                                    Dictionary<string, string?> cred;
                                    if (machineCred is not null && machineCred.TryGetValue("credential_id", out var mcid) && mcid == cid)
                                        cred = machineCred;
                                    else if (connection.TryGetValue("credential_id", out var ccid) && ccid == cid
                                             && connection.TryGetValue("secret", out var csec) && !string.IsNullOrEmpty(csec))
                                        cred = connection;
                                    else
                                        cred = MonitoringSecurity.Load(connection["url"] ?? "", cid);

                                    var idle = (Stopwatch.GetTimestamp() - Interlocked.Read(ref _lastInteractionTicks)) / (double)Stopwatch.Frequency;
                                    var live = (sid == session && !_stopping.IsSet) ? outbox.Live(sid, idle) : null;
                                    var result = client.Post("device-telemetry", new
                                    {
                                        session_id = sid,
                                        events = batch,
                                        live
                                    }, cred);
                                    var seq = result["event_sequence"].GetInt64();
                                    outbox.Acknowledge(sid, seq);
                                }
                                catch (CloudErrorException histErr)
                                {
                                    if (sid != session && histErr.Status is 400 or 401 or 403 or 409)
                                    {
                                        outbox.MarkBlocked(sid);
                                        continue;
                                    }
                                    throw;
                                }
                            }

                            failures = 0;
                            if (sw.Elapsed.TotalSeconds >= _jobsDueTime)
                            {
                                List<Dictionary<string, object?>>? jobsSnapshot;
                                lock (_jobsLock)
                                    jobsSnapshot = _reconciliationJobs is null ? null : [.. _reconciliationJobs];
                                if (jobsSnapshot is not null)
                                {
                                    try
                                    {
                                        for (int offset = 0; offset < jobsSnapshot.Count; offset += 50)
                                        {
                                            var slice = jobsSnapshot.Skip(offset).Take(50).ToList();
                                            client.Post("device-jobs", new { jobs = slice }, credential);
                                        }
                                    }
                                    catch { }
                                }
                                _jobsDueTime = sw.Elapsed.TotalSeconds + 30;
                            }

                            var blocked = outbox.BlockedCount();
                            Message = blocked == 0
                                ? "Cloud connected."
                                : "Cloud connected; historical sessions need review.";
                            due = sw.Elapsed.TotalSeconds + _intervalSeconds;
                        }
                        catch (CloudErrorException error)
                        {
                            var status = error.Status;
                            if (status == 403)
                            {
                                if (DecommissionService.HandleRejection(client, lastCredential) == RejectionOutcome.ReRegister)
                                {
                                    status = 401; // restored by an admin: enroll again below
                                }
                                else
                                {
                                    rejected = true;
                                    Message = "Device authorization revoked by administrator. Monitoring stopped.";
                                    break;
                                }
                            }
                            if (status == 401)
                            {
                                MonitoringSecurity.DeleteMachineCredential();
                                if (DeviceIdentity.AutoRegisterMachine(force: true))
                                {
                                    machineCred = MonitoringSecurity.LoadMachineCredential();
                                    if (machineCred is not null)
                                    {
                                        connection = ToConnection(machineCred);
                                        client.Dispose();
                                        client = null;
                                        failures = 0;
                                        due = sw.Elapsed.TotalSeconds;
                                        continue;
                                    }
                                }
                                rejected = true;
                                if (active)
                                {
                                    outbox.Append(session, "unclean", new { });
                                    outbox.MarkBlocked(session);
                                    active = false;
                                    session = Guid.NewGuid().ToString();
                                }
                                Message = "Cloud credential invalid or expired.";
                            }
                            else if (error.Status is 400 or 409)
                            {
                                rejected = true;
                                if (active)
                                {
                                    outbox.Append(session, "unclean", new { });
                                    outbox.MarkBlocked(session);
                                    active = false;
                                    session = Guid.NewGuid().ToString();
                                }
                                Message = "Cloud needs attention: check credentials, clock and pending history. History retained.";
                            }
                            else
                            {
                                failures += 1;
                            }
                        }
                        catch
                        {
                            failures += 1;
                        }

                        if (failures > 0)
                        {
                            Message = "Cloud unavailable; events retained locally.";
                            var backoff = Math.Min(240.0, 1 << Math.Min(failures, 7)) * (0.8 + Random.Shared.NextDouble() * 0.4);
                            due = sw.Elapsed.TotalSeconds + backoff;
                        }
                    }
                }

                if (active && previous is not null)
                {
                    var current = CurrentOperatorIdentity();
                    if (current.OperatorName != previous.Value.OperatorName || current.IdentitySource != previous.Value.IdentitySource)
                    {
                        outbox.Append(session, "operator_changed", new
                        {
                            operator_name = current.OperatorName,
                            identity_source = current.IdentitySource
                        });
                    }
                    if (_module != previous.Value.Module)
                    {
                        outbox.Append(session, "module_changed", new { module = _module });
                    }
                    previous = (current.OperatorName, current.IdentitySource, _module);
                }

                if (_stopping.IsSet)
                {
                    if (active)
                    {
                        outbox.Append(session, "closed", new { });
                        if (client is not null && !rejected && lastCredential is not null)
                        {
                            try
                            {
                                var result = client.Post("device-telemetry", new
                                {
                                    session_id = session,
                                    events = outbox.Batch(session),
                                    live = (object?)null
                                }, lastCredential);
                                outbox.Acknowledge(session, result["event_sequence"].GetInt64());
                            }
                            catch { }
                        }
                    }
                    break;
                }

                _stopping.Wait(500);
            }
        }
        catch (Exception ex)
        {
            Message = $"Cloud monitoring unavailable ({ex.GetType().Name}). Shared device setup may be required; the application remains available.";
        }
        finally
        {
            client?.Dispose();
            outbox?.Dispose();
            if (lease is not null)
            {
                try { lease.Dispose(); } catch { }
                if (!string.IsNullOrEmpty(leasePath))
                {
                    try { File.Delete(leasePath); } catch { }
                }
            }
        }
    }

    private static Dictionary<string, string?> ToConnection(Dictionary<string, string?> machineCred) => new(StringComparer.Ordinal)
    {
        ["url"] = machineCred.GetValueOrDefault("url"),
        ["key"] = machineCred.GetValueOrDefault("key"),
        ["credential_id"] = machineCred.GetValueOrDefault("credential_id"),
        ["secret"] = machineCred.GetValueOrDefault("secret"),
        ["device_id"] = machineCred.GetValueOrDefault("device_id"),
        ["pending"] = "false"
    };

    private static Dictionary<string, string?>? ReadStringDict(string json)
    {
        using var doc = JsonDocument.Parse(json);
        if (doc.RootElement.ValueKind != JsonValueKind.Object) return null;
        var d = new Dictionary<string, string?>(StringComparer.Ordinal);
        foreach (var p in doc.RootElement.EnumerateObject())
            d[p.Name] = p.Value.ValueKind == JsonValueKind.Null ? null : p.Value.ValueKind == JsonValueKind.True ? "true" : p.Value.ValueKind == JsonValueKind.False ? "false" : (p.Value.GetString() ?? p.Value.GetRawText());
        return d;
    }

    private static void WriteConnectionAtomic(string settingsPath, Dictionary<string, string?> data)
    {
        var tmp = Path.ChangeExtension(settingsPath, ".tmp");
        File.WriteAllText(tmp, JsonSerializer.Serialize(data));
        File.Move(tmp, settingsPath, overwrite: true);
    }

    public void Dispose()
    {
        Stop();
        _stopping.Dispose();
        _shutdownPersisted.Dispose();
    }
}
