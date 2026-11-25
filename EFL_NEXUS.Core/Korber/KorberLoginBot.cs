using System.IO;
using EflNexus.Core.Infrastructure;
using OpenQA.Selenium;
using OpenQA.Selenium.Chrome;
using OpenQA.Selenium.Support.UI;

namespace EflNexus.Core.Korber;

/// <summary>
/// Manages Chrome profile isolation, .env/config credential resolution, and initial Körber login.
/// Matches korber_login_bot.py 1:1.
/// </summary>
public static class KorberLoginBot
{
    public const string DefaultKorberUrl = "https://lopwaprodweb.koerbercloud.com/core/Default.html";

    private static Dictionary<string, string> ReadDotEnv()
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var envPath = AppPaths.ResolveResourcePath(".env");
        if (!File.Exists(envPath))
            return result;

        try
        {
            foreach (var raw in File.ReadAllLines(envPath))
            {
                var line = raw.Trim();
                if (string.IsNullOrEmpty(line) || line.StartsWith('#'))
                    continue;
                var idx = line.IndexOf('=');
                if (idx <= 0) continue;
                var key = line[..idx].Trim();
                var val = line[(idx + 1)..].Trim();
                if ((val.StartsWith('"') && val.EndsWith('"') && val.Length >= 2) ||
                    (val.StartsWith('\'') && val.EndsWith('\'') && val.Length >= 2))
                {
                    val = val[1..^1];
                }
                result[key] = val;
            }
        }
        catch { }
        return result;
    }

    public static KorberCredentials GetCredentials()
    {
        var store = new ConfigStore();
        var dotenv = ReadDotEnv();

        string user = store.Get("korber_user").Trim();
        string pwd = store.Get("korber_pass");
        string url = store.Get("korber_url").Trim();

        if (string.IsNullOrEmpty(user))
            user = (Environment.GetEnvironmentVariable("KORBER_USER") ?? "").Trim();
        if (string.IsNullOrEmpty(pwd))
            pwd = Environment.GetEnvironmentVariable("KORBER_PASS") ?? "";
        if (string.IsNullOrEmpty(url))
            url = (Environment.GetEnvironmentVariable("KORBER_URL") ?? "").Trim();

        if (string.IsNullOrEmpty(user) && dotenv.TryGetValue("KORBER_USER", out var du))
            user = du.Trim();
        if (string.IsNullOrEmpty(pwd) && dotenv.TryGetValue("KORBER_PASS", out var dp))
            pwd = dp;
        if (string.IsNullOrEmpty(url) && dotenv.TryGetValue("KORBER_URL", out var dl))
            url = dl.Trim();

        if (string.IsNullOrEmpty(url))
            url = DefaultKorberUrl;

        return new KorberCredentials(url, user, pwd);
    }

    public static void SaveCredentials(string username, string password, string? url = null)
    {
        var store = new ConfigStore();
        var targetUrl = !string.IsNullOrWhiteSpace(url)
            ? url.Trim()
            : (string.IsNullOrWhiteSpace(store.Get("korber_url")) ? DefaultKorberUrl : store.Get("korber_url").Trim());

        store.Save(
            korberUser: username.Trim(),
            korberPass: password ?? "",
            korberUrl: targetUrl);

        Environment.SetEnvironmentVariable("KORBER_USER", username.Trim());
        Environment.SetEnvironmentVariable("KORBER_PASS", password ?? "");
        Environment.SetEnvironmentVariable("KORBER_URL", targetUrl);
    }

    public static IWebDriver OpenNewBrowser(bool headless = false, string profileName = "default")
    {
        var options = new ChromeOptions();
        if (headless)
            options.AddArgument("--headless=new");
        options.AddArgument("--start-maximized");

        var safeChars = (profileName ?? "default")
            .Where(c => char.IsLetterOrDigit(c) || c == '-' || c == '_')
            .ToArray();
        var safeName = safeChars.Length > 0 ? new string(safeChars) : "default";

        var profileDir = Path.Combine(AppPaths.AppDir, $"chrome_automation_profile_{safeName}");
        Directory.CreateDirectory(profileDir);

        foreach (var lockName in new[] { "SingletonLock", "SingletonCookie", "SingletonSocket" })
        {
            var lockPath = Path.Combine(profileDir, lockName);
            try
            {
                if (File.Exists(lockPath))
                    File.Delete(lockPath);
            }
            catch { }
        }

        options.AddArgument($"--user-data-dir={profileDir}");
        options.AddArgument("--profile-directory=Default");

        try
        {
            var home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            var wdmLockDir = Path.Combine(home, ".wdm");
            if (Directory.Exists(wdmLockDir))
            {
                foreach (var lockFile in Directory.GetFiles(wdmLockDir, ".wdm-lock*"))
                {
                    try { File.Delete(lockFile); } catch { }
                }
            }
        }
        catch { }

        var service = ChromeDriverService.CreateDefaultService();
        service.HideCommandPromptWindow = true;
        return new ChromeDriver(service, options);
    }

    public static void Login(IWebDriver driver, string? username = null, string? password = null, string? url = null)
    {
        var creds = GetCredentials();
        var targetUrl = !string.IsNullOrWhiteSpace(url) ? url.Trim() : creds.KorberUrl;
        if (string.IsNullOrWhiteSpace(targetUrl))
            targetUrl = DefaultKorberUrl;
        var targetUser = !string.IsNullOrWhiteSpace(username) ? username.Trim() : creds.Username;
        var targetPwd = !string.IsNullOrEmpty(password) ? password : creds.Password;

        if (string.IsNullOrEmpty(targetUser) || string.IsNullOrEmpty(targetPwd))
        {
            throw new InvalidOperationException(
                "Körber Username or Password is not configured.\n" +
                "Please go to Settings (⚙) in EFL NEXUS to enter and save your login credentials.");
        }

        var wait = new WebDriverWait(driver, TimeSpan.FromSeconds(20));
        driver.Navigate().GoToUrl(targetUrl);

        IWebElement usernameField;
        try
        {
            usernameField = wait.Until(d =>
            {
                var els = d.FindElements(By.CssSelector("hj-textbox[data-hj-test-id='username'] input"));
                return els.Count > 0 ? els[0] : null;
            })!;
        }
        catch (WebDriverTimeoutException)
        {
            usernameField = wait.Until(d =>
            {
                var els = d.FindElements(By.CssSelector("input.k-textbox[placeholder='User Name']"));
                return els.Count > 0 ? els[0] : null;
            })!;
        }

        usernameField.Clear();
        usernameField.SendKeys(targetUser);

        IWebElement passwordField;
        try
        {
            passwordField = driver.FindElement(By.CssSelector("hj-password-textbox[data-hj-test-id='password'] input"));
        }
        catch (NoSuchElementException)
        {
            passwordField = driver.FindElement(By.CssSelector("input[type='password']"));
        }

        passwordField.Clear();
        passwordField.SendKeys(targetPwd);

        IWebElement loginButton;
        try
        {
            loginButton = driver.FindElement(By.CssSelector("hj-button[data-hj-test-id='actionButton'] button"));
        }
        catch (NoSuchElementException)
        {
            loginButton = driver.FindElement(By.XPath("//hj-button//span[text()='Login']/ancestor::button"));
        }

        loginButton.Click();
        Thread.Sleep(3000);
    }
}
