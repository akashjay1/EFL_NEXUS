using System.IO;
using System.Text;
using ClosedXML.Excel;
using EflNexus.Core.Infrastructure;

namespace EflNexus.Core.Kpi;

public sealed record UserKpiExportRow(
    string UnicCode,
    DateTime Date,
    string UserId,
    string UserName,
    string Site,
    string Customer,
    string TCode,
    string TransactionName,
    string Time,
    string Uom,
    int NumberOfTransaction);

public sealed record ReferenceMetricSpec(
    string Task,
    string Uom,
    string Label,
    string SystemName,
    string TCode,
    double Width);

public sealed record KpiExportResult(
    bool Success,
    string Message,
    string OutputPath,
    IReadOnlyList<string> Details);

public static class KpiExcelExporter
{
    public static readonly ReferenceMetricSpec[] ReferenceMetrics =
    [
        new("GRN Reconciliation", "Per Reconciliation Report", "GRN Reconciliation:", "Inbound", "CSSTR0324", 25.71),
        new("GRN Creation", "Per vehicle", "GRN Creation:", "Inbound", "CSSTR0325", 14.86),
        new("GDN Reconciliation", "Per Reconciliation Report", "GDN Reconciliation:", "Outbound", "CSSTR0324", 25.71),
        new("GDN Creation", "Per vehicle", "GDN Creation:", "Outbound", "CSSTR0326", 14.86),
        new("Load Plan / ASN", "Per load plan", "Load Plan or Asn:", "Outbound", "CSSTR0327", 18.14),
        new("Load Audit", "Load ID Count", "Load Audit:", "Outbound", "", 14.57),
        new("Shipping", "Load ID Count", "Shipping:", "Outbound", "", 14.57),
        new("Load Transfer", "Load ID Count", "Load Transfer:", "Outbound", "", 15.0),
        new("Load Transfer", "LP Count", "Load Transfer:", "Outbound", "", 15.0),
        new("Allocation", "LP Count", "Allocation", "Outbound", "", 11.0),
        new("Backorders", "LP Count", "Backorders", "Outbound", "", 12.14),
    ];

    public static (DateTime StartDate, DateTime EndDate) ComputeExportRange(DateTime selectedDate)
    {
        var today = KpiTracking.KpiNow().Date;
        if (selectedDate.Day == 1)
        {
            var firstOfThisMonth = new DateTime(selectedDate.Year, selectedDate.Month, 1);
            var lastOfPrev = firstOfThisMonth.AddDays(-1);
            var firstOfPrev = new DateTime(lastOfPrev.Year, lastOfPrev.Month, 1);
            return (firstOfPrev, lastOfPrev);
        }
        var start = new DateTime(selectedDate.Year, selectedDate.Month, 1);
        var end = selectedDate.Date.AddDays(-1);
        if (end >= today)
            end = today.AddDays(-1);
        if (end < start)
            end = start;
        return (start, end);
    }

