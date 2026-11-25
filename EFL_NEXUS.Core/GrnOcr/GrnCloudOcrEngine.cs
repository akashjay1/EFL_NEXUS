using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using EflNexus.Core.Infrastructure;
using EflNexus.Core.WhatsApp;
using Microsoft.Data.Sqlite;
using OpenCvSharp;

namespace EflNexus.Core.GrnOcr;

/// <summary>
/// Opt-in OCR.space fallback, with compatibility for existing Azure jobs
/// (1:1 parity with grn_cloud_ocr.py).
/// </summary>
public static class GrnCloudOcrEngine
{
    public const string ApiVersion = "2024-11-30";
    public const string CloudVersion = GrnOcrEngine.RecognitionVersion + "-azure-read-1";
    public const string OcrSpaceVersion = GrnOcrEngine.RecognitionVersion + "-ocr-space-engine2-1";
    public const string OcrSpaceEndpoint = "https://api.ocr.space/parse/image";

    public static readonly string[] PendingStates = ["Cloud queued", "Cloud reading"];

    public static string ValidateEndpoint(string value)
    {
        var trimmed = (value ?? "").Trim().TrimEnd('/');
        if (!Uri.TryCreate(trimmed, UriKind.Absolute, out var uri))
            throw new ArgumentException("Enter an HTTPS OCR.space /parse/image API endpoint, not the website homepage.");

        var host = (uri.Host ?? "").ToLowerInvariant();
        if (uri.Scheme == "https"
            && !string.IsNullOrEmpty(host)
            && (host == "api.ocr.space" || host.EndsWith(".ocr.space", StringComparison.Ordinal))
            && string.Equals(uri.AbsolutePath, "/parse/image", StringComparison.OrdinalIgnoreCase)
            && string.IsNullOrEmpty(uri.UserInfo)
            && (uri.IsDefaultPort || uri.Port == 443)
            && string.IsNullOrEmpty(uri.Query)
            && string.IsNullOrEmpty(uri.Fragment))
        {
            return "https://" + host + "/parse/image";
        }

        if (uri.Scheme != "https"
            || string.IsNullOrEmpty(host)
            || !string.IsNullOrEmpty(uri.UserInfo)
            || !(uri.IsDefaultPort || uri.Port == 443)
            || (!string.IsNullOrEmpty(uri.AbsolutePath) && uri.AbsolutePath != "/")
            || !string.IsNullOrEmpty(uri.Query)
            || !string.IsNullOrEmpty(uri.Fragment)
            || !host.EndsWith(".cognitiveservices.azure.com", StringComparison.Ordinal))
        {
            throw new ArgumentException("Enter an HTTPS OCR.space /parse/image API endpoint, not the website homepage.");
        }

        return "https://" + host;
    }

    public static bool IsOcrSpace(string endpoint)
    {
        if (!Uri.TryCreate(endpoint, UriKind.Absolute, out var uri))
            return false;
        var host = (uri.Host ?? "").ToLowerInvariant();
        return host == "ocr.space" || host.EndsWith(".ocr.space", StringComparison.Ordinal);
    }

    public static string RecognitionVersionFor(string endpoint)
        => IsOcrSpace(endpoint) ? OcrSpaceVersion : CloudVersion;

