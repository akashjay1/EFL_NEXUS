using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json;

namespace EflNexus.Core.PendingJobs;

/// <summary>
/// WebView2 COM host object &amp; context resolver for HighJump Loading History export browser
/// (1:1 parity with LoadingHistoryBridge in website_data_grabber.py).
/// </summary>
[ComVisible(true)]
[ClassInterface(ClassInterfaceType.AutoDual)]
public sealed class LoadingHistoryBridge
{
    private readonly bool _stopAtGatepass;
    private string _gatepass;
    private string _jobId;
    private string _client;
    private string _pageCode;
    private string _reportName;

    public LoadingHistoryBridge(
        string gatepass,
        string jobId = "",
        string client = "",
        bool stopAtGatepass = false,
        string pageCode = "1992",
        string reportName = "Loading History Report")
    {
        _stopAtGatepass = stopAtGatepass;
        _gatepass = GrabberSettingsAndPaths.Clean(gatepass);
        _jobId = GrabberSettingsAndPaths.Clean(jobId);
        _client = GrabberSettingsAndPaths.Clean(client);
        _pageCode = string.IsNullOrWhiteSpace(pageCode) ? "1992" : pageCode.Trim();
        _reportName = string.IsNullOrWhiteSpace(reportName) ? "Loading History Report" : reportName.Trim();
        if (_pageCode == "1992" && _jobId.StartsWith("IN", StringComparison.OrdinalIgnoreCase))
        {
            _pageCode = "2598";
            _reportName = "Inventory by gatepass";
        }
    }

    [ComVisible(false)]
    public static (string Gatepass, string JobId, string Client, string PageCode, string ReportName) ResolveInitialContext(
        string gatepass,
        string jobId,
        string client,
        bool stopAtGatepass,
        string pageCode = "1992",
        string reportName = "Loading History Report")
    {
        string pCode = string.IsNullOrWhiteSpace(pageCode) ? "1992" : pageCode.Trim();
        string rName = string.IsNullOrWhiteSpace(reportName) ? "Loading History Report" : reportName.Trim();

        if (stopAtGatepass)
            return ("", "", "", pCode, rName);

        string gp = GrabberSettingsAndPaths.Clean(gatepass);
        string jid = GrabberSettingsAndPaths.Clean(jobId);
        string cli = GrabberSettingsAndPaths.Clean(client);

        var eventPath = GrabberSettingsAndPaths.LoadingHistoryEventFilePath;
        if (File.Exists(eventPath))
        {
            try
            {
                var ev = JsonSerializer.Deserialize<LoadingHistoryEventPayload>(File.ReadAllText(eventPath));
                if (ev is not null)
                {
                    if (string.IsNullOrEmpty(gp))
                        gp = GrabberSettingsAndPaths.Clean(string.IsNullOrEmpty(ev.Gatepass) ? ev.ActiveGatepass : ev.Gatepass);
                    if (string.IsNullOrEmpty(jid))
                        jid = GrabberSettingsAndPaths.Clean(ev.JobId);
                    if (string.IsNullOrEmpty(cli))
                        cli = GrabberSettingsAndPaths.Clean(ev.Client);
                    if (!string.IsNullOrEmpty(ev.PageCode))
                        pCode = GrabberSettingsAndPaths.Clean(ev.PageCode);
                    if (!string.IsNullOrEmpty(ev.ReportName))
                        rName = GrabberSettingsAndPaths.Clean(ev.ReportName);
                }
            }
            catch { }
        }

        var persisted = GrabberSettingsAndPaths.LoadPersistedJobMap();
        if (!string.IsNullOrEmpty(jid) && persisted.TryGetValue(jid.ToLowerInvariant(), out var byJid))
        {
            if (string.IsNullOrEmpty(gp))
                gp = GrabberSettingsAndPaths.Clean(byJid.Gatepass);
            if (string.IsNullOrEmpty(cli))
                cli = GrabberSettingsAndPaths.Clean(byJid.Client);
        }
        else if (!string.IsNullOrEmpty(gp))
        {
            foreach (var mapped in persisted.Values)
            {
                if (string.Equals(GrabberSettingsAndPaths.Clean(mapped.Gatepass), gp, StringComparison.Ordinal))
                {
                    if (string.IsNullOrEmpty(jid))
                        jid = GrabberSettingsAndPaths.Clean(mapped.JobId);
                    if (string.IsNullOrEmpty(cli))
                        cli = GrabberSettingsAndPaths.Clean(mapped.Client);
                    break;
                }
            }
        }

        if ((string.IsNullOrEmpty(jid) || string.IsNullOrEmpty(cli) || string.IsNullOrEmpty(gp))
            && File.Exists(GrabberSettingsAndPaths.ResultFilePath))
        {
            try
            {
                var res = JsonSerializer.Deserialize<PortalResultsPayload>(File.ReadAllText(GrabberSettingsAndPaths.ResultFilePath));
                if (res?.Records is not null)
                {
                    for (int i = res.Records.Count - 1; i >= 0; i--)
                    {
                        var item = res.Records[i];
                        var itemGp = GrabberSettingsAndPaths.Clean(item.Gatepass);
                        var itemJid = GrabberSettingsAndPaths.Clean(item.JobId);
                        var itemCli = GrabberSettingsAndPaths.Clean(item.Client);
                        if (!string.IsNullOrEmpty(gp) && string.Equals(itemGp, gp, StringComparison.Ordinal))
                        {
                            if (string.IsNullOrEmpty(jid)) jid = itemJid;
                            if (string.IsNullOrEmpty(cli)) cli = itemCli;
                            break;
                        }
                        if (!string.IsNullOrEmpty(jid) && string.Equals(itemJid, jid, StringComparison.Ordinal))
                        {
                            if (string.IsNullOrEmpty(gp)) gp = itemGp;
                            if (string.IsNullOrEmpty(cli)) cli = itemCli;
                            break;
                        }
                    }
                }
            }
            catch { }
        }

        if (pCode == "1992" && jid.StartsWith("IN", StringComparison.OrdinalIgnoreCase))
        {
            pCode = "2598";
            rName = "Inventory by gatepass";
        }

        return (gp, jid, cli, pCode, rName);
    }

