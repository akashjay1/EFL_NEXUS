namespace KorberAuditShip.Services;

/// <summary>
/// URLs, timeouts, recognized RF text aliases, XPaths, and DOM JavaScript snippets
/// matching KORBER AuditShip's Körber One Mobile Web automation layer.
/// </summary>
public static class KorberSelectors
{
    public const string KorberUrl = "https://lopwaprodweb.koerbercloud.com/core/Default.html";
    public const double VisualScale = 0.85;
    public const int EdgeDebugPort = 9222;
    public const string EdgeProfileFolderName = "Edge_LPAKASHM_Profile";
    public const int PollSleepMs = 30;
    public const int CriticalPopupWaitSeconds = 300;

    public static readonly string[] KnownErrorMessages =
    [
        "INVALID LOAD ID",
        "AUDIT COMPLETE",
        "LOAD ID NOT FOUND",
        "INVALID OPTION",
        "LOAD ALREADY AUDITED",
        "ALREADY AUDITED",
        "LOAD ID IS INVALID"
    ];

    public static readonly string[] OutboundSubmenuTexts =
    [
        "Order Pick",
        "Loading EFL",
        "Load Audit EFL",
        "Shipping EFL",
        "PO Packing"
    ];

    public static readonly string[] LoginUsernameXPaths =
    [
        "//input[@placeholder='User Name']",
        "//hj-textbox[@data-hj-test-id='username']//input",
        "//input[@type='text' and not(@placeholder='Tenant')]",
        "//input[not(@type='password')][1]"
    ];

    public static readonly string[] InitialLoginUsernameXPaths =
    [
        "//input[@type='text' and not(@placeholder='Tenant')]",
        "//input[not(@type='password')][1]"
    ];

    public static readonly string[] LoginPasswordXPaths =
    [
        "//input[@placeholder='Password']",
        "//hj-password-textbox[@data-hj-test-id='password']//input",
        "//input[@type='password']"
    ];

    public static readonly string[] FastLoginButtonXPaths =
    [
        "//button[.//span[normalize-space()='Login'] or normalize-space()='Login']",
        "//hj-button[@data-hj-test-id='actionButton']//button",
        "//*[normalize-space()='Login']"
    ];

    public static readonly string[] InitialLoginButtonXPaths =
    [
        "//button[normalize-space()='Login']",
        "//*[normalize-space()='Login']"
    ];

    public static readonly string[] HamburgerMenuXPaths =
    [
        "//button[@aria-label='menu']",
        "//button[contains(@class,'menu')]",
        "//button[contains(@class,'hamburger')]",
        "//i[contains(@class,'fa-bars')]",
        "//*[@title='Menu']",
        "//*[contains(@class,'menu')]"
    ];

    public static readonly string[] HamburgerOpenVerifyXPaths =
    [
        "//*[normalize-space()='Körber One Mobile']",
        "//*[contains(normalize-space(), 'Körber One Mobile')]",
        "//*[normalize-space()='Korber One Mobile']",
        "//*[contains(normalize-space(), 'Korber One Mobile')]",
        "//*[normalize-space()='Supply Chain Advantage']",
        "//*[contains(normalize-space(), 'Supply Chain Advantage')]"
    ];

    public static readonly string[] KorberMobileXPaths =
    [
        "//*[normalize-space()='Körber One Mobile']",
        "//*[normalize-space()='Korber One Mobile']",
        "//*[contains(normalize-space(), 'Körber One Mobile')]",
        "//*[contains(normalize-space(), 'Korber One Mobile')]"
    ];

    public static readonly string[] MobileLoginXPaths =
    [
        "//a[normalize-space()='Login']",
        "//span[normalize-space()='Login']",
        "//div[normalize-space()='Login']",
        "//button[normalize-space()='Login']",
        "//*[normalize-space()='Login']"
    ];

    public static readonly string[] ForkInputXPaths =
    [
        "//input[@type='text']",
        "//input[not(@type='password')]",
        "//textarea"
    ];

    public static readonly string[] ForkSubmitXPaths =
    [
        "//button[normalize-space()='Submit']",
        "//input[@type='submit']",
        "//*[normalize-space()='Submit']"
    ];

    public static readonly string[] DismissXPaths =
    [
        "//button[normalize-space()='Dismiss']",
        "//span[normalize-space()='Dismiss']",
        "//*[normalize-space()='Dismiss']"
    ];

    public static readonly string[] ErrorOkXPaths =
    [
        "//*[@role='dialog']//button[normalize-space()='OK' or normalize-space()='Ok']",
        "//*[contains(@class,'k-dialog') or contains(@class,'k-window') or contains(@class,'modal')]//button[normalize-space()='OK' or normalize-space()='Ok']",
        "//button[normalize-space()='OK' or normalize-space()='Ok']"
    ];

