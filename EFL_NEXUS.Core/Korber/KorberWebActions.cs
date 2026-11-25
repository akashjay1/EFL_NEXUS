using OpenQA.Selenium;
using OpenQA.Selenium.Support.UI;

namespace EflNexus.Core.Korber;

/// <summary>
/// Exact 1:1 Selenium DOM / Kendo / Knockout interactions ported from korber_tool.py.
/// </summary>
public static class KorberWebActions
{
    public static readonly string[] CreateGrnSystemErrorSnippets =
    [
        "Quantity discrepancy found",
        "Cannot generate GRN. Some LPs are still in fork location"
    ];

    public static void PlayCompletionBeep()
    {
        try
        {
            Console.Beep(1000, 1000);
        }
        catch
        {
            try { Console.Write("\a"); } catch { }
        }
    }

    public static void PlayErrorBeep()
    {
        try
        {
            Console.Beep(400, 250);
            Thread.Sleep(150);
            Console.Beep(400, 250);
        }
        catch
        {
            try { Console.Write("\a\a"); } catch { }
        }
    }

    public static bool IsRetryableException(Exception ex)
        => ex is WebDriverTimeoutException
            or StaleElementReferenceException
            or ElementClickInterceptedException
            or ElementNotInteractableException
            or NoSuchElementException
            or JavaScriptException;

    private static IWebElement? FindVisible(IWebDriver d, By by)
    {
        try
        {
            var el = d.FindElement(by);
            return el.Displayed ? el : null;
        }
        catch (NoSuchElementException) { return null; }
        catch (StaleElementReferenceException) { return null; }
    }

    private static IWebElement? FindClickable(IWebDriver d, By by)
    {
        try
        {
            var el = d.FindElement(by);
            return el.Displayed && el.Enabled ? el : null;
        }
        catch (NoSuchElementException) { return null; }
        catch (StaleElementReferenceException) { return null; }
    }

    private static IWebElement? FindPresent(IWebDriver d, By by)
    {
        try { return d.FindElement(by); }
        catch (NoSuchElementException) { return null; }
        catch (StaleElementReferenceException) { return null; }
    }

    private static bool IsStale(IWebElement el)
    {
        try
        {
            _ = el.Enabled;
            return false;
        }
        catch (StaleElementReferenceException)
        {
            return true;
        }
    }

    private static void JsClick(IWebDriver driver, IWebElement el)
        => ((IJavaScriptExecutor)driver).ExecuteScript("arguments[0].click();", el);

    public static void OpenNewTabAndEnsureLogin(IWebDriver driver)
    {
        ((IJavaScriptExecutor)driver).ExecuteScript("window.open('about:blank', '_blank');");
        var handles = driver.WindowHandles;
        driver.SwitchTo().Window(handles[^1]);
        var url = KorberLoginBot.GetCredentials().KorberUrl;
        driver.Navigate().GoToUrl(url);

        var shortWait = new WebDriverWait(driver, TimeSpan.FromSeconds(5));
        try
        {
            shortWait.Until(d => FindPresent(d, By.CssSelector("hj-textbox[data-hj-test-id='username'] input")) is not null);
            KorberLoginBot.Login(driver);
        }
        catch (WebDriverTimeoutException)
        {
            // Already authenticated via shared cookies
        }
    }

    public static void WaitForLoadingToDisappear(IWebDriver driver, int timeoutSeconds = 30)
    {
        var quickWait = new WebDriverWait(driver, TimeSpan.FromMilliseconds(500));
        IWebElement? spinner;
        try
        {
            spinner = quickWait.Until(d => FindPresent(d, By.CssSelector("div[data-hj-test-id='processing-dialog-container']")));
        }
        catch (WebDriverTimeoutException)
        {
            return;
        }

        if (spinner is null)
            return;

        var longWait = new WebDriverWait(driver, TimeSpan.FromSeconds(timeoutSeconds));
        try
        {
            longWait.Until(_ =>
            {
                try { return !spinner.Displayed; }
                catch (StaleElementReferenceException) { return true; }
                catch (NoSuchElementException) { return true; }
            });
        }
        catch (WebDriverTimeoutException)
        {
            try
            {
                var stillThere = driver.FindElement(By.CssSelector("div[data-hj-test-id='processing-dialog-container']"));
                if (stillThere.Displayed)
                    throw;
            }
            catch (NoSuchElementException) { }
            catch (StaleElementReferenceException) { }
        }
    }

