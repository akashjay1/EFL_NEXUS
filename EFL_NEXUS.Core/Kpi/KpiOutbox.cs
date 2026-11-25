using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.Data.Sqlite;
using EflNexus.Core.Infrastructure;

namespace EflNexus.Core.Kpi;

internal sealed class OutboxPayload
{
    [JsonPropertyName("job_id")]
    public string JobId { get; set; } = "";

    [JsonPropertyName("task")]
    public string Task { get; set; } = "";

    [JsonPropertyName("warehouse")]
    public string Warehouse { get; set; } = "";

    [JsonPropertyName("user_id")]
    public string UserId { get; set; } = "";

    [JsonPropertyName("user_code")]
    public string UserCode { get; set; } = "";

    [JsonPropertyName("status")]
    public string Status { get; set; } = "";

    [JsonPropertyName("timestamp")]
    public string Timestamp { get; set; } = "";

    [JsonPropertyName("load_count")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? LoadCount { get; set; }

    [JsonPropertyName("lp_count")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? LpCount { get; set; }

    [JsonPropertyName("source")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Source { get; set; }

    [JsonPropertyName("event_id")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? EventId { get; set; }
}

public sealed class KpiOutbox
{
    public string DbPath { get; }
    public object Lock { get; } = new();
    public object MutationLock { get; } = new();

    public KpiOutbox(string? path = null)
    {
        DbPath = string.IsNullOrWhiteSpace(path)
            ? Path.Combine(AppPaths.LocalAppDataDir, "kpi_outbox.sqlite3")
            : path;

        var dir = Path.GetDirectoryName(Path.GetFullPath(DbPath));
        if (!string.IsNullOrEmpty(dir))
            Directory.CreateDirectory(dir);

        using var db = OpenConnection();
        using var cmd = db.CreateCommand();
        cmd.CommandText = """
            CREATE TABLE IF NOT EXISTS submissions (
                event_id TEXT PRIMARY KEY,
                identity TEXT NOT NULL,
                payload TEXT NOT NULL,
                state TEXT NOT NULL,
                error TEXT NOT NULL DEFAULT ''
            );
            CREATE UNIQUE INDEX IF NOT EXISTS active_identity
                ON submissions(identity) WHERE state != 'cancelled';
            """;
        cmd.ExecuteNonQuery();
    }

    private SqliteConnection OpenConnection()
    {
        var conn = new SqliteConnection($"Data Source={DbPath};Default Timeout=30;Pooling=False");
        conn.Open();
        return conn;
    }

    private static string BuildIdentity(KpiLogRecord record)
    {
        var tuple = new[]
        {
            KpiTracking.Norm(record.Task),
            KpiTracking.Norm(record.JobId),
            KpiTracking.Norm(record.Status),
            KpiTracking.Norm(record.Warehouse)
        };
        return JsonSerializer.Serialize(tuple);
    }

    private static string ComputeState(KpiLogRecord record)
    {
        if (string.IsNullOrEmpty(record.UserId) || string.IsNullOrEmpty(record.UserCode))
            return "needs_profile";
        return !string.IsNullOrEmpty(record.Warehouse) ? "pending" : "needs_warehouse";
    }

    private static KpiLogRecord ReadRow(SqliteDataReader reader, bool duplicate = false)
    {
        var eventId = reader.GetString(0);
        var payloadJson = reader.GetString(1);
        var state = reader.GetString(2);
        var error = reader.GetString(3);
        var p = JsonSerializer.Deserialize<OutboxPayload>(payloadJson) ?? new OutboxPayload();
        return new KpiLogRecord
        {
            EventId = eventId,
            JobId = p.JobId,
            Task = p.Task,
            Warehouse = p.Warehouse,
            UserId = p.UserId,
            UserCode = p.UserCode,
            Status = p.Status,
            Timestamp = p.Timestamp,
            LoadCount = p.LoadCount ?? "",
            LpCount = p.LpCount ?? "",
            Source = p.Source ?? "",
            State = state,
            Error = error,
            Duplicate = duplicate
        };
    }

    private static OutboxPayload ToPayload(KpiLogRecord r, bool includeSheet2Fields = false)
        => new()
        {
            JobId = r.JobId,
            Task = r.Task,
            Warehouse = r.Warehouse,
            UserId = r.UserId,
            UserCode = r.UserCode,
            Status = r.Status,
            Timestamp = r.Timestamp,
            LoadCount = includeSheet2Fields ? r.LoadCount : null,
            LpCount = includeSheet2Fields ? r.LpCount : null,
            Source = includeSheet2Fields ? "sheet2" : null,
            EventId = includeSheet2Fields && !string.IsNullOrEmpty(r.EventId) ? r.EventId : null
        };

    public KpiLogRecord Capture(
        string jobId,
        string task,
        string site,
        string? userId,
        string? userCode,
        string status = "New",
        string? timestamp = null)
    {
        var record = new KpiLogRecord
        {
            JobId = (jobId ?? "").Trim(),
            Task = (task ?? "").Trim(),
            Warehouse = KpiTracking.Warehouse(site),
            UserId = (userId ?? "").Trim(),
            UserCode = (userCode ?? "").Trim(),
            Status = status,
            Timestamp = string.IsNullOrEmpty(timestamp) ? KpiTracking.RegistrationTimestamp() : timestamp
        };

        if (string.IsNullOrEmpty(record.JobId) || !KpiTracking.Transactions.ContainsKey(KpiTracking.Norm(task)))
            throw new ArgumentException("A supported KPI task and job ID are required.");

        lock (Lock)
        {
            using var db = OpenConnection();
            using var tx = db.BeginTransaction(System.Data.IsolationLevel.Serializable);

            var active = new List<KpiLogRecord>();
            using (var cmd = db.CreateCommand())
            {
                cmd.Transaction = tx;
                cmd.CommandText = "SELECT event_id, payload, state, error FROM submissions WHERE state NOT IN ('cancelled','conflict')";
                using var r = cmd.ExecuteReader();
                while (r.Read())
                {
                    var rec = ReadRow(r);
                    if (rec.Source != "sheet2")
                        active.Add(rec);
                }
            }

            var conflict = KpiTracking.SubmissionConflict(active, record);
            if (conflict.HasValue)
            {
                if (conflict.Value.Kind == "different_warehouse")
                    throw new KpiConflictException(conflict.Value.Existing);
                return conflict.Value.Existing with { Duplicate = true };
            }

            var identity = BuildIdentity(record);
            using (var cmd = db.CreateCommand())
            {
                cmd.Transaction = tx;
                cmd.CommandText = "SELECT event_id, payload, state, error FROM submissions WHERE identity=$id AND state!='cancelled'";
                cmd.Parameters.AddWithValue("$id", identity);
                using var r = cmd.ExecuteReader();
                if (r.Read())
                    return ReadRow(r);
            }

            var eventId = Guid.NewGuid().ToString();
            var state = ComputeState(record);
            using (var ins = db.CreateCommand())
            {
                ins.Transaction = tx;
                ins.CommandText = "INSERT INTO submissions(event_id, identity, payload, state) VALUES($eid, $id, $pl, $st)";
                ins.Parameters.AddWithValue("$eid", eventId);
                ins.Parameters.AddWithValue("$id", identity);
                ins.Parameters.AddWithValue("$pl", JsonSerializer.Serialize(ToPayload(record)));
                ins.Parameters.AddWithValue("$st", state);
                ins.ExecuteNonQuery();
            }

            tx.Commit();
            return record with { EventId = eventId, State = state, Error = "" };
        }
    }

    public KpiLogRecord CaptureCounts(KpiLogRecord input)
    {
        var taskNorm = KpiTracking.Norm(input.Task);
        if (!KpiTracking.CountTransactions.ContainsKey(taskNorm) || taskNorm == "allocation/backorders")
            throw new ArgumentException("Select a supported transaction name; Allocation and Backorders are separate.");

        var loadVal = KpiTracking.CountValue(input.LoadCount);
        var lpVal = KpiTracking.CountValue(input.LpCount);
        var record = input with
        {
            Source = "sheet2",
            Status = "",
            LoadCount = loadVal.HasValue ? loadVal.Value.ToString() : "",
            LpCount = lpVal.HasValue ? lpVal.Value.ToString() : "",
            Warehouse = KpiTracking.Warehouse(input.Warehouse)
        };

        if (string.IsNullOrEmpty(record.JobId) || string.IsNullOrEmpty(record.Warehouse)
            || string.IsNullOrEmpty(record.UserId) || string.IsNullOrEmpty(record.UserCode))
        {
            throw new ArgumentException("Job ID, warehouse and KPI profile are required.");
        }

        static bool FieldsEqual(KpiLogRecord a, KpiLogRecord b)
            => KpiTracking.Norm(a.JobId) == KpiTracking.Norm(b.JobId)
               && KpiTracking.Norm(a.Task) == KpiTracking.Norm(b.Task)
               && KpiTracking.Norm(a.Warehouse) == KpiTracking.Norm(b.Warehouse)
               && KpiTracking.Norm(a.UserId) == KpiTracking.Norm(b.UserId)
               && KpiTracking.Norm(a.UserCode) == KpiTracking.Norm(b.UserCode)
               && KpiTracking.Norm(a.LoadCount) == KpiTracking.Norm(b.LoadCount)
               && KpiTracking.Norm(a.LpCount) == KpiTracking.Norm(b.LpCount);

        lock (Lock)
        {
            using var db = OpenConnection();
            using var tx = db.BeginTransaction(System.Data.IsolationLevel.Serializable);

            if (!string.IsNullOrEmpty(record.EventId))
            {
                using var chk = db.CreateCommand();
                chk.Transaction = tx;
                chk.CommandText = "SELECT 1 FROM submissions WHERE event_id=$eid AND state='cancelled'";
                chk.Parameters.AddWithValue("$eid", record.EventId);
                if (chk.ExecuteScalar() is not null)
                    throw new ArgumentException("This KPI entry was cancelled. Submit a new entry.");
            }

            using (var cmd = db.CreateCommand())
            {
                cmd.Transaction = tx;
                cmd.CommandText = "SELECT event_id, payload, state, error FROM submissions WHERE state!='cancelled'";
                using var r = cmd.ExecuteReader();
                while (r.Read())
                {
                    var existing = ReadRow(r);
                    if (existing.Source != "sheet2")
                        continue;

                    bool sameEvent = !string.IsNullOrEmpty(record.EventId) && record.EventId == existing.EventId;
                    bool samePending = string.IsNullOrEmpty(record.EventId) && existing.State == "pending" && FieldsEqual(existing, record);
                    if (sameEvent || samePending)
                    {
                        if (!FieldsEqual(existing, record))
                            throw new ArgumentException("A KPI event ID cannot be reused for another transaction.");
                        return existing;
                    }
                }
            }

            var eventId = !string.IsNullOrEmpty(record.EventId) ? record.EventId : Guid.NewGuid().ToString();
            var ts = !string.IsNullOrEmpty(record.Timestamp) ? record.Timestamp : KpiTracking.RegistrationTimestamp();
            record = record with { Timestamp = ts, EventId = eventId, State = "pending", Error = "" };

            using (var ins = db.CreateCommand())
            {
                ins.Transaction = tx;
                ins.CommandText = "INSERT INTO submissions(event_id, identity, payload, state) VALUES($eid, $id, $pl, 'pending')";
                ins.Parameters.AddWithValue("$eid", eventId);
                ins.Parameters.AddWithValue("$id", "sheet2:" + eventId);
                ins.Parameters.AddWithValue("$pl", JsonSerializer.Serialize(ToPayload(record, includeSheet2Fields: true)));
                ins.ExecuteNonQuery();
            }

            tx.Commit();
            return record;
        }
    }

    public List<KpiLogRecord> List(params string[] states)
    {
        HashSet<string>? filter = states is { Length: > 0 } ? new HashSet<string>(states, StringComparer.Ordinal) : null;
        lock (Lock)
        {
            using var db = OpenConnection();
            using var cmd = db.CreateCommand();
            cmd.CommandText = "SELECT event_id, payload, state, error FROM submissions ORDER BY rowid";
            using var r = cmd.ExecuteReader();
            var list = new List<KpiLogRecord>();
            while (r.Read())
            {
                var rec = ReadRow(r);
                if (filter is null || filter.Contains(rec.State))
                    list.Add(rec);
            }
            return list;
        }
    }

    public KpiLogRecord? Get(string eventId)
    {
        lock (Lock)
        {
            using var db = OpenConnection();
            using var cmd = db.CreateCommand();
            cmd.CommandText = "SELECT event_id, payload, state, error FROM submissions WHERE event_id=$eid";
            cmd.Parameters.AddWithValue("$eid", eventId);
            using var r = cmd.ExecuteReader();
            return r.Read() ? ReadRow(r) : null;
        }
    }

    public KpiLogRecord Resolve(string eventId, string site, string userId, string userCode)
    {
        lock (Lock)
        {
            using var db = OpenConnection();
            using var tx = db.BeginTransaction();

            KpiLogRecord? record = null;
            using (var cmd = db.CreateCommand())
            {
                cmd.Transaction = tx;
                cmd.CommandText = "SELECT event_id, payload, state, error FROM submissions WHERE event_id=$eid";
                cmd.Parameters.AddWithValue("$eid", eventId);
                using var r = cmd.ExecuteReader();
                if (r.Read())
                    record = ReadRow(r);
            }

            if (record is null || (record.State != "needs_profile" && record.State != "needs_warehouse"))
                throw new ArgumentException("This pending KPI entry cannot be edited.");

            if (!string.IsNullOrEmpty(record.UserId) && KpiTracking.Norm(record.UserId) != KpiTracking.Norm(userId))
                throw new ArgumentException($"Configure KPI profile for {record.UserId} to submit this job.");

            record = record with { Warehouse = KpiTracking.Warehouse(site) };
            if (string.IsNullOrEmpty(record.UserId))
                record = record with { UserId = userId, UserCode = userCode };

            var state = ComputeState(record);
            if (state != "pending")
                throw new ArgumentException("Configure the KPI profile and select a warehouse.");

            var active = new List<KpiLogRecord>();
            using (var cmd = db.CreateCommand())
            {
                cmd.Transaction = tx;
                cmd.CommandText = "SELECT event_id, payload, state, error FROM submissions WHERE state NOT IN ('cancelled','conflict') AND event_id!=$eid";
                cmd.Parameters.AddWithValue("$eid", eventId);
                using var r = cmd.ExecuteReader();
                while (r.Read())
                {
                    var item = ReadRow(r);
                    if (item.Source != "sheet2")
                        active.Add(item);
                }
            }

            var conflict = KpiTracking.SubmissionConflict(active, record);
            if (conflict.HasValue)
            {
                if (conflict.Value.Kind == "different_warehouse")
                    throw new KpiConflictException(conflict.Value.Existing);

                using var cancelCmd = db.CreateCommand();
                cancelCmd.Transaction = tx;
                cancelCmd.CommandText = "UPDATE submissions SET state='cancelled' WHERE event_id=$eid";
                cancelCmd.Parameters.AddWithValue("$eid", eventId);
                cancelCmd.ExecuteNonQuery();
                tx.Commit();
                return conflict.Value.Existing with { Duplicate = true };
            }

            var identity = BuildIdentity(record);
            try
            {
                using var upd = db.CreateCommand();
                upd.Transaction = tx;
                upd.CommandText = "UPDATE submissions SET identity=$id, payload=$pl, state=$st, error='' WHERE event_id=$eid";
                upd.Parameters.AddWithValue("$id", identity);
                upd.Parameters.AddWithValue("$pl", JsonSerializer.Serialize(ToPayload(record)));
                upd.Parameters.AddWithValue("$st", state);
                upd.Parameters.AddWithValue("$eid", eventId);
                upd.ExecuteNonQuery();
                tx.Commit();
                return record with { State = state, Error = "" };
            }
            catch (SqliteException ex) when (ex.SqliteErrorCode == 19) // Constraint violation
            {
                using var colCmd = db.CreateCommand();
                colCmd.Transaction = tx;
                colCmd.CommandText = "SELECT event_id, payload, state, error FROM submissions WHERE identity=$id AND state!='cancelled'";
                colCmd.Parameters.AddWithValue("$id", identity);
                using var cr = colCmd.ExecuteReader();
                if (cr.Read())
                {
                    var found = ReadRow(cr);
                    cr.Close();
                    using var cancelCmd = db.CreateCommand();
                    cancelCmd.Transaction = tx;
                    cancelCmd.CommandText = "UPDATE submissions SET state='cancelled' WHERE event_id=$eid";
                    cancelCmd.Parameters.AddWithValue("$eid", eventId);
                    cancelCmd.ExecuteNonQuery();
                    tx.Commit();
                    return found;
                }
                throw new ArgumentException("This job already has a KPI entry for that warehouse.", ex);
            }
        }
    }

    public void Mark(string eventId, string state, string error = "")
    {
        lock (Lock)
        {
            using var db = OpenConnection();
            using var cmd = db.CreateCommand();
            cmd.CommandText = "UPDATE submissions SET state=$st, error=$err WHERE event_id=$eid";
            cmd.Parameters.AddWithValue("$st", state);
            cmd.Parameters.AddWithValue("$err", error ?? "");
            cmd.Parameters.AddWithValue("$eid", eventId);
            cmd.ExecuteNonQuery();
        }
    }

    public void Cancel(KpiLogRecord record)
    {
        var targetKey = KpiTracking.TransactionKey(record);
        var targetUser = KpiTracking.Norm(record.UserId);
        lock (Lock)
        {
            using var db = OpenConnection();
            using var tx = db.BeginTransaction();
            var toCancel = new List<string>();
            using (var cmd = db.CreateCommand())
            {
                cmd.Transaction = tx;
                cmd.CommandText = "SELECT event_id, payload, state, error FROM submissions WHERE state!='cancelled'";
                using var r = cmd.ExecuteReader();
                while (r.Read())
                {
                    var item = ReadRow(r);
                    if (KpiTracking.TransactionKey(item) == targetKey && KpiTracking.Norm(item.UserId) == targetUser)
                        toCancel.Add(item.EventId);
                }
            }
            foreach (var eid in toCancel)
            {
                using var upd = db.CreateCommand();
                upd.Transaction = tx;
                upd.CommandText = "UPDATE submissions SET state='cancelled' WHERE event_id=$eid";
                upd.Parameters.AddWithValue("$eid", eid);
                upd.ExecuteNonQuery();
            }
            tx.Commit();
        }
    }

    public KpiLogRecord RequestDelete(KpiLogRecord record)
    {
        lock (MutationLock)
        {
            var key = KpiTracking.TransactionKey(record);
            var existing = List().FirstOrDefault(r => r.State != "cancelled" && KpiTracking.TransactionKey(r) == key);
            KpiLogRecord item;
            if (existing is not null)
            {
                item = existing;
            }
            else
            {
                item = record with
                {
                    Timestamp = KpiTracking.RegistrationTimestamp(),
                    EventId = Guid.NewGuid().ToString()
                };
                lock (Lock)
                {
                    using var db = OpenConnection();
                    using var cmd = db.CreateCommand();
                    cmd.CommandText = "INSERT INTO submissions(event_id, identity, payload, state) VALUES($eid, $id, $pl, 'deleting')";
                    cmd.Parameters.AddWithValue("$eid", item.EventId);
                    cmd.Parameters.AddWithValue("$id", BuildIdentity(item));
                    cmd.Parameters.AddWithValue("$pl", JsonSerializer.Serialize(ToPayload(item)));
                    cmd.ExecuteNonQuery();
                }
            }

            if (KpiTracking.Norm(item.UserId) != KpiTracking.Norm(record.UserId))
                throw new ArgumentException($"Already assigned by {item.UserId}");

            Mark(item.EventId, "deleting");
            return Get(item.EventId)!;
        }
    }
}
