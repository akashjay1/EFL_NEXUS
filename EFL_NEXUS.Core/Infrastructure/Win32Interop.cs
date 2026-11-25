using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32;

namespace EflNexus.Core.Infrastructure;

public static class Win32Interop
{
    public const int GWL_STYLE = -16;
    public const int GWL_EXSTYLE = -20;

    public const uint WS_CHILD = 0x40000000;
    public const uint WS_VISIBLE = 0x10000000;
    public const uint WS_CLIPCHILDREN = 0x02000000;
    public const uint WS_CAPTION = 0x00C00000;
    public const uint WS_THICKFRAME = 0x00040000;
    public const uint WS_SYSMENU = 0x00080000;
    public const uint WS_MINIMIZEBOX = 0x00020000;
    public const uint WS_MAXIMIZEBOX = 0x00010000;
    public const uint WS_POPUP = 0x80000000;
    public const uint WS_MAXIMIZE = 0x01000000;

    public const int SW_HIDE = 0;
    public const int SW_SHOW = 5;
    public const int SW_RESTORE = 9;

    public const uint SWP_NOSIZE = 0x0001;
    public const uint SWP_NOMOVE = 0x0002;
    public const uint SWP_NOZORDER = 0x0004;
    public const uint SWP_NOACTIVATE = 0x0010;
    public const uint SWP_FRAMECHANGED = 0x0020;

    public const uint EVENT_OBJECT_CREATE = 0x8000;
    public const uint EVENT_OBJECT_SHOW = 0x8002;
    public const uint WINEVENT_OUTOFCONTEXT = 0x0000;
    public const int OBJID_WINDOW = 0;

    public const uint SYNCHRONIZE = 0x00100000;

    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    public static extern int SetCurrentProcessExplicitAppUserModelID(string appId);

    [DllImport("shell32.dll")]
    public static extern bool IsUserAnAdmin();

    public delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr lParam);
    public delegate void WinEventDelegate(
        IntPtr hWinEventHook, uint eventType, IntPtr hwnd, int idObject, int idChild, uint dwEventThread, uint dwmsEventTime);

    [DllImport("user32.dll")]
    public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowTextW(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowTextLengthW(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool IsWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern IntPtr SetParent(IntPtr hWndChild, IntPtr hWndNewParent);

    [DllImport("user32.dll")]
    public static extern IntPtr GetParent(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll")]
    public static extern bool MoveWindow(IntPtr hWnd, int x, int y, int nWidth, int nHeight, bool bRepaint);

    [DllImport("user32.dll")]
    public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int x, int y, int cx, int cy, uint uFlags);

    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")]
    public static extern IntPtr GetWindowLongPtr(IntPtr hWnd, int nIndex);

    [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW")]
    public static extern IntPtr SetWindowLongPtr(IntPtr hWnd, int nIndex, IntPtr dwNewLong);

    [DllImport("user32.dll")]
    public static extern IntPtr SetWinEventHook(
        uint eventMin, uint eventMax, IntPtr hmodWinEventProc, WinEventDelegate lpfnWinEventProc,
        uint idProcess, uint idThread, uint dwFlags);

    [DllImport("user32.dll")]
    public static extern bool UnhookWinEvent(IntPtr hWinEventHook);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int MessageBoxW(IntPtr hWnd, string text, string caption, uint type);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern IntPtr OpenProcess(uint dwDesiredAccess, bool bInheritHandle, uint dwProcessId);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern uint WaitForSingleObject(IntPtr hHandle, uint dwMilliseconds);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool CloseHandle(IntPtr hObject);

    [DllImport("winmm.dll", CharSet = CharSet.Unicode)]
    public static extern int mciSendStringW(string command, StringBuilder? buffer, int bufferSize, IntPtr hwndCallback);

    public static void SetAppUserModelIdSafe(string appId)
    {
        try { SetCurrentProcessExplicitAppUserModelID(appId); } catch { }
    }

    public static string GetWindowTitle(IntPtr hwnd)
    {
        var len = GetWindowTextLengthW(hwnd);
        if (len <= 0) return string.Empty;
        var sb = new StringBuilder(len + 1);
        GetWindowTextW(hwnd, sb, sb.Capacity);
        return sb.ToString();
    }

    public static IntPtr FindWindowByProcessAndTitle(int pid, string exactTitle)
    {
        IntPtr match = IntPtr.Zero;
        EnumWindows((hwnd, _) =>
        {
            GetWindowThreadProcessId(hwnd, out uint owner);
            if (owner == (uint)pid && GetWindowTitle(hwnd) == exactTitle)
            {
                match = hwnd;
                return false;
            }
            return true;
        }, IntPtr.Zero);
        return match;
    }

    public static List<(IntPtr Hwnd, string Title, bool Visible)> FindWindowsForPid(int pid)
    {
        var list = new List<(IntPtr, string, bool)>();
        EnumWindows((hwnd, _) =>
        {
            GetWindowThreadProcessId(hwnd, out uint owner);
            if (owner == (uint)pid)
                list.Add((hwnd, GetWindowTitle(hwnd), IsWindowVisible(hwnd)));
            return true;
        }, IntPtr.Zero);
        return list;
    }

    public static void AttachChildWindow(IntPtr childHwnd, IntPtr hostHwnd)
    {
        ShowWindow(childHwnd, SW_HIDE);
        long chrome = WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_POPUP | WS_MAXIMIZE;
        long style = GetWindowLongPtr(childHwnd, GWL_STYLE).ToInt64();
        SetWindowLongPtr(childHwnd, GWL_STYLE, new IntPtr((style & ~chrome) | WS_CHILD));
        SetWindowLongPtr(childHwnd, GWL_EXSTYLE, IntPtr.Zero);

        long hostStyle = GetWindowLongPtr(hostHwnd, GWL_STYLE).ToInt64();
        SetWindowLongPtr(hostHwnd, GWL_STYLE, new IntPtr(hostStyle | WS_CLIPCHILDREN));

        SetParent(childHwnd, hostHwnd);
        if (GetParent(childHwnd) != hostHwnd)
            throw new IOException("Windows could not attach the child window to NEXUS.");

        SetWindowPos(childHwnd, IntPtr.Zero, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED);
    }

    public static string GetDownloadsFolder()
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders");
            if (key?.GetValue("{374DE290-123F-4565-9164-39C4925E467B}") is string dl && Directory.Exists(dl))
                return dl;
        }
        catch { }
        return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads");
    }

    public static void PlayMediaAlert(string filePath)
    {
        if (!File.Exists(filePath)) return;
        var alias = "efl_alert_snd";
        mciSendStringW($"close {alias}", null, 0, IntPtr.Zero);
        var res = mciSendStringW($"open \"{filePath}\" type mpegvideo alias {alias}", null, 0, IntPtr.Zero);
        if (res == 0)
            mciSendStringW($"play {alias} from 0", null, 0, IntPtr.Zero);
    }

    public static void BeepAsync(int frequency, int durationMs)
    {
        try
        {
            Console.Beep(Math.Clamp(frequency, 37, 32767), Math.Max(20, durationMs));
        }
        catch { }
    }

    public static void TerminateExcelProcesses()
    {
        try
        {
            foreach (var proc in Process.GetProcessesByName("EXCEL"))
            {
                try { proc.Kill(true); proc.WaitForExit(1500); } catch { }
            }
        }
        catch { }
    }
}
