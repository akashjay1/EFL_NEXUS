using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;
using EflNexus.Core.Reconciliation;
using MediaBrushes = System.Windows.Media.Brushes;
using MediaColor = System.Windows.Media.Color;
using MediaFontFamily = System.Windows.Media.FontFamily;

namespace EflNexus.App.Helpers;

public static class RichTextTableHelper
{
    private static readonly MediaFontFamily MonoFont = new("Consolas");

    public static void ConfigureFlatParagraphSpacing(System.Windows.Controls.RichTextBox rtb)
    {
        var style = new Style(typeof(Paragraph));
        style.Setters.Add(new Setter(Block.MarginProperty, new Thickness(0)));
        rtb.Resources[typeof(Paragraph)] = style;
    }

    public static void SetPlainText(System.Windows.Controls.RichTextBox rtb, string text)
    {
        var doc = new FlowDocument { PageWidth = 10000 };
        var p = new Paragraph { Margin = new Thickness(0) };
        p.Inlines.Add(new Run(text ?? string.Empty));
        doc.Blocks.Add(p);
        rtb.Document = doc;
    }

    public static string GetPlainText(System.Windows.Controls.RichTextBox rtb)
    {
        var doc = rtb.Document;
        if (doc is null || doc.Blocks.Count == 0)
            return string.Empty;

        var raw = new TextRange(doc.ContentStart, doc.ContentEnd).Text;
        raw = raw.Replace("\r\n", "\n");
        if (raw.EndsWith('\n'))
            raw = raw[..^1];
        return raw;
    }

    public static void InsertTextAtCaret(System.Windows.Controls.RichTextBox rtb, string text)
    {
        var caret = rtb.CaretPosition;
        if (rtb.Selection is not null && !rtb.Selection.IsEmpty)
            rtb.Selection.Text = string.Empty;
        caret.InsertTextInRun(text ?? string.Empty);
    }

    public static bool TryPasteExcelOrText(System.Windows.Controls.RichTextBox rtb)
    {
        string plainText = string.Empty;
        try
        {
            if (System.Windows.Clipboard.ContainsText(System.Windows.TextDataFormat.UnicodeText))
                plainText = System.Windows.Clipboard.GetText(System.Windows.TextDataFormat.UnicodeText);
            else if (System.Windows.Clipboard.ContainsText())
                plainText = System.Windows.Clipboard.GetText();
        }
        catch
        {
            return false;
        }

        if (string.IsNullOrEmpty(plainText))
            return false;

        var lines = plainText
            .Trim()
            .Replace("\r\n", "\n")
            .Split('\n')
            .Select(l => l.TrimEnd('\r'))
            .Where(l => !string.IsNullOrWhiteSpace(l))
            .ToList();

        if (lines.Count == 0)
            return false;

        var grid = lines.Select(line => line.Split('\t').ToList()).ToList();
        int maxCols = grid.Max(r => r.Count);

        if (maxCols >= 2 || (grid.Count > 1 && plainText.Contains('\t')))
        {
            InsertGridTable(rtb, grid);
            return true;
        }

        InsertTextAtCaret(rtb, plainText);
        return true;
    }

    public static void InsertGridTable(System.Windows.Controls.RichTextBox rtb, List<List<string>> grid)
    {
        var segments = VarianceHtmlFormatter.BuildGridTableSegments(grid);
        if (segments.Count == 0)
            return;

        if (rtb.Selection is not null && !rtb.Selection.IsEmpty)
            rtb.Selection.Text = string.Empty;

        var caret = rtb.CaretPosition;
        foreach (var seg in segments)
        {
            var (bg, fg, weight) = StyleForTag(seg.Tag);
            var parts = seg.Text.Split('\n');
            for (int i = 0; i < parts.Length; i++)
            {
                if (parts[i].Length > 0)
                {
                    var run = new Run(parts[i], caret)
                    {
                        FontFamily = MonoFont,
                        FontSize = 12,
                        FontWeight = weight,
                        Foreground = fg
                    };
                    if (bg is not null)
                        run.Background = bg;
                    caret = run.ContentEnd;
                }

                if (i < parts.Length - 1)
                {
                    caret = caret.InsertParagraphBreak();
                }
            }
        }
        rtb.CaretPosition = caret;
    }

    private static (System.Windows.Media.Brush? Bg, System.Windows.Media.Brush Fg, FontWeight Weight) StyleForTag(string tag)
    {
        return tag switch
        {
            "tbl_header" => (
                new SolidColorBrush(MediaColor.FromRgb(0x1C, 0x3F, 0x60)),
                MediaBrushes.White,
                FontWeights.Bold),
            "tbl_border" => (
                null,
                new SolidColorBrush(MediaColor.FromRgb(0x64, 0x74, 0x8B)),
                FontWeights.Normal),
            "tbl_match" => (
                new SolidColorBrush(MediaColor.FromRgb(0xD4, 0xED, 0xDA)),
                new SolidColorBrush(MediaColor.FromRgb(0x15, 0x57, 0x24)),
                FontWeights.Bold),
            "tbl_variance" => (
                new SolidColorBrush(MediaColor.FromRgb(0xF8, 0xD7, 0xDA)),
                new SolidColorBrush(MediaColor.FromRgb(0x72, 0x1C, 0x24)),
                FontWeights.Bold),
            "tbl_missing" => (
                new SolidColorBrush(MediaColor.FromRgb(0xFF, 0xF3, 0xCD)),
                new SolidColorBrush(MediaColor.FromRgb(0x85, 0x64, 0x04)),
                FontWeights.Bold),
            _ => (null, System.Windows.SystemColors.ControlTextBrush, FontWeights.Normal)
        };
    }
}