    public static void WriteReferenceKpiSheet(
        IXLWorksheet ws,
        IReadOnlyList<KpiExportRow> rows,
        IReadOnlyList<KpiSummaryRow> summary)
    {
        ws.Name = "RECONCILIATION";
        var metrics = ReferenceMetrics.ToList();
        var known = new HashSet<(string Task, string Uom)>(metrics.Select(m => (m.Task, m.Uom)));
        var extras = summary
            .Select(r => (r.TransactionName, r.Uom))
            .Where(k => !known.Contains(k))
            .Distinct()
            .OrderBy(k => k.TransactionName, StringComparer.Ordinal)
            .ThenBy(k => k.Uom, StringComparer.Ordinal);
        foreach (var (task, uom) in extras)
            metrics.Add(new ReferenceMetricSpec(task, uom, task, "", "", Math.Max(18, task.Length + 2)));

        int lastColumn = 5 + metrics.Count * 3;
        int lastRow = 7 + rows.Count;
        var headerFill = XLColor.FromHtml("#BDD7EE");
        var unavailableFill = XLColor.FromHtml("#FFF2CC");
        var fontColor = XLColor.FromHtml("#000000");

        int gridMaxRow = Math.Max(lastRow, 8);
        for (int r = 1; r <= gridMaxRow; r++)
        {
            for (int c = 1; c <= lastColumn; c++)
            {
                var cell = ws.Cell(r, c);
                cell.Style.Font.FontName = "Calibri";
                cell.Style.Font.FontSize = 11;
                cell.Style.Font.FontColor = fontColor;
                cell.Style.Border.LeftBorder = XLBorderStyleValues.Thin;
                cell.Style.Border.RightBorder = XLBorderStyleValues.Thin;
                cell.Style.Border.TopBorder = XLBorderStyleValues.Thin;
                cell.Style.Border.BottomBorder = XLBorderStyleValues.Thin;
                cell.Style.Border.LeftBorderColor = XLColor.Black;
                cell.Style.Border.RightBorderColor = XLColor.Black;
                cell.Style.Border.TopBorderColor = XLColor.Black;
                cell.Style.Border.BottomBorderColor = XLColor.Black;
                cell.Style.Alignment.Vertical = XLAlignmentVerticalValues.Center;
                if (r <= 7)
                    cell.Style.Fill.BackgroundColor = headerFill;
            }
        }

        double[] leftWidths = [12, 18, 13, 12, 12];
        for (int c = 1; c <= leftWidths.Length; c++)
            ws.Column(c).Width = leftWidths[c - 1];

        ws.Cell(2, 5).Value = "TOTAL";
        ws.Cell(3, 5).Value = "CLIENT";
        ws.Cell(4, 5).Value = "SYSTEM";
        ws.Cell(5, 5).Value = "UOM";
        ws.Cell(6, 5).Value = "T-CODE";

        string[] row7Headers = ["DATE", "USER", "IN-TIME", "U-CODE", "SITE"];
        for (int c = 1; c <= row7Headers.Length; c++)
            ws.Cell(7, c).Value = row7Headers[c - 1];

        var totals = new Dictionary<(string Task, string Uom), int?>();
        foreach (var row in summary)
        {
            var key = (row.TransactionName, row.Uom);
            if (!row.KpiTotal.HasValue || (totals.TryGetValue(key, out var existing) && !existing.HasValue))
                totals[key] = null;
            else
                totals[key] = totals.GetValueOrDefault(key, 0)!.Value + row.KpiTotal.Value;
        }

        for (int idx = 0; idx < metrics.Count; idx++)
        {
            var m = metrics[idx];
            int column = 6 + idx * 3;
            ws.Column(column).Width = m.Width;
            if (totals.TryGetValue((m.Task, m.Uom), out var totalVal))
            {
                if (totalVal.HasValue)
                    ws.Cell(2, column).Value = totalVal.Value;
                else
                    ws.Cell(2, column).Value = Blank.Value;
            }
            else
            {
                ws.Cell(2, column).Value = 0;
            }

            ws.Cell(4, column).Value = m.SystemName;
            ws.Cell(5, column).Value = m.Uom;
            ws.Cell(6, column).Value = m.TCode;
            ws.Cell(7, column).Value = m.Label;
        }

        for (int i = 0; i < rows.Count; i++)
        {
            int rowNumber = 8 + i;
            var rec = rows[i];
            ws.Cell(rowNumber, 1).Value = rec.RegisteredDate;
            ws.Cell(rowNumber, 1).Style.NumberFormat.Format = "mm-dd-yy";
            ws.Cell(rowNumber, 2).Value = rec.UserName;
            if (rec.RegisteredTime.HasValue)
                ws.Cell(rowNumber, 3).Value = rec.RegisteredTime.Value;
            else
                ws.Cell(rowNumber, 3).Value = Blank.Value;
            ws.Cell(rowNumber, 3).Style.NumberFormat.Format = "hh:mm:ss";
            ws.Cell(rowNumber, 4).Value = rec.UserCode;
            ws.Cell(rowNumber, 5).Value = rec.Site;

            var quantities = KpiTracking.BuildSummaryRows([rec])
                .ToDictionary(s => (s.TransactionName, s.Uom), s => s.KpiTotal);

            for (int idx = 0; idx < metrics.Count; idx++)
            {
                var m = metrics[idx];
                var cell = ws.Cell(rowNumber, 6 + idx * 3);
                if (quantities.TryGetValue((m.Task, m.Uom), out var qty))
                {
                    if (qty.HasValue)
                        cell.Value = qty.Value;
                    else
                        cell.Style.Fill.BackgroundColor = unavailableFill;
                }
                cell.Style.NumberFormat.Format = "#,##0";
            }
        }

        for (int r = 1; r <= 7; r++)
            ws.Row(r).Height = 16;
        for (int r = 8; r <= gridMaxRow; r++)
            ws.Row(r).Height = 18;

        ws.SheetView.FreezeRows(7);
        ws.SheetView.FreezeColumns(5);
        ws.Range(7, 1, Math.Max(lastRow, 7), lastColumn).SetAutoFilter();
        ws.ShowGridLines = false;

        if (rows.Count > 0)
        {
            ws.Range($"C8:C{lastRow}")
                .AddConditionalFormat()
                .WhenIsTrue("=ISBLANK(C8)")
                .Fill.SetBackgroundColor(unavailableFill);
        }

        string[] notes =
        [
            "IN-TIME is the KPI registration time in Sri Lanka (UTC+05:30). Highlighted blank times or quantities are unavailable in the source.",
            "GRN/GDN Creation totals include the agreed credit from Reconciliation."
        ];
        for (int offset = 0; offset < notes.Length; offset++)
        {
            int num = Math.Max(lastRow, 8) + 2 + offset;
            ws.Range(num, 1, num, lastColumn).Merge();
            var noteCell = ws.Cell(num, 1);
            noteCell.Value = notes[offset];
            noteCell.Style.Font.FontName = "Calibri";
            noteCell.Style.Font.FontSize = 11;
            noteCell.Style.Font.FontColor = XLColor.FromHtml("#64748B");
        }
    }

