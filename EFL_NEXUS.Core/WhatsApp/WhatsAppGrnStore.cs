using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;
using EflNexus.Core.GrnOcr;
using Microsoft.Data.Sqlite;
using OpenCvSharp;

namespace EflNexus.Core.WhatsApp;

/// <summary>
/// Durable photo capture and local GRN review records (1:1 parity with whatsapp_grn.py).
/// </summary>
public sealed partial class WhatsAppGrnStore : WhatsAppGdnStore
{
    public const int MaxImageBytes = WhatsAppScripts.MaxImageBytes;
    public const int MaxImagePixels = WhatsAppScripts.MaxImagePixels;
    public const int GrnScanWindowSeconds = WhatsAppScripts.GrnScanWindowSeconds;

    public static readonly string[] GrnWarehouses =
        ["EGDC", "ESKD", "NUGE", "LPPL", "LPSP", "INMM01"];

    [GeneratedRegex(@"^\d{1,2}:\d{2}(?: [AP]M)?, \d{1,2}/\d{1,2}/\d{4}$", RegexOptions.IgnoreCase)]
    private static partial Regex WhatsAppStampRegex();

    public WhatsAppGrnStore(string? path = null) : base(path)
    {
        lock (DbLock)
        {
            ExecuteNonQuery("""
                CREATE TABLE IF NOT EXISTS grn_documents (
                    id INTEGER PRIMARY KEY,
                    image_hash TEXT NOT NULL UNIQUE,
                    image_path TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    warehouse TEXT NOT NULL DEFAULT '',
                    gatepass TEXT NOT NULL DEFAULT '',
                    extraction TEXT NOT NULL DEFAULT '{}',
                    state TEXT NOT NULL DEFAULT 'Pending',
                    action TEXT NOT NULL DEFAULT 'New',
                    reviewed INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS grn_sources (
                    id INTEGER PRIMARY KEY,
                    group_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    photo_index INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    warehouse TEXT NOT NULL DEFAULT '',
                    document_id INTEGER REFERENCES grn_documents(id),
                    skipped INTEGER NOT NULL DEFAULT 0,
                    capture_error TEXT NOT NULL DEFAULT '',
                    next_try REAL NOT NULL DEFAULT 0,
                    capture_refresh INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(group_id, message_id, photo_index)
                );
                """);

            AddColumns("grn_sources", new Dictionary<string, string>(StringComparer.Ordinal)
            {
                ["capture_refresh"] = "INTEGER NOT NULL DEFAULT 0",
                ["incoming_verified"] = "INTEGER NOT NULL DEFAULT 1",
                ["capture_attempts"] = "INTEGER NOT NULL DEFAULT 0",
                ["message_time"] = "TEXT NOT NULL DEFAULT ''",
                ["captured_at"] = "TEXT NOT NULL DEFAULT ''",
                ["hidden_reason"] = "TEXT NOT NULL DEFAULT ''",
                ["message_received_at"] = "REAL"
            });

            AddColumns("grn_documents", new Dictionary<string, string>(StringComparer.Ordinal)
            {
                ["message_time"] = "TEXT NOT NULL DEFAULT ''",
                ["hidden_reason"] = "TEXT NOT NULL DEFAULT ''",
                ["run_state"] = "TEXT NOT NULL DEFAULT 'New'",
                ["run_id"] = "TEXT NOT NULL DEFAULT ''",
                ["ocr_revision"] = "INTEGER NOT NULL DEFAULT 0"
            });

            GrnCloudOcrEngine.InitializeCloudTables(this);
        }
    }

    internal SqliteConnection Connection => Db;
    internal object SyncRoot => DbLock;

    public static double? GrnMessageEpoch(string? value)
    {
        var tokens = (value ?? "")
            .Replace("\u200e", "")
            .Replace("\u200f", "")
            .Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
        var text = string.Join(" ", tokens);
        if (string.IsNullOrEmpty(text))
            return null;

        if (DateTimeOffset.TryParse(text, CultureInfo.InvariantCulture, DateTimeStyles.None, out var isoDto)
            && (text.EndsWith('Z') || text.Contains('+') || (text.Length > 10 && text[10..].Contains('-'))))
        {
            return isoDto.ToUnixTimeMilliseconds() / 1000.0;
        }

        if (WhatsAppStampRegex().IsMatch(text))
        {
            var upper = text.ToUpperInvariant();
            string[] formats = ["H:mm, d/M/yyyy", "h:mm tt, d/M/yyyy"];
            if (DateTime.TryParseExact(upper, formats, CultureInfo.InvariantCulture, DateTimeStyles.AssumeLocal, out var localDt))
            {
                return new DateTimeOffset(localDt).ToUnixTimeMilliseconds() / 1000.0;
            }
        }
        return null;
    }

