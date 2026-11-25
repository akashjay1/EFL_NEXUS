using System.Globalization;
using System.Text.RegularExpressions;
using EflNexus.Core.Infrastructure;

namespace EflNexus.Core.Kpi;

public sealed record KpiLogRecord
{
    public int RowNumber { get; init; }
    public string Timestamp { get; init; } = "";
    public string Task { get; init; } = "";
    public string JobId { get; init; } = "";
    public string Status { get; init; } = "";
    public string UserId { get; init; } = "";
    public string UserCode { get; init; } = "";
    public string EventId { get; init; } = "";
    public string Warehouse { get; init; } = "";
    public string LoadCount { get; init; } = "";
    public string LpCount { get; init; } = "";
    public string Source { get; init; } = "";
    public string State { get; init; } = "";
    public string Error { get; init; } = "";
    public bool Duplicate { get; init; }
}

public sealed record KpiExportRow(
    DateTime RegisteredDate,
    TimeSpan? RegisteredTime,
    string UserName,
    string UserCode,
    string Site,
    string TransactionName,
    string JobOrReferenceId,
    string Status,
    int EntryCount,
    int? LoadIdCount,
    int? LpCount,
    string TCode,
    string Customer = "");

public sealed record KpiSummaryRow(
    DateTime RegisteredDate,
    string UserName,
    string UserCode,
    string Site,
    string TransactionName,
    string Uom,
    int? DirectQuantity,
    int CreationCredit,
    int? KpiTotal);

public sealed record KpiSyncResult(
    KpiLogRecord Record,
    string State,
    string Owner,
    string Error = "",
    int Removed = 0);

public sealed class KpiConflictException : Exception
{
    public KpiLogRecord ConflictingRecord { get; }

    public KpiConflictException(KpiLogRecord record)
        : base($"Job ID: {record.JobId} | Warehouse: {record.Warehouse} | User: {(string.IsNullOrEmpty(record.UserId) ? "another user" : record.UserId)}")
    {
        ConflictingRecord = record;
    }
}

public static partial class KpiTracking
{
    public static readonly string[] Warehouses =
    [
        "LPPL", "ESKD", "NUGE", "EGDC", "MYBR", "INMM01", "IDBTH", "MYJB", "LPSP", "LPIC"
    ];

    public const string DefaultWarehouse = "LPPL";

    public static readonly string[] ExportHeaders =
    [
        "Registered Date", "Registered Time", "User Name", "User Code", "Site",
        "Transaction Name", "Job / Reference ID", "Status", "Entry Count",
        "Load ID Count", "LP Count", "T-Code"
    ];

    public static readonly string[] SummaryHeaders =
    [
        "Registered Date", "User Name", "User Code", "Site", "Transaction Name",
        "UOM", "Direct Quantity", "Creation Credit from Reconciliation", "KPI Total"
    ];

    public static readonly Dictionary<string, (string TCode, string Title)> Transactions = new(StringComparer.Ordinal)
    {
        ["gdn reconciliation"] = ("CSSTR0324", "GDN Reconciliation"),
        ["grn reconciliation"] = ("CSSTR0324", "GRN Reconciliation"),
        ["grn creation"] = ("CSSTR0325", "GRN Creation"),
        ["gdn creation"] = ("CSSTR0326", "GDN Creation"),
        ["load plan or asn"] = ("CSSTR0327", "Load Plan / ASN"),
    };

    public static readonly Dictionary<string, (string TCode, string Title)> CountTransactions = new(StringComparer.Ordinal)
    {
        ["load audit"] = ("", "Load Audit"),
        ["shipping"] = ("", "Shipping"),
        ["load transfer"] = ("", "Load Transfer"),
        ["allocation"] = ("", "Allocation"),
        ["backorders"] = ("", "Backorders"),
        ["allocation/backorders"] = ("", "Allocation/Backorders"),
    };

    public static readonly TimeSpan SriLankaOffset = TimeSpan.FromHours(5) + TimeSpan.FromMinutes(30);

