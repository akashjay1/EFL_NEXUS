using System.IO;
using System.Text.RegularExpressions;
using Google.Apis.Auth.OAuth2;
using Google.Apis.Services;
using Google.Apis.Sheets.v4;
using Google.Apis.Sheets.v4.Data;
using EflNexus.Core.Infrastructure;

namespace EflNexus.Core.Kpi;

public interface IKpiSheetWorksheet
{
    int ColCount { get; }
    IReadOnlyList<IReadOnlyList<string>> GetAllValues();
    void Resize(int cols);
    void UpdateRange(string rangeName, IReadOnlyList<IReadOnlyList<string>> values, bool raw = true);
    void AppendRow(IReadOnlyList<string> row, bool raw = true);
    void DeleteRow(int oneBasedRowNumber);
    void DeleteColumn(int oneBasedColumnNumber);
}

public sealed class GoogleSheetsWorksheet : IKpiSheetWorksheet
{
    private readonly SheetsService _service;
    private readonly string _spreadsheetId;
    private readonly string _sheetName;
    private readonly int _sheetId;

    public int ColCount { get; private set; }

    public GoogleSheetsWorksheet(SheetsService service, string spreadsheetId, string sheetName, int sheetId, int colCount)
    {
        _service = service;
        _spreadsheetId = spreadsheetId;
        _sheetName = sheetName;
        _sheetId = sheetId;
        ColCount = colCount;
    }

    public IReadOnlyList<IReadOnlyList<string>> GetAllValues()
    {
        var req = _service.Spreadsheets.Values.Get(_spreadsheetId, _sheetName);
        var resp = req.Execute();
        var result = new List<IReadOnlyList<string>>();
        if (resp.Values is null)
            return result;

        foreach (var row in resp.Values)
        {
            result.Add(row.Select(cell => cell?.ToString() ?? "").ToList());
        }
        return result;
    }

    public void Resize(int cols)
    {
        var update = new Request
        {
            UpdateSheetProperties = new UpdateSheetPropertiesRequest
            {
                Properties = new SheetProperties
                {
                    SheetId = _sheetId,
                    GridProperties = new GridProperties { ColumnCount = cols }
                },
                Fields = "gridProperties.columnCount"
            }
        };
        _service.Spreadsheets.BatchUpdate(new BatchUpdateSpreadsheetRequest { Requests = [update] }, _spreadsheetId).Execute();
        ColCount = cols;
    }

    public void UpdateRange(string rangeName, IReadOnlyList<IReadOnlyList<string>> values, bool raw = true)
    {
        var body = new ValueRange
        {
            Values = values.Select(r => (IList<object>)r.Cast<object>().ToList()).ToList()
        };
        var req = _service.Spreadsheets.Values.Update(body, _spreadsheetId, $"{_sheetName}!{rangeName}");
        req.ValueInputOption = raw
            ? SpreadsheetsResource.ValuesResource.UpdateRequest.ValueInputOptionEnum.RAW
            : SpreadsheetsResource.ValuesResource.UpdateRequest.ValueInputOptionEnum.USERENTERED;
        req.Execute();
    }

    public void AppendRow(IReadOnlyList<string> row, bool raw = true)
    {
        var body = new ValueRange
        {
            Values = new List<IList<object>> { row.Cast<object>().ToList() }
        };
        var req = _service.Spreadsheets.Values.Append(body, _spreadsheetId, $"{_sheetName}!A1");
        req.ValueInputOption = raw
            ? SpreadsheetsResource.ValuesResource.AppendRequest.ValueInputOptionEnum.RAW
            : SpreadsheetsResource.ValuesResource.AppendRequest.ValueInputOptionEnum.USERENTERED;
        req.InsertDataOption = SpreadsheetsResource.ValuesResource.AppendRequest.InsertDataOptionEnum.INSERTROWS;
        req.Execute();
    }

    public void DeleteRow(int oneBasedRowNumber)
    {
        var req = new Request
        {
            DeleteDimension = new DeleteDimensionRequest
            {
                Range = new DimensionRange
                {
                    SheetId = _sheetId,
                    Dimension = "ROWS",
                    StartIndex = oneBasedRowNumber - 1,
                    EndIndex = oneBasedRowNumber
                }
            }
        };
        _service.Spreadsheets.BatchUpdate(new BatchUpdateSpreadsheetRequest { Requests = [req] }, _spreadsheetId).Execute();
    }