    public static bool GrnPhotoIsRecent(string? messageTime, double? nowEpoch = null)
    {
        var received = GrnMessageEpoch(messageTime);
        if (received is null)
            return false;
        double current = nowEpoch ?? (DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0);
        double delta = current - received.Value;
        return delta >= 0 && delta <= GrnScanWindowSeconds;
    }

    public static List<string> ValidateGrnFields(string? warehouse, string? gatepass, IReadOnlySet<string>? warehouses = null)
    {
        var allowed = warehouses ?? new HashSet<string>(GrnWarehouses, StringComparer.Ordinal);
        var errors = new List<string>();
        if (string.IsNullOrEmpty(warehouse) || !allowed.Contains(warehouse))
            errors.Add("Choose a valid GRN Warehouse ID.");
        if (string.IsNullOrEmpty(gatepass) || !gatepass.All(ch => ch is >= '0' and <= '9'))
            errors.Add("Enter the printed gate pass using digits only; leading zeroes are preserved.");
        return errors;
    }

    public override void ObserveMessages(WhatsAppSnapshot snapshot)
    {
        base.ObserveMessages(snapshot);
        lock (DbLock)
        {
            RunImmediate(() =>
            {
                ExecuteNonQuery(
                    """
                    UPDATE grn_sources SET hidden_reason='done'
                    WHERE hidden_reason<>'done' AND EXISTS (
                        SELECT 1 FROM whatsapp_messages m
                        WHERE m.group_id=grn_sources.group_id AND m.message_id=grn_sources.message_id AND m.done=1
                    )
                    """);
                ExecuteNonQuery(
                    """
                    UPDATE grn_documents SET hidden_reason='done'
                    WHERE hidden_reason<>'done' AND id IN (
                        SELECT document_id FROM grn_sources WHERE hidden_reason='done' AND document_id IS NOT NULL
                    )
                    """);
            });
        }
    }

    public override int ClearList()
    {
        lock (DbLock)
        {
            return RunImmediate(() =>
            {
                int count = ExecuteScalar<int>("SELECT count(*) FROM grn_documents WHERE hidden_reason=''");
                count += ExecuteScalar<int>("SELECT count(*) FROM grn_sources WHERE hidden_reason='' AND skipped=0 AND document_id IS NULL");
                ExecuteNonQuery("UPDATE grn_documents SET hidden_reason='cleared' WHERE hidden_reason=''");
                ExecuteNonQuery("UPDATE grn_sources SET hidden_reason='cleared' WHERE hidden_reason='' AND skipped=0");
                return count;
            });
        }
    }

    public long GrnNewCount()
    {
        lock (DbLock)
        {
            return ExecuteScalar<long>(
                """
                SELECT
                    (SELECT count(*) FROM grn_documents WHERE action='New' AND hidden_reason='') +
                    (SELECT count(*) FROM grn_sources WHERE skipped=0 AND hidden_reason='' AND document_id IS NULL)
                """);
        }
    }

    public string DefaultWarehouse(string groupId)
    {
        var map = Setting("grn_warehouses", new Dictionary<string, string>(StringComparer.Ordinal));
        return map.TryGetValue(groupId, out var wh) ? wh : "";
    }

    public void SetDefaultWarehouse(string groupId, string warehouse)
    {
        if (!GrnWarehouses.Contains(warehouse, StringComparer.Ordinal))
            throw new ArgumentException("Choose a valid GRN warehouse.");
        var mapping = Setting("grn_warehouses", new Dictionary<string, string>(StringComparer.Ordinal));
        mapping[groupId] = warehouse;
        SetSetting("grn_warehouses", mapping);
        lock (DbLock)
        {
            RunImmediate(() =>
            {
                ExecuteNonQuery("UPDATE grn_sources SET warehouse=@wh WHERE group_id=@gid AND warehouse=''",
                    ("@wh", warehouse), ("@gid", groupId));
                ExecuteNonQuery(
                    """
                    UPDATE grn_documents SET warehouse=@wh
                    WHERE warehouse='' AND reviewed=0 AND id IN (SELECT document_id FROM grn_sources WHERE group_id=@gid AND document_id IS NOT NULL)
                    """,
                    ("@wh", warehouse), ("@gid", groupId));
            });
        }
    }

