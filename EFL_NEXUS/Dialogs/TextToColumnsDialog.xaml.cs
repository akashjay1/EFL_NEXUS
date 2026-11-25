using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;
using EflNexus.App.Helpers;
using MediaBrush = System.Windows.Media.Brush;
using MediaColor = System.Windows.Media.Color;
using MediaFontFamily = System.Windows.Media.FontFamily;
using MediaPen = System.Windows.Media.Pen;
using MediaPoint = System.Windows.Point;
using SolidBrush = System.Windows.Media.SolidColorBrush;

namespace EflNexus.App.Dialogs;

public partial class TextToColumnsDialog : Window
{
    private const double XStart = 50.0;
    private const double YStart = 28.0;
    private const double LineHeight = 25.0;

    private readonly IReadOnlyList<string> _columnData;
    private readonly string _columnName;
    private readonly bool _isDarkMode;
    private readonly List<int> _splitPositions = [];

    private double _charWidth = 6.6;
    private readonly int _previewRows;

    private int? _draggingSplitValue;
    private MediaPoint _dragStartPoint;
    private bool _didDrag;

    public List<int> Widths { get; private set; } = [];
    public List<List<string>>? ResultData { get; private set; }

    public TextToColumnsDialog(
        Window? owner,
        string title,
        IReadOnlyList<string> columnData,
        string? columnName = null,
        bool isDarkMode = false)
    {
        InitializeComponent();
        App.TrySetWindowIcon(this);
        Title = title;
        ImageLoader.SizeAndCenterDialog(this, owner, 0.85, 0.85, 1000, 700);

        _columnData = columnData;
        _columnName = string.IsNullOrWhiteSpace(columnName) ? "Unknown" : columnName;
        _isDarkMode = isDarkMode;
        _previewRows = Math.Min(10, columnData.Count);

        ColumnNameLabel.Text = _columnName;
        TotalRowsLabel.Text = columnData.Count.ToString(CultureInfo.InvariantCulture);

        PopulateSampleData();
        ApplyTheme();

        Loaded += (_, _) =>
        {
            MeasureCharWidth();
            RenderPreview();
            UpdateDetails();
        };
    }

    private void MeasureCharWidth()
    {
        try
        {
            var dpi = VisualTreeHelper.GetDpi(this).PixelsPerDip;
            var ft = new FormattedText(
                "WWWWWWWWWW",
                CultureInfo.InvariantCulture,
                System.Windows.FlowDirection.LeftToRight,
                new Typeface(new MediaFontFamily("Consolas"), FontStyles.Normal, FontWeights.Normal, FontStretches.Normal),
                12.0,
                System.Windows.Media.Brushes.Black,
                dpi);
            _charWidth = ft.WidthIncludingTrailingWhitespace / 10.0;
            if (_charWidth <= 0)
                _charWidth = 6.6;
        }
        catch
        {
            _charWidth = 6.6;
        }
    }

    private void PopulateSampleData()
    {
        var sb = new StringBuilder();
        sb.AppendLine("Row | Data");
        sb.AppendLine(new string('-', 60));
        for (int i = 0; i < Math.Min(5, _columnData.Count); i++)
            sb.AppendLine($"{i + 1,3} | {_columnData[i]}");
        SampleText.Text = sb.ToString();
    }

    private void ApplyTheme()
    {
        var bg = new SolidBrush(_isDarkMode ? MediaColor.FromRgb(0x0B, 0x14, 0x20) : MediaColor.FromRgb(0xFA, 0xF8, 0xF2));
        var panel = new SolidBrush(_isDarkMode ? MediaColor.FromRgb(0x13, 0x23, 0x3A) : MediaColor.FromRgb(0xFF, 0xFF, 0xFF));
        var fg = new SolidBrush(_isDarkMode ? MediaColor.FromRgb(0xEC, 0xEC, 0xEC) : MediaColor.FromRgb(0x0F, 0x17, 0x2A));
        var entryBg = new SolidBrush(_isDarkMode ? MediaColor.FromRgb(0x16, 0x2E, 0x4C) : MediaColor.FromRgb(0xFF, 0xFF, 0xFF));

        Background = bg;
        InstructionLabel.Foreground = fg;
        PreviewGroup.Foreground = fg;
        DetailsGroup.Foreground = fg;
        ResultGroup.Foreground = fg;
        SplitInfoGroup.Foreground = fg;
        StatusText.Foreground = fg;

        PreviewCanvas.Background = panel;
        ResultText.Background = entryBg;
        ResultText.Foreground = fg;
        SampleText.Background = entryBg;
        SampleText.Foreground = fg;
        SplitInfoText.Background = entryBg;
        SplitInfoText.Foreground = fg;
    }

