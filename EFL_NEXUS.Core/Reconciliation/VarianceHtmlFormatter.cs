using System.Net;
using System.Text;
using System.Text.RegularExpressions;

namespace EflNexus.Core.Reconciliation;

/// <summary>
/// Builds ASCII box-drawing grid tables and converts them + prose body text into Outlook-ready HTML
/// (exact 1:1 port of SendVarianceDialog._insert_grid_table / _convert_ascii_table_to_html / _compose_variance_html).
/// </summary>
public static class VarianceHtmlFormatter
{
    public sealed record StyledSegment(string Text, string Tag);

    public static List<StyledSegment> BuildGridTableSegments(List<List<string>> grid)
    {
        var segments = new List<StyledSegment>();
        if (grid.Count == 0)
            return segments;

        int maxCols = grid.Max(r => r.Count);
        if (maxCols < 1)
            return segments;

        var normGrid = grid
            .Select(r =>
            {
                var copy = r.Select(c => (c ?? "").Trim()).ToList();
                while (copy.Count < maxCols) copy.Add("");
                return copy;
            })
            .ToList();

        var colWidths = new int[maxCols];
        for (int c = 0; c < maxCols; c++)
        {
            int maxW = normGrid.Max(r => r[c].Length);
            colWidths[c] = Math.Max(maxW, 8);
        }

        string MakeBorder(string left, string mid, string right, char fill = '─')
            => left + string.Join(mid, colWidths.Select(w => new string(fill, w + 2))) + right;

        string topBorder = MakeBorder("┌", "┬", "┐");
        string midBorder = MakeBorder("├", "┼", "┤");
        string botBorder = MakeBorder("└", "┴", "┘");

        segments.Add(new StyledSegment("\n", "tbl_cell"));
        segments.Add(new StyledSegment(topBorder + "\n", "tbl_border"));

        for (int rIdx = 0; rIdx < normGrid.Count; rIdx++)
        {
            bool isHeader = rIdx == 0;
            var row = normGrid[rIdx];
            segments.Add(new StyledSegment("│", "tbl_border"));

            for (int cIdx = 0; cIdx < maxCols; cIdx++)
            {
                var val = row[cIdx];
                var padded = " " + val.PadRight(colWidths[cIdx]) + " ";
                var upper = val.ToUpperInvariant();

                string tag;
                if (isHeader)
                    tag = "tbl_header";
                else if (upper.Contains("MATCH") || val == "Exact match")
                    tag = "tbl_match";
                else if (upper.Contains("VARIANCE"))
                    tag = "tbl_variance";
                else if (upper.Contains("MISSING") || upper.Contains("EXTRA"))
                    tag = "tbl_missing";
                else
                    tag = "tbl_cell";

                segments.Add(new StyledSegment(padded, tag));
                segments.Add(new StyledSegment("│", "tbl_border"));
            }
            segments.Add(new StyledSegment("\n", "tbl_cell"));

            if (isHeader && normGrid.Count > 1)
                segments.Add(new StyledSegment(midBorder + "\n", "tbl_border"));
        }

        segments.Add(new StyledSegment(botBorder + "\n\n", "tbl_border"));
        return segments;
    }

    public static string BuildGridTableText(List<List<string>> grid)
        => string.Concat(BuildGridTableSegments(grid).Select(s => s.Text));