    public static string CredentialTarget(string endpoint)
    {
        var canonical = ValidateEndpoint(endpoint);
        var provider = IsOcrSpace(canonical) ? "OCR.space" : "Azure";
        var hash = Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(canonical)));
        return $"EFL_NEXUS/GRN/{provider}/{hash}";
    }

    public static string LoadCredential(string endpoint)
    {
        var rec = CredentialManager.Read(CredentialTarget(endpoint));
        return rec?.Secret ?? "";
    }

    public static void SaveCredential(string endpoint, string key)
    {
        if (string.IsNullOrWhiteSpace(key))
            throw new ArgumentException("Enter the OCR API key.");
        CredentialManager.Write(CredentialTarget(endpoint), "GRN cloud OCR", key.Trim(), CredentialManager.CredPersistLocalMachine);
    }

    public static CloudOcrConfig CloudSettings(WhatsAppGdnStore store)
    {
        var raw = store.Setting<JsonElement?>("grn_cloud_ocr", null);
        if (raw is null || raw.Value.ValueKind != JsonValueKind.Object)
            return new CloudOcrConfig { Enabled = false, Endpoint = OcrSpaceEndpoint, DailyLimit = 0 };

        var obj = raw.Value;
        string endpoint = obj.TryGetProperty("endpoint", out var epEl) && epEl.ValueKind == JsonValueKind.String
            ? epEl.GetString() ?? OcrSpaceEndpoint
            : OcrSpaceEndpoint;
        bool rawEnabled = obj.TryGetProperty("enabled", out var enEl) && enEl.ValueKind == JsonValueKind.True;
        string provider = obj.TryGetProperty("provider", out var prEl) && prEl.ValueKind == JsonValueKind.String
            ? prEl.GetString() ?? ""
            : "";
        int limit = 0;
        if (obj.TryGetProperty("daily_limit", out var limEl) && limEl.ValueKind == JsonValueKind.Number && limEl.TryGetInt32(out var limVal))
            limit = limVal;

        bool enabled = rawEnabled && (IsOcrSpace(endpoint) || provider == "azure");
        return new CloudOcrConfig
        {
            Enabled = enabled,
            Endpoint = endpoint,
            DailyLimit = limit
        };
    }

    public static void InitializeCloudTables(WhatsAppGrnStore store)
    {
        store.ExecuteNonQuery("""
            CREATE TABLE IF NOT EXISTS grn_cloud_jobs (
                id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL,
                image_hash TEXT NOT NULL, revision INTEGER NOT NULL, version TEXT NOT NULL,
                endpoint TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
                operation_url TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
                deadline REAL NOT NULL DEFAULT 0, result TEXT NOT NULL DEFAULT '{}',
                UNIQUE(document_id,image_hash,revision,version)
            );
            CREATE TABLE IF NOT EXISTS grn_cloud_cache (
                image_hash TEXT NOT NULL, version TEXT NOT NULL, endpoint TEXT NOT NULL,
                result TEXT NOT NULL, PRIMARY KEY(image_hash,version,endpoint)
            );
            CREATE TABLE IF NOT EXISTS grn_cloud_usage (day TEXT PRIMARY KEY, uploads INTEGER NOT NULL);
            """);
    }

    public static int UsageToday(WhatsAppGrnStore store)
    {
        var day = DateTime.Now.Date.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
        return store.ExecuteScalar<int>("SELECT uploads FROM grn_cloud_usage WHERE day=@d", ("@d", day));
    }

    internal static GrnDocumentRecord? EligibleDocumentUnsafe(WhatsAppGrnStore store, long documentId, string imageHash, int revision)
    {
        using var cmd = store.Connection.CreateCommand();
        cmd.CommandText = """
            SELECT * FROM grn_documents WHERE id=@id AND image_hash=@h AND ocr_revision=@rev
            AND hidden_reason='' AND reviewed=0 AND action='New' AND run_state<>'Running'
            AND state IN ('Cloud queued','Cloud reading') AND NOT EXISTS
            (SELECT 1 FROM grn_sources WHERE document_id=grn_documents.id AND capture_refresh=1)
            """;
        cmd.Parameters.AddWithValue("@id", documentId);
        cmd.Parameters.AddWithValue("@h", imageHash);
        cmd.Parameters.AddWithValue("@rev", revision);
        using var r = cmd.ExecuteReader();
        if (!r.Read())
            return null;

        var extJson = r.GetString(r.GetOrdinal("extraction"));
        Dictionary<string, JsonElement> extDict;
        try
        {
            extDict = JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(string.IsNullOrWhiteSpace(extJson) ? "{}" : extJson)
                ?? new(StringComparer.Ordinal);
        }
        catch
        {
            extDict = new(StringComparer.Ordinal);
        }

        return new GrnDocumentRecord
        {
            Id = r.GetInt64(r.GetOrdinal("id")),
            ImageHash = r.GetString(r.GetOrdinal("image_hash")),
            ImagePath = r.GetString(r.GetOrdinal("image_path")),
            ReceivedAt = r.GetString(r.GetOrdinal("received_at")),
            Warehouse = r.GetString(r.GetOrdinal("warehouse")),
            Gatepass = r.GetString(r.GetOrdinal("gatepass")),
            ExtractionJson = extJson,
            Extraction = extDict,
            State = r.GetString(r.GetOrdinal("state")),
            Action = r.GetString(r.GetOrdinal("action")),
            Reviewed = r.GetInt32(r.GetOrdinal("reviewed")),
            MessageTime = r.GetString(r.GetOrdinal("message_time")),
            HiddenReason = r.GetString(r.GetOrdinal("hidden_reason")),
            RunState = r.GetString(r.GetOrdinal("run_state")),
            RunId = r.GetString(r.GetOrdinal("run_id")),
            OcrRevision = r.GetInt32(r.GetOrdinal("ocr_revision"))
        };
    }

    public static bool QueueCloud(WhatsAppGrnStore store, long documentId, string imageHash, int revision)
    {
        var config = CloudSettings(store);
        if (!config.Enabled)
            return false;

        string endpoint;
        try
        {
            endpoint = ValidateEndpoint(config.Endpoint);
            if (config.DailyLimit < 1)
                return false;
        }
        catch (ArgumentException)
        {
            return false;
        }

        var version = RecognitionVersionFor(endpoint);
        var exists = store.ExecuteScalar<long?>(
            "SELECT 1 FROM grn_documents WHERE id=@id AND image_hash=@h AND ocr_revision=@rev AND reviewed=0 AND action='New' AND hidden_reason=''",
            ("@id", documentId), ("@h", imageHash), ("@rev", revision));
        if (exists is null)
            return false;

        int? prevRev = null;
        string? prevStatus = null;
        string? prevOpUrl = null;
        double prevDeadline = 0;

        using (var cmd = store.Connection.CreateCommand())
        {
            cmd.CommandText = "SELECT revision, status, operation_url, deadline FROM grn_cloud_jobs WHERE image_hash=@h AND version=@v AND endpoint=@e ORDER BY id DESC LIMIT 1";
            cmd.Parameters.AddWithValue("@h", imageHash);
            cmd.Parameters.AddWithValue("@v", version);
            cmd.Parameters.AddWithValue("@e", endpoint);
            using var r = cmd.ExecuteReader();
            if (r.Read())
            {
                prevRev = r.GetInt32(0);
                prevStatus = r.GetString(1);
                prevOpUrl = r.GetString(2);
                prevDeadline = r.GetDouble(3);
            }
        }

        store.ExecuteNonQuery(
            "INSERT INTO grn_cloud_jobs(document_id,image_hash,revision,version,endpoint) VALUES(@did,@h,@rev,@v,@e) ON CONFLICT DO NOTHING",
            ("@did", documentId), ("@h", imageHash), ("@rev", revision), ("@v", version), ("@e", endpoint));

        store.ExecuteNonQuery(
            "UPDATE grn_documents SET state='Cloud queued' WHERE id=@did AND image_hash=@h AND ocr_revision=@rev AND reviewed=0 AND action='New' AND hidden_reason=''",
            ("@did", documentId), ("@h", imageHash), ("@rev", revision));

        if (prevRev.HasValue && prevRev.Value != revision)
        {
            if (prevStatus is "uncertain" or "submitting")
            {
                store.ExecuteNonQuery(
                    "UPDATE grn_cloud_jobs SET status='uncertain', error=@err WHERE document_id=@did AND revision=@rev AND version=@v",
                    ("@err", "Previous cloud submission is uncertain. Check provider usage before Retry Cloud."),
                    ("@did", documentId), ("@rev", revision), ("@v", version));
                store.ExecuteNonQuery("UPDATE grn_documents SET state='Ready for review' WHERE id=@did", ("@did", documentId));
                store.ExecuteNonQuery(
                    "INSERT OR REPLACE INTO monitor_settings VALUES('grn_cloud_status', @val)",
                    ("@val", JsonSerializer.Serialize("Previous cloud upload is uncertain. Retry Cloud explicitly to upload again.")));
            }
            else if (!string.IsNullOrEmpty(prevOpUrl) && prevStatus != "complete")
            {
                store.ExecuteNonQuery(
                    "UPDATE grn_cloud_jobs SET status='polling', operation_url=@url, deadline=@dl WHERE document_id=@did AND revision=@rev AND version=@v",
                    ("@url", prevOpUrl), ("@dl", prevDeadline), ("@did", documentId), ("@rev", revision), ("@v", version));
            }
        }
        return true;
    }

    public static byte[] PrepareUpload(GrnDocumentRecord record, int maxBytes = 4 * 1024 * 1024)
    {
        var ext = JsonSerializer.Deserialize<OcrExtractionResult>(record.ExtractionJson) ?? new OcrExtractionResult();
        var path = !string.IsNullOrEmpty(ext.HeaderPath) ? ext.HeaderPath
            : !string.IsNullOrEmpty(ext.WorkingPath) ? ext.WorkingPath
            : record.ImagePath;

        var rawBytes = File.ReadAllBytes(path);
        using var image = Cv2.ImDecode(rawBytes, ImreadModes.Color);
        if (image.Empty())
            throw new InvalidOperationException("Could not open header image for cloud upload.");

        foreach (int quality in new[] { 95, 85, 75 })
        {
            Cv2.ImEncode(".jpg", image, out var jpegBytes, new ImageEncodingParam(ImwriteFlags.JpegQuality, quality));
            if (jpegBytes.Length <= maxBytes)
                return jpegBytes;
        }
        throw new ArgumentException($"Cloud image exceeds the {maxBytes:N0}-byte upload limit. Crop the header or review manually.");
    }

    public static CloudOcrParsedResult ParseAzureResult(JsonElement payload)
    {
        var candidates = new SortedSet<string>(StringComparer.Ordinal);
        var evidence = new List<OcrEvidence>();

        if (!payload.TryGetProperty("analyzeResult", out var ar) ||
            !ar.TryGetProperty("pages", out var pages) ||
            pages.ValueKind != JsonValueKind.Array)
        {
            return new CloudOcrParsedResult { AzureCandidates = [], Evidence = [] };
        }

        foreach (var page in pages.EnumerateArray())
        {
            double width = page.GetProperty("width").GetDouble();
            double height = page.GetProperty("height").GetDouble();
            double angleDeg = page.TryGetProperty("angle", out var angEl) && angEl.ValueKind == JsonValueKind.Number
                ? angEl.GetDouble() : 0.0;
            double angle = angleDeg * Math.PI / 180.0;
            double cosine = Math.Cos(angle);
            double sine = Math.Sin(angle);
            double uprightWidth = Math.Abs(cosine) * width + Math.Abs(sine) * height;
            double uprightHeight = Math.Abs(sine) * width + Math.Abs(cosine) * height;

            var words = new List<OcrWord>();
            if (page.TryGetProperty("words", out var wordsEl) && wordsEl.ValueKind == JsonValueKind.Array)
            {
                foreach (var word in wordsEl.EnumerateArray())
                {
                    if (!word.TryGetProperty("polygon", out var polyEl) || polyEl.ValueKind != JsonValueKind.Array)
                        continue;
                    var poly = polyEl.EnumerateArray().Select(e => e.GetDouble()).ToArray();
                    if (poly.Length != 8)
                        continue;

                    double minX = double.PositiveInfinity, maxX = double.NegativeInfinity;
                    double minY = double.PositiveInfinity, maxY = double.NegativeInfinity;
                    for (int i = 0; i < 8; i += 2)
                    {
                        double x = poly[i];
                        double y = poly[i + 1];
                        double px = cosine * (x - width / 2.0) + sine * (y - height / 2.0) + uprightWidth / 2.0;
                        double py = -sine * (x - width / 2.0) + cosine * (y - height / 2.0) + uprightHeight / 2.0;
                        minX = Math.Min(minX, px);
                        maxX = Math.Max(maxX, px);
                        minY = Math.Min(minY, py);
                        maxY = Math.Max(maxY, py);
                    }

                    string content = word.TryGetProperty("content", out var cEl) && cEl.ValueKind == JsonValueKind.String
                        ? cEl.GetString() ?? "" : "";
                    double conf = word.TryGetProperty("confidence", out var cfEl) && cfEl.ValueKind == JsonValueKind.Number
                        ? cfEl.GetDouble() * 100.0 : 0.0;

                    words.Add(new OcrWord
                    {
                        Text = content,
                        Confidence = conf,
                        Left = minX,
                        Top = minY,
                        Width = maxX - minX,
                        Height = maxY - minY
                    });
                }
            }

            foreach (var word in GrnOcrEngine.HeaderNumberEvidence(words, uprightWidth, uprightHeight))
            {
                candidates.Add(word.Text);
                evidence.Add(new OcrEvidence
                {
                    Source = "Azure",
                    Value = word.Text,
                    Confidence = word.Confidence,
                    Box = [word.Left, word.Top, word.Width, word.Height]
                });
            }
        }

        return new CloudOcrParsedResult
        {
            AzureCandidates = [.. candidates],
            Evidence = evidence
        };
    }

    public static CloudOcrParsedResult ParseOcrSpaceResult(JsonElement payload, int width, int height)
    {
        if (!payload.TryGetProperty("IsErroredOnProcessing", out var errEl)
            || errEl.ValueKind != JsonValueKind.False
            || (payload.TryGetProperty("OCRExitCode", out var exitEl) ? exitEl.ToString() : "") != "1")
        {
            throw new InvalidOperationException("OCR.space could not process this image. Check the API key, service quota and file size, then retry explicitly.");
        }

        if (!payload.TryGetProperty("ParsedResults", out var pagesEl) || pagesEl.ValueKind != JsonValueKind.Array || pagesEl.GetArrayLength() == 0)
            throw new ArgumentException("OCR.space returned no image results. Review manually.");

        var candidates = new SortedSet<string>(StringComparer.Ordinal);
        var evidence = new List<OcrEvidence>();

        foreach (var page in pagesEl.EnumerateArray())
        {
            var parseCode = page.TryGetProperty("FileParseExitCode", out var pCodeEl) ? pCodeEl.ToString() : "";
            if (parseCode != "1")
                throw new InvalidOperationException("OCR.space could not parse the image completely. Review manually or retry explicitly.");

            if (!page.TryGetProperty("TextOverlay", out var overlay) || overlay.ValueKind != JsonValueKind.Object)
                throw new ArgumentException("OCR.space returned no word positions. The GATE PASS header could not be verified.");

            if (!overlay.TryGetProperty("HasOverlay", out var hasOverlayEl) || hasOverlayEl.ValueKind != JsonValueKind.True)
                throw new ArgumentException("OCR.space returned no word positions. The GATE PASS header could not be verified.");

            var words = new List<OcrWord>();
            if (overlay.TryGetProperty("Lines", out var linesEl) && linesEl.ValueKind == JsonValueKind.Array)
            {
                foreach (var line in linesEl.EnumerateArray())
                {
                    if (!line.TryGetProperty("Words", out var wordsArr) || wordsArr.ValueKind != JsonValueKind.Array)
                        continue;
                    foreach (var word in wordsArr.EnumerateArray())
                    {
                        double wLeft = word.GetProperty("Left").GetDouble();
                        double wTop = word.GetProperty("Top").GetDouble();
                        double wWidth = word.GetProperty("Width").GetDouble();
                        double wHeight = word.GetProperty("Height").GetDouble();
                        if (!double.IsFinite(wLeft) || !double.IsFinite(wTop) || !double.IsFinite(wWidth) || !double.IsFinite(wHeight)
                            || wWidth <= 0 || wHeight <= 0)
                        {
                            throw new ArgumentException("OCR.space returned invalid word positions. Review manually.");
                        }

                        words.Add(new OcrWord
                        {
                            Text = word.GetProperty("WordText").GetString() ?? "",
                            Confidence = null,
                            Left = wLeft,
                            Top = wTop,
                            Width = wWidth,
                            Height = wHeight
                        });
                    }
                }
            }

            foreach (int degrees in new[] { 0, 90, 180, 270 })
            {
                double angle = degrees * Math.PI / 180.0;
                double cosine = Math.Cos(angle);
                double sine = Math.Sin(angle);
                double w = Math.Abs(cosine) * width + Math.Abs(sine) * height;
                double h = Math.Abs(sine) * width + Math.Abs(cosine) * height;

                var oriented = new List<OcrWord>(words.Count);
                foreach (var word in words)
                {
                    double x = word.Left, y = word.Top, bw = word.Width, bh = word.Height;
                    (double Px, double Py)[] corners = [(x, y), (x + bw, y), (x, y + bh), (x + bw, y + bh)];
                    double minX = double.PositiveInfinity, maxX = double.NegativeInfinity;
                    double minY = double.PositiveInfinity, maxY = double.NegativeInfinity;
                    foreach (var (px, py) in corners)
                    {
                        double nx = cosine * (px - width / 2.0) + sine * (py - height / 2.0) + w / 2.0;
                        double ny = -sine * (px - width / 2.0) + cosine * (py - height / 2.0) + h / 2.0;
                        minX = Math.Min(minX, nx);
                        maxX = Math.Max(maxX, nx);
                        minY = Math.Min(minY, ny);
                        maxY = Math.Max(maxY, ny);
                    }
                    oriented.Add(new OcrWord
                    {
                        Text = word.Text,
                        Confidence = word.Confidence,
                        Left = minX,
                        Top = minY,
                        Width = maxX - minX,
                        Height = maxY - minY
                    });
                }

                foreach (var word in GrnOcrEngine.HeaderNumberEvidence(oriented, w, h))
                {
                    candidates.Add(word.Text);
                    evidence.Add(new OcrEvidence
                    {
                        Source = "OCR.space",
                        Value = word.Text,
                        Confidence = null,
                        Box = [word.Left, word.Top, word.Width, word.Height]
                    });
                }
            }
        }

        return new CloudOcrParsedResult
        {
            OcrSpaceCandidates = [.. candidates],
            Evidence = evidence
        };
    }

    public static OcrExtractionResult MergeCloudResult(OcrExtractionResult local, CloudOcrParsedResult cloud)
    {
        bool isSpace = cloud.OcrSpaceCandidates is not null;
        string provider = isSpace ? "OCR.space" : "Azure";
        var cloudList = (isSpace ? cloud.OcrSpaceCandidates : cloud.AzureCandidates) ?? [];

        var values = new SortedSet<string>(local.OcrCandidates ?? [], StringComparer.Ordinal);
        values.UnionWith(local.BarcodeCandidates ?? []);
        values.UnionWith(cloudList);

        var mergedWarnings = (local.Warnings ?? []).Select(w => "Local attempt: " + w).ToList();
        if (values.Count > 1)
            mergedWarnings.Add($"Local OCR, barcode or {provider} readings disagree. Enter the number manually.");
        if (cloudList.Count == 0)
            mergedWarnings.Add($"{provider} found no unambiguous number beside the GATE PASS header.");
        if ((cloud.Evidence ?? []).Any(w => w.Confidence.HasValue && w.Confidence.Value < 60))
            mergedWarnings.Add($"Low-confidence {provider} reading; compare every digit with the photo.");
        if (provider == "OCR.space")
            mergedWarnings.Add("OCR.space does not supply word confidence scores. Verify the printed number.");

        var result = new OcrExtractionResult
        {
            Gatepass = values.Count == 1 ? values.First() : "",
            OcrCandidates = local.OcrCandidates ?? [],
            BarcodeCandidates = local.BarcodeCandidates ?? [],
            OcrSpaceCandidates = isSpace ? cloudList : local.OcrSpaceCandidates,
            AzureCandidates = !isSpace ? cloudList : local.AzureCandidates,
            Warnings = mergedWarnings,
            HeaderPath = local.HeaderPath,
            WorkingPath = local.WorkingPath,
            RecognitionSource = (string.IsNullOrEmpty(local.RecognitionSource) ? "local" : local.RecognitionSource) + " + " + provider,
            RecognitionVersion = provider == "OCR.space" ? OcrSpaceVersion : CloudVersion,
            ProcessingStatus = "cloud_complete",
            Evidence = (local.Evidence ?? []).Concat(cloud.Evidence ?? []).ToList(),
            HeaderBox = local.HeaderBox,
            Rotation = local.Rotation,
            Seconds = local.Seconds
        };
        return result;
    }

    public static void RetryCloud(WhatsAppGrnStore store, long recordId)
    {
        var config = CloudSettings(store);
        if (!config.Enabled)
            throw new ArgumentException("Enable cloud OCR in OCR Settings before retrying a cloud request.");

        lock (store.SyncRoot)
        {
            store.RunImmediate(() =>
            {
                long jobId = 0;
                string endpoint = "";
                string status = "";
                string opUrl = "";

                using (var cmd = store.Connection.CreateCommand())
                {
                    cmd.CommandText = """
                        SELECT j.id, j.endpoint, j.status, j.operation_url
                        FROM grn_cloud_jobs j
                        JOIN grn_documents d ON d.id=j.document_id AND d.image_hash=j.image_hash AND d.ocr_revision=j.revision
                        WHERE d.id=@id AND d.hidden_reason='' AND d.reviewed=0 AND d.action='New' AND d.run_state<>'Running'
                        ORDER BY j.id DESC LIMIT 1
                        """;
                    cmd.Parameters.AddWithValue("@id", recordId);
                    using var r = cmd.ExecuteReader();
                    if (r.Read())
                    {
                        jobId = r.GetInt64(0);
                        endpoint = r.GetString(1);
                        status = r.GetString(2);
                        opUrl = r.GetString(3);
                    }
                }

                if (jobId == 0)
                    throw new ArgumentException("No retryable cloud request for this unreviewed photo. Use Retry Extraction after configuring cloud OCR.");
                if (!string.Equals(endpoint, config.Endpoint, StringComparison.Ordinal))
                    throw new ArgumentException("The cloud OCR endpoint changed. Use Retry Extraction for the configured service.");
                if (status is "queued" or "submitting" or "polling")
                    throw new ArgumentException("Cloud OCR is already queued or running for this photo.");
                if (status == "complete")
                    throw new ArgumentException("This cloud result is already cached. Review the number or retry extraction.");

                var nextStatus = string.IsNullOrEmpty(opUrl) ? "queued" : "polling";
                double deadline = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0 + 60.0;
                store.ExecuteNonQuery(
                    "UPDATE grn_cloud_jobs SET status=@st, error='', deadline=@dl WHERE id=@jid",
                    ("@st", nextStatus), ("@dl", deadline), ("@jid", jobId));
                store.ExecuteNonQuery("UPDATE grn_documents SET state='Cloud queued' WHERE id=@did", ("@did", recordId));
            });
        }
    }
}