    public static readonly string[] BaseHeaders = ["Timestamp", "Task", "Job ID", "Status", "User ID", "User Code"];
    public static readonly string[] Sheet2Headers = ["Timestamp", "Task", "Job ID", "Load ID Count", "LP Count", "User ID", "User Code"];
    public const string WarehouseHeader = "WH";
    public const string EventHeader = "KPI Event ID";

    private static readonly string[] TimestampFormats =
    [
        "dd-MM-yyyy HH:mm:ss", "dd-MM-yyyy HH:mm", "dd-MM-yyyy",
        "d-M-yyyy HH:mm:ss", "d-M-yyyy HH:mm", "d-M-yyyy",
        "d-M-yyyy H:m:s", "d-M-yyyy H:m",
        "MM/dd/yyyy HH:mm:ss", "MM/dd/yyyy HH:mm", "MM/dd/yyyy",
        "M/d/yyyy HH:mm:ss", "M/d/yyyy HH:mm", "M/d/yyyy",
        "M/d/yyyy H:m:s", "M/d/yyyy H:m",
        "yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd HH:mm", "yyyy-MM-dd",
        "yyyy-M-d H:m:s", "yyyy-M-d H:m", "yyyy-M-d"
    ];

    [GeneratedRegex(@"\s+")]
    private static partial Regex WhitespaceRegex();

    public static string Norm(object? value)
    {
        var s = (value?.ToString() ?? "").Trim().TrimEnd(':');
        return WhitespaceRegex().Replace(s, " ").Trim().ToLowerInvariant();
    }

    public static string Warehouse(object? value)
        => (value?.ToString() ?? "").Trim().ToUpperInvariant();

    public static DateTime KpiNow()
        => DateTimeOffset.UtcNow.ToOffset(SriLankaOffset).DateTime;

    public static string RegistrationTimestamp()
        => KpiNow().ToString("dd-MM-yyyy HH:mm:ss", CultureInfo.InvariantCulture);

    public static DateTime ParseTimestamp(object? value)
    {
        if (value is DateTime dt)
            return dt.Kind == DateTimeKind.Utc ? TimeZoneInfo.ConvertTimeFromUtc(dt, TimeZoneInfo.CreateCustomTimeZone("SL", SriLankaOffset, "SL", "SL")) : dt;

        var text = (value?.ToString() ?? "").Trim();
        if (text.Contains('T') || text.EndsWith('Z') || text.Contains('+'))
        {
            if (DateTimeOffset.TryParse(text, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind, out var dto))
                return dto.ToOffset(SriLankaOffset).DateTime;
        }

        if (DateTime.TryParseExact(text, TimestampFormats, CultureInfo.InvariantCulture, DateTimeStyles.None, out var parsed))
            return parsed;

        throw new FormatException($"Invalid KPI timestamp: '{value}'");
    }

    public static string ParseTimestampDate(string? ts)
    {
        if (string.IsNullOrWhiteSpace(ts))
            return "";
        var clean = ts.Trim();
        if (DateTime.TryParseExact(clean, TimestampFormats, CultureInfo.InvariantCulture, DateTimeStyles.None, out var parsed))
            return parsed.ToString("dd-MM-yyyy", CultureInfo.InvariantCulture);
        if (clean.Contains(' '))
            return clean.Split(' ')[0];
        return clean;
    }

    public static int? CountValue(object? value)
    {
        var s = value?.ToString()?.Trim();
        if (string.IsNullOrEmpty(s))
            return null;
        if (!decimal.TryParse(s, NumberStyles.Number, CultureInfo.InvariantCulture, out var number))
            throw new ArgumentException($"Invalid KPI count: '{value}'");
        if (number < 0 || decimal.Truncate(number) != number || number > int.MaxValue)
            throw new ArgumentException($"Invalid KPI count: '{value}'");
        return (int)number;
    }

