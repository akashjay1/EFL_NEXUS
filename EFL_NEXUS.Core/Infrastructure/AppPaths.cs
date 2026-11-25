using System.IO;
using System.Reflection;

namespace EflNexus.Core.Infrastructure;

public static class AppPaths
{
    public static readonly string[] HelperFlags =
    [
        "--provision-monitoring",
        "--whatsapp-browser",
        "--internal-browser",
        "--loading-history-browser"
    ];

    public static bool IsDesktopLaunch(string[] args)
        => !args.Any(a => HelperFlags.Contains(a, StringComparer.Ordinal));

    /// <summary>
    /// Directory containing the running executable (equivalent to frozen sys.executable parent).
    /// </summary>
    public static string AppDir { get; } = ResolveAppDir();

    /// <summary>
    /// Per-user local app data folder: %LOCALAPPDATA%\EFL_NEXUS
    /// </summary>
    public static string LocalAppDataDir { get; } = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData)
            is { Length: > 0 } lad ? lad : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "AppData", "Local"),
        "EFL_NEXUS");

    private static string ResolveAppDir()
    {
        var baseDir = AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        if (!string.IsNullOrWhiteSpace(baseDir))
            return baseDir;
        var entry = Assembly.GetEntryAssembly()?.Location;
        return !string.IsNullOrWhiteSpace(entry)
            ? Path.GetDirectoryName(entry) ?? Environment.CurrentDirectory
            : Environment.CurrentDirectory;
    }

    /// <summary>
    /// Resolves EFL_NEXUS.exe even when launched from dotnet.exe during development.
    /// </summary>
    public static string ResolveAppExecutable()
    {
        var procPath = Environment.ProcessPath;
        if (!string.IsNullOrWhiteSpace(procPath)
            && !string.Equals(Path.GetFileNameWithoutExtension(procPath), "dotnet", StringComparison.OrdinalIgnoreCase)
            && File.Exists(procPath))
        {
            return procPath;
        }

        var beside = Path.Combine(AppDir, "EFL_NEXUS.exe");
        if (File.Exists(beside))
            return beside;

        return procPath ?? beside;
    }

    /// <summary>
    /// Locates bundled read-only assets or sibling tools (e.g., Korber_AuditShip, assets/, credentials.json)
    /// checking AppDir first, then parent development workspace ancestors up to 6 levels.
    /// </summary>
    public static string ResolveResourcePath(string relativePath)
    {
        var direct = Path.Combine(AppDir, relativePath);
        if (File.Exists(direct) || Directory.Exists(direct))
            return direct;

        var dir = new DirectoryInfo(AppDir);
        for (int i = 0; i < 6 && dir?.Parent is not null; i++)
        {
            dir = dir.Parent;
            var candidate = Path.Combine(dir.FullName, relativePath);
            if (File.Exists(candidate) || Directory.Exists(candidate))
                return candidate;
        }
        return direct;
    }

    public static string ReadAppVersion()
    {
        var path = ResolveResourcePath("version.txt");
        if (File.Exists(path))
        {
            try
            {
                var v = File.ReadAllText(path).Trim();
                if (!string.IsNullOrWhiteSpace(v))
                    return v;
            }
            catch { }
        }
        return "1.0.8";
    }

    public static string ReadBuildNumber()
    {
        var path = ResolveResourcePath("build.txt");
        if (File.Exists(path))
        {
            try { return File.ReadAllText(path).Trim(); }
            catch { }
        }
        return "0";
    }
}