    public static void OpenMenuAndSearch(IWebDriver driver, string searchCode, string resultText)
    {
        var wait = new WebDriverWait(driver, TimeSpan.FromSeconds(20));
        var menuToggle = wait.Until(d => FindClickable(d, By.Id("menuButtonToggle")))!;
        menuToggle.Click();

        var searchBox = wait.Until(d => FindVisible(d, By.CssSelector("input[data-hj-test-id='menuSearchTextBox']")))!;
        Thread.Sleep(500);

        try { searchBox.Click(); }
        catch { JsClick(driver, searchBox); }

        searchBox.Clear();
        searchBox.SendKeys(searchCode);

        var menuItem = wait.Until(d => FindVisible(d, By.XPath($"//span[@class='title' and text()='{resultText}']/ancestor::a")))!;
        try { menuItem.Click(); }
        catch { JsClick(driver, menuItem); }
    }

    public static void NavigateToGdn(IWebDriver driver)
        => OpenMenuAndSearch(driver, "1703", "Goods Delivery Note");

    public static void NavigateToGrn(IWebDriver driver)
        => OpenMenuAndSearch(driver, "1712", "Print GRN");

    public static void SetKendoDropdownValue(IWebDriver driver, IWebElement selectElement, string code)
    {
        ((IJavaScriptExecutor)driver).ExecuteScript(
            """
            var $select = jQuery(arguments[0]);
            var widget = $select.data('kendoDropDownList');
            if (!widget) { throw 'Kendo widget not initialized on this element'; }

            var rawCode = arguments[1];
            var code = (rawCode ? String(rawCode) : '').trim().toUpperCase();
            var match = null;
            $select.find('option').each(function() {
                var v = (this.value ? String(this.value) : '').trim();
                var vUpper = v.toUpperCase();
                if (vUpper === code) {
                    match = v;
                    return false;
                }
                if (vUpper.indexOf(code) === 0) {
                    var next = vUpper.charAt(code.length);
                    if (next === '' || next === ' ' || next === '-') {
                        match = v;
                        return false;
                    }
                }
            });
            if (match === null) {
                throw 'No matching option found for code: ' + rawCode;
            }

            widget.value(match);
            widget.trigger('change');
            """,
            selectElement,
            code);
    }

    public static IWebElement GetFieldCell(IWebDriver driver, string labelText)
    {
        var wait = new WebDriverWait(driver, TimeSpan.FromSeconds(20));
        var labelLower = labelText.ToLowerInvariant();
        var xpath =
            "//hj-field-cell[.//hj-label//span[normalize-space(translate(translate(" +
            "text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), " +
            "'*', ''))" +
            $"='{labelLower}']]";

        return wait.Until(d =>
        {
            foreach (var cell in d.FindElements(By.XPath(xpath)))
            {
                try
                {
                    if (cell.Displayed)
                        return cell;
                }
                catch (StaleElementReferenceException) { }
            }
            return null;
        })!;
    }

    public static string CaptureGdnNumber(IWebDriver driver)
    {
        var wait = new WebDriverWait(driver, TimeSpan.FromSeconds(15));
        var gdnCell = GetFieldCell(driver, "GDN");
        var gdnInput = gdnCell.FindElement(By.CssSelector("input.k-textbox"));
        return wait.Until(_ =>
        {
            var v = (gdnInput.GetAttribute("value") ?? "").Trim();
            return string.IsNullOrEmpty(v) ? null : v;
        })!;
    }

    public static void FillGdnForm(IWebDriver driver, string warehouseId, string clientCode, string gatePassNumber)
    {
        var warehouseCell = GetFieldCell(driver, "Warehouse ID");
        var warehouseSelect = warehouseCell.FindElement(By.CssSelector("select[data-role='dropdownlist']"));
        SetKendoDropdownValue(driver, warehouseSelect, warehouseId);

        var clientCell = GetFieldCell(driver, "Client Code");
        var clientSelect = clientCell.FindElement(By.CssSelector("select[data-role='dropdownlist']"));
        SetKendoDropdownValue(driver, clientSelect, clientCode);

        var gatepassCell = GetFieldCell(driver, "Gate Pass Number");
        var gatepassInput = gatepassCell.FindElement(By.CssSelector("input.k-textbox"));
        gatepassInput.Clear();
        gatepassInput.SendKeys(gatePassNumber);
    }

