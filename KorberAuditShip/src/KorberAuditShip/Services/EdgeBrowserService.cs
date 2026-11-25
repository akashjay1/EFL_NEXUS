using System.Diagnostics;
using System.IO;
using System.Net.Sockets;
using OpenQA.Selenium;
using OpenQA.Selenium.Edge;
using OpenQA.Selenium.Interactions;

namespace KorberAuditShip.Services;

/// <summary>
/// Launches Microsoft Edge with remote debugging on port 9222 and a dedicated user profile
/// (~/Edge_LPAKASHM_Profile), then attaches Selenium EdgeDriver with eager page-load strategy.
/// </summary>
public sealed class EdgeBrowserService : IBrowserSessionFactory
{
    public static string GetEdgeExecutablePath()
    {
        var userProfile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        string[] candidates =
        [
            @"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            @"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            Path.Combine(userProfile, @"AppData\Local\Microsoft\Edge\Application\msedge.exe")
        ];

        foreach (var path in candidates)
        {
            if (File.Exists(path))
                return path;
        }

        throw new FileNotFoundException("Microsoft Edge executable was not found.");
    }

    public static string GetEdgeProfileDirectory()
    {
        var home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        return Path.Combine(home, KorberSelectors.EdgeProfileFolderName);
    }

    public static bool IsPortOpen(string host, int port, TimeSpan timeout)
    {
        try
        {
            using var client = new TcpClient();
            var task = client.ConnectAsync(host, port);
            return task.Wait(timeout) && client.Connected;
        }
        catch
        {
            return false;
        }
    }

    public async Task<IBrowserSession> OpenOrAttachAsync(
        Action<string>? statusCallback,
        CancellationToken cancellationToken)
    {
        await EnsureEdgeDebugRunningAsync(statusCallback, cancellationToken).ConfigureAwait(false);

        var options = new EdgeOptions
        {
            PageLoadStrategy = PageLoadStrategy.Eager,
            DebuggerAddress = $"127.0.0.1:{KorberSelectors.EdgeDebugPort}"
        };

        var driver = await Task.Run(() =>
        {
            cancellationToken.ThrowIfCancellationRequested();
            var service = EdgeDriverService.CreateDefaultService();
            service.HideCommandPromptWindow = true;
            var d = new EdgeDriver(service, options);
            d.Manage().Timeouts().PageLoad = TimeSpan.FromSeconds(90);
            d.Manage().Timeouts().ImplicitWait = TimeSpan.Zero;
            try
            {
                d.Manage().Window.Maximize();
            }
            catch
            {
                // Ignore maximize errors when already maximized
            }
            return d;
        }, cancellationToken).ConfigureAwait(false);

        return new SeleniumEdgeSession(driver);
    }

    private static async Task EnsureEdgeDebugRunningAsync(
        Action<string>? statusCallback,
        CancellationToken cancellationToken)
    {
        if (IsPortOpen("127.0.0.1", KorberSelectors.EdgeDebugPort, TimeSpan.FromMilliseconds(500)))
            return;

        var edgeExe = GetEdgeExecutablePath();
        var profileDir = GetEdgeProfileDirectory();
        Directory.CreateDirectory(profileDir);

        var psi = new ProcessStartInfo
        {
            FileName = edgeExe,
            UseShellExecute = false,
            CreateNoWindow = false
        };
        psi.ArgumentList.Add($"--remote-debugging-port={KorberSelectors.EdgeDebugPort}");
        psi.ArgumentList.Add($"--user-data-dir={profileDir}");
        psi.ArgumentList.Add("--start-maximized");
        psi.ArgumentList.Add("--no-first-run");
        psi.ArgumentList.Add("--no-default-browser-check");
        psi.ArgumentList.Add(KorberSelectors.KorberUrl);

        Process.Start(psi);

        var deadline = DateTime.UtcNow.AddSeconds(20);
        while (DateTime.UtcNow < deadline)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (IsPortOpen("127.0.0.1", KorberSelectors.EdgeDebugPort, TimeSpan.FromMilliseconds(500)))
                return;

            statusCallback?.Invoke("Starting normal Microsoft Edge...");
            await Task.Delay(500, cancellationToken).ConfigureAwait(false);
        }

