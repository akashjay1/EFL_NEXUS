using System.Net;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;

namespace EflNexus.Core.Monitoring;

public sealed class CloudErrorException : Exception
{
    public int Status { get; }

    public CloudErrorException(int status)
        : base(status < 500 ? "Cloud request rejected" : "Cloud unavailable")
    {
        Status = status;
    }
}

public sealed class CloudClient : IDisposable
{
    private readonly HttpClientHandler _handler;
    private readonly HttpClient _http;

    public string Url { get; }
    public string Key { get; }

    public CloudClient(string url, string key)
    {
        Url = OperatorPresence.ValidateProjectUrl(url);
        Key = OperatorPresence.ValidatePublishableKey(key);
        _handler = new HttpClientHandler { AllowAutoRedirect = false };
        _http = new HttpClient(_handler) { Timeout = TimeSpan.FromSeconds(8) };
    }

    public Dictionary<string, JsonElement> Post(
        string functionName,
        object body,
        IReadOnlyDictionary<string, string?>? credential = null)
    {
        using var req = new HttpRequestMessage(HttpMethod.Post, $"{Url}/functions/v1/{functionName}");
        req.Headers.Add("apikey", Key);
        if (credential is not null)
        {
            if (credential.TryGetValue("credential_id", out var cid) && !string.IsNullOrEmpty(cid))
                req.Headers.Add("x-device-id", cid);
            if (credential.TryGetValue("secret", out var sec) && !string.IsNullOrEmpty(sec))
                req.Headers.Add("x-device-secret", sec);
        }
        req.Content = JsonContent.Create(body);

        using var resp = _http.Send(req);
        if (resp.StatusCode != HttpStatusCode.OK)
            throw new CloudErrorException((int)resp.StatusCode);

        using var stream = resp.Content.ReadAsStream();
        using var doc = JsonDocument.Parse(stream);
        var result = new Dictionary<string, JsonElement>(StringComparer.Ordinal);
        if (doc.RootElement.ValueKind == JsonValueKind.Object)
        {
            foreach (var p in doc.RootElement.EnumerateObject())
                result[p.Name] = p.Value.Clone();
        }
        return result;
    }

    public void Dispose()
    {
        _http.Dispose();
        _handler.Dispose();
    }
}
