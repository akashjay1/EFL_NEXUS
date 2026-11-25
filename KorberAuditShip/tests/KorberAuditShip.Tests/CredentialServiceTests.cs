using System.IO;
using System.Text.Json;
using KorberAuditShip.Services;
using Xunit;

namespace KorberAuditShip.Tests;

public sealed class CredentialServiceTests : IDisposable
{
    private readonly string _tempDir;
    private readonly string _localStorePath;
    private readonly string _bridgeConfigPath;

    public CredentialServiceTests()
    {
        _tempDir = Path.Combine(Path.GetTempPath(), $"KorberCredTests_{Guid.NewGuid():N}");
        Directory.CreateDirectory(_tempDir);
        _localStorePath = Path.Combine(_tempDir, "credentials.dat");
        _bridgeConfigPath = Path.Combine(_tempDir, "config.json");
    }

    public void Dispose()
    {
        if (Directory.Exists(_tempDir))
            Directory.Delete(_tempDir, recursive: true);
    }

    [Fact]
    public void ResolveCredentials_PrefersAuditShipEnvVars_AndDefaultsForkIdToUsername()
    {
        var env = new Dictionary<string, string?>
        {
            ["AUDITSHIP_USER"] = " OP_USER1 ",
            ["AUDITSHIP_PASS"] = "Secret!123",
            ["EFL_KB_USER"] = "OTHER_USER",
            ["EFL_KB_PASS"] = "OTHER_PASS"
        };

        var service = new CredentialService(_localStorePath, _bridgeConfigPath, k => env.GetValueOrDefault(k));
        var creds = service.ResolveCredentials();

        Assert.NotNull(creds);
        Assert.Equal("OP_USER1", creds!.Username);
        Assert.Equal("Secret!123", creds.Password);
        Assert.Equal("OP_USER1", creds.ForkId);
        Assert.Contains("AUDITSHIP_*", creds.Source);
    }

    [Fact]
    public void ResolveCredentials_UsesEflKbEnvVars_WhenAuditShipEnvVarsAbsent()
    {
        var env = new Dictionary<string, string?>
        {
            ["EFL_KB_USER"] = "KB_OP",
            ["EFL_KB_PASS"] = "KB_PW",
            ["EFL_KB_FORK"] = "FORK_09"
        };

        var service = new CredentialService(_localStorePath, _bridgeConfigPath, k => env.GetValueOrDefault(k));
        var creds = service.ResolveCredentials();

        Assert.NotNull(creds);
        Assert.Equal("KB_OP", creds!.Username);
        Assert.Equal("KB_PW", creds.Password);
        Assert.Equal("FORK_09", creds.ForkId);
        Assert.Contains("EFL_KB_*", creds.Source);
    }

    [Fact]
    public void ResolveCredentials_ReadsAdjacentBridgeConfigJson_WhenEnvVarsAbsent()
    {
        File.WriteAllText(_bridgeConfigPath, JsonSerializer.Serialize(new
        {
            auditship_user = "NEXUS_USER",
            auditship_pass = "NEXUS_PASS",
            auditship_fork_id = "FORK_NEXUS"
        }));

        var service = new CredentialService(_localStorePath, _bridgeConfigPath, _ => null);
        var creds = service.ResolveCredentials();

        Assert.NotNull(creds);
        Assert.Equal("NEXUS_USER", creds!.Username);
        Assert.Equal("NEXUS_PASS", creds.Password);
        Assert.Equal("FORK_NEXUS", creds.ForkId);
        Assert.Contains("config.json", creds.Source);
    }

    [Fact]
    public void SaveAndResolveLocalCredentials_RoundTripsViaDpapi_AndClearDeletesFile()
    {
        var service = new CredentialService(_localStorePath, _bridgeConfigPath, _ => null);
        Assert.Null(service.ResolveCredentials());

        service.SaveLocalCredentials("LOCAL_OP", "LocalPass#9", "FORK_77");

        Assert.True(File.Exists(_localStorePath));
        // Encrypted DPAPI bytes should not contain plaintext password
        var rawContent = File.ReadAllText(_localStorePath);
        Assert.DoesNotContain("LocalPass#9", rawContent, StringComparison.Ordinal);

        var loaded = service.ResolveCredentials();
        Assert.NotNull(loaded);
        Assert.Equal("LOCAL_OP", loaded!.Username);
        Assert.Equal("LocalPass#9", loaded.Password);
        Assert.Equal("FORK_77", loaded.ForkId);
        Assert.Contains("DPAPI", loaded.Source);

        service.ClearLocalCredentials();
        Assert.False(File.Exists(_localStorePath));
        Assert.Null(service.ResolveCredentials());
    }

    [Fact]
    public void SaveLocalCredentials_RejectsMissingFields()
    {
        var service = new CredentialService(_localStorePath, _bridgeConfigPath, _ => null);
        Assert.Throws<ArgumentException>(() => service.SaveLocalCredentials("", "pass", "fork"));
        Assert.Throws<ArgumentException>(() => service.SaveLocalCredentials("user", "", "fork"));
    }
}