        throw new TimeoutException("Normal Microsoft Edge did not open with remote debugging.");
    }

    private sealed class SeleniumEdgeSession : IBrowserSession
    {
        private readonly EdgeDriver _driver;
        private bool _disposed;

        public SeleniumEdgeSession(EdgeDriver driver)
        {
            _driver = driver;
        }

        public bool IsAlive
        {
            get
            {
                if (_disposed) return false;
                try
                {
                    _ = _driver.CurrentWindowHandle;
                    return true;
                }
                catch
                {
                    return false;
                }
            }
        }

        public void Navigate(string url) => _driver.Navigate().GoToUrl(url);

        public string GetCurrentUrl() => _driver.Url ?? string.Empty;

        public string GetPageSource()
        {
            try
            {
                return _driver.PageSource ?? string.Empty;
            }
            catch
            {
                return string.Empty;
            }
        }

        public string GetReadyState()
        {
            try
            {
                return _driver.ExecuteScript("return document.readyState")?.ToString() ?? string.Empty;
            }
            catch
            {
                return string.Empty;
            }
        }

        public string GetVisibleBodyText()
        {
            try
            {
                return _driver.ExecuteScript("return (document.body && (document.body.innerText || document.body.textContent)) || '';")?.ToString()
                    ?? string.Empty;
            }
            catch
            {
                return string.Empty;
            }
        }

        public object? ExecuteScript(string script, params object[] args)
            => _driver.ExecuteScript(script, args);

        public bool TryClickVisibleByXPaths(IEnumerable<string> xpaths)
        {
            foreach (var xpath in xpaths)
            {
                try
                {
                    var els = _driver.FindElements(By.XPath(xpath));
                    foreach (var el in els)
                    {
                        if (!el.Displayed) continue;
                        if (SafeClickElement(el))
                            return true;
                    }
                }
                catch
                {
                    // Try next candidate
                }
            }

            return false;
        }

        public bool TryDoubleClickVisibleByXPaths(IEnumerable<string> xpaths)
        {
            foreach (var xpath in xpaths)
            {
                try
                {
                    var els = _driver.FindElements(By.XPath(xpath));
                    foreach (var el in els)
                    {
                        if (!el.Displayed) continue;
                        try
                        {
                            _driver.ExecuteScript("arguments[0].scrollIntoView({block:'center', inline:'center'});", el);
                        }
                        catch
                        {
                            // ignore scroll issue
                        }

                        new Actions(_driver)
                            .MoveToElement(el)
                            .Pause(TimeSpan.FromMilliseconds(20))
                            .DoubleClick(el)
                            .Perform();
                        return true;
                    }
                }
                catch
                {
                    // Try next candidate
                }
            }

            return false;
        }

        public bool TryTypeVisibleByXPaths(IEnumerable<string> xpaths, string value)
        {
            foreach (var xpath in xpaths)
            {
                try
                {
                    var els = _driver.FindElements(By.XPath(xpath));
                    foreach (var el in els)
                    {
                        if (!el.Displayed) continue;
                        try
                        {
                            _driver.ExecuteScript("arguments[0].scrollIntoView({block:'center', inline:'center'});", el);
                        }
                        catch
                        {
                            // ignore
                        }

                        el.Click();
                        try
                        {
                            el.Clear();
                        }
                        catch
                        {
                            el.SendKeys(Keys.Control + "a");
                            el.SendKeys(Keys.Delete);
                        }

                        el.SendKeys(value);
                        return true;
                    }
                }
                catch
                {
                    // Try next candidate
                }
            }

            return false;
        }

        public bool IsAnyXPathVisible(IEnumerable<string> xpaths)
        {
            foreach (var xpath in xpaths)
            {
                try
                {
                    if (_driver.FindElements(By.XPath(xpath)).Any(e => e.Displayed))
                        return true;
                }
                catch
                {
                    // ignore stale/missing
                }
            }

            return false;
        }

        public bool TryFallbackTypeRfInput(string value)
        {
            const string xpath =
                "//input[not(@type='hidden') and not(@type='password') and not(@type='checkbox') and not(@type='radio') and not(@type='submit') and not(@type='button') and not(contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'search'))] | //textarea";

            try
            {
                var els = _driver.FindElements(By.XPath(xpath));
                foreach (var el in els)
                {
                    if (!el.Displayed || !el.Enabled) continue;

                    try
                    {
                        _driver.ExecuteScript("arguments[0].scrollIntoView({block:'center', inline:'center'});", el);
                    }
                    catch
                    {
                        // ignore
                    }

                    el.Click();
                    el.SendKeys(Keys.Control + "a");
                    el.SendKeys(Keys.Delete);
                    el.SendKeys(value);

                    var current = (el.GetAttribute("value") ?? string.Empty).Trim();
                    if (current == value.Trim())
                        return true;

                    // Secondary JS property setter fallback
                    _driver.ExecuteScript("""
                        const el = arguments[0];
                        const value = String(arguments[1] ?? '');
                        el.focus();
                        const inputSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
                        const textAreaSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
                        const setter = el.tagName === 'TEXTAREA' ? textAreaSetter : inputSetter;
                        if (setter) setter.call(el, value); else el.value = value;
                        el.dispatchEvent(new Event('input', {bubbles:true}));
                        el.dispatchEvent(new Event('change', {bubbles:true}));
                        """, el, value);

                    if (((el.GetAttribute("value") ?? string.Empty).Trim()) == value.Trim())
                        return true;
                }
            }
            catch
            {
                // ignore
            }

            return false;
        }

        public bool TryFallbackClickRfSubmit()
        {
            foreach (var xpath in KorberSelectors.RfSubmitButtonXPaths)
            {
                try
                {
                    var els = _driver.FindElements(By.XPath(xpath));
                    foreach (var el in els)
                    {
                        if (!el.Displayed || !el.Enabled) continue;
                        var inAppBar = Convert.ToBoolean(
                            _driver.ExecuteScript("return !!arguments[0].closest('.app-bar,.action-group,header');", el));
                        if (inAppBar) continue;

                        if (SafeClickElement(el))
                            return true;
                    }
                }
                catch
                {
                    // ignore
                }
            }

            return false;
        }

        public void SendEnterKeyToActiveElement()
        {
            _driver.SwitchTo().ActiveElement().SendKeys(Keys.Enter);
        }

        public void SendF1Key()
        {
            new Actions(_driver).SendKeys(Keys.F1).Perform();
        }

        public void Quit()
        {
            if (_disposed) return;
            _disposed = true;
            try
            {
                _driver.Quit();
            }
            catch
            {
                // ignore cleanup errors
            }
        }

        public void Dispose() => Quit();

        private bool SafeClickElement(IWebElement element)
        {
            try
            {
                _driver.ExecuteScript("arguments[0].scrollIntoView({block:'center', inline:'center'});", element);
            }
            catch
            {
                // ignore
            }

            try
            {
                element.Click();
                return true;
            }
            catch (StaleElementReferenceException)
            {
                return false;
            }
            catch
            {
                try
                {
                    _driver.ExecuteScript("arguments[0].click();", element);
                    return true;
                }
                catch
                {
                    try
                    {
                        new Actions(_driver)
                            .MoveToElement(element)
                            .Pause(TimeSpan.FromMilliseconds(50))
                            .Click()
                            .Perform();
                        return true;
                    }
                    catch
                    {
                        return false;
                    }
                }
            }
        }
    }
}