    public static void FillGrnForm(IWebDriver driver, string warehouseId, string gatePassNumber)
    {
        var warehouseCell = GetFieldCell(driver, "Warehouse ID");
        var warehouseSelect = warehouseCell.FindElement(By.CssSelector("select[data-role='dropdownlist']"));
        SetKendoDropdownValue(driver, warehouseSelect, warehouseId);

        var gatepassCell = GetFieldCell(driver, "Gate Pass ID");
        var gatepassInput = gatepassCell.FindElement(By.CssSelector("input.k-textbox"));
        gatepassInput.Clear();
        gatepassInput.SendKeys(gatePassNumber);
    }

    public static void SetGridPageSize(IWebDriver driver, string size)
    {
        ((IJavaScriptExecutor)driver).ExecuteScript(
            """
            var target = null;
            var expected = ['5', '10', '15', '20', '25', '50', '100'];
            document.querySelectorAll("select[data-role='dropdownlist']").forEach(function(sel) {
                var values = Array.prototype.map.call(sel.options, function(o) { return o.value; });
                if (values.length === expected.length && values.every(function(v, i) { return v === expected[i]; })) {
                    target = sel;
                }
            });
            if (!target) { throw 'Page size dropdown not found (expected options 5/10/15/20/25/50/100)'; }

            var widget = jQuery(target).data('kendoDropDownList');
            if (!widget) { throw 'Kendo widget not initialized on page size dropdown'; }
            widget.value(arguments[0]);
            widget.trigger('change');
            """,
            size);
    }

    public static void SetPageSize(IWebDriver driver, string size)
    {
        try
        {
            var wait = new WebDriverWait(driver, TimeSpan.FromSeconds(10));
            const string xpath =
                "//select[@data-role='dropdownlist']" +
                "[option[@value='5'] and option[@value='10'] and option[@value='100']]";
            var pageSizeSelect = wait.Until(d => FindPresent(d, By.XPath(xpath)))!;
            SetKendoDropdownValue(driver, pageSizeSelect, size);
            return;
        }
        catch { }

        try
        {
            SetGridPageSize(driver, size);
            return;
        }
        catch { }

        ((IJavaScriptExecutor)driver).ExecuteScript(
            """
            var target = null;
            document.querySelectorAll("select[data-role='dropdownlist']").forEach(function(sel) {
                var values = Array.prototype.map.call(sel.options, function(o) { return o.value; });
                if (values.indexOf('100') !== -1) {
                    target = sel;
                }
            });
            if (!target) { throw 'Page size dropdown not found (no select with a 100 option)'; }
            var widget = jQuery(target).data('kendoDropDownList');
            if (!widget) { throw 'Kendo widget not initialized on page size dropdown'; }
            widget.value(arguments[0]);
            widget.trigger('change');
            """,
            size);
    }

    public static IWebElement ClickQueryButton(IWebDriver driver)
    {
        var wait = new WebDriverWait(driver, TimeSpan.FromSeconds(20));
        var queryLi = wait.Until(d => FindPresent(d, By.CssSelector("li[data-hj-test-id='query-button']")))!;

        wait.Until(_ =>
        {
            var cls = queryLi.GetAttribute("class") ?? "";
            return !cls.Split(' ', StringSplitOptions.RemoveEmptyEntries).Contains("disabled");
        });

        var queryLink = queryLi.FindElement(By.CssSelector("a"));
        try { JsClick(driver, queryLink); }
        catch { queryLink.Click(); }

        return queryLi;
    }

    public static IWebElement ClickSelectAllCheckbox(IWebDriver driver)
    {
        var wait = new WebDriverWait(driver, TimeSpan.FromSeconds(20));
        var iconSpan = wait.Until(d => FindPresent(d, By.CssSelector("span.select-all-icon")))!;

        IWebElement targetTh;
        try { targetTh = iconSpan.FindElement(By.XPath("./ancestor::th[1]")); }
        catch { targetTh = iconSpan; }

        try { JsClick(driver, targetTh); }
        catch
        {
            try { targetTh.Click(); }
            catch { JsClick(driver, iconSpan); }
        }
        return targetTh;
    }

