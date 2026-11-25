using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Windows;
using System.Windows.Interop;
using EflNexus.Core.GrnOcr;
using EflNexus.Core.Infrastructure;
using EflNexus.Core.WhatsApp;
using Microsoft.Data.Sqlite;
using Microsoft.Web.WebView2.Core;

namespace EflNexus.App.Browsers;

public partial class WhatsAppBrowserWindow : Window
{
    private readonly string _dbPath;
    private readonly string _runId;
    private readonly int _parentPid;
    private readonly CancellationTokenSource _cts = new();
    private readonly ConcurrentQueue<(long SourceId, long Token, PhotoCaptureResult Result)> _photoResults = new();

    private WhatsAppGdnStore? _store;
    private WhatsAppGrnStore? _photos;
    private CaptureEngine? _engine;
    private GrnExtractionWorker? _extractionWorker;
    private GrnCloudWorker? _cloudWorker;
    private IntPtr _parentHandle = IntPtr.Zero;
    private bool _loaded;
    private long _nextPhotoToken;
    private Task? _pollTask;

    public WhatsAppBrowserWindow(string dbPath, string runId, int parentPid)
    {
        InitializeComponent();
        _dbPath = dbPath;
        _runId = runId;
        _parentPid = parentPid;

        App.TrySetWindowIcon(this);
        SourceInitialized += OnSourceInitialized;
        Loaded += OnLoaded;
        Closing += OnClosing;
    }

    private void OnSourceInitialized(object? sender, EventArgs e)
    {
        try
        {
            var hwnd = new WindowInteropHelper(this).Handle;
            if (hwnd != IntPtr.Zero)
            {
                const int wsExToolWindow = 0x00000080;
                long ex = Win32Interop.GetWindowLongPtr(hwnd, Win32Interop.GWL_EXSTYLE).ToInt64();
                Win32Interop.SetWindowLongPtr(hwnd, Win32Interop.GWL_EXSTYLE, new IntPtr(ex | wsExToolWindow));
            }
        }
        catch { }
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        try
        {
            if (_parentPid > 0)
            {
                _parentHandle = Win32Interop.OpenProcess(Win32Interop.SYNCHRONIZE, false, (uint)_parentPid);
                if (_parentHandle == IntPtr.Zero)
                    throw new InvalidOperationException("Cannot monitor the parent process lifetime.");
            }

            _store = new WhatsAppGdnStore(_dbPath);
            _photos = new WhatsAppGrnStore(_dbPath);
            _engine = new CaptureEngine(_store, _runId);

            _extractionWorker = new GrnExtractionWorker(_dbPath, _cts.Token);
            _extractionWorker.Start();
            _cloudWorker = new GrnCloudWorker(_dbPath, _cts.Token);
            _cloudWorker.Start();

            var profileDir = Path.Combine(Path.GetDirectoryName(Path.GetFullPath(_dbPath)) ?? ".", "webview_profile");
            Directory.CreateDirectory(profileDir);

            var env = await CoreWebView2Environment.CreateAsync(userDataFolder: profileDir);
            await WebView.EnsureCoreWebView2Async(env);

            WebView.CoreWebView2.Settings.AreHostObjectsAllowed = false;
            WebView.CoreWebView2.Settings.AreDefaultScriptDialogsEnabled = false;
            WebView.CoreWebView2.Settings.IsStatusBarEnabled = false;

            WebView.CoreWebView2.DownloadStarting += (_, args) => args.Cancel = true;
            WebView.CoreWebView2.NewWindowRequested += (_, args) =>
            {
                args.Handled = true;
                if (!string.IsNullOrWhiteSpace(args.Uri) &&
                    Uri.TryCreate(args.Uri, UriKind.Absolute, out var uri) &&
                    (uri.Scheme == Uri.UriSchemeHttp || uri.Scheme == Uri.UriSchemeHttps))
                {
                    try
                    {
                        Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true });
                    }
                    catch { }
                }
            };

            WebView.CoreWebView2.NavigationStarting += (_, args) =>
            {
                if (!string.IsNullOrWhiteSpace(args.Uri) &&
                    args.Uri.StartsWith("file:", StringComparison.OrdinalIgnoreCase))
                {
                    args.Cancel = true;
                    return;
                }
                _loaded = false;
            };

            WebView.CoreWebView2.NavigationCompleted += (_, args) =>
            {
                if (args.IsSuccess || WebView.CoreWebView2.Source.StartsWith("https://web.whatsapp.com", StringComparison.OrdinalIgnoreCase))
                    _loaded = true;
            };

