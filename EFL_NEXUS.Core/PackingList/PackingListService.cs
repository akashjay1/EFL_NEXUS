using System.Data;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text.Json;
using ClosedXML.Excel;
using EflNexus.Core.Infrastructure;
using EflNexus.Core.OutlookEmail;
using ExcelDataReader;

namespace EflNexus.Core.PackingList;

public sealed class PackingListService
{
    public const string CcEmails =
        "ayodhya.mahindapala@sparsl.com; indima.senadheera@sparsl.com; " +
        "siddhartha.durairatnam@sparsl.com; irosha.ranasinghe@sparsl.com; " +
        "rajith.dezoysa@sparsl.com; jegatheeman.palani@sparsl.com; " +
        "Lahiru.Senavirathna@sparsl.com; thushara.jayathilaka@sparsl.com; " +
        "Samith Kanishka <samithk@efl.global>; Supun Kanchana <supunk@efl.global>; " +
        "Anushi Hewamaraba <anushih@efl.global>; Prabodhi Sethsarani Peiris <Prabodhip@efl.global>; " +
        "Nuwangi Wijesena <nuwangiw@efl.global>; Hasitha Kodithuwakku <hasithakod@efl.global>; " +
        "Asitha Samalka <lka-3plcssops11@efl.global>; Sampath Ekanayake <sampathe@efl.global>; " +
        "Shafwan Waffoor <shafwanw@efl.global>; Salinda Madushan <salindam@efl.global>; " +
        "GRN GDN Team <lka-grngdnteam@efl.global>; suranga.babarenda@sparsl.com; " +
        "Ashan Dilentha <ashand@efl.global>; Namith Rajapakse <namithr@efl.global>";

    public static readonly List<string> MlpOrder = [];

    private readonly OutlookComClient _outlookClient = new();

    static PackingListService()
    {
        System.Text.Encoding.RegisterProvider(System.Text.CodePagesEncodingProvider.Instance);
    }

    private static string ConfigPath => Path.Combine(AppPaths.LocalAppDataDir, "packing_list_config.json");

    public string? LoadSavedMailExcelPath()
    {
        try
        {
            if (File.Exists(ConfigPath))
            {
                var json = File.ReadAllText(ConfigPath);
                using var doc = JsonDocument.Parse(json);
                if (doc.RootElement.TryGetProperty("mail_excel_path", out var prop))
                {
                    var p = prop.GetString();
                    if (!string.IsNullOrWhiteSpace(p) && File.Exists(p))
                        return p;
                }
            }
        }
        catch { }
        return null;
    }

    public void SaveMailExcelPath(string path)
    {
        try
        {
            Directory.CreateDirectory(AppPaths.LocalAppDataDir);
            var json = JsonSerializer.Serialize(new { mail_excel_path = path }, new JsonSerializerOptions { WriteIndented = true });
            File.WriteAllText(ConfigPath, json);
        }
        catch { }
    }

    public Dictionary<string, string> ProcessMailExcel(string filePath)
    {
        var emailMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var table = ReadFirstTableFromExcel(filePath)
            ?? throw new InvalidOperationException("Could not read sheets from the specified Mail Excel file.");

        string? codeCol = null;
        string? emailCol = null;

        foreach (DataColumn col in table.Columns)
        {
            var colName = (col.ColumnName ?? string.Empty).Trim().ToLowerInvariant();
            if (codeCol == null && colName.Contains("code"))
                codeCol = col.ColumnName;
            if (emailCol == null && colName.Contains("email"))
                emailCol = col.ColumnName;
        }

        if (codeCol == null || emailCol == null)
            throw new InvalidOperationException("Could not find Outlet Code or Email ID columns in Mail Excel.");

        foreach (DataRow row in table.Rows)
        {
            var codeVal = row[codeCol];
            var emailVal = row[emailCol];

            if (codeVal is null || codeVal is DBNull || emailVal is null || emailVal is DBNull)
                continue;

            var rawCode = codeVal.ToString()?.Trim() ?? string.Empty;
            var email = emailVal.ToString()?.Trim() ?? string.Empty;

            if (string.IsNullOrWhiteSpace(rawCode) || string.IsNullOrWhiteSpace(email))
                continue;

            var cleanCode = CleanOutletCode(rawCode);
            emailMap[cleanCode] = email;
        }

        return emailMap;
    }

