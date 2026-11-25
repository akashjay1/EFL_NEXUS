using System.Globalization;
using System.IO;
using System.Text.Json;
using Microsoft.Data.Sqlite;

namespace EflNexus.Core.WhatsApp;

/// <summary>
/// Durable SQLite inbox store for WhatsApp GDN messages, monitor runtime/commands, and gatepass runs.
/// Exact 1:1 schema and behavior with python GDNInboxStore in whatsapp_gdn.py.
/// </summary>
public class WhatsAppGdnStore : IDisposable
{
    public string FilePath { get; }
    protected readonly SqliteConnection Db;
    protected readonly object DbLock = new();
    private bool _disposed;

    public WhatsAppGdnStore(string? path = null)
    {
        FilePath = string.IsNullOrWhiteSpace(path)
            ? Path.Combine(WhatsAppGdnParser.DataDirectory(), "inbox.sqlite3")
            : path;

        var dir = Path.GetDirectoryName(Path.GetFullPath(FilePath));
        if (!string.IsNullOrEmpty(dir))
            Directory.CreateDirectory(dir);

        var cs = new SqliteConnectionStringBuilder
        {
            DataSource = FilePath,
            Mode = SqliteOpenMode.ReadWriteCreate,
            Pooling = false,
            DefaultTimeout = 5
        }.ToString();

        Db = new SqliteConnection(cs);
        Db.Open();

        lock (DbLock)
        {
            var existingCols = GetTableColumns("requests");
            if (existingCols.Count > 0 && !existingCols.Contains("run_state"))
            {
                var stem = Path.GetFileNameWithoutExtension(FilePath);
                var backupName = $"{stem}.before-gatepass-runs-{Guid.NewGuid():N}.sqlite3";
                var backupPath = Path.Combine(dir ?? ".", backupName);
                var backupCs = new SqliteConnectionStringBuilder
                {
                    DataSource = backupPath,
                    Mode = SqliteOpenMode.ReadWriteCreate,
                    Pooling = false
                }.ToString();
                using var backupConn = new SqliteConnection(backupCs);
                backupConn.Open();
                Db.BackupDatabase(backupConn);
            }

            ExecuteNonQuery("PRAGMA journal_mode=WAL");
            ExecuteNonQuery("PRAGMA busy_timeout=5000");

            ExecuteNonQuery("""
                CREATE TABLE IF NOT EXISTS requests (
                    id INTEGER PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    raw_text TEXT NOT NULL,
                    fields TEXT NOT NULL,
                    warnings TEXT NOT NULL,
                    action TEXT NOT NULL DEFAULT 'New'
                );
                CREATE TABLE IF NOT EXISTS monitor_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS monitor_runtime (
                    run_id TEXT PRIMARY KEY,
                    heartbeat REAL NOT NULL,
                    state TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    gap INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS monitor_commands (
                    id INTEGER PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS whatsapp_messages (
                    group_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    message_time TEXT NOT NULL DEFAULT '',
                    request_id INTEGER,
                    done INTEGER NOT NULL DEFAULT 0,
                    done_reply_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(group_id, message_id)
                );
                CREATE TABLE IF NOT EXISTS gdn_message_requests (
                    group_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    request_id INTEGER NOT NULL,
                    PRIMARY KEY(group_id, message_id, request_id)
                );
                CREATE TABLE IF NOT EXISTS gatepass_runs (
                    run_id TEXT PRIMARY KEY,
                    doc_type TEXT NOT NULL,
                    record_id INTEGER NOT NULL,
                    lane TEXT NOT NULL,
                    state TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL DEFAULT ''
                );
                INSERT OR IGNORE INTO gdn_message_requests
                    SELECT group_id, message_id, request_id
                    FROM whatsapp_messages
                    WHERE request_id IS NOT NULL;
                """);

            AddColumns("requests", new Dictionary<string, string>(StringComparer.Ordinal)
            {
                ["message_time"] = "TEXT NOT NULL DEFAULT ''",
                ["hidden_reason"] = "TEXT NOT NULL DEFAULT ''",
                ["run_state"] = "TEXT NOT NULL DEFAULT 'New'",
                ["run_id"] = "TEXT NOT NULL DEFAULT ''"
            });
        }
    }

