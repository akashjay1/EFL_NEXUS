using System.Diagnostics;
using System.Net;
using System.Net.Http;
using System.Net.Http.Json;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using EflNexus.Core.Infrastructure;

namespace EflNexus.Core.Monitoring;

public sealed record PresenceConfig(string Url, string Key, string DeviceId)
{
    public static PresenceConfig? FromStore(ConfigStore? store)
    {
        if (store is null) return null;
        if (!string.Equals(store.Get("presence_enabled", "false"), "true", StringComparison.OrdinalIgnoreCase))
            return null;
        return new PresenceConfig(
            OperatorPresence.ValidateProjectUrl(store.Get("presence_url")),
            OperatorPresence.ValidatePublishableKey(store.Get("presence_key")),
            Guid.Parse(store.Get("presence_device_id")).ToString());
    }
}

public static class OperatorPresence
{
    public const int HeartbeatSeconds = 30;
    public const int StaleSeconds = 90;
    public const string EnrollmentPrefix = "eflnexus1.";

    private static readonly Regex SupabaseHostRegex = new(@"^[a-z0-9]+\.supabase\.co$", RegexOptions.Compiled);
    private static readonly Regex PublishableKeyRegex = new(@"^sb_publishable_[A-Za-z0-9_-]{16,200}$", RegexOptions.Compiled);
    private static readonly Regex TokenHexRegex = new(@"^[0-9a-f]{64}$", RegexOptions.Compiled);

    public static string ValidateProjectUrl(string? value)
    {
        var trimmed = (value ?? string.Empty).Trim().TrimEnd('/');
        if (!Uri.TryCreate(trimmed, UriKind.Absolute, out var uri)
            || !string.Equals(uri.Scheme, "https", StringComparison.Ordinal)
            || string.IsNullOrEmpty(uri.Host)
            || !SupabaseHostRegex.IsMatch(uri.Host)
            || !string.IsNullOrEmpty(uri.UserInfo)
            || !uri.IsDefaultPort
            || (uri.AbsolutePath is not "" and not "/")
            || !string.IsNullOrEmpty(uri.Query)
            || !string.IsNullOrEmpty(uri.Fragment))
        {
            throw new ArgumentException("Use the HTTPS project URL from Supabase (not a dashboard URL).");
        }
        return trimmed;
    }

    public static string ValidatePublishableKey(string? value)
    {
        var trimmed = (value ?? string.Empty).Trim();
        if (!PublishableKeyRegex.IsMatch(trimmed))
            throw new ArgumentException("Use a Supabase publishable key; secret and service-role keys are not accepted.");
        return trimmed;
    }

    public static (PresenceConfig Config, string Token) ParseEnrollment(string? code)
    {
        var trimmed = (code ?? string.Empty).Trim();
        if (trimmed.Length > 8192 || !trimmed.StartsWith(EnrollmentPrefix, StringComparison.Ordinal))
            throw new ArgumentException("Paste the enrollment code created in the Live Operators dashboard.");
        try
        {
            var encoded = trimmed[EnrollmentPrefix.Length..].Replace('-', '+').Replace('_', '/');
            var pad = (4 - encoded.Length % 4) % 4;
            encoded += new string('=', pad);
            var raw = Convert.FromBase64String(encoded);
            using var doc = JsonDocument.Parse(raw);
            var root = doc.RootElement;
            var url = ValidateProjectUrl(root.GetProperty("url").GetString());
            var key = ValidatePublishableKey(root.GetProperty("key").GetString());
            var deviceId = Guid.Parse(root.GetProperty("device_id").GetString() ?? "").ToString();
            var token = root.GetProperty("device_token").GetString() ?? "";
            if (!TokenHexRegex.IsMatch(token))
                throw new ArgumentException("Invalid device credential.");
            return (new PresenceConfig(url, key, deviceId), token);
        }
        catch (Exception ex) when (ex is FormatException or JsonException or KeyNotFoundException or InvalidOperationException or ArgumentException)
        {
            throw new ArgumentException("Invalid enrollment code. Ask an administrator to create a new device enrollment.", ex);
        }
    }

