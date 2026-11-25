using System.IO;
using ClosedXML.Excel;
using EflNexus.Core.PackingList;
using Xunit;

namespace KorberAuditShip.Tests;

public class PackingListServiceTests
{
    [Theory]
    [InlineData("00123", "123")]
    [InlineData("0001", "1")]
    [InlineData("123", "123")]
    [InlineData("0", "0")]
    [InlineData("000", "0")]
    [InlineData("105.0", "105")]
    [InlineData("  0045  ", "45")]
    [InlineData("", "")]
    public void CleanOutletCode_CorrectlyNormalizes(string input, string expected)
    {
        var actual = PackingListService.CleanOutletCode(input);
        Assert.Equal(expected, actual);
    }

    [Fact]
    public void LocationSummary_StatusDot_UpdatesOnSentMail()
    {
        var summary = new PackingListLocationSummary
        {
            Location = "Colombo",
            TotalQty = 50,
            GatePass = "GP-100",
            GdnNumber = "GDN-555",
            VehicleNumber = "WP-AB-1234"
        };

        Assert.Equal(string.Empty, summary.StatusDot);
        Assert.False(summary.HasSentMail);

        summary.HasSentMail = true;

        Assert.Equal("●", summary.StatusDot);
        Assert.True(summary.HasSentMail);
    }

    [Fact]
    public void CreateExcelFile_GeneratesValidWorkbook()
    {
        var service = new PackingListService();
        var tempFile = Path.Combine(Path.GetTempPath(), $"Test_PackingList_{Guid.NewGuid():N}.xlsx");

        try
        {
            var summary = new PackingListLocationSummary
            {
                Location = "SPAR Thalawathugoda",
                TotalQty = 25,
                GatePass = "GP-9999",
                GdnDate = "16-11-2026",
                GdnNumber = "GDN-9999",
                VehicleNumber = "CAB-5678",
                Items =
                [
                    new PackingListGroupedItem
                    {
                        ShipToCity = "SPAR Thalawathugoda",
                        OrderNumber = "ORD-001",
                        Mlp = "MLP-01",
                        ItemNumber = "ITEM-100",
                        Description = "Anchor Butter 200g",
                        LotNumber = "LOT-99",
                        ExpirationDate = "01-01-2027",
                        ActualQty = 15,
                        CountOfLPs = 2
                    },
                    new PackingListGroupedItem
                    {
                        ShipToCity = "SPAR Thalawathugoda",
                        OrderNumber = "ORD-002",
                        Mlp = "MLP-02",
                        ItemNumber = "ITEM-200",
                        Description = "Fresh Milk 1L",
                        LotNumber = "LOT-100",
                        ExpirationDate = "15-02-2027",
                        ActualQty = 10,
                        CountOfLPs = 1
                    }
                ]
            };

            var success = service.CreateExcelFile(summary, tempFile);
            Assert.True(success);
            Assert.True(File.Exists(tempFile));

            using var wb = new XLWorkbook(tempFile);
            var ws = wb.Worksheet("Packing List");
            Assert.NotNull(ws);

            // Title
            Assert.Equal("SPAR Packing List", ws.Cell("A1").GetString());
            // Metadata
            Assert.Equal("GDN Date :-", ws.Cell("A2").GetString());
            Assert.Equal("16-11-2026", ws.Cell("B2").GetString());
            Assert.Equal("Vehicle Number :-", ws.Cell("A3").GetString());
            Assert.Equal("CAB-5678", ws.Cell("B3").GetString());
            Assert.Equal("GDN Number :-", ws.Cell("A4").GetString());
            Assert.Equal("GDN-9999", ws.Cell("B4").GetString());
            Assert.Equal("SPAR Thalawathugoda", ws.Cell("A6").GetString());

            // Header row 7
            Assert.Equal("Order Number", ws.Cell("A7").GetString());
            Assert.Equal("Actual Qty", ws.Cell("G7").GetString());
            Assert.Equal("Count of LPs", ws.Cell("H7").GetString());

            // Data rows 8 and 9
            Assert.Equal("ORD-001", ws.Cell("A8").GetString());
            Assert.Equal(15, ws.Cell("G8").GetDouble());
            Assert.Equal(2, ws.Cell("H8").GetDouble());

            Assert.Equal("ORD-002", ws.Cell("A9").GetString());
            Assert.Equal(10, ws.Cell("G9").GetDouble());
            Assert.Equal(1, ws.Cell("H9").GetDouble());

            // Grand Total row 10
            Assert.Equal("GRAND TOTAL", ws.Cell("A10").GetString());
            Assert.Equal(25, ws.Cell("G10").GetDouble());
            Assert.Equal(3, ws.Cell("H10").GetDouble());

            // Sign-off section at row 14
            Assert.Equal("Date", ws.Cell("A14").GetString());
            Assert.Equal("Date", ws.Cell("E14").GetString());
            Assert.Equal("Driver Name", ws.Cell("A15").GetString());
            Assert.Equal("Outlet In-charge Name", ws.Cell("E15").GetString());
        }
        finally
        {
            if (File.Exists(tempFile))
            {
                try { File.Delete(tempFile); } catch { }
            }
        }
    }
}
