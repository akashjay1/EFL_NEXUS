using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.Net.WebSockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Windows.Forms;
using SIPSorcery.Net;
using SIPSorceryMedia.Abstractions;
using SIPSorceryMedia.Encoders;

namespace EflNexus.Core.Monitoring;

/// <summary>
/// Real-time WebRTC desktop streamer (VP8 @ ~20 FPS), signalling via the Supabase Realtime
/// channel `realtime:nexus:screen:{device_id}`. Answers only backend-verified view requests
/// and shows <see cref="ViewerBanner"/> on the operator's screen for the whole view.
/// Uses no capture CPU when no admin viewer is connected.
/// </summary>
public sealed class ScreenStreamService : IDisposable
{
    private static readonly string[] StunUrls =
    [
        "stun:stun.l.google.com:19302",
        "stun:stun1.l.google.com:19302",
        "stun:stun2.l.google.com:19302"
    ];

    private static readonly Lazy<ScreenStreamService> Singleton = new(() => new ScreenStreamService());
    public static ScreenStreamService Instance => Singleton.Value;

    private readonly CancellationTokenSource _cts = new();
    private Task? _workerTask;
    private ClientWebSocket? _ws;
    private RTCPeerConnection? _pc;
    private VpxVideoEncoder? _encoder;
    private CancellationTokenSource? _streamCts;
    private Task? _captureTask;
    private string? _deviceId;
    private readonly SemaphoreSlim _wsSendLock = new(1, 1);

    public void Start()
    {
        if (_workerTask is { IsCompleted: false })
            return;
        _workerTask = Task.Run(() => WorkerLoopAsync(_cts.Token), _cts.Token);
    }

    public void Stop()
    {
        _cts.Cancel();
        StopPeerAsync().GetAwaiter().GetResult();
        try { _workerTask?.Wait(2000); } catch { }
    }

    private async Task WorkerLoopAsync(CancellationToken ct)
    {
        double backoffSeconds = 3.0;
        while (!ct.IsCancellationRequested)
        {
            var cred = MonitoringSecurity.LoadMachineCredential();
            if (cred is null
                || !cred.TryGetValue("device_id", out var devId) || string.IsNullOrEmpty(devId)
                || !cred.TryGetValue("key", out var apiKey) || string.IsNullOrEmpty(apiKey))
            {
                await Task.Delay(4000, ct).ConfigureAwait(false);
                continue;
            }

            _deviceId = devId;
            var supabaseUrl = cred.GetValueOrDefault("url") ?? DeviceIdentity.DefaultSupabaseUrl;
            var host = supabaseUrl.Replace("https://", "", StringComparison.OrdinalIgnoreCase)
                                  .Replace("http://", "", StringComparison.OrdinalIgnoreCase)
                                  .TrimEnd('/');
            var wsUri = new Uri($"wss://{host}/realtime/v1/websocket?apikey={Uri.EscapeDataString(apiKey)}&vsn=1.0.0");
            var topic = $"realtime:nexus:screen:{_deviceId}";

            try
            {
                using var ws = new ClientWebSocket();
                ws.Options.KeepAliveInterval = TimeSpan.FromSeconds(20);
                _ws = ws;
                await ws.ConnectAsync(wsUri, ct).ConfigureAwait(false);
                backoffSeconds = 3.0;

                await SendWsJsonAsync(ws, new
                {
                    topic,
                    @event = "phx_join",
                    payload = new { config = new { broadcast = new { self = false } } },
                    @ref = "join_screen"
                }, ct).ConfigureAwait(false);

                using var sessionCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
                var heartbeatTask = HeartbeatLoopAsync(ws, sessionCts.Token);

                var buffer = new byte[64 * 1024];
                while (ws.State == WebSocketState.Open && !ct.IsCancellationRequested)
                {
                    var ms = new System.IO.MemoryStream();
                    WebSocketReceiveResult result;
                    do
                    {
                        result = await ws.ReceiveAsync(buffer, ct).ConfigureAwait(false);
                        if (result.MessageType == WebSocketMessageType.Close)
                            goto Disconnected;
                        ms.Write(buffer, 0, result.Count);
                    } while (!result.EndOfMessage);

                    var text = Encoding.UTF8.GetString(ms.ToArray());
                    await HandleRealtimeMessageAsync(ws, topic, text, ct).ConfigureAwait(false);
                }

            Disconnected:
                sessionCts.Cancel();
                try { await heartbeatTask.ConfigureAwait(false); } catch { }
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                break;
            }
            catch
            {
                // Reconnect with exponential backoff
            }
            finally
            {
                _ws = null;
                await StopPeerAsync().ConfigureAwait(false);
            }

            if (!ct.IsCancellationRequested)
            {
                await Task.Delay(TimeSpan.FromSeconds(backoffSeconds), ct).ConfigureAwait(false);
                backoffSeconds = Math.Min(backoffSeconds * 1.5, 30.0);
            }
        }
    }

