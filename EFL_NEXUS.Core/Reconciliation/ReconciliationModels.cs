using System.Globalization;
using System.Text.Json.Serialization;

namespace EflNexus.Core.Reconciliation;

public sealed class TabularDataset
{
    public List<string> Columns { get; }
    public List<object?[]> Rows { get; }

    public TabularDataset(List<string> columns, List<object?[]> rows)
    {
        Columns = columns;
        Rows = rows;
    }

    public int RowCount => Rows.Count;
    public int ColumnCount => Columns.Count;
    public bool IsEmpty => Rows.Count == 0 || Columns.Count == 0;

    public int IndexOfColumn(string columnName)
        => Columns.FindIndex(c => string.Equals(c, columnName, StringComparison.Ordinal));

    public TabularDataset Clone()
    {
        var cols = new List<string>(Columns);
        var rows = new List<object?[]>(Rows.Count);
        foreach (var r in Rows)
        {
            var copy = new object?[cols.Count];
            Array.Copy(r, copy, Math.Min(r.Length, cols.Count));
            rows.Add(copy);
        }
        return new TabularDataset(cols, rows);
    }

    public static string CellToString(object? value)
    {
        if (value is null || value == DBNull.Value)
            return string.Empty;
        return value switch
        {
            double d => double.IsNaN(d) || double.IsInfinity(d) ? string.Empty
                : (Math.Abs(d - Math.Round(d)) < 1e-12 && Math.Abs(d) <= long.MaxValue ? ((long)Math.Round(d)).ToString(CultureInfo.InvariantCulture) : d.ToString(CultureInfo.InvariantCulture)),
            float f => float.IsNaN(f) || float.IsInfinity(f) ? string.Empty
                : (Math.Abs(f - Math.Round(f)) < 1e-6f ? ((long)Math.Round(f)).ToString(CultureInfo.InvariantCulture) : f.ToString(CultureInfo.InvariantCulture)),
            decimal m => m == Math.Truncate(m) ? decimal.Truncate(m).ToString(CultureInfo.InvariantCulture) : m.ToString(CultureInfo.InvariantCulture),
            DateTime dt => dt.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture),
            _ => value.ToString() ?? string.Empty
        };
    }
}

public sealed class TransformConfig
{
    [JsonPropertyName("type")]
    public string Type { get; set; } = "split"; // "split" | "concatenate"

    [JsonPropertyName("column")]
    public string Column { get; set; } = "";

    [JsonPropertyName("widths")]
    public List<int> Widths { get; set; } = [];

    [JsonPropertyName("columns")]
    public List<string> Columns { get; set; } = [];

    [JsonPropertyName("separator")]
    public string Separator { get; set; } = "-";

    [JsonPropertyName("new_column_name")]
    public string NewColumnName { get; set; } = "Concatenated";

    [JsonPropertyName("drop_originals")]
    public bool DropOriginals { get; set; }
}

public sealed class ReconciliationSettingsData
{
    [JsonPropertyName("remember_settings")]
    public bool RememberSettings { get; set; }

    [JsonPropertyName("dark_mode")]
    public bool DarkMode { get; set; }

    [JsonPropertyName("window_geometry")]
    public string? WindowGeometry { get; set; }

    [JsonPropertyName("window_state")]
    public string? WindowState { get; set; }

    [JsonPropertyName("output_folder")]
    public string? OutputFolder { get; set; }

    [JsonPropertyName("archive_folder")]
    public string? ArchiveFolder { get; set; }

    [JsonPropertyName("archive_after_processing")]
    public bool? ArchiveAfterProcessing { get; set; }

    [JsonPropertyName("auto_open_file")]
    public bool? AutoOpenFile { get; set; }

    [JsonPropertyName("verbose_logging")]
    public bool? VerboseLogging { get; set; }
}

public sealed class VarianceRow
{
    public string LoadId { get; set; } = "";
    public double PlanQty { get; set; }
    public double LoadedQty { get; set; }
    public double Variance { get; set; }
    public string Status { get; set; } = "";
    public string Comments { get; set; } = "";
}

public sealed class ReconciliationRequest
{
    public string HistoryFilePath { get; set; } = "";
    public string PlanFilePath { get; set; } = "";
    public string HistoryLoadIdCol { get; set; } = "";
    public string HistoryQtyCol { get; set; } = "";
    public string PlanLoadIdCol { get; set; } = "";
    public string PlanQtyCol { get; set; } = "";
    public bool HistorySplitEnabled { get; set; }
    public bool PlanSplitEnabled { get; set; }
    public List<TransformConfig> HistoryTransforms { get; set; } = [];
    public List<TransformConfig> PlanTransforms { get; set; } = [];
    public bool PlanDivideEnabled { get; set; }
    public double PlanDivideValue { get; set; } = 1.0;
    public string OutputFolder { get; set; } = "";
    public string ArchiveFolder { get; set; } = @"C:\Reconciliation\Archive";
    public bool ArchiveFiles { get; set; } = true;
    public string QueuedJobId { get; set; } = "";
    public string Client { get; set; } = "";
    public string Gatepass { get; set; } = "";
}

public sealed class ReconciliationResult
{
    public string OutputFilePath { get; set; } = "";
    public string SelectedJobId { get; set; } = "";
    public int PlanUniqueCount { get; set; }
    public int HistoryUniqueCount { get; set; }
    public int MatchCount { get; set; }
    public int VarianceCount { get; set; }
    public int MissingCount { get; set; }
    public int ExtraCount { get; set; }
    public double MatchRate { get; set; }
    public string SummaryText { get; set; } = "";
    public bool FormattingSucceeded { get; set; }
    public List<string> UpdatedHistoryColumns { get; set; } = [];
    public List<string> UpdatedPlanColumns { get; set; } = [];
}
