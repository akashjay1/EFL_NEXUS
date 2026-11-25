using System.Globalization;
using System.IO;
using System.Text.Json;
using Microsoft.Data.Sqlite;

namespace EflNexus.Core.Monitoring;

public sealed class ExpiredHistoryException(string message) : InvalidOperationException(message);

public sealed class OfflineQueue : IDisposable
{
    public const int DefaultLimit = 10000;
    private readonly SqliteConnection _db;
    private readonly int _limit;

    public OfflineQueue(string path, int limit = DefaultLimit, int timeoutSeconds = 2)
    {
        var dir = Path.GetDirectoryName(Path.GetFullPath(path));
        if (!string.IsNullOrEmpty(dir))
            Directory.CreateDirectory(dir);

        _limit = limit;
        _db = new SqliteConnection(new SqliteConnectionStringBuilder
        {
            DataSource = path,
            DefaultTimeout = timeoutSeconds
        }.ToString());
        _db.Open();

        using var cmd = _db.CreateCommand();
        cmd.CommandText = """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS launches(
                id TEXT PRIMARY KEY,
                credential TEXT NOT NULL,
                next_sequence INTEGER NOT NULL DEFAULT 1,
                ack INTEGER NOT NULL DEFAULT 0,
                live_sequence INTEGER NOT NULL DEFAULT 0,
                ended INTEGER NOT NULL DEFAULT 0,
                dropped INTEGER NOT NULL DEFAULT 0,
                last_stamp TEXT NOT NULL,
                blocked INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS outbox(
                session TEXT NOT NULL REFERENCES launches(id),
                sequence INTEGER NOT NULL,
                body TEXT NOT NULL,
                PRIMARY KEY(session, sequence)
            );
            CREATE TABLE IF NOT EXISTS expired_history(
                session TEXT,
                sequence INTEGER,
                body TEXT,
                PRIMARY KEY(session, sequence)
            );
            CREATE TABLE IF NOT EXISTS pending_gaps(
                id INTEGER PRIMARY KEY CHECK(id=1),
                count INTEGER NOT NULL
            );
            INSERT OR IGNORE INTO pending_gaps VALUES(1, 0);
            """;
        cmd.ExecuteNonQuery();
    }

    public static string UtcNowIso()
        => DateTimeOffset.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fff'Z'", CultureInfo.InvariantCulture);

    public static Dictionary<string, object?> BuildEvent(long sequence, string kind, object? payload, string? timestamp = null)
        => new(StringComparer.Ordinal)
        {
            ["id"] = Guid.NewGuid().ToString(),
            ["sequence"] = sequence,
            ["type"] = kind,
            ["timestamp"] = timestamp ?? UtcNowIso(),
            ["payload"] = payload
        };

    public void Create(string session, string credential, object? payload)
    {
        using var tx = _db.BeginTransaction();
        long count = ExecuteScalarLong("SELECT COUNT(*) FROM outbox", tx);
        long opened = ExecuteScalarLong("SELECT COUNT(*) FROM launches WHERE ended=0", tx);
        if (count + opened * 2 + 3 > _limit)
            throw new InvalidOperationException("Outbox capacity reserved for existing session shutdowns.");

        using (var cmd = _db.CreateCommand())
        {
            cmd.Transaction = tx;
            cmd.CommandText = "INSERT INTO launches(id,credential,last_stamp) VALUES(@s,@c,@t)";
            cmd.Parameters.AddWithValue("@s", session);
            cmd.Parameters.AddWithValue("@c", credential);
            cmd.Parameters.AddWithValue("@t", UtcNowIso());
            cmd.ExecuteNonQuery();
        }
        AppendInternal(session, "started", payload, tx);
        tx.Commit();
    }

    private void AppendInternal(string session, string kind, object? payload, SqliteTransaction tx)
    {
        long seq;
        string lastStamp;
        using (var cmd = _db.CreateCommand())
        {
            cmd.Transaction = tx;
            cmd.CommandText = "SELECT next_sequence,last_stamp FROM launches WHERE id=@s";
            cmd.Parameters.AddWithValue("@s", session);
            using var reader = cmd.ExecuteReader();
            if (!reader.Read())
                throw new InvalidOperationException($"Unknown session '{session}'.");
            seq = reader.GetInt64(0);
            lastStamp = reader.GetString(1);
        }

        var now = UtcNowIso();
        var stamp = string.CompareOrdinal(lastStamp, now) >= 0 ? lastStamp : now;
        var bodyJson = JsonSerializer.Serialize(BuildEvent(seq, kind, payload, stamp));

        using (var ins = _db.CreateCommand())
        {
            ins.Transaction = tx;
            ins.CommandText = "INSERT INTO outbox VALUES(@s,@q,@b)";
            ins.Parameters.AddWithValue("@s", session);
            ins.Parameters.AddWithValue("@q", seq);
            ins.Parameters.AddWithValue("@b", bodyJson);
            ins.ExecuteNonQuery();
        }

        int ended = (kind is "closed" or "unclean") ? 1 : 0;
        using (var upd = _db.CreateCommand())
        {
            upd.Transaction = tx;
            upd.CommandText = "UPDATE launches SET next_sequence=@nq,last_stamp=@t,ended=@e WHERE id=@s";
            upd.Parameters.AddWithValue("@nq", seq + 1);
            upd.Parameters.AddWithValue("@t", stamp);
            upd.Parameters.AddWithValue("@e", ended);
            upd.Parameters.AddWithValue("@s", session);
            upd.ExecuteNonQuery();
        }
    }

