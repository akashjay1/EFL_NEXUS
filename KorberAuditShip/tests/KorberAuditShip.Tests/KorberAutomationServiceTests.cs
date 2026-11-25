using KorberAuditShip.Models;
using KorberAuditShip.Services;
using Xunit;

namespace KorberAuditShip.Tests;

public sealed class KorberAutomationServiceTests
{
    private static readonly KorberCredentials TestCreds = new("OP_TEST", "Pass123!", "FORK_01", "Test");

    [Fact]
    public async Task OpenBrowserToOutboundAsync_NavigatesThroughLoginMenuWarehouseAndOutbound()
    {
        var session = new FakeKorberBrowserSession(FakeKorberBrowserSession.InitialScreen.Login);
        var factory = new SingleSessionFactory(session);
        var service = new KorberAutomationService(factory);

        var rows = new List<AuditShipRow>
        {
            new() { RowIndex = 0, WhId = "LPPL", LoadId = "L100", GatePassId = "GP100", DoorLocation = "D01" }
        };

        var statuses = new List<string>();
        var result = await service.OpenBrowserToOutboundAsync(rows, TestCreds, statuses.Add, null, CancellationToken.None);

        Assert.True(result.Success, result.Message);
        Assert.Equal("Browser opened and stopped at LPPL > EFL > OUTBOUND.", result.Message);
        Assert.True(service.HasActiveBrowser);
        Assert.Contains("FORK_01", session.EnteredForkIds);
        Assert.Contains("WH:LPPL", session.SubmittedValues);
        Assert.Contains("Main menu warehouse options visible. Found LPPL.", statuses);
        Assert.Equal(KorberSelectors.KorberUrl, session.NavigatedUrl);
    }

    [Fact]
    public async Task RunLoadAuditLoopAsync_HandlesDoneInvalidErrorPopupAndLoadingIssue()
    {
        var session = new FakeKorberBrowserSession(FakeKorberBrowserSession.InitialScreen.OutboundMenu);
        var service = new KorberAutomationService(new SingleSessionFactory(session));
        service.AttachExistingSessionForTesting(session);

        var rows = new List<AuditShipRow>
        {
            new() { RowIndex = 0, WhId = "LPPL", LoadId = "LD-OK", GatePassId = "GP-1", DoorLocation = "D-1" },
            new() { RowIndex = 1, WhId = "LPPL", LoadId = "LD-BAD", GatePassId = "GP-2", DoorLocation = "D-1" },
            new() { RowIndex = 2, WhId = "LPPL", LoadId = "LD-ISSUE", GatePassId = "GP-3", DoorLocation = "D-1" }
        };

        var rowUpdates = new Dictionary<int, string>();
        var result = await service.RunLoadAuditLoopAsync(
            rows,
            TestCreds,
            null,
            (idx, status) => rowUpdates[idx] = status,
            null,
            CancellationToken.None);

        Assert.True(result.Success, result.Message);
        Assert.Equal(1, result.DoneCount);
        Assert.Equal(2, result.SkippedCount);
        Assert.Equal("Done", rowUpdates[0]);
        Assert.Equal("INVALID LOAD ID", rowUpdates[1]);
        Assert.Equal("Loding Issue", rowUpdates[2]);
        Assert.True(session.ReturnedToMainMenuAfterWorkflow);
    }

    [Fact]
    public async Task RunShippingLoopAsync_CompletesValidRowAndSkipsNotFoundError()
    {
        var session = new FakeKorberBrowserSession(FakeKorberBrowserSession.InitialScreen.OutboundMenu);
        var service = new KorberAutomationService(new SingleSessionFactory(session));
        service.AttachExistingSessionForTesting(session);

        var rows = new List<AuditShipRow>
        {
            new() { RowIndex = 0, WhId = "ESKD", LoadId = "LD-SHIP", GatePassId = "GP-10", DoorLocation = "D-9" },
            new() { RowIndex = 1, WhId = "ESKD", LoadId = "LD-MISSING", GatePassId = "GP-11", DoorLocation = "D-9" }
        };

        var rowUpdates = new Dictionary<int, string>();
        var result = await service.RunShippingLoopAsync(
            rows,
            "SEAL-88",
            TestCreds,
            null,
            (idx, status) => rowUpdates[idx] = status,
            null,
            CancellationToken.None);

        Assert.True(result.Success, result.Message);
        Assert.Equal(1, result.DoneCount);
        Assert.Equal(1, result.SkippedCount);
        Assert.Equal("Done", rowUpdates[0]);
        Assert.Equal("LOAD ID NOT FOUND", rowUpdates[1]);
        Assert.Contains("DEFAULT", session.SubmittedValues);
        Assert.Contains("SEAL-88", session.SubmittedValues);
    }