    protected internal HashSet<string> GetTableColumns(string table)
    {
        var cols = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        using var cmd = Db.CreateCommand();
        cmd.CommandText = $"PRAGMA table_info({table})";
        using var reader = cmd.ExecuteReader();
        while (reader.Read())
        {
            if (!reader.IsDBNull(1))
                cols.Add(reader.GetString(1));
        }
        return cols;
    }

    public void AddColumns(string table, IReadOnlyDictionary<string, string> definitions)
    {
        lock (DbLock)
        {
            RunImmediate(() =>
            {
                var columns = GetTableColumns(table);
                foreach (var (name, definition) in definitions)
                {
                    if (!columns.Contains(name))
                    {
                        ExecuteNonQuery($"ALTER TABLE {table} ADD COLUMN {name} {definition}");
                    }
                }
            });
        }
    }

    protected internal void RunImmediate(Action body)
    {
        ExecuteNonQuery("BEGIN IMMEDIATE");
        try
        {
            body();
            ExecuteNonQuery("COMMIT");
        }
        catch
        {
            try { ExecuteNonQuery("ROLLBACK"); } catch { }
            throw;
        }
    }

    protected internal T RunImmediate<T>(Func<T> body)
    {
        ExecuteNonQuery("BEGIN IMMEDIATE");
        try
        {
            var result = body();
            ExecuteNonQuery("COMMIT");
            return result;
        }
        catch
        {
            try { ExecuteNonQuery("ROLLBACK"); } catch { }
            throw;
        }
    }

    protected internal int ExecuteNonQuery(string sql, params (string Name, object? Value)[] parameters)
    {
        using var cmd = Db.CreateCommand();
        cmd.CommandText = sql;
        foreach (var (name, value) in parameters)
            cmd.Parameters.AddWithValue(name, value ?? DBNull.Value);
        return cmd.ExecuteNonQuery();
    }

    protected internal T? ExecuteScalar<T>(string sql, params (string Name, object? Value)[] parameters)
    {
        using var cmd = Db.CreateCommand();
        cmd.CommandText = sql;
        foreach (var (name, value) in parameters)
            cmd.Parameters.AddWithValue(name, value ?? DBNull.Value);
        var res = cmd.ExecuteScalar();
        if (res is null || res is DBNull)
            return default;
        return (T)Convert.ChangeType(res, typeof(T), CultureInfo.InvariantCulture);
    }

    protected static string RunTable(string docType) => docType switch
    {
        "GDN" => "requests",
        "GRN" => "grn_documents",
        _ => throw new KeyNotFoundException($"Unsupported doc_type: {docType}")
    };

