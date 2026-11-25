using System.IO;
using System.Text;
using KorberAuditShip.Models;
using KorberAuditShip.Services;
using Xunit;

namespace KorberAuditShip.Tests;

public sealed class PdfExportServiceTests : IDisposable
{
    private readonly string _tempDir;
    private readonly PdfExportService _service = new();

    public PdfExportServiceTests()
    {
        _tempDir = Path.Combine(Path.GetTempPath(), $"KorberPdfTests_{Guid.NewGuid():N}");
        Directory.CreateDirectory(_tempDir);
    }

    public void Dispose()
    {
        if (Directory.Exists(_tempDir))
            Directory.Delete(_tempDir, recursive: true);
    }

    [Fact]
    public void ExportPdf_ThrowsInvalidOperationException_WhenEmpty()
    {
        var outPath = Path.Combine(_tempDir, "empty.pdf");
        Assert.Throws<InvalidOperationException>(() => _service.ExportPdf([], outPath));
    }

    [Fact]
    public void ExportPdf_GeneratesValidMultiPageA4LandscapePdfWithEscapedText()
    {
        var outPath = Path.Combine(_tempDir, "report.pdf");
        var rows = Enumerable.Range(1, 75).Select(i => new AuditShipRow
        {
            RowIndex = i - 1,
            WhId = "LPPL",
            LoadId = $"LD-{i:0000}",
            GatePassId = $"GP-{i:0000}",
            DoorLocation = "D(1)\\A",
            LoadAuditStatus = i % 2 == 0 ? "Done" : "INVALID LOAD ID (Test)",
            ShippingStatus = "Pending"
        }).ToList();

        var timestamp = new DateTime(2026, 11, 14, 15, 30, 0);
        _service.ExportPdf(rows, outPath, timestamp);

        Assert.True(File.Exists(outPath));
        var pdfBytes = File.ReadAllBytes(outPath);
        var pdfText = Encoding.Latin1.GetString(pdfBytes);

        Assert.StartsWith("%PDF-1.4", pdfText);
        Assert.Contains("/MediaBox [0 0 841.89 595.28]", pdfText);
        Assert.Contains("3PL EFL", pdfText);
        Assert.Contains("Exported: 2026-11-14 15:30:00", pdfText);
        // Literal parentheses in content must be escaped cleanly for Type 1 string literals
        Assert.Contains(@"D\(1\)\\A", pdfText);
        // 75 rows should span multiple pages in A4 landscape with repeated header rows
        var countMatch = System.Text.RegularExpressions.Regex.Match(pdfText, @"/Count\s+(\d+)");
        Assert.True(countMatch.Success);
        Assert.True(int.Parse(countMatch.Groups[1].Value) >= 2);
        Assert.EndsWith("%%EOF\n", pdfText.Replace("\r\n", "\n"));
    }
}