    [Fact]
    public async Task CloseBrowserAsync_ClicksCancelThenFinalSubmitAndQuitsSession()
    {
        var session = new FakeKorberBrowserSession(FakeKorberBrowserSession.InitialScreen.AuditLoadId)
        {
            CancelStepsBeforeFinalSubmit = 2
        };
        var service = new KorberAutomationService(new SingleSessionFactory(session));
        service.AttachExistingSessionForTesting(session);

        var result = await service.CloseBrowserAsync(TestCreds, null, null, CancellationToken.None);

        Assert.True(result.Success, result.Message);
        Assert.True(session.FinalSubmitClicked);
        Assert.True(session.QuitCalled);
        Assert.False(service.HasActiveBrowser);
    }

    [Fact]
    public async Task HandleCriticalKorberPopupAsync_InvokesCallbackAndStopsWhenCancelled()
    {
        var session = new FakeKorberBrowserSession(FakeKorberBrowserSession.InitialScreen.CriticalDeviceIdPopup);
        var service = new KorberAutomationService(new SingleSessionFactory(session));

        string? capturedTitle = null;
        string? capturedMessage = null;
        var statuses = new List<string>();
        using var cts = new CancellationTokenSource();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(async () =>
        {
            await service.HandleCriticalKorberPopupAsync(
                session,
                msg =>
                {
                    statuses.Add(msg);
                    cts.Cancel();
                },
                (title, message) =>
                {
                    capturedTitle = title;
                    capturedMessage = message;
                },
                cts.Token);
        });

        Assert.Equal("Device ID Error", capturedTitle);
        Assert.Contains("contact the System Team", capturedMessage);
        Assert.Contains(statuses, s => s.Contains("Waiting 300 seconds", StringComparison.Ordinal));
    }

    private sealed class SingleSessionFactory(IBrowserSession session) : IBrowserSessionFactory
    {
        public Task<IBrowserSession> OpenOrAttachAsync(Action<string>? statusCallback, CancellationToken cancellationToken)
            => Task.FromResult(session);
    }

    private sealed class FakeKorberBrowserSession : IBrowserSession
    {
        public enum InitialScreen
        {
            Login,
            HomePage,
            KorberMobileMenu,
            ForkIdPrompt,
            WarehouseList,
            EflSubmenu,
            OutboundMenu,
            AuditLoadId,
            AuditGatePass,
            AuditLocation,
            AuditYesNo,
            AuditConfirm,
            AuditLoadingIssue,
            ShippingLoadId,
            ShippingGatePass,
            ShippingLocation,
            ShippingCarrier,
            ShippingProNumber,
            ShippingSealNumber,
            ShippingConfirm,
            ErrorDialog,
            FinalSubmitScreen,
            CriticalDeviceIdPopup
        }

        private InitialScreen _screen;
        private string _activeError = string.Empty;
        private string _pendingInput = string.Empty;
        private bool _inShippingMode;
        private bool _triggerForkAfterLogin = true;

        public FakeKorberBrowserSession(InitialScreen initial) => _screen = initial;

        public bool IsAlive { get; private set; } = true;
        public string NavigatedUrl { get; private set; } = string.Empty;
        public List<string> EnteredForkIds { get; } = [];
        public List<string> SubmittedValues { get; } = [];
        public bool ReturnedToMainMenuAfterWorkflow => _screen == InitialScreen.OutboundMenu;
        public int CancelStepsBeforeFinalSubmit { get; set; }
        public bool FinalSubmitClicked { get; private set; }
        public bool QuitCalled { get; private set; }

        public void Navigate(string url)
        {
            NavigatedUrl = url;
            _screen = InitialScreen.Login;
        }