    public static readonly string[] GenericOkXPaths =
    [
        "//button[normalize-space()='Ok']",
        "//button[normalize-space()='OK']",
        "//span[normalize-space()='Ok']",
        "//span[normalize-space()='OK']",
        "//*[normalize-space()='Ok']",
        "//*[normalize-space()='OK']"
    ];

    public static readonly string[] RfSubmitButtonXPaths =
    [
        "//hj-button//button[.//span[normalize-space()='Submit'] or normalize-space()='Submit']",
        "//button[.//span[normalize-space()='Submit'] or normalize-space()='Submit']",
        "//input[@type='submit']"
    ];

    public static readonly string[] LoadIdAliases = ["LOAD ID", "Enter the Load ID"];
    public static readonly string[] ShippingLoadIdAliases = ["LOAD ID", "Enter the Load ID"];
    public static readonly string[] GatePassAliases = ["GATE PASS ID", "GATE PASS", "Gate Pass", "Gatepass"];
    public static readonly string[] LocationAliases = ["LOCATION", "Location", "Door Location", "LOC"];
    public static readonly string[] YesNoAliases = ["Y OR N", "Y or N", "Ready to print reports"];
    public static readonly string[] ConfirmAliases = ["ENTER:CONFIRM", "ENTER:Confirm", "Confirm", "ready to ship"];
    public static readonly string[] ShippingConfirmAliases = ["ENTER:CONFIRM", "ENTER:Confirm", "Confirm"];
    public static readonly string[] CarrierAliases = ["CARRIER NAME", "Carrier Name", "Carrier"];
    public static readonly string[] ProNumberAliases = ["PRO NUMBER", "Pro Number", "PRO #", "PRO"];
    public static readonly string[] SealNumberAliases = ["SEAL NUMBER", "Seal Number", "SEAL"];

    public static string XPathTextExact(string text) => $"//*[normalize-space()='{text}']";
    public static string XPathTextContains(string text) => $"//*[contains(normalize-space(), '{text}')]";

    public static string BuildVisualScaleScript(double scale)
    {
        var pct = Math.Round(100.0 / scale, 2).ToString(System.Globalization.CultureInfo.InvariantCulture);
        var scaleStr = scale.ToString(System.Globalization.CultureInfo.InvariantCulture);
        return $$"""
            (function() {
                const html = document.documentElement;
                const body = document.body;
                if (!html || !body) return;
                html.style.overflowX = 'auto';
                html.style.overflowY = 'auto';
                html.style.height = '100%';
                body.style.margin = '0';
                body.style.transformOrigin = 'top left';
                body.style.transform = 'scale({{scaleStr}})';
                body.style.width = '{{pct}}%';
                body.style.minHeight = '{{pct}}vh';
                body.style.overflow = 'visible';
            })();
            """;
    }

    public const string HamburgerFallbackPointsJs = """
        const points = [[30,120],[35,130],[40,140],[45,150],[50,160]];
        for (const [x, y] of points) {
            let el = document.elementFromPoint(x, y);
            if (!el) continue;
            let cur = el;
            for (let i = 0; i < 8 && cur; i++) {
                try { cur.click(); return true; } catch(e) {}
                cur = cur.parentElement;
            }
        }
        return false;
        """;

    public const string IsLoginScreenVisibleJs = """
        function norm(s) { return String(s || '').replace(/\s+/g, ' ').trim().toUpperCase(); }
        function visible(el) {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const st = window.getComputedStyle(el);
            return r.width > 20 && r.height > 15 && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
        }
        const bodyText = norm(document.body && (document.body.innerText || document.body.textContent));
        const userInput = Array.from(document.querySelectorAll("input[type='text'], input:not([type])"))
            .find(el => visible(el) && norm(el.getAttribute('placeholder')).includes('USER NAME'));
        const passwordInput = Array.from(document.querySelectorAll("input[type='password']"))
            .find(el => visible(el));
        const loginButton = Array.from(document.querySelectorAll('button, hj-button button'))
            .find(el => visible(el) && norm(el.innerText || el.textContent || el.value) === 'LOGIN');
        return !!(userInput && passwordInput && loginButton && (bodyText.includes('SIGN IN') || bodyText.includes('KORBER ONE') || bodyText.includes('KÖRBER ONE')));
        """;