public sealed class OcrSpaceClient : IDisposable
{
    private readonly string _endpoint;
    private readonly string _apiKey;
    private readonly HttpClient _http;

    public OcrSpaceClient(string endpoint, string key)
    {
        _endpoint = GrnCloudOcrEngine.ValidateEndpoint(endpoint);
        if (!GrnCloudOcrEngine.IsOcrSpace(_endpoint))
            throw new ArgumentException("Choose an OCR.space API endpoint.");
        _apiKey = key;
        var handler = new HttpClientHandler { AllowAutoRedirect = false };
        _http = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(55) };
    }

    public JsonElement Submit(byte[] jpegData)
    {
        using var form = new MultipartFormDataContent();
        var fileContent = new ByteArrayContent(jpegData);
        fileContent.Headers.ContentType = new MediaTypeHeaderValue("image/jpeg");
        form.Add(fileContent, "file", "grn-photo.jpg");
        form.Add(new StringContent("2"), "OCREngine");
        form.Add(new StringContent("true"), "isOverlayRequired");
        form.Add(new StringContent("false"), "detectOrientation");
        form.Add(new StringContent("false"), "scale");
        form.Add(new StringContent("false"), "isCreateSearchablePdf");

        using var req = new HttpRequestMessage(HttpMethod.Post, _endpoint) { Content = form };
        req.Headers.TryAddWithoutValidation("apikey", _apiKey);

        using var resp = _http.Send(req);
        int code = (int)resp.StatusCode;
        if (code >= 500)
            throw new HttpRequestException("OCR.space submission outcome is uncertain.");
        if (code != 200)
        {
            string msg = code switch
            {
                401 => "OCR.space API key is invalid.",
                403 => "OCR.space denied access. Check your API key.",
                429 => "OCR.space rate limit or quota reached. Retry later.",
                413 => "OCR.space rejected the image size.",
                _ => $"OCR.space returned HTTP {code}. Retry explicitly or review manually."
            };
            throw new InvalidOperationException(msg);
        }

        using var stream = resp.Content.ReadAsStream();
        using var doc = JsonDocument.Parse(stream);
        return doc.RootElement.Clone();
    }

    public void Dispose() => _http.Dispose();
}