    private int GetCharPosition(double x)
    {
        double rel = x - XStart;
        if (rel < 0)
            return 0;
        return (int)Math.Round(rel / _charWidth);
    }

    private int GetMaxLength()
    {
        int maxLen = 0;
        for (int i = 0; i < _previewRows; i++)
        {
            int len = (_columnData[i] ?? string.Empty).Length;
            if (len > maxLen)
                maxLen = len;
        }
        return maxLen;
    }

    private void RenderPreview()
    {
        PreviewCanvas.Children.Clear();
        var fg = new SolidBrush(_isDarkMode ? MediaColor.FromRgb(0xEC, 0xEC, 0xEC) : MediaColor.FromRgb(0x0F, 0x17, 0x2A));
        var grayBrush = new SolidBrush(MediaColor.FromRgb(0x64, 0x74, 0x8B));
        var markerBrush = new SolidBrush(MediaColor.FromRgb(0xE7, 0x4C, 0x3C));
        var markerDark = new SolidBrush(MediaColor.FromRgb(0xC0, 0x39, 0x2B));

        if (_columnData.Count == 0)
        {
            AddCanvasText(10, 10, "No data to preview", grayBrush, 12, false, "Segoe UI");
            return;
        }

        int maxLength = GetMaxLength();
        double canvasW = Math.Max(700, XStart + maxLength * _charWidth + 120);
        double canvasH = Math.Max(260, YStart + (_previewRows + 2) * LineHeight + 24);
        PreviewCanvas.Width = canvasW;
        PreviewCanvas.Height = canvasH;

        AddCanvasText(XStart - 16, YStart - 6, "#", fg, 12, true, "Segoe UI");
        AddCanvasText(XStart, YStart - 6, "Data", fg, 12, true, "Segoe UI");

        var headerLine = new Line
        {
            X1 = XStart - 20,
            Y1 = YStart + 14,
            X2 = XStart + maxLength * _charWidth + 100,
            Y2 = YStart + 14,
            Stroke = grayBrush,
            StrokeThickness = 1
        };
        PreviewCanvas.Children.Add(headerLine);

        for (int i = 0; i < _previewRows; i++)
        {
            double yPos = YStart + (i + 1) * LineHeight + 4;
            string textStr = _columnData[i] ?? string.Empty;

            AddCanvasText(XStart - 22, yPos, (i + 1).ToString(CultureInfo.InvariantCulture), grayBrush, 11, false, "Segoe UI");
            AddCanvasText(XStart, yPos, textStr, fg, 12, false, "Consolas");

            foreach (int pos in _splitPositions)
            {
                if (pos < textStr.Length)
                {
                    double markerX = XStart + pos * _charWidth;
                    AddCanvasText(markerX - 5, yPos + 12, "▼", markerBrush, 11, true, "Segoe UI");
                    var vline = new Line
                    {
                        X1 = markerX,
                        Y1 = YStart + 14,
                        X2 = markerX,
                        Y2 = yPos + 16,
                        Stroke = markerBrush,
                        StrokeThickness = 1,
                        StrokeDashArray = [3, 3]
                    };
                    PreviewCanvas.Children.Add(vline);
                }
            }
        }

        foreach (int pos in _splitPositions)
        {
            double markerX = XStart + pos * _charWidth;
            var fillBox = new System.Windows.Shapes.Rectangle
            {
                Width = 8,
                Height = 10,
                Fill = markerBrush,
                Stroke = markerDark,
                StrokeThickness = 1
            };
            Canvas.SetLeft(fillBox, markerX - 4);
            Canvas.SetTop(fillBox, YStart - 14);
            PreviewCanvas.Children.Add(fillBox);

            AddCanvasText(markerX - 6, YStart - 26, "▼", markerBrush, 14, true, "Segoe UI");

            var handleBox = new System.Windows.Shapes.Rectangle
            {
                Width = 16,
                Height = 20,
                Fill = System.Windows.Media.Brushes.Transparent,
                Stroke = markerBrush,
                StrokeThickness = 2
            };
            Canvas.SetLeft(handleBox, markerX - 8);
            Canvas.SetTop(handleBox, YStart - 23);
            PreviewCanvas.Children.Add(handleBox);
        }

        UpdateDetails();
    }