    public const string ClickByVisibleTextJs = """
        const target = String(arguments[0] || '').trim().toUpperCase();
        function norm(s) { return String(s || '').replace(/\s+/g, ' ').trim().toUpperCase(); }
        function visible(el) {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const st = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none' && st.opacity !== '0';
        }
        function fireClick(el) {
            if (!el) return false;
            try { el.scrollIntoView({block:'center', inline:'center'}); } catch(e) {}
            const r = el.getBoundingClientRect();
            const x = Math.max(1, Math.min(window.innerWidth - 2, r.left + r.width / 2));
            const y = Math.max(1, Math.min(window.innerHeight - 2, r.top + r.height / 2));
            const opts = {bubbles:true, cancelable:true, view:window, clientX:x, clientY:y};
            for (const ev of ['mouseover','mousemove','mousedown','mouseup','click']) {
                try { el.dispatchEvent(new MouseEvent(ev, opts)); } catch(e) {}
            }
            try { el.click(); } catch(e) {}
            return true;
        }
        const all = Array.from(document.querySelectorAll('body *')).filter(visible);
        let textMatches = all.filter(el => norm(el.innerText) === target || norm(el.textContent) === target);
        if (!textMatches.length) {
            textMatches = all.filter(el => {
                const t = norm(el.innerText || el.textContent);
                return t === target || (t.includes(target) && t.length <= target.length + 30);
            });
        }
        let candidates = [];
        for (const el of textMatches) {
            let cur = el;
            for (let i = 0; i < 8 && cur; i++) {
                if (visible(cur)) candidates.push(cur);
                cur = cur.parentElement;
            }
        }
        candidates = [...new Set(candidates)];
        for (const el of candidates) { if (fireClick(el)) return true; }
        for (const el of textMatches) { if (fireClick(el)) return true; }
        return false;
        """;

    public const string ClickRfMenuButtonExactJs = """
        const target = String(arguments[0] || '').trim().toUpperCase();
        function norm(s) { return String(s || '').replace(/\s+/g, ' ').trim().toUpperCase(); }
        function visible(el) {
            if (!el) return false;
            const st = window.getComputedStyle(el);
            if (st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0') return false;
            const r = el.getBoundingClientRect();
            return r.width > 8 && r.height > 8;
        }
        function scrollAncestorsToElement(el) {
            try { el.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'}); } catch(e) {}
            let cur = el.parentElement;
            while (cur && cur !== document.body && cur !== document.documentElement) {
                try {
                    const st = window.getComputedStyle(cur);
                    const canScrollY = /(auto|scroll)/.test(st.overflowY) || cur.scrollHeight > cur.clientHeight + 5;
                    const canScrollX = /(auto|scroll)/.test(st.overflowX) || cur.scrollWidth > cur.clientWidth + 5;
                    if (canScrollY || canScrollX) {
                        const er = el.getBoundingClientRect();
                        const cr = cur.getBoundingClientRect();
                        if (canScrollY) cur.scrollTop += (er.top - cr.top) - (cr.height / 2) + (er.height / 2);
                        if (canScrollX) cur.scrollLeft += (er.left - cr.left) - (cr.width / 2) + (er.width / 2);
                    }
                } catch(e) {}
                cur = cur.parentElement;
            }
            try { window.scrollTo(0, Math.max(0, el.getBoundingClientRect().top + window.pageYOffset - 220)); } catch(e) {}
        }
        function fireClick(el) {
            if (!el) return false;
            scrollAncestorsToElement(el);
            let clickable = el.closest('hj-field-cell, .field-cell, .listButton, button, a, [role="button"]') || el;
            scrollAncestorsToElement(clickable);
            const r = clickable.getBoundingClientRect();
            const x = Math.max(2, Math.min(window.innerWidth - 2, Math.round(r.left + r.width / 2)));
            const y = Math.max(2, Math.min(window.innerHeight - 2, Math.round(r.top + r.height / 2)));
            const pointEl = document.elementFromPoint(x, y);
            const finalEl = (pointEl && (pointEl.closest('hj-field-cell, .field-cell, .listButton, button, a, [role="button"]') || pointEl)) || clickable;
            const opts = {bubbles: true, cancelable: true, view: window, clientX: x, clientY: y, button: 0, buttons: 1};
            for (const ev of ['pointerover','mouseover','mousemove','pointerdown','mousedown','pointerup','mouseup','click']) {
                try { finalEl.dispatchEvent(new MouseEvent(ev, opts)); } catch(e) {}
            }
            try { finalEl.click(); } catch(e) {}
            try { clickable.click(); } catch(e) {}
            return true;
        }
        const selectors = ['.listButton .noselect', '.listButton', 'hj-field-cell', '.field-cell', 'button', 'a', 'span', 'div'];
        let candidates = [];
        for (const selector of selectors) {
            for (const el of Array.from(document.querySelectorAll(selector))) {
                if (!visible(el)) continue;
                const text = norm(el.innerText || el.textContent || el.value);
                if (text === target) candidates.push(el);
            }
            if (candidates.length) break;
        }
        candidates = candidates.map(el => el.closest('hj-field-cell, .field-cell, .listButton, button, a, [role="button"]') || el);
        candidates = [...new Set(candidates)].filter(visible);
        candidates.sort((a, b) => {
            const aRf = a.closest('.inMotion') ? 0 : 1;
            const bRf = b.closest('.inMotion') ? 0 : 1;
            if (aRf !== bRf) return aRf - bRf;
            return a.getBoundingClientRect().top - b.getBoundingClientRect().top;
        });
        for (const el of candidates) {
            if (fireClick(el)) return true;
        }
        return false;
        """;