    public static void WriteTransactionLog(IXLWorksheet ws, IReadOnlyList<KpiExportRow> rows)
    {
        for (int c = 0; c < KpiTracking.ExportHeaders.Length; c++)
        {
            var cell = ws.Cell(1, c + 1);
            cell.Value = KpiTracking.ExportHeaders[c];
            cell.Style.Font.FontName = "Calibri";
            cell.Style.Font.Bold = true;
            cell.Style.Font.FontSize = 11;
            cell.Style.Font.FontColor = XLColor.Black;
            cell.Style.Fill.BackgroundColor = XLColor.FromHtml("#BDD7EE");
            cell.Style.Alignment.WrapText = true;
            cell.Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Center;
            cell.Style.Alignment.Vertical = XLAlignmentVerticalValues.Center;
        }
        ws.Row(1).Height = 32;

        double[] widths = [19, 19, 22, 18, 16, 29, 26, 16, 14, 17, 14, 18];
        for (int c = 0; c < widths.Length; c++)
            ws.Column(c + 1).Width = widths[c];

        var evenFill = XLColor.FromHtml("#F0F4F8");
        for (int i = 0; i < rows.Count; i++)
        {
            int rowNum = i + 2;
            var rec = rows[i];

            ws.Cell(rowNum, 1).Value = rec.RegisteredDate;
            if (rec.RegisteredTime.HasValue)
                ws.Cell(rowNum, 2).Value = rec.RegisteredTime.Value;
            else
                ws.Cell(rowNum, 2).Value = Blank.Value;
            ws.Cell(rowNum, 3).Value = rec.UserName;
            ws.Cell(rowNum, 4).Value = rec.UserCode;
            ws.Cell(rowNum, 5).Value = rec.Site;
            ws.Cell(rowNum, 6).Value = rec.TransactionName;
            ws.Cell(rowNum, 7).Value = rec.JobOrReferenceId;
            ws.Cell(rowNum, 8).Value = rec.Status;
            ws.Cell(rowNum, 9).Value = rec.EntryCount;
            if (rec.LoadIdCount.HasValue)
                ws.Cell(rowNum, 10).Value = rec.LoadIdCount.Value;
            if (rec.LpCount.HasValue)
                ws.Cell(rowNum, 11).Value = rec.LpCount.Value;
            ws.Cell(rowNum, 12).Value = rec.TCode;

            for (int c = 1; c <= KpiTracking.ExportHeaders.Length; c++)
            {
                var cell = ws.Cell(rowNum, c);
                cell.Style.Font.FontName = "Calibri";
                cell.Style.Font.FontSize = 11;
                cell.Style.Font.FontColor = XLColor.Black;
                cell.Style.Alignment.WrapText = true;
                cell.Style.Alignment.Vertical = XLAlignmentVerticalValues.Center;
                if (rowNum % 2 == 0)
                    cell.Style.Fill.BackgroundColor = evenFill;
            }

            ws.Cell(rowNum, 1).Style.NumberFormat.Format = "yyyy-mm-dd";
            ws.Cell(rowNum, 2).Style.NumberFormat.Format = "hh:mm:ss";
            foreach (int numCol in new[] { 9, 10, 11 })
            {
                ws.Cell(rowNum, numCol).Style.NumberFormat.Format = "#,##0";
                ws.Cell(rowNum, numCol).Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Right;
            }
            ws.Row(rowNum).Height = 30;
        }

        ws.SheetView.FreezeRows(1);
        ws.SheetView.FreezeColumns(2);
        ws.Range(1, 1, rows.Count + 1, KpiTracking.ExportHeaders.Length).SetAutoFilter();
        ws.ShowGridLines = false;

        ws.Column(14).Width = 65;
        string[] notes =
        [
            "Registration times: Sri Lanka (UTC+05:30).",
            "Blank time: unavailable in the original record."
        ];
        for (int idx = 0; idx < notes.Length; idx++)
        {
            var noteCell = ws.Cell(idx + 1, 14);
            noteCell.Value = notes[idx];
            noteCell.Style.Font.FontName = "Calibri";
            noteCell.Style.Font.FontSize = 11;
            noteCell.Style.Font.FontColor = XLColor.FromHtml("#64748B");
        }

        if (rows.Count > 0)
        {
            ws.Range($"B2:B{rows.Count + 1}")
                .AddConditionalFormat()
                .WhenIsTrue("=ISBLANK(B2)")
                .Fill.SetBackgroundColor(XLColor.FromHtml("#FFF2CC"));
        }
    }

