using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using EflNexus.App.Helpers;
using EflNexus.Core.Reconciliation;
using MediaBrushes = System.Windows.Media.Brushes;
using MediaColor = System.Windows.Media.Color;
using SolidBrush = System.Windows.Media.SolidColorBrush;
using WpfBinding = System.Windows.Data.Binding;

namespace EflNexus.App.Dialogs;

public partial class ConcatenateColumnsDialog : Window
{
    private readonly TabularDataset _df;
    private readonly bool _isDarkMode;
    private readonly List<string> _availableColumns;
    private readonly List<string> _selectedColumns = [];
    private readonly List<DataGridTextColumn> _gridColumns = [];
    private readonly List<string[]> _previewRows = [];

    public TransformConfig? ResultConfig { get; private set; }

    public ConcatenateColumnsDialog(Window? owner, string title, TabularDataset df, bool isDarkMode = false)
    {
        InitializeComponent();
        App.TrySetWindowIcon(this);
        Title = title;
        ImageLoader.SizeAndCenterDialog(this, owner, 0.85, 0.85, 1000, 700);

        _df = df;
        _isDarkMode = isDarkMode;
        _availableColumns = df.Columns.ToList();

        SeparatorCombo.ItemsSource = new[] { "-", " ", "_", ",", ", ", "|", "/", "(none)" };
        SeparatorCombo.Text = "-";

        PopulateDataPreview();
        RefreshLists();
        ApplyTheme();
    }

    private void ApplyTheme()
    {
        var bg = new SolidBrush(_isDarkMode ? MediaColor.FromRgb(0x0B, 0x14, 0x20) : MediaColor.FromRgb(0xFA, 0xF8, 0xF2));
        var panel = new SolidBrush(_isDarkMode ? MediaColor.FromRgb(0x13, 0x23, 0x3A) : MediaColor.FromRgb(0xFF, 0xFF, 0xFF));
        var fg = new SolidBrush(_isDarkMode ? MediaColor.FromRgb(0xEC, 0xEC, 0xEC) : MediaColor.FromRgb(0x0F, 0x17, 0x2A));
        var entryBg = new SolidBrush(_isDarkMode ? MediaColor.FromRgb(0x16, 0x2E, 0x4C) : MediaColor.FromRgb(0xFF, 0xFF, 0xFF));
        var altRow = new SolidBrush(_isDarkMode ? MediaColor.FromRgb(0x0F, 0x1B, 0x2D) : MediaColor.FromRgb(0xF8, 0xFA, 0xFC));
        var headingBg = new SolidBrush(_isDarkMode ? MediaColor.FromRgb(0x16, 0x2E, 0x4C) : MediaColor.FromRgb(0xE2, 0xE8, 0xF0));

        Background = bg;
        InstructionLabel.Foreground = fg;
        DataPreviewGroup.Foreground = fg;
        PickerGroup.Foreground = fg;
        OptionsGroup.Foreground = fg;
        StatusText.Foreground = fg;
        DropOriginalsCheck.Foreground = fg;

        AvailableListBox.Background = entryBg;
        AvailableListBox.Foreground = fg;
        SelectedListBox.Background = entryBg;
        SelectedListBox.Foreground = fg;

        PreviewTextBox.Background = entryBg;
        PreviewTextBox.Foreground = fg;
        NewColumnNameBox.Background = entryBg;
        NewColumnNameBox.Foreground = fg;

        PreviewGrid.Background = panel;
        PreviewGrid.RowBackground = panel;
        PreviewGrid.AlternatingRowBackground = altRow;
        PreviewGrid.Foreground = fg;

        var headerStyle = new Style(typeof(DataGridColumnHeader));
        headerStyle.Setters.Add(new EventSetter(ButtonBase.ClickEvent, new RoutedEventHandler(ColumnHeader_Click)));
        headerStyle.Setters.Add(new Setter(Control.BackgroundProperty, headingBg));
        headerStyle.Setters.Add(new Setter(Control.ForegroundProperty, fg));
        headerStyle.Setters.Add(new Setter(Control.PaddingProperty, new Thickness(6, 4, 6, 4)));
        headerStyle.Setters.Add(new Setter(Control.HorizontalContentAlignmentProperty, System.Windows.HorizontalAlignment.Left));
        headerStyle.Setters.Add(new Setter(Control.CursorProperty, System.Windows.Input.Cursors.Hand));
        PreviewGrid.ColumnHeaderStyle = headerStyle;

        HighlightSelectedHeaders();
    }