    public const string FindVisibleMainWarehouseJs = """
        const names = arguments[0] || [];
        function norm(s) { return String(s || '').replace(/\s+/g, ' ').trim().toUpperCase(); }
        function visible(el) {
            if (!el) return false;
            const st = window.getComputedStyle(el);
            if (st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0') return false;
            const r = el.getBoundingClientRect();
            return r.width > 8 && r.height > 8 && r.bottom >= 0 && r.right >= 0 && r.top <= window.innerHeight && r.left <= window.innerWidth;
        }
        const text = norm(document.body && (document.body.innerText || document.body.textContent));
        if (!text.includes('MAIN')) return '';
        const all = Array.from(document.querySelectorAll('body *')).filter(visible);
        for (const name of names) {
            if (all.some(el => norm(el.innerText || el.textContent || el.value) === name)) return name;
        }
        return '';
        """;

    public const string ClickWarehouseJs = """
        const target = String(arguments[0] || '').trim().toUpperCase();
        function norm(s) { return String(s || '').replace(/\s+/g, ' ').trim().toUpperCase(); }
        function visible(el) {
            if (!el) return false;
            const st = window.getComputedStyle(el);
            if (st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0') return false;
            const r = el.getBoundingClientRect();
            return r.width > 8 && r.height > 8;
        }
        function scrollAll(el) {
            try { el.scrollIntoView({block:'center', inline:'center', behavior:'instant'}); } catch(e) {}
            let cur = el.parentElement;
            while (cur && cur !== document.body && cur !== document.documentElement) {
                try {
                    if (cur.scrollHeight > cur.clientHeight + 5 || cur.scrollWidth > cur.clientWidth + 5) {
                        const er = el.getBoundingClientRect();
                        const cr = cur.getBoundingClientRect();
                        cur.scrollTop += (er.top - cr.top) - (cr.height / 2) + (er.height / 2);
                        cur.scrollLeft += (er.left - cr.left) - (cr.width / 2) + (er.width / 2);
                    }
                } catch(e) {}
                cur = cur.parentElement;
            }
        }
        function fire(el) {
            if (!el) return false;
            let clickable = el.closest('hj-field-cell, .field-cell, .listButton, button, a, [role="button"]') || el;
            scrollAll(clickable);
            const r = clickable.getBoundingClientRect();
            const x = Math.max(2, Math.min(window.innerWidth - 2, Math.round(r.left + r.width / 2)));
            const y = Math.max(2, Math.min(window.innerHeight - 2, Math.round(r.top + r.height / 2)));
            const hit = document.elementFromPoint(x, y) || clickable;
            const finalEl = hit.closest('hj-field-cell, .field-cell, .listButton, button, a, [role="button"]') || clickable;
            const opts = {bubbles:true, cancelable:true, view:window, clientX:x, clientY:y, button:0, buttons:1};
            for (const ev of ['pointerover','mouseover','mousemove','pointerdown','mousedown','pointerup','mouseup','click','dblclick']) {
                try { finalEl.dispatchEvent(new MouseEvent(ev, opts)); } catch(e) {}
            }
            try { finalEl.click(); } catch(e) {}
            try { clickable.click(); } catch(e) {}
            return true;
        }
        let candidates = Array.from(document.querySelectorAll('.inMotion .listButton, .inMotion .listButton .noselect, hj-field-cell, .field-cell, button, a, span, div'))
            .filter(visible)
            .filter(el => norm(el.innerText || el.textContent || el.value) === target);
        candidates = candidates.map(el => el.closest('hj-field-cell, .field-cell, .listButton, button, a, [role="button"]') || el);
        candidates = [...new Set(candidates)].filter(visible);
        candidates.sort((a,b) => {
            const ar = a.getBoundingClientRect();
            const br = b.getBoundingClientRect();
            const ain = a.closest('.inMotion') ? 0 : 1;
            const bin = b.closest('.inMotion') ? 0 : 1;
            if (ain !== bin) return ain - bin;
            return ar.top - br.top;
        });
        for (const c of candidates) {
            if (fire(c)) return true;
        }
        return false;
        """;