    public static string ResolveWarehouse(string? jobId, string? value = "", IReadOnlyDictionary<string, JobMapEntry>? jobMap = null)
    {
        var wh = Warehouse(value);
        if (!string.IsNullOrEmpty(wh))
            return wh;

        var key = Norm(jobId);
        if (jobMap is not null)
        {
            foreach (var record in jobMap.Values)
            {
                if (record is not null && Norm(record.JobId) == key)
                {
                    var recWh = Warehouse(record.Warehouse);
                    if (!string.IsNullOrEmpty(recWh))
                        return recWh;
                }
            }
        }
        return "";
    }

    public static string ResolveCustomer(string? jobId, IReadOnlyDictionary<string, JobMapEntry>? jobMap = null)
    {
        if (string.IsNullOrWhiteSpace(jobId) || jobMap is null)
            return "";

        var key = Norm(jobId);
        if (jobMap.TryGetValue(key, out var direct) && !string.IsNullOrWhiteSpace(direct?.Client))
            return direct.Client.Trim();

        foreach (var record in jobMap.Values)
        {
            if (record is null) continue;
            if (Norm(record.JobId) == key && !string.IsNullOrWhiteSpace(record.Client))
                return record.Client.Trim();
            if (Norm(record.WarfId) == key && !string.IsNullOrWhiteSpace(record.Client))
                return record.Client.Trim();
        }
        return "";
    }

    public static List<string> WarehouseOptions(IReadOnlyDictionary<string, JobMapEntry>? jobMap = null)
    {
        var found = new HashSet<string>(StringComparer.Ordinal);
        if (jobMap is not null)
        {
            foreach (var r in jobMap.Values)
            {
                var w = Warehouse(r?.Warehouse);
                if (!string.IsNullOrEmpty(w))
                    found.Add(w);
            }
        }
        var baseSet = new HashSet<string>(Warehouses, StringComparer.Ordinal);
        var result = new List<string>(Warehouses);
        result.AddRange(found.Where(w => !baseSet.Contains(w)).OrderBy(w => w, StringComparer.Ordinal));
        return result;
    }

    public static int? WarehouseColumn(IReadOnlyList<IReadOnlyList<string>> values, int position = 6, IReadOnlyDictionary<string, JobMapEntry>? jobMap = null)
    {
        var headers = values.Count > 0 ? values[0].Select(h => Norm(h)).ToList() : [];
        foreach (var alias in new[] { WarehouseHeader, "WH", "Warehouse", "Warehouse ID", "SITE" })
        {
            int idx = headers.IndexOf(Norm(alias));
            if (idx >= 0)
                return idx;
        }
        if (position < headers.Count && !string.IsNullOrEmpty(headers[position]))
            return null;

        var valid = new HashSet<string>(WarehouseOptions(jobMap), StringComparer.Ordinal);
        var cells = new HashSet<string>(StringComparer.Ordinal);
        for (int i = 1; i < values.Count; i++)
        {
            var row = values[i];
            if (position < row.Count)
            {
                var w = Warehouse(row[position]);
                if (!string.IsNullOrEmpty(w))
                    cells.Add(w);
            }
        }
        return cells.Count > 0 && cells.IsSubsetOf(valid) ? position : null;
    }