    public void DeleteColumn(int oneBasedColumnNumber)
    {
        var req = new Request
        {
            DeleteDimension = new DeleteDimensionRequest
            {
                Range = new DimensionRange
                {
                    SheetId = _sheetId,
                    Dimension = "COLUMNS",
                    StartIndex = oneBasedColumnNumber - 1,
                    EndIndex = oneBasedColumnNumber
                }
            }
        };
        _service.Spreadsheets.BatchUpdate(new BatchUpdateSpreadsheetRequest { Requests = [req] }, _spreadsheetId).Execute();
        ColCount = Math.Max(0, ColCount - 1);
    }
}

public class Sheet1Log
{
    public virtual string[] BaseHeaderNames => KpiTracking.BaseHeaders;
    public virtual string[] MetadataHeaderNames => [KpiTracking.WarehouseHeader, KpiTracking.EventHeader];

    public IKpiSheetWorksheet Worksheet { get; }
    public IReadOnlyDictionary<string, JobMapEntry> JobMap { get; }

    public Sheet1Log(IKpiSheetWorksheet worksheet, IReadOnlyDictionary<string, JobMapEntry>? jobMap = null)
    {
        Worksheet = worksheet;
        JobMap = jobMap ?? new Dictionary<string, JobMapEntry>(StringComparer.Ordinal);
    }

    public IReadOnlyList<IReadOnlyList<string>> Read() => Worksheet.GetAllValues();

    public List<string> EnsureMetadata(IReadOnlyList<IReadOnlyList<string>> values)
    {
        var headers = values.Count > 0 ? values[0].ToList() : BaseHeaderNames.ToList();
        int maxRowWidth = values.Count > 0 ? values.Max(r => r.Count) : headers.Count;
        while (headers.Count < maxRowWidth)
            headers.Add("");

        if (values.Count > 0 && (headers.Count < BaseHeaderNames.Length
            || headers.Take(BaseHeaderNames.Length).Any(v => string.IsNullOrWhiteSpace(v))))
        {
            throw new InvalidOperationException("The transaction sheet requires its existing headers before KPI can sync.");
        }

        MigrateWarehouseIdColumn(headers, values);

        var nonEmptyNorms = headers.Select(KpiTracking.Norm).Where(n => !string.IsNullOrEmpty(n)).ToList();
        if (nonEmptyNorms.Distinct(StringComparer.Ordinal).Count() != nonEmptyNorms.Count)
            throw new InvalidOperationException("Sheet has duplicate headers; KPI metadata cannot be mapped safely.");

        var additions = new List<(int Column, string Name)>();
        var legacyWhColumn = KpiTracking.WarehouseColumn(values, BaseHeaderNames.Length, JobMap);
        if (legacyWhColumn.HasValue && string.IsNullOrEmpty(KpiTracking.Norm(headers[legacyWhColumn.Value])))
        {
            headers[legacyWhColumn.Value] = KpiTracking.WarehouseHeader;
            additions.Add((legacyWhColumn.Value + 1, KpiTracking.WarehouseHeader));
        }

        foreach (var name in MetadataHeaderNames)
        {
            int? existing = name == KpiTracking.WarehouseHeader
                ? KpiTracking.WarehouseColumn([headers])
                : headers.Select(KpiTracking.Norm).ToList().IndexOf(KpiTracking.Norm(name)) is int idx and >= 0 ? idx : null;

            if (!existing.HasValue)
            {
                headers.Add(name);
                additions.Add((headers.Count, name));
            }
        }

        if (additions.Count > 0 || values.Count == 0)
        {
            int width = Math.Max(headers.Count, values.Count > 0 ? values.Max(r => r.Count) : 0);
            if (Worksheet.ColCount < width)
                Worksheet.Resize(width);
            if (values.Count == 0)
                Worksheet.UpdateRange("A1", [BaseHeaderNames], raw: true);
            foreach (var (column, name) in additions)
            {
                Worksheet.UpdateRange($"{ToColumnLetters(column)}1", [[name]], raw: true);
            }
        }

        return headers;
    }