            WebView.CoreWebView2.WebMessageReceived += OnWebMessageReceived;
            WebView.CoreWebView2.Navigate("https://web.whatsapp.com/");

            _pollTask = PollLoopAsync(_cts.Token);
        }
        catch (Exception exc)
        {
            try
            {
                _engine?.Report("Failed", $"WhatsApp helper stopped ({exc.GetType().Name}). Reconnect from NEXUS.");
            }
            catch { }
            Close();
        }
    }

    private void OnWebMessageReceived(object? sender, CoreWebView2WebMessageReceivedEventArgs e)
    {
        try
        {
            var raw = e.TryGetWebMessageAsString();
            if (string.IsNullOrWhiteSpace(raw))
                return;

            using var doc = JsonDocument.Parse(raw);
            var root = doc.RootElement;
            if (!root.TryGetProperty("__nexusPhotoToken", out var tokEl) || !tokEl.TryGetInt64(out var token))
                return;
            if (!root.TryGetProperty("sourceId", out var sidEl) || !sidEl.TryGetInt64(out var sourceId))
                return;

            var result = root.TryGetProperty("result", out var resEl)
                ? JsonSerializer.Deserialize<PhotoCaptureResult>(resEl.GetRawText()) ?? new PhotoCaptureResult { Error = "Photo retrieval failed." }
                : new PhotoCaptureResult { Error = "Photo retrieval failed." };

            _photoResults.Enqueue((sourceId, token, result));
        }
        catch { }
    }

    private async Task ExecuteScriptIgnoreAsync(string script)
    {
        var core = WebView.CoreWebView2;
        if (core is null)
            return;
        try { await core.ExecuteScriptAsync(script); } catch { }
    }

    private async Task<WhatsAppSnapshot?> EvalSnapshotAsync(string? expectedGroup = null, Dictionary<string, Dictionary<string, string>>? knownDone = null)
    {
        try
        {
            var core = WebView.CoreWebView2;
            if (core is null)
                return null;
            var raw = await core.ExecuteScriptAsync(WhatsAppScripts.ReadScript(expectedGroup, knownDone));
            if (string.IsNullOrWhiteSpace(raw) || raw == "null")
                return null;
            return JsonSerializer.Deserialize<WhatsAppSnapshot>(raw);
        }
        catch
        {
            return null;
        }
    }

    private async Task PollLoopAsync(CancellationToken ct)
    {
        var store = _store!;
        var photos = _photos!;
        var engine = _engine!;

        var photoInflight = new Dictionary<long, (long Token, double StartedMono)>();
        long? photoOwnerId = null;
        bool scanRequested = false;
        double lastRestoreMono = 0;
        string? selectionError = null;
        bool? pendingSelectionImportVisible = null;

        try
        {
            while (!ct.IsCancellationRequested)
            {
                if (_parentHandle != IntPtr.Zero && Win32Interop.WaitForSingleObject(_parentHandle, 0) == 0)
                    break;

                foreach (var (action, payload) in store.TakeCommands(_runId))
                {
                    if (action == "shutdown")
                    {
                        engine.Report("Stopping", "Closing the internal WhatsApp browser.");
                        await _cts.CancelAsync();
                        break;
                    }

                    switch (action)
                    {
                        case "pause":
                            engine.Pause();
                            break;
                        case "resume":
                            engine.Resume();
                            break;
                        case "retry_ocr":
                            if (_extractionWorker is null || !_extractionWorker.IsAlive)
                            {
                                _extractionWorker = new GrnExtractionWorker(_dbPath, ct);
                                _extractionWorker.Start();
                            }
                            break;
                        case "retry_cloud":
                            if (_cloudWorker is null || !_cloudWorker.IsAlive)
                            {
                                _cloudWorker = new GrnCloudWorker(_dbPath, ct);
                                _cloudWorker.Start();
                            }
                            break;
                        case "acknowledge_gap":
                            store.SetSetting("capture_gap", false);
                            break;
                        case "reload":
                            _loaded = false;
                            engine.Recovering = true;
                            WebView.CoreWebView2?.Navigate("https://web.whatsapp.com/");
                            break;
                        case "probe" when _loaded && WebView.CoreWebView2 is not null:
                            try
                            {
                                var probeRaw = await WebView.CoreWebView2.ExecuteScriptAsync(WhatsAppScripts.ProbeStructureJs);
                                if (!string.IsNullOrWhiteSpace(probeRaw) && probeRaw != "null")
                                {
                                    using var probeDoc = JsonDocument.Parse(probeRaw);
                                    store.SetSetting("last_probe", probeDoc.RootElement.Clone());
                                }
                            }
                            catch { }
                            break;
                        case "import_photos" when _loaded:
                        {
                            var grp = store.Setting<WhatsAppGroupSetting?>("group", null);
                            var current = await EvalSnapshotAsync(grp?.Id, store.KnownDoneReplies());
                            if (current is not null && !string.IsNullOrEmpty(grp?.Id) && current.GroupId == grp.Id)
                            {
                                if (!string.IsNullOrEmpty(photos.DefaultWarehouse(current.GroupId)))
                                    scanRequested = true;
                                else
                                    store.SetSetting("grn_capture_notice", "Choose and save the default GRN warehouse before scanning photos.");
                            }
                            else
                            {
                                store.SetSetting("grn_capture_notice", "Return to the selected group before importing photos.");
                            }
                            break;
                        }
                        case "select":
                            pendingSelectionImportVisible = payload.ValueKind == JsonValueKind.Object &&
                                                            payload.TryGetProperty("import_visible", out var iv) &&
                                                            iv.ValueKind == JsonValueKind.True;
                            selectionError = null;
                            break;
                    }
                }

                if (ct.IsCancellationRequested)
                    break;

                if (pendingSelectionImportVisible.HasValue && _loaded)
                {
                    var selectionSnapshot = await EvalSnapshotAsync(knownDone: store.KnownDoneReplies());
                    if (selectionSnapshot is null || !selectionSnapshot.ReplyScanPending)
                    {
                        try
                        {
                            engine.Select(selectionSnapshot, pendingSelectionImportVisible.Value);
                        }
                        catch (Exception exc)
                        {
                            selectionError = exc.Message;
                        }
                        pendingSelectionImportVisible = null;
                    }
                }

                if (ct.IsCancellationRequested)
                    break;

                while (_photoResults.TryDequeue(out var item))
                {
                    if (!photoInflight.TryGetValue(item.SourceId, out var flight) || flight.Token != item.Token)
                        continue;

                    try
                    {
                        if (item.Result.Waiting)
                        {
                            photos.CaptureWaiting(item.SourceId, item.Result.Error ?? "Loading original photo.");
                        }
                        else if (!string.IsNullOrEmpty(item.Result.Error) || string.IsNullOrEmpty(item.Result.Data))
                        {
                            photos.CaptureFailed(item.SourceId, item.Result.Error ?? "Photo retrieval failed.");
                        }
                        else
                        {
                            photos.SaveImage(item.SourceId, item.Result.Data);
                        }
                    }
                    catch (Exception exc)
                    {
                        photos.CaptureFailed(item.SourceId, exc.Message);
                    }

                    if (!item.Result.Waiting)
                        photoOwnerId = null;
                    photoInflight.Remove(item.SourceId);
                }

                double monoNow = Environment.TickCount64 / 1000.0;
                foreach (var sid in photoInflight.Where(kv => monoNow - kv.Value.StartedMono > 15.0).Select(kv => kv.Key).ToList())
                {
                    photos.CaptureFailed(sid, "Photo retrieval timed out. Capture will retry.");
                    photoInflight.Remove(sid);
                    photoOwnerId = null;
                }

                WhatsAppSnapshot? snapshot = null;
                var savedGroup = store.Setting<WhatsAppGroupSetting?>("group", null);
                var savedGroupId = savedGroup?.Id ?? "";
                var savedGroupName = savedGroup?.Name ?? "";
                bool enabled = store.Setting("enabled", false);

                if (!_loaded)
                {
                    engine.Report("Starting", "Loading WhatsApp Web...");
                }
                else if (!enabled)
                {
                    if (!string.IsNullOrEmpty(selectionError))
                    {
                        engine.Report("Group selection required", selectionError);
                    }
                    else
                    {
                        engine.Report(
                            !string.IsNullOrEmpty(savedGroupId) ? "Paused" : "Setup required",
                            "Open the Browser tab, sign in, and select the group.");
                    }
                }
                else
                {
                    snapshot = await EvalSnapshotAsync(savedGroupId, store.KnownDoneReplies());
                    if (snapshot is null)
                    {
                        engine.Recovering = true;
                        engine.Report("Reconnecting", "Waiting for a readable WhatsApp page.");
                    }
                    else if (!string.IsNullOrEmpty(snapshot.Error))
                    {
                        engine.Recovering = true;
                        if (Environment.TickCount64 / 1000.0 - lastRestoreMono > 10.0 && !string.IsNullOrEmpty(savedGroupName))
                        {
                            await ExecuteScriptIgnoreAsync(WhatsAppScripts.RestoreGroupScript(savedGroupName));
                            lastRestoreMono = Environment.TickCount64 / 1000.0;
                        }
                        engine.Report(snapshot.State ?? "Group selection required", snapshot.Error);
                    }
                    else if (snapshot.GroupId != savedGroupId)
                    {
                        engine.Recovering = true;
                        if (Environment.TickCount64 / 1000.0 - lastRestoreMono > 10.0 && !string.IsNullOrEmpty(savedGroupName))
                        {
                            await ExecuteScriptIgnoreAsync(WhatsAppScripts.RestoreGroupScript(savedGroupName));
                            lastRestoreMono = Environment.TickCount64 / 1000.0;
                        }
                        engine.Report("Group selection required", "Return to the saved group, or pause to select a replacement.");
                    }
                    else
                    {
                        try
                        {
                            engine.Accept(snapshot);
                            bool initial = photos.Setting("grn_capture_initialized", "") != snapshot.GroupId;
                            (int Eligible, int OutsideWindow, int UnknownTime) recency = (0, 0, 0);

                            if (!snapshot.ReplyScanPending)
                            {
                                recency = photos.Discover(snapshot, baseline: initial, recentOnly: true);
                                await ExecuteScriptIgnoreAsync(WhatsAppScripts.PhotoAckScript(snapshot));
                                if (initial)
                                    photos.SetSetting("grn_capture_initialized", snapshot.GroupId);
                            }

                            var notice = !string.IsNullOrEmpty(snapshot.PhotoNotice)
                                ? snapshot.PhotoNotice
                                : (snapshot.UnclassifiedPhotos.Count > 0
                                    ? "Some photo senders could not be verified as incoming. Check the group for missing photos."
                                    : "");

                            if (!snapshot.ReplyScanPending && recency.UnknownTime > 0)
                            {
                                notice = (string.IsNullOrEmpty(notice) ? "" : notice + " ") +
                                         $"Skipped {recency.UnknownTime} photo(s): received time unavailable or unsupported. Only the last hour is scanned.";
                            }

                            if (store.Setting("grn_capture_notice", "") != notice)
                                store.SetSetting("grn_capture_notice", notice);

                            if (!snapshot.ReplyScanPending)
                            {
                                await ExecuteScriptIgnoreAsync(WhatsAppScripts.FollowLatestJs);
                            }
                        }
                        catch (SqliteException)
                        {
                            engine.Report("Storage error", "Capture is waiting for local inbox storage; requests will be retried.");
                        }
                    }
                }

                savedGroup = store.Setting<WhatsAppGroupSetting?>("group", null);
                savedGroupId = savedGroup?.Id ?? "";
                if (_loaded && photoInflight.Count < 1 && !string.IsNullOrEmpty(savedGroupId))
                {
                    snapshot ??= await EvalSnapshotAsync(savedGroupId, store.KnownDoneReplies());
                    bool valid = snapshot is not null && string.IsNullOrEmpty(snapshot.Error) && snapshot.GroupId == savedGroupId;
                    if (valid && snapshot is not null)
                    {
                        photos.ObserveMessages(snapshot);
                        if (scanRequested && !snapshot.ReplyScanPending)
                        {
                            var recency = photos.Discover(snapshot, importVisible: true, recentOnly: true);
                            await ExecuteScriptIgnoreAsync(WhatsAppScripts.PhotoAckScript(snapshot));
                            photos.SetSettings(new Dictionary<string, object?>
                            {
                                ["grn_capture_initialized"] = snapshot.GroupId,
                                ["grn_scan_status"] = $"Scan complete: {recency.Eligible} photo(s) within the last hour; {recency.OutsideWindow} outside the window and {recency.UnknownTime} with unverified times skipped. Cleared and DONE items stay hidden."
                            });
                            scanRequested = false;
                        }
                    }

                    var visibleIds = new HashSet<string>(StringComparer.Ordinal);
                    if (valid && snapshot is not null && !snapshot.ReplyScanPending)
                    {
                        foreach (var p in snapshot.Photos.Concat(snapshot.UnclassifiedPhotos))
                        {
                            if (!string.IsNullOrEmpty(p.MessageId))
                                visibleIds.Add(p.MessageId);
                        }
                        if (snapshot.VisiblePhotos.Count > 0)
                            visibleIds.IntersectWith(snapshot.VisiblePhotos);
                    }

                    if (photoOwnerId is not null)
                    {
                        var active = photos.GetSource(photoOwnerId.Value);
                        if (active is null || !string.IsNullOrEmpty(active.HiddenReason) ||
                            active.GroupId != savedGroupId || (active.DocumentId is not null && active.CaptureRefresh == 0))
                        {
                            photoOwnerId = null;
                        }
                        else if (!WhatsAppGrnStore.GrnPhotoIsRecent(active.MessageTime))
                        {
                            photos.CaptureWaiting(photoOwnerId.Value, "Outside the last-hour scan window; capture skipped.");
                            photoOwnerId = null;
                        }
                        else if (valid && snapshot is not null && !snapshot.ReplyScanPending && !visibleIds.Contains(active.MessageId))
                        {
                            photos.CaptureWaiting(photoOwnerId.Value, "Photo message is outside the rendered history. Open its message to complete capture.");
                            photoOwnerId = null;
                        }
                    }

                    var pending = photos.PendingCapture(
                        savedGroupId,
                        limit: Math.Max(0, 1 - photoInflight.Count),
                        excludeIds: photoInflight.Keys.ToList(),
                        visibleIds: visibleIds,
                        ownerId: photoOwnerId,
                        recentOnly: true);

                    foreach (var source in pending)
                    {
                        var core = WebView.CoreWebView2;
                        if (core is null)
                            break;

                        photoOwnerId = source.Id;
                        long token = Interlocked.Increment(ref _nextPhotoToken);
                        photoInflight[source.Id] = (token, Environment.TickCount64 / 1000.0);
                        try
                        {
                            var expr = WhatsAppScripts.PhotoReadScript(source.GroupId, source.MessageId, source.PhotoIndex);
                            var wrapper = $$"""
                                (() => {
                                  const __tok = {{token}};
                                  const __sid = {{source.Id}};
                                  try {
                                    Promise.resolve({{expr}}).then(
                                      r => window.chrome.webview.postMessage(JSON.stringify({ __nexusPhotoToken: __tok, sourceId: __sid, result: r })),
                                      e => window.chrome.webview.postMessage(JSON.stringify({ __nexusPhotoToken: __tok, sourceId: __sid, result: { error: String((e && e.message) || e || 'Photo retrieval failed.') } }))
                                    );
                                  } catch (e) {
                                    window.chrome.webview.postMessage(JSON.stringify({ __nexusPhotoToken: __tok, sourceId: __sid, result: { error: String((e && e.message) || e || 'Photo retrieval failed.') } }));
                                  }
                                })()
                                """;
                            _ = core.ExecuteScriptAsync(wrapper);
                        }
                        catch (Exception exc)
                        {
                            photos.CaptureFailed(source.Id, $"Photo retrieval failed ({exc.GetType().Name}). Retry capture.");
                            photoInflight.Remove(source.Id);
                            photoOwnerId = null;
                        }
                    }
                }

                await Task.Delay(500, ct);
            }
        }
        catch (OperationCanceledException) { }
        catch (Exception exc)
        {
            try
            {
                engine.Report("Failed", $"WhatsApp helper stopped ({exc.GetType().Name}). Reconnect from NEXUS.");
            }
            catch { }
        }
        finally
        {
            CloseWindowSafely();
        }
    }

    private void CloseWindowSafely()
    {
        if (!Dispatcher.CheckAccess())
        {
            Dispatcher.BeginInvoke(CloseWindowSafely);
            return;
        }
        if (IsLoaded)
        {
            try { Close(); } catch { }
        }
    }

    private void OnClosing(object? sender, System.ComponentModel.CancelEventArgs e)
    {
        if (!_cts.IsCancellationRequested)
            _cts.Cancel();

        try { WebView.Dispose(); } catch { }

        if (_parentHandle != IntPtr.Zero)
        {
            Win32Interop.CloseHandle(_parentHandle);
            _parentHandle = IntPtr.Zero;
        }

        _store?.Dispose();
        _photos?.Dispose();
    }
}