    private void AddCanvasText(double x, double y, string text, MediaBrush foreground, double size, bool bold, string font)
    {
        var tb = new TextBlock
        {
            Text = text,
            Foreground = foreground,
            FontSize = size,
            FontWeight = bold ? FontWeights.Bold : FontWeights.Normal,
            FontFamily = new MediaFontFamily(font),
            IsHitTestVisible = false
        };
        Canvas.SetLeft(tb, x);
        Canvas.SetTop(tb, y);
        PreviewCanvas.Children.Add(tb);
    }

    private void UpdateDetails()
    {
        if (_splitPositions.Count == 0)
        {
            SplitInfoText.Text = "No splits configured yet.\nDrag the ▼ arrows above to set split points.";
            WarningLabel.Text = string.Empty;
            return;
        }

        int maxLength = GetMaxLength();
        var widths = new List<int>();
        int prev = 0;
        var sorted = _splitPositions.OrderBy(p => p).ToList();
        foreach (int pos in sorted)
        {
            widths.Add(pos - prev);
            prev = pos;
        }
        widths.Add(Math.Max(0, maxLength - prev));

        var sb = new StringBuilder();
        sb.AppendLine($"Split Points: {sorted.Count}");
        sb.AppendLine($"Positions: {string.Join(", ", sorted)}");
        sb.AppendLine($"Column Widths: {string.Join(", ", widths)}");
        sb.AppendLine($"Total Columns: {widths.Count}");
        sb.AppendLine();
        sb.AppendLine("Column Preview (first row):");

        if (_columnData.Count > 0)
        {
            string text = _columnData[0] ?? string.Empty;
            var parts = new List<string>();
            int pos = 0;
            for (int i = 0; i < widths.Count - 1; i++)
            {
                int w = widths[i];
                if (pos < text.Length)
                {
                    parts.Add($"[{text.Substring(pos, Math.Min(w, text.Length - pos)).Trim()}]");
                    pos += w;
                }
                else
                {
                    parts.Add("[]");
                }
            }
            parts.Add(pos < text.Length ? $"[{text[pos..].Trim()}]" : "[]");
            sb.Append(string.Join(" | ", parts));
        }

        SplitInfoText.Text = sb.ToString();

        var warns = new List<string>();
        if (widths.Count > 10)
            warns.Add("⚠️ Many columns created (>10) - verify this is intended");
        if (widths.Take(Math.Max(0, widths.Count - 1)).Any(w => w < 2))
            warns.Add("⚠️ Very narrow columns detected (width < 2 chars)");
        if (widths.Count > 0 && widths[^1] > 50)
            warns.Add("ℹ️ Last column is very wide - may contain remaining data");

        if (warns.Count > 0)
        {
            WarningLabel.Foreground = new SolidBrush(MediaColor.FromRgb(0xDC, 0x26, 0x26));
            WarningLabel.Text = string.Join("\n", warns);
        }
        else
        {
            WarningLabel.Foreground = new SolidBrush(MediaColor.FromRgb(0x16, 0xA3, 0x4A));
            WarningLabel.Text = "✅ Split configuration looks good";
        }

        StatusText.Text = $"Ready - {widths.Count} columns, widths: {string.Join(", ", widths)}";
    }

