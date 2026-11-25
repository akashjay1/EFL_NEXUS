using System.Globalization;
using System.IO;
using System.Net.Http;
using System.Text.Json;
using EflNexus.Core.WhatsApp;
using OpenCvSharp;

namespace EflNexus.Core.GrnOcr;

/// <summary>
/// Background local GRN extraction worker (1:1 parity with GRNExtractionWorker in whatsapp_grn.py).
/// </summary>
public sealed class GrnExtractionWorker
{
    private readonly string _dbPath;
    private readonly CancellationToken _stopping;
    private Thread? _thread;

    public GrnExtractionWorker(string dbPath, CancellationToken stopping)
    {
        _dbPath = dbPath;
        _stopping = stopping;
    }

    public bool IsAlive => _thread?.IsAlive ?? false;

    public void Start()
    {
        if (_thread is not null)
            return;
        _thread = new Thread(Run)
        {
            Name = "GRN OCR",
            IsBackground = true
        };
        _thread.Start();
    }

    private void Run()
    {
        using var store = new WhatsAppGrnStore(_dbPath);
        try
        {
            store.SetSetting("grn_ocr_status", "Starting local OCR worker");
            lock (store.SyncRoot)
            {
                store.RunImmediate(() => store.ExecuteNonQuery("UPDATE grn_documents SET state='Pending' WHERE state='Extracting'"));
            }

            while (!_stopping.IsCancellationRequested)
            {
                long rowId = 0;
                int ocrRevision = 0;
                string imagePath = "";
                string imageHash = "";

                lock (store.SyncRoot)
                {
                    using var cmd = store.Connection.CreateCommand();
                    cmd.CommandText = "SELECT id, ocr_revision, image_path, image_hash FROM grn_documents WHERE state='Pending' AND hidden_reason='' ORDER BY id LIMIT 1";
                    using var r = cmd.ExecuteReader();
                    if (r.Read())
                    {
                        rowId = r.GetInt64(0);
                        ocrRevision = r.GetInt32(1);
                        imagePath = r.GetString(2);
                        imageHash = r.GetString(3);
                    }
                }

                if (rowId == 0)
                {
                    _stopping.WaitHandle.WaitOne(1000);
                    continue;
                }

                int claimed;
                lock (store.SyncRoot)
                {
                    claimed = store.RunImmediate(() => store.ExecuteNonQuery(
                        "UPDATE grn_documents SET state='Extracting' WHERE id=@id AND ocr_revision=@rev AND state='Pending' AND hidden_reason=''",
                        ("@id", rowId), ("@rev", ocrRevision)));
                }
                if (claimed == 0)
                    continue;

                store.SetSetting("grn_ocr_status", $"Extracting photo {rowId}");

                OcrExtractionResult result;
                string state;
                try
                {
                    var parentDir = Path.GetDirectoryName(Path.GetFullPath(store.FilePath)) ?? ".";
                    var outputDir = Path.Combine(parentDir, "grn_images", imageHash);
                    result = GrnOcrEngine.ExtractGatepass(imagePath, outputDir);
                    state = "Ready for review";
                }
                catch (Exception ex)
                {
                    var msg = ex.Message.Length > 500 ? ex.Message[..500] : ex.Message;
                    result = new OcrExtractionResult
                    {
                        Gatepass = "",
                        Warnings = [$"Extraction failed: {msg}"]
                    };
                    state = "Extraction failed";
                }

                lock (store.SyncRoot)
                {
                    store.RunImmediate(() =>
                    {
                        int changed = store.ExecuteNonQuery(
                            """
                            UPDATE grn_documents SET state=@st, extraction=@ext,
                            gatepass=CASE WHEN reviewed=0 THEN @gp ELSE gatepass END
                            WHERE id=@id AND hidden_reason='' AND image_hash=@h AND ocr_revision=@rev AND state='Extracting'
                            """,
                            ("@st", state),
                            ("@ext", JsonSerializer.Serialize(result)),
                            ("@gp", result.Gatepass),
                            ("@id", rowId),
                            ("@h", imageHash),
                            ("@rev", ocrRevision));

                        if (changed > 0 && (string.IsNullOrEmpty(result.Gatepass) || result.Warnings.Count > 0))
                            GrnCloudOcrEngine.QueueCloud(store, rowId, imageHash, ocrRevision);
                    });
                }

                store.SetSetting("grn_ocr_status", "Local OCR worker ready");
            }
        }
        catch (Exception ex)
        {
            try
            {
                var detail = ex.Message.Length > 200 ? ex.Message[..200] : ex.Message;
                store.SetSetting("grn_ocr_status", $"OCR worker stopped: {ex.GetType().Name}: {detail}. Reconnect WhatsApp to retry.");
            }
            catch { }
        }
    }
}