    public static string CredentialTarget(PresenceConfig config)
    {
        var bytes = Encoding.UTF8.GetBytes($"{config.Url}/{config.DeviceId}");
        var digest = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        return "EFL_NEXUS:operator-presence:" + digest;
    }

    public static string LoadDeviceToken(PresenceConfig config)
    {
        try
        {
            var rec = CredentialManager.Read(CredentialTarget(config));
            return rec?.Secret ?? string.Empty;
        }
        catch (Exception ex)
        {
            throw new InvalidOperationException("Windows Credential Manager could not read this device enrollment.", ex);
        }
    }

    private static void SaveDeviceToken(PresenceConfig config, string token)
        => CredentialManager.Write(CredentialTarget(config), config.DeviceId, token, CredentialManager.CredPersistLocalMachine);

    public static PresenceConfig SaveEnrollment(ConfigStore store, string code)
    {
        var (config, token) = ParseEnrollment(code);
        var previousToken = LoadDeviceToken(config);
        var previousConfig = new Dictionary<string, string>(store.Config, StringComparer.Ordinal);
        SaveDeviceToken(config, token);

        var ok = store.SaveKeyValues(
            ("presence_enabled", "true"),
            ("presence_url", config.Url),
            ("presence_key", config.Key),
            ("presence_device_id", config.DeviceId));

        if (!ok)
        {
            store.Config.Clear();
            foreach (var kv in previousConfig)
                store.Config[kv.Key] = kv.Value;

            if (!string.IsNullOrEmpty(previousToken))
                SaveDeviceToken(config, previousToken);
            else
                CredentialManager.Delete(CredentialTarget(config));

            throw new InvalidOperationException("Could not save tracking settings. Check file access.");
        }
        return config;
    }

    public static void EnableSavedTracking(ConfigStore store)
    {
        var config = new PresenceConfig(
            ValidateProjectUrl(store.Get("presence_url")),
            ValidatePublishableKey(store.Get("presence_key")),
            Guid.Parse(store.Get("presence_device_id")).ToString());

        if (string.IsNullOrEmpty(LoadDeviceToken(config)))
            throw new ArgumentException("No saved device credential. Paste a new enrollment code.");

        var previous = new Dictionary<string, string>(store.Config, StringComparer.Ordinal);
        if (!store.SaveKeyValues(("presence_enabled", "true")))
        {
            store.Config.Clear();
            foreach (var kv in previous)
                store.Config[kv.Key] = kv.Value;
            throw new InvalidOperationException("Could not save tracking settings. Check file access.");
        }
    }

    public static string DeviceName()
    {
        var name = Dns.GetHostName().Trim();
        if (string.IsNullOrEmpty(name)) name = "Unnamed device";
        return name.Length > 120 ? name[..120] : name;
    }

    public static Dictionary<string, string?> PresenceIdentity(KpiUserProfile? profile, string hostname)
    {
        var op = profile is not null ? profile.UserId.Trim() : null;
        if (op is not null && op.Length > 120) op = op[..120];
        var dev = (hostname ?? string.Empty).Trim();
        if (string.IsNullOrEmpty(dev)) dev = "Unnamed device";
        if (dev.Length > 120) dev = dev[..120];
        return new Dictionary<string, string?>
        {
            ["operator_name"] = op,
            ["device_name"] = dev
        };
    }
}

public sealed class PresenceTracker : IDisposable
{
    private readonly PresenceConfig _config;
    private string _token;
    private readonly string _sessionId = Guid.NewGuid().ToString();
    private readonly Dictionary<string, object?> _context;
    private readonly object _lock = new();
    private readonly ManualResetEventSlim _stop = new(false);
    private Thread? _thread;
    private int _sequence;
    private string _status = "Starting tracking\u2026";
    private long? _lastSuccessTicks;
    private bool _rejected;

    public string SessionId => _sessionId;

    public PresenceTracker(PresenceConfig config, string token, Dictionary<string, string?> identity, string appVersion)
    {
        _config = config;
        _token = token;
        var ver = (appVersion ?? string.Empty);
        if (ver.Length > 40) ver = ver[..40];
        _context = new Dictionary<string, object?>(StringComparer.Ordinal);
        foreach (var kv in identity)
            _context[kv.Key] = kv.Value;
        _context["current_tool"] = "Dashboard";
        _context["app_version"] = ver;
    }