    public static IWebElement ClickCreateGrnAtGatepass(IWebDriver driver)
    {
        var wait = new WebDriverWait(driver, TimeSpan.FromSeconds(20));
        var grnLi = wait.Until(d => FindPresent(d, By.XPath("//span[normalize-space(text())='Create GRN @ GatePass']/ancestor::li[1]")))!;

        wait.Until(_ =>
        {
            var cls = grnLi.GetAttribute("class") ?? "";
            return !cls.Split(' ', StringSplitOptions.RemoveEmptyEntries).Contains("disabled");
        });

        var grnLink = grnLi.FindElement(By.CssSelector("a"));
        try { JsClick(driver, grnLink); }
        catch { grnLink.Click(); }

        return grnLink;
    }

    public static IWebElement ClickGrnDetailsButton(IWebDriver driver, int timeoutSeconds = 10)
    {
        var wait = new WebDriverWait(driver, TimeSpan.FromSeconds(timeoutSeconds));
        IWebElement detailsLink;
        try
        {
            var detailsLi = wait.Until(d => FindPresent(d, By.XPath("//span[normalize-space(text())='GRN Details']/ancestor::li[1]")))!;
            wait.Until(_ =>
            {
                var cls = detailsLi.GetAttribute("class") ?? "";
                return !cls.Split(' ', StringSplitOptions.RemoveEmptyEntries).Contains("disabled");
            });
            detailsLink = detailsLi.FindElement(By.CssSelector("a"));
        }
        catch (WebDriverTimeoutException)
        {
            detailsLink = wait.Until(d => FindClickable(d, By.XPath("//span[normalize-space(text())='GRN Details']/ancestor::a")))!;
        }

        try { JsClick(driver, detailsLink); }
        catch { detailsLink.Click(); }

        return detailsLink;
    }

    public static bool IsGrnDetailsButtonAvailable(IWebDriver driver)
    {
        try
        {
            var detailsLi = driver.FindElement(By.XPath("//span[normalize-space(text())='GRN Details']/ancestor::li[1]"));
            var cls = detailsLi.GetAttribute("class") ?? "";
            return !cls.Split(' ', StringSplitOptions.RemoveEmptyEntries).Contains("disabled");
        }
        catch (NoSuchElementException) { }
        catch { return false; }

        try
        {
            driver.FindElement(By.XPath("//span[normalize-space(text())='GRN Details']/ancestor::a"));
            return true;
        }
        catch
        {
            return false;
        }
    }

    public static IWebElement ClickPrintGrnSku(IWebDriver driver)
    {
        var wait = new WebDriverWait(driver, TimeSpan.FromSeconds(20));
        var printLi = wait.Until(d => FindPresent(d, By.XPath("//span[normalize-space(text())='Print GRN - SKU']/ancestor::li[1]")))!;

        wait.Until(_ =>
        {
            var cls = printLi.GetAttribute("class") ?? "";
            return !cls.Split(' ', StringSplitOptions.RemoveEmptyEntries).Contains("disabled");
        });

        var printLink = printLi.FindElement(By.CssSelector("a"));
        try { JsClick(driver, printLink); }
        catch { printLink.Click(); }

        return printLink;
    }

    public static void WaitForReport(IWebDriver driver, string titleText, int timeoutSeconds = 30)
    {
        var wait = new WebDriverWait(driver, TimeSpan.FromSeconds(timeoutSeconds));

        var reportIframe = wait.Until(d =>
        {
            var frames = d.FindElements(By.XPath(
                "//iframe[contains(@src, 'ReportViewer') or contains(@src, 'Report') or contains(@id, 'report') or contains(@id, 'Report')]"))
                .Where(f =>
                {
                    try { return f.Displayed; }
                    catch { return false; }
                })
                .ToList();
            return frames.Count > 0 ? frames[^1] : null;
        })!;

        driver.SwitchTo().Frame(reportIframe);
        try
        {
            wait.Until(d => FindVisible(d, By.XPath($"//*[contains(normalize-space(text()), '{titleText}')]")) is not null);
        }
        finally
        {
            driver.SwitchTo().DefaultContent();
        }
    }

    public static void WaitForGrnReport(IWebDriver driver, int timeoutSeconds = 30)
        => WaitForReport(driver, "GOODS RECEIVED NOTE", timeoutSeconds);

    public static void WaitForGdnReport(IWebDriver driver, int timeoutSeconds = 30)
        => WaitForReport(driver, "DELIVERY NOTE", timeoutSeconds);