    public const string IsRfTextEntryVisibleJs = """
        function visible(el) {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const st = window.getComputedStyle(el);
            return r.width > 20 && r.height > 15 && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
        }
        const textEntry = document.querySelector('.textEntry');
        if (textEntry && visible(textEntry)) {
            const inp = textEntry.querySelector("input:not([type='hidden']):not([disabled]):not([readonly]), textarea:not([disabled]):not([readonly])");
            if (inp && visible(inp)) return true;
        }
        const submit = Array.from(document.querySelectorAll('hj-button button, button'))
            .find(b => visible(b) && String(b.innerText || b.textContent || '').trim().toUpperCase() === 'SUBMIT' && !b.closest('.app-bar,.action-group,header'));
        const input = Array.from(document.querySelectorAll("input:not([type='hidden']):not([type='password']):not([type='checkbox']):not([type='radio']):not([type='submit']):not([type='button']), textarea"))
            .find(el => visible(el) && !el.disabled && !el.readOnly && !String(el.placeholder || '').toUpperCase().includes('SEARCH'));
        return !!(submit && input);
        """;

    public const string GetVisibleErrorMessageJs = """
        function norm(s) { return String(s || '').replace(/\s+/g, ' ').trim(); }
        function visible(el) {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const st = window.getComputedStyle(el);
            return r.width > 20 && r.height > 15 && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
        }
        function hasOkButton(el) {
            return Array.from(el.querySelectorAll('button, hj-button button, a, span, div'))
                .some(b => visible(b) && norm(b.innerText || b.textContent || b.value).toUpperCase() === 'OK');
        }
        const known = [
            'INVALID LOAD ID',
            'AUDIT COMPLETE',
            'LOAD ID NOT FOUND',
            'INVALID OPTION',
            'LOAD ALREADY AUDITED',
            'ALREADY AUDITED',
            'LOAD ID IS INVALID'
        ];
        let containers = Array.from(document.querySelectorAll(
            '[role="dialog"], .k-dialog, .k-window, .k-window-content, .dx-popup-content, .modal, .modal-dialog, .modal-content, .popup, hj-error-dialog'
        )).filter(visible);
        const visibleBlocks = Array.from(document.querySelectorAll('body *')).filter(el => {
            if (!visible(el)) return false;
            const txt = norm(el.innerText || el.textContent);
            if (!txt.toUpperCase().includes('ERROR')) return false;
            if (!(txt.toUpperCase().includes('OK') || known.some(k => txt.toUpperCase().includes(k)))) return false;
            return true;
        });
        containers = containers.concat(visibleBlocks);
        const seen = new Set();
        for (const c of containers) {
            if (seen.has(c)) continue;
            seen.add(c);
            const txt = norm(c.innerText || c.textContent);
            const upper = txt.toUpperCase();
            if (!upper.includes('ERROR')) continue;
            if (!(hasOkButton(c) || known.some(k => upper.includes(k)))) continue;
            for (const k of known) {
                if (upper.includes(k)) return k;
            }
            continue;
        }
        return '';
        """;

    public const string IsLoadingIssueScreenJs = """
        function norm(s) { return String(s || '').replace(/\s+/g, ' ').trim().toUpperCase(); }
        function visible(el) {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const st = window.getComputedStyle(el);
            return r.width > 15 && r.height > 15 && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
        }
        const activePage = Array.from(document.querySelectorAll('[data-hj-test-id="active-workspace-page-container"], .hj-spaces-page-wrap, .inMotion, body'))
            .find(el => visible(el) && norm(el.innerText || el.textContent).includes('LOAD AUDIT EFL')) || document.body;
        const text = norm(activePage.innerText || activePage.textContent || '');
        if (!text.includes('LOAD AUDIT EFL')) return false;
        const promptWords = ['LOAD ID', 'GATE PASS', 'LOCATION', 'DOOR LOCATION', 'Y OR N', 'READY TO PRINT REPORTS', 'ENTER:CONFIRM', 'READY TO SHIP'];
        for (const w of promptWords) {
            if (text.includes(w)) return false;
        }
        const hasOrderLines = text.includes('ORDER:') && text.includes('ITEM:') && text.includes('ORDERED:') && text.includes('PICKED:') && text.includes('LOADED:');
        const hasConfirm = text.includes('CONFIRM');
        const hasInput = Array.from(activePage.querySelectorAll("input:not([type='hidden']):not([type='password']):not([type='checkbox']):not([type='radio']):not([type='submit']):not([type='button']), textarea"))
            .some(el => visible(el) && !el.disabled && !el.readOnly);
        const hasSubmit = Array.from(activePage.querySelectorAll('hj-button button, button, input[type=submit]'))
            .some(el => visible(el) && norm(el.innerText || el.value || el.textContent).includes('SUBMIT'));
        return !!(hasOrderLines && hasInput && hasSubmit && hasConfirm);
        """;

