using System.Data;
using System.Globalization;
using System.IO;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;
using ClosedXML.Excel;
using EflNexus.Core.Infrastructure;
using ExcelDataReader;

namespace EflNexus.Core.Reconciliation;

public static class ExcelReaderHelper
{
    private static readonly string[] ValidExtensions = [".xlsx", ".xls", ".xlsm", ".xlsb"];

    public static (bool IsValid, string Message) ValidateExcelFile(string? filePath)
    {
        if (string.IsNullOrWhiteSpace(filePath))
            return (false, "No file selected");

        if (!File.Exists(filePath))
            return (false, "File does not exist");

        var ext = Path.GetExtension(filePath).ToLowerInvariant();
        if (!ValidExtensions.Contains(ext))
            return (false, "File is not a valid Excel file (must be .xlsx or .xls)");

        try
        {
            _ = ReadExcel(filePath, previewOnly: true);
            return (true, "Valid Excel file");
        }
        catch (Exception ex)
        {
            return (false, $"Invalid Excel file: {ex.Message}");
        }
    }

    public static TabularDataset ReadExcel(string filePath, string? sheetName = null, bool previewOnly = false)
    {
        EncodingInit.EnsureRegistered();

        if (!File.Exists(filePath))
            throw new FileNotFoundException("Excel file not found.", filePath);

        // 1. Check for HTML-table .xls masquerading as Excel (common in WMS/ERP exports)
        if (LooksLikeHtmlTable(filePath))
        {
            var htmlTable = TryReadHtmlTable(filePath);
            if (htmlTable is not null)
                return CleanWholeNumberColumns(htmlTable);
        }

        var ext = Path.GetExtension(filePath).ToLowerInvariant();
        Exception? primaryError = null;

        // 2. Try ClosedXML first for .xlsx / .xlsm
        if (ext is ".xlsx" or ".xlsm")
        {
            try
            {
                var ds = ReadWithClosedXml(filePath, sheetName, previewOnly ? 5 : int.MaxValue);
                return CleanWholeNumberColumns(ds);
            }
            catch (Exception ex)
            {
                primaryError = ex;
            }
        }

        // 3. Fallback (or primary for .xls / .xlsb): ExcelDataReader
        try
        {
            var ds = ReadWithExcelDataReader(filePath, sheetName, previewOnly ? 5 : int.MaxValue);
            return CleanWholeNumberColumns(ds);
        }
        catch (Exception ex)
        {
            // Last resort: check HTML table again regardless of leading bytes
            var htmlTable = TryReadHtmlTable(filePath);
            if (htmlTable is not null)
                return CleanWholeNumberColumns(htmlTable);

            throw new InvalidDataException(
                $"Could not read file: {(primaryError ?? ex).Message}", primaryError ?? ex);
        }
    }

    public static List<List<string>> ReadVarianceSheetGrid(string excelPath)
    {
        EncodingInit.EnsureRegistered();
        var sheetNames = GetSheetNames(excelPath);
        string? targetSheet = sheetNames.FirstOrDefault(s => s.Contains("variance", StringComparison.OrdinalIgnoreCase))
            ?? sheetNames.FirstOrDefault();

        var ds = ReadExcel(excelPath, targetSheet, previewOnly: false);
        var grid = new List<List<string>>(ds.RowCount + 1)
        {
            ds.Columns.ToList()
        };
        foreach (var row in ds.Rows)
        {
            var line = new List<string>(ds.ColumnCount);
            for (int c = 0; c < ds.ColumnCount; c++)
                line.Add(c < row.Length ? TabularDataset.CellToString(row[c]) : "");
            grid.Add(line);
        }
        return grid;
    }

