using System.Globalization;
using System.IO;
using System.Text;
using KorberAuditShip.Models;

namespace KorberAuditShip.Services;

/// <summary>
/// Exports the Aligned Data Table as an A4 Landscape PDF matching KORBER AuditShip's
/// ReportLab layout: "3PL EFL" header, export timestamp, #2563EB repeated table headers,
/// zebra striping (#FFFFFF / #F8FAFC), grid borders (#CBD5E1 / #64748B), and wrapped cells.
/// Implemented in pure managed C# with built-in Helvetica Type 1 fonts so it requires no external native dependencies.
/// </summary>
public sealed class PdfExportService
{
    private const double PageWidth = 841.89;   // A4 landscape width in points
    private const double PageHeight = 595.28;  // A4 landscape height in points
    private const double Margin = 24.0;
    private const double CellPaddingH = 5.0;
    private const double CellPaddingV = 4.0;
    private const double HeaderFontSize = 7.6;
    private const double HeaderLeading = 9.2;
    private const double CellFontSize = 7.2;
    private const double CellLeading = 8.6;

    // Preferred relative weights from FINAL_CODE2_DEFAULT_KAWSHI.py
    private static readonly double[] ColumnWeights = [0.55, 1.05, 1.15, 0.95, 2.1, 2.1];

    public void ExportPdf(IReadOnlyList<AuditShipRow> rows, string outputPath, DateTime? timestamp = null)
    {
        if (rows.Count == 0)
            throw new InvalidOperationException("No aligned table data to export. Upload Excel first.");

        var exportedAt = timestamp ?? DateTime.Now;
        var printableWidth = PageWidth - (Margin * 2.0);
        var weightSum = ColumnWeights.Sum();
        var colWidths = ColumnWeights.Select(w => printableWidth * (w / weightSum)).ToArray();

        // Pre-wrap header and body rows
        var headers = SpreadsheetService.AllColumns.ToArray();
        var wrappedHeaders = headers
            .Select((h, i) => WrapText(h, colWidths[i] - CellPaddingH * 2, HeaderFontSize, isBold: true))
            .ToArray();
        var headerHeight = Math.Max(18.0, wrappedHeaders.Max(lines => lines.Count) * HeaderLeading + CellPaddingV * 2);

        var bodyRows = new List<(string[] Raw, List<string>[] Wrapped, double Height)>(rows.Count);
        foreach (var row in rows)
        {
            var raw = new[]
            {
                SpreadsheetService.FormatExportValue(row.WhId),
                SpreadsheetService.FormatExportValue(row.LoadId),
                SpreadsheetService.FormatExportValue(row.GatePassId),
                SpreadsheetService.FormatExportValue(row.DoorLocation),
                SpreadsheetService.FormatExportValue(row.LoadAuditStatus),
                SpreadsheetService.FormatExportValue(row.ShippingStatus)
            };

            var wrapped = new List<string>[raw.Length];
            var maxLines = 1;
            for (var c = 0; c < raw.Length; c++)
            {
                wrapped[c] = WrapText(raw[c], colWidths[c] - CellPaddingH * 2, CellFontSize, isBold: false);
                if (wrapped[c].Count > maxLines)
                    maxLines = wrapped[c].Count;
            }

            var rowHeight = Math.Max(15.0, maxLines * CellLeading + CellPaddingV * 2);
            bodyRows.Add((raw, wrapped, rowHeight));
        }

        // Paginate
        var pages = BuildPageStreams(exportedAt, colWidths, wrappedHeaders, headerHeight, bodyRows);
        WritePdfDocument(outputPath, pages);
    }

