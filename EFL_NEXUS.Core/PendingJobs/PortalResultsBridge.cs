using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Text.RegularExpressions;
using ClosedXML.Excel;
using EflNexus.Core.Infrastructure;

namespace EflNexus.Core.PendingJobs;

/// <summary>
/// WebView2 COM host object &amp; strongly-typed coordinator for the internal Reconciliation portal browser
/// (1:1 parity with ResultsBridge in website_data_grabber.py).
/// </summary>
[ComVisible(true)]
[ClassInterface(ClassInterfaceType.AutoDual)]
public sealed partial class PortalResultsBridge
{
    private readonly string _cmdPath;
    private readonly string? _resultPath;
    private readonly Dictionary<string, PortalJobRecord> _knownRecords = new(StringComparer.OrdinalIgnoreCase);

    [GeneratedRegex(@"^\d+$")]
    private static partial Regex DigitsOnlyRegex();

    public PortalResultsBridge(string cmdPath, string? resultPath = null)
    {
        _cmdPath = cmdPath;
        _resultPath = resultPath;
        foreach (var (key, entry) in GrabberSettingsAndPaths.LoadPersistedJobMap())
        {
            _knownRecords[key] = new PortalJobRecord
            {
                JobId = entry.JobId,
                WarfId = entry.WarfId,
                Gatepass = entry.Gatepass,
                Client = entry.Client,
                Status = entry.Status,
                Warehouse = entry.Warehouse
            };
        }
    }

    public string save_job_ids_json(string valuesJson)
    {
        var list = new List<PortalJobRecord>();
        try
        {
            using var doc = JsonDocument.Parse(string.IsNullOrWhiteSpace(valuesJson) ? "[]" : valuesJson);
            if (doc.RootElement.ValueKind == JsonValueKind.Array)
            {
                foreach (var el in doc.RootElement.EnumerateArray())
                {
                    if (el.ValueKind == JsonValueKind.Object)
                    {
                        list.Add(new PortalJobRecord
                        {
                            JobId = GrabberSettingsAndPaths.Clean(GetStringProp(el, "job_id")),
                            Client = GrabberSettingsAndPaths.Clean(GetStringProp(el, "client")),
                            Status = GrabberSettingsAndPaths.Clean(GetStringProp(el, "status")),
                            Warehouse = GrabberSettingsAndPaths.Clean(GetStringProp(el, "warehouse")),
                            Gatepass = GrabberSettingsAndPaths.Clean(GetStringProp(el, "gatepass")),
                            Seal = GrabberSettingsAndPaths.Clean(GetStringProp(el, "seal")),
                            DeliveryLocation = GrabberSettingsAndPaths.Clean(GetStringProp(el, "delivery_location")),
                            WarfId = GrabberSettingsAndPaths.Clean(GetStringProp(el, "warf_id"))
                        });
                    }
                    else
                    {
                        list.Add(new PortalJobRecord
                        {
                            JobId = GrabberSettingsAndPaths.Clean(el.ToString())
                        });
                    }
                }
            }
        }
        catch { }

        int count = SaveJobIds(list);
        return JsonSerializer.Serialize(new { count });
    }

    [ComVisible(false)]
    public int SaveJobIds(IEnumerable<PortalJobRecord> values)
    {
        var records = new List<PortalJobRecord>();
        var uniqueIds = new List<string>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (var item in values)
        {
            var rawId = GrabberSettingsAndPaths.Clean(item.JobId);
            if (string.IsNullOrEmpty(rawId) || !seen.Add(rawId))
                continue;

            var rec = new PortalJobRecord
            {
                JobId = rawId,
                Client = GrabberSettingsAndPaths.Clean(item.Client),
                Status = GrabberSettingsAndPaths.NormalizeReconciliationStatus(item.Status),
                Warehouse = GrabberSettingsAndPaths.Clean(item.Warehouse),
                Gatepass = GrabberSettingsAndPaths.Clean(item.Gatepass),
                Seal = GrabberSettingsAndPaths.Clean(item.Seal),
                DeliveryLocation = GrabberSettingsAndPaths.Clean(item.DeliveryLocation),
                WarfId = GrabberSettingsAndPaths.Clean(item.WarfId)
            };

            records.Add(rec);
            _knownRecords[rawId] = rec;
            if (!string.IsNullOrEmpty(rec.WarfId))
                _knownRecords[rec.WarfId] = rec;
            uniqueIds.Add(rawId);
        }

        if (!string.IsNullOrEmpty(_resultPath))
            GrabberSettingsAndPaths.WriteResultsAtomic(_resultPath, uniqueIds, records);

        GrabberSettingsAndPaths.UpdatePersistedJobMap(records);
        return uniqueIds.Count;
    }