    public static IEnumerable<KpiLogRecord> LogRecords(IReadOnlyList<IReadOnlyList<string>>? values, IReadOnlyDictionary<string, JobMapEntry>? jobMap = null)
    {
        if (values is null || values.Count == 0)
            yield break;

        var headers = values[0].Select(h => Norm(h)).ToList();
        var indexes = new Dictionary<string, int?>(StringComparer.Ordinal);
        for (int i = 0; i < BaseHeaders.Length; i++)
        {
            int idx = headers.IndexOf(Norm(BaseHeaders[i]));
            indexes[BaseHeaders[i]] = idx >= 0 ? idx : i;
        }
        indexes[WarehouseHeader] = WarehouseColumn(values, 6, jobMap);
        int evIdx = headers.IndexOf(Norm(EventHeader));
        indexes[EventHeader] = evIdx >= 0 ? evIdx : null;

        for (int number = 1; number < values.Count; number++)
        {
            var row = values[number];
            if (!row.Any(v => !string.IsNullOrWhiteSpace(v)))
                continue;

            string Get(string name)
            {
                var i = indexes[name];
                return i.HasValue && i.Value < row.Count ? (row[i.Value] ?? "").Trim() : "";
            }

            var jobId = Get("Job ID");
            yield return new KpiLogRecord
            {
                RowNumber = number + 1,
                Timestamp = Get("Timestamp"),
                Task = Get("Task"),
                JobId = jobId,
                Status = Get("Status"),
                UserId = Get("User ID"),
                UserCode = Get("User Code"),
                EventId = Get(EventHeader),
                Warehouse = ResolveWarehouse(jobId, Get(WarehouseHeader), jobMap)
            };
        }
    }

    public static IEnumerable<KpiLogRecord> Sheet2Records(IReadOnlyList<IReadOnlyList<string>>? values, IReadOnlyDictionary<string, JobMapEntry>? jobMap = null)
    {
        if (values is null || values.Count == 0)
            yield break;

        var headers = values[0].Select(h => Norm(h)).ToList();
        int? whCol = WarehouseColumn(values, 7, jobMap);
        var indexes = new int[Sheet2Headers.Length];
        for (int i = 0; i < Sheet2Headers.Length; i++)
        {
            int idx = headers.IndexOf(Norm(Sheet2Headers[i]));
            indexes[i] = idx >= 0 ? idx : i;
        }
        int evIdx = headers.IndexOf(Norm(EventHeader));
        int? eventCol = evIdx >= 0 ? evIdx : null;

        for (int number = 1; number < values.Count; number++)
        {
            var row = values[number];
            if (!row.Any(v => !string.IsNullOrWhiteSpace(v)))
                continue;

            string GetIdx(int? idx) => idx.HasValue && idx.Value < row.Count ? (row[idx.Value] ?? "").Trim() : "";

            var jobId = GetIdx(indexes[2]);
            yield return new KpiLogRecord
            {
                RowNumber = number + 1,
                Timestamp = GetIdx(indexes[0]),
                Task = GetIdx(indexes[1]),
                JobId = jobId,
                LoadCount = GetIdx(indexes[3]),
                LpCount = GetIdx(indexes[4]),
                UserId = GetIdx(indexes[5]),
                UserCode = GetIdx(indexes[6]),
                EventId = GetIdx(eventCol),
                Warehouse = ResolveWarehouse(jobId, GetIdx(whCol), jobMap),
                Source = "sheet2"
            };
        }
    }

    public static (string Task, string JobId, string Status, string Warehouse) TransactionKey(KpiLogRecord record)
        => (Norm(record.Task), Norm(record.JobId), Norm(record.Status), Norm(record.Warehouse));

    public static Dictionary<(string JobId, string Warehouse), string> JobAssignments(
        IReadOnlyList<IReadOnlyList<string>>? values,
        IReadOnlyDictionary<string, JobMapEntry>? jobMap = null)
    {
        var owners = new Dictionary<(string JobId, string Warehouse), Dictionary<string, string>>();
        foreach (var record in LogRecords(values, jobMap))
        {
            var t = Norm(record.Task);
            if (t is not ("gdn creation" or "grn creation" or "gdn reconciliation" or "grn reconciliation"))
                continue;
            if (string.IsNullOrEmpty(record.JobId) || string.IsNullOrEmpty(record.UserId))
                continue;
            var key = (Norm(record.JobId), Norm(record.Warehouse));
            if (!owners.TryGetValue(key, out var map))
            {
                map = new Dictionary<string, string>(StringComparer.Ordinal);
                owners[key] = map;
            }
            map[Norm(record.UserId)] = record.UserId;
        }

        return owners.ToDictionary(
            kvp => kvp.Key,
            kvp => string.Join(", ", kvp.Value.Keys.OrderBy(k => k, StringComparer.Ordinal).Select(k => kvp.Value[k])));
    }