    public bool Append(string session, string kind, object? payload)
    {
        using var tx = _db.BeginTransaction();
        long ended, dropped;
        using (var cmd = _db.CreateCommand())
        {
            cmd.Transaction = tx;
            cmd.CommandText = "SELECT ended,dropped FROM launches WHERE id=@s";
            cmd.Parameters.AddWithValue("@s", session);
            using var r = cmd.ExecuteReader();
            if (!r.Read())
                return false;
            ended = r.GetInt64(0);
            dropped = r.GetInt64(1);
        }

        if (ended != 0)
            return false;

        if (kind is "closed" or "unclean")
        {
            if (dropped > 0)
            {
                AppendInternal(session, "recording_gap", new { dropped_events = dropped }, tx);
                ExecuteNonQuery("UPDATE launches SET dropped=0 WHERE id=@s", tx, ("@s", session));
            }
            AppendInternal(session, kind, payload, tx);
            tx.Commit();
            return true;
        }

        long count = ExecuteScalarLong("SELECT COUNT(*) FROM outbox", tx);
        long opened = ExecuteScalarLong("SELECT COUNT(*) FROM launches WHERE ended=0", tx);
        if (count + opened * 2 >= _limit)
        {
            ExecuteNonQuery("UPDATE launches SET dropped=dropped+1 WHERE id=@s", tx, ("@s", session));
            tx.Commit();
            return false;
        }

        AppendInternal(session, kind, payload, tx);
        tx.Commit();
        return true;
    }

    public List<JsonElement> Batch(string session)
    {
        var events = new List<JsonElement>();
        using (var cmd = _db.CreateCommand())
        {
            cmd.CommandText = "SELECT body FROM outbox WHERE session=@s ORDER BY sequence LIMIT 25";
            cmd.Parameters.AddWithValue("@s", session);
            using var r = cmd.ExecuteReader();
            while (r.Read())
            {
                using var doc = JsonDocument.Parse(r.GetString(0));
                events.Add(doc.RootElement.Clone());
            }
        }

        var cutoff = DateTimeOffset.UtcNow.AddDays(-7);
        foreach (var e in events)
        {
            if (e.TryGetProperty("timestamp", out var tsEl)
                && DateTimeOffset.TryParse(tsEl.GetString(), CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal, out var ts)
                && ts < cutoff)
            {
                ArchiveExpired(session);
                throw new ExpiredHistoryException("Seven-day history limit exceeded; history retained for review.");
            }
        }
        return events;
    }

    public void Acknowledge(string session, long high)
    {
        using var tx = _db.BeginTransaction();
        long ack, nextSeq;
        using (var cmd = _db.CreateCommand())
        {
            cmd.Transaction = tx;
            cmd.CommandText = "SELECT ack,next_sequence FROM launches WHERE id=@s";
            cmd.Parameters.AddWithValue("@s", session);
            using var r = cmd.ExecuteReader();
            if (!r.Read()) throw new InvalidOperationException("Invalid session.");
            ack = r.GetInt64(0);
            nextSeq = r.GetInt64(1);
        }

        if (high < ack || high >= nextSeq)
            throw new ArgumentException("Invalid server sequence; history retained.");

        ExecuteNonQuery("DELETE FROM outbox WHERE session=@s AND sequence<=@h", tx, ("@s", session), ("@h", high));
        ExecuteNonQuery("UPDATE launches SET ack=@h WHERE id=@s", tx, ("@h", high), ("@s", session));

        long dropped = 0, ended = 1;
        using (var cmd = _db.CreateCommand())
        {
            cmd.Transaction = tx;
            cmd.CommandText = "SELECT dropped,ended FROM launches WHERE id=@s";
            cmd.Parameters.AddWithValue("@s", session);
            using var r = cmd.ExecuteReader();
            if (r.Read())
            {
                dropped = r.GetInt64(0);
                ended = r.GetInt64(1);
            }
        }

        long opened = ExecuteScalarLong("SELECT COUNT(*) FROM launches WHERE ended=0", tx);
        long totalOutbox = ExecuteScalarLong("SELECT COUNT(*) FROM outbox", tx);
        if (dropped > 0 && ended == 0 && totalOutbox + opened * 2 < _limit)
        {
            AppendInternal(session, "recording_gap", new { dropped_events = dropped }, tx);
            ExecuteNonQuery("UPDATE launches SET dropped=0 WHERE id=@s", tx, ("@s", session));
        }
        tx.Commit();
    }

