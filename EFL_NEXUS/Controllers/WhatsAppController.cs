using System.Diagnostics;
using System.IO;
using System.Windows;
using System.Windows.Threading;
using EflNexus.Core.Infrastructure;
using EflNexus.Core.WhatsApp;
using Microsoft.Data.Sqlite;
using WinForms = System.Windows.Forms;

namespace EflNexus.App.Controllers;

/// <summary>
/// Application-owned WebView2 lifecycle, embedding, and watchdog (1:1 parity with whatsapp_controller.py).
/// </summary>
public sealed class WhatsAppController : IDisposable
{
    public const string BrowserTitle = "EFL NEXUS - WhatsApp Browser";
    private static readonly int[] RetryDelaysSeconds = [2, 5, 15];

    private readonly Dispatcher _dispatcher;
    private readonly List<Action<WhatsAppController>> _listeners = [];

    private Process? _process;
    private IntPtr _hwnd;
    private WinForms.Control? _host;
    private bool _visible;
    private bool _closed;
    private bool _wanted;
    private int _retryIndex;
    private long? _restartAtTicks;
    private long _startedAtTicks;
    private long? _healthySinceTicks;
    private DispatcherTimer? _timer;
    private StreamWriter? _logWriter;
    private (string State, string Detail, long NewCount, long GrnNewCount, bool Gap)? _lastNotice;

    public WhatsAppGrnStore Store { get; }
    public string? RunId { get; private set; }
    public string State { get; private set; }
    public string Detail { get; private set; }
    public long NewCount { get; private set; }
    public long GrnNewCount { get; private set; }
    public bool Gap { get; private set; }

    public event Action<WhatsAppController>? Changed;

    public WhatsAppController(
        Dispatcher dispatcher,
        string? dbPath = null,
        Action<WhatsAppController>? onChange = null,
        bool autostart = true)
    {
        _dispatcher = dispatcher;
        Store = new WhatsAppGrnStore(dbPath);
        if (onChange is not null)
            Changed += onChange;

        State = Store.Setting<WhatsAppGroupSetting?>("group", null) is not null
            ? "Paused"
            : "Setup required";
        Detail = "Open WhatsApp to sign in and choose your GDN group.";
        NewCount = Store.Counts().NewCount;
        GrnNewCount = Store.GrnNewCount();
        Gap = Store.Setting("capture_gap", false);

        if (autostart && Store.Setting("enabled", false) && Store.Setting<WhatsAppGroupSetting?>("group", null) is not null)
            Start();

        _timer = new DispatcherTimer(DispatcherPriority.Normal, _dispatcher)
        {
            Interval = TimeSpan.FromMilliseconds(250)
        };
        _timer.Tick += OnTick;
        _timer.Start();
    }

    public void AddListener(Action<WhatsAppController> listener)
    {
        if (!_listeners.Contains(listener))
            _listeners.Add(listener);
    }

    public void RemoveListener(Action<WhatsAppController> listener)
    {
        _listeners.Remove(listener);
    }

    public void Start()
    {
        if (_closed)
            return;
        _wanted = true;
        if (_process is not null && !_process.HasExited)
            return;
        _retryIndex = 0;
        _restartAtTicks = null;
        Launch();
    }

    private void Launch()
    {
        RunId = Guid.NewGuid().ToString("N");
        _startedAtTicks = Environment.TickCount64;
        _healthySinceTicks = null;
        State = "Starting";
        Detail = "Opening the internal WhatsApp browser...";
        _hwnd = IntPtr.Zero;

        try
        {
            Store.Report(RunId, State, Detail);

            _logWriter?.Dispose();
            var logDir = Path.GetDirectoryName(Path.GetFullPath(Store.FilePath)) ?? AppPaths.LocalAppDataDir;
            Directory.CreateDirectory(logDir);
            var logPath = Path.Combine(logDir, "browser.log");
            var fs = new FileStream(logPath, FileMode.Create, FileAccess.Write, FileShare.ReadWrite);
            _logWriter = new StreamWriter(fs) { AutoFlush = true };

            var exePath = AppPaths.ResolveAppExecutable();
            if (string.IsNullOrWhiteSpace(exePath))
                exePath = Path.Combine(AppContext.BaseDirectory, "EFL_NEXUS.exe");

            var psi = new ProcessStartInfo
            {
                FileName = exePath,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true
            };
            psi.ArgumentList.Add("--whatsapp-browser");
            psi.ArgumentList.Add(Store.FilePath);
            psi.ArgumentList.Add(RunId);
            psi.ArgumentList.Add(Environment.ProcessId.ToString());

            var proc = new Process { StartInfo = psi, EnableRaisingEvents = true };
            proc.OutputDataReceived += (_, e) => WriteLogLine(e.Data);
            proc.ErrorDataReceived += (_, e) => WriteLogLine(e.Data);
            if (!proc.Start())
                throw new IOException("Process failed to start.");

            proc.BeginOutputReadLine();
            proc.BeginErrorReadLine();
            _process = proc;
        }
        catch (Exception exc) when (exc is IOException or SqliteException or InvalidOperationException or System.ComponentModel.Win32Exception)
        {
            _process = null;
            Failed($"Could not launch WhatsApp ({exc.GetType().Name}). Check browser.log and WebView2 installation.");
        }
    }