    public static string CleanOutletCode(string raw)
    {
        if (string.IsNullOrWhiteSpace(raw))
            return string.Empty;

        var trimmed = raw.Trim();
        if (double.TryParse(trimmed, NumberStyles.Any, CultureInfo.InvariantCulture, out var num))
        {
            long intVal = (long)num;
            return intVal.ToString(CultureInfo.InvariantCulture);
        }

        var stripped = trimmed.TrimStart('0');
        return string.IsNullOrEmpty(stripped) ? "0" : stripped;
    }

    public List<PackingListLocationSummary> ProcessLoadingReport(string filePath)
    {
        var table = ReadFirstTableFromExcel(filePath)
            ?? throw new InvalidOperationException("Could not read data from the loading report file.");

        var colMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (DataColumn col in table.Columns)
        {
            var clean = (col.ColumnName ?? string.Empty).Trim();
            colMap[clean] = col.ColumnName ?? string.Empty;
        }

        string GetCol(string pattern)
        {
            foreach (var kvp in colMap)
            {
                if (kvp.Key.Equals(pattern, StringComparison.OrdinalIgnoreCase) ||
                    kvp.Key.Contains(pattern, StringComparison.OrdinalIgnoreCase))
                    return kvp.Value;
            }
            return string.Empty;
        }

        var colShipToCity = GetCol("Ship To City");
        var colOrderNumber = GetCol("Order Number");
        var colMlp = GetCol("Mlp");
        var colItemNumber = GetCol("Item Number");
        var colDescription = GetCol("Description");
        var colLotNumber = GetCol("Lot Number");
        var colExpDate = GetCol("Expiration Date");
        if (string.IsNullOrEmpty(colExpDate)) colExpDate = GetCol("Expire Date");

        var colPlannedQty = GetCol("Planned Qty");
        var colHuId = GetCol("Hu Id");
        var colGatePass = GetCol("Gate Pass Id");
        if (string.IsNullOrEmpty(colGatePass)) colGatePass = GetCol("Gate Pass");
        var colDeliveryAddr = GetCol("Delivery Addr1");
        if (string.IsNullOrEmpty(colDeliveryAddr)) colDeliveryAddr = GetCol("Delivery Addr");

        if (string.IsNullOrEmpty(colShipToCity))
            throw new InvalidOperationException("Column 'Ship To City' not found in report.");

        // Read all rows
        var rawRows = new List<(
            string ShipToCity,
            string OrderNumber,
            string Mlp,
            string ItemNumber,
            string Description,
            string LotNumber,
            string ExpDate,
            double PlannedQty,
            string HuId,
            string GatePass,
            string DeliveryAddr
        )>();

        var locationOrder = new List<string>();

        foreach (DataRow row in table.Rows)
        {
            var city = (row[colShipToCity]?.ToString() ?? string.Empty).Trim();
            if (string.IsNullOrWhiteSpace(city))
                continue;

            if (!locationOrder.Contains(city, StringComparer.OrdinalIgnoreCase))
                locationOrder.Add(city);

            var orderNo = string.IsNullOrEmpty(colOrderNumber) ? string.Empty : (row[colOrderNumber]?.ToString() ?? string.Empty).Trim();
            var mlp = string.IsNullOrEmpty(colMlp) ? string.Empty : (row[colMlp]?.ToString() ?? string.Empty).Trim();
            var itemNo = string.IsNullOrEmpty(colItemNumber) ? string.Empty : (row[colItemNumber]?.ToString() ?? string.Empty).Trim();
            var desc = string.IsNullOrEmpty(colDescription) ? string.Empty : (row[colDescription]?.ToString() ?? string.Empty).Trim();
            var lotNo = string.IsNullOrEmpty(colLotNumber) ? string.Empty : (row[colLotNumber]?.ToString() ?? string.Empty).Trim();

            string expDate = string.Empty;
            if (!string.IsNullOrEmpty(colExpDate))
            {
                var val = row[colExpDate];
                if (val is DateTime dt)
                    expDate = dt.ToString("dd-MM-yyyy");
                else if (val is not null && val is not DBNull)
                {
                    var s = val.ToString()?.Trim() ?? string.Empty;
                    if (DateTime.TryParse(s, CultureInfo.InvariantCulture, DateTimeStyles.None, out var parsedDt))
                        expDate = parsedDt.ToString("dd-MM-yyyy");
                    else
                        expDate = s;
                }
            }

            double qty = 0;
            if (!string.IsNullOrEmpty(colPlannedQty))
            {
                var qVal = row[colPlannedQty]?.ToString()?.Trim();
                if (!string.IsNullOrWhiteSpace(qVal))
                    double.TryParse(qVal, NumberStyles.Any, CultureInfo.InvariantCulture, out qty);
            }

            var huId = string.IsNullOrEmpty(colHuId) ? string.Empty : (row[colHuId]?.ToString() ?? string.Empty).Trim();
            var gatePass = string.IsNullOrEmpty(colGatePass) ? string.Empty : (row[colGatePass]?.ToString() ?? string.Empty).Trim();
            var delivAddr = string.IsNullOrEmpty(colDeliveryAddr) ? string.Empty : (row[colDeliveryAddr]?.ToString() ?? string.Empty).Trim();

            rawRows.Add((city, orderNo, mlp, itemNo, desc, lotNo, expDate, qty, huId, gatePass, delivAddr));
        }

        // Group rows by [Ship To City, Order Number, Mlp, Item Number, Description, Lot Number, Expiration Date]
        var groupedDict = new Dictionary<string, PackingListGroupedItem>(StringComparer.OrdinalIgnoreCase);

        foreach (var r in rawRows)
        {
            var key = $"{r.ShipToCity}|{r.OrderNumber}|{r.Mlp}|{r.ItemNumber}|{r.Description}|{r.LotNumber}|{r.ExpDate}";
            if (!groupedDict.TryGetValue(key, out var existing))
            {
                existing = new PackingListGroupedItem
                {
                    ShipToCity = r.ShipToCity,
                    OrderNumber = r.OrderNumber,
                    Mlp = r.Mlp,
                    ItemNumber = r.ItemNumber,
                    Description = r.Description,
                    LotNumber = r.LotNumber,
                    ExpirationDate = r.ExpDate,
                    ActualQty = 0,
                    CountOfLPs = 0,
                    GatePassId = r.GatePass,
                    DeliveryAddr1 = r.DeliveryAddr
                };
                groupedDict[key] = existing;
            }

            existing.ActualQty += r.PlannedQty;
            if (!string.IsNullOrWhiteSpace(r.HuId))
                existing.CountOfLPs++;
            else
                existing.CountOfLPs++;

            if (string.IsNullOrEmpty(existing.GatePassId) && !string.IsNullOrEmpty(r.GatePass))
                existing.GatePassId = r.GatePass;
            if (string.IsNullOrEmpty(existing.DeliveryAddr1) && !string.IsNullOrEmpty(r.DeliveryAddr))
                existing.DeliveryAddr1 = r.DeliveryAddr;
        }

        var allGrouped = groupedDict.Values.ToList();

        // Sort rows: preserve location appearance order, then sort by MLP within location
        var summaries = new List<PackingListLocationSummary>();

        foreach (var loc in locationOrder)
        {
            var locItems = allGrouped
                .Where(x => string.Equals(x.ShipToCity, loc, StringComparison.OrdinalIgnoreCase))
                .ToList();

            if (locItems.Count == 0)
                continue;

            locItems.Sort((a, b) =>
            {
                var mlpA = a.Mlp.Trim();
                var mlpB = b.Mlp.Trim();

                bool knownA = MlpOrder.Contains(mlpA);
                bool knownB = MlpOrder.Contains(mlpB);

                if (knownA && knownB)
                {
                    int rankA = MlpOrder.IndexOf(mlpA);
                    int rankB = MlpOrder.IndexOf(mlpB);
                    int cmp = rankA.CompareTo(rankB);
                    if (cmp != 0) return cmp;
                }
                else if (knownA && !knownB)
                {
                    return -1;
                }
                else if (!knownA && knownB)
                {
                    return 1;
                }

                return string.Compare(mlpA, mlpB, StringComparison.OrdinalIgnoreCase);
            });

            var totalQty = locItems.Sum(x => x.ActualQty);
            var firstGatePass = locItems.FirstOrDefault(x => !string.IsNullOrEmpty(x.GatePassId))?.GatePassId ?? string.Empty;
            var firstDeliveryAddr = locItems.FirstOrDefault(x => !string.IsNullOrEmpty(x.DeliveryAddr1))?.DeliveryAddr1 ?? string.Empty;

            summaries.Add(new PackingListLocationSummary
            {
                Location = loc,
                TotalQty = totalQty,
                GatePass = firstGatePass,
                DeliveryAddr = firstDeliveryAddr,
                CleanAddr = CleanOutletCode(firstDeliveryAddr),
                Items = locItems
            });
        }

        return summaries;
    }

