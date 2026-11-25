using System.Collections.ObjectModel;
using System.ComponentModel;
using System.IO;
using System.Runtime.CompilerServices;
using System.Windows.Media;
using KorberAuditShip.Models;
using KorberAuditShip.Services;

namespace KorberAuditShip.ViewModels;

/// <summary>
/// Coordinates UI state, spreadsheet import/export, table virtualization/pagination,
/// credential resolution, and background Körber automation tasks.
/// </summary>
public sealed class MainViewModel : INotifyPropertyChanged
{
    public const int VisibleTableRows = 10;

    // Color constants matching KORBER AuditShip's UI palette
    public const string BgColorHex = "#F3F6FA";
    public const string SidebarColorHex = "#101828";
    public const string CardColorHex = "#FFFFFF";
    public const string TextDarkHex = "#101828";
    public const string TextMidHex = "#667085";
    public const string AccentHex = "#7F56D9";
    public const string BlueHex = "#2563EB";
    public const string GreenHex = "#16A34A";
    public const string EmeraldHex = "#059669";
    public const string RedHex = "#DC2626";
    public const string AmberHex = "#F59E0B";
    public const string CloseRedHex = "#EF4444";

    private readonly SpreadsheetService _spreadsheetService;
    private readonly PdfExportService _pdfExportService;
    private readonly CredentialService _credentialService;
    private readonly KorberAutomationService _automationService;
    private readonly IDialogService _dialogs;

    private readonly List<AuditShipRow> _allRows = [];
    private readonly object _workerLock = new();
    private CancellationTokenSource? _activeCts;
    private bool _isWorkerRunning;

    private OperationalSummary? _summary;
    private int _startRow;
    private string _goToRowInput = string.Empty;
    private string _statusText = "No spreadsheet loaded";
    private string _statusColorHex = AccentHex;
    private bool _buttonsEnabled = true;

    public MainViewModel(
        SpreadsheetService spreadsheetService,
        PdfExportService pdfExportService,
        CredentialService credentialService,
        KorberAutomationService automationService,
        IDialogService dialogs)
    {
        _spreadsheetService = spreadsheetService;
        _pdfExportService = pdfExportService;
        _credentialService = credentialService;
        _automationService = automationService;
        _dialogs = dialogs;

        UploadSpreadsheetCommand = new RelayCommand(ExecuteUploadSpreadsheet, () => ButtonsEnabled);
        ClearWorkspaceCommand = new RelayCommand(ExecuteClearWorkspace, () => ButtonsEnabled);
        OpenKorberCommand = new RelayCommand(ExecuteOpenKorber, () => ButtonsEnabled);
        CloseBrowserCommand = new RelayCommand(ExecuteCloseBrowser, () => ButtonsEnabled);
        RunLoadAuditCommand = new RelayCommand(ExecuteRunLoadAudit, () => ButtonsEnabled);
        ProcessShippingCommand = new RelayCommand(ExecuteProcessShipping, () => ButtonsEnabled);
        StopAutomationCommand = new RelayCommand(ExecuteStopAutomation);
        ExportPdfCommand = new RelayCommand(ExecuteExportPdf, () => ButtonsEnabled);
        ExportExcelCommand = new RelayCommand(ExecuteExportExcel, () => ButtonsEnabled);
        ConfigureCredentialsCommand = new RelayCommand(ExecuteConfigureCredentials, () => ButtonsEnabled);
        PreviousPageCommand = new RelayCommand(ExecutePreviousPage, () => CanGoPrevious);
        NextPageCommand = new RelayCommand(ExecuteNextPage, () => CanGoNext);
        GoToRowCommand = new RelayCommand(ExecuteGoToRow);
    }

    public ObservableCollection<AuditShipRow> VisibleRows { get; } = [];

    public RelayCommand UploadSpreadsheetCommand { get; }
    public RelayCommand ClearWorkspaceCommand { get; }
    public RelayCommand OpenKorberCommand { get; }
    public RelayCommand CloseBrowserCommand { get; }
    public RelayCommand RunLoadAuditCommand { get; }
    public RelayCommand ProcessShippingCommand { get; }
    public RelayCommand StopAutomationCommand { get; }
    public RelayCommand ExportPdfCommand { get; }
    public RelayCommand ExportExcelCommand { get; }
    public RelayCommand ConfigureCredentialsCommand { get; }
    public RelayCommand PreviousPageCommand { get; }
    public RelayCommand NextPageCommand { get; }
    public RelayCommand GoToRowCommand { get; }

