using System.Data;
using System.IO;
using System.Text;
using ClosedXML.Excel;
using ExcelDataReader;
using KorberAuditShip.Models;

namespace KorberAuditShip.Services;

/// <summary>
/// Loads, validates, deduplicates, sorts, summarizes, and exports Aligned Data Table spreadsheets.
/// Supports both legacy .xls binary workbooks and OpenXML .xlsx workbooks.
/// </summary>
public sealed class SpreadsheetService
{
    public const string WhIdColumn = "Wh Id";
    public const string LoadIdColumn = "Load Id";
    public const string GatePassIdColumn = "Gate Pass Id";
    public const string DoorLocationColumn = "Door Location";
    public const string LoadAuditStatusColumn = "Load Audit Status";
    public const string ShippingStatusColumn = "Shipping Status";

    public static readonly IReadOnlyList<string> RequiredColumns =
    [
        WhIdColumn,
        LoadIdColumn,
        GatePassIdColumn
    ];

    public static readonly IReadOnlyList<string> AllColumns =
    [
        WhIdColumn,
        LoadIdColumn,
        GatePassIdColumn,
        DoorLocationColumn,
        LoadAuditStatusColumn,
        ShippingStatusColumn
    ];

    public static readonly IReadOnlyList<string> ValidWarehouses =
    [
        "LPPL",
        "ESKD",
        "NUGE",
        "EGDC"
    ];

    static SpreadsheetService()
    {
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
    }

