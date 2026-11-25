using System.Collections.Concurrent;
using System.IO;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.RegularExpressions;
using ClosedXML.Excel;
using EflNexus.Core.Infrastructure;

namespace EflNexus.Core.OutlookEmail;

public sealed class SentLogRecord
{
    public string Type { get; set; } = "";
    public string Date { get; set; } = "";
    public string Time { get; set; } = "";
    public string Number { get; set; } = "";
    public string Warehouse { get; set; } = "General";
}

public sealed record SentLogCounts(int Gdn, int Grn);

public sealed partial class SentLogStore
{
    public const string SendTypeGdn = "GDN";
    public const string SendTypeGrn = "GRN";

    private static readonly ConcurrentDictionary<string, object> PathLocks = new(StringComparer.OrdinalIgnoreCase);
    private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(10) };

    private readonly ConfigStore _configStore;
    public string ExcelPath { get; }

    public SentLogStore(ConfigStore configStore, string? excelPath = null)
    {
        _configStore = configStore;
        ExcelPath = string.IsNullOrWhiteSpace(excelPath)
            ? Path.Combine(AppPaths.AppDir, "sent_log.xlsx")
            : excelPath;
    }

    private object GetPathLock()
    {
        var key = Path.GetFullPath(ExcelPath);
        return PathLocks.GetOrAdd(key, _ => new object());
    }

    [GeneratedRegex(@"^(\d{1,2})/(\d{1,2})/(\d{4})$")]
    private static partial Regex SlashDateRegex();

    [GeneratedRegex(@"^(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?$")]
    private static partial Regex ColonTimeRegex();

    public static string NormalizeDateStr(object? val)
    {
        if (val is null) return "";
        if (val is DateTime dt) return dt.ToString("yyyy-MM-dd");
        var s = val.ToString()?.Trim() ?? "";
        if (string.IsNullOrEmpty(s)) return "";
        var m = SlashDateRegex().Match(s);
        if (m.Success)
        {
            int month = int.Parse(m.Groups[1].Value);
            int day = int.Parse(m.Groups[2].Value);
            string year = m.Groups[3].Value;
            return $"{year}-{month:D2}-{day:D2}";
        }
        return s;
    }

    public static string NormalizeTimeStr(object? val)
    {
        if (val is null) return "";
        if (val is DateTime dt) return dt.ToString("HH:mm:ss");
        if (val is TimeSpan ts) return $"{(int)ts.TotalHours:D2}:{ts.Minutes:D2}:{ts.Seconds:D2}";
        var s = val.ToString()?.Trim() ?? "";
        if (string.IsNullOrEmpty(s)) return "";
        var m = ColonTimeRegex().Match(s);
        if (m.Success)
        {
            int hour = int.Parse(m.Groups[1].Value);
            int minute = int.Parse(m.Groups[2].Value);
            int second = m.Groups[3].Success ? int.Parse(m.Groups[3].Value) : 0;
            return $"{hour:D2}:{minute:D2}:{second:D2}";
        }
        return s;
    }

    public static (string NumberPart, string TypePart) SplitSubject(string sendType, string? subjectText)
    {
        var text = (subjectText ?? "").Trim();
        var marker = $"{sendType} -";
        int idx = text.IndexOf(marker, StringComparison.Ordinal);
        if (idx == -1)
            return (text, sendType);

        int prefixEnd = idx + marker.Length;
        if (prefixEnd < text.Length && text[prefixEnd] == ' ')
            prefixEnd++;

        var numberPart = text[prefixEnd..].Trim();
        var typePart = text[..prefixEnd].TrimEnd();
        if (typePart.EndsWith('-'))
            typePart = typePart[..^1].TrimEnd();
        return (numberPart, typePart);
    }

    private static string ReadCellAsString(IXLCell cell)
    {
        if (cell.IsEmpty()) return "";
        return cell.DataType switch
        {
            XLDataType.DateTime => cell.GetDateTime().ToString("yyyy-MM-dd"),
            XLDataType.TimeSpan => cell.GetTimeSpan().ToString(@"hh\:mm\:ss"),
            _ => cell.GetFormattedString().Trim()
        };
    }

    private static void ReadRowsFromSheet(
        IXLWorksheet ws,
        List<string[]> gdnRows,
        List<string[]> grnRows)
    {
        var lastRow = ws.LastRowUsed()?.RowNumber() ?? 1;
        for (int r = 2; r <= lastRow; r++)
        {
            var gdnVals = new[]
            {
                NormalizeDateStr(ReadCellAsString(ws.Cell(r, 1))),
                NormalizeTimeStr(ReadCellAsString(ws.Cell(r, 2))),
                ReadCellAsString(ws.Cell(r, 3)),
                ReadCellAsString(ws.Cell(r, 4))
            };
            if (gdnVals.Any(v => !string.IsNullOrEmpty(v)))
                gdnRows.Add(gdnVals);

            var grnVals = new[]
            {
                NormalizeDateStr(ReadCellAsString(ws.Cell(r, 5))),
                NormalizeTimeStr(ReadCellAsString(ws.Cell(r, 6))),
                ReadCellAsString(ws.Cell(r, 7)),
                ReadCellAsString(ws.Cell(r, 8))
            };
            if (grnVals.Any(v => !string.IsNullOrEmpty(v)))
                grnRows.Add(grnVals);
        }
    }

    private static void ApplySheetFormatting(IXLWorksheet ws, int maxRow)
    {
        for (int colIdx = 1; colIdx <= 8; colIdx++)
        {
            var cell = ws.Cell(1, colIdx);
            cell.Style.Font.FontName = "Calibri";
            cell.Style.Font.FontSize = 11;
            cell.Style.Font.Bold = true;
            cell.Style.Alignment.Vertical = XLAlignmentVerticalValues.Center;
            cell.Style.Alignment.Horizontal = (colIdx == 4 || colIdx == 8)
                ? XLAlignmentHorizontalValues.Left
                : XLAlignmentHorizontalValues.Right;
        }

        for (int rowIdx = 2; rowIdx <= maxRow; rowIdx++)
        {
            for (int colIdx = 1; colIdx <= 8; colIdx++)
            {
                var cell = ws.Cell(rowIdx, colIdx);
                cell.Style.Font.FontName = "Calibri";
                cell.Style.Font.FontSize = 11;
                cell.Style.Alignment.Vertical = XLAlignmentVerticalValues.Center;
                if (colIdx is 1 or 5)
                {
                    cell.Style.NumberFormat.Format = "yyyy-mm-dd";
                    cell.Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Right;
                }
                else if (colIdx is 2 or 6)
                {
                    cell.Style.NumberFormat.Format = "hh:mm:ss";
                    cell.Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Right;
                }
                else if (colIdx is 3 or 7)
                {
                    cell.Style.NumberFormat.Format = "@";
                    cell.Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Right;
                }
                else if (colIdx is 4 or 8)
                {
                    cell.Style.NumberFormat.Format = "@";
                    cell.Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Left;
                }
            }
        }

        double[] widths = [14, 12, 16, 20, 14, 12, 16, 20];
        for (int i = 0; i < widths.Length; i++)
            ws.Column(i + 1).Width = widths[i];
    }

    public void SortLocalRecords()
    {
        if (!File.Exists(ExcelPath)) return;
        lock (GetPathLock())
        {
            try
            {
                using var wb = new XLWorkbook(ExcelPath);
                var ws = wb.Worksheets.First();
                var gdnRows = new List<string[]>();
                var grnRows = new List<string[]>();
                ReadRowsFromSheet(ws, gdnRows, grnRows);

                gdnRows = gdnRows.OrderBy(r => r[0], StringComparer.Ordinal).ThenBy(r => r[1], StringComparer.Ordinal).ToList();
                grnRows = grnRows.OrderBy(r => r[0], StringComparer.Ordinal).ThenBy(r => r[1], StringComparer.Ordinal).ToList();

                int oldLast = ws.LastRowUsed()?.RowNumber() ?? 1;
                if (oldLast > 1)
                    ws.Rows(2, oldLast).Delete();

                int totalRows = Math.Max(gdnRows.Count, grnRows.Count);
                for (int i = 0; i < totalRows; i++)
                {
                    var gdn = i < gdnRows.Count ? gdnRows[i] : ["", "", "", ""];
                    var grn = i < grnRows.Count ? grnRows[i] : ["", "", "", ""];
                    int row = i + 2;
                    for (int c = 0; c < 4; c++)
                    {
                        ws.Cell(row, c + 1).Value = gdn[c];
                        ws.Cell(row, c + 5).Value = grn[c];
                    }
                }

                ApplySheetFormatting(ws, Math.Max(1, totalRows + 1));
                wb.Save();
            }
            catch { }
        }
    }

    private void LogToExcel(string sendType, string dateStr, string timeStr, string numberPart, string typePart)
    {
        lock (GetPathLock())
        {
            try
            {
                var dir = Path.GetDirectoryName(Path.GetFullPath(ExcelPath));
                if (!string.IsNullOrEmpty(dir))
                    Directory.CreateDirectory(dir);

                XLWorkbook wb;
                IXLWorksheet ws;
                if (File.Exists(ExcelPath))
                {
                    wb = new XLWorkbook(ExcelPath);
                    ws = wb.Worksheets.First();
                }
                else
                {
                    wb = new XLWorkbook();
                    ws = wb.AddWorksheet("Sent Log");
                    string[] headers = ["GDN Date", "GDN Time", "GDN Number", "GDN Type", "GRN Date", "GRN Time", "GRN Number", "GRN Type"];
                    for (int c = 0; c < headers.Length; c++)
                        ws.Cell(1, c + 1).Value = headers[c];
                }

                using (wb)
                {
                    var gdnRows = new List<string[]>();
                    var grnRows = new List<string[]>();
                    ReadRowsFromSheet(ws, gdnRows, grnRows);

                    var newRecord = new[]
                    {
                        NormalizeDateStr(dateStr),
                        NormalizeTimeStr(timeStr),
                        (numberPart ?? "").Trim(),
                        (typePart ?? "").Trim()
                    };

                    if (sendType == SendTypeGdn)
                    {
                        gdnRows.Add(newRecord);
                        gdnRows = gdnRows.OrderBy(r => r[0], StringComparer.Ordinal).ThenBy(r => r[1], StringComparer.Ordinal).ToList();
                    }
                    else if (sendType == SendTypeGrn)
                    {
                        grnRows.Add(newRecord);
                        grnRows = grnRows.OrderBy(r => r[0], StringComparer.Ordinal).ThenBy(r => r[1], StringComparer.Ordinal).ToList();
                    }

                    int oldLast = ws.LastRowUsed()?.RowNumber() ?? 1;
                    if (oldLast > 1)
                        ws.Rows(2, oldLast).Delete();

                    int totalRows = Math.Max(gdnRows.Count, grnRows.Count);
                    for (int i = 0; i < totalRows; i++)
                    {
                        var gdn = i < gdnRows.Count ? gdnRows[i] : ["", "", "", ""];
                        var grn = i < grnRows.Count ? grnRows[i] : ["", "", "", ""];
                        int row = i + 2;
                        for (int c = 0; c < 4; c++)
                        {
                            ws.Cell(row, c + 1).Value = gdn[c];
                            ws.Cell(row, c + 5).Value = grn[c];
                        }
                    }

                    ApplySheetFormatting(ws, Math.Max(1, totalRows + 1));
                    wb.SaveAs(ExcelPath);
                }
            }
            catch { }
        }
    }

    public async Task LogSendAsync(string sendType, string subjectText)
    {
        if (sendType != SendTypeGdn && sendType != SendTypeGrn)
            return;

        var now = DateTime.Now;
        var dateStr = now.ToString("yyyy-MM-dd");
        var timeStr = now.ToString("HH:mm:ss");
        var (numberPart, typePart) = SplitSubject(sendType, subjectText);

        LogToExcel(sendType, dateStr, timeStr, numberPart, typePart);

        var url = _configStore.GetWebappUrl();
        if (string.IsNullOrWhiteSpace(url))
            return;

        try
        {
            var payload = new
            {
                type = sendType,
                date = dateStr,
                time = timeStr,
                number = numberPart,
                type_part = typePart
            };
            using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            await Http.PostAsJsonAsync(url, payload, cts.Token).ConfigureAwait(false);
        }
        catch { }
    }

    public void LogSend(string sendType, string subjectText)
        => LogSendAsync(sendType, subjectText).GetAwaiter().GetResult();

    public async Task<SentLogCounts> GetCountsAsync()
    {
        var url = _configStore.GetWebappUrl();
        if (string.IsNullOrWhiteSpace(url))
            return new SentLogCounts(0, 0);

        try
        {
            using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            using var resp = await Http.GetAsync(url, cts.Token).ConfigureAwait(false);
            if (resp.IsSuccessStatusCode)
            {
                var text = await resp.Content.ReadAsStringAsync(cts.Token).ConfigureAwait(false);
                using var doc = JsonDocument.Parse(text);
                int gdn = doc.RootElement.TryGetProperty("GDN", out var g) && g.TryGetInt32(out var gv) ? gv : 0;
                int grn = doc.RootElement.TryGetProperty("GRN", out var r) && r.TryGetInt32(out var rv) ? rv : 0;
                return new SentLogCounts(gdn, grn);
            }
        }
        catch { }
        return new SentLogCounts(0, 0);
    }

    public List<SentLogRecord> GetRecentRecords(int limit = 10)
    {
        if (!File.Exists(ExcelPath))
            return [];

        lock (GetPathLock())
        {
            try
            {
                using var wb = new XLWorkbook(ExcelPath);
                var ws = wb.Worksheets.First();
                var records = new List<SentLogRecord>();
                int lastRow = ws.LastRowUsed()?.RowNumber() ?? 1;

                for (int r = 2; r <= lastRow; r++)
                {
                    var d1 = ReadCellAsString(ws.Cell(r, 1));
                    if (!string.IsNullOrWhiteSpace(d1))
                    {
                        var whRaw = ReadCellAsString(ws.Cell(r, 4)).Replace("GDN", "").Trim().TrimEnd('-').Trim();
                        records.Add(new SentLogRecord
                        {
                            Type = "GDN",
                            Date = NormalizeDateStr(d1),
                            Time = NormalizeTimeStr(ReadCellAsString(ws.Cell(r, 2))),
                            Number = ReadCellAsString(ws.Cell(r, 3)),
                            Warehouse = string.IsNullOrEmpty(whRaw) ? "General" : whRaw
                        });
                    }

                    var d2 = ReadCellAsString(ws.Cell(r, 5));
                    if (!string.IsNullOrWhiteSpace(d2))
                    {
                        var whRaw = ReadCellAsString(ws.Cell(r, 8)).Replace("GRN", "").Trim().TrimEnd('-').Trim();
                        records.Add(new SentLogRecord
                        {
                            Type = "GRN",
                            Date = NormalizeDateStr(d2),
                            Time = NormalizeTimeStr(ReadCellAsString(ws.Cell(r, 6))),
                            Number = ReadCellAsString(ws.Cell(r, 7)),
                            Warehouse = string.IsNullOrEmpty(whRaw) ? "General" : whRaw
                        });
                    }
                }

                return records
                    .OrderByDescending(x => x.Date, StringComparer.Ordinal)
                    .ThenByDescending(x => x.Time, StringComparer.Ordinal)
                    .Take(limit)
                    .ToList();
            }
            catch
            {
                return [];
            }
        }
    }
}