    public static void WaitForQueryResults(IWebDriver driver, IWebElement? oldQueryLi = null, int timeoutSeconds = 20)
    {
        var wait = new WebDriverWait(driver, TimeSpan.FromSeconds(timeoutSeconds));
        if (oldQueryLi is not null)
            wait.Until(_ => IsStale(oldQueryLi));

        wait.Until(d => FindPresent(d, By.XPath("//span[normalize-space(text())='Add GDN']/ancestor::a")) is not null);
    }

    public static IWebElement ClickAddGdn(IWebDriver driver)
    {
        var wait = new WebDriverWait(driver, TimeSpan.FromSeconds(20));
        var addGdnLink = wait.Until(d => FindClickable(d, By.XPath("//span[normalize-space(text())='Add GDN']/ancestor::a")))!;
        try { addGdnLink.Click(); }
        catch { JsClick(driver, addGdnLink); }
        return addGdnLink;
    }

    public static IWebElement ClickInsertButton(IWebDriver driver)
    {
        var wait = new WebDriverWait(driver, TimeSpan.FromSeconds(20));
        var insertLink = wait.Until(d => FindClickable(d, By.XPath("//span[normalize-space(text())='Insert']/ancestor::a")))!;

        wait.Until(_ =>
        {
            var cls = insertLink.GetAttribute("class") ?? "";
            return !cls.Split(' ', StringSplitOptions.RemoveEmptyEntries)
                .Any(c => c.Contains("disabled", StringComparison.OrdinalIgnoreCase));
        });

        try { JsClick(driver, insertLink); }
        catch { insertLink.Click(); }
        return insertLink;
    }

    public static void WaitForInsertResult(IWebDriver driver, IWebElement? oldInsertLink = null, int timeoutSeconds = 20)
    {
        var wait = new WebDriverWait(driver, TimeSpan.FromSeconds(timeoutSeconds));
        if (oldInsertLink is not null)
            wait.Until(_ => IsStale(oldInsertLink));
    }

    public static IWebElement ClickAddGdnDetail(IWebDriver driver)
    {
        var wait = new WebDriverWait(driver, TimeSpan.FromSeconds(20));
        var link = wait.Until(d => FindClickable(d, By.XPath("//span[normalize-space(text())='ADD GDN DETAIL']/ancestor::a")))!;
        try { link.Click(); }
        catch { JsClick(driver, link); }
        return link;
    }

    public static IWebElement ClickAddAllToGdn(IWebDriver driver)
    {
        var wait = new WebDriverWait(driver, TimeSpan.FromSeconds(20));
        var addAllLi = wait.Until(d => FindPresent(d, By.XPath("//span[normalize-space(text())='Add All to GDN']/ancestor::li[1]")))!;

        wait.Until(_ =>
        {
            var cls = addAllLi.GetAttribute("class") ?? "";
            return !cls.Split(' ', StringSplitOptions.RemoveEmptyEntries).Contains("disabled");
        });

        var link = addAllLi.FindElement(By.CssSelector("a"));
        try { JsClick(driver, link); }
        catch { link.Click(); }
        return link;
    }

    public static IWebElement ClickPrintGdnSku(IWebDriver driver)
    {
        var wait = new WebDriverWait(driver, TimeSpan.FromSeconds(20));
        var printLink = wait.Until(d =>
        {
            var candidates = d.FindElements(By.XPath("//span[normalize-space(text())='PRINT GDN - SKU']/ancestor::a[1]"));
            var visible = candidates.Where(l =>
            {
                try { return l.Displayed; }
                catch { return false; }
            }).ToList();
            return visible.Count >= 2 ? visible[1] : null;
        })!;

        try { JsClick(driver, printLink); }
        catch { printLink.Click(); }
        return printLink;
    }

    public static bool ClickOkIfPresent(IWebDriver driver, int timeoutSeconds = 8)
    {
        var shortWait = new WebDriverWait(driver, TimeSpan.FromSeconds(timeoutSeconds));
        IWebElement? okButton;
        try
        {
            okButton = shortWait.Until(d => FindVisible(d, By.XPath(
                "//button[contains(@class,'k-button')][normalize-space(.)='OK' or .//span[normalize-space(text())='OK']] | " +
                "//a[contains(@class,'k-button')][normalize-space(.)='OK' or .//span[normalize-space(text())='OK']]")));
        }
        catch (WebDriverTimeoutException)
        {
            return false;
        }

        if (okButton is null)
            return false;

        try { shortWait.Until(_ => okButton.Enabled); } catch { }
        try { okButton.Click(); }
        catch { JsClick(driver, okButton); }
        return true;
    }