    private static async Task HeartbeatLoopAsync(ClientWebSocket ws, CancellationToken ct)
    {
        int count = 1;
        while (!ct.IsCancellationRequested && ws.State == WebSocketState.Open)
        {
            await Task.Delay(25000, ct).ConfigureAwait(false);
            if (ws.State != WebSocketState.Open) break;
            var payload = JsonSerializer.SerializeToUtf8Bytes(new
            {
                topic = "phoenix",
                @event = "heartbeat",
                payload = new { },
                @ref = $"hb_{count++}"
            });
            await ws.SendAsync(payload, WebSocketMessageType.Text, true, ct).ConfigureAwait(false);
        }
    }

    private async Task SendWsJsonAsync(ClientWebSocket ws, object message, CancellationToken ct)
    {
        if (ws.State != WebSocketState.Open) return;
        var bytes = JsonSerializer.SerializeToUtf8Bytes(message);
        await _wsSendLock.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            if (ws.State == WebSocketState.Open)
                await ws.SendAsync(bytes, WebSocketMessageType.Text, true, ct).ConfigureAwait(false);
        }
        finally
        {
            _wsSendLock.Release();
        }
    }

    private Task SendBroadcastAsync(ClientWebSocket ws, string topic, string eventName, object payload, CancellationToken ct)
        => SendWsJsonAsync(ws, new
        {
            topic,
            @event = "broadcast",
            payload = new
            {
                type = "broadcast",
                @event = eventName,
                payload
            },
            @ref = Guid.NewGuid().ToString()
        }, ct);

    private async Task HandleRealtimeMessageAsync(ClientWebSocket ws, string topic, string rawMsg, CancellationToken ct)
    {
        try
        {
            using var doc = JsonDocument.Parse(rawMsg);
            var root = doc.RootElement;
            if (!root.TryGetProperty("event", out var evEl) || evEl.GetString() != "broadcast")
                return;
            if (!root.TryGetProperty("payload", out var outerPayload))
                return;
            var bEvent = outerPayload.TryGetProperty("event", out var beEl) ? beEl.GetString() : null;
            if (!outerPayload.TryGetProperty("payload", out var bData))
                return;

            switch (bEvent)
            {
                case "screen:request_offer":
                    await HandleRequestOfferAsync(ws, topic, bData, ct).ConfigureAwait(false);
                    break;
                case "screen:ice_candidate":
                    HandleRemoteIce(bData);
                    break;
                case "screen:stop_stream":
                    await StopPeerAsync().ConfigureAwait(false);
                    break;
            }
        }
        catch { }
    }

    private static readonly System.Text.RegularExpressions.Regex FingerprintRegex =
        new(@"a=fingerprint:sha-256\s+([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){31})", System.Text.RegularExpressions.RegexOptions.Compiled);

    /// <summary>
    /// The signalling channel is not private, so anyone holding the publishable key could post an offer.
    /// Only answer offers that the backend confirms were started by an MFA administrator for this device,
    /// with the exact DTLS fingerprint found in this offer (single use, 60 s lifetime).
    /// </summary>
    internal static (bool Ok, string Admin, string Reason) VerifyViewRequest(JsonElement data)
    {
        var viewId = data.TryGetProperty("view_id", out var vEl) ? vEl.GetString() : null;
        var sdp = data.TryGetProperty("sdp", out var sEl) ? sEl.GetString() : null;
        if (string.IsNullOrEmpty(viewId) || !Guid.TryParse(viewId, out _) || string.IsNullOrEmpty(sdp))
            return (false, "", "");
        var match = FingerprintRegex.Match(sdp);
        if (!match.Success)
            return (false, "", "");

        var cred = MonitoringSecurity.LoadMachineCredential();
        if (cred is null)
            return (false, "", "");
        try
        {
            using var client = new CloudClient(cred.GetValueOrDefault("url") ?? DeviceIdentity.DefaultSupabaseUrl,
                                               cred.GetValueOrDefault("key") ?? DeviceIdentity.DefaultSupabaseKey);
            var res = client.Post("device-screen-verify", new
            {
                view_id = viewId,
                fingerprint = match.Groups[1].Value.ToUpperInvariant()
            }, cred);
            if (!res.TryGetValue("ok", out var okEl) || okEl.ValueKind != JsonValueKind.True)
                return (false, "", "");
            var admin = res.TryGetValue("admin", out var aEl) ? aEl.GetString() ?? "Administrator" : "Administrator";
            var reason = res.TryGetValue("reason", out var rEl) ? rEl.GetString() ?? "" : "";
            return (true, admin, reason);
        }
        catch
        {
            return (false, "", "");
        }
    }

    private async Task HandleRequestOfferAsync(ClientWebSocket ws, string topic, JsonElement data, CancellationToken ct)
    {
        var verdict = await Task.Run(() => VerifyViewRequest(data), ct).ConfigureAwait(false);
        if (!verdict.Ok)
            return;

        await StopPeerAsync().ConfigureAwait(false);
        ViewerBanner.Show(verdict.Admin, verdict.Reason);

        var config = new RTCConfiguration
        {
            iceServers = StunUrls.Select(u => new RTCIceServer { urls = u }).ToList()
        };
        var pc = new RTCPeerConnection(config);
        var encoder = new VpxVideoEncoder();
        _pc = pc;
        _encoder = encoder;

        var vp8Formats = encoder.SupportedFormats.Where(f => f.Codec == VideoCodecsEnum.VP8).ToList();
        if (vp8Formats.Count == 0) vp8Formats = encoder.SupportedFormats;

        var track = new MediaStreamTrack(vp8Formats, MediaStreamStatusEnum.SendOnly);
        pc.addTrack(track);

        var peerStop = CancellationTokenSource.CreateLinkedTokenSource(ct);
        _streamCts = peerStop;

        pc.onicecandidate += async cand =>
        {
            if (cand is null || ct.IsCancellationRequested) return;
            try
            {
                var candStr = cand.ToString()?.Trim() ?? "";
                if (candStr.StartsWith("a=", StringComparison.OrdinalIgnoreCase))
                    candStr = candStr[2..];

                await SendBroadcastAsync(ws, topic, "screen:ice_candidate", new
                {
                    candidate = candStr,
                    sdpMid = cand.sdpMid ?? "0",
                    sdpMLineIndex = cand.sdpMLineIndex
                }, ct).ConfigureAwait(false);
            }
            catch { }
        };

        pc.onconnectionstatechange += async state =>
        {
            if (state is RTCPeerConnectionState.connected)
            {
                encoder.ForceKeyFrame();
            }
            else if (state is RTCPeerConnectionState.failed or RTCPeerConnectionState.closed)
            {
                await StopPeerAsync().ConfigureAwait(false);
            }
        };

        var sdp = data.GetProperty("sdp").GetString() ?? "";
        var typeStr = data.GetProperty("type").GetString() ?? "offer";
        var sdpType = Enum.TryParse<RTCSdpType>(typeStr, ignoreCase: true, out var parsed) ? parsed : RTCSdpType.offer;

        var setRes = pc.setRemoteDescription(new RTCSessionDescriptionInit { sdp = sdp, type = sdpType });
        if (setRes != SetDescriptionResultEnum.OK)
        {
            await StopPeerAsync().ConfigureAwait(false);
            return;
        }

        var answer = pc.createAnswer(null);
        await pc.setLocalDescription(answer).ConfigureAwait(false);

        for (int i = 0; i < 15 && pc.iceGatheringState != RTCIceGatheringState.complete; i++)
            await Task.Delay(100, ct).ConfigureAwait(false);

        await SendBroadcastAsync(ws, topic, "screen:answer", new
        {
            sdp = pc.localDescription.sdp.ToString(),
            type = pc.localDescription.type.ToString().ToLowerInvariant()
        }, ct).ConfigureAwait(false);

        _captureTask = Task.Run(() => CaptureDesktopLoopAsync(pc, encoder, peerStop.Token), peerStop.Token);
    }

    private void HandleRemoteIce(JsonElement data)
    {
        var pc = _pc;
        if (pc is null) return;
        var candidate = data.TryGetProperty("candidate", out var cEl) ? cEl.GetString() : null;
        if (string.IsNullOrWhiteSpace(candidate)) return;
        try
        {
            pc.addIceCandidate(new RTCIceCandidateInit
            {
                candidate = candidate,
                sdpMid = data.TryGetProperty("sdpMid", out var mEl) ? mEl.GetString() : "0",
                sdpMLineIndex = data.TryGetProperty("sdpMLineIndex", out var idxEl) && idxEl.TryGetInt32(out var idx) ? (ushort)idx : (ushort)0
            });
        }
        catch { }
    }

    private static async Task CaptureDesktopLoopAsync(RTCPeerConnection pc, VpxVideoEncoder encoder, CancellationToken ct)
    {
        const int fps = 20;
        const int frameDelayMs = 1000 / fps;
        const uint rtpDuration = 90000 / fps;

        var bounds = Screen.PrimaryScreen?.Bounds ?? new Rectangle(0, 0, 1280, 720);
        int width = (bounds.Width / 2) * 2;
        int height = (bounds.Height / 2) * 2;
        if (width < 2 || height < 2) { width = 1280; height = 720; }

        using var bmp = new Bitmap(width, height, PixelFormat.Format24bppRgb);
        using var g = Graphics.FromImage(bmp);
        var bgrBytes = new byte[width * height * 3];

        while (!ct.IsCancellationRequested)
        {
            var frameStart = Stopwatch.GetTimestamp();
            try
            {
                if (pc.connectionState == RTCPeerConnectionState.connected)
                {
                    g.CopyFromScreen(bounds.Left, bounds.Top, 0, 0, new Size(width, height), CopyPixelOperation.SourceCopy);
                    var bmpData = bmp.LockBits(new Rectangle(0, 0, width, height), ImageLockMode.ReadOnly, PixelFormat.Format24bppRgb);
                    try
                    {
                        for (int y = 0; y < height; y++)
                            Marshal.Copy(bmpData.Scan0 + y * bmpData.Stride, bgrBytes, y * width * 3, width * 3);
                    }
                    finally
                    {
                        bmp.UnlockBits(bmpData);
                    }

                    var encoded = encoder.EncodeVideo(width, height, bgrBytes, VideoPixelFormatsEnum.Bgr, VideoCodecsEnum.VP8);
                    if (encoded is { Length: > 0 })
                        pc.SendVideo(rtpDuration, encoded);
                }
            }
            catch { }

            var elapsedMs = (int)((Stopwatch.GetTimestamp() - frameStart) * 1000 / Stopwatch.Frequency);
            var wait = Math.Max(5, frameDelayMs - elapsedMs);
            await Task.Delay(wait, ct).ConfigureAwait(false);
        }
    }

    private async Task StopPeerAsync()
    {
        ViewerBanner.Hide();
        try { _streamCts?.Cancel(); } catch { }
        if (_captureTask is not null)
        {
            try { await _captureTask.ConfigureAwait(false); } catch { }
            _captureTask = null;
        }
        try { _pc?.close(); _pc?.Dispose(); } catch { }
        _pc = null;
        try { _encoder?.Dispose(); } catch { }
        _encoder = null;
        _streamCts?.Dispose();
        _streamCts = null;
    }

    public void Dispose()
    {
        Stop();
        _cts.Dispose();
        _wsSendLock.Dispose();
    }
}