    public string BeginGatepassRun(long recordId, string lane, string docType = "GDN")
    {
        var table = RunTable(docType);
        var runId = Guid.NewGuid().ToString("N");
        lock (DbLock)
        {
            RunImmediate(() =>
            {
                string? hiddenReason = null;
                string? runState = null;
                string? fieldsJson = null;
                string? grnWh = null;
                string? grnGp = null;

                using (var cmd = Db.CreateCommand())
                {
                    cmd.CommandText = $"SELECT * FROM {table} WHERE id=@id";
                    cmd.Parameters.AddWithValue("@id", recordId);
                    using var r = cmd.ExecuteReader();
                    if (r.Read())
                    {
                        hiddenReason = r["hidden_reason"]?.ToString() ?? "";
                        runState = r["run_state"]?.ToString() ?? "New";
                        if (docType == "GDN")
                            fieldsJson = r["fields"]?.ToString() ?? "{}";
                        else
                        {
                            grnWh = r["warehouse"]?.ToString() ?? "";
                            grnGp = r["gatepass"]?.ToString() ?? "";
                        }
                    }
                }

                if (hiddenReason is null || !string.IsNullOrEmpty(hiddenReason))
                    throw new ArgumentException("This item was cleared or marked DONE. Select an active item.");
                if (string.Equals(runState, "Running", StringComparison.Ordinal))
                    throw new ArgumentException("This gate pass is already running. Wait for it to finish or stop the lane.");

                var targetIdentity = docType == "GDN"
                    ? ExtractGdnIdentity(fieldsJson!)
                    : ((grnWh ?? "").Trim().ToLowerInvariant(), "", (grnGp ?? "").Trim().ToLowerInvariant());

                using (var otherCmd = Db.CreateCommand())
                {
                    otherCmd.CommandText = $"SELECT * FROM {table} WHERE run_state='Running'";
                    using var or = otherCmd.ExecuteReader();
                    while (or.Read())
                    {
                        var otherId = docType == "GDN"
                            ? ExtractGdnIdentity(or["fields"]?.ToString() ?? "{}")
                            : ((or["warehouse"]?.ToString() ?? "").Trim().ToLowerInvariant(), "",
                               (or["gatepass"]?.ToString() ?? "").Trim().ToLowerInvariant());
                        if (otherId == targetIdentity)
                            throw new ArgumentException("A matching gate pass is already running in another lane.");
                    }
                }

                ExecuteNonQuery(
                    $"UPDATE {table} SET run_state='Running', run_id=@runId WHERE id=@id",
                    ("@runId", runId), ("@id", recordId));
                ExecuteNonQuery(
                    "INSERT INTO gatepass_runs(run_id,doc_type,record_id,lane,state,started_at) VALUES (@runId,@docType,@recordId,@lane,'Running',@startedAt)",
                    ("@runId", runId), ("@docType", docType), ("@recordId", recordId), ("@lane", lane),
                    ("@startedAt", DateTimeOffset.UtcNow.ToString("O")));
            });
        }
        return runId;
    }

    private static (string Warehouse, string Client, string Gatepass) ExtractGdnIdentity(string fieldsJson)
    {
        var dict = JsonSerializer.Deserialize<Dictionary<string, string>>(fieldsJson) ?? [];
        dict.TryGetValue("warehouse", out var wh);
        dict.TryGetValue("client", out var cli);
        dict.TryGetValue("gatepass", out var gp);
        return ((wh ?? "").Trim().ToLowerInvariant(),
                (cli ?? "").Trim().ToLowerInvariant(),
                (gp ?? "").Trim().ToLowerInvariant());
    }

    public void FinishGatepassRun(string runId, bool completed, string detail = "")
    {
        lock (DbLock)
        {
            RunImmediate(() =>
            {
                string? docType = null;
                long recordId = 0;
                using (var cmd = Db.CreateCommand())
                {
                    cmd.CommandText = "SELECT doc_type, record_id FROM gatepass_runs WHERE run_id=@runId AND state='Running'";
                    cmd.Parameters.AddWithValue("@runId", runId);
                    using var r = cmd.ExecuteReader();
                    if (r.Read())
                    {
                        docType = r.GetString(0);
                        recordId = r.GetInt64(1);
                    }
                }
                if (docType is null)
                    return;

                var state = completed ? "Completed" : "New";
                ExecuteNonQuery(
                    "UPDATE gatepass_runs SET state=@state, detail=@detail, finished_at=@fin WHERE run_id=@runId AND state='Running'",
                    ("@state", state), ("@detail", detail), ("@fin", DateTimeOffset.UtcNow.ToString("O")), ("@runId", runId));

                var table = RunTable(docType);
                ExecuteNonQuery(
                    $"UPDATE {table} SET run_state=@state WHERE id=@recordId AND run_id=@runId AND run_state='Running'",
                    ("@state", state), ("@recordId", recordId), ("@runId", runId));
            });
        }
    }

    public void RecoverGatepassRuns(IReadOnlySet<string> activeRunIds, string docType)
    {
        var table = RunTable(docType);
        List<string> staleIds = [];
        lock (DbLock)
        {
            using var cmd = Db.CreateCommand();
            cmd.CommandText = $"SELECT run_id FROM {table} WHERE run_state='Running'";
            using var r = cmd.ExecuteReader();
            while (r.Read())
            {
                var rid = r.GetString(0);
                if (!activeRunIds.Contains(rid))
                    staleIds.Add(rid);
            }
        }
        foreach (var rid in staleIds)
            FinishGatepassRun(rid, false, "Previous run ended without a confirmed result; ready to run again.");
    }