    public static bool CheckForQuantityDiscrepancyError(IWebDriver driver)
    {
        try
        {
            foreach (var snippet in CreateGrnSystemErrorSnippets)
            {
                var els = driver.FindElements(By.XPath($"//*[contains(text(), '{snippet}')]"));
                if (els.Any(el =>
                {
                    try { return el.Displayed; }
                    catch { return false; }
                }))
                {
                    return true;
                }
            }
        }
        catch
        {
            return false;
        }
        return false;
    }

    public static bool IsAddGdnDetailButtonAvailable(IWebDriver driver)
    {
        try
        {
            var el = driver.FindElement(By.XPath("//span[normalize-space(text())='ADD GDN DETAIL']/ancestor::a"));
            return el.Displayed;
        }
        catch
        {
            return false;
        }
    }

    public static void ClickRefreshPageButton(IWebDriver driver, int timeoutSeconds = 8)
    {
        var shortWait = new WebDriverWait(driver, TimeSpan.FromSeconds(timeoutSeconds));
        var refreshLi = shortWait.Until(d => FindPresent(d, By.CssSelector("li[data-hj-test-id='refresh-page-button']")))!;
        var refreshLink = refreshLi.FindElement(By.CssSelector("a"));
        try { refreshLink.Click(); }
        catch (Exception ex) when (ex is ElementClickInterceptedException or ElementNotInteractableException)
        {
            JsClick(driver, refreshLink);
        }
    }

    public static bool ClickSendGrnButton(IWebDriver driver, int timeoutSeconds = 8)
    {
        var shortWait = new WebDriverWait(driver, TimeSpan.FromSeconds(timeoutSeconds));
        IWebElement? sendGrnLi;
        try
        {
            sendGrnLi = shortWait.Until(d => FindPresent(d, By.XPath("//span[normalize-space(text())='Send GRN']/ancestor::li[1]")));
        }
        catch (WebDriverTimeoutException)
        {
            return false;
        }

        if (sendGrnLi is null)
            return false;

        shortWait.Until(_ =>
        {
            var cls = sendGrnLi.GetAttribute("class") ?? "";
            return !cls.Split(' ', StringSplitOptions.RemoveEmptyEntries).Contains("disabled");
        });

        var link = sendGrnLi.FindElement(By.CssSelector("a"));
        try { link.Click(); }
        catch (Exception ex) when (ex is ElementClickInterceptedException or ElementNotInteractableException)
        {
            JsClick(driver, link);
        }
        catch
        {
            // Navigation invalidated element after click fired
        }
        return true;
    }

    public static IWebElement ClickSendButton(IWebDriver driver)
    {
        var wait = new WebDriverWait(driver, TimeSpan.FromSeconds(20));
        var sendLink = wait.Until(d => FindClickable(d, By.XPath("//a[.//span[normalize-space(text())='Send'] or normalize-space(.)='Send']")))!;
        try { sendLink.Click(); }
        catch { JsClick(driver, sendLink); }
        return sendLink;
    }

    public static IWebElement ClickBackButton(IWebDriver driver)
    {
        var wait = new WebDriverWait(driver, TimeSpan.FromSeconds(20));
        var backLink = wait.Until(d => FindPresent(d, By.CssSelector("a[data-hj-test-id='active-thread-previous-button']")))!;

        wait.Until(_ =>
        {
            var cls = backLink.GetAttribute("class") ?? "";
            return !cls.Split(' ', StringSplitOptions.RemoveEmptyEntries).Contains("disabled");
        });

        try { backLink.Click(); }
        catch (Exception ex) when (ex is ElementClickInterceptedException or ElementNotInteractableException)
        {
            JsClick(driver, backLink);
        }
        catch
        {
            // Assume navigation already started (prevents triple-click bug)
        }
        return backLink;
    }