    private void PopulateDataPreview()
    {
        PreviewGrid.Columns.Clear();
        _gridColumns.Clear();
        _previewRows.Clear();

        for (int c = 0; c < _availableColumns.Count; c++)
        {
            var colName = _availableColumns[c];
            var col = new DataGridTextColumn
            {
                Header = colName,
                Binding = new WpfBinding($"[{c}]"),
                MinWidth = 60
            };
            PreviewGrid.Columns.Add(col);
            _gridColumns.Add(col);
        }

        int maxRows = Math.Min(200, _df.RowCount);
        for (int r = 0; r < maxRows; r++)
        {
            var src = _df.Rows[r];
            var vals = new string[_availableColumns.Count];
            for (int c = 0; c < _availableColumns.Count; c++)
                vals[c] = c < src.Length ? TabularDataset.CellToString(src[c]) : string.Empty;
            _previewRows.Add(vals);
        }

        PreviewGrid.ItemsSource = _previewRows;
        HighlightSelectedHeaders();
    }

    private void HighlightSelectedHeaders()
    {
        var badgeBg = new SolidBrush(MediaColor.FromRgb(0x25, 0x63, 0xEB));
        var fg = new SolidBrush(_isDarkMode ? MediaColor.FromRgb(0xEC, 0xEC, 0xEC) : MediaColor.FromRgb(0x0F, 0x17, 0x2A));

        for (int i = 0; i < _gridColumns.Count; i++)
        {
            string colName = _availableColumns[i];
            int selIdx = _selectedColumns.IndexOf(colName);
            if (selIdx >= 0)
            {
                var badge = new Border
                {
                    Background = badgeBg,
                    CornerRadius = new CornerRadius(3),
                    Padding = new Thickness(6, 2, 6, 2),
                    Child = new TextBlock
                    {
                        Text = $"🔗 #{selIdx + 1} {colName}",
                        Foreground = MediaBrushes.White,
                        FontWeight = FontWeights.Bold,
                        FontFamily = new System.Windows.Media.FontFamily("Segoe UI"),
                        FontSize = 11
                    }
                };
                _gridColumns[i].Header = badge;
            }
            else
            {
                _gridColumns[i].Header = new TextBlock
                {
                    Text = colName,
                    Foreground = fg,
                    FontFamily = new System.Windows.Media.FontFamily("Segoe UI"),
                    FontSize = 12
                };
            }
        }
    }

    private void ColumnHeader_Click(object sender, RoutedEventArgs e)
    {
        if (sender is DataGridColumnHeader header && header.Column is DataGridTextColumn col)
        {
            int idx = _gridColumns.IndexOf(col);
            if (idx >= 0 && idx < _availableColumns.Count)
                ToggleColumnFromPreview(_availableColumns[idx]);
        }
    }

    private void ToggleColumnFromPreview(string col)
    {
        if (_selectedColumns.Contains(col))
            _selectedColumns.Remove(col);
        else
            _selectedColumns.Add(col);
        RefreshLists();
    }

