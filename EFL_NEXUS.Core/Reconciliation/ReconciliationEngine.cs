using System.Globalization;
using System.IO;
using System.Text.RegularExpressions;
using ClosedXML.Excel;
using EflNexus.Core.Infrastructure;

namespace EflNexus.Core.Reconciliation;

/// <summary>
/// Headless core engine for Load Reconciliation (column detection, splits, concatenations,
/// variance calculation, Styled Excel export, queue completion, archiving). Matches reconciliation_tool.py 1:1.
/// </summary>
public static class ReconciliationEngine
{
    public static bool IsOutJobId(string? jobId)
    {
        if (string.IsNullOrWhiteSpace(jobId))
            return false;
        var trimmed = jobId.Trim();
        return trimmed.StartsWith("OUT_", StringComparison.OrdinalIgnoreCase)
            || trimmed.StartsWith("OUT-", StringComparison.OrdinalIgnoreCase)
            || trimmed.StartsWith("OUT", StringComparison.OrdinalIgnoreCase);
    }

    public static string FindOrderNumberColumn(IReadOnlyList<string> columns)
    {
        string[] targetOrderPatterns =
        [
            "order number",
            "order no",
            "order #",
            "order id",
            "ordernumber",
            "orderno",
            "order num",
            "order"
        ];

        // Priority 1: Exact normalized match
        foreach (var pattern in targetOrderPatterns)
        {
            var patNorm = Regex.Replace(pattern.ToLowerInvariant(), @"[^a-z0-9]", "");
            foreach (var col in columns)
            {
                var colNorm = Regex.Replace(col.ToLowerInvariant(), @"[^a-z0-9]", "");
                if (colNorm == patNorm)
                    return col;
            }
        }

        // Priority 2: Substring contains order + (number / no / # / id / num) excluding quantity
        foreach (var col in columns)
        {
            var colLower = col.ToLowerInvariant().Trim();
            if (colLower.Contains("order") &&
                (colLower.Contains("number") || colLower.Contains("no") || colLower.Contains('#') || colLower.Contains("id") || colLower.Contains("num")) &&
                !colLower.Contains("qty") && !colLower.Contains("quantity"))
            {
                return col;
            }
        }

        // Priority 3: Substring contains order excluding quantity
        foreach (var col in columns)
        {
            var colLower = col.ToLowerInvariant().Trim();
            if (colLower.Contains("order") && !colLower.Contains("qty") && !colLower.Contains("quantity"))
            {
                return col;
            }
        }

        return string.Empty;
    }

    public static string FindLoadIdColumn(IReadOnlyList<string> columns)
    {
        foreach (var col in columns)
        {
            var colLower = col.ToLowerInvariant().Trim();
            if (colLower.Contains("load") &&
                (colLower.Contains("id") || colLower.Contains('#') || colLower.Contains("number") || colLower.Contains("no")))
            {
                return col;
            }
        }

        foreach (var col in columns)
        {
            if (col.ToLowerInvariant().Trim().Contains("load"))
            {
                return col;
            }
        }

        foreach (var col in columns)
        {
            var colLower = col.ToLowerInvariant().Trim();
            if (colLower.Contains("id") || colLower.Contains("key"))
            {
                return col;
            }
        }

        return string.Empty;
    }

    public static (string LoadIdCol, string QtyCol) AutoSelectColumns(
        IReadOnlyList<string> columns,
        bool isOutJob = false)
    {
        string loadIdCol = "";
        string qtyCol = "";

        // 1. Primary Key / Identifier auto-selection:
        // For OUT jobs, prioritize 'Order Number' instead of 'Load Id'
        if (isOutJob)
        {
            loadIdCol = FindOrderNumberColumn(columns);
        }

        // Fall back to standard Load ID auto-selection if not an OUT job or if Order column was not found
        if (string.IsNullOrEmpty(loadIdCol))
        {
            loadIdCol = FindLoadIdColumn(columns);
        }

        if (string.IsNullOrEmpty(loadIdCol) && columns.Count > 0)
            loadIdCol = columns[0];

        // 2. Quantity column auto-selection
        string[] targetQtyPatterns =
        [
            "quantity",
            "actual qty",
            "pln qty",
            "loaded qty",
            "planned qty"
        ];

        // Priority 1: Exact normalized match
        foreach (var pattern in targetQtyPatterns)
        {
            var patNorm = Regex.Replace(pattern.ToLowerInvariant(), @"[^a-z0-9]", "");
            foreach (var col in columns)
            {
                var colNorm = Regex.Replace(col.ToLowerInvariant(), @"[^a-z0-9]", "");
                if (colNorm == patNorm)
                {
                    qtyCol = col;
                    break;
                }
            }
            if (!string.IsNullOrEmpty(qtyCol)) break;
        }

        // Priority 2: Substring normalized match
        if (string.IsNullOrEmpty(qtyCol))
        {
            foreach (var pattern in targetQtyPatterns)
            {
                var patNorm = Regex.Replace(pattern.ToLowerInvariant(), @"[^a-z0-9]", "");
                foreach (var col in columns)
                {
                    var colNorm = Regex.Replace(col.ToLowerInvariant(), @"[^a-z0-9]", "");
                    if (colNorm.Contains(patNorm, StringComparison.Ordinal))
                    {
                        qtyCol = col;
                        break;
                    }
                }
                if (!string.IsNullOrEmpty(qtyCol)) break;
            }
        }

        // Priority 3: General heuristic keywords
        if (string.IsNullOrEmpty(qtyCol))
        {
            foreach (var col in columns)
            {
                var colLower = col.ToLowerInvariant().Trim();
                if (colLower.Contains("qty") || colLower.Contains("quantity") || colLower.Contains("pick") || colLower.Contains("actual"))
                {
                    qtyCol = col;
                    break;
                }
            }
        }

        // Priority 4: Fallback to last column
        if (string.IsNullOrEmpty(qtyCol) && columns.Count > 0)
            qtyCol = columns[^1];

        return (loadIdCol, qtyCol);
    }