    public (int Eligible, int OutsideWindow, int UnknownTime) Discover(
        WhatsAppSnapshot snapshot,
        bool baseline = false,
        bool importVisible = false,
        bool recentOnly = false)
    {
        ObserveMessages(snapshot);
        var group = snapshot.GroupId;
        var warehouse = DefaultWarehouse(group);
        double now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
        int eligible = 0, outsideWindow = 0, unknownTime = 0;

        lock (DbLock)
        {
            RunImmediate(() =>
            {
                var candidates = snapshot.Photos.Select(p => (Photo: p, Verified: 1))
                    .Concat(snapshot.UnclassifiedPhotos.Select(p => (Photo: p, Verified: 0)));

                foreach (var (photo, verified) in candidates)
                {
                    var received = GrnMessageEpoch(photo.MessageTime);
                    if (recentOnly && (received is null || now - received.Value < 0 || now - received.Value > GrnScanWindowSeconds))
                    {
                        if (received is null) unknownTime++;
                        else outsideWindow++;
                        continue;
                    }

                    eligible++;
                    var isDone = ExecuteScalar<long?>(
                        "SELECT 1 FROM whatsapp_messages WHERE group_id=@gid AND message_id=@mid AND done=1",
                        ("@gid", group), ("@mid", photo.MessageId)) is not null;

                    ExecuteNonQuery(
                        """
                        INSERT INTO grn_sources
                            (group_id, message_id, photo_index, source, warehouse, skipped, incoming_verified, message_time, captured_at, hidden_reason, message_received_at)
                        VALUES (@gid, @mid, @idx, @src, @wh, @skip, @ver, @mtime, @cat, @hid, @mrecv)
                        ON CONFLICT(group_id, message_id, photo_index) DO UPDATE SET
                            incoming_verified=max(grn_sources.incoming_verified, excluded.incoming_verified),
                            message_time=CASE WHEN excluded.message_time<>'' THEN excluded.message_time ELSE grn_sources.message_time END,
                            message_received_at=CASE WHEN excluded.message_time<>'' THEN excluded.message_received_at ELSE grn_sources.message_received_at END
                        """,
                        ("@gid", group),
                        ("@mid", photo.MessageId),
                        ("@idx", photo.Index),
                        ("@src", snapshot.Name),
                        ("@wh", warehouse),
                        ("@skip", baseline ? 1 : 0),
                        ("@ver", verified),
                        ("@mtime", photo.MessageTime ?? ""),
                        ("@cat", DateTimeOffset.UtcNow.ToString("O")),
                        ("@hid", isDone ? "done" : ""),
                        ("@mrecv", received));

                    ExecuteNonQuery(
                        """
                        UPDATE grn_documents SET message_time=@mtime
                        WHERE message_time='' AND id IN (
                            SELECT document_id FROM grn_sources
                            WHERE group_id=@gid AND message_id=@mid AND photo_index=@idx AND document_id IS NOT NULL
                        )
                        """,
                        ("@mtime", photo.MessageTime ?? ""), ("@gid", group), ("@mid", photo.MessageId), ("@idx", photo.Index));

                    if (importVisible)
                    {
                        ExecuteNonQuery(
                            """
                            UPDATE grn_sources SET skipped=0, next_try=0, warehouse=@wh
                            WHERE group_id=@gid AND message_id=@mid AND photo_index=@idx AND document_id IS NULL AND hidden_reason=''
                            """,
                            ("@wh", warehouse), ("@gid", group), ("@mid", photo.MessageId), ("@idx", photo.Index));
                    }
                }
            });
        }
        return (eligible, outsideWindow, unknownTime);
    }