    public bool CreateExcelFile(PackingListLocationSummary summary, string savePath)
    {
        try
        {
            using var wb = new XLWorkbook();
            var ws = wb.Worksheets.Add("Packing List");
            ws.ShowGridLines = false;

            var thinBorder = XLBorderStyleValues.Thin;
            var headerBg = XLColor.FromArgb(0x4F, 0x81, 0xBD);

            // Title: A1:H1 merged
            var titleRange = ws.Range("A1:H1");
            titleRange.Merge();
            titleRange.Value = "SPAR Packing List";
            titleRange.Style.Font.FontSize = 16;
            titleRange.Style.Font.Bold = true;
            titleRange.Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Center;
            titleRange.Style.Alignment.Vertical = XLAlignmentVerticalValues.Center;

            // Metadata rows
            ws.Cell(2, 1).Value = "GDN Date :-";
            ws.Cell(2, 2).Value = summary.GdnDate;

            ws.Cell(3, 1).Value = "Vehicle Number :-";
            ws.Cell(3, 2).Value = summary.VehicleNumber;

            ws.Cell(4, 1).Value = "GDN Number :-";
            ws.Cell(4, 2).Value = summary.GdnNumber;

            ws.Cell(6, 1).Value = summary.Location;
            ws.Cell(6, 1).Style.Font.FontSize = 14;
            ws.Cell(6, 1).Style.Font.Bold = true;

            // Table Headers
            string[] tableHeaders =
            [
                "Order Number", "Mlp", "Item Number", "Description",
                "Lot Number", "Expire Date", "Actual Qty", "Count of LPs"
            ];

            const int headerRow = 7;
            for (int colNum = 1; colNum <= tableHeaders.Length; colNum++)
            {
                var cell = ws.Cell(headerRow, colNum);
                cell.Value = tableHeaders[colNum - 1];
                cell.Style.Font.Bold = true;
                cell.Style.Font.FontColor = XLColor.White;
                cell.Style.Fill.BackgroundColor = headerBg;
                cell.Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Center;
                cell.Style.Alignment.Vertical = XLAlignmentVerticalValues.Center;
                cell.Style.Border.SetOutsideBorder(thinBorder);
            }

            double totalQty = 0;
            int totalLps = 0;
            int currentRow = 8;

            foreach (var item in summary.Items)
            {
                ws.Cell(currentRow, 1).Value = item.OrderNumber;
                ws.Cell(currentRow, 2).Value = item.Mlp;
                ws.Cell(currentRow, 3).Value = item.ItemNumber;
                ws.Cell(currentRow, 4).Value = item.Description;
                ws.Cell(currentRow, 5).Value = item.LotNumber;
                ws.Cell(currentRow, 6).Value = item.ExpirationDate;
                ws.Cell(currentRow, 7).Value = item.ActualQty;
                ws.Cell(currentRow, 8).Value = item.CountOfLPs;

                for (int c = 1; c <= 8; c++)
                {
                    var cell = ws.Cell(currentRow, c);
                    cell.Style.Border.SetOutsideBorder(thinBorder);
                    if (c >= 6)
                        cell.Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Center;
                }

                totalQty += item.ActualQty;
                totalLps += item.CountOfLPs;
                currentRow++;
            }

            // Grand Total Row
            var grandCell = ws.Cell(currentRow, 1);
            grandCell.Value = "GRAND TOTAL";
            grandCell.Style.Font.Bold = true;
            grandCell.Style.Border.SetOutsideBorder(thinBorder);

            for (int c = 2; c <= 6; c++)
            {
                ws.Cell(currentRow, c).Style.Border.SetOutsideBorder(thinBorder);
            }

            var qtyTotalCell = ws.Cell(currentRow, 7);
            qtyTotalCell.Value = totalQty;
            qtyTotalCell.Style.Font.Bold = true;
            qtyTotalCell.Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Center;
            qtyTotalCell.Style.Border.SetOutsideBorder(thinBorder);

            var lpsTotalCell = ws.Cell(currentRow, 8);
            lpsTotalCell.Value = totalLps;
            lpsTotalCell.Style.Font.Bold = true;
            lpsTotalCell.Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Center;
            lpsTotalCell.Style.Border.SetOutsideBorder(thinBorder);

            // 3 empty rows
            currentRow += 4;

            // Sign-off section
            ws.Cell(currentRow, 1).Value = "Date";
            ws.Cell(currentRow, 2).Value = "..........................................................";
            ws.Cell(currentRow, 5).Value = "Date";
            ws.Cell(currentRow, 7).Value = "..........................................................";

            currentRow++;
            ws.Cell(currentRow, 1).Value = "Driver Name";
            ws.Cell(currentRow, 2).Value = "..........................................................";
            ws.Cell(currentRow, 5).Value = "Outlet In-charge Name";
            ws.Cell(currentRow, 7).Value = "..........................................................";

            currentRow++;
            ws.Cell(currentRow, 1).Value = "Driver Signature";
            ws.Cell(currentRow, 2).Value = "..........................................................";
            ws.Cell(currentRow, 5).Value = "Outlet In-charge Signature";
            ws.Cell(currentRow, 7).Value = "..........................................................";

            // Column Widths: {'A': 30, 'B': 20, 'C': 22, 'D': 45, 'E': 20, 'F': 20, 'G': 12, 'H': 15}
            ws.Column(1).Width = 30;
            ws.Column(2).Width = 20;
            ws.Column(3).Width = 22;
            ws.Column(4).Width = 45;
            ws.Column(5).Width = 20;
            ws.Column(6).Width = 20;
            ws.Column(7).Width = 12;
            ws.Column(8).Width = 15;

            var dir = Path.GetDirectoryName(savePath);
            if (!string.IsNullOrEmpty(dir))
                Directory.CreateDirectory(dir);

            wb.SaveAs(savePath);
            return true;
        }
        catch
        {
            return false;
        }
    }

