using System.Diagnostics;
using System.IO;
using System.Text;
using EflNexus.Core.Infrastructure;

namespace EflNexus.Core.Monitoring;

public enum RejectionOutcome
{
    /// <summary>Stop monitoring for this run; keep the app installed.</summary>
    Stop,
    /// <summary>The credential is unknown to the server; discard it and enroll again.</summary>
    ReRegister
}

public static class DecommissionService
{
    public static bool IsSelfDestructEnabled()
    {
        var v = Environment.GetEnvironmentVariable("EFL_DISABLE_SELF_DESTRUCT") ?? "";
        return !v.Equals("1", StringComparison.OrdinalIgnoreCase) && !v.Equals("true", StringComparison.OrdinalIgnoreCase);
    }

    public static void ShowRevocationDialog()
    {
        const string title = "EFL NEXUS - Device Authorization Revoked";
        const string message =
            "An administrator has requested that EFL NEXUS be removed from this workstation.\n\n" +
            "EFL NEXUS will now close and remove itself from this PC.";
        try
        {
            // MB_ICONERROR (0x10) | MB_SYSTEMMODAL (0x1000) | MB_SETFOREGROUND (0x10000)
            Win32Interop.MessageBoxW(IntPtr.Zero, message, title, 0x10u | 0x1000u | 0x10000u);
        }
        catch { }
    }

    public static void WipeLocalMonitoringData()
    {
        try { MonitoringSecurity.DeleteMachineCredential(); } catch { }
        try { MonitoringSecurity.SetMachineActive(false); } catch { }

        string[] targetDirs =
        [
            Path.Combine(MonitoringSecurity.ProgramDataRoot, "EFL_NEXUS_Monitoring"),
            Path.Combine(Environment.GetEnvironmentVariable("LOCALAPPDATA") ?? "", "EFL_NEXUS", "Monitoring")
        ];

        foreach (var dir in targetDirs)
        {
            if (!Directory.Exists(dir)) continue;
            try
            {
                foreach (var file in Directory.GetFiles(dir))
                {
                    try { File.Delete(file); } catch { }
                }
            }
            catch { }
        }
    }

    private static bool IsDevWorkspaceTree(string dirPath)
    {
        var cur = new DirectoryInfo(Path.GetFullPath(dirPath));
        for (int i = 0; i < 6 && cur is not null; i++)
        {
            if (cur.GetFiles("*.sln").Length > 0 || cur.GetFiles("*.csproj").Length > 0 || File.Exists(Path.Combine(cur.FullName, "main_app.py")))
                return true;
            cur = cur.Parent;
        }
        return false;
    }

    /// <summary>
    /// Called when the cloud rejects this device. A rejection alone never deletes anything:
    /// the app only removes itself when an administrator has explicitly requested uninstall
    /// for this device (device-status says uninstall=true). Any failure here means "do nothing".
    /// </summary>
    public static RejectionOutcome HandleRejection(CloudClient? client, IReadOnlyDictionary<string, string?>? credential)
    {
        if (client is null || credential is null)
            return RejectionOutcome.Stop;
        try
        {
            var status = client.Post("device-status", new { }, credential);
            if (status.TryGetValue("uninstall", out var u) && u.ValueKind == System.Text.Json.JsonValueKind.True)
                TriggerSelfDestruct(reason: "Uninstall requested by administrator");
            return RejectionOutcome.Stop;
        }
        catch (CloudErrorException ex) when (ex.Status == 401)
        {
            // The server no longer knows this credential (device restored/removed by an admin): register again.
            return RejectionOutcome.ReRegister;
        }
        catch
        {
            return RejectionOutcome.Stop;
        }
    }

    public static void TriggerSelfDestruct(string? installDir = null, string reason = "Device revoked by administrator")
    {
        WipeLocalMonitoringData();

        if (!IsSelfDestructEnabled())
            return;

        ShowRevocationDialog();

        var targetDir = installDir ?? AppPaths.AppDir;
        targetDir = Path.GetFullPath(targetDir);

        // Protect source / development checkout tree (mirrors Python running-from-source guard).
        if (IsDevWorkspaceTree(targetDir))
        {
            Environment.Exit(0);
            return;
        }

        var userProfile = Environment.GetEnvironmentVariable("USERPROFILE") ?? "";
        var appData = Environment.GetEnvironmentVariable("APPDATA") ?? "";
        var uninstallerBat = Path.Combine(targetDir, "uninstall.bat");

        string fileName;
        string arguments;
        if (File.Exists(uninstallerBat))
        {
            fileName = "cmd.exe";
            arguments = $"/c start \"\" /min \"{uninstallerBat}\" --revocation";
        }
        else
        {
            string[] cleanupLines =
            [
                "@echo off",
                "timeout /t 2 /nobreak >nul",
                "taskkill /f /im EFL_NEXUS.exe 2>nul",
                "taskkill /f /im updater.exe 2>nul",
                $"del /f /q \"{userProfile}\\Desktop\\EFL NEXUS.lnk\" 2>nul",
                $"del /f /q \"{userProfile}\\OneDrive\\Desktop\\EFL NEXUS.lnk\" 2>nul",
                $"rmdir /s /q \"{appData}\\Microsoft\\Windows\\Start Menu\\Programs\\EFL NEXUS\" 2>nul",
                $"rmdir /s /q \"{targetDir}\" 2>nul",
                "del \"%~f0\" 2>nul"
            ];
            var cleanupFile = Path.Combine(Path.GetTempPath(), $"efl_nexus_uninstall_{Environment.ProcessId}.bat");
            File.WriteAllText(cleanupFile, string.Join("\r\n", cleanupLines), Encoding.ASCII);
            fileName = "cmd.exe";
            arguments = $"/c \"{cleanupFile}\"";
        }

        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = fileName,
                Arguments = arguments,
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden
            });
        }
        catch { }

        Environment.Exit(0);
    }
}