    private void MigrateWarehouseIdColumn(List<string> headers, IReadOnlyList<IReadOnlyList<string>> values)
    {
        while (true)
        {
            int legacyWhIdx = headers.FindIndex(h => KpiTracking.Norm(h) is "warehouse id" or "warehouseid");
            if (legacyWhIdx < 0)
                break;

            int whIdx = headers.FindIndex(h => KpiTracking.Norm(h) == "wh");
            if (whIdx < 0)
            {
                Worksheet.UpdateRange($"{ToColumnLetters(legacyWhIdx + 1)}1", [["WH"]], raw: true);
                headers[legacyWhIdx] = "WH";
            }
            else if (whIdx == legacyWhIdx)
            {
                headers[legacyWhIdx] = "WH";
            }
            else
            {
                if (values.Count > 1)
                {
                    bool hasDataToMove = false;
                    var colValues = new List<IReadOnlyList<string>>();
                    for (int r = 1; r < values.Count; r++)
                    {
                        var row = values[r];
                        string legacyVal = legacyWhIdx < row.Count ? (row[legacyWhIdx] ?? "").Trim() : "";
                        string currentWhVal = whIdx < row.Count ? (row[whIdx] ?? "").Trim() : "";
                        string finalVal = !string.IsNullOrEmpty(legacyVal) ? legacyVal : currentWhVal;
                        if (!string.IsNullOrEmpty(legacyVal))
                            hasDataToMove = true;
                        colValues.Add([finalVal]);

                        if (row is IList<string> mutableRow)
                        {
                            while (mutableRow.Count <= whIdx)
                                mutableRow.Add("");
                            mutableRow[whIdx] = finalVal;
                            if (legacyWhIdx < mutableRow.Count)
                                mutableRow.RemoveAt(legacyWhIdx);
                        }
                    }

                    if (hasDataToMove)
                    {
                        string whColLetter = ToColumnLetters(whIdx + 1);
                        Worksheet.UpdateRange($"{whColLetter}2", colValues, raw: true);
                    }
                }

                Worksheet.DeleteColumn(legacyWhIdx + 1);
                headers.RemoveAt(legacyWhIdx);
            }
        }
    }

    public virtual string AppendOnce(KpiLogRecord record)
    {
        var values = Read();
        var records = KpiTracking.LogRecords(values, JobMap).ToList();
        foreach (var existing in records)
        {
            if (existing.EventId == record.EventId)
                return string.IsNullOrEmpty(existing.UserId) ? "another user" : existing.UserId;
        }

        var conflict = KpiTracking.SubmissionConflict(records, record);
        if (conflict.HasValue)
        {
            if (conflict.Value.Kind == "different_warehouse")
                throw new KpiConflictException(conflict.Value.Existing);
            return string.IsNullOrEmpty(conflict.Value.Existing.UserId) ? "another user" : conflict.Value.Existing.UserId;
        }

        var headers = EnsureMetadata(values);
        var row = Enumerable.Repeat("", headers.Count).ToArray();
        row[0] = record.Timestamp;
        row[1] = record.Task;
        row[2] = record.JobId;
        row[3] = record.Status;
        row[4] = record.UserId;
        row[5] = record.UserCode;

        var whCol = KpiTracking.WarehouseColumn([headers]);
        if (whCol.HasValue)
            row[whCol.Value] = record.Warehouse;

        int evIdx = headers.Select(KpiTracking.Norm).ToList().IndexOf(KpiTracking.Norm(KpiTracking.EventHeader));
        if (evIdx >= 0)
            row[evIdx] = record.EventId;

        Worksheet.AppendRow(row, raw: true);
        return record.UserId;
    }

    public virtual int Delete(KpiLogRecord record)
    {
        var targetKey = KpiTracking.TransactionKey(record);
        var targetUser = KpiTracking.Norm(record.UserId);
        var matches = KpiTracking.LogRecords(Read(), JobMap)
            .Where(item => KpiTracking.TransactionKey(item) == targetKey && KpiTracking.Norm(item.UserId) == targetUser)
            .ToList();

        foreach (var item in matches.AsEnumerable().Reverse())
            Worksheet.DeleteRow(item.RowNumber);
        return matches.Count;
    }

    protected static string ToColumnLetters(int column)
    {
        string letters = "";
        int c = column;
        while (c > 0)
        {
            int rem = (c - 1) % 26;
            c = (c - 1) / 26;
            letters = (char)('A' + rem) + letters;
        }
        return letters;
    }
}

public sealed class Sheet2Log : Sheet1Log
{
    public override string[] BaseHeaderNames => KpiTracking.Sheet2Headers;