    public const string ClickErrorOkJs = """
        function norm(s) { return String(s || '').replace(/\s+/g, ' ').trim().toUpperCase(); }
        function visible(el) {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const st = window.getComputedStyle(el);
            return r.width > 15 && r.height > 15 && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
        }
        function fire(el) {
            if (!el) return false;
            try { el.scrollIntoView({block:'center', inline:'center'}); } catch(e) {}
            const r = el.getBoundingClientRect();
            const x = Math.max(1, Math.min(window.innerWidth - 2, r.left + r.width / 2));
            const y = Math.max(1, Math.min(window.innerHeight - 2, r.top + r.height / 2));
            const opts = {bubbles:true, cancelable:true, view:window, clientX:x, clientY:y, button:0, buttons:1};
            for (const ev of ['mouseover','mousemove','mousedown','mouseup','click']) {
                try { el.dispatchEvent(new MouseEvent(ev, opts)); } catch(e) {}
            }
            try { el.click(); } catch(e) {}
            return true;
        }
        const containers = Array.from(document.querySelectorAll(
            '[role="dialog"], .k-dialog, .k-window, .k-window-content, .dx-popup-content, .modal, .modal-dialog, .modal-content, .popup, hj-error-dialog, body *'
        )).filter(el => visible(el) && norm(el.innerText || el.textContent).includes('ERROR'));
        for (const c of containers) {
            const buttons = Array.from(c.querySelectorAll('button, hj-button button, a, span, div'))
                .filter(visible)
                .filter(el => norm(el.innerText || el.textContent || el.value) === 'OK');
            buttons.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
            for (const b of buttons) {
                if (fire(b)) return true;
            }
        }
        return false;
        """;

    public const string QuickFillActiveInputJs = """
        function visible(el) {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const st = window.getComputedStyle(el);
            return r.width > 20 && r.height > 15 && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
        }
        function bad(el) {
            const ph = String(el.getAttribute('placeholder') || '').toUpperCase();
            const id = String(el.getAttribute('id') || '').toUpperCase();
            const test = String(el.getAttribute('data-hj-test-id') || '').toUpperCase();
            const cls = String(el.className || '').toUpperCase();
            return ph.includes('SEARCH') || id.includes('SEARCH') || test.includes('SEARCH') || cls.includes('FILTER');
        }
        const inputs = Array.from(document.querySelectorAll("input:not([type='hidden']):not([type='password']):not([type='checkbox']):not([type='radio']):not([type='submit']):not([type='button']), textarea"))
            .filter(el => visible(el) && !el.disabled && !el.readOnly && !bad(el));
        const el = inputs.find(e => e.closest('.inputTextbox')) ||
                   inputs.find(e => String(e.className || '').includes('k-textbox')) ||
                   inputs.find(e => e === document.activeElement) ||
                   inputs[0];
        if (!el) return 'NOT_FOUND';
        try { el.scrollIntoView({block:'center', inline:'center'}); } catch(e) {}
        const value = String(arguments[0] ?? '');
        el.focus();
        try { el.click(); } catch(e) {}
        const inputSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
        const textAreaSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
        const setter = el.tagName === 'TEXTAREA' ? textAreaSetter : inputSetter;
        if (setter) setter.call(el, value); else el.value = value;
        el.dispatchEvent(new Event('input', {bubbles:true}));
        el.dispatchEvent(new Event('change', {bubbles:true}));
        el.dispatchEvent(new KeyboardEvent('keydown', {bubbles:true, key:'Tab'}));
        el.dispatchEvent(new KeyboardEvent('keyup', {bubbles:true, key:'Tab'}));
        return String(el.value ?? '').trim();
        """;