    public long ArchiveExpired(string session)
    {
        using var tx = _db.BeginTransaction();
        long count = ExecuteScalarLong("SELECT COUNT(*) FROM outbox WHERE session=@s", tx, ("@s", session));
        ExecuteNonQuery("INSERT OR IGNORE INTO expired_history SELECT session,sequence,body FROM outbox WHERE session=@s", tx, ("@s", session));
        ExecuteNonQuery("DELETE FROM outbox WHERE session=@s", tx, ("@s", session));
        long dropped = ExecuteScalarLong("SELECT dropped FROM launches WHERE id=@s", tx, ("@s", session));
        ExecuteNonQuery("UPDATE launches SET ended=1,blocked=1,dropped=0 WHERE id=@s", tx, ("@s", session));
        ExecuteNonQuery("UPDATE pending_gaps SET count=count+@c WHERE id=1", tx, ("@c", count + dropped));
        tx.Commit();
        return count + dropped;
    }

    public bool ReportGap(string session)
    {
        using var tx = _db.BeginTransaction();
        long count = ExecuteScalarLong("SELECT count FROM pending_gaps WHERE id=1", tx);
        if (count > 0)
        {
            long occupied = ExecuteScalarLong("SELECT COUNT(*) FROM outbox", tx);
            long opened = ExecuteScalarLong("SELECT COUNT(*) FROM launches WHERE ended=0", tx);
            if (occupied + opened * 2 >= _limit)
                return false;
            AppendInternal(session, "recording_gap", new { dropped_events = count }, tx);
            ExecuteNonQuery("UPDATE pending_gaps SET count=0 WHERE id=1", tx);
        }
        tx.Commit();
        return true;
    }

    public Dictionary<string, object> Live(string session, double idleSeconds)
    {
        using var tx = _db.BeginTransaction();
        ExecuteNonQuery("UPDATE launches SET live_sequence=live_sequence+1 WHERE id=@s", tx, ("@s", session));
        long seq = ExecuteScalarLong("SELECT live_sequence FROM launches WHERE id=@s", tx, ("@s", session));
        tx.Commit();
        return new Dictionary<string, object>(StringComparer.Ordinal)
        {
            ["sequence"] = seq,
            ["sent_at"] = UtcNowIso(),
            ["idle_seconds"] = Math.Min(604800, Math.Max(0, (int)idleSeconds))
        };
    }

    public List<string> ListUnclosedSessions() => QueryStrings("SELECT id FROM launches WHERE ended=0");

    public List<(string SessionId, string CredentialId)> ListActiveLaunches()
    {
        var list = new List<(string, string)>();
        using var cmd = _db.CreateCommand();
        cmd.CommandText = "SELECT id,credential FROM launches WHERE blocked=0";
        using var r = cmd.ExecuteReader();
        while (r.Read())
            list.Add((r.GetString(0), r.GetString(1)));
        return list;
    }

    public long BlockedCount() => ExecuteScalarLong("SELECT COUNT(*) FROM launches WHERE blocked=1", null);

    public void MarkBlocked(string sessionId)
    {
        using var tx = _db.BeginTransaction();
        ExecuteNonQuery("UPDATE launches SET blocked=1 WHERE id=@s", tx, ("@s", sessionId));
        tx.Commit();
    }

    private List<string> QueryStrings(string sql)
    {
        var list = new List<string>();
        using var cmd = _db.CreateCommand();
        cmd.CommandText = sql;
        using var r = cmd.ExecuteReader();
        while (r.Read())
            list.Add(r.GetString(0));
        return list;
    }

    private long ExecuteScalarLong(string sql, SqliteTransaction? tx, params (string Key, object Value)[] parameters)
    {
        using var cmd = _db.CreateCommand();
        cmd.Transaction = tx;
        cmd.CommandText = sql;
        foreach (var (k, v) in parameters)
            cmd.Parameters.AddWithValue(k, v);
        return Convert.ToInt64(cmd.ExecuteScalar() ?? 0L);
    }

    private void ExecuteNonQuery(string sql, SqliteTransaction tx, params (string Key, object Value)[] parameters)
    {
        using var cmd = _db.CreateCommand();
        cmd.Transaction = tx;
        cmd.CommandText = sql;
        foreach (var (k, v) in parameters)
            cmd.Parameters.AddWithValue(k, v);
        cmd.ExecuteNonQuery();
    }

    public void Dispose() => _db.Dispose();
}
