using System.IO;
using ClosedXML.Excel;
using KorberAuditShip.Models;
using KorberAuditShip.Services;
using Xunit;

namespace KorberAuditShip.Tests;

public sealed class SpreadsheetServiceTests : IDisposable
{
    private readonly string _tempDir;
    private readonly SpreadsheetService _service = new();

    public SpreadsheetServiceTests()
    {
        _tempDir = Path.Combine(Path.GetTempPath(), $"KorberExcelTests_{Guid.NewGuid():N}");
        Directory.CreateDirectory(_tempDir);
    }

    public void Dispose()
    {
        if (Directory.Exists(_tempDir))
            Directory.Delete(_tempDir, recursive: true);
    }

    [Fact]
    public void LoadAndPrepare_DeduplicatesSortsNormalizes_AndComputesSummary()
    {
        var inputPath = Path.Combine(_tempDir, "input.xlsx");
        using (var wb = new XLWorkbook())
        {
            var ws = wb.Worksheets.Add("Sheet1");
            ws.Cell(1, 1).Value = "Wh Id";
            ws.Cell(1, 2).Value = "Load Id";
            ws.Cell(1, 3).Value = "Gate Pass Id";

            // Unsorted rows, duplicate key, numeric trailing values, blank row
            ws.Cell(2, 1).Value = "LPPL";
            ws.Cell(2, 2).Value = 2002;
            ws.Cell(2, 3).Value = 9002;

            ws.Cell(3, 1).Value = "ESKD";
            ws.Cell(3, 2).Value = "1001";
            ws.Cell(3, 3).Value = "9001";

            // Duplicate of row 2
            ws.Cell(4, 1).Value = " LPPL ";
            ws.Cell(4, 2).Value = "2002";
            ws.Cell(4, 3).Value = "9002";

            // Same WhId + LoadId, distinct GatePassId
            ws.Cell(5, 1).Value = "LPPL";
            ws.Cell(5, 2).Value = 2001;
            ws.Cell(5, 3).Value = 9003;

            // Blank spacer row
            ws.Cell(6, 1).Value = "";
            ws.Cell(6, 2).Value = "";
            ws.Cell(6, 3).Value = "";

            wb.SaveAs(inputPath);
        }

        var (rows, summary) = _service.LoadAndPrepare(inputPath, " DOOR-12 ");

        Assert.Equal(3, rows.Count);
        // Sorted by WhId -> LoadId -> GatePassId: ESKD/1001, LPPL/2001, LPPL/2002
        Assert.Equal("ESKD", rows[0].WhId);
        Assert.Equal("1001", rows[0].LoadId);
        Assert.Equal("9001", rows[0].GatePassId);
        Assert.Equal("DOOR-12", rows[0].DoorLocation);
        Assert.Equal(0, rows[0].RowIndex);

        Assert.Equal("LPPL", rows[1].WhId);
        Assert.Equal("2001", rows[1].LoadId);
        Assert.Equal(1, rows[1].RowIndex);

        Assert.Equal("LPPL", rows[2].WhId);
        Assert.Equal("2002", rows[2].LoadId);
        Assert.Equal(2, rows[2].RowIndex);

        Assert.Equal(2, summary.TotalWhIds);          // ESKD, LPPL
        Assert.Equal(3, summary.TotalGatePassIds);    // 9001, 9003, 9002
        Assert.Equal(3, summary.TotalUniqueLoadIds);  // 1001, 2001, 2002
        Assert.Equal("DOOR-12", summary.DoorLocation);
    }

    [Fact]
    public void LoadAndPrepare_ThrowsInvalidDataException_WhenRequiredColumnMissing()
    {
        var inputPath = Path.Combine(_tempDir, "missing_col.xlsx");
        using (var wb = new XLWorkbook())
        {
            var ws = wb.Worksheets.Add("Sheet1");
            ws.Cell(1, 1).Value = "Wh Id";
            ws.Cell(1, 2).Value = "Load Id";
            ws.Cell(2, 1).Value = "LPPL";
            ws.Cell(2, 2).Value = "100";
            wb.SaveAs(inputPath);
        }

        var ex = Assert.Throws<InvalidDataException>(() => _service.LoadAndPrepare(inputPath, "D1"));
        Assert.Contains("Gate Pass Id", ex.Message);
    }

    [Fact]
    public void GetValidatedFirstWarehouseId_ValidatesKnownWarehouses()
    {
        Assert.Equal("NUGE", SpreadsheetService.GetValidatedFirstWarehouseId([
            new AuditShipRow { WhId = " nuge ", LoadId = "L1", GatePassId = "G1", DoorLocation = "D1" }
        ]));

        Assert.Throws<InvalidOperationException>(() => SpreadsheetService.GetValidatedFirstWarehouseId([]));
        Assert.Throws<InvalidOperationException>(() => SpreadsheetService.GetValidatedFirstWarehouseId([
            new AuditShipRow { WhId = "UNKNOWN", LoadId = "L1", GatePassId = "G1", DoorLocation = "D1" }
        ]));
    }

    [Fact]
    public void ExportExcel_WritesAlignedDataSheetWithFormattedValuesAndColumnWidths()
    {
        var outputPath = Path.Combine(_tempDir, "exported.xlsx");
        var rows = new List<AuditShipRow>
        {
            new()
            {
                RowIndex = 0,
                WhId = "LPPL",
                LoadId = "LOAD-100",
                GatePassId = "GP-500",
                DoorLocation = "D-01",
                LoadAuditStatus = "Done",
                ShippingStatus = new string('X', 60) // clamped at width 45
            }
        };

        _service.ExportExcel(rows, outputPath);

        Assert.True(File.Exists(outputPath));
        using var wb = new XLWorkbook(outputPath);
        var ws = wb.Worksheet("Aligned Data");
        Assert.Equal("Wh Id", ws.Cell(1, 1).GetString());
        Assert.True(ws.Cell(1, 1).Style.Font.Bold);
        Assert.Equal("LPPL", ws.Cell(2, 1).GetString());
        Assert.Equal("Done", ws.Cell(2, 5).GetString());
        Assert.Equal(14, ws.Column(1).Width); // min clamped to 14
        Assert.Equal(45, ws.Column(6).Width); // max clamped to 45
    }
}