    private static List<string> BuildPageStreams(
        DateTime exportedAt,
        double[] colWidths,
        List<string>[] wrappedHeaders,
        double headerHeight,
        List<(string[] Raw, List<string>[] Wrapped, double Height)> bodyRows)
    {
        var pageStreams = new List<string>();
        var startX = Margin;
        var tableTotalWidth = colWidths.Sum();
        var rowIndex = 0;
        var isFirstPage = true;

        while (rowIndex < bodyRows.Count || isFirstPage)
        {
            var sb = new StringBuilder();
            var cursorY = PageHeight - Margin;

            if (isFirstPage)
            {
                // Title: "3PL EFL" 22pt Helvetica-Bold #0f172a centered
                cursorY -= 22.0;
                DrawCenteredText(sb, "3PL EFL", PageWidth / 2.0, cursorY, "F2", 22.0, 0.059, 0.090, 0.165);
                cursorY -= 4.0; // spaceAfter

                // Subtitle: 9pt Helvetica #475569 centered
                cursorY -= 12.0;
                var subtitle = $"Aligned Data Table | Exported: {exportedAt:yyyy-MM-dd HH:mm:ss}";
                DrawCenteredText(sb, subtitle, PageWidth / 2.0, cursorY, "F1", 9.0, 0.278, 0.333, 0.412);
                cursorY -= 14.0; // Spacer(1, 14)
            }

            var tableTopY = cursorY;

            // Draw table header (#2563EB background, white bold centered text)
            var headerBottomY = cursorY - headerHeight;
            FillRect(sb, startX, headerBottomY, tableTotalWidth, headerHeight, 0.145, 0.388, 0.922);

            var colX = startX;
            for (var c = 0; c < colWidths.Length; c++)
            {
                var lines = wrappedHeaders[c];
                var blockHeight = lines.Count * HeaderLeading;
                var textTopY = headerBottomY + (headerHeight + blockHeight) / 2.0 - HeaderFontSize * 0.85;
                for (var l = 0; l < lines.Count; l++)
                {
                    DrawCenteredText(
                        sb,
                        lines[l],
                        colX + colWidths[c] / 2.0,
                        textTopY - l * HeaderLeading,
                        "F2",
                        HeaderFontSize,
                        1.0, 1.0, 1.0);
                }

                colX += colWidths[c];
            }

            cursorY = headerBottomY;
            var bodyRowCountOnPage = 0;

            while (rowIndex < bodyRows.Count)
            {
                var item = bodyRows[rowIndex];
                if (cursorY - item.Height < Margin && bodyRowCountOnPage > 0)
                    break;

                var rowBottomY = cursorY - item.Height;
                var isAlt = rowIndex % 2 == 1;
                if (isAlt)
                    FillRect(sb, startX, rowBottomY, tableTotalWidth, item.Height, 0.973, 0.980, 0.988); // #f8fafc
                else
                    FillRect(sb, startX, rowBottomY, tableTotalWidth, item.Height, 1.0, 1.0, 1.0);

                colX = startX;
                for (var c = 0; c < colWidths.Length; c++)
                {
                    var lines = item.Wrapped[c];
                    var blockHeight = lines.Count * CellLeading;
                    var textTopY = rowBottomY + (item.Height + blockHeight) / 2.0 - CellFontSize * 0.82;
                    for (var l = 0; l < lines.Count; l++)
                    {
                        DrawLeftText(
                            sb,
                            lines[l],
                            colX + CellPaddingH,
                            textTopY - l * CellLeading,
                            "F1",
                            CellFontSize,
                            0.059, 0.090, 0.165); // #0f172a
                    }

                    colX += colWidths[c];
                }

                // Interior horizontal bottom rule for this row (#cbd5e1, 0.35pt)
                StrokeLine(sb, startX, rowBottomY, startX + tableTotalWidth, rowBottomY, 0.35, 0.796, 0.835, 0.882);

                cursorY = rowBottomY;
                rowIndex++;
                bodyRowCountOnPage++;
            }

            var tableBottomY = cursorY;

            // Header bottom line + interior vertical lines (#cbd5e1, 0.35pt)
            StrokeLine(sb, startX, tableTopY - headerHeight, startX + tableTotalWidth, tableTopY - headerHeight, 0.35, 0.796, 0.835, 0.882);
            var vx = startX;
            for (var c = 0; c < colWidths.Length - 1; c++)
            {
                vx += colWidths[c];
                StrokeLine(sb, vx, tableTopY, vx, tableBottomY, 0.35, 0.796, 0.835, 0.882);
            }

            // Outer box (#64748b, 0.8pt)
            StrokeRect(sb, startX, tableBottomY, tableTotalWidth, tableTopY - tableBottomY, 0.8, 0.392, 0.455, 0.545);

            pageStreams.Add(sb.ToString());
            isFirstPage = false;
        }

        return pageStreams;
    }