    private void PreviewCanvas_MouseMove(object sender, System.Windows.Input.MouseEventArgs e)
    {
        var p = e.GetPosition(PreviewCanvas);
        if (_draggingSplitValue.HasValue && e.LeftButton == MouseButtonState.Pressed)
        {
            if (Math.Abs(p.X - _dragStartPoint.X) >= 3.0)
                _didDrag = true;

            if (_didDrag)
            {
                int maxLength = GetMaxLength();
                int newPos = Math.Max(1, Math.Min(GetCharPosition(p.X), Math.Max(1, maxLength - 1)));
                if (newPos != _draggingSplitValue.Value && !_splitPositions.Contains(newPos))
                {
                    _splitPositions.Remove(_draggingSplitValue.Value);
                    _splitPositions.Add(newPos);
                    _splitPositions.Sort();
                    _draggingSplitValue = newPos;
                    RenderPreview();
                    PreviewResult();
                    StatusText.Text = $"🔄 Moving split to position {newPos}";
                }
            }
            return;
        }

        int hoverPos = GetCharPosition(p.X);
        int maxLen = GetMaxLength();
        StatusText.Text = hoverPos >= 0 && hoverPos <= maxLen
            ? $"Position: {hoverPos} | Click to add split at this position"
            : "Ready - Drag arrows to set split points";

        foreach (int splitPos in _splitPositions)
        {
            double markerX = XStart + splitPos * _charWidth;
            if (Math.Abs(p.X - markerX) < 15 && Math.Abs(p.Y - YStart) < 30)
            {
                PreviewCanvas.Cursor = System.Windows.Input.Cursors.SizeWE;
                return;
            }
        }
        PreviewCanvas.Cursor = System.Windows.Input.Cursors.Arrow;
    }

    private void PreviewCanvas_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        var p = e.GetPosition(PreviewCanvas);
        foreach (int splitPos in _splitPositions)
        {
            double markerX = XStart + splitPos * _charWidth;
            if (Math.Abs(p.X - markerX) < 15 && Math.Abs(p.Y - YStart) < 30)
            {
                _draggingSplitValue = splitPos;
                _dragStartPoint = p;
                _didDrag = false;
                PreviewCanvas.CaptureMouse();
                return;
            }
        }

