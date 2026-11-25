using System.IO;
using System.Text.Json;
using System.Windows;
using EflNexus.Core.Infrastructure;

namespace EflNexus.App.Dialogs;

public static class ReleaseNotesManager
{
    private static ReleaseNotesWindow? _activeWindow;

    private static string StateFilePath => Path.Combine(AppPaths.LocalAppDataDir, "release_notes_state.json");
    private static string CachedNotesFilePath => Path.Combine(AppPaths.LocalAppDataDir, "release_notes.txt");

    public class ReleaseNotesState
    {
        public string? LastSeenVersion { get; set; }
        public bool ShowOnUpdate { get; set; } = true;
    }

    public static bool ShouldShowOnStartup()
    {
        var args = Environment.GetCommandLineArgs();
        if (args.Any(a => string.Equals(a, "--just-updated", StringComparison.OrdinalIgnoreCase)))
        {
            return true;
        }

        var currentVersion = AppPaths.ReadAppVersion();
        var state = LoadState();

        if (!state.ShowOnUpdate)
            return false;

        if (string.IsNullOrWhiteSpace(state.LastSeenVersion))
            return true;

        return !string.Equals(state.LastSeenVersion.Trim().TrimStart('v', 'V'),
                              currentVersion.Trim().TrimStart('v', 'V'),
                              StringComparison.OrdinalIgnoreCase);
    }

    public static ReleaseNotesState LoadState()
    {
        try
        {
            if (File.Exists(StateFilePath))
            {
                var json = File.ReadAllText(StateFilePath);
                var state = JsonSerializer.Deserialize<ReleaseNotesState>(json);
                if (state != null)
                    return state;
            }
        }
        catch { }

        return new ReleaseNotesState();
    }

    public static void MarkVersionSeen(string version, bool showOnUpdate)
    {
        try
        {
            var dir = Path.GetDirectoryName(StateFilePath);
            if (!string.IsNullOrEmpty(dir))
                Directory.CreateDirectory(dir);

            var state = new ReleaseNotesState
            {
                LastSeenVersion = version.Trim().TrimStart('v', 'V'),
                ShowOnUpdate = showOnUpdate
            };

            var json = JsonSerializer.Serialize(state, new JsonSerializerOptions { WriteIndented = true });
            File.WriteAllText(StateFilePath, json);
        }
        catch { }
    }

    public static string LoadReleaseNotes(string version)
    {
        // 1. Check cached release notes from recent GitHub update
        if (File.Exists(CachedNotesFilePath))
        {
            try
            {
                var text = File.ReadAllText(CachedNotesFilePath).Trim();
                if (!string.IsNullOrWhiteSpace(text))
                    return text;
            }
            catch { }
        }

        // 2. Check bundled release_notes.txt
        var bundled = AppPaths.ResolveResourcePath("release_notes.txt");
        if (File.Exists(bundled))
        {
            try
            {
                var text = File.ReadAllText(bundled).Trim();
                if (!string.IsNullOrWhiteSpace(text))
                    return text;
            }
            catch { }
        }

        // 3. Check bundled RELEASE_NOTES.md
        var mdPath = AppPaths.ResolveResourcePath("RELEASE_NOTES.md");
        if (File.Exists(mdPath))
        {
            try
            {
                var text = File.ReadAllText(mdPath).Trim();
                if (!string.IsNullOrWhiteSpace(text))
                    return text;
            }
            catch { }
        }

        // 4. Default fallback
        return $"# EFL NEXUS v{version}\n\n" +
               "• Performance improvements, stability enhancements, and UI updates.\n" +
               "• Check GitHub Releases for full changelog and details:\n" +
               "  https://github.com/akashjay1/EFL_NEXUS/releases";
    }

    public static void SaveDownloadedNotes(string notes)
    {
        if (string.IsNullOrWhiteSpace(notes))
            return;
        try
        {
            Directory.CreateDirectory(AppPaths.LocalAppDataDir);
            File.WriteAllText(CachedNotesFilePath, notes);
        }
        catch { }
    }

    public static void ShowReleaseNotes(Window? owner = null, bool force = false)
    {
        var app = System.Windows.Application.Current;
        if (app == null)
            return;

        app.Dispatcher.Invoke(() =>
        {
            if (_activeWindow != null && _activeWindow.IsLoaded)
            {
                _activeWindow.Activate();
                return;
            }

            var currentVersion = AppPaths.ReadAppVersion();
            var notes = LoadReleaseNotes(currentVersion);
            var isJustUpdated = !force;

            var win = new ReleaseNotesWindow(currentVersion, notes, isJustUpdated: isJustUpdated);
            _activeWindow = win;

            if (owner != null && owner.IsLoaded && owner.IsVisible)
            {
                win.Owner = owner;
                win.WindowStartupLocation = WindowStartupLocation.CenterOwner;
            }
            else
            {
                win.WindowStartupLocation = WindowStartupLocation.CenterScreen;
            }

            win.Closed += (_, _) => _activeWindow = null;
            win.ShowDialog();
        });
    }
}
