using System.Text.Json.Serialization;

namespace EflNexus.Core.PendingJobs;

public sealed class PortalJobRecord
{
    [JsonPropertyName("job_id")]
    public string JobId { get; set; } = "";

    [JsonPropertyName("client")]
    public string Client { get; set; } = "";

    [JsonPropertyName("status")]
    public string Status { get; set; } = "";

    [JsonPropertyName("warehouse")]
    public string Warehouse { get; set; } = "";

    [JsonPropertyName("gatepass")]
    public string Gatepass { get; set; } = "";

    [JsonPropertyName("seal")]
    public string Seal { get; set; } = "";

    [JsonPropertyName("delivery_location")]
    public string DeliveryLocation { get; set; } = "";

    [JsonPropertyName("warf_id")]
    public string WarfId { get; set; } = "";
}

public sealed class PortalResultsPayload
{
    [JsonPropertyName("job_ids")]
    public List<string> JobIds { get; set; } = [];

    [JsonPropertyName("records")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public List<PortalJobRecord>? Records { get; set; }
}

public sealed class PendingCommandPayload
{
    [JsonPropertyName("action")]
    public string Action { get; set; } = "";

    [JsonPropertyName("job_id")]
    public string? JobId { get; set; }

    [JsonPropertyName("gatepass")]
    public string? Gatepass { get; set; }

    [JsonPropertyName("client")]
    public string? Client { get; set; }

    [JsonPropertyName("seconds")]
    public int? Seconds { get; set; }

    [JsonPropertyName("url")]
    public string? Url { get; set; }

    [JsonPropertyName("page_code")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? PageCode { get; set; }

    [JsonPropertyName("report_name")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? ReportName { get; set; }
}

public sealed class SaveDownloadRequest
{
    [JsonPropertyName("filename")]
    public string? Filename { get; set; }

    [JsonPropertyName("data")]
    public string? Data { get; set; }

    [JsonPropertyName("url")]
    public string? Url { get; set; }

    [JsonPropertyName("job_id")]
    public string? JobId { get; set; }

    [JsonPropertyName("gatepass")]
    public string? Gatepass { get; set; }

    [JsonPropertyName("client")]
    public string? Client { get; set; }
}

public sealed class PortalSavedFileResult
{
    [JsonPropertyName("success")]
    public bool Success { get; set; }

    [JsonPropertyName("error")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Error { get; set; }

    [JsonPropertyName("filename")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Filename { get; set; }

    [JsonPropertyName("path")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Path { get; set; }

    [JsonPropertyName("folder")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Folder { get; set; }

    [JsonPropertyName("folder_path")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? FolderPath { get; set; }

    [JsonPropertyName("size")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public long? Size { get; set; }
}

public sealed class DownloadEventPayload
{
    [JsonPropertyName("action")]
    public string Action { get; set; } = "file_downloaded";

    [JsonPropertyName("filename")]
    public string Filename { get; set; } = "";

    [JsonPropertyName("path")]
    public string Path { get; set; } = "";

    [JsonPropertyName("folder")]
    public string Folder { get; set; } = "";

    [JsonPropertyName("folder_path")]
    public string FolderPath { get; set; } = "";

    [JsonPropertyName("size")]
    public long Size { get; set; }

    [JsonPropertyName("time")]
    public double Time { get; set; }

    [JsonPropertyName("job_id")]
    public string JobId { get; set; } = "";

    [JsonPropertyName("gatepass")]
    public string Gatepass { get; set; } = "";

    [JsonPropertyName("client")]
    public string Client { get; set; } = "";
}

public sealed class LoadingHistoryEventPayload
{
    [JsonPropertyName("action")]
    public string Action { get; set; } = "open_loading_history";

    [JsonPropertyName("time")]
    public double Time { get; set; }

    [JsonPropertyName("job_id")]
    public string JobId { get; set; } = "";

    [JsonPropertyName("gatepass")]
    public string Gatepass { get; set; } = "";

    [JsonPropertyName("client")]
    public string Client { get; set; } = "";

    [JsonPropertyName("active_gatepass")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? ActiveGatepass { get; set; }

    [JsonPropertyName("page_code")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? PageCode { get; set; }

    [JsonPropertyName("report_name")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? ReportName { get; set; }
}