    public (IReadOnlyList<AuditShipRow> Rows, OperationalSummary Summary) LoadAndPrepare(string filePath, string doorLocation)
    {
        if (string.IsNullOrWhiteSpace(filePath))
            throw new ArgumentException("File path is required.", nameof(filePath));

        var cleanedDoorLocation = (doorLocation ?? string.Empty).Trim();
        if (string.IsNullOrWhiteSpace(cleanedDoorLocation))
            throw new ArgumentException("Door Location cannot be empty.", nameof(doorLocation));

        using var stream = File.Open(filePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        using var reader = ExcelReaderFactory.CreateReader(stream);

        var dataSet = reader.AsDataSet(new ExcelDataSetConfiguration
        {
            ConfigureDataTable = _ => new ExcelDataTableConfiguration
            {
                UseHeaderRow = true
            }
        });

        if (dataSet.Tables.Count == 0)
            throw new InvalidDataException($"Missing required column(s): {string.Join(", ", RequiredColumns)}");

        var table = dataSet.Tables[0];

        var columnLookup = new Dictionary<string, DataColumn>(StringComparer.Ordinal);
        foreach (DataColumn col in table.Columns)
        {
            var header = col.ColumnName?.Trim() ?? string.Empty;
            if (!string.IsNullOrEmpty(header) && !columnLookup.ContainsKey(header))
                columnLookup[header] = col;
        }

        var missingColumns = RequiredColumns
            .Where(req => !columnLookup.ContainsKey(req))
            .ToList();

        if (missingColumns.Count > 0)
            throw new InvalidDataException($"Missing required column(s): {string.Join(", ", missingColumns)}");

        var whCol = columnLookup[WhIdColumn];
        var loadCol = columnLookup[LoadIdColumn];
        var gatePassCol = columnLookup[GatePassIdColumn];

        var seen = new HashSet<(string WhId, string LoadId, string GatePassId, string DoorLocation)>();
        var rawRows = new List<AuditShipRow>(table.Rows.Count);

        foreach (DataRow row in table.Rows)
        {
            var whId = AuditShipRow.CleanValue(row[whCol]);
            var loadId = AuditShipRow.CleanValue(row[loadCol]);
            var gatePassId = AuditShipRow.CleanValue(row[gatePassCol]);

            // Skip completely blank trailing/spacer rows from Excel UsedRange
            if (string.IsNullOrEmpty(whId) && string.IsNullOrEmpty(loadId) && string.IsNullOrEmpty(gatePassId))
                continue;

            var key = (whId, loadId, gatePassId, cleanedDoorLocation);
            if (!seen.Add(key))
                continue;

            rawRows.Add(new AuditShipRow
            {
                WhId = whId,
                LoadId = loadId,
                GatePassId = gatePassId,
                DoorLocation = cleanedDoorLocation,
                LoadAuditStatus = string.Empty,
                ShippingStatus = string.Empty
            });
        }

        // Stable sort (mergesort equivalent in LINQ) by Wh Id, Load Id, Gate Pass Id
        var sorted = rawRows
            .OrderBy(r => r.WhId, StringComparer.Ordinal)
            .ThenBy(r => r.LoadId, StringComparer.Ordinal)
            .ThenBy(r => r.GatePassId, StringComparer.Ordinal)
            .ToList();

        for (var i = 0; i < sorted.Count; i++)
            sorted[i].RowIndex = i;

        var summary = ComputeSummary(sorted, cleanedDoorLocation);
        return (sorted, summary);
    }

    public static OperationalSummary ComputeSummary(IReadOnlyList<AuditShipRow> rows, string doorLocation)
    {
        var totalWh = rows.Select(r => r.WhId).Where(s => !string.IsNullOrEmpty(s)).Distinct(StringComparer.Ordinal).Count();
        var totalGatePass = rows.Select(r => r.GatePassId).Where(s => !string.IsNullOrEmpty(s)).Distinct(StringComparer.Ordinal).Count();
        var totalLoads = rows.Select(r => r.LoadId).Where(s => !string.IsNullOrEmpty(s)).Distinct(StringComparer.Ordinal).Count();

        return new OperationalSummary(totalWh, totalGatePass, totalLoads, doorLocation.Trim());
    }

    public static string GetValidatedFirstWarehouseId(IReadOnlyList<AuditShipRow>? rows)
    {
        if (rows is null || rows.Count == 0)
            throw new InvalidOperationException("Upload Excel first. No WH Id found in the Aligned Data Table.");

        var whId = AuditShipRow.NormalizeValue(rows[0].WhId);
        if (string.IsNullOrEmpty(whId))
            throw new InvalidOperationException("First row WH Id is empty in the Aligned Data Table.");

        if (!ValidWarehouses.Contains(whId, StringComparer.Ordinal))
            throw new InvalidOperationException($"Unknown WH Id in Aligned Data Table: {whId}. Valid warehouses: {string.Join(", ", ValidWarehouses)}");

        return whId;
    }

    public static string FormatExportValue(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return string.Empty;

        var singleLine = value.Replace('\r', ' ').Replace('\n', ' ');
        return string.Join(' ', singleLine.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
    }

    public void ExportExcel(IReadOnlyList<AuditShipRow> rows, string outputPath)
    {
        if (rows.Count == 0)
            throw new InvalidOperationException("No aligned table data to export. Upload Excel first.");

        using var workbook = new XLWorkbook();
        var worksheet = workbook.Worksheets.Add("Aligned Data");

        for (var c = 0; c < AllColumns.Count; c++)
        {
            var cell = worksheet.Cell(1, c + 1);
            cell.Value = AllColumns[c];
            cell.Style.Font.Bold = true;
            cell.Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Center;
        }

        for (var r = 0; r < rows.Count; r++)
        {
            var row = rows[r];
            var excelRow = r + 2;
            worksheet.Cell(excelRow, 1).Value = row.WhId;
            worksheet.Cell(excelRow, 2).Value = row.LoadId;
            worksheet.Cell(excelRow, 3).Value = row.GatePassId;
            worksheet.Cell(excelRow, 4).Value = row.DoorLocation;
            worksheet.Cell(excelRow, 5).Value = row.LoadAuditStatus;
            worksheet.Cell(excelRow, 6).Value = row.ShippingStatus;
        }

        // Match Python openpyxl width sizing: min(max(max_len + 3, 14), 45)
        for (var c = 0; c < AllColumns.Count; c++)
        {
            var colName = AllColumns[c];
            var maxLen = colName.Length;
            foreach (var row in rows)
            {
                var cellText = c switch
                {
                    0 => row.WhId,
                    1 => row.LoadId,
                    2 => row.GatePassId,
                    3 => row.DoorLocation,
                    4 => row.LoadAuditStatus,
                    5 => row.ShippingStatus,
                    _ => string.Empty
                };
                if (cellText.Length > maxLen)
                    maxLen = cellText.Length;
            }

            worksheet.Column(c + 1).Width = Math.Min(Math.Max(maxLen + 3, 14), 45);
        }

        workbook.SaveAs(outputPath);
    }
}