    public IReadOnlyList<AuditShipRow> AllRows => _allRows;

    public bool HasData => _allRows.Count > 0;

    public int TotalRows => _allRows.Count;

    public int RowsPerPage => Math.Min(Math.Max(VisibleTableRows, 10), Math.Max(TotalRows, 1));

    public int MaxStartRow => Math.Max(0, TotalRows - RowsPerPage);

    public int SliderMaximum => MaxStartRow > 0 ? MaxStartRow : 1;

    public bool IsSliderEnabled => MaxStartRow > 0;

    public int StartRow
    {
        get => _startRow;
        set
        {
            var clamped = ClampStartRow(value);
            if (_startRow == clamped) return;
            _startRow = clamped;
            OnPropertyChanged();
            RenderVisiblePage();
        }
    }

    public bool CanGoPrevious => HasData && StartRow > 0;

    public bool CanGoNext => HasData && (StartRow + RowsPerPage) < TotalRows;

    public string PageInfoText
    {
        get
        {
            if (TotalRows == 0)
                return "No rows";

            var endRow = Math.Min(StartRow + RowsPerPage, TotalRows);
            return $"Showing {StartRow + 1:N0} - {endRow:N0} of {TotalRows:N0} rows";
        }
    }

    public string SummaryText => _summary?.CardSummaryText ?? string.Empty;

    public string GoToRowInput
    {
        get => _goToRowInput;
        set
        {
            if (_goToRowInput == value) return;
            _goToRowInput = value;
            OnPropertyChanged();
        }
    }

    public string StatusText
    {
        get => _statusText;
        private set
        {
            if (_statusText == value) return;
            _statusText = value;
            OnPropertyChanged();
        }
    }

    public string StatusColorHex
    {
        get => _statusColorHex;
        private set
        {
            if (_statusColorHex == value) return;
            _statusColorHex = value;
            OnPropertyChanged();
            OnPropertyChanged(nameof(StatusBrush));
        }
    }

    public Brush StatusBrush => (SolidColorBrush)new BrushConverter().ConvertFromString(_statusColorHex)!;

    public bool ButtonsEnabled
    {
        get => _buttonsEnabled;
        private set
        {
            if (_buttonsEnabled == value) return;
            _buttonsEnabled = value;
            OnPropertyChanged();
            UploadSpreadsheetCommand.RaiseCanExecuteChanged();
            ClearWorkspaceCommand.RaiseCanExecuteChanged();
            OpenKorberCommand.RaiseCanExecuteChanged();
            CloseBrowserCommand.RaiseCanExecuteChanged();
            RunLoadAuditCommand.RaiseCanExecuteChanged();
            ProcessShippingCommand.RaiseCanExecuteChanged();
            ExportPdfCommand.RaiseCanExecuteChanged();
            ExportExcelCommand.RaiseCanExecuteChanged();
            ConfigureCredentialsCommand.RaiseCanExecuteChanged();
        }
    }