/// <summary>
/// Background cloud OCR worker for opt-in OCR.space and legacy Azure polling
/// (1:1 parity with GRNCloudWorker in grn_cloud_ocr.py).
/// </summary>
public sealed class GrnCloudWorker
{
    private readonly string _dbPath;
    private readonly CancellationToken _stopping;
    private Thread? _thread;

    public GrnCloudWorker(string dbPath, CancellationToken stopping)
    {
        _dbPath = dbPath;
        _stopping = stopping;
    }

    public bool IsAlive => _thread?.IsAlive ?? false;

    public void Start()
    {
        if (_thread is not null)
            return;
        _thread = new Thread(Run)
        {
            Name = "GRN cloud OCR",
            IsBackground = true
        };
        _thread.Start();
    }

    private static void ReleaseReviewedUnsafe(WhatsAppGrnStore store, CloudOcrJobRecord job)
    {
        store.ExecuteNonQuery(
            """
            UPDATE grn_documents SET state='Ready for review'
            WHERE id=@did AND image_hash=@h AND ocr_revision=@rev AND reviewed=1 AND hidden_reason=''
              AND state IN ('Cloud queued','Cloud reading')
            """,
            ("@did", job.DocumentId), ("@h", job.ImageHash), ("@rev", job.Revision));
    }

    private static void Finish(WhatsAppGrnStore store, CloudOcrJobRecord job, CloudOcrParsedResult cloud)
    {
        lock (store.SyncRoot)
        {
            store.RunImmediate(() =>
            {
                var record = GrnCloudOcrEngine.EligibleDocumentUnsafe(store, job.DocumentId, job.ImageHash, job.Revision);
                if (record is not null)
                {
                    var local = JsonSerializer.Deserialize<OcrExtractionResult>(record.ExtractionJson) ?? new OcrExtractionResult();
                    var merged = GrnCloudOcrEngine.MergeCloudResult(local, cloud);
                    store.ExecuteNonQuery(
                        "UPDATE grn_documents SET state='Ready for review', extraction=@ext, gatepass=@gp WHERE id=@id",
                        ("@ext", JsonSerializer.Serialize(merged)), ("@gp", merged.Gatepass), ("@id", record.Id));
                }
                ReleaseReviewedUnsafe(store, job);
                var cloudJson = JsonSerializer.Serialize(cloud);
                store.ExecuteNonQuery(
                    "UPDATE grn_cloud_jobs SET status='complete', result=@res, error='' WHERE id=@id",
                    ("@res", cloudJson), ("@id", job.Id));
                store.ExecuteNonQuery(
                    "INSERT OR REPLACE INTO grn_cloud_cache VALUES(@h,@v,@e,@res)",
                    ("@h", job.ImageHash), ("@v", job.Version), ("@e", job.Endpoint), ("@res", cloudJson));
            });
        }
    }

    private static void Fail(WhatsAppGrnStore store, CloudOcrJobRecord job, string message, string status = "error")
    {
        lock (store.SyncRoot)
        {
            store.RunImmediate(() =>
            {
                var record = GrnCloudOcrEngine.EligibleDocumentUnsafe(store, job.DocumentId, job.ImageHash, job.Revision);
                if (record is not null)
                {
                    var local = JsonSerializer.Deserialize<OcrExtractionResult>(record.ExtractionJson) ?? new OcrExtractionResult();
                    local.ProcessingStatus = "cloud_" + status;
                    local.Warnings.Add(message);
                    store.ExecuteNonQuery(
                        "UPDATE grn_documents SET state='Ready for review', extraction=@ext WHERE id=@id",
                        ("@ext", JsonSerializer.Serialize(local)), ("@id", record.Id));
                }
                ReleaseReviewedUnsafe(store, job);
                store.ExecuteNonQuery(
                    "UPDATE grn_cloud_jobs SET status=@st, error=@err WHERE id=@id",
                    ("@st", status), ("@err", message), ("@id", job.Id));
            });
        }
        store.SetSetting("grn_cloud_status", message);
    }

