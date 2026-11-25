using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Threading;
using EflNexus.Core.Infrastructure;
using UserControl = System.Windows.Controls.UserControl;
using WinForms = System.Windows.Forms;

namespace EflNexus.App.Views;

public partial class AuditShipHostView : UserControl
{
    public const string AuditShipRelativePath = @"Korber_AuditShip\KORBER AuditShip.exe";

    private const int SwHide = 0;
    private const int SwShow = 5;
    private const int SwRestore = 9;
    private const uint GwOwner = 4;
    private const int GwlStyle = -16;
    private const int GwlExStyle = -20;

    private const uint WsChild = 0x40000000;
    private const uint WsVisible = 0x10000000;
    private const uint WsPopup = 0x80000000;
    private const uint WsCaption = 0x00C00000;
    private const uint WsThickFrame = 0x00040000;
    private const uint WsSysMenu = 0x00080000;
    private const uint WsMinimizeBox = 0x00020000;
    private const uint WsMaximizeBox = 0x00010000;
    private const uint WsMaximize = 0x01000000;
    private const uint WsIconic = 0x20000000;

    private const uint WsExDlgModalFrame = 0x00000001;
    private const uint WsExToolWindow = 0x00000080;
    private const uint WsExWindowEdge = 0x00000100;
    private const uint WsExClientEdge = 0x00000200;
    private const uint WsExStaticEdge = 0x00020000;
    private const uint WsExAppWindow = 0x00040000;
    private const uint WsExNoActivate = 0x08000000;

    private const uint SwpNoSize = 0x0001;
    private const uint SwpNoMove = 0x0002;
    private const uint SwpNoZOrder = 0x0004;
    private const uint SwpNoActivate = 0x0010;
    private const uint SwpFrameChanged = 0x0020;

    [StructLayout(LayoutKind.Sequential)]
    private struct RECT
    {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    [DllImport("user32.dll")]
    private static extern IntPtr GetWindow(IntPtr hWnd, uint uCmd);

    [DllImport("user32.dll")]
    private static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);

    [DllImport("user32.dll")]
    private static extern IntPtr SetFocus(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern bool ClientToScreen(IntPtr hWnd, ref System.Drawing.Point lpPoint);

    private ConfigStore? _configStore;
    private readonly WinForms.Panel _hostPanel;
    private readonly DispatcherTimer _windowPollTimer;
    private readonly DispatcherTimer _watchdogTimer;
    private readonly DispatcherTimer _processExitTimer;

    private Process? _process;
    private IntPtr _embeddedHwnd = IntPtr.Zero;
    private int _pollAttempts;
    private bool _isViewVisible;
    private bool _closed;

    private Win32Interop.WinEventDelegate? _winEventDelegate;
    private IntPtr _winEventHook = IntPtr.Zero;

    public AuditShipHostView() : this(null)
    {
    }

    public AuditShipHostView(ConfigStore? configStore)
    {
        InitializeComponent();
        _configStore = configStore;

        _hostPanel = new WinForms.Panel
        {
            BackColor = Color.FromArgb(0xFA, 0xF8, 0xF2),
            Dock = WinForms.DockStyle.Fill
        };
        AuditShipHostControl.Child = _hostPanel;

        _windowPollTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(100) };
        _windowPollTimer.Tick += (_, _) => PollWindowTick();

        _watchdogTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(100) };
        _watchdogTimer.Tick += (_, _) => MaintainEmbeddingTick();