    private static void WritePdfDocument(string outputPath, List<string> pageStreams)
    {
        // Objects:
        // 1: Catalog
        // 2: Pages
        // 3: Font F1 (Helvetica)
        // 4: Font F2 (Helvetica-Bold)
        // For each page i (0..N-1):
        //   PageObj = 5 + i*2
        //   ContentObj = 6 + i*2
        var objects = new List<string>
        {
            "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
            "" // placeholder for 2 Pages
        };

        var kids = new List<string>(pageStreams.Count);
        for (var i = 0; i < pageStreams.Count; i++)
            kids.Add($"{5 + i * 2} 0 R");

        objects[1] = $"2 0 obj\n<< /Type /Pages /Kids [{string.Join(' ', kids)}] /Count {pageStreams.Count} >>\nendobj\n";
        objects.Add("3 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>\nendobj\n");
        objects.Add("4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>\nendobj\n");

        var mediaBox = string.Format(CultureInfo.InvariantCulture, "[0 0 {0:F2} {1:F2}]", PageWidth, PageHeight);
        for (var i = 0; i < pageStreams.Count; i++)
        {
            var pageObjNum = 5 + i * 2;
            var contentObjNum = pageObjNum + 1;
            var streamData = pageStreams[i];
            var streamByteLen = Encoding.Latin1.GetByteCount(streamData);

            objects.Add(
                $"{pageObjNum} 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox {mediaBox} /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {contentObjNum} 0 R >>\nendobj\n");
            objects.Add(
                $"{contentObjNum} 0 obj\n<< /Length {streamByteLen} >>\nstream\n{streamData}endstream\nendobj\n");
        }

        using var fs = new FileStream(outputPath, FileMode.Create, FileAccess.Write, FileShare.None);
        var enc = Encoding.Latin1;

        void WriteAscii(string s)
        {
            var bytes = enc.GetBytes(s);
            fs.Write(bytes, 0, bytes.Length);
        }

        WriteAscii("%PDF-1.4\n%\xE2\xE3\xCF\xD3\n");

        var offsets = new long[objects.Count + 1];
        for (var i = 0; i < objects.Count; i++)
        {
            offsets[i + 1] = fs.Position;
            WriteAscii(objects[i]);
        }

        var xrefStart = fs.Position;
        WriteAscii($"xref\n0 {objects.Count + 1}\n");
        WriteAscii("0000000000 65535 f \n");
        for (var i = 1; i <= objects.Count; i++)
            WriteAscii(string.Format(CultureInfo.InvariantCulture, "{0:D10} 00000 n \n", offsets[i]));

        WriteAscii(
            $"trailer\n<< /Size {objects.Count + 1} /Root 1 0 R >>\nstartxref\n{xrefStart}\n%%EOF\n");
    }

    private static void DrawCenteredText(StringBuilder sb, string text, double centerX, double y, string fontRef, double fontSize, double r, double g, double b)
    {
        var width = MeasureTextWidth(text, fontSize, fontRef == "F2");
        var x = centerX - (width / 2.0);
        DrawLeftText(sb, text, x, y, fontRef, fontSize, r, g, b);
    }

    private static void DrawLeftText(StringBuilder sb, string text, double x, double y, string fontRef, double fontSize, double r, double g, double b)
    {
        if (string.IsNullOrEmpty(text))
            return;

        sb.AppendFormat(
            CultureInfo.InvariantCulture,
            "BT /{0} {1:F2} Tf {2:F3} {3:F3} {4:F3} rg 1 0 0 1 {5:F2} {6:F2} Tm ({7}) Tj ET\n",
            fontRef,
            fontSize,
            r, g, b,
            x, y,
            EscapePdfString(text));
    }