    public string? get_pending_command_json()
    {
        var cmdPath = GrabberSettingsAndPaths.LoadingHistoryCommandFilePath;
        try
        {
            if (File.Exists(cmdPath))
            {
                var text = File.ReadAllText(cmdPath);
                try { File.Delete(cmdPath); } catch { }
                var cmd = JsonSerializer.Deserialize<PendingCommandPayload>(text);
                if (cmd is not null)
                {
                    var gp = GrabberSettingsAndPaths.Clean(cmd.Gatepass);
                    var jid = GrabberSettingsAndPaths.Clean(cmd.JobId);
                    var cli = GrabberSettingsAndPaths.Clean(cmd.Client);
                    if (!string.IsNullOrEmpty(gp)) _gatepass = gp;
                    if (!string.IsNullOrEmpty(jid)) _jobId = jid;
                    if (!string.IsNullOrEmpty(cli)) _client = cli;
                    if (!string.IsNullOrEmpty(cmd.PageCode)) _pageCode = cmd.PageCode;
                    if (!string.IsNullOrEmpty(cmd.ReportName)) _reportName = cmd.ReportName;
                }
                return text;
            }
        }
        catch { }
        return null;
    }

    public void report_gatepass(string val)
    {
        var clean = GrabberSettingsAndPaths.Clean(val);
        if (!string.IsNullOrEmpty(clean))
            _gatepass = clean;
    }

    public string get_gatepass()
    {
        if (!string.IsNullOrEmpty(_gatepass))
            return _gatepass;
        if (_stopAtGatepass)
            return "";

        var evPath = GrabberSettingsAndPaths.LoadingHistoryEventFilePath;
        if (File.Exists(evPath))
        {
            try
            {
                var ev = JsonSerializer.Deserialize<LoadingHistoryEventPayload>(File.ReadAllText(evPath));
                if (ev is not null)
                    _gatepass = GrabberSettingsAndPaths.Clean(string.IsNullOrEmpty(ev.Gatepass) ? ev.ActiveGatepass : ev.Gatepass);
            }
            catch { }
        }

        if (string.IsNullOrEmpty(_gatepass) && File.Exists(GrabberSettingsAndPaths.ResultFilePath))
        {
            try
            {
                var res = JsonSerializer.Deserialize<PortalResultsPayload>(File.ReadAllText(GrabberSettingsAndPaths.ResultFilePath));
                if (res?.Records is not null)
                {
                    for (int i = res.Records.Count - 1; i >= 0; i--)
                    {
                        var gp = GrabberSettingsAndPaths.Clean(res.Records[i].Gatepass);
                        if (!string.IsNullOrEmpty(gp))
                        {
                            _gatepass = gp;
                            break;
                        }
                    }
                }
            }
            catch { }
        }

        return _gatepass;
    }

    public string get_job_id() => _jobId;

    public string get_client() => _client;

    public string get_page_code() => _pageCode;

    public string get_report_name() => _reportName;

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
            var gp = GrabberSettingsAndPaths.Clean(!string.IsNullOrEmpty(req.Gatepass) ? req.Gatepass : get_gatepass());
            var jid = GrabberSettingsAndPaths.Clean(!string.IsNullOrEmpty(req.JobId) ? req.JobId : _jobId);
            var cli = GrabberSettingsAndPaths.Clean(!string.IsNullOrEmpty(req.Client) ? req.Client : _client);

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

            var destFolder = GrabberSettingsAndPaths.GetJobDownloadFolder(jid, gp, cli);

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
            {
                rawFilename = (_pageCode == "2598" || jid.StartsWith("IN", StringComparison.OrdinalIgnoreCase))
                    ? "Inventory_By_Gatepass.xlsx"
                    : "Loading_History_Report.xlsx";
            }

            rawFilename = rawFilename.Split('?')[0].Split('#')[0].Trim();
            var targetPath = GrabberSettingsAndPaths.GetUniqueDownloadPath(rawFilename, destFolder);
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
                    JobId = jid,
                    Gatepass = gp,
                    Client = cli
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
}
