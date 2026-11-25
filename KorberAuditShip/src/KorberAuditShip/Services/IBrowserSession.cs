namespace KorberAuditShip.Services;

/// <summary>
/// Abstraction over browser/WebDriver automation so Körber workflows can run against
/// Microsoft Edge via Selenium or against deterministic mock sessions in tests.
/// </summary>
public interface IBrowserSession : IDisposable
{
    bool IsAlive { get; }
    void Navigate(string url);
    string GetCurrentUrl();
    string GetPageSource();
    string GetReadyState();
    string GetVisibleBodyText();
    object? ExecuteScript(string script, params object[] args);
    bool TryClickVisibleByXPaths(IEnumerable<string> xpaths);
    bool TryDoubleClickVisibleByXPaths(IEnumerable<string> xpaths);
    bool TryTypeVisibleByXPaths(IEnumerable<string> xpaths, string value);
    bool IsAnyXPathVisible(IEnumerable<string> xpaths);
    bool TryFallbackTypeRfInput(string value);
    bool TryFallbackClickRfSubmit();
    void SendEnterKeyToActiveElement();
    void SendF1Key();
    void Quit();
}

/// <summary>
/// Factory for launching/attaching to a browser session.
/// </summary>
public interface IBrowserSessionFactory
{
    Task<IBrowserSession> OpenOrAttachAsync(Action<string>? statusCallback, CancellationToken cancellationToken);
}