    private void AvailableListBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (AvailableListBox.SelectedItem is string col)
            ScrollToColumn(col);
    }

    private void SelectedListBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (SelectedListBox.SelectedItem is string col)
            ScrollToColumn(col);
    }

    private void AvailableListBox_DoubleClick(object sender, MouseButtonEventArgs e) => AddSelectedColumns();
    private void SelectedListBox_DoubleClick(object sender, MouseButtonEventArgs e) => RemoveSelectedColumns();

    private void ScrollToColumn(string col)
    {
        int idx = _availableColumns.IndexOf(col);
        if (idx >= 0 && idx < _gridColumns.Count && PreviewGrid.Items.Count > 0)
        {
            try
            {
                PreviewGrid.ScrollIntoView(PreviewGrid.Items[0], _gridColumns[idx]);
            }
            catch { }
        }
    }

    private void AddSelected_Click(object sender, RoutedEventArgs e) => AddSelectedColumns();
    private void RemoveSelected_Click(object sender, RoutedEventArgs e) => RemoveSelectedColumns();
    private void MoveUp_Click(object sender, RoutedEventArgs e) => MoveSelected(-1);
    private void MoveDown_Click(object sender, RoutedEventArgs e) => MoveSelected(1);

    private void AddSelectedColumns()
    {
        foreach (var col in AvailableListBox.SelectedItems.OfType<string>().ToList())
        {
            if (!_selectedColumns.Contains(col))
                _selectedColumns.Add(col);
        }
        RefreshLists();
    }

    private void RemoveSelectedColumns()
    {
        var picks = SelectedListBox.SelectedItems.OfType<string>().ToHashSet(StringComparer.Ordinal);
        _selectedColumns.RemoveAll(c => picks.Contains(c));
        RefreshLists();
    }

    private void MoveSelected(int direction)
    {
        var indices = SelectedListBox.SelectedItems
            .OfType<string>()
            .Select(s => _selectedColumns.IndexOf(s))
            .Where(i => i >= 0)
            .ToList();
        if (indices.Count == 0)
            return;

        indices = direction < 0 ? indices.OrderBy(i => i).ToList() : indices.OrderByDescending(i => i).ToList();
        var reselectNames = indices.Select(i => _selectedColumns[i]).ToHashSet(StringComparer.Ordinal);

        foreach (int idx in indices)
        {
            int newIdx = idx + direction;
            if (newIdx >= 0 && newIdx < _selectedColumns.Count)
                (_selectedColumns[idx], _selectedColumns[newIdx]) = (_selectedColumns[newIdx], _selectedColumns[idx]);
        }

        RefreshLists();
        foreach (var item in SelectedListBox.Items.OfType<string>())
        {
            if (reselectNames.Contains(item))
                SelectedListBox.SelectedItems.Add(item);
        }
    }

    private void RefreshLists()
    {
        SelectedListBox.ItemsSource = null;
        SelectedListBox.ItemsSource = _selectedColumns.ToList();

        AvailableListBox.ItemsSource = null;
        AvailableListBox.ItemsSource = _availableColumns.Where(c => !_selectedColumns.Contains(c)).ToList();

        int count = _selectedColumns.Count;
        StatusText.Text = $"{count} column(s) selected" + (count >= 2 ? string.Empty : " - pick at least two columns to combine");

        HighlightSelectedHeaders();
        PreviewResult();
    }

    private string ResolveSeparator()
    {
        string raw = SeparatorCombo.SelectedItem as string ?? SeparatorCombo.Text ?? "-";
        return raw == "(none)" ? string.Empty : raw;
    }

    private void SeparatorCombo_Changed(object sender, SelectionChangedEventArgs e) => PreviewResult();
    private void NewColumnNameBox_Changed(object sender, TextChangedEventArgs e) => PreviewResult();
    private void RefreshPreview_Click(object sender, RoutedEventArgs e) => PreviewResult();

    private void PreviewResult()
    {
        if (PreviewTextBox is null)
            return;

        if (_selectedColumns.Count < 2)
        {
            PreviewTextBox.Text = "Select at least two columns to see a preview.";
            return;
        }

        string sep = ResolveSeparator();
        string newName = (NewColumnNameBox.Text ?? string.Empty).Trim();
        if (string.IsNullOrEmpty(newName))
            newName = "Concatenated";

        var colIndices = _selectedColumns.Select(c => _df.IndexOfColumn(c)).ToList();
        var sb = new StringBuilder();
        sb.AppendLine(newName);
        sb.AppendLine(new string('-', 40));

        int sampleRows = Math.Min(10, _df.RowCount);
        for (int r = 0; r < sampleRows; r++)
        {
            var row = _df.Rows[r];
            var parts = colIndices.Select(idx => idx >= 0 && idx < row.Length ? TabularDataset.CellToString(row[idx]) : string.Empty);
            sb.AppendLine(string.Join(sep, parts));
        }

        PreviewTextBox.Text = sb.ToString();
        StatusText.Text = $"Previewing '{newName}' from {_selectedColumns.Count} column(s)";
    }

    private void ApplyConcatenate_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedColumns.Count < 2)
        {
            System.Windows.MessageBox.Show(this, "Please select at least two columns to concatenate.", "Warning", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        string newName = (NewColumnNameBox.Text ?? string.Empty).Trim();
        if (string.IsNullOrEmpty(newName))
        {
            System.Windows.MessageBox.Show(this, "Please enter a name for the new column.", "Warning", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        bool dropOriginals = DropOriginalsCheck.IsChecked == true;
        var surviving = _availableColumns
            .Where(c => !(dropOriginals && _selectedColumns.Contains(c)))
            .ToHashSet(StringComparer.Ordinal);

        if (surviving.Contains(newName) && !_selectedColumns.Contains(newName))
        {
            System.Windows.MessageBox.Show(
                this,
                $"A column named '{newName}' already exists. Please choose a different name.",
                "Error",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
            return;
        }

        ResultConfig = new TransformConfig
        {
            Type = "concatenate",
            Columns = _selectedColumns.ToList(),
            Separator = ResolveSeparator(),
            NewColumnName = newName,
            DropOriginals = dropOriginals
        };
        DialogResult = true;
        Close();
    }

    private void Cancel_Click(object sender, RoutedEventArgs e) => Close();
}