    public static IWebElement ClickForwardButton(IWebDriver driver)
    {
        var wait = new WebDriverWait(driver, TimeSpan.FromSeconds(20));
        var forwardLink = wait.Until(d => FindPresent(d, By.CssSelector("a[data-hj-test-id='active-thread-next-button']")))!;

        wait.Until(_ =>
        {
            var cls = forwardLink.GetAttribute("class") ?? "";
            return !cls.Split(' ', StringSplitOptions.RemoveEmptyEntries).Contains("disabled");
        });

        try { forwardLink.Click(); }
        catch (Exception ex) when (ex is ElementClickInterceptedException or ElementNotInteractableException)
        {
            JsClick(driver, forwardLink);
        }
        catch
        {
        }
        return forwardLink;
    }

    public static IWebElement ClickGdnNumberLink(IWebDriver driver, string gdnNumber)
    {
        var wait = new WebDriverWait(driver, TimeSpan.FromSeconds(20));
        var gdnLink = wait.Until(d => FindClickable(d, By.XPath($"//span[normalize-space(text())='{gdnNumber}']/ancestor::a")))!;
        try { gdnLink.Click(); }
        catch { JsClick(driver, gdnLink); }
        return gdnLink;
    }

    public static void WaitForAddGdnPage(IWebDriver driver, IWebElement? oldAddGdnLink = null, int timeoutSeconds = 20)
    {
        var wait = new WebDriverWait(driver, TimeSpan.FromSeconds(timeoutSeconds));
        if (oldAddGdnLink is not null)
            wait.Until(_ => IsStale(oldAddGdnLink));

        const string xpath =
            "//hj-field-cell[.//hj-label//span[" +
            "translate(normalize-space(text()), " +
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')" +
            "='warehouse id']]";

        wait.Until(d =>
        {
            foreach (var cell in d.FindElements(By.XPath(xpath)))
            {
                try
                {
                    if (cell.Displayed)
                        return cell;
                }
                catch { }
            }
            return null;
        });
    }

    public static void FillWarehouseId(IWebDriver driver, string warehouseId)
    {
        var cell = GetFieldCell(driver, "Warehouse ID");
        var sel = cell.FindElement(By.CssSelector("select[data-role='dropdownlist']"));
        SetKendoDropdownValue(driver, sel, warehouseId);
    }

    public static void FillClientCode(IWebDriver driver, string clientCode)
    {
        var cell = GetFieldCell(driver, "Client Code");
        var sel = cell.FindElement(By.CssSelector("select[data-role='dropdownlist']"));
        SetKendoDropdownValue(driver, sel, clientCode);
    }

    public static void FillGatePassNumber(IWebDriver driver, string gatePassNumber)
    {
        var cell = GetFieldCell(driver, "Gate Pass Number");
        var input = cell.FindElement(By.CssSelector("input.k-textbox"));
        input.Clear();
        input.SendKeys(gatePassNumber);
    }

    public static void FillDeliveryLocation(IWebDriver driver, string deliveryLocation)
        => FillValidatedDetailTextbox(driver, "Delivery To", deliveryLocation);

    public static void FillSealNumber(IWebDriver driver, string sealNumber)
        => FillValidatedDetailTextbox(driver, "Seal No", sealNumber);

    private static void FillValidatedDetailTextbox(IWebDriver driver, string labelText, string rawValue)
    {
        var val = (rawValue ?? "").Trim();
        if (string.IsNullOrEmpty(val) || val == "-")
            val = "N/A";

        var wait = new WebDriverWait(driver, TimeSpan.FromSeconds(20));
        var cell = GetFieldCell(driver, labelText);

        var input = wait.Until(_ =>
        {
            var el = cell.FindElement(By.CssSelector("input.k-textbox"));
            return el.Displayed && el.Enabled ? el : null;
        })!;

        void TypeAndBlur()
        {
            input.Clear();
            input.SendKeys(val);
            input.SendKeys(OpenQA.Selenium.Keys.Tab);
        }

        TypeAndBlur();
        Thread.Sleep(500);
        var current = (input.GetAttribute("value") ?? "").Trim();
        if (!string.Equals(current, val, StringComparison.Ordinal))
        {
            TypeAndBlur();
            Thread.Sleep(500);
            current = (input.GetAttribute("value") ?? "").Trim();
            if (!string.Equals(current, val, StringComparison.Ordinal))
            {
                throw new InvalidOperationException(
                    $"{labelText} field shows '{current}' after typing '{val}' twice — something on the page is overwriting it.");
            }
        }
    }
}
