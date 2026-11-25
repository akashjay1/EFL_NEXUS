using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using KorberAuditShip.Models;

namespace KorberAuditShip.Services;

/// <summary>
/// Resolves Körber credentials from EFL NEXUS bridge sources (environment variables or adjacent config.json)
/// or local user-scoped DPAPI storage, without embedding hardcoded secrets in source code.
/// </summary>
public sealed class CredentialService
{
    public const string MissingCredentialsMessage =
        "Enter the AuditShip username, password, and Fork ID in Settings (or via EFL NEXUS Settings / AUDITSHIP_* environment variables) before opening AuditShip.";

    private readonly string _localStorePath;
    private readonly string _bridgeConfigPath;
    private readonly Func<string, string?> _envGetter;
    private readonly Func<KorberCredentials?>? _customResolver;
    private readonly Action<string, string, string>? _customSaver;

    public CredentialService()
        : this(
            localStorePath: Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "KorberAuditShip",
                "credentials.dat"),
            bridgeConfigPath: ResolveDefaultBridgeConfigPath(),
            envGetter: Environment.GetEnvironmentVariable)
    {
    }

    public CredentialService(
        Func<KorberCredentials?>? customResolver,
        Action<string, string, string>? customSaver = null)
        : this(
            localStorePath: Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "KorberAuditShip",
                "credentials.dat"),
            bridgeConfigPath: ResolveDefaultBridgeConfigPath(),
            envGetter: Environment.GetEnvironmentVariable,
            customResolver: customResolver,
            customSaver: customSaver)
    {
    }

    public CredentialService(
        string localStorePath,
        string bridgeConfigPath,
        Func<string, string?> envGetter,
        Func<KorberCredentials?>? customResolver = null,
        Action<string, string, string>? customSaver = null)
    {
        _localStorePath = localStorePath;
        _bridgeConfigPath = bridgeConfigPath;
        _envGetter = envGetter;
        _customResolver = customResolver;
        _customSaver = customSaver;
    }

    private static string ResolveDefaultBridgeConfigPath()
    {
        try
        {
            var exeDir = AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            var parentDir = Directory.GetParent(exeDir)?.FullName;
            return string.IsNullOrWhiteSpace(parentDir)
                ? string.Empty
                : Path.Combine(parentDir, "config.json");
        }
        catch
        {
            return string.Empty;
        }
    }

    public KorberCredentials? ResolveCredentials()
    {
        // 0. Custom resolver (e.g. from EFL NEXUS ConfigStore)
        if (_customResolver != null)
        {
            var custom = _customResolver();
            if (custom != null && custom.IsComplete)
                return custom;
        }

        // 1. Primary bridge environment variables (_AUDITSHIP_CREDENTIAL_BRIDGE_V2)
        var bridgeUser = (_envGetter("AUDITSHIP_USER") ?? string.Empty).Trim();
        var bridgePass = _envGetter("AUDITSHIP_PASS") ?? string.Empty;
        var bridgeFork = (_envGetter("AUDITSHIP_FORK_ID") ?? string.Empty).Trim();

        if (!string.IsNullOrWhiteSpace(bridgeUser) || !string.IsNullOrWhiteSpace(bridgePass) || !string.IsNullOrWhiteSpace(bridgeFork))
        {
            if (string.IsNullOrWhiteSpace(bridgeFork))
                bridgeFork = bridgeUser;

            var candidate = new KorberCredentials(bridgeUser, bridgePass, bridgeFork, "Environment (AUDITSHIP_*)");
            if (candidate.IsComplete)
                return candidate;
        }

        // 2. Fallback injected environment variables (EFL_KB_*)
        var kbUser = (_envGetter("EFL_KB_USER") ?? string.Empty).Trim();
        var kbPass = _envGetter("EFL_KB_PASS") ?? string.Empty;
        var kbFork = (_envGetter("EFL_KB_FORK") ?? string.Empty).Trim();

        if (!string.IsNullOrWhiteSpace(kbUser) && !string.IsNullOrWhiteSpace(kbPass))
        {
            if (string.IsNullOrWhiteSpace(kbFork))
                kbFork = kbUser;

            return new KorberCredentials(kbUser, kbPass, kbFork, "Environment (EFL_KB_*)");
        }

        // 3. Adjacent parent config.json from EFL NEXUS
        var fromBridgeFile = TryReadBridgeConfigJson();
        if (fromBridgeFile is not null && fromBridgeFile.IsComplete)
            return fromBridgeFile;

        // 4. Local DPAPI-encrypted user settings file
        var fromLocalStore = TryReadDpapiLocalCredentials();
        if (fromLocalStore is not null && fromLocalStore.IsComplete)
            return fromLocalStore;

        return null;
    }

    public void SaveLocalCredentials(string username, string password, string forkId)
    {
        var user = username.Trim();
        var fork = string.IsNullOrWhiteSpace(forkId) ? user : forkId.Trim();

        if (string.IsNullOrWhiteSpace(user) || string.IsNullOrWhiteSpace(password) || string.IsNullOrWhiteSpace(fork))
            throw new ArgumentException("Username, Password, and Fork ID must all be provided.");

        try
        {
            _customSaver?.Invoke(user, password, fork);
        }
        catch
        {
            // Do not fail DPAPI storage if custom saver encountered an issue
        }

        var directory = Path.GetDirectoryName(_localStorePath);
        if (!string.IsNullOrWhiteSpace(directory))
            Directory.CreateDirectory(directory);

        var payload = JsonSerializer.Serialize(new BridgeConfigDto
        {
            auditship_user = user,
            auditship_pass = password,
            auditship_fork_id = fork
        });

        var plainBytes = Encoding.UTF8.GetBytes(payload);
        var protectedBytes = ProtectedData.Protect(plainBytes, null, DataProtectionScope.CurrentUser);
        File.WriteAllBytes(_localStorePath, protectedBytes);
    }

    public void ClearLocalCredentials()
    {
        if (File.Exists(_localStorePath))
            File.Delete(_localStorePath);
    }

    private KorberCredentials? TryReadBridgeConfigJson()
    {
        if (string.IsNullOrWhiteSpace(_bridgeConfigPath) || !File.Exists(_bridgeConfigPath))
            return null;

        try
        {
            var json = File.ReadAllText(_bridgeConfigPath, Encoding.UTF8);
            var dto = JsonSerializer.Deserialize<BridgeConfigDto>(json);
            if (dto is null) return null;

            var user = (dto.auditship_user ?? string.Empty).Trim();
            var pass = dto.auditship_pass ?? string.Empty;
            var fork = (dto.auditship_fork_id ?? string.Empty).Trim();
            if (string.IsNullOrWhiteSpace(fork))
                fork = user;

            return new KorberCredentials(user, pass, fork, $"config.json ({_bridgeConfigPath})");
        }
        catch
        {
            return null;
        }
    }

    private KorberCredentials? TryReadDpapiLocalCredentials()
    {
        if (string.IsNullOrWhiteSpace(_localStorePath) || !File.Exists(_localStorePath))
            return null;

        try
        {
            var protectedBytes = File.ReadAllBytes(_localStorePath);
            var plainBytes = ProtectedData.Unprotect(protectedBytes, null, DataProtectionScope.CurrentUser);
            var json = Encoding.UTF8.GetString(plainBytes);
            var dto = JsonSerializer.Deserialize<BridgeConfigDto>(json);
            if (dto is null) return null;

            var user = (dto.auditship_user ?? string.Empty).Trim();
            var pass = dto.auditship_pass ?? string.Empty;
            var fork = (dto.auditship_fork_id ?? string.Empty).Trim();
            if (string.IsNullOrWhiteSpace(fork))
                fork = user;

            return new KorberCredentials(user, pass, fork, "Local Encrypted Settings (DPAPI)");
        }
        catch
        {
            return null;
        }
    }

    private sealed class BridgeConfigDto
    {
        public string? auditship_user { get; set; }
        public string? auditship_pass { get; set; }
        public string? auditship_fork_id { get; set; }
    }
}