    public List<GrnSourceRecord> PendingCapture(
        string groupId,
        int limit = 1,
        IReadOnlyCollection<long>? excludeIds = null,
        IReadOnlyCollection<string>? visibleIds = null,
        long? ownerId = null,
        bool recentOnly = false)
    {
        double now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
        var args = new List<(string, object?)> { ("@gid", groupId), ("@now", now) };
        var query = """
            SELECT * FROM grn_sources
            WHERE group_id=@gid AND incoming_verified=1 AND skipped=0 AND hidden_reason=''
              AND (document_id IS NULL OR capture_refresh=1) AND next_try<=@now
              AND NOT EXISTS (SELECT 1 FROM whatsapp_messages m WHERE m.group_id=grn_sources.group_id AND m.message_id=grn_sources.message_id AND m.done=1)
              AND NOT EXISTS (SELECT 1 FROM grn_documents d WHERE d.id=grn_sources.document_id AND d.hidden_reason<>'')
            """;

        if (recentOnly)
        {
            query += " AND message_received_at BETWEEN @winStart AND @winEnd";
            args.Add(("@winStart", now - GrnScanWindowSeconds));
            args.Add(("@winEnd", now));
        }
        if (ownerId is not null)
        {
            query += " AND id=@ownerId";
            args.Add(("@ownerId", ownerId.Value));
        }
        if (excludeIds is { Count: > 0 })
        {
            var names = excludeIds.Select((id, i) =>
            {
                var p = $"@ex{i}";
                args.Add((p, id));
                return p;
            });
            query += $" AND id NOT IN ({string.Join(',', names)})";
        }
        if (visibleIds is not null)
        {
            if (visibleIds.Count == 0)
                return [];
            var names = visibleIds.Select((mid, i) =>
            {
                var p = $"@vis{i}";
                args.Add((p, mid));
                return p;
            });
            query += $" AND message_id IN ({string.Join(',', names)})";
        }

        query += " ORDER BY next_try, id LIMIT @limit";
        args.Add(("@limit", limit));

        var list = new List<GrnSourceRecord>();
        lock (DbLock)
        {
            using var cmd = Db.CreateCommand();
            cmd.CommandText = query;
            foreach (var (name, value) in args)
                cmd.Parameters.AddWithValue(name, value ?? DBNull.Value);
            using var r = cmd.ExecuteReader();
            while (r.Read())
                list.Add(ReadSource(r));
        }
        return list;
    }

    public List<GrnSourceRecord> PendingEntries()
    {
        var list = new List<GrnSourceRecord>();
        lock (DbLock)
        {
            using var cmd = Db.CreateCommand();
            cmd.CommandText = "SELECT * FROM grn_sources WHERE skipped=0 AND hidden_reason='' AND document_id IS NULL ORDER BY id DESC";
            using var r = cmd.ExecuteReader();
            while (r.Read())
                list.Add(ReadSource(r));
        }
        return list;
    }

    public GrnSourceRecord? GetSource(long sourceId)
    {
        lock (DbLock)
        {
            using var cmd = Db.CreateCommand();
            cmd.CommandText = "SELECT * FROM grn_sources WHERE id=@id";
            cmd.Parameters.AddWithValue("@id", sourceId);
            using var r = cmd.ExecuteReader();
            return r.Read() ? ReadSource(r) : null;
        }
    }

    public void CaptureFailed(long sourceId, string error)
    {
        lock (DbLock)
        {
            RunImmediate(() =>
            {
                int attempts = ExecuteScalar<int>("SELECT capture_attempts FROM grn_sources WHERE id=@id", ("@id", sourceId));
                int[] delays = [1, 2, 5, 15, 30];
                int delay = delays[Math.Min(attempts, 4)];
                double nextTry = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0 + delay;
                var msg = error.Length > 500 ? error[..500] : error;
                ExecuteNonQuery(
                    "UPDATE grn_sources SET capture_error=@err, next_try=@nt, capture_attempts=capture_attempts+1 WHERE id=@id AND hidden_reason=''",
                    ("@err", msg), ("@nt", nextTry), ("@id", sourceId));
            });
        }
    }

    public void CaptureWaiting(long sourceId, string detail)
    {
        double nextTry = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0 + 0.25;
        var msg = detail.Length > 500 ? detail[..500] : detail;
        lock (DbLock)
        {
            RunImmediate(() =>
            {
                ExecuteNonQuery(
                    "UPDATE grn_sources SET capture_error=@err, next_try=@nt WHERE id=@id AND hidden_reason=''",
                    ("@err", msg), ("@nt", nextTry), ("@id", sourceId));
            });
        }
    }