        int pos = GetCharPosition(p.X);
        int maxLen = GetMaxLength();
        if (pos > 0 && pos < maxLen && !_splitPositions.Contains(pos))
        {
            _splitPositions.Add(pos);
            _splitPositions.Sort();
            RenderPreview();
            PreviewResult();
            StatusText.Text = $"✅ Split added at position {pos}";
        }
    }

    private void PreviewCanvas_MouseLeftButtonUp(object sender, MouseButtonEventArgs e)
    {
        if (PreviewCanvas.IsMouseCaptured)
            PreviewCanvas.ReleaseMouseCapture();

        if (_draggingSplitValue.HasValue)
        {
            if (!_didDrag)
            {
                _splitPositions.Remove(_draggingSplitValue.Value);
                _splitPositions.Sort();
                RenderPreview();
                PreviewResult();
            }
            else
            {
                StatusText.Text = "✅ Split position updated";
            }
            _draggingSplitValue = null;
            _didDrag = false;
        }
        PreviewCanvas.Cursor = System.Windows.Input.Cursors.Arrow;
    }

    private void ClearSplits_Click(object sender, RoutedEventArgs e)
    {
        _splitPositions.Clear();
        RenderPreview();
        ResultText.Text = string.Empty;
        StatusText.Text = "🧹 All splits cleared";
    }

    private void AutoDetect_Click(object sender, RoutedEventArgs e)
    {
        if (_columnData.Count == 0)
            return;

        string text = _columnData[0] ?? string.Empty;
        (string Pattern, string Name)[] patterns =
        [
            (@"\t", "Tab"),
            (@"  +", "Multiple spaces"),
            (@",", "Comma"),
            (@"\|", "Pipe")
        ];

        foreach (var (pattern, name) in patterns)
        {
            var matches = Regex.Matches(text, pattern);
            if (matches.Count >= 2)
            {
                _splitPositions.Clear();
                foreach (Match m in matches)
                {
                    if (m.Index > 0 && !_splitPositions.Contains(m.Index))
                        _splitPositions.Add(m.Index);
                }
                _splitPositions.Sort();
                RenderPreview();
                PreviewResult();
                StatusText.Text = $"🔍 Auto-detected {_splitPositions.Count} splits using {name} delimiter";
                return;
            }
        }

        if (_columnData.Count >= 3)
        {
            var lengths = _columnData.Take(3).Select(s => (s ?? string.Empty).Length).ToList();
            if (lengths.All(l => l > 10))
            {
                int maxLen = lengths.Max();
                var suggested = Enumerable.Range(1, Math.Max(0, (maxLen - 1) / 10)).Select(i => i * 10).ToList();
                if (suggested.Count >= 2)
                {
                    _splitPositions.Clear();
                    _splitPositions.AddRange(suggested);
                    _splitPositions.Sort();
                    RenderPreview();
                    PreviewResult();
                    StatusText.Text = $"🔍 Auto-detected fixed-width splits at positions: {string.Join(", ", suggested)}";
                    return;
                }
            }
        }

        StatusText.Text = "⚠️ Could not auto-detect splits. Please set them manually.";
    }

    private void RefreshPreview_Click(object sender, RoutedEventArgs e) => PreviewResult();

    private void PreviewResult()
    {
        if (_splitPositions.Count == 0)
        {
            ResultText.Text = "No splits configured. Drag the arrows or click on text to add splits.";
            return;
        }

        var widths = new List<int>();
        int prev = 0;
        foreach (int pos in _splitPositions.OrderBy(p => p))
        {
            int w = pos - prev;
            if (w > 0)
                widths.Add(w);
            prev = pos;
        }
        widths.Add(100);

        var sb = new StringBuilder();
        string header = string.Join(" | ", Enumerable.Range(1, widths.Count).Select(i => $"Col {i,2}"));
        string separator = new string('-', header.Length + 10);
        sb.AppendLine($"Columns: {widths.Count}");
        sb.AppendLine($"Widths: {string.Join(", ", widths)}");
        sb.AppendLine(separator);
        sb.AppendLine(header);
        sb.AppendLine(separator);

        for (int i = 0; i < Math.Min(10, _columnData.Count); i++)
        {
            string text = _columnData[i] ?? string.Empty;
            var parts = new List<string>();
            int pos = 0;
            for (int wIdx = 0; wIdx < widths.Count - 1; wIdx++)
            {
                int width = widths[wIdx];
                if (pos < text.Length)
                {
                    parts.Add(text.Substring(pos, Math.Min(width, text.Length - pos)).Trim());
                    pos += width;
                }
                else
                {
                    parts.Add(string.Empty);
                }
            }
            parts.Add(pos < text.Length ? text[pos..].Trim() : string.Empty);

            string resultLine = string.Join(" | ", parts.Select(part => part.PadRight(20)));
            sb.AppendLine($"{i + 1,2}. {resultLine}");
        }

        ResultText.Text = sb.ToString();
        UpdateDetails();
    }

    private void ApplySplit_Click(object sender, RoutedEventArgs e)
    {
        if (_splitPositions.Count == 0)
        {
            System.Windows.MessageBox.Show(
                this,
                "Please add split points by dragging the arrows or clicking on text.",
                "Warning",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
            return;
        }

        try
        {
            var widths = new List<int>();
            int prev = 0;
            foreach (int pos in _splitPositions.OrderBy(p => p))
            {
                int w = pos - prev;
                if (w > 0)
                    widths.Add(w);
                prev = pos;
            }
            widths.Add(100);

            var splitData = new List<List<string>>(_columnData.Count);
            foreach (var raw in _columnData)
            {
                string text = raw ?? string.Empty;
                var parts = new List<string>(widths.Count);
                int pos = 0;
                for (int i = 0; i < widths.Count - 1; i++)
                {
                    int w = widths[i];
                    if (pos < text.Length)
                    {
                        parts.Add(text.Substring(pos, Math.Min(w, text.Length - pos)).Trim());
                        pos += w;
                    }
                    else
                    {
                        parts.Add(string.Empty);
                    }
                }
                parts.Add(pos < text.Length ? text[pos..].Trim() : string.Empty);
                splitData.Add(parts);
            }

            Widths = widths;
            ResultData = splitData;
            DialogResult = true;
            Close();
        }
        catch (Exception exc)
        {
            System.Windows.MessageBox.Show(
                this,
                $"Failed to apply split: {exc.Message}",
                "Error",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
        }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e) => Close();
}