        public string GetCurrentUrl() => KorberSelectors.KorberUrl;
        public string GetReadyState() => "complete";

        public string GetVisibleBodyText() => _screen switch
        {
            InitialScreen.Login => "Sign In User Name Password Login",
            InitialScreen.HomePage => "Home Page Workspace",
            InitialScreen.KorberMobileMenu => "Körber One Mobile Login",
            InitialScreen.ForkIdPrompt => "Scan your Fork identifier EQUIPMENT-ZONE",
            InitialScreen.WarehouseList => "Main LPPL ESKD NUGE EGDC",
            InitialScreen.EflSubmenu => "EFL INBOUND INVENTORY OUTBOUND",
            InitialScreen.OutboundMenu => "OUTBOUND Order Pick Loading EFL Load Audit EFL Shipping EFL PO Packing",
            InitialScreen.AuditLoadId => "Load Audit EFL LOAD ID Enter the Load ID",
            InitialScreen.AuditGatePass => "Load Audit EFL GATE PASS ID",
            InitialScreen.AuditLocation => "Load Audit EFL LOCATION Door Location",
            InitialScreen.AuditYesNo => "Load Audit EFL Y or N Ready to print reports",
            InitialScreen.AuditConfirm => "Load Audit EFL ENTER:Confirm ready to ship",
            InitialScreen.AuditLoadingIssue => "Load Audit EFL ORDER: 123 ITEM: ABC ORDERED: 10 PICKED: 5 LOADED: 5 Confirm",
            InitialScreen.ShippingLoadId => "Shipping EFL LOAD ID Enter the Load ID",
            InitialScreen.ShippingGatePass => "Shipping EFL GATE PASS ID",
            InitialScreen.ShippingLocation => "Shipping EFL LOCATION Door Location",
            InitialScreen.ShippingCarrier => "Shipping EFL CARRIER NAME Carrier",
            InitialScreen.ShippingProNumber => "Shipping EFL PRO NUMBER PRO",
            InitialScreen.ShippingSealNumber => "Shipping EFL SEAL NUMBER SEAL",
            InitialScreen.ShippingConfirm => "Shipping EFL ENTER:Confirm Confirm",
            InitialScreen.ErrorDialog => $"Error {_activeError} OK",
            InitialScreen.FinalSubmitScreen => "Submit",
            InitialScreen.CriticalDeviceIdPopup => "THE KOERBER ONE USER HAS CHANGED FOR THIS TERMINAL",
            _ => string.Empty
        };

        public string GetPageSource() => $"<html><body>{GetVisibleBodyText()}</body></html>";

        public object? ExecuteScript(string script, params object[] args)
        {
            if (script == KorberSelectors.IsLoginScreenVisibleJs)
                return _screen == InitialScreen.Login;

            if (script == KorberSelectors.FindVisibleMainWarehouseJs)
            {
                Assert.Single(args);
                var names = Assert.IsAssignableFrom<IEnumerable<string>>(args[0]).ToList();
                Assert.Contains("LPPL", names);
                return _screen == InitialScreen.WarehouseList ? "LPPL" : string.Empty;
            }

            if (script == KorberSelectors.ClickWarehouseJs)
            {
                Assert.Single(args);
                SubmittedValues.Add($"WH:{args[0]}");
                _screen = InitialScreen.EflSubmenu;
                return true;
            }

            if (script == KorberSelectors.ClickRfMenuButtonExactJs || script == KorberSelectors.ClickByVisibleTextJs)
            {
                var target = args.FirstOrDefault()?.ToString() ?? string.Empty;
                if (target.Equals("EFL", StringComparison.OrdinalIgnoreCase) && _screen == InitialScreen.EflSubmenu)
                    return true;
                if (target.Equals("OUTBOUND", StringComparison.OrdinalIgnoreCase))
                {
                    _screen = InitialScreen.OutboundMenu;
                    return true;
                }
                if (target.Equals("Load Audit EFL", StringComparison.OrdinalIgnoreCase))
                {
                    _inShippingMode = false;
                    _screen = InitialScreen.AuditLoadId;
                    return true;
                }
                if (target.Equals("Shipping EFL", StringComparison.OrdinalIgnoreCase))
                {
                    _inShippingMode = true;
                    _screen = InitialScreen.ShippingLoadId;
                    return true;
                }
                return true;
            }

