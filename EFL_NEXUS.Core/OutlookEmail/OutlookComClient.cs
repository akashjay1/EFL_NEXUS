using System.IO;
using System.Net;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using Microsoft.Win32;

namespace EflNexus.Core.OutlookEmail;

public static partial class DefaultSignatureResolver
{
    private static readonly string[] RegistryPaths =
    [
        @"Software\Microsoft\Office\16.0\Common\MailSettings",
        @"Software\Microsoft\Office\15.0\Common\MailSettings"
    ];

    [GeneratedRegex(@"(src)=(['""])([^'""]+)\2", RegexOptions.IgnoreCase)]
    private static partial Regex ImgSrcRegex();

    public static string FixSignatureImagePaths(string htmlText, string filesDir)
    {
        if (string.IsNullOrEmpty(filesDir) || !Directory.Exists(filesDir))
            return htmlText;

        return ImgSrcRegex().Replace(htmlText, m =>
        {
            var attr = m.Groups[1].Value;
            var quote = m.Groups[2].Value;
            var src = m.Groups[3].Value;

            if (src.StartsWith("http://", StringComparison.OrdinalIgnoreCase)
                || src.StartsWith("https://", StringComparison.OrdinalIgnoreCase)
                || src.StartsWith("file://", StringComparison.OrdinalIgnoreCase)
                || src.StartsWith("cid:", StringComparison.OrdinalIgnoreCase)
                || src.StartsWith("data:", StringComparison.OrdinalIgnoreCase))
            {
                return m.Value;
            }

            var absPath = Path.Combine(filesDir, src);
            if (File.Exists(absPath))
            {
                var uri = "file:///" + absPath.Replace('\\', '/');
                return $"{attr}={quote}{uri}{quote}";
            }
            return m.Value;
        });
    }

    public static string GetDefaultSignatureHtml()
    {
        var appdata = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
        if (string.IsNullOrEmpty(appdata))
            return "";

        var sigDir = Path.Combine(appdata, "Microsoft", "Signatures");
        if (!Directory.Exists(sigDir))
            return "";

        string? sigName = null;
        foreach (var regPath in RegistryPaths)
        {
            try
            {
                using var key = Registry.CurrentUser.OpenSubKey(regPath);
                if (key?.GetValue("NewSignature") is string val && !string.IsNullOrEmpty(val))
                {
                    sigName = val;
                    break;
                }
            }
            catch { }
        }

        if (string.IsNullOrEmpty(sigName))
        {
            try
            {
                var latest = new DirectoryInfo(sigDir)
                    .GetFiles("*.htm")
                    .OrderByDescending(f => f.LastWriteTimeUtc)
                    .FirstOrDefault();
                if (latest is null)
                    return "";
                sigName = Path.GetFileNameWithoutExtension(latest.Name);
            }
            catch
            {
                return "";
            }
        }

        var sigPath = Path.Combine(sigDir, $"{sigName}.htm");
        if (!File.Exists(sigPath))
            return "";

        string signatureHtml;
        try
        {
            signatureHtml = File.ReadAllText(sigPath);
        }
        catch
        {
            return "";
        }

        var filesDir = Path.Combine(sigDir, $"{sigName}_files");
        return FixSignatureImagePaths(signatureHtml, filesDir);
    }
}

public sealed partial class OutlookComClient
{
    private const int OutlookMailItem = 0;

    [GeneratedRegex(@"(<body[^>]*>)", RegexOptions.IgnoreCase)]
    private static partial Regex BodyTagRegex();

    public static string ComposeHtml(string bodyText, string signatureHtml, bool isRawHtmlFragment = false)
    {
        var messageHtml = isRawHtmlFragment
            ? bodyText + "<br>"
            : "<div style=\"font-family:Calibri,Arial,sans-serif;font-size:11pt;color:#000000;\">"
              + WebUtility.HtmlEncode(bodyText).Replace("\r\n", "\n").Replace("\n", "<br>")
              + "</div><br>";

        if (!string.IsNullOrEmpty(signatureHtml))
        {
            var match = BodyTagRegex().Match(signatureHtml);
            if (match.Success)
            {
                int idx = match.Index + match.Length;
                return signatureHtml[..idx] + messageHtml + signatureHtml[idx..];
            }
            return messageHtml + signatureHtml;
        }
        return $"<html><body>{messageHtml}</body></html>";
    }