    public const string QuickClickSubmitJs = """
        function norm(s) { return String(s || '').replace(/\s+/g, ' ').trim().toUpperCase(); }
        function visible(el) {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const st = window.getComputedStyle(el);
            return r.width > 20 && r.height > 15 && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
        }
        function fire(el) {
            if (!el) return false;
            try { el.scrollIntoView({block:'center', inline:'center'}); } catch(e) {}
            const r = el.getBoundingClientRect();
            const x = Math.round(r.left + r.width / 2);
            const y = Math.round(r.top + r.height / 2);
            const opts = {bubbles:true, cancelable:true, view:window, clientX:x, clientY:y, button:0, buttons:1};
            for (const ev of ['mouseover','mousemove','mousedown','mouseup','click']) {
                try { el.dispatchEvent(new MouseEvent(ev, opts)); } catch(e) {}
            }
            try { el.click(); } catch(e) {}
            return true;
        }
        const active = document.activeElement;
        const activeRect = active && active.getBoundingClientRect ? active.getBoundingClientRect() : {bottom: 0};
        let candidates = Array.from(document.querySelectorAll('hj-button button, button, input[type=submit]'))
            .filter(visible)
            .filter(el => norm(el.innerText || el.value || el.textContent) === 'SUBMIT');
        candidates = candidates.filter(el => {
            const r = el.getBoundingClientRect();
            const inActionBar = !!el.closest('.app-bar,.action-group,header');
            return !inActionBar && r.top >= (activeRect.bottom - 5);
        }).sort((a,b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
        if (!candidates.length) {
            candidates = Array.from(document.querySelectorAll('hj-button button, button, input[type=submit]'))
                .filter(visible)
                .filter(el => norm(el.innerText || el.value || el.textContent).includes('SUBMIT'))
                .filter(el => !el.closest('.app-bar,.action-group,header'));
        }
        if (candidates.length) return fire(candidates[0]);
        return false;
        """;

    public const string ClickAnyCancelOnceJs = """
        function norm(s) { return String(s || '').replace(/\s+/g, ' ').trim().toUpperCase(); }
        function visible(el) {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const st = window.getComputedStyle(el);
            return r.width > 8 && r.height > 8 && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
        }
        function fire(el) {
            if (!el) return false;
            try { el.scrollIntoView({block:'center', inline:'center'}); } catch(e) {}
            const r = el.getBoundingClientRect();
            const x = Math.max(1, Math.min(window.innerWidth - 2, r.left + r.width / 2));
            const y = Math.max(1, Math.min(window.innerHeight - 2, r.top + r.height / 2));
            const opts = {bubbles:true, cancelable:true, view:window, clientX:x, clientY:y, button:0, buttons:1};
            for (const ev of ['mouseover','mousemove','mousedown','mouseup','click']) {
                try { el.dispatchEvent(new MouseEvent(ev, opts)); } catch(e) {}
            }
            try { el.click(); } catch(e) {}
            return true;
        }
        const all = Array.from(document.querySelectorAll('a, button, .functionKey, .functionKeyHighlighted, .table-cell, div, span')).filter(visible);
        let candidates = all.filter(el => {
            const t = norm(el.innerText || el.textContent || el.value);
            return t === 'CANCEL' || t === 'F1:CANCEL' || t.includes('F1:CANCEL');
        });
        candidates.sort((a,b) => {
            const af = a.closest('.functionKeys') ? 0 : 1;
            const bf = b.closest('.functionKeys') ? 0 : 1;
            if (af !== bf) return af - bf;
            return b.getBoundingClientRect().top - a.getBoundingClientRect().top;
        });
        for (const el of candidates) {
            let cur = el;
            for (let i = 0; i < 7 && cur; i++) {
                if (visible(cur) && fire(cur)) return true;
                cur = cur.parentElement;
            }
            if (fire(el)) return true;
        }
        return false;
        """;

    public const string VisibleRfMenuButtonExistsJs = """
        const targets = arguments[0] || [];
        function norm(s) { return String(s || '').replace(/\s+/g, ' ').trim().toUpperCase(); }
        function visible(el) {
            if (!el) return false;
            const st = window.getComputedStyle(el);
            if (st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0') return false;
            const r = el.getBoundingClientRect();
            return r.width > 8 && r.height > 8;
        }
        const els = Array.from(document.querySelectorAll('.inMotion .listButton, .inMotion .listButton .noselect, hj-field-cell, .field-cell'));
        return els.some(el => visible(el) && targets.includes(norm(el.innerText || el.textContent || el.value)));
        """;