    public static List<string> GetSheetNames(string filePath)
    {
        EncodingInit.EnsureRegistered();
        if (LooksLikeHtmlTable(filePath))
            return ["Sheet1"];

        var ext = Path.GetExtension(filePath).ToLowerInvariant();
        if (ext is ".xlsx" or ".xlsm")
        {
            try
            {
                using var fs = new FileStream(filePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
                using var wb = new XLWorkbook(fs);
                return wb.Worksheets.Select(ws => ws.Name).ToList();
            }
            catch { }
        }

        try
        {
            using var fs = new FileStream(filePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
            using var reader = ExcelReaderFactory.CreateReader(fs);
            var names = new List<string>();
            do
            {
                names.Add(reader.Name);
            } while (reader.NextResult());
            return names;
        }
        catch
        {
            return [];
        }
    }

    private static TabularDataset ReadWithClosedXml(string filePath, string? sheetName, int maxDataRows)
    {
        using var fs = new FileStream(filePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        using var wb = new XLWorkbook(fs);
        var ws = !string.IsNullOrWhiteSpace(sheetName)
            ? wb.Worksheet(sheetName)
            : wb.Worksheets.First();

        var range = ws.RangeUsed();
        if (range is null)
            return new TabularDataset([], []);

        int firstRow = range.FirstRow().RowNumber();
        int lastRow = range.LastRow().RowNumber();
        int firstCol = range.FirstColumn().ColumnNumber();
        int lastCol = range.LastColumn().ColumnNumber();
        int colCount = lastCol - firstCol + 1;

        var rawHeader = new List<string>(colCount);
        bool anyHeader = false;
        for (int c = firstCol; c <= lastCol; c++)
        {
            var h = ExtractXlCellString(ws.Cell(firstRow, c));
            if (!string.IsNullOrWhiteSpace(h))
                anyHeader = true;
            rawHeader.Add(h);
        }

        int dataStartRow = anyHeader ? firstRow + 1 : firstRow;
        var columns = anyHeader
            ? MakeUniqueColumnNames(rawHeader)
            : Enumerable.Range(1, colCount).Select(i => $"Column_{i}").ToList();

        var rows = new List<object?[]>();
        for (int r = dataStartRow; r <= lastRow && rows.Count < maxDataRows; r++)
        {
            var rowArr = new object?[colCount];
            bool allEmpty = true;
            for (int c = 0; c < colCount; c++)
            {
                var val = ConvertXlCellValue(ws.Cell(r, firstCol + c));
                if (val is not null)
                    allEmpty = false;
                rowArr[c] = val;
            }
            if (!allEmpty)
                rows.Add(rowArr);
        }

        // Handle headerless fallback if data rows exist but header was effectively blank
        if (columns.Count == 0 && rows.Count > 0)
            columns = Enumerable.Range(1, colCount).Select(i => $"Column_{i}").ToList();

        return new TabularDataset(columns, rows);
    }

    private static string ExtractXlCellString(IXLCell cell)
    {
        var v = ConvertXlCellValue(cell);
        return TabularDataset.CellToString(v).Trim();
    }

    private static object? ConvertXlCellValue(IXLCell cell)
    {
        var v = cell.Value;
        if (v.IsBlank) return null;
        if (v.IsNumber) return v.GetNumber();
        if (v.IsBoolean) return v.GetBoolean();
        if (v.IsDateTime) return v.GetDateTime();
        if (v.IsTimeSpan) return v.GetTimeSpan().ToString();
        if (v.IsError) return v.GetError().ToString();
        var s = v.ToString(CultureInfo.InvariantCulture);
        return string.IsNullOrEmpty(s) ? null : s;
    }

    private static TabularDataset ReadWithExcelDataReader(string filePath, string? sheetName, int maxDataRows)
    {
        using var fs = new FileStream(filePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        using var reader = ExcelReaderFactory.CreateReader(fs);

        if (!string.IsNullOrWhiteSpace(sheetName))
        {
            bool found = false;
            do
            {
                if (string.Equals(reader.Name, sheetName, StringComparison.OrdinalIgnoreCase))
                {
                    found = true;
                    break;
                }
            } while (reader.NextResult());

            if (!found)
                throw new InvalidOperationException($"Worksheet '{sheetName}' not found.");
        }

        var rawRows = new List<object?[]>();
        int maxCols = 0;
        while (reader.Read())
        {
            int count = reader.FieldCount;
            if (count > maxCols) maxCols = count;
            var arr = new object?[count];
            bool any = false;
            for (int i = 0; i < count; i++)
            {
                var val = reader.GetValue(i);
                if (val is not null && val != DBNull.Value && !string.IsNullOrEmpty(val.ToString()))
                    any = true;
                arr[i] = val == DBNull.Value ? null : val;
            }
            if (any || rawRows.Count == 0)
                rawRows.Add(arr);
            if (rawRows.Count >= maxDataRows + 1)
                break;
        }

        if (rawRows.Count == 0 || maxCols == 0)
            return new TabularDataset([], []);

        var headerRow = rawRows[0];
        var rawHeader = new List<string>(maxCols);
        bool anyHeader = false;
        for (int c = 0; c < maxCols; c++)
        {
            var s = c < headerRow.Length ? TabularDataset.CellToString(headerRow[c]).Trim() : "";
            if (!string.IsNullOrWhiteSpace(s)) anyHeader = true;
            rawHeader.Add(s);
        }

        int startIdx = anyHeader ? 1 : 0;
        var columns = anyHeader
            ? MakeUniqueColumnNames(rawHeader)
            : Enumerable.Range(1, maxCols).Select(i => $"Column_{i}").ToList();

        var dataRows = new List<object?[]>(Math.Max(0, rawRows.Count - startIdx));
        for (int r = startIdx; r < rawRows.Count; r++)
        {
            var src = rawRows[r];
            var normalized = new object?[maxCols];
            bool any = false;
            for (int c = 0; c < maxCols && c < src.Length; c++)
            {
                normalized[c] = src[c];
                if (src[c] is not null) any = true;
            }
            if (any)
                dataRows.Add(normalized);
        }

        return new TabularDataset(columns, dataRows);
    }

    private static bool LooksLikeHtmlTable(string filePath)
    {
        try
        {
            using var fs = new FileStream(filePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
            var buf = new byte[Math.Min(1024, fs.Length)];
            int read = fs.Read(buf, 0, buf.Length);
            var prefix = Encoding.UTF8.GetString(buf, 0, read).TrimStart('\uFEFF', ' ', '\t', '\r', '\n');
            return prefix.StartsWith("<", StringComparison.Ordinal)
                && (prefix.Contains("<html", StringComparison.OrdinalIgnoreCase)
                    || prefix.Contains("<table", StringComparison.OrdinalIgnoreCase)
                    || prefix.Contains("<!doctype", StringComparison.OrdinalIgnoreCase));
        }
        catch
        {
            return false;
        }
    }

    private static TabularDataset? TryReadHtmlTable(string filePath)
    {
        try
        {
            var content = File.ReadAllText(filePath);
            var tableMatch = Regex.Match(content, @"<table\b[^>]*>(.*?)</table>", RegexOptions.IgnoreCase | RegexOptions.Singleline);
            if (!tableMatch.Success)
                return null;

            var rowMatches = Regex.Matches(tableMatch.Groups[1].Value, @"<tr\b[^>]*>(.*?)</tr>", RegexOptions.IgnoreCase | RegexOptions.Singleline);
            if (rowMatches.Count == 0)
                return null;

            var parsedRows = new List<List<string>>();
            foreach (Match tr in rowMatches)
            {
                var cellMatches = Regex.Matches(tr.Groups[1].Value, @"<(td|th)\b[^>]*>(.*?)</\1>", RegexOptions.IgnoreCase | RegexOptions.Singleline);
                if (cellMatches.Count == 0) continue;
                var cells = new List<string>(cellMatches.Count);
                foreach (Match cell in cellMatches)
                {
                    var text = Regex.Replace(cell.Groups[2].Value, @"<[^>]+>", " ");
                    text = WebUtility.HtmlDecode(text).Trim();
                    text = Regex.Replace(text, @"\s+", " ");
                    cells.Add(text);
                }
                parsedRows.Add(cells);
            }

            if (parsedRows.Count == 0)
                return null;

            int maxCols = parsedRows.Max(r => r.Count);
            if (maxCols == 0) return null;

            var header = parsedRows[0];
            while (header.Count < maxCols) header.Add("");
            var columns = MakeUniqueColumnNames(header);

            var dataRows = new List<object?[]>();
            for (int r = 1; r < parsedRows.Count; r++)
            {
                var row = parsedRows[r];
                var arr = new object?[maxCols];
                bool any = false;
                for (int c = 0; c < maxCols && c < row.Count; c++)
                {
                    var valStr = row[c];
                    if (string.IsNullOrEmpty(valStr))
                    {
                        arr[c] = null;
                    }
                    else
                    {
                        any = true;
                        arr[c] = double.TryParse(valStr, NumberStyles.Any, CultureInfo.InvariantCulture, out var num)
                            ? num
                            : valStr;
                    }
                }
                if (any)
                    dataRows.Add(arr);
            }

            return new TabularDataset(columns, dataRows);
        }
        catch
        {
            return null;
        }
    }

    private static List<string> MakeUniqueColumnNames(List<string> rawHeaders)
    {
        var result = new List<string>(rawHeaders.Count);
        var seen = new Dictionary<string, int>(StringComparer.Ordinal);
        for (int i = 0; i < rawHeaders.Count; i++)
        {
            var baseName = string.IsNullOrWhiteSpace(rawHeaders[i])
                ? $"Unnamed: {i}"
                : rawHeaders[i].Trim();
            if (!seen.TryGetValue(baseName, out int count))
            {
                seen[baseName] = 0;
                result.Add(baseName);
            }
            else
            {
                count++;
                seen[baseName] = count;
                var candidate = $"{baseName}.{count}";
                while (seen.ContainsKey(candidate))
                {
                    count++;
                    candidate = $"{baseName}.{count}";
                }
                seen[candidate] = 0;
                result.Add(candidate);
            }
        }
        return result;
    }

    public static TabularDataset CleanWholeNumberColumns(TabularDataset ds)
    {
        for (int c = 0; c < ds.ColumnCount; c++)
        {
            bool hasAnyNumeric = false;
            bool allWhole = true;

            for (int r = 0; r < ds.RowCount; r++)
            {
                var val = ds.Rows[r][c];
                if (val is null) continue;

                double d;
                switch (val)
                {
                    case double dv: d = dv; break;
                    case float fv: d = fv; break;
                    case decimal mv: d = (double)mv; break;
                    case long or int or short or byte:
                        hasAnyNumeric = true;
                        continue;
                    default:
                        allWhole = false;
                        continue;
                }

                if (double.IsNaN(d) || double.IsInfinity(d))
                    continue;

                hasAnyNumeric = true;
                if (Math.Abs(d - Math.Round(d)) > 1e-9 || Math.Abs(d) > long.MaxValue)
                {
                    allWhole = false;
                    break;
                }
            }

            if (hasAnyNumeric && allWhole)
            {
                for (int r = 0; r < ds.RowCount; r++)
                {
                    var val = ds.Rows[r][c];
                    if (val is double dv && !double.IsNaN(dv) && !double.IsInfinity(dv))
                        ds.Rows[r][c] = (long)Math.Round(dv);
                    else if (val is float fv && !float.IsNaN(fv) && !float.IsInfinity(fv))
                        ds.Rows[r][c] = (long)Math.Round(fv);
                    else if (val is decimal mv)
                        ds.Rows[r][c] = (long)Math.Round(mv);
                }
            }
        }
        return ds;
    }
}