    public long SaveImage(long sourceId, string encodedBase64)
    {
        var initial = GetSource(sourceId);
        if (initial is null || !string.IsNullOrEmpty(initial.HiddenReason))
            throw new ArgumentException("Photo source was cleared or marked DONE.");
        if (encodedBase64.Length > MaxImageBytes * 4 / 3 + 4)
            throw new ArgumentException("Photo exceeds the 20 MB capture limit.");

        byte[] data;
        try
        {
            data = Convert.FromBase64String(encodedBase64);
        }
        catch (FormatException)
        {
            throw new ArgumentException("Invalid Base64 photo data.");
        }

        if (data.Length > MaxImageBytes)
            throw new ArgumentException("Photo exceeds the 20 MB capture limit.");

        if (!IsSupportedRasterFormat(data))
            throw new ArgumentException("Unsupported photo format; send a JPEG, PNG or WebP photo.");

        using (var mat = Cv2.ImDecode(data, ImreadModes.Unchanged))
        {
            if (mat.Empty() || mat.Width <= 0 || mat.Height <= 0)
                throw new ArgumentException("Corrupt or unreadable image data.");
            if ((long)mat.Width * mat.Height > MaxImagePixels)
                throw new ArgumentException("Photo exceeds the 30 megapixel limit.");
        }

        var digest = Convert.ToHexStringLower(SHA256.HashData(data));
        var parentDir = Path.GetDirectoryName(Path.GetFullPath(FilePath))!;
        var folder = Path.Combine(parentDir, "grn_images");
        Directory.CreateDirectory(folder);
        var destination = Path.Combine(folder, digest + ".image");
        var tempPath = Path.Combine(folder, $"{digest}.{Environment.ProcessId}.{Environment.CurrentManagedThreadId}.tmp");
        try
        {
            using (var fs = new FileStream(tempPath, FileMode.Create, FileAccess.Write, FileShare.None))
            {
                fs.Write(data, 0, data.Length);
                fs.Flush(flushToDisk: true);
            }
            File.Move(tempPath, destination, overwrite: true);
        }
        finally
        {
            try { if (File.Exists(tempPath)) File.Delete(tempPath); } catch { }
        }

        lock (DbLock)
        {
            return RunImmediate(() =>
            {
                GrnSourceRecord? src = null;
                using (var cmd = Db.CreateCommand())
                {
                    cmd.CommandText = "SELECT * FROM grn_sources WHERE id=@id";
                    cmd.Parameters.AddWithValue("@id", sourceId);
                    using var r = cmd.ExecuteReader();
                    if (r.Read()) src = ReadSource(r);
                }
                if (src is null || !string.IsNullOrEmpty(src.HiddenReason))
                    throw new ArgumentException("Photo source was cleared or marked DONE.");

                if (ExecuteScalar<long?>("SELECT 1 FROM whatsapp_messages WHERE group_id=@gid AND message_id=@mid AND done=1",
                    ("@gid", src.GroupId), ("@mid", src.MessageId)) is not null)
                    throw new ArgumentException("Photo source was marked DONE.");

                if (src.DocumentId is not null)
                {
                    var prev = DocumentUnsafe(src.DocumentId.Value);
                    if (prev is not null && !string.IsNullOrEmpty(prev.HiddenReason))
                        throw new ArgumentException("Photo was cleared or marked DONE.");

                    if (src.CaptureRefresh != 0 && prev is not null)
                    {
                        if (prev.Reviewed != 0 || prev.Action != "New")
                            throw new ArgumentException("A saved review cannot be replaced by capture. Keep the reviewed values.");

                        var dupId = ExecuteScalar<long?>("SELECT id FROM grn_documents WHERE image_hash=@h", ("@h", digest));
                        if (dupId is null || dupId.Value == prev.Id)
                        {
                            ExecuteNonQuery(
                                """
                                UPDATE grn_documents SET image_hash=@h, image_path=@p, extraction='{}',
                                gatepass='', state='Pending', ocr_revision=ocr_revision+1 WHERE id=@id
                                """,
                                ("@h", digest), ("@p", destination), ("@id", prev.Id));
                        }
                        else
                        {
                            ExecuteNonQuery(
                                "UPDATE grn_documents SET action='Replaced by another captured photo', state='Replaced' WHERE id=@id",
                                ("@id", prev.Id));
                        }
                    }
                }

                ExecuteNonQuery(
                    """
                    INSERT INTO grn_documents (image_hash, image_path, received_at, warehouse, message_time)
                    VALUES (@h, @p, @r, @w, @mt) ON CONFLICT(image_hash) DO NOTHING
                    """,
                    ("@h", digest), ("@p", destination), ("@r", DateTimeOffset.UtcNow.ToString("O")),
                    ("@w", src.Warehouse), ("@mt", src.MessageTime));

                long recordId = ExecuteScalar<long>("SELECT id FROM grn_documents WHERE image_hash=@h", ("@h", digest));
                ExecuteNonQuery(
                    "UPDATE grn_sources SET document_id=@did, capture_error='', capture_refresh=0, capture_attempts=0, next_try=0 WHERE id=@sid",
                    ("@did", recordId), ("@sid", sourceId));
                return recordId;
            });
        }
    }