    private void WriteLogLine(string? line)
    {
        if (line is null) return;
        try
        {
            var writer = _logWriter;
            if (writer is not null)
            {
                lock (writer)
                {
                    writer.WriteLine(line);
                }
            }
        }
        catch { }
    }

    public void SelectGroup(bool importVisible = false)
    {
        if (Store.Setting<WhatsAppGroupSetting?>("group", null) is not null && Store.Setting("enabled", false))
        {
            Detail = "Pause monitoring before selecting or replacing the group.";
            Notify();
            return;
        }
        Start();
        if (!string.IsNullOrEmpty(RunId))
            Store.Command(RunId, "select", new { import_visible = importVisible });
    }

    public void Pause()
    {
        Store.SetSetting("enabled", false);
        if (_process is not null && !_process.HasExited && !string.IsNullOrEmpty(RunId))
            Store.Command(RunId, "pause");
        State = "Paused";
        Detail = "Monitoring is paused until you choose Resume.";
        Notify();
    }

    public void Resume()
    {
        if (Store.Setting<WhatsAppGroupSetting?>("group", null) is null)
        {
            State = "Group selection required";
            Detail = "Sign in, open the group, then choose Use Open Group.";
            Notify();
            return;
        }
        Store.SetSetting("enabled", true);
        Start();
        if (!string.IsNullOrEmpty(RunId))
            Store.Command(RunId, "resume");
    }

    public void Reload()
    {
        Start();
        if (!string.IsNullOrEmpty(RunId))
            Store.Command(RunId, "reload");
    }

    public void AcknowledgeGap()
    {
        Store.SetSetting("capture_gap", false);
        Gap = false;
        if (_process is not null && !_process.HasExited && !string.IsNullOrEmpty(RunId))
            Store.Command(RunId, "acknowledge_gap");
        Notify();
    }

    public void SetHost(WinForms.Control host)
    {
        if (_host is not null && !ReferenceEquals(_host, host))
        {
            _host.Resize -= OnHostResize;
            _host.HandleCreated -= OnHostHandleCreated;
        }
        _host = host;
        host.Resize += OnHostResize;
        host.HandleCreated += OnHostHandleCreated;
        TryEmbed();
    }

    private void OnHostHandleCreated(object? sender, EventArgs e) => TryEmbed();
    private void OnHostResize(object? sender, EventArgs e) => Resize();

    public void SetVisible(bool visible)
    {
        _visible = visible;
        if (_hwnd != IntPtr.Zero)
        {
            Win32Interop.ShowWindow(_hwnd, _visible ? Win32Interop.SW_SHOW : Win32Interop.SW_HIDE);
            if (_visible)
                Resize();
        }
    }

    public void Resize()
    {
        if (_hwnd == IntPtr.Zero || _host is null || _host.IsDisposed)
            return;

        int width = _host.ClientSize.Width;
        int height = _host.ClientSize.Height;
        if (width < 300 || height < 200)
            return;

        Win32Interop.MoveWindow(_hwnd, 0, 0, width, height, true);
    }

    private void TryEmbed()
    {
        if (_process is null || _host is null || _host.IsDisposed || _hwnd != IntPtr.Zero || string.IsNullOrEmpty(RunId))
            return;

        var runtime = Store.Runtime(RunId);
        if (runtime is null || runtime.State is "Starting" or "Failed")
            return;

        var hwnd = Win32Interop.FindWindowByProcessAndTitle(_process.Id, BrowserTitle);
        if (hwnd != IntPtr.Zero)
        {
            if (!_host.IsHandleCreated)
                _ = _host.Handle;
            Win32Interop.AttachChildWindow(hwnd, _host.Handle);
            _hwnd = hwnd;
            Resize();
            SetVisible(_visible);
        }
    }

    private void TerminateProcess()
    {
        if (_process is not null)
        {
            try
            {
                if (!_process.HasExited)
                {
                    _process.CloseMainWindow();
                    if (!_process.WaitForExit(1500))
                    {
                        _process.Kill(true);
                        _process.WaitForExit(2000);
                    }
                }
            }
            catch { }
            finally
            {
                _process.Dispose();
                _process = null;
            }
        }
        _hwnd = IntPtr.Zero;
    }