            if (script == KorberSelectors.VisibleRfMenuButtonExistsJs)
            {
                Assert.Single(args);
                var labels = Assert.IsAssignableFrom<IEnumerable<string>>(args[0]).ToList();
                var body = GetVisibleBodyText().ToUpperInvariant();
                return labels.Any(l => body.Contains(l.ToUpperInvariant(), StringComparison.Ordinal));
            }

            if (script == KorberSelectors.IsRfTextEntryVisibleJs)
            {
                return _screen is InitialScreen.ForkIdPrompt
                    or InitialScreen.AuditLoadId or InitialScreen.AuditGatePass
                    or InitialScreen.AuditLocation or InitialScreen.AuditYesNo
                    or InitialScreen.ShippingLoadId or InitialScreen.ShippingGatePass
                    or InitialScreen.ShippingLocation or InitialScreen.ShippingCarrier
                    or InitialScreen.ShippingProNumber or InitialScreen.ShippingSealNumber;
            }

            if (script == KorberSelectors.GetVisibleErrorMessageJs)
                return _screen == InitialScreen.ErrorDialog ? _activeError : string.Empty;

            if (script == KorberSelectors.IsLoadingIssueScreenJs)
                return _screen == InitialScreen.AuditLoadingIssue;

            if (script == KorberSelectors.ClickErrorOkJs)
            {
                if (_screen != InitialScreen.ErrorDialog) return false;
                _activeError = string.Empty;
                _screen = _inShippingMode ? InitialScreen.ShippingLoadId : InitialScreen.AuditLoadId;
                return true;
            }

            if (script == KorberSelectors.QuickFillActiveInputJs)
            {
                _pendingInput = args.FirstOrDefault()?.ToString()?.Trim() ?? string.Empty;
                if (_screen == InitialScreen.ForkIdPrompt)
                    EnteredForkIds.Add(_pendingInput);
                else
                    SubmittedValues.Add(_pendingInput);
                return _pendingInput;
            }

            if (script == KorberSelectors.QuickClickSubmitJs)
            {
                AdvanceScreenOnSubmit();
                return true;
            }

            if (script == KorberSelectors.ClickAnyCancelOnceJs)
            {
                if (CancelStepsBeforeFinalSubmit > 0)
                {
                    CancelStepsBeforeFinalSubmit--;
                    if (CancelStepsBeforeFinalSubmit == 0)
                        _screen = InitialScreen.FinalSubmitScreen;
                    return true;
                }

                if (_screen is InitialScreen.AuditLoadId or InitialScreen.ShippingLoadId)
                {
                    _screen = InitialScreen.OutboundMenu;
                    return true;
                }

                return false;
            }

            if (script == KorberSelectors.FinalSubmitVisibleJs)
                return _screen == InitialScreen.FinalSubmitScreen;

            if (script == KorberSelectors.ClickFinalSubmitJs)
            {
                if (_screen != InitialScreen.FinalSubmitScreen) return false;
                FinalSubmitClicked = true;
                return true;
            }

            return null;
        }

        public bool TryClickVisibleByXPaths(IEnumerable<string> xpaths)
        {
            var list = xpaths.ToList();
            if (_screen == InitialScreen.Login && list.SequenceEqual(KorberSelectors.InitialLoginButtonXPaths))
            {
                _screen = InitialScreen.HomePage;
                return true;
            }

            if (_screen == InitialScreen.HomePage && list.SequenceEqual(KorberSelectors.HamburgerMenuXPaths))
            {
                _screen = InitialScreen.KorberMobileMenu;
                return true;
            }

            if (_screen == InitialScreen.KorberMobileMenu && list.SequenceEqual(KorberSelectors.KorberMobileXPaths))
            {
                if (_triggerForkAfterLogin)
                {
                    _triggerForkAfterLogin = false;
                    _screen = InitialScreen.ForkIdPrompt;
                }
                else
                {
                    _screen = InitialScreen.WarehouseList;
                }
                return true;
            }

            if (list.SequenceEqual(KorberSelectors.MobileLoginXPaths))
                return true;

            if (list.SequenceEqual(KorberSelectors.RfSubmitButtonXPaths))
            {
                AdvanceScreenOnSubmit();
                return true;
            }

            if (_screen == InitialScreen.ForkIdPrompt && list.SequenceEqual(KorberSelectors.ForkSubmitXPaths))
            {
                AdvanceScreenOnSubmit();
                return true;
            }

            return false;
        }