    private bool ProcessOne(WhatsAppGrnStore store)
    {
        CloudOcrJobRecord? job = null;
        lock (store.SyncRoot)
        {
            using var cmd = store.Connection.CreateCommand();
            cmd.CommandText = "SELECT id, document_id, image_hash, revision, version, endpoint, status, operation_url, error, deadline, result FROM grn_cloud_jobs WHERE status IN ('queued','polling') ORDER BY id LIMIT 1";
            using var r = cmd.ExecuteReader();
            if (r.Read())
            {
                job = new CloudOcrJobRecord
                {
                    Id = r.GetInt64(0),
                    DocumentId = r.GetInt64(1),
                    ImageHash = r.GetString(2),
                    Revision = r.GetInt32(3),
                    Version = r.GetString(4),
                    Endpoint = r.GetString(5),
                    Status = r.GetString(6),
                    OperationUrl = r.GetString(7),
                    Error = r.GetString(8),
                    Deadline = r.GetDouble(9),
                    Result = r.GetString(10)
                };
            }
        }

        if (job is null)
            return false;

        GrnDocumentRecord? eligible;
        lock (store.SyncRoot)
        {
            eligible = GrnCloudOcrEngine.EligibleDocumentUnsafe(store, job.DocumentId, job.ImageHash, job.Revision);
            if (eligible is null)
            {
                store.RunImmediate(() =>
                {
                    store.ExecuteNonQuery("UPDATE grn_cloud_jobs SET status='cancelled' WHERE id=@id", ("@id", job.Id));
                    ReleaseReviewedUnsafe(store, job);
                });
                return true;
            }
        }

        var config = GrnCloudOcrEngine.CloudSettings(store);
        if (!config.Enabled || !string.Equals(config.Endpoint, job.Endpoint, StringComparison.Ordinal))
        {
            Fail(store, job, "Cloud OCR disabled or resource changed. Review manually or retry extraction.", "paused");
            return true;
        }

        try
        {
            string? cachedJson;
            lock (store.SyncRoot)
            {
                cachedJson = store.ExecuteScalar<string>(
                    "SELECT result FROM grn_cloud_cache WHERE image_hash=@h AND version=@v AND endpoint=@e",
                    ("@h", job.ImageHash), ("@v", job.Version), ("@e", job.Endpoint));
            }
            if (!string.IsNullOrEmpty(cachedJson))
            {
                var cached = JsonSerializer.Deserialize<CloudOcrParsedResult>(cachedJson) ?? new CloudOcrParsedResult();
                Finish(store, job, cached);
                return true;
            }

            var key = GrnCloudOcrEngine.LoadCredential(job.Endpoint);
            if (string.IsNullOrEmpty(key))
                throw new ArgumentException("OCR API key is missing. Open OCR Settings and save the provider key.");

            bool space = GrnCloudOcrEngine.IsOcrSpace(job.Endpoint);

            if (job.Status == "queued")
            {
                var data = GrnCloudOcrEngine.PrepareUpload(eligible, maxBytes: space ? 1_000_000 : 4 * 1024 * 1024);

                bool proceed = true;
                lock (store.SyncRoot)
                {
                    store.RunImmediate(() =>
                    {
                        if (GrnCloudOcrEngine.EligibleDocumentUnsafe(store, job.DocumentId, job.ImageHash, job.Revision) is null)
                        {
                            proceed = false;
                            return;
                        }
                        var curStatus = store.ExecuteScalar<string>("SELECT status FROM grn_cloud_jobs WHERE id=@id", ("@id", job.Id));
                        if (curStatus != "queued")
                        {
                            proceed = false;
                            return;
                        }
                        var latest = GrnCloudOcrEngine.CloudSettings(store);
                        if (!latest.Enabled || !string.Equals(latest.Endpoint, job.Endpoint, StringComparison.Ordinal))
                            throw new ArgumentException("Cloud OCR was disabled or the resource changed before upload.");

                        int limit = latest.DailyLimit;
                        if (GrnCloudOcrEngine.UsageToday(store) >= limit || limit < 1)
                            throw new ArgumentException("Daily cloud upload limit reached. Review manually or retry on another day.");

                        var day = DateTime.Now.Date.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
                        store.ExecuteNonQuery(
                            "INSERT INTO grn_cloud_usage VALUES(@d,1) ON CONFLICT(day) DO UPDATE SET uploads=uploads+1",
                            ("@d", day));
                        store.ExecuteNonQuery(
                            "UPDATE grn_cloud_jobs SET status='submitting' WHERE id=@id AND status='queued'",
                            ("@id", job.Id));
                        store.ExecuteNonQuery(
                            "UPDATE grn_documents SET state='Cloud reading' WHERE id=@did",
                            ("@did", job.DocumentId));
                    });
                }

                if (!proceed)
                    return true;

                if (space)
                {
                    using var client = new OcrSpaceClient(job.Endpoint, key);
                    JsonElement response;
                    try
                    {
                        response = client.Submit(data);
                    }
                    catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or ArgumentException)
                    {
                        Fail(store, job, "Cloud submission outcome is uncertain. Check provider usage; Retry Cloud explicitly to upload again.", "uncertain");
                        return true;
                    }

                    using var uploadedMat = Cv2.ImDecode(data, ImreadModes.Unchanged);
                    var cloud = GrnCloudOcrEngine.ParseOcrSpaceResult(response, uploadedMat.Width, uploadedMat.Height);
                    Finish(store, job, cloud);
                    store.SetSetting("grn_cloud_status", "OCR.space reading complete. Check the number and warehouse.");
                    return true;
                }
                else
                {
                    using var azClient = new AzureReadClient(job.Endpoint, key);
                    string operation;
                    try
                    {
                        operation = azClient.Submit(data);
                    }
                    catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or ArgumentException)
                    {
                        Fail(store, job, "Cloud submission outcome is uncertain. Check provider usage; Retry Cloud explicitly to upload again.", "uncertain");
                        return true;
                    }

                    job.OperationUrl = operation;
                    job.Deadline = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0 + 60.0;
                    job.Status = "polling";
                    lock (store.SyncRoot)
                    {
                        store.RunImmediate(() => store.ExecuteNonQuery(
                            "UPDATE grn_cloud_jobs SET status='polling', operation_url=@url, deadline=@dl WHERE id=@id",
                            ("@url", operation), ("@dl", job.Deadline), ("@id", job.Id)));
                    }
                }
            }