    public void Start()
    {
        if (_thread is null)
        {
            _thread = new Thread(Run) { Name = "operator-presence", IsBackground = true };
            _thread.Start();
        }
    }

    public void UpdateContext(Dictionary<string, string?> identity, string currentTool)
    {
        lock (_lock)
        {
            foreach (var kv in identity)
                _context[kv.Key] = kv.Value;
            var tool = currentTool ?? string.Empty;
            _context["current_tool"] = tool.Length > 80 ? tool[..80] : tool;
        }
    }

    public void Stop() => _stop.Set();

    public bool IsAlive => _thread?.IsAlive == true;

    public string Status()
    {
        lock (_lock)
        {
            if (!_rejected && _lastSuccessTicks.HasValue)
            {
                var elapsed = (Stopwatch.GetTimestamp() - _lastSuccessTicks.Value) / (double)Stopwatch.Frequency;
                if (elapsed > OperatorPresence.StaleSeconds)
                    return "Tracking connection lost; app remains available.";
            }
            return _status;
        }
    }

    private string Send(HttpClient http, bool closed = false)
    {
        Dictionary<string, object?> payload;
        lock (_lock)
        {
            _sequence += 1;
            payload = new Dictionary<string, object?>(StringComparer.Ordinal);
            foreach (var kv in _context)
                payload["p_" + kv.Key] = kv.Value;
            payload["p_device_id"] = _config.DeviceId;
            payload["p_device_token"] = _token;
            payload["p_session_id"] = _sessionId;
            payload["p_sequence"] = _sequence;
            payload["p_closed"] = closed;
        }

        using var req = new HttpRequestMessage(HttpMethod.Post, _config.Url + "/rest/v1/rpc/nexus_heartbeat");
        req.Headers.Add("apikey", _config.Key);
        req.Content = JsonContent.Create(payload);
        using var resp = http.Send(req);

        if ((int)resp.StatusCode is 401 or 403)
        {
            lock (_lock)
            {
                _rejected = true;
                _status = "Enrollment rejected or revoked. Ask your administrator to enroll this device.";
            }
            return "rejected";
        }

        if (resp.StatusCode != HttpStatusCode.OK)
            throw new HttpRequestException($"Unexpected tracking status {(int)resp.StatusCode}");

        using var stream = resp.Content.ReadAsStream();
        using var doc = JsonDocument.Parse(stream);
        if (doc.RootElement.ValueKind != JsonValueKind.Object
            || !doc.RootElement.TryGetProperty("accepted", out var acceptedEl)
            || acceptedEl.ValueKind is not (JsonValueKind.True or JsonValueKind.False))
        {
            throw new InvalidDataException("Unexpected tracking response");
        }

        if (acceptedEl.GetBoolean())
        {
            lock (_lock)
            {
                _lastSuccessTicks = Stopwatch.GetTimestamp();
                _status = "Connected \u2014 sharing KPI name/device and selected tool.";
            }
        }
        return "ok";
    }

    private void Run()
    {
        int failures = 0;
        bool rejected = false;
        using var handler = new HttpClientHandler { AllowAutoRedirect = false };
        using var http = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(5) };

        try
        {
            while (!_stop.IsSet)
            {
                try
                {
                    rejected = Send(http) == "rejected";
                    if (rejected) break;
                    failures = 0;
                }
                catch
                {
                    failures += 1;
                    lock (_lock)
                    {
                        _status = "Tracking unavailable; retrying in the background.";
                    }
                }

                var waitSec = Math.Min(OperatorPresence.HeartbeatSeconds * (1 << Math.Min(failures, 3)), 240);
                _stop.Wait(TimeSpan.FromSeconds(waitSec));
            }
        }
        finally
        {
            if (_stop.IsSet && !rejected)
            {
                try { Send(http, closed: true); } catch { }
            }
            _token = string.Empty;
        }
    }

    public void Dispose()
    {
        Stop();
        _stop.Dispose();
    }
}