    private sealed record AggregatedKpiKey(
        DateTime Date,
        string Site,
        string Customer,
        string TCode,
        string TransactionName);

    private static int TransactionSortOrder(string tCode, string taskName)
    {
        return tCode switch
        {
            "CSSTR0324" => 1,
            "CSSTR0325" => 2,
            "CSSTR0326" => 3,
            "CSSTR0327" => 4,
            _ => 10
        };
    }

    public static List<UserKpiExportRow> BuildUserKpiExportRows(
        IEnumerable<KpiExportRow> rows,
        string configuredUserCode = "",
        string configuredUserName = "")
    {
        var counts = new Dictionary<AggregatedKpiKey, int>();
        string userCode = (configuredUserCode ?? string.Empty).Trim();
        string userName = (configuredUserName ?? string.Empty).Trim();

        if (string.IsNullOrEmpty(userCode))
        {
            var saved = KpiProfile.LoadSavedProfile();
            if (saved != null && !string.IsNullOrWhiteSpace(saved.UserCode))
                userCode = saved.UserCode.Trim();
            else
            {
                var store = new ConfigStore();
                userCode = (store.Get("kpi_user_code") ?? string.Empty).Trim();
            }
        }

        if (string.IsNullOrEmpty(userName))
        {
            var saved = KpiProfile.LoadSavedProfile();
            if (saved != null && !string.IsNullOrWhiteSpace(saved.UserId))
                userName = saved.UserId.Trim();
            else
            {
                var store = new ConfigStore();
                userName = (store.Get("kpi_user_id") ?? string.Empty).Trim();
            }
        }

        void AddCount(DateTime date, string site, string customer, string tCode, string taskName, int count)
        {
            if (count <= 0) return;
            var key = new AggregatedKpiKey(date.Date, site, customer, tCode, taskName);
            counts[key] = counts.GetValueOrDefault(key) + count;
        }

        var today = KpiTracking.KpiNow().Date;
        foreach (var rec in rows)
        {
            if (rec.RegisteredDate.Date >= today)
                continue;

            if (string.IsNullOrEmpty(userCode) && !string.IsNullOrWhiteSpace(rec.UserCode))
                userCode = rec.UserCode.Trim();
            if (string.IsNullOrEmpty(userName) && !string.IsNullOrWhiteSpace(rec.UserName))
                userName = rec.UserName.Trim();

            var date = rec.RegisteredDate.Date;
            var site = string.IsNullOrWhiteSpace(rec.Site) ? "Unassigned" : rec.Site.Trim().ToUpperInvariant();
            var customer = string.IsNullOrWhiteSpace(rec.Customer) ? "RECONCILIATION" : rec.Customer.Trim();
            var taskNorm = KpiTracking.Norm(rec.TransactionName);

            if (taskNorm is "gdn reconciliation" or "grn reconciliation")
            {
                AddCount(date, site, "RECONCILIATION", "CSSTR0324", "Reconciliation", rec.EntryCount > 0 ? rec.EntryCount : 1);

                if (taskNorm == "gdn reconciliation")
                    AddCount(date, site, "RECONCILIATION", "CSSTR0326", "GDN Creation", rec.EntryCount > 0 ? rec.EntryCount : 1);
                else
                    AddCount(date, site, "RECONCILIATION", "CSSTR0325", "GRN Creation", rec.EntryCount > 0 ? rec.EntryCount : 1);
                continue;
            }

            if (taskNorm == "gdn creation")
            {
                AddCount(date, site, "RECONCILIATION", "CSSTR0326", "GDN Creation", rec.EntryCount > 0 ? rec.EntryCount : 1);
                continue;
            }

            if (taskNorm == "grn creation")
            {
                AddCount(date, site, "RECONCILIATION", "CSSTR0325", "GRN Creation", rec.EntryCount > 0 ? rec.EntryCount : 1);
                continue;
            }

            if (taskNorm is "load plan / asn" or "load plan or asn")
            {
                AddCount(date, site, "RECONCILIATION", "CSSTR0327", "Loading plan creation and upload into the portal", rec.EntryCount > 0 ? rec.EntryCount : 1);
                continue;
            }

            if (taskNorm == "load audit")
            {
                AddCount(date, site, customer, "", "Load Audit", rec.LoadIdCount ?? (rec.EntryCount > 0 ? rec.EntryCount : 1));
                continue;
            }

            if (taskNorm == "shipping")
            {
                AddCount(date, site, customer, "", "Shipping", rec.LoadIdCount ?? (rec.EntryCount > 0 ? rec.EntryCount : 1));
                continue;
            }

            if (taskNorm == "load transfer")
            {
                int count = rec.LoadIdCount ?? rec.LpCount ?? (rec.EntryCount > 0 ? rec.EntryCount : 1);
                AddCount(date, site, customer, "", "Load Transfer", count);
                continue;
            }

            if (taskNorm == "allocation")
            {
                AddCount(date, site, customer, "", "Allocation", rec.LpCount ?? (rec.EntryCount > 0 ? rec.EntryCount : 1));
                continue;
            }

            if (taskNorm == "backorders")
            {
                AddCount(date, site, customer, "", "Backorders", rec.LpCount ?? (rec.EntryCount > 0 ? rec.EntryCount : 1));
                continue;
            }

            if (taskNorm == "allocation/backorders")
            {
                AddCount(date, site, customer, "", "Allocation/Backorders", rec.LpCount ?? (rec.EntryCount > 0 ? rec.EntryCount : 1));
                continue;
            }

            int fallbackCount = rec.LoadIdCount ?? rec.LpCount ?? (rec.EntryCount > 0 ? rec.EntryCount : 1);
            AddCount(date, site, customer, rec.TCode, rec.TransactionName, fallbackCount);
        }

        if (string.IsNullOrEmpty(userCode) && !string.IsNullOrEmpty(configuredUserCode))
            userCode = configuredUserCode.Trim();
        if (string.IsNullOrEmpty(userName) && !string.IsNullOrEmpty(configuredUserName))
            userName = configuredUserName.Trim();

        return counts
            .OrderBy(kv => kv.Key.Date)
            .ThenBy(kv => kv.Key.Site, StringComparer.Ordinal)
            .ThenBy(kv => TransactionSortOrder(kv.Key.TCode, kv.Key.TransactionName))
            .ThenBy(kv => kv.Key.TransactionName, StringComparer.Ordinal)
            .Select(kv => new UserKpiExportRow(
                UnicCode: "",
                Date: kv.Key.Date,
                UserId: userCode,
                UserName: userName,
                Site: kv.Key.Site,
                Customer: kv.Key.Customer,
                TCode: kv.Key.TCode,
                TransactionName: kv.Key.TransactionName,
                Time: "NORMAL",
                Uom: "",
                NumberOfTransaction: kv.Value))
            .ToList();
    }