    public static (string LoadIdCol, string QtyCol) AutoSelectColumns(
        IReadOnlyList<string> columns,
        string? jobId)
        => AutoSelectColumns(columns, IsOutJobId(jobId));

    public static (string LoadIdCol, string QtyCol) AutoSelectColumns(IReadOnlyList<string> columns)
        => AutoSelectColumns(columns, isOutJob: false);

    public static TabularDataset ApplyTextToColumns(
        TabularDataset df,
        string splitColumn,
        IReadOnlyList<int> widths,
        string friendlyName = "Data",
        Action<string, string>? log = null)
    {
        if (widths.Count == 0 || string.IsNullOrWhiteSpace(splitColumn))
            return df;

        int srcIdx = df.IndexOfColumn(splitColumn);
        if (srcIdx < 0)
            throw new InvalidOperationException($"Missing column '{splitColumn}' for text-to-columns.");

        log?.Invoke($"🔄 Applying text-to-columns to {friendlyName}...", "INFO");

        var newColNames = new List<string>(widths.Count);
        for (int i = 0; i < widths.Count; i++)
        {
            var cname = $"{splitColumn}_part_{i + 1}";
            newColNames.Add(cname);
            log?.Invoke($"   Created column: {cname}", "DEBUG");
        }

        var remainingIndices = new List<int>();
        var remainingNames = new List<string>();
        for (int c = 0; c < df.ColumnCount; c++)
        {
            if (c != srcIdx)
            {
                remainingIndices.Add(c);
                remainingNames.Add(df.Columns[c]);
            }
        }

        // Place new split columns at the very beginning
        var finalColumns = new List<string>(newColNames.Count + remainingNames.Count);
        finalColumns.AddRange(newColNames);
        finalColumns.AddRange(remainingNames);

        var finalRows = new List<object?[]>(df.RowCount);
        for (int r = 0; r < df.RowCount; r++)
        {
            var srcRow = df.Rows[r];
            var text = TabularDataset.CellToString(srcRow[srcIdx]);
            var destRow = new object?[finalColumns.Count];

            int pos = 0;
            for (int i = 0; i < widths.Count; i++)
            {
                string part;
                if (i < widths.Count - 1)
                {
                    int w = widths[i];
                    part = pos < text.Length
                        ? text.Substring(pos, Math.Min(w, text.Length - pos)).Trim()
                        : string.Empty;
                    pos += w;
                }
                else
                {
                    part = pos < text.Length ? text[pos..].Trim() : string.Empty;
                }
                destRow[i] = part;
            }

            for (int j = 0; j < remainingIndices.Count; j++)
                destRow[widths.Count + j] = srcRow[remainingIndices[j]];

            finalRows.Add(destRow);
        }

        log?.Invoke($"✅ Text-to-columns applied: {widths.Count} new columns placed at the top/beginning", "SUCCESS");
        return new TabularDataset(finalColumns, finalRows);
    }