    public static string ConvertAsciiTableToHtml(IReadOnlyList<string> tableLines)
    {
        var dataRows = new List<List<string>>();
        foreach (var line in tableLines)
        {
            var s = (line ?? "").Trim();
            if (string.IsNullOrEmpty(s) || s.StartsWith('┌') || s.StartsWith('├') || s.StartsWith('└') || s.StartsWith('+'))
                continue;
            if (s.Contains('│'))
            {
                var parts = s.Split('│');
                if (parts.Length >= 3)
                {
                    var cells = parts[1..^1].Select(c => c.Trim()).ToList();
                    if (cells.Any(c => !string.IsNullOrEmpty(c)))
                        dataRows.Add(cells);
                }
            }
        }

        if (dataRows.Count == 0)
            return "";

        int maxCols = dataRows.Max(r => r.Count);
        var htmlRows = new StringBuilder();

        for (int rIdx = 0; rIdx < dataRows.Count; rIdx++)
        {
            bool isHeader = rIdx == 0;
            var row = dataRows[rIdx];
            var tdTags = new StringBuilder();

            for (int cIdx = 0; cIdx < maxCols; cIdx++)
            {
                var val = cIdx < row.Count ? row[cIdx].Trim() : "";
                if (isHeader)
                {
                    const string thStyle =
                        "background-color: #1c3f60; color: #ffffff; font-weight: bold; " +
                        "padding: 8px 14px; border: 1px solid #0d1826; text-align: left; font-size: 10pt;";
                    tdTags.Append($"<th style=\"{thStyle}\">{WebUtility.HtmlEncode(val)}</th>");
                }
                else
                {
                    var valUpper = val.ToUpperInvariant();
                    string bgColor = "#ffffff";
                    string fgColor = "#1f2937";
                    string fontWeight = "normal";

                    if (valUpper.Contains("MATCH") || val == "Exact match" || valUpper.Contains("EXACT MATCH"))
                    {
                        bgColor = "#d4edda";
                        fgColor = "#155724";
                        fontWeight = "bold";
                    }
                    else if (valUpper.Contains("MAJOR VARIANCE") || valUpper.Contains("LARGE VARIANCE"))
                    {
                        bgColor = "#f8d7da";
                        fgColor = "#721c24";
                        fontWeight = "bold";
                    }
                    else if (valUpper.Contains("VARIANCE") || valUpper.Contains("MODERATE VARIANCE") || valUpper.Contains("MINOR VARIANCE"))
                    {
                        bgColor = "#fff3cd";
                        fgColor = "#856404";
                        fontWeight = "bold";
                    }
                    else if (valUpper.Contains("EXTRA") || valUpper.Contains("MISSING"))
                    {
                        bgColor = "#e2e3e5";
                        fgColor = "#383d41";
                        fontWeight = "bold";
                    }
                    else if (rIdx % 2 == 1)
                    {
                        bgColor = "#f8fafc";
                    }

                    string tdStyle =
                        $"background-color: {bgColor}; color: {fgColor}; font-weight: {fontWeight}; " +
                        "padding: 6px 12px; border: 1px solid #cbd5e1; font-size: 10pt;";
                    tdTags.Append($"<td style=\"{tdStyle}\">{WebUtility.HtmlEncode(val)}</td>");
                }
            }
            htmlRows.Append("<tr>").Append(tdTags).Append("</tr>");
        }

        const string tableStyle =
            "border-collapse: collapse; width: auto; margin: 12px 0; " +
            "font-family: Calibri, Segoe UI, Arial, sans-serif; " +
            "border: 1px solid #0d1826;";
        return $"<table border=\"1\" cellpadding=\"0\" cellspacing=\"0\" style=\"{tableStyle}\">{htmlRows}</table>";
    }

    public static string ComposeVarianceBodyFragment(string bodyText)
    {
        var lines = (bodyText ?? "").Replace("\r\n", "\n").Split('\n');
        var htmlParts = new StringBuilder();
        bool inTable = false;
        var tableLines = new List<string>();

        foreach (var line in lines)
        {
            bool isTblLine =
                line.StartsWith('┌') ||
                line.StartsWith("+---", StringComparison.Ordinal) ||
                (line.Contains('│') && (line.StartsWith('│') || line.EndsWith('│'))) ||
                line.StartsWith('├') ||
                line.StartsWith('└') ||
                line.StartsWith('+');

            if (isTblLine)
            {
                if (!inTable)
                {
                    inTable = true;
                    tableLines.Clear();
                }
                tableLines.Add(line);
            }
            else
            {
                if (inTable)
                {
                    htmlParts.Append(ConvertAsciiTableToHtml(tableLines));
                    inTable = false;
                    tableLines.Clear();
                }

                if (!string.IsNullOrWhiteSpace(line))
                    htmlParts.Append($"<div style=\"margin: 4px 0;\">{WebUtility.HtmlEncode(line)}</div>");
                else
                    htmlParts.Append("<div style=\"height: 12px;\"></div>");
            }
        }

        if (inTable)
            htmlParts.Append(ConvertAsciiTableToHtml(tableLines));

        return "<div style=\"font-family:Calibri,Arial,sans-serif;font-size:11pt;color:#000000;\">"
            + htmlParts
            + "</div>";
    }

    public static string ComposeVarianceHtml(string bodyText, string signatureHtml)
    {
        var messageHtml = ComposeVarianceBodyFragment(bodyText) + "<br>";

        if (!string.IsNullOrEmpty(signatureHtml))
        {
            var match = Regex.Match(signatureHtml, @"(<body[^>]*>)", RegexOptions.IgnoreCase);
            if (match.Success)
            {
                int idx = match.Index + match.Length;
                return signatureHtml[..idx] + messageHtml + signatureHtml[idx..];
            }
            return messageHtml + signatureHtml;
        }
        return $"<html><body>{messageHtml}</body></html>";
    }
}