    public static void WriteUserKpiSheet(IXLWorksheet ws, IReadOnlyList<UserKpiExportRow> exportRows)
    {
        ws.Name = "User KPI";
        string[] headers =
        [
            "UNIC CODE", "DATE", "USER ID", "USER NAME", "SITE", "CUSTOMMER",
            "T-CODE", "TRANSACTION NAME", "TIME", "UOM", "# OF TRANSACTION"
        ];

        for (int c = 0; c < headers.Length; c++)
        {
            var cell = ws.Cell(1, c + 1);
            cell.Value = headers[c];
            cell.Style.Font.FontName = "Calibri";
            cell.Style.Font.Bold = true;
            cell.Style.Font.FontSize = 11;
            cell.Style.Font.FontColor = XLColor.Black;
            cell.Style.Fill.BackgroundColor = XLColor.FromHtml("#BDD7EE");
            cell.Style.Alignment.WrapText = true;
            cell.Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Center;
            cell.Style.Alignment.Vertical = XLAlignmentVerticalValues.Center;
        }
        ws.Row(1).Height = 28;

        double[] widths = [14, 14, 16, 18, 12, 20, 15, 38, 14, 12, 18];
        for (int c = 0; c < widths.Length; c++)
            ws.Column(c + 1).Width = widths[c];

        var evenFill = XLColor.FromHtml("#F0F4F8");

        for (int i = 0; i < exportRows.Count; i++)
        {
            int rowNum = i + 2;
            var item = exportRows[i];

            ws.Cell(rowNum, 1).Value = item.UnicCode;
            ws.Cell(rowNum, 1).Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Center;

            ws.Cell(rowNum, 2).Value = item.Date;
            ws.Cell(rowNum, 2).Style.NumberFormat.Format = "yyyy-mm-dd";
            ws.Cell(rowNum, 2).Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Center;

            ws.Cell(rowNum, 3).Value = item.UserId;
            ws.Cell(rowNum, 3).Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Center;

            ws.Cell(rowNum, 4).Value = item.UserName;
            ws.Cell(rowNum, 4).Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Left;

            ws.Cell(rowNum, 5).Value = item.Site;
            ws.Cell(rowNum, 5).Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Center;

            ws.Cell(rowNum, 6).Value = item.Customer;
            ws.Cell(rowNum, 6).Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Left;

            ws.Cell(rowNum, 7).Value = item.TCode;
            ws.Cell(rowNum, 7).Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Center;

            ws.Cell(rowNum, 8).Value = item.TransactionName;
            ws.Cell(rowNum, 8).Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Left;

            ws.Cell(rowNum, 9).Value = item.Time;
            ws.Cell(rowNum, 9).Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Center;

            ws.Cell(rowNum, 10).Value = item.Uom;
            ws.Cell(rowNum, 10).Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Center;

            ws.Cell(rowNum, 11).Value = item.NumberOfTransaction;
            ws.Cell(rowNum, 11).Style.NumberFormat.Format = "#,##0";
            ws.Cell(rowNum, 11).Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Right;

            for (int c = 1; c <= headers.Length; c++)
            {
                var cell = ws.Cell(rowNum, c);
                cell.Style.Font.FontName = "Calibri";
                cell.Style.Font.FontSize = 11;
                cell.Style.Font.FontColor = XLColor.Black;
                cell.Style.Alignment.Vertical = XLAlignmentVerticalValues.Center;
                cell.Style.Border.LeftBorder = XLBorderStyleValues.Thin;
                cell.Style.Border.RightBorder = XLBorderStyleValues.Thin;
                cell.Style.Border.TopBorder = XLBorderStyleValues.Thin;
                cell.Style.Border.BottomBorder = XLBorderStyleValues.Thin;
                cell.Style.Border.LeftBorderColor = XLColor.FromHtml("#E2E8F0");
                cell.Style.Border.RightBorderColor = XLColor.FromHtml("#E2E8F0");
                cell.Style.Border.TopBorderColor = XLColor.FromHtml("#E2E8F0");
                cell.Style.Border.BottomBorderColor = XLColor.FromHtml("#E2E8F0");

                if (rowNum % 2 == 0)
                    cell.Style.Fill.BackgroundColor = evenFill;
            }
            ws.Row(rowNum).Height = 22;
        }

        ws.SheetView.FreezeRows(1);
        ws.Range(1, 1, Math.Max(exportRows.Count + 1, 2), headers.Length).SetAutoFilter();
        ws.ShowGridLines = true;
    }