    public static TabularDataset ApplyColumnConcatenation(
        TabularDataset df,
        IReadOnlyList<string> columns,
        string separator,
        string newColumnName,
        bool dropOriginals,
        string friendlyName = "Data",
        Action<string, string>? log = null)
    {
        log?.Invoke($"🔗 Concatenating {friendlyName} columns into '{newColumnName}': {string.Join(", ", columns)}", "INFO");

        var colIndices = new List<int>(columns.Count);
        foreach (var col in columns)
        {
            int idx = df.IndexOfColumn(col);
            if (idx < 0)
                throw new InvalidOperationException($"Missing source column '{col}' for concatenation.");
            colIndices.Add(idx);
        }

        var dropSet = dropOriginals
            ? new HashSet<string>(columns.Where(c => c != newColumnName), StringComparer.Ordinal)
            : new HashSet<string>(StringComparer.Ordinal);

        if (dropOriginals && dropSet.Count > 0)
            log?.Invoke($"   Removed original columns: {string.Join(", ", dropSet)}", "DEBUG");

        var remainingIndices = new List<int>();
        var finalColumns = new List<string> { newColumnName };
        for (int c = 0; c < df.ColumnCount; c++)
        {
            var col = df.Columns[c];
            if (col == newColumnName || dropSet.Contains(col))
                continue;
            remainingIndices.Add(c);
            finalColumns.Add(col);
        }

        var finalRows = new List<object?[]>(df.RowCount);
        for (int r = 0; r < df.RowCount; r++)
        {
            var srcRow = df.Rows[r];
            var parts = new string[colIndices.Count];
            for (int i = 0; i < colIndices.Count; i++)
                parts[i] = TabularDataset.CellToString(srcRow[colIndices[i]]);

            var destRow = new object?[finalColumns.Count];
            destRow[0] = string.Join(separator, parts);
            for (int j = 0; j < remainingIndices.Count; j++)
                destRow[1 + j] = srcRow[remainingIndices[j]];

            finalRows.Add(destRow);
        }

        log?.Invoke($"✅ Concatenation applied: '{newColumnName}' placed at the top/beginning", "SUCCESS");
        return new TabularDataset(finalColumns, finalRows);
    }

    public static TabularDataset ApplyColumnTransformations(
        TabularDataset df,
        IReadOnlyList<TransformConfig> configs,
        bool splitEnabled,
        string friendlyName,
        Action<string, string>? log = null)
    {
        foreach (var config in configs)
        {
            if (config.Type == "split")
            {
                if (!splitEnabled)
                    continue;

                if (df.IndexOfColumn(config.Column) < 0)
                {
                    throw new InvalidOperationException(
                        $"Cannot reapply {friendlyName} split: missing source column(s): {config.Column}. Check the column operations and ensure Text-to-Columns is enabled for configured splits.");
                }
                df = ApplyTextToColumns(df, config.Column, config.Widths, friendlyName, log);
            }
            else
            {
                var missing = config.Columns.Where(c => df.IndexOfColumn(c) < 0).ToList();
                if (missing.Count > 0)
                {
                    throw new InvalidOperationException(
                        $"Cannot reapply {friendlyName} concatenate: missing source column(s): {string.Join(", ", missing)}. Check the column operations and ensure Text-to-Columns is enabled for configured splits.");
                }
                df = ApplyColumnConcatenation(
                    df, config.Columns, config.Separator, config.NewColumnName, config.DropOriginals, friendlyName, log);
            }
        }
        return df;
    }

    public static string DescribeColumnSplits(IReadOnlyList<TransformConfig> configs)
        => string.Join("; ", configs
            .Where(c => c.Type == "split")
            .Select(c => $"Column: {c.Column}, Widths: [{string.Join(", ", c.Widths)}]"));