    private static void FillRect(StringBuilder sb, double x, double y, double w, double h, double r, double g, double b)
    {
        sb.AppendFormat(
            CultureInfo.InvariantCulture,
            "{0:F3} {1:F3} {2:F3} rg {3:F2} {4:F2} {5:F2} {6:F2} re f\n",
            r, g, b, x, y, w, h);
    }

    private static void StrokeRect(StringBuilder sb, double x, double y, double w, double h, double lineWidth, double r, double g, double b)
    {
        sb.AppendFormat(
            CultureInfo.InvariantCulture,
            "{0:F2} w {1:F3} {2:F3} {3:F3} RG {4:F2} {5:F2} {6:F2} {7:F2} re S\n",
            lineWidth, r, g, b, x, y, w, h);
    }

    private static void StrokeLine(StringBuilder sb, double x1, double y1, double x2, double y2, double lineWidth, double r, double g, double b)
    {
        sb.AppendFormat(
            CultureInfo.InvariantCulture,
            "{0:F2} w {1:F3} {2:F3} {3:F3} RG {4:F2} {5:F2} m {6:F2} {7:F2} l S\n",
            lineWidth, r, g, b, x1, y1, x2, y2);
    }

    private static string EscapePdfString(string text)
    {
        var sb = new StringBuilder(text.Length + 8);
        foreach (var ch in text)
        {
            var safe = ch > 0xFF ? '?' : ch;
            switch (safe)
            {
                case '\\': sb.Append("\\\\"); break;
                case '(': sb.Append("\\("); break;
                case ')': sb.Append("\\)"); break;
                default: sb.Append(safe); break;
            }
        }
        return sb.ToString();
    }

    private static List<string> WrapText(string text, double maxWidth, double fontSize, bool isBold)
    {
        if (string.IsNullOrEmpty(text))
            return [string.Empty];

        if (MeasureTextWidth(text, fontSize, isBold) <= maxWidth)
            return [text];

        var lines = new List<string>();
        var words = text.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        var current = new StringBuilder();

        foreach (var word in words)
        {
            if (current.Length == 0)
            {
                if (MeasureTextWidth(word, fontSize, isBold) <= maxWidth)
                {
                    current.Append(word);
                }
                else
                {
                    SplitLongWord(word, maxWidth, fontSize, isBold, lines, current);
                }
            }
            else
            {
                var candidate = current + " " + word;
                if (MeasureTextWidth(candidate, fontSize, isBold) <= maxWidth)
                {
                    current.Append(' ').Append(word);
                }
                else
                {
                    lines.Add(current.ToString());
                    current.Clear();
                    if (MeasureTextWidth(word, fontSize, isBold) <= maxWidth)
                        current.Append(word);
                    else
                        SplitLongWord(word, maxWidth, fontSize, isBold, lines, current);
                }
            }
        }

        if (current.Length > 0)
            lines.Add(current.ToString());

        return lines.Count > 0 ? lines : [string.Empty];
    }

    private static void SplitLongWord(
        string word,
        double maxWidth,
        double fontSize,
        bool isBold,
        List<string> lines,
        StringBuilder current)
    {
        foreach (var ch in word)
        {
            var next = current.ToString() + ch;
            if (current.Length > 0 && MeasureTextWidth(next, fontSize, isBold) > maxWidth)
            {
                lines.Add(current.ToString());
                current.Clear();
            }
            current.Append(ch);
        }
    }

    private static double MeasureTextWidth(string text, double fontSize, bool isBold)
    {
        var factor = isBold ? 0.58 : 0.54;
        var sum = 0.0;
        foreach (var ch in text)
        {
            sum += ch switch
            {
                'i' or 'l' or 'I' or '.' or ',' or ':' or ';' or '\'' or '!' or '|' => 0.28,
                'f' or 'j' or 'r' or 't' or '-' or ' ' => 0.34,
                'W' or 'M' or 'm' or 'w' or 'Q' or 'O' or 'G' => 0.78,
                >= 'A' and <= 'Z' => 0.66,
                >= '0' and <= '9' => 0.56,
                _ => factor
            };
        }
        return sum * fontSize;
    }
}