    public static void WriteUserKpiCsv(string csvPath, IReadOnlyList<UserKpiExportRow> exportRows)
    {
        var sb = new StringBuilder();
        sb.AppendLine("UNIC CODE,DATE,USER ID,USER NAME,SITE,CUSTOMMER,T-CODE,TRANSACTION NAME,TIME,UOM,# OF TRANSACTION");

        foreach (var item in exportRows)
        {
            string dateStr = item.Date.ToString("yyyy-MM-dd");
            sb.AppendLine(string.Join(",",
                item.UnicCode,
                dateStr,
                CsvEscape(item.UserId),
                CsvEscape(item.UserName),
                CsvEscape(item.Site),
                CsvEscape(item.Customer),
                CsvEscape(item.TCode),
                CsvEscape(item.TransactionName),
                CsvEscape(item.Time),
                item.Uom,
                item.NumberOfTransaction.ToString()
            ));
        }

        File.WriteAllText(csvPath, sb.ToString(), Encoding.UTF8);
    }

    private static string CsvEscape(string? value)
    {
        if (string.IsNullOrEmpty(value)) return "";
        if (value.Contains(',') || value.Contains('"') || value.Contains('\n') || value.Contains('\r'))
            return $"\"{value.Replace("\"", "\"\"")}\"";
        return value;
    }

    public static KpiExportResult GenerateUserExport(
        string folder,
        string userId,
        string userCode,
        DateTime selectedDate,
        IReadOnlyList<IReadOnlyList<string>> values1,
        IReadOnlyList<IReadOnlyList<string>> values2,
        IReadOnlyDictionary<string, JobMapEntry>? jobMap = null)
    {
        if (string.IsNullOrWhiteSpace(userCode) || string.IsNullOrWhiteSpace(userId))
        {
            var saved = KpiProfile.LoadSavedProfile();
            if (saved != null)
            {
                if (string.IsNullOrWhiteSpace(userCode)) userCode = saved.UserCode;
                if (string.IsNullOrWhiteSpace(userId)) userId = saved.UserId;
            }
            var store = new ConfigStore();
            if (string.IsNullOrWhiteSpace(userCode))
                userCode = (store.Get("kpi_user_code") ?? string.Empty).Trim();
            if (string.IsNullOrWhiteSpace(userId))
                userId = (store.Get("kpi_user_id") ?? string.Empty).Trim();
        }
        userCode = (userCode ?? string.Empty).Trim();
        userId = (userId ?? string.Empty).Trim();

        var (startDate, endDate) = ComputeExportRange(selectedDate);
        var path = Path.Combine(folder, KpiProfile.ExportFilename(userId, startDate, endDate));
        var tempPath = Path.Combine(folder, $".kpi_{Guid.NewGuid():N}.xlsx");
        try
        {
            Directory.CreateDirectory(folder);
            var rows = KpiTracking.BuildExportRows(values1, userId, userCode, startDate, endDate, jobMap, values2);
            var summary = KpiTracking.BuildSummaryRows(rows);
            var exportRows = BuildUserKpiExportRows(rows, userCode, userId);

            using (var wb = new XLWorkbook())
            {
                var wsKpi = wb.AddWorksheet("User KPI");
                WriteUserKpiSheet(wsKpi, exportRows);

                var ws1 = wb.AddWorksheet("RECONCILIATION");
                WriteReferenceKpiSheet(ws1, rows, summary);

                var ws2 = wb.AddWorksheet("Transaction Log");
                WriteTransactionLog(ws2, rows);

                wb.SaveAs(tempPath);
            }

            File.Move(tempPath, path, overwrite: true);

            try
            {
                var csvPath = Path.ChangeExtension(path, ".csv");
                WriteUserKpiCsv(csvPath, exportRows);
            }
            catch
            {
            }

            return new KpiExportResult(
                true,
                "Excel saved.",
                path,
                [$"{exportRows.Count} KPI rows ({rows.Count} registered entries)", "User KPI sheet, Reference KPI sheet and Transaction Log"]);
        }
        catch (Exception ex)
        {
            return new KpiExportResult(false, ex.Message, path, []);
        }
        finally
        {
            if (File.Exists(tempPath))
            {
                try { File.Delete(tempPath); } catch { }
            }
        }
    }
}