    public static ReconciliationResult ExecuteReconciliation(
        ReconciliationRequest request,
        Action<double, string>? onProgress = null,
        Action<string, string>? onLog = null)
    {
        string selectedJobId = (request.QueuedJobId ?? "").Trim();
        bool isOutJob = IsOutJobId(selectedJobId);
        string historyLoadIdCol = request.HistoryLoadIdCol.Trim();
        string historyQtyCol = request.HistoryQtyCol.Trim();
        string planLoadIdCol = request.PlanLoadIdCol.Trim();
        string planQtyCol = request.PlanQtyCol.Trim();

        onProgress?.Invoke(5, "📖 Reading files...");
        onLog?.Invoke("📖 Reading input files...", "INFO");

        var historyDf = ExcelReaderHelper.ReadExcel(request.HistoryFilePath);
        var planDf = ExcelReaderHelper.ReadExcel(request.PlanFilePath);

        onLog?.Invoke($"📊 History: {historyDf.RowCount} rows, {historyDf.ColumnCount} columns", "INFO");
        onLog?.Invoke($"📊 Plan: {planDf.RowCount} rows, {planDf.ColumnCount} columns", "INFO");

        historyDf = ApplyColumnTransformations(historyDf, request.HistoryTransforms, request.HistorySplitEnabled, "History", onLog);
        planDf = ApplyColumnTransformations(planDf, request.PlanTransforms, request.PlanSplitEnabled, "Plan", onLog);

        // Trim header names just like history_df.columns = history_df.columns.str.strip()
        for (int c = 0; c < historyDf.ColumnCount; c++)
            historyDf.Columns[c] = historyDf.Columns[c].Trim();
        for (int c = 0; c < planDf.ColumnCount; c++)
            planDf.Columns[c] = planDf.Columns[c].Trim();

        var updatedHistoryCols = historyDf.Columns.ToList();
        var updatedPlanCols = planDf.Columns.ToList();

        if (string.IsNullOrEmpty(historyLoadIdCol))
            (historyLoadIdCol, _) = AutoSelectColumns(historyDf.Columns, isOutJob);
        if (string.IsNullOrEmpty(planLoadIdCol))
            (planLoadIdCol, _) = AutoSelectColumns(planDf.Columns, isOutJob);
        if (string.IsNullOrEmpty(historyQtyCol))
            (_, historyQtyCol) = AutoSelectColumns(historyDf.Columns, isOutJob);
        if (string.IsNullOrEmpty(planQtyCol))
            (_, planQtyCol) = AutoSelectColumns(planDf.Columns, isOutJob);

        bool isOrderReconciliation = isOutJob ||
            (historyLoadIdCol.Contains("order", StringComparison.OrdinalIgnoreCase) &&
             planLoadIdCol.Contains("order", StringComparison.OrdinalIgnoreCase));
        string pkHeader = isOrderReconciliation ? "Order Number" : "Load ID";
        string entityType = isOrderReconciliation ? "Orders" : "Loads";
        string entityLabel = isOrderReconciliation ? "Order" : "Load";

        var missingHistory = new[] { historyLoadIdCol, historyQtyCol }.Where(c => historyDf.IndexOfColumn(c) < 0).ToList();
        var missingPlan = new[] { planLoadIdCol, planQtyCol }.Where(c => planDf.IndexOfColumn(c) < 0).ToList();

        if (missingHistory.Count > 0 || missingPlan.Count > 0)
        {
            var detail = new List<string>();
            if (missingHistory.Count > 0)
                detail.Add($"History file is missing: {string.Join(", ", missingHistory)}");
            if (missingPlan.Count > 0)
                detail.Add($"Plan file is missing: {string.Join(", ", missingPlan)}");

            throw new InvalidOperationException(
                $"The selected {pkHeader}/Quantity column(s) could not be found in the file.\n\n" +
                string.Join("\n", detail) +
                $"\n\nIf you used Concatenate Columns or Text-to-Columns, please re-check that " +
                $"configuration and re-select the {pkHeader} / Quantity columns.");
        }

        onProgress?.Invoke(20, "🔄 Processing data...");
        onLog?.Invoke($"📌 History - {pkHeader}: '{historyLoadIdCol}', Quantity: '{historyQtyCol}'", "INFO");
        onLog?.Invoke($"📌 Plan - {pkHeader}: '{planLoadIdCol}', Quantity: '{planQtyCol}'", "INFO");
        onLog?.Invoke($"🔄 Converting {pkHeader} columns to string type...", "INFO");

        int hIdIdx = historyDf.IndexOfColumn(historyLoadIdCol);
        int hQtyIdx = historyDf.IndexOfColumn(historyQtyCol);
        int pIdIdx = planDf.IndexOfColumn(planLoadIdCol);
        int pQtyIdx = planDf.IndexOfColumn(planQtyCol);

        double? divideVal = request.PlanDivideEnabled ? request.PlanDivideValue : null;
        if (divideVal.HasValue)
            onLog?.Invoke($"➗ Dividing Plan Qty ('{planQtyCol}') by {divideVal.Value}", "INFO");

        onLog?.Invoke($"✅ {pkHeader} columns converted to string type", "INFO");
        onProgress?.Invoke(30, "📊 Cleaning and grouping data...");

        // Normalize Load IDs + coerce numeric Qty on historyDf & planDf and group by Load ID
        var historyGrouped = GroupByLoadId(historyDf, hIdIdx, hQtyIdx, divisor: null);
        var planGrouped = GroupByLoadId(planDf, pIdIdx, pQtyIdx, divisor: divideVal);

        onLog?.Invoke($"📊 Unique {entityType} in Plan: {planGrouped.Count}", "INFO");
        onLog?.Invoke($"📊 Unique {entityType} in History: {historyGrouped.Count}", "INFO");
        onProgress?.Invoke(50, "🔍 Finding variances...");

        // Merge (Plan left join History + History-only rows)
        var resultRows = new List<VarianceRow>(planGrouped.Count + historyGrouped.Count);
        var planIds = new HashSet<string>(StringComparer.Ordinal);

        foreach (var (loadId, planQty) in planGrouped)
        {
            planIds.Add(loadId);
            historyGrouped.TryGetValue(loadId, out double loadedQty);
            double variance = planQty - loadedQty;
            string status = ComputeStatus(planQty, loadedQty, variance);
            resultRows.Add(new VarianceRow
            {
                LoadId = loadId,
                PlanQty = planQty,
                LoadedQty = loadedQty,
                Variance = variance,
                Status = status,
                Comments = ComputeComments(status, variance, entityLabel)
            });
        }

        int extraCountOnly = 0;
        foreach (var (loadId, loadedQty) in historyGrouped)
        {
            if (planIds.Contains(loadId))
                continue;

            extraCountOnly++;
            double variance = -loadedQty;
            string status = ComputeStatus(0, loadedQty, variance);
            resultRows.Add(new VarianceRow
            {
                LoadId = loadId,
                PlanQty = 0,
                LoadedQty = loadedQty,
                Variance = variance,
                Status = status,
                Comments = ComputeComments(status, variance, entityLabel)
            });
        }

        if (extraCountOnly > 0)
            onLog?.Invoke($"⚠️ Found {extraCountOnly} extra {entityType.ToLowerInvariant()} in History", "WARNING");

        // Sort: numeric if ALL Load IDs parse cleanly as numbers, else lexicographic string
        bool allNumeric = resultRows.All(r => double.TryParse(r.LoadId, NumberStyles.Any, CultureInfo.InvariantCulture, out _));
        if (allNumeric)
        {
            resultRows.Sort((a, b) =>
            {
                double da = double.Parse(a.LoadId, CultureInfo.InvariantCulture);
                double db = double.Parse(b.LoadId, CultureInfo.InvariantCulture);
                return da.CompareTo(db);
            });
        }
        else
        {
            resultRows.Sort((a, b) => string.CompareOrdinal(a.LoadId, b.LoadId));
        }

        onProgress?.Invoke(70, "💾 Saving results...");

        string outputPath = request.OutputFolder;
        if (!string.IsNullOrEmpty(selectedJobId))
            outputPath = ReconciliationQueue.GetReconciliationOutputFolder(outputPath, selectedJobId);

        if (!Directory.Exists(outputPath))
        {
            Directory.CreateDirectory(outputPath);
            onLog?.Invoke($"📁 Created output folder: {outputPath}", "INFO");
        }

        string timestamp = DateTime.Now.ToString("yyyy-MM-dd_HHmmss");
        var nameParts = new[] { selectedJobId, request.Client, request.Gatepass }
            .Select(p => SanitizeFileNamePart(p ?? ""))
            .Where(p => p.Length > 0)
            .ToList();
        string baseName = nameParts.Count > 0 ? string.Join("_", nameParts) : "Reconciliations";
        string outputFile = Path.Combine(outputPath, $"{baseName}_{timestamp}.xlsx");

        int matchCount = resultRows.Count(r => r.Status == "MATCH");
        int varianceCount = resultRows.Count(r => r.Status.Contains("VARIANCE", StringComparison.OrdinalIgnoreCase));
        int missingCount = resultRows.Count(r => r.Status == "MISSING IN HISTORY");
        int extraCount = resultRows.Count(r => r.Status == "EXTRA IN HISTORY");
        double matchRate = planGrouped.Count > 0 ? Math.Round(matchCount / (double)planGrouped.Count * 100.0, 2) : 0.0;

        var summaryMetrics = new List<(string Metric, object Value)>
        {
            ($"Total {entityType} in Plan (unique)", planGrouped.Count),
            ($"Total {entityType} in History (unique)", historyGrouped.Count),
            ("Exact Matches", matchCount),
            ("Variances Found", varianceCount),
            ("Missing in History", missingCount),
            ("Extra in History", extraCount),
            ("Match Rate", $"{matchRate}%"),
            ("Processing Date", DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss")),
            ($"History {pkHeader} Column", historyLoadIdCol),
            ("History Quantity Column", historyQtyCol),
            ($"Plan {pkHeader} Column", planLoadIdCol),
            ("Plan Quantity Column", planQtyCol)
        };

        if (request.HistorySplitEnabled)
            summaryMetrics.Add(("History Text-to-Columns", DescribeColumnSplits(request.HistoryTransforms)));
        if (request.PlanSplitEnabled)
            summaryMetrics.Add(("Plan Text-to-Columns", DescribeColumnSplits(request.PlanTransforms)));
        if (divideVal.HasValue)
            summaryMetrics.Add(("Plan Qty Divided By", divideVal.Value));

        onProgress?.Invoke(85, "🎨 Applying formatting...");
        bool formattingSucceeded = WriteFormattedWorkbook(
            outputFile, resultRows, historyDf, planDf, summaryMetrics, pkHeader, onLog, isOutJob);

        onLog?.Invoke($"💾 Results saved to: {Path.GetFileName(outputFile)}", "SUCCESS");

        if (!string.IsNullOrEmpty(selectedJobId) && formattingSucceeded)
        {
            if (ReconciliationQueue.CompleteJob(selectedJobId))
                onLog?.Invoke($"Completed queued Job ID: {selectedJobId}", "SUCCESS");
        }

        onProgress?.Invoke(95, "📂 Archiving files...");
        if (request.ArchiveFiles && !string.IsNullOrWhiteSpace(request.ArchiveFolder))
        {
            if (!Directory.Exists(request.ArchiveFolder))
            {
                Directory.CreateDirectory(request.ArchiveFolder);
                onLog?.Invoke($"📁 Created archive folder: {request.ArchiveFolder}", "INFO");
            }
            var dateStr = DateTime.Now.ToString("yyyy-MM-dd");
            var archiveDatePath = Path.Combine(request.ArchiveFolder, dateStr);
            Directory.CreateDirectory(archiveDatePath);

            var histName = Path.GetFileName(request.HistoryFilePath);
            var planName = Path.GetFileName(request.PlanFilePath);
            File.Copy(request.HistoryFilePath, Path.Combine(archiveDatePath, $"{timestamp}_{histName}"), overwrite: true);
            File.Copy(request.PlanFilePath, Path.Combine(archiveDatePath, $"{timestamp}_{planName}"), overwrite: true);
            onLog?.Invoke($"📦 Archived files to: {archiveDatePath}", "INFO");
        }

        onProgress?.Invoke(100, "✅ Done!");

        var summary =
            $"✅ Reconciliation Complete!\n\n" +
            $"📁 File saved: {outputFile}\n\n" +
            $"📊 SUMMARY:\n" +
            $"  • Unique {entityType} in Plan: {planGrouped.Count}\n" +
            $"  • Unique {entityType} in History: {historyGrouped.Count}\n" +
            $"  • ✅ Exact Matches: {matchCount}\n" +
            $"  • ⚠️ Variances Found: {varianceCount}\n" +
            $"  • ❌ Missing in History: {missingCount}\n" +
            $"  • ➕ Extra in History: {extraCount}\n" +
            $"  • 🎯 Match Rate: {matchRate}%\n\n" +
            $"📌 Column Mapping:\n" +
            $"  • History {pkHeader}: '{historyLoadIdCol}'\n" +
            $"  • History Quantity: '{historyQtyCol}'\n" +
            $"  • Plan {pkHeader}: '{planLoadIdCol}'\n" +
            $"  • Plan Quantity: '{planQtyCol}'";

        if (request.HistorySplitEnabled)
            summary += $"\n  • History Text-to-Columns: {DescribeColumnSplits(request.HistoryTransforms)}";
        if (request.PlanSplitEnabled)
            summary += $"\n  • Plan Text-to-Columns: {DescribeColumnSplits(request.PlanTransforms)}";
        if (divideVal.HasValue)
            summary += $"\n  • Plan Qty divided by: {divideVal.Value}";

        onLog?.Invoke($"✅ Reconciliation complete! Match rate: {matchRate}%", "SUCCESS");

        return new ReconciliationResult
        {
            OutputFilePath = outputFile,
            SelectedJobId = selectedJobId,
            PlanUniqueCount = planGrouped.Count,
            HistoryUniqueCount = historyGrouped.Count,
            MatchCount = matchCount,
            VarianceCount = varianceCount,
            MissingCount = missingCount,
            ExtraCount = extraCount,
            MatchRate = matchRate,
            SummaryText = summary,
            FormattingSucceeded = formattingSucceeded,
            UpdatedHistoryColumns = updatedHistoryCols,
            UpdatedPlanColumns = updatedPlanCols
        };
    }

    private static Dictionary<string, double> GroupByLoadId(TabularDataset df, int idIdx, int qtyIdx, double? divisor)
    {
        var grouped = new Dictionary<string, double>(StringComparer.Ordinal);
        for (int r = 0; r < df.RowCount; r++)
        {
            var row = df.Rows[r];
            var rawId = TabularDataset.CellToString(row[idIdx]).Trim();
            if (rawId is "nan" or "None")
                rawId = string.Empty;

            // Persist cleaned Load ID string onto row so Loading_History_Original/Load_Plan_Original match pandas output
            row[idIdx] = rawId;

            double qty = CoerceNumeric(row[qtyIdx]);
            if (divisor.HasValue && divisor.Value != 0)
                qty /= divisor.Value;

            row[qtyIdx] = qty;

            grouped.TryGetValue(rawId, out double current);
            grouped[rawId] = current + qty;
        }
        return grouped;
    }

    private static double CoerceNumeric(object? val)
    {
        if (val is null) return 0.0;
        return val switch
        {
            double d => double.IsNaN(d) || double.IsInfinity(d) ? 0.0 : d,
            float f => float.IsNaN(f) || float.IsInfinity(f) ? 0.0 : f,
            decimal m => (double)m,
            long l => l,
            int i => i,
            short s => s,
            _ => double.TryParse(val.ToString()?.Trim(), NumberStyles.Any, CultureInfo.InvariantCulture, out var parsed)
                ? parsed
                : 0.0
        };
    }

    public static string ComputeStatus(double planQty, double loadedQty, double variance)
    {
        if (planQty == 0 && loadedQty > 0)
            return "EXTRA IN HISTORY";
        if (planQty > 0 && loadedQty == 0)
            return "MISSING IN HISTORY";
        if (Math.Abs(variance) < 0.01)
            return "MATCH";
        if (Math.Abs(variance) <= 100)
            return "MINOR VARIANCE";
        if (Math.Abs(variance) <= 1000)
            return "MODERATE VARIANCE";
        return "MAJOR VARIANCE";
    }

    private static string SanitizeFileNamePart(string value)
    {
        var invalid = Path.GetInvalidFileNameChars();
        var cleaned = new string(value.Trim().Select(ch => invalid.Contains(ch) ? '-' : ch).ToArray());
        return cleaned.Trim(' ', '.');
    }

    public static string ComputeComments(string status, double variance, string entityLabel = "Load") => status switch
    {
        "MATCH" => "Exact match ✅",
        "EXTRA IN HISTORY" => $"{entityLabel} in History but not in Plan (variance: {variance:F2}) ⚠️",
        "MISSING IN HISTORY" => $"{entityLabel} in Plan but not in History (variance: {variance:F2}) ⚠️",
        "MINOR VARIANCE" => $"Minor variance - check quantities (variance: {variance:F2}) 🔶",
        "MODERATE VARIANCE" => $"Moderate variance - investigate (variance: {variance:F2}) 🟠",
        "MAJOR VARIANCE" => $"LARGE VARIANCE - URGENT! (variance: {variance:F2}) 🔴",
        _ => status
    };

    private static bool WriteFormattedWorkbook(
        string outputFile,
        List<VarianceRow> varianceRows,
        TabularDataset historyDf,
        TabularDataset planDf,
        List<(string Metric, object Value)> summaryMetrics,
        string pkHeader,
        Action<string, string>? log,
        bool isOutJob = false)
    {
        try
        {
            log?.Invoke("🎨 Applying Excel formatting...", "INFO");
            using var wb = new XLWorkbook();

            var headerBlue = XLColor.FromHtml("#0066CC");
            var whiteColor = XLColor.White;
            var blackColor = XLColor.Black;

            var statusStyles = new Dictionary<string, (XLColor Fill, XLColor Font)>(StringComparer.Ordinal)
            {
                ["MATCH"] = (XLColor.FromHtml("#00B050"), whiteColor),
                ["MINOR VARIANCE"] = (XLColor.FromHtml("#FFFF00"), blackColor),
                ["MODERATE VARIANCE"] = (XLColor.FromHtml("#FFC000"), blackColor),
                ["MAJOR VARIANCE"] = (XLColor.FromHtml("#FF0000"), whiteColor),
                ["MISSING IN HISTORY"] = (XLColor.FromHtml("#0070C0"), whiteColor),
                ["EXTRA IN HISTORY"] = (XLColor.FromHtml("#7030A0"), whiteColor)
            };

            // 1. Sheet: variance
            var wsVar = wb.Worksheets.Add("variance");
            string[] varHeaders = isOutJob
                ? ["UNIQUE", "LoadPlan QTY", "KorberReport QTY", "Variance", "Status"]
                : ["Unique", "ASN QTY", "KorberReport QTY", "Variance", "Status"];
            for (int c = 0; c < varHeaders.Length; c++)
            {
                var cell = wsVar.Cell(1, c + 1);
                cell.Value = varHeaders[c];
                ApplyHeaderStyle(cell, headerBlue);
            }
            wsVar.Row(1).Height = 30;

            for (int r = 0; r < varianceRows.Count; r++)
            {
                int excelRow = r + 2;
                var row = varianceRows[r];
                wsVar.Row(excelRow).Height = 25;

                // Numeric-first conversion for Load ID just like result_df['Load ID'] = pd.to_numeric(...)
                if (long.TryParse(row.LoadId, NumberStyles.Integer, CultureInfo.InvariantCulture, out var longId))
                    wsVar.Cell(excelRow, 1).Value = longId;
                else if (double.TryParse(row.LoadId, NumberStyles.Any, CultureInfo.InvariantCulture, out var dblId))
                    wsVar.Cell(excelRow, 1).Value = dblId;
                else
                    wsVar.Cell(excelRow, 1).Value = row.LoadId;

                wsVar.Cell(excelRow, 2).Value = row.PlanQty;
                wsVar.Cell(excelRow, 3).Value = row.LoadedQty;
                wsVar.Cell(excelRow, 4).Value = row.Variance;
                wsVar.Cell(excelRow, 5).Value = row.Status;

                for (int c = 1; c <= 5; c++)
                {
                    var cell = wsVar.Cell(excelRow, c);
                    cell.Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Center;
                    cell.Style.Alignment.Vertical = XLAlignmentVerticalValues.Center;
                    ApplyThinBorder(cell);
                }

                var (fill, font) = statusStyles.GetValueOrDefault(row.Status, (XLColor.FromHtml("#00B050"), whiteColor));
                foreach (int styledCol in new[] { 4, 5 })
                {
                    var sc = wsVar.Cell(excelRow, styledCol);
                    sc.Style.Fill.BackgroundColor = fill;
                    sc.Style.Font.FontColor = font;
                    sc.Style.Font.Bold = true;
                }
            }
            AutoFitSheetColumns(wsVar);

            // 2. Loading_History_Original
            WriteDatasetSheet(wb, "Loading_History_Original", historyDf, headerBlue);

            // 3. Load_Plan_Original
            WriteDatasetSheet(wb, "Load_Plan_Original", planDf, headerBlue);

            // 4. Summary
            var wsSum = wb.Worksheets.Add("Summary");
            wsSum.Cell(1, 1).Value = "Metric";
            wsSum.Cell(1, 2).Value = "Value";
            ApplyHeaderStyle(wsSum.Cell(1, 1), headerBlue);
            ApplyHeaderStyle(wsSum.Cell(1, 2), headerBlue);

            for (int r = 0; r < summaryMetrics.Count; r++)
            {
                int er = r + 2;
                wsSum.Cell(er, 1).Value = summaryMetrics[r].Metric;
                SetXlObjectValue(wsSum.Cell(er, 2), summaryMetrics[r].Value);
                for (int c = 1; c <= 2; c++)
                {
                    var cell = wsSum.Cell(er, c);
                    cell.Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Left;
                    cell.Style.Alignment.Vertical = XLAlignmentVerticalValues.Center;
                    ApplyThinBorder(cell);
                }
            }
            AutoFitSheetColumns(wsSum);

            wb.SaveAs(outputFile);
            log?.Invoke("✅ Excel formatting applied successfully", "SUCCESS");
            return true;
        }
        catch (Exception e)
        {
            log?.Invoke($"⚠️ Formatting warning: {e.Message}", "WARNING");
            return false;
        }
    }

    private static void WriteDatasetSheet(XLWorkbook wb, string name, TabularDataset ds, XLColor headerBlue)
    {
        var ws = wb.Worksheets.Add(name);
        for (int c = 0; c < ds.ColumnCount; c++)
        {
            var cell = ws.Cell(1, c + 1);
            cell.Value = ds.Columns[c];
            ApplyHeaderStyle(cell, headerBlue);
        }

        for (int r = 0; r < ds.RowCount; r++)
        {
            int er = r + 2;
            var row = ds.Rows[r];
            for (int c = 0; c < ds.ColumnCount; c++)
            {
                var cell = ws.Cell(er, c + 1);
                SetXlObjectValue(cell, c < row.Length ? row[c] : null);
                cell.Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Left;
                cell.Style.Alignment.Vertical = XLAlignmentVerticalValues.Center;
                ApplyThinBorder(cell);
            }
        }
        AutoFitSheetColumns(ws);
    }

    private static void SetXlObjectValue(IXLCell cell, object? val)
    {
        if (val is null || val == DBNull.Value)
        {
            cell.Value = Blank.Value;
            return;
        }
        switch (val)
        {
            case long l: cell.Value = l; break;
            case int i: cell.Value = i; break;
            case double d: cell.Value = d; break;
            case float f: cell.Value = (double)f; break;
            case decimal m: cell.Value = (double)m; break;
            case bool b: cell.Value = b; break;
            case DateTime dt: cell.Value = dt; break;
            default: cell.Value = val.ToString() ?? ""; break;
        }
    }

    private static void ApplyHeaderStyle(IXLCell cell, XLColor headerBlue)
    {
        cell.Style.Fill.BackgroundColor = headerBlue;
        cell.Style.Font.FontColor = XLColor.White;
        cell.Style.Font.Bold = true;
        cell.Style.Font.FontSize = 11;
        cell.Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Center;
        cell.Style.Alignment.Vertical = XLAlignmentVerticalValues.Center;
        ApplyThinBorder(cell);
    }

    private static void ApplyThinBorder(IXLCell cell)
    {
        cell.Style.Border.LeftBorder = XLBorderStyleValues.Thin;
        cell.Style.Border.RightBorder = XLBorderStyleValues.Thin;
        cell.Style.Border.TopBorder = XLBorderStyleValues.Thin;
        cell.Style.Border.BottomBorder = XLBorderStyleValues.Thin;
    }

    private static void AutoFitSheetColumns(IXLWorksheet ws)
    {
        var range = ws.RangeUsed();
        if (range is null) return;

        int maxCol = range.LastColumn().ColumnNumber();
        int maxRow = range.LastRow().RowNumber();

        for (int col = 1; col <= maxCol; col++)
        {
            int maxLength = 0;
            for (int row = 1; row <= maxRow; row++)
            {
                var str = ws.Cell(row, col).GetFormattedString();
                if (!string.IsNullOrEmpty(str))
                    maxLength = Math.Max(maxLength, str.Length);
            }
            ws.Column(col).Width = Math.Min(maxLength + 3, 50);
        }
    }
}