    public Sheet2Log(IKpiSheetWorksheet worksheet, IReadOnlyDictionary<string, JobMapEntry>? jobMap = null)
        : base(worksheet, jobMap)
    {
    }

    public string Append(KpiLogRecord record) => AppendOnce(record);

    public override string AppendOnce(KpiLogRecord record)
    {
        var values = Read();
        if (!string.IsNullOrEmpty(record.EventId))
        {
            var existing = KpiTracking.Sheet2Records(values, JobMap).FirstOrDefault(r => r.EventId == record.EventId);
            if (existing is not null)
                return string.IsNullOrEmpty(existing.UserId) ? "another user" : existing.UserId;
        }

        var headers = EnsureMetadata(values);
        var row = Enumerable.Repeat("", headers.Count).ToArray();
        row[0] = record.Timestamp;
        row[1] = record.Task;
        row[2] = record.JobId;
        row[3] = record.LoadCount;
        row[4] = record.LpCount;
        row[5] = record.UserId;
        row[6] = record.UserCode;

        var whCol = KpiTracking.WarehouseColumn([headers]);
        if (whCol.HasValue)
            row[whCol.Value] = record.Warehouse;

        int evIdx = headers.Select(KpiTracking.Norm).ToList().IndexOf(KpiTracking.Norm(KpiTracking.EventHeader));
        if (evIdx >= 0)
            row[evIdx] = !string.IsNullOrEmpty(record.EventId) ? record.EventId : Guid.NewGuid().ToString();

        Worksheet.AppendRow(row, raw: true);
        return record.UserId;
    }

    public override int Delete(KpiLogRecord record)
    {
        var matches = KpiTracking.Sheet2Records(Read(), JobMap)
            .Where(r => KpiTracking.Norm(r.JobId) == KpiTracking.Norm(record.JobId)
                        && KpiTracking.Norm(r.Task) == KpiTracking.Norm(record.Task)
                        && KpiTracking.Norm(r.Warehouse) == KpiTracking.Norm(record.Warehouse)
                        && KpiTracking.Norm(r.UserId) == KpiTracking.Norm(record.UserId))
            .ToList();

        foreach (var item in matches.AsEnumerable().Reverse())
            Worksheet.DeleteRow(item.RowNumber);
        return matches.Count;
    }
}

public static class OutboxSynchronizer
{
    public static void SyncOutbox(
        KpiOutbox outbox,
        Sheet1Log log,
        Action<KpiSyncResult>? onSaved = null,
        Func<bool>? shouldStop = null,
        Sheet2Log? countLog = null)
    {
        shouldStop ??= () => false;
        foreach (var candidate in outbox.List("pending", "deleting"))
        {
            lock (outbox.MutationLock)
            {
                var record = outbox.Get(candidate.EventId);
                if (record is null || (record.State != "pending" && record.State != "deleting"))
                    continue;
                if (shouldStop())
                    break;

                Sheet1Log? targetLog = record.Source == "sheet2" ? countLog : log;
                if (targetLog is null)
                    continue;

                try
                {
                    if (record.State == "deleting")
                    {
                        int removed = targetLog.Delete(record);
                        outbox.Mark(record.EventId, "cancelled");
                        onSaved?.Invoke(new KpiSyncResult(record with { State = "cancelled" }, "cancelled", record.UserId, Removed: removed));
                        continue;
                    }

                    var owner = targetLog.AppendOnce(record);
                    var state = KpiTracking.Norm(owner) == KpiTracking.Norm(record.UserId) ? "synced" : "conflict";
                    var err = state == "synced" ? "" : $"Already assigned by {owner}";
                    outbox.Mark(record.EventId, state, err);
                    onSaved?.Invoke(new KpiSyncResult(record with { State = state }, state, owner, err));
                }
                catch (KpiConflictException exc)
                {
                    outbox.Mark(record.EventId, "conflict", exc.Message);
                    onSaved?.Invoke(new KpiSyncResult(record with { State = "conflict" }, "conflict", exc.ConflictingRecord.UserId, exc.Message));
                }
                catch (Exception exc)
                {
                    outbox.Mark(record.EventId, record.State, exc.Message);
                    break;
                }
            }
        }
    }
}

