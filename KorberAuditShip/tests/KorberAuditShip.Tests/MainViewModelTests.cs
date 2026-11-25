using System.IO;
using ClosedXML.Excel;
using KorberAuditShip.Models;
using KorberAuditShip.Services;
using KorberAuditShip.ViewModels;
using Xunit;

namespace KorberAuditShip.Tests;

public sealed class MainViewModelTests : IDisposable
{
    private readonly string _tempDir;
    private readonly string _credPath;
    private readonly string _bridgePath;
    private readonly FakeDialogService _dialogs = new();
    private readonly FakeBrowserFactory _browserFactory = new();
    private readonly CredentialService _credentialService;
    private readonly SpreadsheetService _spreadsheetService = new();
    private readonly PdfExportService _pdfExportService = new();
    private readonly KorberAutomationService _automationService;

    public MainViewModelTests()
    {
        _tempDir = Path.Combine(Path.GetTempPath(), $"KorberVmTests_{Guid.NewGuid():N}");
        Directory.CreateDirectory(_tempDir);
        _credPath = Path.Combine(_tempDir, "creds.dat");
        _bridgePath = Path.Combine(_tempDir, "config.json");
        _credentialService = new CredentialService(_credPath, _bridgePath, _ => null);
        _automationService = new KorberAutomationService(_browserFactory);
    }

    public void Dispose()
    {
        if (Directory.Exists(_tempDir))
            Directory.Delete(_tempDir, recursive: true);
    }

    private MainViewModel CreateViewModel()
        => new(_spreadsheetService, _pdfExportService, _credentialService, _automationService, _dialogs);

    private string CreateSampleExcel(int rowCount)
    {
        var path = Path.Combine(_tempDir, $"sample_{rowCount}.xlsx");
        using var wb = new XLWorkbook();
        var ws = wb.Worksheets.Add("Sheet1");
        ws.Cell(1, 1).Value = "Wh Id";
        ws.Cell(1, 2).Value = "Load Id";
        ws.Cell(1, 3).Value = "Gate Pass Id";

        for (var i = 1; i <= rowCount; i++)
        {
            ws.Cell(i + 1, 1).Value = "LPPL";
            ws.Cell(i + 1, 2).Value = $"LD-{i:000}";
            ws.Cell(i + 1, 3).Value = $"GP-{i:000}";
        }

        wb.SaveAs(path);
        return path;
    }

    [Fact]
    public async Task LoadSpreadsheetFromFileAsync_PopulatesPaginationSliderAndSummary()
    {
        var vm = CreateViewModel();
        var excelPath = CreateSampleExcel(25);

        await vm.LoadSpreadsheetFromFileAsync(excelPath, "D-07");

        Assert.True(vm.HasData);
        Assert.Equal(25, vm.TotalRows);
        Assert.Equal(10, vm.VisibleRows.Count);
        Assert.Equal("Showing 1 - 10 of 25 rows", vm.PageInfoText);
        Assert.Contains("Door Location: D-07", vm.SummaryText);
        Assert.Equal(15, vm.SliderMaximum);
        Assert.True(vm.IsSliderEnabled);
        Assert.False(vm.CanGoPrevious);
        Assert.True(vm.CanGoNext);

        // Next page -> rows 11..20
        vm.NextPageCommand.Execute(null);
        Assert.Equal(10, vm.StartRow);
        Assert.Equal("Showing 11 - 20 of 25 rows", vm.PageInfoText);
        Assert.Equal("LD-011", vm.VisibleRows[0].LoadId);
        Assert.True(vm.CanGoPrevious);
        Assert.True(vm.CanGoNext);

        // GoToRow -> row 22 (clamped to MaxStartRow = 15 -> rows 16..25)
        vm.GoToRowInput = "22";
        vm.GoToRowCommand.Execute(null);
        Assert.Equal(15, vm.StartRow);
        Assert.Equal("Showing 16 - 25 of 25 rows", vm.PageInfoText);

        // Mouse wheel scroll up (+120 steps up by VisibleTableRows = 10 rows -> 15 - 10 = 5)
        vm.HandleTableMouseWheel(120);
        Assert.Equal(5, vm.StartRow);
    }

    [Fact]
    public async Task ExportsCopyAndClearWorkspace_WorkEndToEnd()
    {
        var vm = CreateViewModel();
        var excelPath = CreateSampleExcel(3);
        await vm.LoadSpreadsheetFromFileAsync(excelPath, "D-01");

        var excelOut = Path.Combine(_tempDir, "out.xlsx");
        var pdfOut = Path.Combine(_tempDir, "out.pdf");
        _dialogs.SaveExcelPath = excelOut;
        _dialogs.SavePdfPath = pdfOut;

        vm.ExportExcelCommand.Execute(null);
        vm.ExportPdfCommand.Execute(null);

        Assert.True(File.Exists(excelOut));
        Assert.True(File.Exists(pdfOut));

        vm.CopyCellValue("LD-001");
        Assert.Equal("LD-001", _dialogs.LastCopiedText);
        Assert.Contains("LD-001", vm.StatusText);

        vm.ClearWorkspaceCommand.Execute(null);
        Assert.False(vm.HasData);
        Assert.Equal(0, vm.TotalRows);
        Assert.Equal("View cleared", vm.StatusText);
    }

    [Fact]
    public void CommandsWarn_WhenWorkspaceEmptyOrCredentialsMissing()
    {
        var vm = CreateViewModel();

        vm.RunLoadAuditCommand.Execute(null);
        Assert.Contains("Upload Excel first.", _dialogs.Warnings);

        _dialogs.NextCredentialsResult = new KorberCredentials("OP1", "PW1", "F1", "Local Encrypted Settings (DPAPI)");
        vm.ConfigureCredentialsCommand.Execute(null);
        Assert.Contains("OP1", vm.CredentialStatusLabel);
    }

    private sealed class FakeDialogService : IDialogService
    {
        public string? OpenExcelPath { get; set; }
        public string? SaveExcelPath { get; set; }
        public string? SavePdfPath { get; set; }
        public string? PromptResult { get; set; }
        public KorberCredentials? NextCredentialsResult { get; set; }
        public List<string> Warnings { get; } = [];
        public string? LastCopiedText { get; private set; }

        public string? OpenExcelFile() => OpenExcelPath;
        public string? SaveExcelFile(string defaultFileName) => SaveExcelPath;
        public string? SavePdfFile(string defaultFileName) => SavePdfPath;
        public string? PromptInput(string title, string prompt, string initialValue = "") => PromptResult;
        public KorberCredentials? PromptCredentials(KorberCredentials? current, CredentialService credentialService)
        {
            if (NextCredentialsResult is { IsComplete: true })
                credentialService.SaveLocalCredentials(NextCredentialsResult.Username, NextCredentialsResult.Password, NextCredentialsResult.ForkId);
            return NextCredentialsResult;
        }
        public void ShowInfo(string title, string message) { }
        public void ShowWarning(string title, string message) => Warnings.Add(message);
        public void ShowError(string title, string message) => Warnings.Add(message);
        public void CopyTextToClipboard(string text) => LastCopiedText = text;
        public void InvokeOnUiThread(Action action) => action();
    }

    private sealed class FakeBrowserFactory : IBrowserSessionFactory
    {
        public Task<IBrowserSession> OpenOrAttachAsync(Action<string>? statusCallback, CancellationToken cancellationToken)
            => throw new NotSupportedException();
    }
}