    private static bool IsSupportedRasterFormat(byte[] data)
    {
        // JPEG: FF D8 FF
        if (data.Length >= 3 && data[0] == 0xFF && data[1] == 0xD8 && data[2] == 0xFF)
            return true;
        // PNG: 89 50 4E 47 0D 0A 1A 0A
        if (data.Length >= 8 && data[0] == 0x89 && data[1] == 0x50 && data[2] == 0x4E && data[3] == 0x47
            && data[4] == 0x0D && data[5] == 0x0A && data[6] == 0x1A && data[7] == 0x0A)
            return true;
        // WEBP: RIFF....WEBP
        if (data.Length >= 12 && data[0] == 'R' && data[1] == 'I' && data[2] == 'F' && data[3] == 'F'
            && data[8] == 'W' && data[9] == 'E' && data[10] == 'B' && data[11] == 'P')
            return true;
        return false;
    }

    public List<GrnDocumentRecord> Documents(bool includeHidden = false)
    {
        var where = includeHidden ? "" : " WHERE d.hidden_reason=''";
        var list = new List<GrnDocumentRecord>();
        lock (DbLock)
        {
            using var cmd = Db.CreateCommand();
            cmd.CommandText = $"""
                SELECT d.*,
                    (SELECT source FROM grn_sources WHERE document_id=d.id ORDER BY id LIMIT 1) AS source,
                    (SELECT count(*) FROM grn_sources WHERE document_id=d.id) AS copies
                FROM grn_documents d{where} ORDER BY d.id DESC
                """;
            using var r = cmd.ExecuteReader();
            while (r.Read())
                list.Add(ReadDocument(r, includeJoins: true));
        }
        return list;
    }

    public GrnDocumentRecord? Document(long recordId)
    {
        lock (DbLock)
        {
            return DocumentUnsafe(recordId);
        }
    }

    private GrnDocumentRecord? DocumentUnsafe(long recordId)
    {
        using var cmd = Db.CreateCommand();
        cmd.CommandText = "SELECT * FROM grn_documents WHERE id=@id";
        cmd.Parameters.AddWithValue("@id", recordId);
        using var r = cmd.ExecuteReader();
        return r.Read() ? ReadDocument(r, includeJoins: false) : null;
    }

    public void SaveGrnReview(long recordId, string warehouse, string gatepass, string action = "Reviewed")
    {
        lock (DbLock)
        {
            RunImmediate(() =>
            {
                int changed = ExecuteNonQuery(
                    "UPDATE grn_documents SET warehouse=@wh, gatepass=@gp, reviewed=1, action=@act WHERE id=@id AND hidden_reason='' AND run_state<>'Running'",
                    ("@wh", warehouse), ("@gp", gatepass), ("@act", action), ("@id", recordId));
                if (changed == 0)
                    throw new ArgumentException("This photo is running, cleared, or marked DONE. Select an idle active photo.");
            });
        }
    }

    public void Retry(long? recordId = null)
    {
        lock (DbLock)
        {
            RunImmediate(() =>
            {
                if (recordId is not null)
                {
                    ExecuteNonQuery(
                        "UPDATE grn_documents SET state='Pending', ocr_revision=ocr_revision+1 WHERE id=@id AND hidden_reason='' AND state<>'Awaiting original photo' AND run_state<>'Running' AND action NOT LIKE 'Filled:%'",
                        ("@id", recordId.Value));
                }
                ExecuteNonQuery("UPDATE grn_sources SET next_try=0, capture_attempts=0 WHERE skipped=0 AND hidden_reason='' AND (document_id IS NULL OR capture_refresh=1)");
            });
        }
    }