public sealed partial class GoogleSheetsManager
{
    public const string DefaultSpreadsheetUrl = "https://docs.google.com/spreadsheets/d/1FyX5TQgoVluPYfFol6L0M813Aqov8eoC6fRk4lp1hn0/edit?usp=sharing";
    public const string Sheet1Name = "Sheet1";
    public const string Sheet2Name = "Sheet2";
    private static readonly string[] CredentialFileNames = ["credentials.json", "credentials", "credentials.txt"];

    public string SpreadsheetUrl { get; }
    public bool Connected { get; set; }
    public string? CredFileUsed { get; private set; }
    public IKpiSheetWorksheet? Worksheet1 { get; private set; }
    public IKpiSheetWorksheet? Worksheet2 { get; private set; }

    private long _lastRequestTicks;
    private readonly object _rateLock = new();

    [GeneratedRegex(@"/d/([a-zA-Z0-9-_]+)")]
    private static partial Regex SpreadsheetIdRegex();

    public GoogleSheetsManager(string spreadsheetUrl = DefaultSpreadsheetUrl)
    {
        SpreadsheetUrl = spreadsheetUrl;
    }

    private void RateLimitWait()
    {
        lock (_rateLock)
        {
            long now = Environment.TickCount64;
            long diff = now - _lastRequestTicks;
            if (diff < 100)
                Thread.Sleep((int)(100 - diff));
            _lastRequestTicks = Environment.TickCount64;
        }
    }

    public bool Connect()
    {
        try
        {
            CredFileUsed = null;
            foreach (var name in CredentialFileNames)
            {
                var p = AppPaths.ResolveResourcePath(name);
                if (File.Exists(p))
                {
                    CredFileUsed = p;
                    break;
                }
            }
            if (CredFileUsed is null)
            {
                Connected = false;
                return false;
            }

            var match = SpreadsheetIdRegex().Match(SpreadsheetUrl);
            if (!match.Success)
            {
                Connected = false;
                return false;
            }
            var spreadsheetId = match.Groups[1].Value;

            GoogleCredential credential;
            using (var fs = File.OpenRead(CredFileUsed))
            {
                credential = GoogleCredential.FromServiceAccountCredential(
                        ServiceAccountCredential.FromServiceAccountData(fs))
                    .CreateScoped(SheetsService.Scope.Spreadsheets, SheetsService.Scope.Drive);
            }

            var service = new SheetsService(new BaseClientService.Initializer
            {
                HttpClientInitializer = credential,
                ApplicationName = "EFL NEXUS"
            });

            var spreadsheet = service.Spreadsheets.Get(spreadsheetId).Execute();
            var sheet1Meta = spreadsheet.Sheets.FirstOrDefault(s => s.Properties.Title == Sheet1Name);
            var sheet2Meta = spreadsheet.Sheets.FirstOrDefault(s => s.Properties.Title == Sheet2Name);
            if (sheet1Meta is null || sheet2Meta is null)
            {
                Connected = false;
                return false;
            }

            Worksheet1 = new GoogleSheetsWorksheet(
                service, spreadsheetId, Sheet1Name,
                sheet1Meta.Properties.SheetId ?? 0,
                sheet1Meta.Properties.GridProperties?.ColumnCount ?? 26);

            Worksheet2 = new GoogleSheetsWorksheet(
                service, spreadsheetId, Sheet2Name,
                sheet2Meta.Properties.SheetId ?? 0,
                sheet2Meta.Properties.GridProperties?.ColumnCount ?? 26);

            Connected = true;
            return true;
        }
        catch
        {
            Connected = false;
            return false;
        }
    }

    public IReadOnlyList<IReadOnlyList<string>> GetAllValuesSheet1()
    {
        if (!Connected || Worksheet1 is null) return [];
        try { return Worksheet1.GetAllValues(); }
        catch { return []; }
    }

    public IReadOnlyList<IReadOnlyList<string>> GetAllValuesSheet2()
    {
        if (!Connected || Worksheet2 is null) return [];
        try { return Worksheet2.GetAllValues(); }
        catch { return []; }
    }

    public bool AppendRowSheet1(IReadOnlyList<string> rowData)
    {
        if (!Connected || Worksheet1 is null) return false;
        try { RateLimitWait(); Worksheet1.AppendRow(rowData, raw: true); return true; }
        catch { return false; }
    }

    public bool AppendRowSheet2(IReadOnlyList<string> rowData)
    {
        if (!Connected || Worksheet2 is null) return false;
        try { RateLimitWait(); Worksheet2.AppendRow(rowData, raw: true); return true; }
        catch { return false; }
    }
}