    public string CredentialStatusLabel
    {
        get
        {
            var creds = _credentialService.ResolveCredentials();
            return creds is { IsComplete: true }
                ? $"Account: {creds.Username} | Fork: {creds.ForkId}"
                : "Credentials not configured";
        }
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    public void SetStatus(string message, string colorHex)
    {
        StatusText = message;
        StatusColorHex = colorHex;
    }

    public void CopyCellValue(string? value)
    {
        var cleaned = value?.Trim() ?? string.Empty;
        if (string.IsNullOrEmpty(cleaned))
            return;

        _dialogs.CopyTextToClipboard(cleaned);
        SetStatus($"Copied: {cleaned}", BlueHex);
    }

    public void HandleTableMouseWheel(int delta)
    {
        if (TotalRows <= RowsPerPage)
            return;

        const int step = 10;
        StartRow = delta < 0 ? StartRow + step : StartRow - step;
    }

    public void ExecuteClearWorkspace()
    {
        _allRows.Clear();
        VisibleRows.Clear();
        _summary = null;
        _startRow = 0;
        GoToRowInput = string.Empty;
        NotifyDataChanged();
        SetStatus("View cleared", AccentHex);
    }

    public async void ExecuteUploadSpreadsheet()
    {
        var path = _dialogs.OpenExcelFile();
        if (string.IsNullOrWhiteSpace(path))
            return;

        var doorLocation = _dialogs.PromptInput("Door Location", "Enter Door Location:");
        if (doorLocation is null)
            return;

        doorLocation = doorLocation.Trim();
        if (string.IsNullOrWhiteSpace(doorLocation))
        {
            _dialogs.ShowWarning("Door Location", "Door Location cannot be empty.");
            return;
        }

        await LoadSpreadsheetFromFileAsync(path, doorLocation);
    }

    public async Task LoadSpreadsheetFromFileAsync(string path, string doorLocation)
    {
        ButtonsEnabled = false;
        SetStatus("Starting Excel load...", BlueHex);

        try
        {
            SetStatus("Reading Excel file. Please continue using the UI...", BlueHex);
            var (rows, summary) = await Task.Run(() => _spreadsheetService.LoadAndPrepare(path, doorLocation));

            _dialogs.InvokeOnUiThread(() =>
            {
                _allRows.Clear();
                _allRows.AddRange(rows);
                _summary = summary;
                _startRow = 0;
                SetStatus("Preparing aligned data table...", BlueHex);
                NotifyDataChanged();
                RenderVisiblePage();
                SetStatus(summary.LoadedStatusText, EmeraldHex);
            });
        }
        catch (InvalidDataException ex)
        {
            _dialogs.InvokeOnUiThread(() =>
            {
                _dialogs.ShowError("Missing Column", ex.Message);
                SetStatus("Excel load failed: missing required columns", RedHex);
            });
        }
        catch (Exception ex)
        {
            _dialogs.InvokeOnUiThread(() =>
            {
                _dialogs.ShowError("Error", $"Could not load file.\n\n{ex.Message}");
                SetStatus($"Excel load failed: {ex.Message}", RedHex);
            });
        }
        finally
        {
            _dialogs.InvokeOnUiThread(() => ButtonsEnabled = true);
        }
    }

    public void ExecuteExportExcel()
    {
        if (_allRows.Count == 0)
        {
            _dialogs.ShowWarning("No Data", "No aligned table data to export. Upload Excel first.");
            return;
        }

        var defaultName = $"aligned_table_{DateTime.Now:yyyyMMdd_HHmmss}.xlsx";
        var savePath = _dialogs.SaveExcelFile(defaultName);
        if (string.IsNullOrWhiteSpace(savePath))
            return;

        try
        {
            _spreadsheetService.ExportExcel(_allRows, savePath);
            SetStatus($"Excel exported: {Path.GetFileName(savePath)}", GreenHex);
            _dialogs.ShowInfo("Export Excel", $"Excel file saved successfully:\n{savePath}");
        }
        catch (Exception ex)
        {
            _dialogs.ShowError("Export Excel Error", $"Could not export Excel.\n\n{ex.Message}");
            SetStatus($"Excel export failed: {ex.Message}", RedHex);
        }
    }

    public void ExecuteExportPdf()
    {
        if (_allRows.Count == 0)
        {
            _dialogs.ShowWarning("No Data", "No aligned table data to export. Upload Excel first.");
            return;
        }

        var defaultName = $"3PL_EFL_aligned_table_{DateTime.Now:yyyyMMdd_HHmmss}.pdf";
        var savePath = _dialogs.SavePdfFile(defaultName);
        if (string.IsNullOrWhiteSpace(savePath))
            return;

        try
        {
            _pdfExportService.ExportPdf(_allRows, savePath);
            SetStatus($"PDF exported: {Path.GetFileName(savePath)}", GreenHex);
            _dialogs.ShowInfo("Export PDF", $"PDF file saved successfully:\n{savePath}");
        }
        catch (Exception ex)
        {
            _dialogs.ShowError("Export PDF Error", $"Could not export PDF.\n\n{ex.Message}");
            SetStatus($"PDF export failed: {ex.Message}", RedHex);
        }
    }

    public void ExecuteConfigureCredentials()
    {
        var current = _credentialService.ResolveCredentials();
        _dialogs.PromptCredentials(current, _credentialService);
        OnPropertyChanged(nameof(CredentialStatusLabel));
    }

    public async void ExecuteOpenKorber()
    {
        if (!TryBeginWorker("Browser process is already running. Use BOT STOP to stop it.", out var cts))
            return;

        if (_allRows.Count == 0)
        {
            EndWorker(cts);
            _dialogs.ShowWarning("No Data", "Upload Excel first.");
            return;
        }

        var creds = EnsureCredentialsOrPrompt();
        if (creds is null)
        {
            EndWorker(cts);
            return;
        }

        string selectedWhId;
        try
        {
            selectedWhId = SpreadsheetService.GetValidatedFirstWarehouseId(_allRows);
        }
        catch (Exception ex)
        {
            EndWorker(cts);
            _dialogs.ShowError("Error", ex.Message);
            SetStatus($"Failed: {ex.Message}", RedHex);
            return;
        }

        ButtonsEnabled = false;
        SetStatus($"Opening browser to {selectedWhId} > EFL > OUTBOUND...", BlueHex);

        try
        {
            var result = await _automationService.OpenBrowserToOutboundAsync(
                _allRows.ToList(),
                creds,
                msg => _dialogs.InvokeOnUiThread(() => SetStatus(msg, BlueHex)),
                (title, msg) => _dialogs.InvokeOnUiThread(() => _dialogs.ShowError(title, msg)),
                cts.Token);

            _dialogs.InvokeOnUiThread(() =>
            {
                if (result.Success)
                {
                    _dialogs.ShowInfo("Ready", result.Message);
                    SetStatus(result.Message, GreenHex);
                }
                else if (cts.IsCancellationRequested)
                {
                    SetStatus("Stopped by BOT STOP", RedHex);
                }
                else
                {
                    _dialogs.ShowError("Error", result.Message);
                    SetStatus($"Failed: {result.Message}", RedHex);
                }
            });
        }
        catch (Exception ex)
        {
            _dialogs.InvokeOnUiThread(() =>
            {
                _dialogs.ShowError("Open Korber Error", ex.Message);
                SetStatus($"Open Korber error: {ex.Message}", RedHex);
            });
        }
        finally
        {
            EndWorker(cts);
            _dialogs.InvokeOnUiThread(() => ButtonsEnabled = true);
        }
    }

    public async void ExecuteRunLoadAudit()
    {
        if (!TryBeginWorker("A browser/BOT process is already running. Use BOT STOP to stop it.", out var cts))
            return;

        if (_allRows.Count == 0)
        {
            EndWorker(cts);
            _dialogs.ShowWarning("No Data", "Upload Excel first.");
            return;
        }

        var creds = EnsureCredentialsOrPrompt();
        if (creds is null)
        {
            EndWorker(cts);
            return;
        }

        ButtonsEnabled = false;
        SetStatus("Starting Load Audit loop...", BlueHex);

        try
        {
            var result = await _automationService.RunLoadAuditLoopAsync(
                _allRows.ToList(),
                creds,
                msg => _dialogs.InvokeOnUiThread(() => SetStatus(msg, BlueHex)),
                (rowIndex, value) => _dialogs.InvokeOnUiThread(() =>
                {
                    if (rowIndex >= 0 && rowIndex < _allRows.Count)
                        _allRows[rowIndex].LoadAuditStatus = value;
                }),
                (title, msg) => _dialogs.InvokeOnUiThread(() => _dialogs.ShowError(title, msg)),
                cts.Token);

            _dialogs.InvokeOnUiThread(() =>
            {
                if (result.Success)
                {
                    _dialogs.ShowInfo("Load Audit", result.Message);
                    SetStatus(result.Message, GreenHex);
                }
                else if (cts.IsCancellationRequested)
                {
                    SetStatus("Stopped by BOT STOP", RedHex);
                }
                else
                {
                    _dialogs.ShowError("Load Audit Error", result.Message);
                    SetStatus($"Load Audit failed: {result.Message}", RedHex);
                }
            });
        }
        catch (Exception ex)
        {
            _dialogs.InvokeOnUiThread(() =>
            {
                _dialogs.ShowError("Load Audit Error", ex.Message);
                SetStatus($"Load Audit error: {ex.Message}", RedHex);
            });
        }
        finally
        {
            EndWorker(cts);
            _dialogs.InvokeOnUiThread(() => ButtonsEnabled = true);
        }
    }

    public async void ExecuteProcessShipping()
    {
        if (!TryBeginWorker("A browser/BOT process is already running. Use BOT STOP to stop it.", out var cts))
            return;

        if (_allRows.Count == 0)
        {
            EndWorker(cts);
            _dialogs.ShowWarning("No Data", "Upload Excel first.");
            return;
        }

        var sealNumber = _dialogs.PromptInput("Seal Number", "Enter SEAL NUMBER")?.Trim();
        if (string.IsNullOrWhiteSpace(sealNumber))
        {
            EndWorker(cts);
            SetStatus("Shipping cancelled: Seal Number required", RedHex);
            return;
        }

        var creds = EnsureCredentialsOrPrompt();
        if (creds is null)
        {
            EndWorker(cts);
            return;
        }

        ButtonsEnabled = false;
        SetStatus("Starting Shipping loop...", AmberHex);

        try
        {
            var result = await _automationService.RunShippingLoopAsync(
                _allRows.ToList(),
                sealNumber,
                creds,
                msg => _dialogs.InvokeOnUiThread(() => SetStatus(msg, AmberHex)),
                (rowIndex, value) => _dialogs.InvokeOnUiThread(() =>
                {
                    if (rowIndex >= 0 && rowIndex < _allRows.Count)
                        _allRows[rowIndex].ShippingStatus = value;
                }),
                (title, msg) => _dialogs.InvokeOnUiThread(() => _dialogs.ShowError(title, msg)),
                cts.Token);

            _dialogs.InvokeOnUiThread(() =>
            {
                if (result.Success)
                {
                    _dialogs.ShowInfo("Shipping", result.Message);
                    SetStatus(result.Message, GreenHex);
                }
                else if (cts.IsCancellationRequested)
                {
                    SetStatus("Stopped by BOT STOP", RedHex);
                }
                else
                {
                    _dialogs.ShowError("Shipping Error", result.Message);
                    SetStatus($"Shipping failed: {result.Message}", RedHex);
                }
            });
        }
        catch (Exception ex)
        {
            _dialogs.InvokeOnUiThread(() =>
            {
                _dialogs.ShowError("Shipping Error", ex.Message);
                SetStatus($"Shipping error: {ex.Message}", RedHex);
            });
        }
        finally
        {
            EndWorker(cts);
            _dialogs.InvokeOnUiThread(() => ButtonsEnabled = true);
        }
    }

    public async void ExecuteCloseBrowser()
    {
        if (!TryBeginWorker("A browser/BOT process is already running. Use BOT STOP to stop it.", out var cts))
            return;

        if (!_automationService.HasActiveBrowser)
        {
            EndWorker(cts);
            SetStatus("No open browser", AccentHex);
            return;
        }

        var creds = _credentialService.ResolveCredentials();
        ButtonsEnabled = false;
        SetStatus("Close Browser: starting Cancel-back sequence...", CloseRedHex);

        try
        {
            var result = await _automationService.CloseBrowserAsync(
                creds,
                msg => _dialogs.InvokeOnUiThread(() => SetStatus(msg, CloseRedHex)),
                (title, msg) => _dialogs.InvokeOnUiThread(() => _dialogs.ShowError(title, msg)),
                cts.Token);

            _dialogs.InvokeOnUiThread(() =>
            {
                if (!result.Success)
                    SetStatus($"Close sequence warning: {result.Message}. Closing browser anyway...", RedHex);
                SetStatus("Browser closed successfully", GreenHex);
            });
        }
        catch (Exception ex)
        {
            _dialogs.InvokeOnUiThread(() =>
            {
                _dialogs.ShowError("Close Browser Error", ex.Message);
                SetStatus($"Close Browser error: {ex.Message}", RedHex);
            });
        }
        finally
        {
            EndWorker(cts);
            _dialogs.InvokeOnUiThread(() => ButtonsEnabled = true);
        }
    }

    public void ExecuteStopAutomation()
    {
        CancellationTokenSource? current;
        lock (_workerLock)
        {
            current = _activeCts;
        }

        SetStatus("BOT STOP pressed. Stopping browser/process...", RedHex);
        current?.Cancel();
        Task.Run(() => _automationService.ForceCloseBrowser());
        ButtonsEnabled = true;
        SetStatus("BOT stopped", RedHex);
    }

    private KorberCredentials? EnsureCredentialsOrPrompt()
    {
        var creds = _credentialService.ResolveCredentials();
        if (creds is { IsComplete: true })
            return creds;

        var configured = _dialogs.PromptCredentials(creds, _credentialService);
        OnPropertyChanged(nameof(CredentialStatusLabel));
        if (configured is { IsComplete: true })
            return configured;

        _dialogs.ShowError("AuditShip credentials missing", CredentialService.MissingCredentialsMessage);
        return null;
    }

    private bool TryBeginWorker(string alreadyRunningMessage, out CancellationTokenSource cts)
    {
        lock (_workerLock)
        {
            if (_isWorkerRunning)
            {
                cts = null!;
                _dialogs.ShowWarning("Already Running", alreadyRunningMessage);
                return false;
            }

            _isWorkerRunning = true;
            _activeCts = new CancellationTokenSource();
            cts = _activeCts;
            return true;
        }
    }

    private void EndWorker(CancellationTokenSource cts)
    {
        lock (_workerLock)
        {
            if (ReferenceEquals(_activeCts, cts))
                _activeCts = null;
            _isWorkerRunning = false;
        }
        cts.Dispose();
    }

    private int ClampStartRow(int value) => Math.Max(0, Math.Min(value, MaxStartRow));

    private void ExecutePreviousPage()
        => StartRow = ClampStartRow(StartRow - RowsPerPage);

    private void ExecuteNextPage()
        => StartRow = ClampStartRow(StartRow + RowsPerPage);

    private void ExecuteGoToRow()
    {
        if (!int.TryParse((GoToRowInput ?? string.Empty).Trim(), out var requestedRow))
        {
            SetStatus("Invalid row number", RedHex);
            return;
        }

        StartRow = ClampStartRow(requestedRow - 1);
    }

    private void RenderVisiblePage()
    {
        VisibleRows.Clear();
        if (TotalRows > 0)
        {
            var endRow = Math.Min(StartRow + RowsPerPage, TotalRows);
            for (var i = StartRow; i < endRow; i++)
                VisibleRows.Add(_allRows[i]);
        }

        OnPropertyChanged(nameof(PageInfoText));
        OnPropertyChanged(nameof(CanGoPrevious));
        OnPropertyChanged(nameof(CanGoNext));
        PreviousPageCommand.RaiseCanExecuteChanged();
        NextPageCommand.RaiseCanExecuteChanged();
    }

    private void NotifyDataChanged()
    {
        OnPropertyChanged(nameof(HasData));
        OnPropertyChanged(nameof(TotalRows));
        OnPropertyChanged(nameof(RowsPerPage));
        OnPropertyChanged(nameof(MaxStartRow));
        OnPropertyChanged(nameof(SliderMaximum));
        OnPropertyChanged(nameof(IsSliderEnabled));
        OnPropertyChanged(nameof(SummaryText));
        OnPropertyChanged(nameof(StartRow));
        OnPropertyChanged(nameof(PageInfoText));
        OnPropertyChanged(nameof(CanGoPrevious));
        OnPropertyChanged(nameof(CanGoNext));
        PreviousPageCommand.RaiseCanExecuteChanged();
        NextPageCommand.RaiseCanExecuteChanged();
    }

    private void OnPropertyChanged([CallerMemberName] string? propertyName = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
}