        _processExitTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(1000) };
        _processExitTimer.Tick += (_, _) => PollProcessExitTick();
    }

    public void SetConfigStore(ConfigStore? configStore) => _configStore = configStore;

    public void SetWindowVisibility(bool visible)
    {
        _isViewVisible = visible;
        if (_embeddedHwnd == IntPtr.Zero)
        {
            AuditShipHostControl.Visibility = Visibility.Collapsed;
            return;
        }

        if (!Win32Interop.IsWindow(_embeddedHwnd))
        {
            _embeddedHwnd = IntPtr.Zero;
            AuditShipHostControl.Visibility = Visibility.Collapsed;
            return;
        }

        AuditShipHostControl.Visibility = visible ? Visibility.Visible : Visibility.Collapsed;
        Win32Interop.ShowWindow(_embeddedHwnd, visible ? SwShow : SwHide);
        if (visible)
        {
            Dispatcher.BeginInvoke(DispatcherPriority.Loaded, new Action(() => RefreshChrome(_embeddedHwnd)));
        }
    }

    private void OpenAuditShip_Click(object sender, RoutedEventArgs e)
    {
        ShowLoadingOverlay();
        Dispatcher.BeginInvoke(DispatcherPriority.Background, new Action(() =>
        {
            var t = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(100) };
            t.Tick += (_, _) =>
            {
                t.Stop();
                LaunchAuditShip();
            };
            t.Start();
        }));
    }

    private void RetryAuditShip_Click(object sender, RoutedEventArgs e) => LaunchAuditShip();

    private void AuditShipHostControl_SizeChanged(object sender, SizeChangedEventArgs e) => ResizeEmbeddedWindow();

    private static string ResolveAuditShipExecutable()
        => AppPaths.ResolveResourcePath(AuditShipRelativePath);

    private void LaunchAuditShip()
    {
        if (_closed) return;

        if (_process is not null && !_process.HasExited)
        {
            FocusEmbeddedWindow();
            return;
        }

        var exePath = ResolveAuditShipExecutable();
        if (!File.Exists(exePath))
        {
            ShowErrorOverlay(
                "Korber AuditShip is unavailable",
                "The bundled AuditShip executable was not found. Rebuild or reinstall EFL NEXUS with the Korber_AuditShip folder included.");
            return;
        }

        try
        {
            _embeddedHwnd = IntPtr.Zero;
            ShowLoadingOverlay();

            var psi = new ProcessStartInfo
            {
                FileName = exePath,
                WorkingDirectory = Path.GetDirectoryName(exePath) ?? AppPaths.AppDir,
                UseShellExecute = false,
                WindowStyle = ProcessWindowStyle.Hidden
            };

            // AuditShip is a separate bundled executable; keep its runtime environment isolated.
            psi.Environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1";
            if (_configStore is not null)
            {
                var asUser = _configStore.GetAuditshipUser();
                var asPass = _configStore.GetAuditshipPass();
                var asFork = _configStore.GetAuditshipForkId();
                if (!string.IsNullOrEmpty(asUser)) psi.Environment["AUDITSHIP_USER"] = asUser;
                if (!string.IsNullOrEmpty(asPass)) psi.Environment["AUDITSHIP_PASS"] = asPass;
                if (!string.IsNullOrEmpty(asFork)) psi.Environment["AUDITSHIP_FORK_ID"] = asFork;
            }

            _process = Process.Start(psi) ?? throw new InvalidOperationException("Failed to start AuditShip process.");
            _pollAttempts = 0;

            var delayStart = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(350) };
            var launchedProc = _process;
            delayStart.Tick += (_, _) =>
            {
                delayStart.Stop();
                if (!_closed && ReferenceEquals(_process, launchedProc))
                    _windowPollTimer.Start();
            };
            delayStart.Start();
            _processExitTimer.Start();
        }
        catch (Exception ex)
        {
            _process = null;
            ShowErrorOverlay("AuditShip could not start", $"EFL NEXUS could not embed AuditShip. {ex.Message}");
        }
    }

    private static IntPtr FindLargestUnownedWindow(int pid)
    {
        IntPtr best = IntPtr.Zero;
        long bestArea = -1;

        Win32Interop.EnumWindows((hwnd, _) =>
        {
            Win32Interop.GetWindowThreadProcessId(hwnd, out uint ownerPid);
            if (ownerPid != (uint)pid)
                return true;
            if (GetWindow(hwnd, GwOwner) != IntPtr.Zero)
                return true;
            if (GetWindowRect(hwnd, out var rect))
            {
                long area = Math.Max(0, rect.Right - rect.Left) * (long)Math.Max(0, rect.Bottom - rect.Top);
                if (area > bestArea)
                {
                    bestArea = area;
                    best = hwnd;
                }
            }
            return true;
        }, IntPtr.Zero);

        return best;
    }

    private void PollWindowTick()
    {
        if (_closed || _process is null)
        {
            _windowPollTimer.Stop();
            return;
        }
        if (_process.HasExited)
        {
            _windowPollTimer.Stop();
            return;
        }

        var hwnd = FindLargestUnownedWindow(_process.Id);
        if (hwnd != IntPtr.Zero)
        {
            _windowPollTimer.Stop();
            try
            {
                Win32Interop.ShowWindow(hwnd, SwHide);
                EmbedWindow(hwnd);
            }
            catch (Exception ex)
            {
                FailEmbedding(_process, ex.Message);
            }
            return;
        }

        _pollAttempts++;
        if (_pollAttempts >= 200)
        {
            _windowPollTimer.Stop();
            FailEmbedding(_process, "The AuditShip window did not become available within 20 seconds.");
        }
    }

    private void EmbedWindow(IntPtr hwnd)
    {
        if (!_hostPanel.IsHandleCreated)
            _ = _hostPanel.Handle;
        IntPtr hostHwnd = _hostPanel.Handle;
        if (hostHwnd == IntPtr.Zero)
            throw new InvalidOperationException("The AuditShip host panel handle is unavailable.");

        Win32Interop.ShowWindow(hwnd, SwHide);
        ApplyChildChrome(hwnd);

        Win32Interop.SetParent(hwnd, hostHwnd);
        IntPtr actualParent = Win32Interop.GetParent(hwnd);
        if (actualParent != hostHwnd)
        {
            throw new InvalidOperationException(
                $"Windows could not attach the AuditShip window (window={hwnd}, host={hostHwnd}, actual_parent={actualParent}).");
        }

        _embeddedHwnd = hwnd;
        ApplyChildChrome(hwnd);
        HideAllOverlays();
        ResizeEmbeddedWindow();
        SetWindowVisibility(_isViewVisible);
        StartWatchdog();

        foreach (int delayMs in new[] { 250, 700, 1400, 2500, 4000 })
        {
            var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(delayMs) };
            timer.Tick += (_, _) =>
            {
                timer.Stop();
                RefreshChrome(hwnd);
            };
            timer.Start();
        }
    }

    private void RefreshChrome(IntPtr hwnd)
    {
        if (_closed || hwnd != _embeddedHwnd || _process is null)
            return;
        try
        {
            ApplyChildChrome(hwnd);
            ResizeEmbeddedWindow();
        }
        catch { }
    }

    private static void ApplyChildChrome(IntPtr hwnd)
    {
        Win32Interop.ShowWindow(hwnd, SwRestore);

        long style = Win32Interop.GetWindowLongPtr(hwnd, GwlStyle).ToInt64() & 0xFFFFFFFFL;
        style &= ~(long)(WsPopup | WsCaption | WsThickFrame | WsSysMenu | WsMinimizeBox | WsMaximizeBox | WsMaximize | WsIconic);
        style |= WsChild | WsVisible;
        Win32Interop.SetWindowLongPtr(hwnd, GwlStyle, new IntPtr(unchecked((int)(uint)style)));

        long exStyle = Win32Interop.GetWindowLongPtr(hwnd, GwlExStyle).ToInt64() & 0xFFFFFFFFL;
        exStyle &= ~(long)(WsExDlgModalFrame | WsExToolWindow | WsExWindowEdge | WsExClientEdge | WsExStaticEdge | WsExAppWindow | WsExNoActivate);
        Win32Interop.SetWindowLongPtr(hwnd, GwlExStyle, new IntPtr(unchecked((int)(uint)exStyle)));

        Win32Interop.SetWindowPos(
            hwnd, IntPtr.Zero, 0, 0, 0, 0,
            SwpNoSize | SwpNoMove | SwpNoZOrder | SwpNoActivate | SwpFrameChanged);
    }

    private void StartWatchdog()
    {
        if (!_watchdogTimer.IsEnabled)
            _watchdogTimer.Start();
        InstallShowHook();
    }

    private void InstallShowHook()
    {
        if (_winEventHook != IntPtr.Zero || _process is null)
            return;
        try
        {
            _winEventDelegate = OnWinEventShow;
            _winEventHook = Win32Interop.SetWinEventHook(
                Win32Interop.EVENT_OBJECT_SHOW,
                Win32Interop.EVENT_OBJECT_SHOW,
                IntPtr.Zero,
                _winEventDelegate,
                (uint)_process.Id,
                0,
                Win32Interop.WINEVENT_OUTOFCONTEXT);
        }
        catch
        {
            _winEventHook = IntPtr.Zero;
        }
    }

    private void OnWinEventShow(
        IntPtr hWinEventHook,
        uint eventType,
        IntPtr hwnd,
        int idObject,
        int idChild,
        uint dwEventThread,
        uint dwmsEventTime)
    {
        if (hwnd == IntPtr.Zero || hwnd != _embeddedHwnd || !_hostPanel.IsHandleCreated)
            return;

        try
        {
            IntPtr hostHwnd = _hostPanel.Handle;
            if (Win32Interop.GetParent(hwnd) != hostHwnd)
            {
                Win32Interop.ShowWindow(hwnd, SwHide);
                Dispatcher.BeginInvoke(DispatcherPriority.ApplicationIdle, new Action(() => ForceReembed(hwnd)));
            }
        }
        catch { }
    }

    private void TeardownShowHook()
    {
        if (_winEventHook != IntPtr.Zero)
        {
            try { Win32Interop.UnhookWinEvent(_winEventHook); } catch { }
            _winEventHook = IntPtr.Zero;
        }
        _winEventDelegate = null;
    }

    private void ForceReembed(IntPtr hwnd)
    {
        if (_closed || hwnd != _embeddedHwnd || _process is null || !_hostPanel.IsHandleCreated)
            return;
        try
        {
            Win32Interop.ShowWindow(hwnd, SwHide);
            ApplyChildChrome(hwnd);
            Win32Interop.SetParent(hwnd, _hostPanel.Handle);
            ResizeEmbeddedWindow();
            if (_isViewVisible)
            {
                AuditShipHostControl.Visibility = Visibility.Visible;
                Win32Interop.ShowWindow(hwnd, SwShow);
            }
        }
        catch { }
    }

    private void MaintainEmbeddingTick()
    {
        if (_closed || _process is null || _process.HasExited || _embeddedHwnd == IntPtr.Zero || !_hostPanel.IsHandleCreated)
        {
            _watchdogTimer.Stop();
            return;
        }

        try
        {
            if (!Win32Interop.IsWindow(_embeddedHwnd))
            {
                _embeddedHwnd = IntPtr.Zero;
                _watchdogTimer.Stop();
                return;
            }

            IntPtr hostHwnd = _hostPanel.Handle;
            bool reparented = false;
            if (Win32Interop.GetParent(_embeddedHwnd) != hostHwnd)
            {
                Win32Interop.ShowWindow(_embeddedHwnd, SwHide);
                ApplyChildChrome(_embeddedHwnd);
                Win32Interop.SetParent(_embeddedHwnd, hostHwnd);
                reparented = Win32Interop.GetParent(_embeddedHwnd) == hostHwnd;
            }

            const uint chromeStyleMask =
                WsPopup | WsCaption | WsThickFrame | WsSysMenu | WsMinimizeBox | WsMaximizeBox | WsMaximize;
            const uint chromeExStyleMask =
                WsExDlgModalFrame | WsExToolWindow | WsExWindowEdge | WsExClientEdge | WsExStaticEdge | WsExAppWindow | WsExNoActivate;

            long style = Win32Interop.GetWindowLongPtr(_embeddedHwnd, GwlStyle).ToInt64() & 0xFFFFFFFFL;
            long exStyle = Win32Interop.GetWindowLongPtr(_embeddedHwnd, GwlExStyle).ToInt64() & 0xFFFFFFFFL;
            if ((style & WsChild) == 0 || (style & chromeStyleMask) != 0 || (exStyle & chromeExStyleMask) != 0)
                ApplyChildChrome(_embeddedHwnd);

            if (GetWindowRect(_embeddedHwnd, out var rect))
            {
                var pt = new System.Drawing.Point(0, 0);
                ClientToScreen(hostHwnd, ref pt);
                int w = Math.Max(1, _hostPanel.ClientSize.Width);
                int h = Math.Max(1, _hostPanel.ClientSize.Height);
                bool boundsChanged =
                    Math.Abs(rect.Left - pt.X) > 2 ||
                    Math.Abs(rect.Top - pt.Y) > 2 ||
                    Math.Abs((rect.Right - rect.Left) - w) > 2 ||
                    Math.Abs((rect.Bottom - rect.Top) - h) > 2;
                if (boundsChanged)
                    ResizeEmbeddedWindow();
            }

            if (reparented)
                SetWindowVisibility(_isViewVisible);
        }
        catch { }
    }

    private void ResizeEmbeddedWindow()
    {
        if (_embeddedHwnd == IntPtr.Zero || _hostPanel.IsDisposed)
            return;

        try
        {
            int w = Math.Max(1, _hostPanel.ClientSize.Width);
            int h = Math.Max(1, _hostPanel.ClientSize.Height);
            Win32Interop.MoveWindow(_embeddedHwnd, 0, 0, w, h, true);
        }
        catch { }
    }

    private void FocusEmbeddedWindow()
    {
        if (_embeddedHwnd == IntPtr.Zero) return;
        SetWindowVisibility(true);
        try { SetFocus(_embeddedHwnd); } catch { }
    }

    private void FailEmbedding(Process proc, string reason)
    {
        TeardownShowHook();
        _watchdogTimer.Stop();
        _processExitTimer.Stop();
        if (ReferenceEquals(proc, _process))
        {
            try { if (!proc.HasExited) proc.Kill(true); } catch { }
            _process = null;
        }
        _embeddedHwnd = IntPtr.Zero;
        ShowErrorOverlay("AuditShip could not be embedded", $"EFL NEXUS could not attach AuditShip. {reason}");
    }

    private void PollProcessExitTick()
    {
        if (_closed || _process is null)
        {
            _processExitTimer.Stop();
            return;
        }

        if (!_process.HasExited)
            return;

        _processExitTimer.Stop();
        _windowPollTimer.Stop();
        _watchdogTimer.Stop();
        TeardownShowHook();

        int code = _process.ExitCode;
        _process.Dispose();
        _process = null;
        _embeddedHwnd = IntPtr.Zero;

        string detail = code == 0
            ? "AuditShip was closed."
            : $"AuditShip stopped unexpectedly (exit code {code}).";
        ShowErrorOverlay("AuditShip is not running", detail);
    }

    private void ShowLoadingOverlay()
    {
        AuditShipHostControl.Visibility = Visibility.Collapsed;
        LauncherOverlay.Visibility = Visibility.Collapsed;
        ErrorOverlay.Visibility = Visibility.Collapsed;
        LoadingOverlay.Visibility = Visibility.Visible;
    }

    private void ShowErrorOverlay(string title, string detail)
    {
        AuditShipHostControl.Visibility = Visibility.Collapsed;
        LauncherOverlay.Visibility = Visibility.Collapsed;
        LoadingOverlay.Visibility = Visibility.Collapsed;
        ErrorTitleText.Text = title;
        ErrorDetailText.Text = detail;
        ErrorOverlay.Visibility = Visibility.Visible;
    }

    private void HideAllOverlays()
    {
        LauncherOverlay.Visibility = Visibility.Collapsed;
        LoadingOverlay.Visibility = Visibility.Collapsed;
        ErrorOverlay.Visibility = Visibility.Collapsed;
    }

    public void Shutdown()
    {
        if (_closed) return;
        _closed = true;

        _windowPollTimer.Stop();
        _watchdogTimer.Stop();
        _processExitTimer.Stop();
        TeardownShowHook();

        if (_process is not null)
        {
            try
            {
                if (!_process.HasExited)
                    _process.Kill(true);
            }
            catch { }
            finally
            {
                _process.Dispose();
                _process = null;
            }
        }
        _embeddedHwnd = IntPtr.Zero;
    }
}