    public static string TaskGroup(string? task)
    {
        var t = Norm(task);
        return t switch
        {
            "gdn creation" or "gdn reconciliation" => "gdn",
            "grn creation" or "grn reconciliation" => "grn",
            _ => t
        };
    }

    public static (string Kind, KpiLogRecord Existing)? SubmissionConflict(IEnumerable<KpiLogRecord> records, KpiLogRecord target)
    {
        (string, KpiLogRecord)? sameGroup = null;
        foreach (var record in records)
        {
            if (Norm(record.JobId) != Norm(target.JobId))
                continue;
            if (!string.IsNullOrEmpty(record.Warehouse) && !string.IsNullOrEmpty(target.Warehouse)
                && Norm(record.Warehouse) != Norm(target.Warehouse))
            {
                return ("different_warehouse", record);
            }
            if (TaskGroup(record.Task) == TaskGroup(target.Task) && Norm(record.Status) == Norm(target.Status))
            {
                sameGroup = ("same_warehouse", record);
            }
        }
        return sameGroup;
    }

    public static string RecordIdentity(KpiLogRecord record)
    {
        if (!string.IsNullOrEmpty(record.EventId))
            return "event:" + record.EventId;
        return "legacy:" + string.Join("\u001F",
            Norm(record.Timestamp), Norm(record.Task), Norm(record.JobId), Norm(record.Status),
            Norm(record.Warehouse), Norm(record.UserId), Norm(record.UserCode),
            Norm(record.LoadCount), Norm(record.LpCount));
    }

    public static List<KpiExportRow> BuildExportRows(
        IReadOnlyList<IReadOnlyList<string>>? values1,
        string userId,
        string userCode,
        DateTime startDate,
        DateTime endDate,
        IReadOnlyDictionary<string, JobMapEntry>? jobMap = null,
        IReadOnlyList<IReadOnlyList<string>>? values2 = null)
    {
        var rows = new List<KpiExportRow>();
        var names = new Dictionary<string, (string TCode, string Title)>(Transactions, StringComparer.Ordinal);
        foreach (var kv in CountTransactions)
            names[kv.Key] = kv.Value;

        IEnumerable<KpiLogRecord>[] streams = [LogRecords(values1, jobMap), Sheet2Records(values2, jobMap)];
        foreach (var records in streams)
        {
            var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (var record in records)
            {
                if (Norm(record.UserId) != Norm(userId))
                    continue;
                var stamp = ParseTimestamp(record.Timestamp);
                if (stamp.Date < startDate.Date || stamp.Date > endDate.Date)
                    continue;
                var id = RecordIdentity(record);
                if (!seen.Add(id))
                    continue;

                var taskNorm = Norm(record.Task);
                var (code, title) = names.TryGetValue(taskNorm, out var found)
                    ? found
                    : ("", record.Task.Trim().TrimEnd(':'));
                bool hasTime = record.Timestamp.Contains(':');
                var customer = ResolveCustomer(record.JobId, jobMap);
                rows.Add(new KpiExportRow(
                    stamp.Date,
                    hasTime ? stamp.TimeOfDay : null,
                    record.UserId,
                    !string.IsNullOrWhiteSpace(userCode) ? userCode.Trim() : (record.UserCode ?? string.Empty),
                    string.IsNullOrEmpty(record.Warehouse) ? "Unassigned" : record.Warehouse,
                    title,
                    record.JobId,
                    record.Status,
                    1,
                    CountValue(record.LoadCount),
                    CountValue(record.LpCount),
                    code,
                    customer));
            }
        }

        return rows
            .OrderBy(r => r.RegisteredDate)
            .ThenBy(r => r.RegisteredTime ?? TimeSpan.Zero)
            .ThenBy(r => r.Site, StringComparer.Ordinal)
            .ThenBy(r => r.TransactionName, StringComparer.Ordinal)
            .ThenBy(r => r.JobOrReferenceId, StringComparer.Ordinal)
            .ToList();
    }