    public void RefreshPhoto(long recordId, bool recentOnly = false)
    {
        var record = Document(recordId);
        if (record is null || !string.IsNullOrEmpty(record.HiddenReason) || record.Reviewed != 0 || record.Action != "New")
            throw new ArgumentException("Only an unreviewed photo can be recaptured. Saved review values are preserved.");

        if (recentOnly)
        {
            bool anyRecent = false;
            lock (DbLock)
            {
                using var cmd = Db.CreateCommand();
                cmd.CommandText = "SELECT message_time FROM grn_sources WHERE document_id=@id";
                cmd.Parameters.AddWithValue("@id", recordId);
                using var r = cmd.ExecuteReader();
                while (r.Read())
                {
                    if (GrnPhotoIsRecent(r.GetString(0)))
                    {
                        anyRecent = true;
                        break;
                    }
                }
            }
            if (!anyRecent)
                throw new ArgumentException("Only GRN photos received within the last hour can be captured. The received time must be available.");
        }

        if (record.State is "Pending" or "Extracting")
            throw new ArgumentException("Wait for extraction to finish before recapturing the photo.");

        lock (DbLock)
        {
            RunImmediate(() =>
            {
                ExecuteNonQuery("UPDATE grn_documents SET state='Awaiting original photo' WHERE id=@id", ("@id", recordId));
                ExecuteNonQuery("UPDATE grn_sources SET capture_refresh=1, next_try=0 WHERE document_id=@id", ("@id", recordId));
            });
        }
    }

    public List<(long Id, string Source, string CaptureError)> CaptureErrors()
    {
        var list = new List<(long, string, string)>();
        lock (DbLock)
        {
            using var cmd = Db.CreateCommand();
            cmd.CommandText = """
                SELECT id, source, capture_error FROM grn_sources
                WHERE skipped=0 AND hidden_reason='' AND (document_id IS NULL OR capture_refresh=1) AND capture_error<>''
                ORDER BY id DESC
                """;
            using var r = cmd.ExecuteReader();
            while (r.Read())
                list.Add((r.GetInt64(0), r.GetString(1), r.GetString(2)));
        }
        return list;
    }

    public long GetSourceCountForDocument(long documentId)
    {
        lock (DbLock)
        {
            return ExecuteScalar<long>("SELECT count(*) FROM grn_sources WHERE document_id=@id", ("@id", documentId));
        }
    }

    public static void FillGrnRequest(
        WhatsAppGrnStore store,
        long? recordId,
        string warehouse,
        string gatepass,
        string laneName,
        IReadOnlyDictionary<string, IKorberLaneTarget> lanes,
        bool allowRepeat = false)
    {
        var errors = ValidateGrnFields(warehouse, gatepass);
        if (errors.Count > 0)
            throw new ArgumentException(string.Join("\n", errors));

        if (recordId is null)
            throw new ArgumentException("Select a captured photo first.");

        var record = store.Document(recordId.Value) ?? throw new ArgumentException("Select a captured photo first.");
        if (!string.IsNullOrEmpty(record.HiddenReason))
            throw new ArgumentException("This photo was cleared or marked DONE. Select an active photo.");

        if (record.State is "Pending" or "Extracting" or "Awaiting original photo" ||
            GrnCloudOcrEngine.PendingStates.Contains(record.State, StringComparer.Ordinal))
            throw new ArgumentException("Wait for extraction to finish before transferring the reviewed number.");

        bool hasRefreshPending;
        lock (store.SyncRoot)
        {
            hasRefreshPending = store.ExecuteScalar<long?>(
                "SELECT 1 FROM grn_sources WHERE document_id=@id AND capture_refresh=1 LIMIT 1",
                ("@id", recordId.Value)) is not null;
        }
        if (hasRefreshPending)
            throw new ArgumentException("Wait for original-photo capture before transferring the reviewed number.");

        if (record.RunState == "Running")
            throw new ArgumentException("This gate pass is running. Wait for it to finish or stop its lane.");

        if (record.Action.StartsWith("Replaced", StringComparison.Ordinal) ||
            (!allowRepeat && (record.Action.StartsWith("Filled:", StringComparison.Ordinal) ||
                              record.Action.StartsWith("Filling:", StringComparison.Ordinal) ||
                              record.Action.StartsWith("Transfer uncertain:", StringComparison.Ordinal))))
        {
            throw new ArgumentException("This document was already transferred. Check the target lane before processing it again.");
        }

        if (!lanes.TryGetValue(laneName, out var lane))
            throw new ArgumentException("Select an available target lane.");

        if (lane.IsQueueRunning || lane.IsBusy)
            throw new ArgumentException($"{laneName} is busy. Choose another lane or wait.");

        foreach (var other in store.Documents(includeHidden: true))
        {
            if (other.Id != recordId.Value && other.Warehouse == warehouse && other.Gatepass == gatepass &&
                (other.RunState == "Running" || (!allowRepeat &&
                    (other.Action.StartsWith("Filled:", StringComparison.Ordinal) ||
                     other.Action.StartsWith("Filling:", StringComparison.Ordinal) ||
                     other.Action.StartsWith("Transfer uncertain:", StringComparison.Ordinal)))))
            {
                throw new ArgumentException("This warehouse and gate pass were already transferred from another photo. Check the existing request.");
            }
        }

        if (lanes.Values.Any(l => l.HasActiveGatepass("GRN", warehouse, "", gatepass)))
            throw new ArgumentException("This warehouse and gate pass are already in a GRN queue or running.");

        store.SaveGrnReview(recordId.Value, warehouse, gatepass, $"Filling: {laneName}");
        try
        {
            lane.PrefillGrn(warehouse, gatepass);
            lane.SetStatus($"Reviewed WhatsApp GRN (GP={gatepass}). Click Create GRN when ready.");
            store.SaveGrnReview(recordId.Value, warehouse, gatepass, $"Filled: {laneName}");
        }
        catch
        {
            store.SaveGrnReview(recordId.Value, warehouse, gatepass, $"Transfer uncertain: {laneName}");
            throw;
        }
    }