    public (long? RecordId, string Message) Add(
        string text,
        string source = "Clipboard",
        string messageId = "",
        string groupId = "",
        string messageTime = "")
    {
        var parsed = WhatsAppGdnParser.ParseGdnMessage(text);
        if (!parsed.Candidate)
            return (null, "Not a GDN request: at least two labelled GDN fields are needed.");

        var fingerprint = WhatsAppGdnParser.ContentFingerprint(text);
        lock (DbLock)
        {
            return RunImmediate<(long?, string)>(() =>
            {
                int inserted = ExecuteNonQuery(
                    """
                    INSERT INTO requests (fingerprint, source, message_id, received_at, raw_text, fields, warnings)
                    VALUES (@fp, @src, @mid, @recv, @raw, @fields, @warn)
                    ON CONFLICT(fingerprint) DO NOTHING
                    """,
                    ("@fp", fingerprint),
                    ("@src", source),
                    ("@mid", messageId),
                    ("@recv", DateTimeOffset.UtcNow.ToString("O")),
                    ("@raw", text),
                    ("@fields", JsonSerializer.Serialize(parsed.Fields)),
                    ("@warn", JsonSerializer.Serialize(parsed.Warnings)));

                var recordId = ExecuteScalar<long>("SELECT id FROM requests WHERE fingerprint=@fp", ("@fp", fingerprint));

                if (!string.IsNullOrEmpty(groupId) && !string.IsNullOrEmpty(messageId))
                {
                    ExecuteNonQuery(
                        """
                        INSERT INTO whatsapp_messages(group_id, message_id, message_time, request_id)
                        VALUES (@gid, @mid, @mtime, @rid)
                        ON CONFLICT(group_id, message_id) DO UPDATE SET
                            request_id=excluded.request_id,
                            message_time=CASE WHEN excluded.message_time<>'' THEN excluded.message_time ELSE whatsapp_messages.message_time END
                        """,
                        ("@gid", groupId), ("@mid", messageId), ("@mtime", messageTime), ("@rid", recordId));

                    ExecuteNonQuery(
                        "UPDATE requests SET message_time=@mtime WHERE id=@rid AND message_time=''",
                        ("@mtime", messageTime), ("@rid", recordId));

                    ExecuteNonQuery(
                        "INSERT OR IGNORE INTO gdn_message_requests VALUES (@gid, @mid, @rid)",
                        ("@gid", groupId), ("@mid", messageId), ("@rid", recordId));

                    ExecuteNonQuery(
                        """
                        UPDATE requests SET hidden_reason='done'
                        WHERE id=@rid AND EXISTS (
                            SELECT 1 FROM gdn_message_requests a
                            JOIN whatsapp_messages m ON m.group_id=a.group_id AND m.message_id=a.message_id
                            WHERE a.request_id=@rid AND m.done=1
                        )
                        """,
                        ("@rid", recordId));
                }

                var hidden = ExecuteScalar<string>("SELECT hidden_reason FROM requests WHERE id=@rid", ("@rid", recordId)) ?? "";
                if (!string.IsNullOrEmpty(hidden))
                    return (null, "Request was cleared or marked DONE; retained in history.");

                return (recordId, inserted > 0 ? "Imported for review." : "Duplicate message already in inbox.");
            });
        }
    }