    public static List<KpiSummaryRow> BuildSummaryRows(IEnumerable<KpiExportRow> rows)
    {
        var direct = new Dictionary<(DateTime Day, string User, string Code, string Site, string Task, string Uom), int>();
        var credits = new Dictionary<(DateTime Day, string User, string Code, string Site, string Task, string Uom), int>();
        var unavailable = new HashSet<(DateTime Day, string User, string Code, string Site, string Task, string Uom)>();

        void Add(Dictionary<(DateTime, string, string, string, string, string), int> dict, (DateTime, string, string, string, string, string) k, int amount)
            => dict[k] = dict.GetValueOrDefault(k) + amount;

        foreach (var row in rows)
        {
            var task = row.TransactionName;
            if (task is "GRN Reconciliation" or "GDN Reconciliation")
            {
                Add(direct, (row.RegisteredDate, row.UserName, row.UserCode, row.Site, task, "Per Reconciliation Report"), row.EntryCount);
                Add(credits, (row.RegisteredDate, row.UserName, row.UserCode, row.Site, task.Replace("Reconciliation", "Creation"), "Per vehicle"), row.EntryCount);
            }
            else if (task is "GRN Creation" or "GDN Creation")
            {
                Add(direct, (row.RegisteredDate, row.UserName, row.UserCode, row.Site, task, "Per vehicle"), row.EntryCount);
            }
            else if (task == "Load Plan / ASN")
            {
                Add(direct, (row.RegisteredDate, row.UserName, row.UserCode, row.Site, task, "Per load plan"), row.EntryCount);
            }
            else
            {
                if (row.LoadIdCount.HasValue || task is "Load Audit" or "Shipping" or "Load Transfer")
                {
                    var key = (row.RegisteredDate, row.UserName, row.UserCode, row.Site, task, "Load ID Count");
                    Add(direct, key, row.LoadIdCount ?? 0);
                    if (!row.LoadIdCount.HasValue)
                        unavailable.Add(key);
                }
                if (row.LpCount.HasValue || task is "Load Transfer" or "Allocation" or "Backorders" or "Allocation/Backorders")
                {
                    var key = (row.RegisteredDate, row.UserName, row.UserCode, row.Site, task, "LP Count");
                    Add(direct, key, row.LpCount ?? 0);
                    if (!row.LpCount.HasValue)
                        unavailable.Add(key);
                }
                if (!row.LoadIdCount.HasValue && !row.LpCount.HasValue && !CountTransactions.ContainsKey(Norm(task)))
                {
                    Add(direct, (row.RegisteredDate, row.UserName, row.UserCode, row.Site, task, "Recorded entry"), row.EntryCount);
                }
            }
        }

        var allKeys = direct.Keys.Union(credits.Keys)
            .OrderBy(k => k.Day)
            .ThenBy(k => k.User, StringComparer.Ordinal)
            .ThenBy(k => k.Code, StringComparer.Ordinal)
            .ThenBy(k => k.Site, StringComparer.Ordinal)
            .ThenBy(k => k.Task, StringComparer.Ordinal)
            .ThenBy(k => k.Uom, StringComparer.Ordinal);

        var result = new List<KpiSummaryRow>();
        foreach (var key in allKeys)
        {
            bool isUnavailable = unavailable.Contains(key);
            int dirVal = direct.GetValueOrDefault(key);
            int credVal = credits.GetValueOrDefault(key);
            result.Add(new KpiSummaryRow(
                key.Day, key.User, key.Code, key.Site, key.Task, key.Uom,
                isUnavailable ? null : dirVal,
                credVal,
                isUnavailable ? null : dirVal + credVal));
        }
        return result;
    }
}