    public async Task<bool> SendMailAsync(PackingListLocationSummary summary, string toEmail)
    {
        var tempDir = Path.GetTempPath();
        var tempExcelPath = Path.Combine(tempDir, $"Packing List - {summary.Location}.xlsx");

        if (!CreateExcelFile(summary, tempExcelPath))
            throw new InvalidOperationException("Failed to generate temporary Excel packing list.");

        var subject = $"EFL_GDN - Gate Pass: {summary.GatePass} | GDN: {summary.GdnNumber} | Delivery Location: {summary.Location}";

        var bodyHtml =
            "<div style='font-family: Calibri, Arial, sans-serif; font-size: 11pt;'>" +
            "Dear Team,<br>" +
            "Please find attached the packing list.<br><br>" +
            $"Gate Pass Number - {summary.GatePass}<br>" +
            $"Delivery Location – {summary.Location}<br>" +
            $"GDN Number - {summary.GdnNumber}<br><br>" +
            "<span style='color: red;'>************* This is an automatically generated Mail. *************</span>" +
            "</div>";

        var attachments = new List<string> { tempExcelPath };
        if (!string.IsNullOrWhiteSpace(summary.AttachedPdfPath) && File.Exists(summary.AttachedPdfPath))
        {
            attachments.Add(summary.AttachedPdfPath);
        }

        try
        {
            await _outlookClient.PreviewAsync(
                toAddr: toEmail ?? string.Empty,
                ccAddr: CcEmails,
                subject: subject,
                bodyText: bodyHtml,
                attachmentPaths: attachments,
                includeSignature: false,
                isRawHtmlFragment: true);

            summary.HasSentMail = true;
            return true;
        }
        catch
        {
            try
            {
                Process.Start(new ProcessStartInfo
                {
                    FileName = tempDir,
                    UseShellExecute = true
                });
            }
            catch { }
            throw;
        }
    }

    private static DataTable? ReadFirstTableFromExcel(string filePath)
    {
        using var stream = File.Open(filePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        using var reader = ExcelReaderFactory.CreateReader(stream);
        var result = reader.AsDataSet(new ExcelDataSetConfiguration
        {
            ConfigureDataTable = _ => new ExcelDataTableConfiguration
            {
                UseHeaderRow = true
            }
        });

        if (result.Tables.Count == 0)
            return null;

        return result.Tables[0];
    }
}