    [ComVisible(false)]
    public PortalJobRecord? LookupJobRecord(string? keyOrId)
    {
        var target = (keyOrId ?? "").Trim();
        if (string.IsNullOrEmpty(target))
            return null;

        if (_knownRecords.TryGetValue(target, out var cached))
            return cached;

        var persisted = GrabberSettingsAndPaths.LoadPersistedJobMap();
        if (persisted.TryGetValue(target.ToLowerInvariant(), out var mapped) ||
            persisted.TryGetValue(target, out mapped))
        {
            var rec = new PortalJobRecord
            {
                JobId = mapped.JobId,
                WarfId = mapped.WarfId,
                Gatepass = mapped.Gatepass,
                Client = mapped.Client,
                Status = mapped.Status,
                Warehouse = mapped.Warehouse
            };
            _knownRecords[target] = rec;
            return rec;
        }

        foreach (var candidate in new[] { _resultPath, GrabberSettingsAndPaths.ResultFilePath })
        {
            if (string.IsNullOrEmpty(candidate) || !File.Exists(candidate))
                continue;
            try
            {
                var payload = JsonSerializer.Deserialize<PortalResultsPayload>(File.ReadAllText(candidate));
                if (payload?.Records is null)
                    continue;
                foreach (var r in payload.Records)
                {
                    if (!string.IsNullOrWhiteSpace(r.JobId))
                        _knownRecords[r.JobId.Trim()] = r;
                    if (!string.IsNullOrWhiteSpace(r.WarfId))
                        _knownRecords[r.WarfId.Trim()] = r;
                    if (string.Equals(target, r.JobId.Trim(), StringComparison.OrdinalIgnoreCase)
                        || string.Equals(target, r.WarfId.Trim(), StringComparison.OrdinalIgnoreCase))
                    {
                        return r;
                    }
                }
            }
            catch { }
        }

        return null;
    }

    public string lookup_warf_job_json(string warfId)
    {
        var rec = LookupJobRecord(warfId);
        return JsonSerializer.Serialize(new
        {
            job_id = (rec?.JobId ?? "").Trim(),
            gatepass = (rec?.Gatepass ?? "").Trim(),
            client = (rec?.Client ?? "").Trim()
        });
    }

    public string save_downloaded_file_json(string payloadJson)
    {
        var req = JsonSerializer.Deserialize<SaveDownloadRequest>(string.IsNullOrWhiteSpace(payloadJson) ? "{}" : payloadJson)
            ?? new SaveDownloadRequest();
        return JsonSerializer.Serialize(SaveDownloadedFile(req));
    }

