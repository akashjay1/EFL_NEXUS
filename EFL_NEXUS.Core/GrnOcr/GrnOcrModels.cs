using System.Text.Json.Serialization;

namespace EflNexus.Core.GrnOcr;

public sealed class OcrWord
{
    [JsonPropertyName("text")]
    public string Text { get; set; } = "";

    [JsonPropertyName("confidence")]
    public double? Confidence { get; set; }

    [JsonPropertyName("left")]
    public double Left { get; set; }

    [JsonPropertyName("top")]
    public double Top { get; set; }

    [JsonPropertyName("width")]
    public double Width { get; set; }

    [JsonPropertyName("height")]
    public double Height { get; set; }

    [JsonPropertyName("line")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string[]? Line { get; set; }

    [JsonPropertyName("anchor")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public double[]? Anchor { get; set; }
}

public sealed class OcrEvidence
{
    [JsonPropertyName("source")]
    public string Source { get; set; } = "";

    [JsonPropertyName("value")]
    public string Value { get; set; } = "";

    [JsonPropertyName("confidence")]
    public double? Confidence { get; set; }

    [JsonPropertyName("box")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public List<double>? Box { get; set; }

    [JsonPropertyName("variant")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Variant { get; set; }
}

public sealed class OcrExtractionResult
{
    [JsonPropertyName("gatepass")]
    public string Gatepass { get; set; } = "";

    [JsonPropertyName("ocr_candidates")]
    public List<string> OcrCandidates { get; set; } = [];

    [JsonPropertyName("barcode_candidates")]
    public List<string> BarcodeCandidates { get; set; } = [];

    [JsonPropertyName("ocr_space_candidates")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public List<string>? OcrSpaceCandidates { get; set; }

    [JsonPropertyName("azure_candidates")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public List<string>? AzureCandidates { get; set; }

    [JsonPropertyName("warnings")]
    public List<string> Warnings { get; set; } = [];

    [JsonPropertyName("header_path")]
    public string HeaderPath { get; set; } = "";

    [JsonPropertyName("working_path")]
    public string WorkingPath { get; set; } = "";

    [JsonPropertyName("recognition_source")]
    public string RecognitionSource { get; set; } = "local";

    [JsonPropertyName("recognition_version")]
    public string RecognitionVersion { get; set; } = "grn-header-v2";

    [JsonPropertyName("processing_status")]
    public string ProcessingStatus { get; set; } = "local_complete";

    [JsonPropertyName("evidence")]
    public List<OcrEvidence> Evidence { get; set; } = [];

    [JsonPropertyName("header_box")]
    public List<int>? HeaderBox { get; set; }

    [JsonPropertyName("rotation")]
    public int? Rotation { get; set; }

    [JsonPropertyName("seconds")]
    public double Seconds { get; set; }
}

public sealed class CloudOcrConfig
{
    [JsonPropertyName("enabled")]
    public bool Enabled { get; set; }

    [JsonPropertyName("endpoint")]
    public string Endpoint { get; set; } = "https://api.ocr.space/parse/image";

    [JsonPropertyName("daily_limit")]
    public int DailyLimit { get; set; }
}

public sealed class CloudOcrParsedResult
{
    [JsonPropertyName("ocr_space_candidates")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public List<string>? OcrSpaceCandidates { get; set; }

    [JsonPropertyName("azure_candidates")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public List<string>? AzureCandidates { get; set; }

    [JsonPropertyName("evidence")]
    public List<OcrEvidence> Evidence { get; set; } = [];
}

public sealed class CloudOcrJobRecord
{
    public long Id { get; set; }
    public long DocumentId { get; set; }
    public string ImageHash { get; set; } = "";
    public int Revision { get; set; }
    public string Version { get; set; } = "";
    public string Endpoint { get; set; } = "";
    public string Status { get; set; } = "queued";
    public string OperationUrl { get; set; } = "";
    public string Error { get; set; } = "";
    public double Deadline { get; set; }
    public string Result { get; set; } = "{}";
}