        public bool TryDoubleClickVisibleByXPaths(IEnumerable<string> xpaths) => false;

        public bool TryTypeVisibleByXPaths(IEnumerable<string> xpaths, string value)
        {
            if (_screen == InitialScreen.ForkIdPrompt)
                EnteredForkIds.Add(value);
            SubmittedValues.Add(value);
            return true;
        }

        public bool IsAnyXPathVisible(IEnumerable<string> xpaths)
        {
            var list = xpaths.ToList();
            if (_screen == InitialScreen.ForkIdPrompt && list.Any(x => x.Contains("Scan your Fork identifier", StringComparison.Ordinal)))
                return true;
            return _screen == InitialScreen.KorberMobileMenu && list.SequenceEqual(KorberSelectors.HamburgerOpenVerifyXPaths);
        }

        public bool TryFallbackTypeRfInput(string value)
        {
            _pendingInput = value.Trim();
            if (_screen == InitialScreen.ForkIdPrompt)
                EnteredForkIds.Add(_pendingInput);
            return true;
        }

        public bool TryFallbackClickRfSubmit()
        {
            AdvanceScreenOnSubmit();
            return true;
        }

        public void SendEnterKeyToActiveElement() => AdvanceScreenOnSubmit();
        public void SendF1Key() { }

        public void Quit()
        {
            QuitCalled = true;
            IsAlive = false;
        }

        public void Dispose() => Quit();

        private void AdvanceScreenOnSubmit()
        {
            switch (_screen)
            {
                case InitialScreen.ForkIdPrompt:
                    _screen = InitialScreen.WarehouseList;
                    break;
                case InitialScreen.AuditLoadId:
                    if (_pendingInput == "LD-BAD")
                    {
                        _activeError = "INVALID LOAD ID";
                        _screen = InitialScreen.ErrorDialog;
                    }
                    else
                    {
                        _screen = InitialScreen.AuditGatePass;
                    }
                    break;
                case InitialScreen.AuditGatePass:
                    _screen = InitialScreen.AuditLocation;
                    break;
                case InitialScreen.AuditLocation:
                    _screen = _pendingInput == "D-1" && SubmittedValues.Contains("LD-ISSUE") && !SubmittedValues.Contains("LD-DONE-3") && SubmittedValues.LastOrDefault(v => v.StartsWith("LD-", StringComparison.Ordinal)) == "LD-ISSUE"
                        ? InitialScreen.AuditLoadingIssue
                        : InitialScreen.AuditYesNo;
                    break;
                case InitialScreen.AuditLoadingIssue:
                    _screen = InitialScreen.AuditLoadId;
                    break;
                case InitialScreen.AuditYesNo:
                    _screen = InitialScreen.AuditConfirm;
                    break;
                case InitialScreen.AuditConfirm:
                    _screen = InitialScreen.AuditLoadId;
                    break;
                case InitialScreen.ShippingLoadId:
                    if (_pendingInput == "LD-MISSING")
                    {
                        _activeError = "LOAD ID NOT FOUND";
                        _screen = InitialScreen.ErrorDialog;
                    }
                    else
                    {
                        _screen = InitialScreen.ShippingGatePass;
                    }
                    break;
                case InitialScreen.ShippingGatePass:
                    _screen = InitialScreen.ShippingLocation;
                    break;
                case InitialScreen.ShippingLocation:
                    _screen = InitialScreen.ShippingCarrier;
                    break;
                case InitialScreen.ShippingCarrier:
                    _screen = InitialScreen.ShippingProNumber;
                    break;
                case InitialScreen.ShippingProNumber:
                    _screen = InitialScreen.ShippingSealNumber;
                    break;
                case InitialScreen.ShippingSealNumber:
                    _screen = InitialScreen.ShippingConfirm;
                    break;
                case InitialScreen.ShippingConfirm:
                    _screen = InitialScreen.ShippingLoadId;
                    break;
            }
        }
    }
}