    private void Failed(string detail)
    {
        TerminateProcess();
        _healthySinceTicks = null;
        if (_wanted && _retryIndex < RetryDelaysSeconds.Length)
        {
            int delay = RetryDelaysSeconds[_retryIndex];
            _retryIndex++;
            _restartAtTicks = Environment.TickCount64 + delay * 1000L;
            State = "Reconnecting";
            Detail = $"{detail} Retrying in {delay}s ({_retryIndex}/3).";
        }
        else
        {
            _restartAtTicks = null;
            State = "Failed";
            Detail = $"{detail} Choose Reconnect to try again.";
        }
    }

    private void Notify()
    {
        var notice = (State, Detail, NewCount, GrnNewCount, Gap);
        if (_lastNotice == notice)
            return;

        _lastNotice = notice;
        Changed?.Invoke(this);
        foreach (var listener in _listeners.ToArray())
        {
            try { listener(this); } catch { }
        }
    }

    private void OnTick(object? sender, EventArgs e)
    {
        if (_closed)
            return;

        if (_timer is not null && _timer.Interval.TotalMilliseconds < 700)
            _timer.Interval = TimeSpan.FromMilliseconds(750);

        try
        {
            NewCount = Store.Counts().NewCount;
            GrnNewCount = Store.GrnNewCount();
            Gap = Store.Setting("capture_gap", false);

            long nowTicks = Environment.TickCount64;
            if (_restartAtTicks.HasValue && nowTicks >= _restartAtTicks.Value)
            {
                _restartAtTicks = null;
                Launch();
            }

            if (_process is not null)
            {
                if (_process.HasExited)
                {
                    Failed("The internal WhatsApp browser closed unexpectedly.");
                }
                else if (!string.IsNullOrEmpty(RunId))
                {
                    var runtime = Store.Runtime(RunId);
                    if (runtime is not null)
                    {
                        State = runtime.State;
                        Detail = runtime.Detail;
                        double nowEpoch = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
                        double age = nowEpoch - runtime.Heartbeat;
                        double grace = State == "Starting" ? 60.0 : 15.0;

                        if (age > grace || (State == "Starting" && (nowTicks - _startedAtTicks) / 1000.0 > 60.0))
                        {
                            Failed("The WhatsApp browser stopped responding.");
                        }
                        else if (State == "Monitoring")
                        {
                            _healthySinceTicks ??= nowTicks;
                            if ((nowTicks - _healthySinceTicks.Value) / 1000.0 >= 60.0)
                                _retryIndex = 0;
                        }
                        else
                        {
                            _healthySinceTicks = null;
                        }
                    }
                    TryEmbed();
                }
            }

            Notify();
        }
        catch (Exception exc) when (exc is IOException or SqliteException or InvalidOperationException)
        {
            State = "Unavailable";
            Detail = $"WhatsApp needs attention ({exc.GetType().Name}). Open the WhatsApp page.";
            Notify();
        }
    }

    public void Shutdown()
    {
        if (_closed)
            return;

        _closed = true;
        _wanted = false;
        if (_timer is not null)
        {
            _timer.Stop();
            _timer.Tick -= OnTick;
            _timer = null;
        }

        try
        {
            if (_process is not null && !_process.HasExited && !string.IsNullOrEmpty(RunId))
            {
                Store.Command(RunId, "shutdown");
                long deadline = Environment.TickCount64 + 5000;
                while (_process is not null && !_process.HasExited && Environment.TickCount64 < deadline)
                {
                    PumpUiEvents();
                    Thread.Sleep(50);
                }
                if (_process is not null && !_process.HasExited)
                    TerminateProcess();
            }
        }
        finally
        {
            if (_process is not null)
                TerminateProcess();

            if (_host is not null)
            {
                _host.Resize -= OnHostResize;
                _host.HandleCreated -= OnHostHandleCreated;
                _host = null;
            }

            Store.Close();
            if (_logWriter is not null)
            {
                try { _logWriter.Dispose(); } catch { }
                _logWriter = null;
            }
            _listeners.Clear();
        }
    }

    private void PumpUiEvents()
    {
        try { WinForms.Application.DoEvents(); } catch { }
        try
        {
            if (!_dispatcher.HasShutdownStarted && !_dispatcher.HasShutdownFinished)
            {
                var frame = new DispatcherFrame();
                _dispatcher.BeginInvoke(
                    DispatcherPriority.Background,
                    new DispatcherOperationCallback(_ => { frame.Continue = false; return null; }),
                    null);
                Dispatcher.PushFrame(frame);
            }
        }
        catch { }
    }

    public void Dispose() => Shutdown();
}