    public Task PreviewAsync(
        string toAddr,
        string ccAddr,
        string subject,
        string bodyText,
        IReadOnlyList<string> attachmentPaths,
        bool includeSignature = true,
        bool isRawHtmlFragment = false)
    {
        return RunStaAsync(() => ExecuteOutlook(
            toAddr, ccAddr, subject, bodyText, attachmentPaths, includeSignature, isRawHtmlFragment, send: false));
    }

    public Task SendAsync(
        string toAddr,
        string ccAddr,
        string subject,
        string bodyText,
        IReadOnlyList<string> attachmentPaths,
        bool includeSignature = true,
        bool isRawHtmlFragment = false)
    {
        return RunStaAsync(() => ExecuteOutlook(
            toAddr, ccAddr, subject, bodyText, attachmentPaths, includeSignature, isRawHtmlFragment, send: true));
    }

    private static Task RunStaAsync(Action action)
    {
        var tcs = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var thread = new Thread(() =>
        {
            try
            {
                action();
                tcs.SetResult();
            }
            catch (Exception ex)
            {
                tcs.SetException(ex);
            }
        });
        thread.IsBackground = true;
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        return tcs.Task;
    }

    private static void ExecuteOutlook(
        string toAddr,
        string ccAddr,
        string subject,
        string bodyText,
        IReadOnlyList<string> attachmentPaths,
        bool includeSignature,
        bool isRawHtmlFragment,
        bool send)
    {
        var outlookType = Type.GetTypeFromProgID("Outlook.Application")
            ?? throw new InvalidOperationException("Microsoft Outlook classic COM automation ('Outlook.Application') is not available on this machine.");

        object? app = null;
        object? mail = null;
        object? attachments = null;
        try
        {
            app = Activator.CreateInstance(outlookType)
                ?? throw new InvalidOperationException("Could not initialize Outlook.Application.");

            mail = Invoke(app, "CreateItem", OutlookMailItem)
                ?? throw new InvalidOperationException("Outlook CreateItem(0) returned null.");

            try
            {
                SetProp(mail, "To", toAddr);
                if (!string.IsNullOrWhiteSpace(ccAddr))
                    SetProp(mail, "CC", ccAddr);
                SetProp(mail, "Subject", subject);
            }
            catch (Exception ex)
            {
                throw new InvalidOperationException($"Could not set recipients/subject: {ex.Message}", ex);
            }

            string sigHtml = "";
            if (includeSignature)
            {
                try { sigHtml = DefaultSignatureResolver.GetDefaultSignatureHtml(); }
                catch { sigHtml = ""; }
            }

            try
            {
                SetProp(mail, "HTMLBody", ComposeHtml(bodyText, sigHtml, isRawHtmlFragment));
            }
            catch (Exception ex)
            {
                throw new InvalidOperationException($"Could not set the email body: {ex.Message}", ex);
            }

            attachments = GetProp(mail, "Attachments");
            if (attachments is not null)
            {
                foreach (var path in attachmentPaths)
                {
                    if (!File.Exists(path))
                        throw new FileNotFoundException($"Attachment file not found on disk: {path}", path);
                    try
                    {
                        Invoke(attachments, "Add", path);
                    }
                    catch (Exception ex)
                    {
                        throw new InvalidOperationException($"Could not attach '{Path.GetFileName(path)}': {ex.Message}", ex);
                    }
                }
            }

            if (send)
                Invoke(mail, "Send");
            else
                Invoke(mail, "Display", false);
        }
        finally
        {
            ReleaseCom(attachments);
            ReleaseCom(mail);
            ReleaseCom(app);
        }
    }

    private static object? Invoke(object target, string method, params object[] args)
        => target.GetType().InvokeMember(method, BindingFlags.InvokeMethod, null, target, args);

    private static object? GetProp(object target, string prop)
        => target.GetType().InvokeMember(prop, BindingFlags.GetProperty, null, target, null);

    private static void SetProp(object target, string prop, object value)
        => target.GetType().InvokeMember(prop, BindingFlags.SetProperty, null, target, [value]);

    private static void ReleaseCom(object? obj)
    {
        if (obj is not null && Marshal.IsComObject(obj))
        {
            try { Marshal.ReleaseComObject(obj); } catch { }
        }
    }
}