public sealed class AzureReadClient : IDisposable
{
    private readonly string _endpoint;
    private readonly string _apiKey;
    private readonly HttpClient _http;

    public AzureReadClient(string endpoint, string key)
    {
        _endpoint = GrnCloudOcrEngine.ValidateEndpoint(endpoint);
        _apiKey = key;
        var handler = new HttpClientHandler { AllowAutoRedirect = false };
        _http = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(20) };
    }

    public string ValidateOperationUrl(string value)
    {
        if (!Uri.TryCreate(value, UriKind.Absolute, out var opUri)
            || !Uri.TryCreate(_endpoint, UriKind.Absolute, out var epUri)
            || opUri.Scheme != "https"
            || !string.Equals(opUri.Authority, epUri.Authority, StringComparison.OrdinalIgnoreCase)
            || !opUri.AbsolutePath.StartsWith("/documentintelligence/documentModels/prebuilt-read/analyzeResults/", StringComparison.Ordinal)
            || !string.IsNullOrEmpty(opUri.UserInfo)
            || !string.IsNullOrEmpty(opUri.Fragment))
        {
            throw new ArgumentException("Azure returned an invalid operation address; no credential was sent to it.");
        }
        return value;
    }

    private static void CheckResponse(HttpResponseMessage response, HttpStatusCode expected)
    {
        if (response.StatusCode != expected)
        {
            int code = (int)response.StatusCode;
            string msg = code switch
            {
                401 => "Azure key or resource is invalid.",
                403 => "Azure denied access to this resource.",
                429 => "Azure quota or rate limit reached. Retry later.",
                404 => "Azure resource or operation was not found.",
                _ => $"Azure returned HTTP {code}. Review or retry later."
            };
            throw new InvalidOperationException(msg);
        }
    }

    public string Submit(byte[] imageData)
    {
        var url = $"{_endpoint}/documentintelligence/documentModels/prebuilt-read:analyze?api-version={Uri.EscapeDataString(GrnCloudOcrEngine.ApiVersion)}";
        var bodyJson = JsonSerializer.Serialize(new { base64Source = Convert.ToBase64String(imageData) });

        using var req = new HttpRequestMessage(HttpMethod.Post, url)
        {
            Content = new StringContent(bodyJson, Encoding.UTF8, "application/json")
        };
        req.Headers.TryAddWithoutValidation("Ocp-Apim-Subscription-Key", _apiKey);

        using var resp = _http.Send(req);
        if ((int)resp.StatusCode >= 500)
            throw new HttpRequestException("Azure submission outcome is uncertain.");
        CheckResponse(resp, HttpStatusCode.Accepted);

        var opLocation = resp.Headers.TryGetValues("Operation-Location", out var vals) ? vals.FirstOrDefault() ?? "" : "";
        return ValidateOperationUrl(opLocation);
    }

    public (JsonElement Payload, int DelaySeconds) Poll(string operationUrl, double remainingSeconds = 15.0)
    {
        var validUrl = ValidateOperationUrl(operationUrl);
        using var req = new HttpRequestMessage(HttpMethod.Get, validUrl);
        req.Headers.TryAddWithoutValidation("Ocp-Apim-Subscription-Key", _apiKey);

        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(Math.Clamp(remainingSeconds / 2.0, 1.0, 15.0)));
        using var resp = _http.Send(req, cts.Token);
        CheckResponse(resp, HttpStatusCode.OK);

        int retryAfter = 1;
        if (resp.Headers.TryGetValues("Retry-After", out var raVals)
            && int.TryParse(raVals.FirstOrDefault(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var parsedRa))
        {
            retryAfter = Math.Max(1, parsedRa);
        }

        using var stream = resp.Content.ReadAsStream();
        using var doc = JsonDocument.Parse(stream);
        return (doc.RootElement.Clone(), retryAfter);
    }

    public void Dispose() => _http.Dispose();
}