            if (!space)
            {
                using var azClient = new AzureReadClient(job.Endpoint, key);
                while (!_stopping.IsCancellationRequested)
                {
                    bool canContinue;
                    lock (store.SyncRoot)
                    {
                        canContinue = GrnCloudOcrEngine.EligibleDocumentUnsafe(store, job.DocumentId, job.ImageHash, job.Revision) is not null
                            && GrnCloudOcrEngine.CloudSettings(store).Enabled;
                    }
                    if (!canContinue)
                    {
                        Fail(store, job, "Cloud reading cancelled; saved review and visibility are preserved.", "cancelled");
                        return true;
                    }

                    double remaining = job.Deadline - DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
                    if (remaining <= 0)
                    {
                        Fail(store, job, "Azure reading reached its 60-second wait limit. Retry Cloud to poll the accepted request without uploading again.", "timeout");
                        return true;
                    }

                    var (payload, delay) = azClient.Poll(job.OperationUrl, Math.Max(0.01, remaining));
                    var statusStr = payload.TryGetProperty("status", out var stEl) && stEl.ValueKind == JsonValueKind.String
                        ? stEl.GetString() ?? "" : "";

                    if (statusStr == "succeeded")
                    {
                        Finish(store, job, GrnCloudOcrEngine.ParseAzureResult(payload));
                        store.SetSetting("grn_cloud_status", "Azure reading complete. Check the number and warehouse.");
                        return true;
                    }
                    if (statusStr == "failed")
                        throw new ArgumentException("Azure could not read this photo. Review manually or retry extraction.");
                    if (statusStr is not ("running" or "notStarted"))
                        throw new ArgumentException("Azure returned an unsupported processing status. Review manually.");

                    _stopping.WaitHandle.WaitOne(TimeSpan.FromSeconds(Math.Min(delay, remaining)));
                }
            }
        }
        catch (HttpRequestException)
        {
            Fail(store, job, "Cloud OCR connection failed. Check the network and retry explicitly.");
        }
        catch (TaskCanceledException)
        {
            Fail(store, job, "Cloud OCR connection failed. Check the network and retry explicitly.");
        }
        catch (Exception ex)
        {
            Fail(store, job, ex.Message);
        }

        return true;
    }

    private void Run()
    {
        using var store = new WhatsAppGrnStore(_dbPath);
        try
        {
            var interrupted = new List<CloudOcrJobRecord>();
            lock (store.SyncRoot)
            {
                using var cmd = store.Connection.CreateCommand();
                cmd.CommandText = "SELECT id, document_id, image_hash, revision, version, endpoint, status, operation_url, error, deadline, result FROM grn_cloud_jobs WHERE status='submitting'";
                using var r = cmd.ExecuteReader();
                while (r.Read())
                {
                    interrupted.Add(new CloudOcrJobRecord
                    {
                        Id = r.GetInt64(0),
                        DocumentId = r.GetInt64(1),
                        ImageHash = r.GetString(2),
                        Revision = r.GetInt32(3),
                        Version = r.GetString(4),
                        Endpoint = r.GetString(5),
                        Status = r.GetString(6),
                        OperationUrl = r.GetString(7),
                        Error = r.GetString(8),
                        Deadline = r.GetDouble(9),
                        Result = r.GetString(10)
                    });
                }
            }

            foreach (var j in interrupted)
                Fail(store, j, "Interrupted cloud submission has an uncertain outcome. Check provider usage before Retry Cloud.", "uncertain");

            while (!_stopping.IsCancellationRequested)
            {
                if (!ProcessOne(store))
                    _stopping.WaitHandle.WaitOne(500);
            }
        }
        catch
        {
            try
            {
                store.SetSetting("grn_cloud_status", "Cloud OCR worker stopped. Reconnect WhatsApp to resume; accepted requests are retained.");
            }
            catch { }
        }
    }
}