    public static string LaunchGatepass(
        WhatsAppGdnStore store,
        long recordId,
        string docType,
        string laneName,
        IKorberLaneTarget lane)
    {
        var runId = store.BeginGatepassRun(recordId, laneName, docType);
        lane.WhatsappRunId = runId;
        var dbPath = store.FilePath;

        void Finished(bool completed, string detail)
        {
            try
            {
                using var resultStore = new WhatsAppGrnStore(dbPath);
                resultStore.FinishGatepassRun(runId, completed, detail);
            }
            catch { }
            finally
            {
                if (lane.WhatsappRunId == runId)
                    lane.WhatsappRunId = "";
            }
        }

        try
        {
            if (!lane.RunFlow(docType, Finished))
                throw new InvalidOperationException("The lane did not start. Check its required fields and current run.");
        }
        catch (Exception ex)
        {
            Finished(false, $"Could not start: {ex.Message}");
            throw;
        }

        return runId;
    }

    private static GrnSourceRecord ReadSource(SqliteDataReader r)
    {
        return new GrnSourceRecord
        {
            Id = r.GetInt64(r.GetOrdinal("id")),
            GroupId = r.GetString(r.GetOrdinal("group_id")),
            MessageId = r.GetString(r.GetOrdinal("message_id")),
            PhotoIndex = r.GetInt32(r.GetOrdinal("photo_index")),
            Source = r.GetString(r.GetOrdinal("source")),
            Warehouse = r.GetString(r.GetOrdinal("warehouse")),
            DocumentId = r.IsDBNull(r.GetOrdinal("document_id")) ? null : r.GetInt64(r.GetOrdinal("document_id")),
            Skipped = r.GetInt32(r.GetOrdinal("skipped")),
            CaptureError = r.GetString(r.GetOrdinal("capture_error")),
            NextTry = r.GetDouble(r.GetOrdinal("next_try")),
            CaptureRefresh = r.GetInt32(r.GetOrdinal("capture_refresh")),
            IncomingVerified = r.GetInt32(r.GetOrdinal("incoming_verified")),
            CaptureAttempts = r.GetInt32(r.GetOrdinal("capture_attempts")),
            MessageTime = r.GetString(r.GetOrdinal("message_time")),
            CapturedAt = r.GetString(r.GetOrdinal("captured_at")),
            HiddenReason = r.GetString(r.GetOrdinal("hidden_reason")),
            MessageReceivedAt = r.IsDBNull(r.GetOrdinal("message_received_at"))
                ? null
                : r.GetDouble(r.GetOrdinal("message_received_at"))
        };
    }

    private static GrnDocumentRecord ReadDocument(SqliteDataReader r, bool includeJoins)
    {
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
            OcrRevision = r.GetInt32(r.GetOrdinal("ocr_revision")),
            Source = includeJoins && !r.IsDBNull(r.GetOrdinal("source")) ? r.GetString(r.GetOrdinal("source")) : "",
            Copies = includeJoins && !r.IsDBNull(r.GetOrdinal("copies")) ? r.GetInt64(r.GetOrdinal("copies")) : 0
        };
    }
}