    public virtual void ObserveMessages(WhatsAppSnapshot snapshot)
    {
        var group = snapshot.GroupId;
        lock (DbLock)
        {
            RunImmediate(() =>
            {
                foreach (var reply in snapshot.Replies)
                {
                    if (!string.Equals((reply.Text ?? "").Trim(), "done", StringComparison.OrdinalIgnoreCase)
                        || string.IsNullOrEmpty(reply.ReplyTo))
                        continue;

                    ExecuteNonQuery(
                        """
                        INSERT INTO whatsapp_messages(group_id, message_id, done, done_reply_id)
                        VALUES (@gid, @replyTo, 1, @replyId)
                        ON CONFLICT(group_id, message_id) DO UPDATE SET
                            done=1, done_reply_id=excluded.done_reply_id
                        """,
                        ("@gid", group), ("@replyTo", reply.ReplyTo), ("@replyId", reply.Id));
                }

                foreach (var msg in snapshot.Messages.Concat(snapshot.ObservedOriginals))
                {
                    var mid = msg.Id;
                    var stamp = msg.MessageTime ?? "";
                    ExecuteNonQuery(
                        """
                        INSERT INTO whatsapp_messages(group_id, message_id, message_time)
                        VALUES (@gid, @mid, @mtime)
                        ON CONFLICT(group_id, message_id) DO UPDATE SET
                            message_time=CASE WHEN excluded.message_time<>'' THEN excluded.message_time ELSE whatsapp_messages.message_time END
                        """,
                        ("@gid", group), ("@mid", mid), ("@mtime", stamp));

                    ExecuteNonQuery(
                        """
                        UPDATE whatsapp_messages
                        SET request_id=coalesce((SELECT id FROM requests WHERE fingerprint=@fp), request_id)
                        WHERE group_id=@gid AND message_id=@mid
                        """,
                        ("@fp", WhatsAppGdnParser.ContentFingerprint(msg.Text)),
                        ("@gid", group), ("@mid", mid));

                    ExecuteNonQuery(
                        """
                        INSERT OR IGNORE INTO gdn_message_requests
                        SELECT group_id, message_id, request_id FROM whatsapp_messages
                        WHERE group_id=@gid AND message_id=@mid AND request_id IS NOT NULL
                        """,
                        ("@gid", group), ("@mid", mid));

                    ExecuteNonQuery(
                        """
                        UPDATE requests SET message_time=@mtime
                        WHERE message_time='' AND id IN (
                            SELECT request_id FROM whatsapp_messages WHERE group_id=@gid AND message_id=@mid
                        )
                        """,
                        ("@mtime", stamp), ("@gid", group), ("@mid", mid));
                }

                ExecuteNonQuery(
                    """
                    UPDATE requests SET hidden_reason='done'
                    WHERE hidden_reason<>'done' AND id IN (
                        SELECT a.request_id FROM gdn_message_requests a
                        JOIN whatsapp_messages m ON m.group_id=a.group_id AND m.message_id=a.message_id
                        WHERE m.done=1
                    )
                    """);
            });
        }

        var notice = snapshot.UnresolvedDone.Count > 0
            ? "A DONE reply could not be linked to its original message; that request remains visible."
            : "";
        if (!snapshot.ReplyScanPending && Setting("done_reply_notice", "") != notice)
            SetSetting("done_reply_notice", notice);
    }

    public virtual int ClearList()
    {
        lock (DbLock)
        {
            return RunImmediate(() => ExecuteNonQuery("UPDATE requests SET hidden_reason='cleared' WHERE hidden_reason=''"));
        }
    }

    public Dictionary<string, Dictionary<string, string>> KnownDoneReplies()
    {
        var result = new Dictionary<string, Dictionary<string, string>>(StringComparer.Ordinal);
        lock (DbLock)
        {
            using var cmd = Db.CreateCommand();
            cmd.CommandText = "SELECT group_id, message_id, done_reply_id FROM whatsapp_messages WHERE done=1 AND done_reply_id<>''";
            using var r = cmd.ExecuteReader();
            while (r.Read())
            {
                var gid = r.GetString(0);
                var mid = r.GetString(1);
                var replyId = r.GetString(2);
                if (!result.TryGetValue(gid, out var map))
                {
                    map = new Dictionary<string, string>(StringComparer.Ordinal);
                    result[gid] = map;
                }
                map[replyId] = mid;
            }
        }
        return result;
    }

    public T Setting<T>(string key, T defaultValue)
    {
        lock (DbLock)
        {
            var raw = ExecuteScalar<string>("SELECT value FROM monitor_settings WHERE key=@k", ("@k", key));
            if (string.IsNullOrEmpty(raw))
                return defaultValue;
            try
            {
                return JsonSerializer.Deserialize<T>(raw) ?? defaultValue;
            }
            catch
            {
                return defaultValue;
            }
        }
    }

