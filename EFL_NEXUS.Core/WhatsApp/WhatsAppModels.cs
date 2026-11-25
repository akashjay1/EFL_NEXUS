using System.Text.Json;
using System.Text.Json.Serialization;

namespace EflNexus.Core.WhatsApp;

public sealed class ParsedGdn
{
    public Dictionary<string, string> Fields { get; set; } = new(StringComparer.Ordinal);
    public List<string> Warnings { get; set; } = [];
    public bool Candidate { get; set; }
}

public sealed class GdnRequestRecord
{
    public long Id { get; set; }
    public string Fingerprint { get; set; } = "";
    public string Source { get; set; } = "";
    public string MessageId { get; set; } = "";
    public string ReceivedAt { get; set; } = "";
    public string RawText { get; set; } = "";
    public Dictionary<string, string> Fields { get; set; } = new(StringComparer.Ordinal);
    public List<string> Warnings { get; set; } = [];
    public string Action { get; set; } = "New";
    public string MessageTime { get; set; } = "";
    public string HiddenReason { get; set; } = "";
    public string RunState { get; set; } = "New";
    public string RunId { get; set; } = "";
}

public sealed class GrnSourceRecord
{
    public long Id { get; set; }
    public string GroupId { get; set; } = "";
    public string MessageId { get; set; } = "";
    public int PhotoIndex { get; set; }
    public string Source { get; set; } = "";
    public string Warehouse { get; set; } = "";
    public long? DocumentId { get; set; }
    public int Skipped { get; set; }
    public string CaptureError { get; set; } = "";
    public double NextTry { get; set; }
    public int CaptureRefresh { get; set; }
    public int IncomingVerified { get; set; } = 1;
    public int CaptureAttempts { get; set; }
    public string MessageTime { get; set; } = "";
    public string CapturedAt { get; set; } = "";
    public string HiddenReason { get; set; } = "";
    public double? MessageReceivedAt { get; set; }
}

public sealed class GrnDocumentRecord
{
    public long Id { get; set; }
    public string ImageHash { get; set; } = "";
    public string ImagePath { get; set; } = "";
    public string ReceivedAt { get; set; } = "";
    public string Warehouse { get; set; } = "";
    public string Gatepass { get; set; } = "";
    public string ExtractionJson { get; set; } = "{}";
    public Dictionary<string, JsonElement> Extraction { get; set; } = new(StringComparer.Ordinal);
    public string State { get; set; } = "Pending";
    public string Action { get; set; } = "New";
    public int Reviewed { get; set; }
    public string MessageTime { get; set; } = "";
    public string HiddenReason { get; set; } = "";
    public string RunState { get; set; } = "New";
    public string RunId { get; set; } = "";
    public int OcrRevision { get; set; }
    public string Source { get; set; } = "";
    public long Copies { get; set; }
}

public sealed class MonitorRuntimeInfo
{
    public string RunId { get; set; } = "";
    public double Heartbeat { get; set; }
    public string State { get; set; } = "";
    public string Detail { get; set; } = "";
    public int Gap { get; set; }
}

public sealed class WhatsAppGroupSetting
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("identity_method")]
    public string IdentityMethod { get; set; } = "exact_name";
}

public sealed class WhatsAppMessageItem
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("text")]
    public string Text { get; set; } = "";

    [JsonPropertyName("message_time")]
    public string MessageTime { get; set; } = "";
}

public sealed class WhatsAppPhotoItem
{
    [JsonPropertyName("message_id")]
    public string MessageId { get; set; } = "";

    [JsonPropertyName("index")]
    public int Index { get; set; }

    [JsonPropertyName("message_time")]
    public string MessageTime { get; set; } = "";
}

public sealed class WhatsAppReplyItem
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("text")]
    public string Text { get; set; } = "";

    [JsonPropertyName("message_time")]
    public string MessageTime { get; set; } = "";

    [JsonPropertyName("reply_to")]
    public string? ReplyTo { get; set; }
}

public sealed class WhatsAppSnapshot
{
    [JsonPropertyName("group_id")]
    public string GroupId { get; set; } = "";

    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("identity_method")]
    public string IdentityMethod { get; set; } = "exact_name";

    [JsonPropertyName("error")]
    public string? Error { get; set; }

    [JsonPropertyName("state")]
    public string? State { get; set; }

    [JsonPropertyName("messages")]
    public List<WhatsAppMessageItem> Messages { get; set; } = [];

    [JsonPropertyName("unclassified")]
    public List<WhatsAppMessageItem> Unclassified { get; set; } = [];

    [JsonPropertyName("photos")]
    public List<WhatsAppPhotoItem> Photos { get; set; } = [];

    [JsonPropertyName("unclassifiedPhotos")]
    public List<WhatsAppPhotoItem> UnclassifiedPhotos { get; set; } = [];

    [JsonPropertyName("replies")]
    public List<WhatsAppReplyItem> Replies { get; set; } = [];

    [JsonPropertyName("visible_photos")]
    public List<string> VisiblePhotos { get; set; } = [];

    [JsonPropertyName("photo_notice")]
    public string PhotoNotice { get; set; } = "";

    [JsonPropertyName("photo_observations")]
    public List<JsonElement> PhotoObservations { get; set; } = [];

    [JsonPropertyName("observed_originals")]
    public List<WhatsAppMessageItem> ObservedOriginals { get; set; } = [];

    [JsonPropertyName("unresolved_done")]
    public List<string> UnresolvedDone { get; set; } = [];

    [JsonPropertyName("reply_scan_pending")]
    public bool ReplyScanPending { get; set; }
}

public sealed class PhotoCaptureResult
{
    [JsonPropertyName("error")]
    public string? Error { get; set; }

    [JsonPropertyName("waiting")]
    public bool Waiting { get; set; }

    [JsonPropertyName("data")]
    public string? Data { get; set; }

    [JsonPropertyName("width")]
    public int Width { get; set; }

    [JsonPropertyName("height")]
    public int Height { get; set; }

    [JsonPropertyName("quality")]
    public string? Quality { get; set; }
}

/// <summary>
/// Abstraction allowing WhatsApp GDN/GRN review workflows to inspect or populate Korber lanes
/// without tight circular dependencies on WPF/UI code.
/// </summary>
public interface IKorberLaneTarget
{
    string LaneName { get; }
    bool IsBusy { get; }
    bool IsQueueRunning { get; }
    string WhatsappRunId { get; set; }
    IReadOnlyList<string> AvailableWarehouses { get; }
    bool HasActiveGatepass(string docType, string warehouseId, string clientCode, string gatePassNumber);
    void PrefillGdn(string warehouse, string client, string gatepass, string deliveryLocation, string seal);
    void PrefillGrn(string warehouse, string gatepass);
    void AddToQueue(string docType);
    void SetStatus(string status);
    bool RunFlow(string docType, Action<bool, string>? onComplete = null);
}