    public const string FinalSubmitVisibleJs = """
        function norm(s) { return String(s || '').replace(/\s+/g, ' ').trim().toUpperCase(); }
        function visible(el) {
            if (!el) return false;
            const st = window.getComputedStyle(el);
            if (st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0') return false;
            const r = el.getBoundingClientRect();
            if (r.width < 30 || r.height < 18) return false;
            if (r.bottom < 0 || r.right < 0 || r.top > window.innerHeight || r.left > window.innerWidth) return false;
            return true;
        }
        function isReallyClickable(el) {
            if (!visible(el)) return false;
            const r = el.getBoundingClientRect();
            const x = Math.max(2, Math.min(window.innerWidth - 2, Math.round(r.left + r.width / 2)));
            const y = Math.max(2, Math.min(window.innerHeight - 2, Math.round(r.top + r.height / 2)));
            const hit = document.elementFromPoint(x, y);
            return !!(hit && (hit === el || el.contains(hit) || hit.closest('button,input[type=submit],hj-button') === el.closest('button,input[type=submit],hj-button')));
        }
        const rfButtons = Array.from(document.querySelectorAll('.inMotion .listButton, .inMotion .listButton .noselect, hj-field-cell, .field-cell'))
            .filter(visible)
            .map(el => norm(el.innerText || el.textContent));
        if (rfButtons.some(t => ['EFL','INBOUND','INVENTORY','OUTBOUND','LOAD AUDIT EFL','SHIPPING EFL','ORDER PICK','LOADING EFL','PO PACKING'].includes(t))) return false;
        const bodyText = norm(document.body && (document.body.innerText || document.body.textContent));
        if (['LOAD ID', 'GATE PASS', 'LOCATION', 'CARRIER NAME', 'PRO NUMBER', 'SEAL NUMBER', 'ENTER:CONFIRM', 'Y OR N'].some(t => bodyText.includes(t))) return false;
        const cancelVisible = Array.from(document.querySelectorAll('a, button, div, span'))
            .filter(visible)
            .some(el => {
                const t = norm(el.innerText || el.textContent || el.value);
                return t === 'CANCEL' || t === 'F1:CANCEL' || t.includes('F1:CANCEL');
            });
        if (cancelVisible) return false;
        const buttons = Array.from(document.querySelectorAll('hj-button button, button, input[type=submit]'))
            .filter(visible)
            .filter(el => norm(el.innerText || el.textContent || el.value) === 'SUBMIT')
            .filter(el => !el.closest('.app-bar,.action-bar,header,.quick-nav'))
            .filter(isReallyClickable);
        return buttons.length > 0;
        """;

    public const string ClickFinalSubmitJs = """
        function norm(s) { return String(s || '').replace(/\s+/g, ' ').trim().toUpperCase(); }
        function visible(el) {
            if (!el) return false;
            const st = window.getComputedStyle(el);
            if (st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0') return false;
            const r = el.getBoundingClientRect();
            if (r.width < 30 || r.height < 18) return false;
            if (r.bottom < 0 || r.right < 0 || r.top > window.innerHeight || r.left > window.innerWidth) return false;
            return true;
        }
        function isReallyClickable(el) {
            if (!visible(el)) return false;
            const r = el.getBoundingClientRect();
            const x = Math.max(2, Math.min(window.innerWidth - 2, Math.round(r.left + r.width / 2)));
            const y = Math.max(2, Math.min(window.innerHeight - 2, Math.round(r.top + r.height / 2)));
            const hit = document.elementFromPoint(x, y);
            return !!(hit && (hit === el || el.contains(hit) || hit.closest('button,input[type=submit],hj-button') === el.closest('button,input[type=submit],hj-button')));
        }
        function fire(el) {
            if (!isReallyClickable(el)) return false;
            try { el.scrollIntoView({block:'center', inline:'center', behavior:'instant'}); } catch(e) {}
            const r = el.getBoundingClientRect();
            const x = Math.max(2, Math.min(window.innerWidth - 2, Math.round(r.left + r.width / 2)));
            const y = Math.max(2, Math.min(window.innerHeight - 2, Math.round(r.top + r.height / 2)));
            const hit = document.elementFromPoint(x, y) || el;
            const clickable = hit.closest('button, input[type=submit], hj-button, a, [role="button"]') || el;
            const opts = {bubbles:true, cancelable:true, view:window, clientX:x, clientY:y, button:0, buttons:1};
            for (const ev of ['pointerover','mouseover','mousemove','pointerdown','mousedown','pointerup','mouseup','click']) {
                try { clickable.dispatchEvent(new MouseEvent(ev, opts)); } catch(e) {}
            }
            try { clickable.click(); } catch(e) {}
            try { el.click(); } catch(e) {}
            return true;
        }
        const bodyText = norm(document.body && (document.body.innerText || document.body.textContent));
        if (['LOAD ID', 'GATE PASS', 'LOCATION', 'CARRIER NAME', 'PRO NUMBER', 'SEAL NUMBER', 'ENTER:CONFIRM', 'Y OR N'].some(t => bodyText.includes(t))) return false;
        let buttons = Array.from(document.querySelectorAll('hj-button button, button, input[type=submit]'))
            .filter(visible)
            .filter(el => norm(el.innerText || el.textContent || el.value) === 'SUBMIT')
            .filter(el => !el.closest('.app-bar,.action-bar,header,.quick-nav'))
            .filter(isReallyClickable)
            .sort((a,b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
        for (const b of buttons) {
            if (fire(b)) return true;
        }
        return false;
        """;
}