    public JsonElement? SettingJson(string key)
    {
        lock (DbLock)
        {
            var raw = ExecuteScalar<string>("SELECT value FROM monitor_settings WHERE key=@k", ("@k", key));
            if (string.IsNullOrEmpty(raw))
                return null;
            using var doc = JsonDocument.Parse(raw);
            return doc.RootElement.Clone();
        }
    }

    public void SetSetting<T>(string key, T value)
    {
        SetSettings(new Dictionary<string, object?> { [key] = value });
    }

    public void SetSettings(IReadOnlyDictionary<string, object?> settings)
    {
        lock (DbLock)
        {
            RunImmediate(() =>
            {
                foreach (var (key, value) in settings)
                {
                    ExecuteNonQuery(
                        "INSERT INTO monitor_settings VALUES (@k, @v) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        ("@k", key), ("@v", JsonSerializer.Serialize(value)));
                }
            });
        }
    }

    public MonitorRuntimeInfo? Runtime(string runId)
    {
        lock (DbLock)
        {
            using var cmd = Db.CreateCommand();
            cmd.CommandText = "SELECT run_id, heartbeat, state, detail, gap FROM monitor_runtime WHERE run_id=@rid";
            cmd.Parameters.AddWithValue("@rid", runId);
            using var r = cmd.ExecuteReader();
            if (!r.Read())
                return null;
            return new MonitorRuntimeInfo
            {
                RunId = r.GetString(0),
                Heartbeat = r.GetDouble(1),
                State = r.GetString(2),
                Detail = r.GetString(3),
                Gap = r.GetInt32(4)
            };
        }
    }

    public void Report(string runId, string state, string detail = "", bool gap = false)
    {
        var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
        lock (DbLock)
        {
            RunImmediate(() =>
            {
                ExecuteNonQuery(
                    """
                    INSERT INTO monitor_runtime VALUES (@rid, @hb, @st, @dt, @gap)
                    ON CONFLICT(run_id) DO UPDATE SET
                        heartbeat=excluded.heartbeat, state=excluded.state,
                        detail=excluded.detail, gap=excluded.gap
                    """,
                    ("@rid", runId), ("@hb", now), ("@st", state), ("@dt", detail), ("@gap", gap ? 1 : 0));
            });
        }
    }

    public void Command(string runId, string action, object? payload = null)
    {
        lock (DbLock)
        {
            RunImmediate(() =>
            {
                ExecuteNonQuery(
                    "INSERT INTO monitor_commands (run_id, action, payload) VALUES (@rid, @act, @pl)",
                    ("@rid", runId), ("@act", action), ("@pl", JsonSerializer.Serialize(payload ?? new { })));
            });
        }
    }

    public List<(string Action, JsonElement Payload)> TakeCommands(string runId)
    {
        lock (DbLock)
        {
            return RunImmediate(() =>
            {
                var list = new List<(string, JsonElement)>();
                using (var cmd = Db.CreateCommand())
                {
                    cmd.CommandText = "SELECT action, payload FROM monitor_commands WHERE run_id=@rid ORDER BY id";
                    cmd.Parameters.AddWithValue("@rid", runId);
                    using var r = cmd.ExecuteReader();
                    while (r.Read())
                    {
                        var action = r.GetString(0);
                        var rawPayload = r.GetString(1);
                        using var doc = JsonDocument.Parse(string.IsNullOrWhiteSpace(rawPayload) ? "{}" : rawPayload);
                        list.Add((action, doc.RootElement.Clone()));
                    }
                }
                ExecuteNonQuery("DELETE FROM monitor_commands WHERE run_id=@rid", ("@rid", runId));
                return list;
            });
        }
    }

    public (long Total, long NewCount) Counts()
    {
        lock (DbLock)
        {
            using var cmd = Db.CreateCommand();
            cmd.CommandText = "SELECT COUNT(*), COALESCE(SUM(action='New'), 0) FROM requests WHERE hidden_reason=''";
            using var r = cmd.ExecuteReader();
            if (r.Read())
                return (r.GetInt64(0), r.IsDBNull(1) ? 0 : r.GetInt64(1));
            return (0, 0);
        }
    }

    public long Version()
    {
        lock (DbLock)
        {
            return ExecuteScalar<long>("PRAGMA data_version");
        }
    }

    public List<GdnRequestRecord> Records(bool includeHidden = false)
    {
        var where = includeHidden ? "" : " WHERE hidden_reason=''";
        var list = new List<GdnRequestRecord>();
        lock (DbLock)
        {
            using var cmd = Db.CreateCommand();
            cmd.CommandText = $"SELECT id, fingerprint, source, message_id, received_at, raw_text, fields, warnings, action, message_time, hidden_reason, run_state, run_id FROM requests{where} ORDER BY id DESC";
            using var r = cmd.ExecuteReader();
            while (r.Read())
                list.Add(ReadRecord(r));
        }
        return list;
    }

    public GdnRequestRecord? Get(long recordId)
    {
        lock (DbLock)
        {
            using var cmd = Db.CreateCommand();
            cmd.CommandText = "SELECT id, fingerprint, source, message_id, received_at, raw_text, fields, warnings, action, message_time, hidden_reason, run_state, run_id FROM requests WHERE id=@id";
            cmd.Parameters.AddWithValue("@id", recordId);
            using var r = cmd.ExecuteReader();
            return r.Read() ? ReadRecord(r) : null;
        }
    }

    private static GdnRequestRecord ReadRecord(SqliteDataReader r)
    {
        var fieldsJson = r.GetString(6);
        var warningsJson = r.GetString(7);
        return new GdnRequestRecord
        {
            Id = r.GetInt64(0),
            Fingerprint = r.GetString(1),
            Source = r.GetString(2),
            MessageId = r.GetString(3),
            ReceivedAt = r.GetString(4),
            RawText = r.GetString(5),
            Fields = JsonSerializer.Deserialize<Dictionary<string, string>>(fieldsJson) ?? new(StringComparer.Ordinal),
            Warnings = JsonSerializer.Deserialize<List<string>>(warningsJson) ?? [],
            Action = r.GetString(8),
            MessageTime = r.GetString(9),
            HiddenReason = r.GetString(10),
            RunState = r.GetString(11),
            RunId = r.GetString(12)
        };
    }

    public void SaveReview(long recordId, IReadOnlyDictionary<string, string> fields, string action = "Reviewed")
    {
        lock (DbLock)
        {
            RunImmediate(() =>
            {
                int changed = ExecuteNonQuery(
                    "UPDATE requests SET fields=@fields, action=@action WHERE id=@id AND hidden_reason='' AND run_state<>'Running'",
                    ("@fields", JsonSerializer.Serialize(fields)),
                    ("@action", action),
                    ("@id", recordId));
                if (changed == 0)
                    throw new ArgumentException("This request is running, cleared, or marked DONE. Select an idle active request.");
            });
        }
    }

    public List<GdnRequestRecord> Related(IReadOnlyDictionary<string, string> fields, long? excludeId = null)
    {
        var wh = (fields.TryGetValue("warehouse", out var w) ? w : "").Trim().ToLowerInvariant();
        var cli = (fields.TryGetValue("client", out var c) ? c : "").Trim().ToLowerInvariant();
        var gp = (fields.TryGetValue("gatepass", out var g) ? g : "").Trim().ToLowerInvariant();
        if (string.IsNullOrEmpty(wh) || string.IsNullOrEmpty(cli) || string.IsNullOrEmpty(gp))
            return [];

        var all = Records(includeHidden: true);
        return all.Where(r =>
            r.Id != excludeId &&
            (r.Fields.TryGetValue("warehouse", out var rw) ? rw : "").Trim().ToLowerInvariant() == wh &&
            (r.Fields.TryGetValue("client", out var rc) ? rc : "").Trim().ToLowerInvariant() == cli &&
            (r.Fields.TryGetValue("gatepass", out var rg) ? rg : "").Trim().ToLowerInvariant() == gp).ToList();
    }

    public void Close() => Dispose();

    public void Dispose()
    {
        if (_disposed)
            return;
        _disposed = true;
        Db.Dispose();
        GC.SuppressFinalize(this);
    }
}