    [ComVisible(false)]
    public PortalSavedFileResult SaveDownloadedFile(SaveDownloadRequest req)
    {
        try
        {
            var rawFilename = (req.Filename ?? "").Trim();
            var b64Data = req.Data ?? "";
            var url = req.Url ?? "";
            var rawJobId = (req.JobId ?? "").Trim();
            var gatepass = (req.Gatepass ?? "").Trim();
            var client = (req.Client ?? "").Trim();

            int comma = b64Data.IndexOf(',');
            if (comma >= 0)
                b64Data = b64Data[(comma + 1)..];

            byte[] fileBytes;
            try
            {
                fileBytes = Convert.FromBase64String(b64Data);
            }
            catch
            {
                return new PortalSavedFileResult { Success = false, Error = "Invalid data format" };
            }

            var jobId = rawJobId;
            var rec = LookupJobRecord(rawJobId);
            if (rec is not null)
            {
                if (!string.IsNullOrWhiteSpace(rec.JobId))
                    jobId = rec.JobId.Trim();
                if (string.IsNullOrEmpty(gatepass))
                    gatepass = (rec.Gatepass ?? "").Trim();
                if (string.IsNullOrEmpty(client))
                    client = (rec.Client ?? "").Trim();
            }

            // Excel metadata fallback for zip/xlsx payloads starting with PK\x03\x04
            if ((string.IsNullOrEmpty(gatepass) || string.IsNullOrEmpty(client) || DigitsOnlyRegex().IsMatch(jobId))
                && fileBytes.Length >= 4 && fileBytes[0] == 0x50 && fileBytes[1] == 0x4B && fileBytes[2] == 0x03 && fileBytes[3] == 0x04)
            {
                try
                {
                    using var ms = new MemoryStream(fileBytes, writable: false);
                    using var wb = new XLWorkbook(ms);
                    var ws = wb.Worksheets.FirstOrDefault();
                    if (ws is not null)
                    {
                        var range = ws.RangeUsed();
                        if (range is not null && range.RowCount() >= 2)
                        {
                            var headers = range.FirstRow().Cells()
                                .Select(c => c.GetString().Trim().ToLowerInvariant())
                                .ToList();
                            var rowVals = range.Row(2).Cells()
                                .Select(c => c.GetString().Trim())
                                .ToList();

                            int gpIdx = headers.FindIndex(h => h.Contains("gate", StringComparison.Ordinal) && h.Contains("pass", StringComparison.Ordinal));
                            if (gpIdx >= 0 && gpIdx < rowVals.Count && string.IsNullOrEmpty(gatepass))
                                gatepass = rowVals[gpIdx];

                            int cliIdx = headers.FindIndex(h =>
                                h.Contains("cust", StringComparison.Ordinal) ||
                                h.Contains("client", StringComparison.Ordinal) ||
                                h.Contains("customer", StringComparison.Ordinal));
                            if (cliIdx >= 0 && cliIdx < rowVals.Count && string.IsNullOrEmpty(client))
                                client = rowVals[cliIdx];
                        }
                    }
                }
                catch { }
            }

            var targetFolder = GrabberSettingsAndPaths.GetJobDownloadFolder(jobId, gatepass, client);

            if (string.IsNullOrEmpty(rawFilename) || rawFilename.Equals("download", StringComparison.OrdinalIgnoreCase)
                || rawFilename.Equals("file", StringComparison.OrdinalIgnoreCase))
            {
                if (!string.IsNullOrEmpty(url) && Uri.TryCreate(url, UriKind.RelativeOrAbsolute, out var parsedUri))
                {
                    var pathPart = parsedUri.IsAbsoluteUri ? parsedUri.AbsolutePath : url;
                    var seg = pathPart.Split('/').LastOrDefault();
                    if (!string.IsNullOrEmpty(seg))
                        rawFilename = Uri.UnescapeDataString(seg);
                }
            }

            if (string.IsNullOrEmpty(rawFilename))
                rawFilename = !string.IsNullOrEmpty(jobId) ? $"job_{jobId}_file.xlsx" : "downloaded_file";

            rawFilename = rawFilename.Split('?')[0].Split('#')[0].Trim();
            var targetPath = GrabberSettingsAndPaths.GetUniqueDownloadPath(rawFilename, targetFolder);
            File.WriteAllBytes(targetPath, fileBytes);

            var fullPath = Path.GetFullPath(targetPath);
            var parentFull = Path.GetDirectoryName(fullPath)!;
            var folderName = new DirectoryInfo(parentFull).Name;

            try
            {
                var ev = new DownloadEventPayload
                {
                    Action = "file_downloaded",
                    Filename = Path.GetFileName(fullPath),
                    Path = fullPath,
                    Folder = folderName,
                    FolderPath = parentFull,
                    Size = fileBytes.LongLength,
                    Time = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0,
                    JobId = jobId,
                    Gatepass = gatepass,
                    Client = client
                };
                GrabberSettingsAndPaths.WriteJsonAtomic(GrabberSettingsAndPaths.DownloadEventFilePath, JsonSerializer.Serialize(ev));
            }
            catch { }

            return new PortalSavedFileResult
            {
                Success = true,
                Filename = Path.GetFileName(fullPath),
                Path = fullPath,
                Folder = folderName,
                FolderPath = parentFull,
                Size = fileBytes.LongLength
            };
        }
        catch (Exception ex)
        {
            return new PortalSavedFileResult { Success = false, Error = ex.Message };
        }
    }

