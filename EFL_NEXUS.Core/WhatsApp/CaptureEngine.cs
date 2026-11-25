using System.Text.Json;
using System.Text.Json.Serialization;

namespace EflNexus.Core.WhatsApp;

/// <summary>
/// Browser-independent state transitions and durable message acknowledgements
/// (1:1 parity with CaptureSession &amp; CaptureEngine in whatsapp_monitor.py).
/// </summary>
public sealed class CaptureSession
{
    public string? GroupId { get; private set; }
    public string Name { get; private set; } = "";
    private readonly HashSet<(string Id, string Fingerprint)> _seen = [];

    public static (string Id, string Fingerprint) Key(WhatsAppMessageItem message)
        => (message.Id, WhatsAppGdnParser.ContentFingerprint(message.Text));

    public List<WhatsAppMessageItem> Bind(WhatsAppSnapshot? snapshot, bool importVisible = false)
    {
        if (snapshot is null || !string.IsNullOrEmpty(snapshot.Error) || string.IsNullOrEmpty(snapshot.GroupId))
            throw new InvalidOperationException(snapshot?.Error ?? "No group identity available.");

        GroupId = snapshot.GroupId;
        Name = snapshot.Name;
        _seen.Clear();
        if (!importVisible)
        {
            foreach (var msg in snapshot.Messages)
                _seen.Add(Key(msg));
        }
        return Capture(snapshot);
    }

    public List<WhatsAppMessageItem> Capture(WhatsAppSnapshot? snapshot)
    {
        if (snapshot is null)
            throw new InvalidOperationException("Capture paused: Snapshot unavailable.");
        if (!string.IsNullOrEmpty(snapshot.Error))
            throw new InvalidOperationException($"Capture paused: {snapshot.Error}");
        if (snapshot.GroupId != GroupId)
            throw new InvalidOperationException("Capture paused: return to the selected group, or select a new group in NEXUS.");

        var found = new List<WhatsAppMessageItem>();
        foreach (var msg in snapshot.Messages)
        {
            var key = Key(msg);
            if (!_seen.Contains(key))
                found.Add(msg);
        }
        return found;
    }

    public void Acknowledge(WhatsAppMessageItem message) => _seen.Add(Key(message));
}

public sealed class CaptureCheckpoint
{
    [JsonPropertyName("group_id")]
    public string GroupId { get; set; } = "";

    [JsonPropertyName("message_id")]
    public string MessageId { get; set; } = "";

    [JsonPropertyName("fingerprint")]
    public string Fingerprint { get; set; } = "";
}

public sealed class CaptureEngine(WhatsAppGdnStore store, string runId)
{
    private readonly WhatsAppGdnStore _store = store;
    private readonly string _runId = runId;
    public CaptureSession Session { get; private set; } = new();
    public bool Recovering { get; set; } = true;

    public void Report(string state, string detail = "")
        => _store.Report(_runId, state, detail, _store.Setting("capture_gap", false));

    public void Select(WhatsAppSnapshot? snapshot, bool importVisible = false)
    {
        if (snapshot is null)
            throw new InvalidOperationException("WhatsApp is not ready yet. Wait for the group to load, then select it again.");

        var group = _store.Setting<WhatsAppGroupSetting?>("group", null);
        if (group is not null && !string.IsNullOrEmpty(group.Id) && _store.Setting("enabled", false))
            throw new InvalidOperationException("Pause monitoring before selecting or replacing the group.");

        Session = new CaptureSession();
        Session.Bind(snapshot, importVisible);

        _store.SetSettings(new Dictionary<string, object?>
        {
            ["group"] = new WhatsAppGroupSetting
            {
                Id = snapshot.GroupId,
                Name = snapshot.Name,
                IdentityMethod = snapshot.IdentityMethod
            },
            ["enabled"] = true,
            ["checkpoint"] = null,
            ["capture_gap"] = false,
            ["unclassified_seen"] = Array.Empty<string>()
        });

        Recovering = false;
        Accept(snapshot, baseline: !importVisible);

        using var photos = new WhatsAppGrnStore(_store.FilePath);
        photos.Discover(snapshot, baseline: !importVisible, importVisible: importVisible, recentOnly: true);
        photos.SetSetting("grn_capture_initialized", snapshot.GroupId);
    }

    public void Pause()
    {
        _store.SetSetting("enabled", false);
        Recovering = true;
        Report("Paused", "Monitoring is paused. Resume when ready.");
    }

    public void Resume()
    {
        _store.SetSetting("enabled", true);
        Session = new CaptureSession();
        Recovering = true;
    }

    public void Accept(WhatsAppSnapshot snapshot, bool baseline = false)
    {
        var group = _store.Setting<WhatsAppGroupSetting?>("group", null);
        if (group is null || string.IsNullOrEmpty(group.Id) || snapshot.GroupId != group.Id)
            throw new InvalidOperationException("Group selection required: the open chat does not match the saved group name.");

        _store.ObserveMessages(snapshot);
        if (snapshot.ReplyScanPending)
        {
            Report("Monitoring", "Checking DONE reply links...");
            return;
        }

        var messages = snapshot.Messages;
        var unknownHistory = _store.Setting("unclassified_seen", new List<string>());
        var knownUnknown = new HashSet<string>(unknownHistory, StringComparer.Ordinal);
        var newlyUnknown = new List<string>();
        foreach (var msg in snapshot.Unclassified)
        {
            var fp = WhatsAppGdnParser.ContentFingerprint(msg.Text);
            if (!knownUnknown.Contains(fp) && WhatsAppGdnParser.ParseGdnMessage(msg.Text).Candidate)
            {
                newlyUnknown.Add(fp);
                knownUnknown.Add(fp);
            }
        }
        if (newlyUnknown.Count > 0)
        {
            var updated = unknownHistory.Concat(newlyUnknown).TakeLast(1000).ToList();
            _store.SetSetting("unclassified_seen", updated);
            if (!baseline)
                _store.SetSetting("capture_gap", true);
        }

        if (Recovering)
        {
            Session = new CaptureSession();
            Session.Bind(snapshot, importVisible: true);
            var checkpoint = _store.Setting<CaptureCheckpoint?>("checkpoint", null);
            if (checkpoint is not null && checkpoint.GroupId == group.Id)
            {
                int idx = -1;
                for (int i = 0; i < messages.Count; i++)
                {
                    if (messages[i].Id == checkpoint.MessageId)
                        idx = i;
                }
                if (idx >= 0)
                {
                    bool unchanged = WhatsAppGdnParser.ContentFingerprint(messages[idx].Text) == checkpoint.Fingerprint;
                    int upto = idx + (unchanged ? 1 : 0);
                    for (int i = 0; i < upto; i++)
                        Session.Acknowledge(messages[i]);
                }
                else
                {
                    _store.SetSetting("capture_gap", true);
                }
            }
            else
            {
                _store.SetSetting("capture_gap", true);
            }
            Recovering = false;
        }

        if (baseline)
        {
            foreach (var msg in messages)
                Session.Acknowledge(msg);
        }

        foreach (var msg in Session.Capture(snapshot))
        {
            _store.Add(msg.Text, group.Name, msg.Id, groupId: group.Id, messageTime: msg.MessageTime);
            Session.Acknowledge(msg);
        }

        if (messages.Count > 0)
        {
            var last = messages[^1];
            _store.SetSetting("checkpoint", new CaptureCheckpoint
            {
                GroupId = group.Id,
                MessageId = last.Id,
                Fingerprint = WhatsAppGdnParser.ContentFingerprint(last.Text)
            });
        }

        Report("Monitoring", group.Name);
    }
}