    public string request_loading_history_json(string payloadJson)
    {
        try
        {
            using var doc = JsonDocument.Parse(string.IsNullOrWhiteSpace(payloadJson) ? "{}" : payloadJson);
            var root = doc.RootElement;
            string jid = GrabberSettingsAndPaths.Clean(GetStringProp(root, "job_id"));
            string gp = GrabberSettingsAndPaths.Clean(GetStringProp(root, "gatepass"));
            string cli = GrabberSettingsAndPaths.Clean(GetStringProp(root, "client"));
            string pageCode = GrabberSettingsAndPaths.Clean(GetStringProp(root, "page_code"));
            string reportName = GrabberSettingsAndPaths.Clean(GetStringProp(root, "report_name"));

            if (string.IsNullOrEmpty(pageCode))
            {
                pageCode = jid.StartsWith("IN", StringComparison.OrdinalIgnoreCase) ? "2598" : "1992";
            }
            if (string.IsNullOrEmpty(reportName))
            {
                reportName = pageCode == "2598" ? "Inventory by gatepass" : "Loading History Report";
            }

            if (string.IsNullOrEmpty(gp) && !string.IsNullOrEmpty(jid))
            {
                var rec = LookupJobRecord(jid);
                if (rec is not null)
                {
                    gp = GrabberSettingsAndPaths.Clean(rec.Gatepass);
                    if (string.IsNullOrEmpty(cli))
                        cli = GrabberSettingsAndPaths.Clean(rec.Client);
                }
            }

            if (string.IsNullOrEmpty(gp) && !string.IsNullOrEmpty(jid))
            {
                var persisted = GrabberSettingsAndPaths.LoadPersistedJobMap();
                if (persisted.TryGetValue(jid.ToLowerInvariant(), out var mapped))
                {
                    gp = GrabberSettingsAndPaths.Clean(mapped.Gatepass);
                    if (string.IsNullOrEmpty(cli))
                        cli = GrabberSettingsAndPaths.Clean(mapped.Client);
                }
            }

            if (string.IsNullOrEmpty(gp) && File.Exists(GrabberSettingsAndPaths.ResultFilePath))
            {
                try
                {
                    var res = JsonSerializer.Deserialize<PortalResultsPayload>(File.ReadAllText(GrabberSettingsAndPaths.ResultFilePath));
                    if (res?.Records is not null)
                    {
                        for (int i = res.Records.Count - 1; i >= 0; i--)
                        {
                            var item = res.Records[i];
                            var itemJid = GrabberSettingsAndPaths.Clean(item.JobId);
                            var itemGp = GrabberSettingsAndPaths.Clean(item.Gatepass);
                            var itemCli = GrabberSettingsAndPaths.Clean(item.Client);
                            if ((!string.IsNullOrEmpty(jid) && string.Equals(itemJid, jid, StringComparison.OrdinalIgnoreCase))
                                || string.IsNullOrEmpty(jid))
                            {
                                if (string.IsNullOrEmpty(gp) && !string.IsNullOrEmpty(itemGp))
                                    gp = itemGp;
                                if (string.IsNullOrEmpty(jid) && !string.IsNullOrEmpty(itemJid))
                                    jid = itemJid;
                                if (string.IsNullOrEmpty(cli) && !string.IsNullOrEmpty(itemCli))
                                    cli = itemCli;
                                if (!string.IsNullOrEmpty(gp))
                                    break;
                            }
                        }
                    }
                }
                catch { }
            }

            double now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
            var ev = new LoadingHistoryEventPayload
            {
                Action = "open_loading_history",
                Time = now,
                JobId = jid,
                Gatepass = gp,
                Client = cli,
                PageCode = pageCode,
                ReportName = reportName
            };
            GrabberSettingsAndPaths.WriteJsonAtomic(GrabberSettingsAndPaths.LoadingHistoryEventFilePath, JsonSerializer.Serialize(ev));

            if (!string.IsNullOrEmpty(gp))
            {
                var cmd = new
                {
                    action = "query_and_export",
                    time = now,
                    job_id = jid,
                    gatepass = gp,
                    client = cli,
                    page_code = pageCode,
                    report_name = reportName
                };
                GrabberSettingsAndPaths.WriteJsonAtomic(GrabberSettingsAndPaths.LoadingHistoryCommandFilePath, JsonSerializer.Serialize(cmd));
            }

            return JsonSerializer.Serialize(new { success = true });
        }
        catch (Exception ex)
        {
            return JsonSerializer.Serialize(new { success = false, error = ex.Message });
        }
    }

    public string? get_pending_command_json()
    {
        try
        {
            if (File.Exists(_cmdPath))
            {
                var text = File.ReadAllText(_cmdPath);
                try { File.Delete(_cmdPath); } catch { }
                return text;
            }
        }
        catch { }
        return null;
    }

    private static string GetStringProp(JsonElement obj, string name)
        => obj.ValueKind == JsonValueKind.Object && obj.TryGetProperty(name, out var el) && el.ValueKind != JsonValueKind.Null
            ? el.ToString()
            : "";
}
