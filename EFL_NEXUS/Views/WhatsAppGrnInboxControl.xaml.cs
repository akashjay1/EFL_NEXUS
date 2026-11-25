using System.Collections.ObjectModel;
using System.ComponentModel;
using System.IO;
using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using EflNexus.App.Controllers;
using EflNexus.App.Dialogs;
using EflNexus.App.Helpers;
using EflNexus.Core.GrnOcr;
using EflNexus.Core.WhatsApp;
using Microsoft.Data.Sqlite;
using UserControl = System.Windows.Controls.UserControl;

namespace EflNexus.App.Views;

public sealed class GrnInboxRowViewModel : INotifyPropertyChanged
{
    private string _gatepass = string.Empty;
    private string _status = string.Empty;
    private string _runState = string.Empty;
    private string _received = string.Empty;

    public string Key { get; init; } = string.Empty;
    public long? DocumentId { get; init; }
    public long? SourceId { get; init; }

    public string Gatepass
    {
        get => _gatepass;
        set { if (_gatepass != value) { _gatepass = value; OnPropertyChanged(); } }
    }

    public string Status
    {
        get => _status;
        set { if (_status != value) { _status = value; OnPropertyChanged(); } }
    }

    public string RunState
    {
        get => _runState;
        set { if (_runState != value) { _runState = value; OnPropertyChanged(); } }
    }

    public string Received
    {
        get => _received;
        set { if (_received != value) { _received = value; OnPropertyChanged(); } }
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    private void OnPropertyChanged([CallerMemberName] string? name = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}

public partial class WhatsAppGrnInboxControl : UserControl
{
    private WhatsAppController? _controller;
    private WhatsAppGrnStore? _store;
    private IReadOnlyDictionary<string, IKorberLaneTarget> _lanes = new Dictionary<string, IKorberLaneTarget>();
    private Func<IReadOnlyDictionary<string, IKorberLaneTarget>>? _ensureLanes;
    private DispatcherTimer? _pollTimer;

    private long? _selectedId;
    private long? _selectedSourceId;
    private (string State, string ImagePath, string ExtractionJson)? _selectedRevision;
    private readonly Dictionary<long, string> _runStates = [];
    private long _version = -1;
    private bool _closed;
    private bool _dirty;
    private bool _loading;
    private bool _suppressSelection;

    public ObservableCollection<GrnInboxRowViewModel> Rows { get; } = [];

    public WhatsAppGrnInboxControl()
    {
        InitializeComponent();
        WarehouseCombo.ItemsSource = WhatsAppGrnStore.GrnWarehouses;
        DocumentsGrid.ItemsSource = Rows;
    }

    public WhatsAppGrnInboxControl(
        WhatsAppController controller,
        IReadOnlyDictionary<string, IKorberLaneTarget> lanes,
        Func<IReadOnlyDictionary<string, IKorberLaneTarget>>? ensureLanes = null) : this()
    {
        Configure(controller, lanes, ensureLanes);
    }

    public void Configure(
        WhatsAppController controller,
        IReadOnlyDictionary<string, IKorberLaneTarget> lanes,
        Func<IReadOnlyDictionary<string, IKorberLaneTarget>>? ensureLanes = null)
    {
        _controller = controller;
        _lanes = lanes;
        _ensureLanes = ensureLanes;
        _store = new WhatsAppGrnStore(controller.Store.FilePath);

        RecoverActiveGatepasses();
        PopulateLaneCombo();

        _version = -1;
        PollOnce();

        _pollTimer?.Stop();
        _pollTimer = new DispatcherTimer(DispatcherPriority.Background, Dispatcher)
        {
            Interval = TimeSpan.FromMilliseconds(250)
        };
        _pollTimer.Tick += (_, _) => PollOnce();
        _pollTimer.Start();
    }

    private void PopulateLaneCombo()
    {
        var keys = _lanes.Keys.ToList();
        LaneCombo.ItemsSource = keys;
        if (keys.Count > 0 && LaneCombo.SelectedItem is null)
            LaneCombo.SelectedIndex = 0;
    }

    private void RecoverActiveGatepasses()
    {
        if (_store is null) return;
        var activeRunIds = _lanes.Values
            .Select(l => l.WhatsappRunId)
            .Where(id => !string.IsNullOrWhiteSpace(id))
            .ToHashSet(StringComparer.Ordinal);
        _store.RecoverGatepassRuns(activeRunIds, "GRN");
    }

    private void OnFieldEdited()
    {
        if (!_loading)
        {
            _dirty = true;
            ConfirmedCheck.IsChecked = false;
        }
    }

    private void WarehouseCombo_SelectionChanged(object sender, SelectionChangedEventArgs e) => OnFieldEdited();
    private void GatePassBox_TextChanged(object sender, TextChangedEventArgs e) => OnFieldEdited();

    private void PollOnce()
    {
        if (_closed || _store is null)
            return;

        try
        {
            long version = _store.Version();
            if (version != _version)
            {
                _version = version;
                Refresh();
            }

            var errors = _store.CaptureErrors();
            var notice = _store.Setting("grn_capture_notice", string.Empty);
            var ocrStatus = _store.Setting("grn_ocr_status", string.Empty);
            if (ocrStatus.StartsWith("OCR worker stopped", StringComparison.Ordinal))
                notice = ocrStatus;

            var group = _store.Setting<WhatsAppGroupSetting?>("group", null);
            var groupId = group?.Id ?? string.Empty;
            if (string.IsNullOrEmpty(_store.DefaultWarehouse(groupId)))
                notice = "Choose and save the default GRN warehouse above before importing photos.";

            var cloudCfg = GrnCloudOcrEngine.CloudSettings(_store);
            int uploadsToday = GrnCloudOcrEngine.UsageToday(_store);
            var cloudStatusText =
                $"Cloud OCR: {(cloudCfg.Enabled ? "enabled" : "disabled")}; uploads today: {uploadsToday} / {(cloudCfg.DailyLimit > 0 ? cloudCfg.DailyLimit : "not set")}";

            var statusLines = new List<string>();
            void AddIfNotEmpty(string s) { if (!string.IsNullOrWhiteSpace(s)) statusLines.Add(s); }

            AddIfNotEmpty(notice);
            AddIfNotEmpty(_store.Setting("grn_scan_status", string.Empty));
            AddIfNotEmpty(_store.Setting("done_reply_notice", string.Empty));
            AddIfNotEmpty(_store.Setting("grn_cloud_status", string.Empty));
            statusLines.Add(cloudStatusText);
            foreach (var err in errors.Take(3))
                statusLines.Add($"{err.Source}: {err.CaptureError}");

            CaptureStatusText.Text = string.Join("\n", statusLines);
        }
        catch (Exception exc) when (exc is SqliteException or IOException)
        {
            StatusText.Text = $"Could not refresh GRN inbox: {exc.Message}";
        }
    }

    public void Refresh()
    {
        if (_store is null) return;

        if (_selectedSourceId.HasValue)
        {
            var src = _store.GetSource(_selectedSourceId.Value);
            if (src?.DocumentId is { } promotedDocId)
            {
                _selectedId = promotedDocId;
                _selectedSourceId = null;
                LoadSelected();
            }
        }

        var desired = new List<(string Key, long? DocId, long? SourceId, string Gatepass, string Status, string RunState, string Received)>();
        var previousStates = new Dictionary<long, string>(_runStates);
        _runStates.Clear();

        foreach (var source in _store.PendingEntries())
        {
            var state = source.IncomingVerified != 0 ? "Waiting for original photo" : "Sender verification required";
            if (!string.IsNullOrEmpty(source.CaptureError))
                state = source.CaptureError;
            if (WhatsAppGrnStore.GrnMessageEpoch(source.MessageTime) is null)
                state = "Received time unverified; not scanned";
            else if (!WhatsAppGrnStore.GrnPhotoIsRecent(source.MessageTime))
                state = "Outside last hour; not scanned";

            desired.Add((
                $"source:{source.Id}",
                null,
                source.Id,
                "Incoming photo",
                state,
                "New",
                WhatsAppGdnParser.ReceivedLabel(source.MessageTime, source.CapturedAt)));
        }

        foreach (var record in _store.Documents())
        {
            _runStates[record.Id] = record.RunState;
            var state = record.Action != "New" ? record.Action : record.State;
            desired.Add((
                record.Id.ToString(),
                record.Id,
                null,
                string.IsNullOrEmpty(record.Gatepass) ? "Unread" : record.Gatepass,
                state,
                record.RunState,
                WhatsAppGdnParser.ReceivedLabel(record.MessageTime, record.ReceivedAt)));
        }

        var wantedKeys = desired.Select(d => d.Key).ToHashSet(StringComparer.Ordinal);
        string? selectionKey = _selectedId.HasValue
            ? _selectedId.Value.ToString()
            : (_selectedSourceId.HasValue ? $"source:{_selectedSourceId.Value}" : null);

        if (selectionKey is not null && !wantedKeys.Contains(selectionKey))
            ResetSelection();

        _suppressSelection = true;
        try
        {
            for (int i = Rows.Count - 1; i >= 0; i--)
            {
                if (!wantedKeys.Contains(Rows[i].Key))
                    Rows.RemoveAt(i);
            }

            for (int index = 0; index < desired.Count; index++)
            {
                var item = desired[index];
                var existingIndex = -1;
                for (int j = 0; j < Rows.Count; j++)
                {
                    if (Rows[j].Key == item.Key)
                    {
                        existingIndex = j;
                        break;
                    }
                }

                if (existingIndex < 0)
                {
                    Rows.Insert(index, new GrnInboxRowViewModel
                    {
                        Key = item.Key,
                        DocumentId = item.DocId,
                        SourceId = item.SourceId,
                        Gatepass = item.Gatepass,
                        Status = item.Status,
                        RunState = item.RunState,
                        Received = item.Received
                    });
                }
                else
                {
                    var row = Rows[existingIndex];
                    row.Gatepass = item.Gatepass;
                    row.Status = item.Status;
                    row.RunState = item.RunState;
                    row.Received = item.Received;
                    if (existingIndex != index)
                        Rows.Move(existingIndex, index);
                }
            }

            if (_selectedId.HasValue)
            {
                var selKey = _selectedId.Value.ToString();
                var match = Rows.FirstOrDefault(r => r.Key == selKey);
                if (match is not null)
                {
                    DocumentsGrid.SelectedItem = match;
                    var current = _store.Document(_selectedId.Value);
                    if (current is not null)
                    {
                        var revision = (current.State, current.ImagePath, current.ExtractionJson);
                        if (revision != _selectedRevision && !_dirty)
                            LoadSelected();
                        if (previousStates.TryGetValue(_selectedId.Value, out var prevState) &&
                            prevState == "Running" && current.RunState != "Running")
                        {
                            StatusText.Text = $"GRN state: {current.RunState}. You can use Run Gatepass again.";
                        }
                    }
                }
            }
        }
        finally
        {
            _suppressSelection = false;
        }
    }

    public void ResetSelection()
    {
        _selectedId = null;
        _selectedSourceId = null;
        _selectedRevision = null;

        _suppressSelection = true;
        try { DocumentsGrid.SelectedItem = null; }
        finally { _suppressSelection = false; }

        _loading = true;
        WarehouseCombo.SelectedItem = null;
        GatePassBox.Text = string.Empty;
        _loading = false;
        _dirty = false;
        ConfirmedCheck.IsChecked = false;

        SetPlaceholder(OriginalImage, OriginalPlaceholderText, "Select a photo");
        SetPlaceholder(CropImage, CropPlaceholderText, "Select a photo");
        WarningsText.Text = "Select a document to review.";
    }

    private void ClearList_Click(object sender, RoutedEventArgs e)
    {
        if (_store is null) return;
        try
        {
            int count = _store.ClearList();
            ResetSelection();
            Refresh();
            StatusText.Text = $"Cleared {count} photos from this list. History and duplicate protection are retained.";
        }
        catch (SqliteException exc)
        {
            StatusText.Text = $"Could not clear the list: {exc.Message}";
        }
    }

    private void DocumentsGrid_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_suppressSelection || _store is null || DocumentsGrid.SelectedItem is not GrnInboxRowViewModel row)
            return;

        if (row.SourceId.HasValue)
        {
            _selectedSourceId = row.SourceId.Value;
            _selectedId = null;
            var source = _store.GetSource(_selectedSourceId.Value);

            _loading = true;
            WarehouseCombo.SelectedItem = source is not null && !string.IsNullOrEmpty(source.Warehouse)
                ? source.Warehouse
                : null;
            GatePassBox.Text = string.Empty;
            _loading = false;
            _dirty = false;
            ConfirmedCheck.IsChecked = false;

            SetPlaceholder(OriginalImage, OriginalPlaceholderText, "Waiting for the original photo");
            SetPlaceholder(CropImage, CropPlaceholderText, "Waiting for the original photo");

            WarningsText.Text = !string.IsNullOrEmpty(source?.CaptureError)
                ? source.CaptureError
                : (source?.IncomingVerified != 0
                    ? "Waiting for WhatsApp to load the original photo."
                    : "Sender is not verified as incoming. Keep the message and adjacent incoming messages visible.");
            StatusText.Text = "Photo detected and saved in the inbox. Download and extraction are pending.";

            if (source is not null && !WhatsAppGrnStore.GrnPhotoIsRecent(source.MessageTime))
            {
                WarningsText.Text = "Only photos with a verified WhatsApp received time within the last hour are scanned.";
                StatusText.Text = "Photo skipped by the last-hour capture filter. Existing history is retained.";
            }
        }
        else if (row.DocumentId.HasValue && row.DocumentId.Value != _selectedId)
        {
            _selectedId = row.DocumentId.Value;
            _selectedSourceId = null;
            LoadSelected();
        }
    }

    private static void SetPlaceholder(System.Windows.Controls.Image img, TextBlock placeholder, string message)
    {
        img.Source = null;
        img.Visibility = Visibility.Collapsed;
        placeholder.Text = message;
        placeholder.Visibility = Visibility.Visible;
    }

    private static void ShowBitmap(System.Windows.Controls.Image img, TextBlock placeholder, string? path)
    {
        var bmp = ImageLoader.LoadOrientedBitmap(path);
        if (bmp is not null)
        {
            img.Source = bmp;
            img.Visibility = Visibility.Visible;
            placeholder.Visibility = Visibility.Collapsed;
        }
        else
        {
            SetPlaceholder(img, placeholder, !string.IsNullOrEmpty(path) ? "Image unavailable" : "No header detected");
        }
    }

    public void LoadSelected()
    {
        if (_store is null || !_selectedId.HasValue)
            return;

        var record = _store.Document(_selectedId.Value);
        if (record is null || !string.IsNullOrEmpty(record.HiddenReason))
        {
            ResetSelection();
            return;
        }

        _loading = true;
        WarehouseCombo.SelectedItem = WhatsAppGrnStore.GrnWarehouses.Contains(record.Warehouse, StringComparer.Ordinal)
            ? record.Warehouse
            : null;
        GatePassBox.Text = record.Gatepass;
        _loading = false;
        ConfirmedCheck.IsChecked = false;
        _dirty = false;
        _selectedRevision = (record.State, record.ImagePath, record.ExtractionJson);

        ShowBitmap(OriginalImage, OriginalPlaceholderText, record.ImagePath);
        var headerPath = GetExtractionString(record.Extraction, "header_path");
        ShowBitmap(CropImage, CropPlaceholderText, headerPath);

        var warnings = new List<string>(GetExtractionArray(record.Extraction, "warnings"));
        var ocrCandidates = GetExtractionArray(record.Extraction, "ocr_candidates");
        if (ocrCandidates.Count > 0)
            warnings.Add("Printed reading: " + string.Join(", ", ocrCandidates));

        var barcodeCandidates = GetExtractionArray(record.Extraction, "barcode_candidates");
        if (barcodeCandidates.Count > 0)
            warnings.Add("Header barcode: " + string.Join(", ", barcodeCandidates));

        var azureCandidates = GetExtractionArray(record.Extraction, "azure_candidates");
        if (azureCandidates.Count > 0)
            warnings.Add("Azure reading: " + string.Join(", ", azureCandidates));

        var spaceCandidates = GetExtractionArray(record.Extraction, "ocr_space_candidates");
        if (spaceCandidates.Count > 0)
            warnings.Add("OCR.space reading: " + string.Join(", ", spaceCandidates));

        var recognitionSource = GetExtractionString(record.Extraction, "recognition_source");
        if (!string.IsNullOrEmpty(recognitionSource))
            warnings.Insert(0, "Reading source: " + recognitionSource);

        if (!string.IsNullOrEmpty(record.Gatepass) &&
            _store.Documents().Any(other =>
                other.Id != record.Id && other.Warehouse == record.Warehouse && other.Gatepass == record.Gatepass))
        {
            warnings.Add("Another photo has this warehouse and gate pass. Compare the originals.");
        }

        long copies = _store.GetSourceCountForDocument(record.Id);
        if (copies > 1)
            warnings.Add($"This same image was received {copies} times; it is one review record.");

        WarningsText.Text = warnings.Count > 0
            ? string.Join("\n", warnings)
            : "Compare every digit and the warehouse with the original.";
        StatusText.Text = $"{record.State} — {record.Action}. Save edits before selecting another photo.";
    }

    private static string GetExtractionString(IReadOnlyDictionary<string, JsonElement> dict, string key)
    {
        if (dict.TryGetValue(key, out var el) && el.ValueKind == JsonValueKind.String)
            return el.GetString() ?? string.Empty;
        return string.Empty;
    }

    private static List<string> GetExtractionArray(IReadOnlyDictionary<string, JsonElement> dict, string key)
    {
        var list = new List<string>();
        if (dict.TryGetValue(key, out var el) && el.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in el.EnumerateArray())
            {
                if (item.ValueKind == JsonValueKind.String)
                {
                    var str = item.GetString();
                    if (!string.IsNullOrEmpty(str))
                        list.Add(str);
                }
            }
        }
        return list;
    }

    private (string Warehouse, string Gatepass) CurrentValues()
        => ((WarehouseCombo.SelectedItem?.ToString() ?? string.Empty).Trim().ToUpperInvariant(),
            (GatePassBox.Text ?? string.Empty).Trim());

    private void SaveReview_Click(object sender, RoutedEventArgs e) => SaveReview();
    private void FillForm_Click(object sender, RoutedEventArgs e) => FillForm(startRun: false);
    private void RunGatepass_Click(object sender, RoutedEventArgs e) => FillForm(startRun: true);

    public bool SaveReview()
    {
        if (_store is null || !_selectedId.HasValue)
        {
            StatusText.Text = "Select a photo first.";
            return false;
        }
        var record = _store.Document(_selectedId.Value);
        if (record is null || !string.IsNullOrEmpty(record.HiddenReason))
        {
            ResetSelection();
            StatusText.Text = "This photo was cleared or marked DONE.";
            return false;
        }
        if (record.State == "Awaiting original photo" || GrnCloudOcrEngine.PendingStates.Contains(record.State, StringComparer.Ordinal))
        {
            StatusText.Text = "Wait for original-photo capture and cloud reading before saving the review.";
            return false;
        }
        if (record.RunState == "Running" || record.Action.StartsWith("Replaced", StringComparison.Ordinal))
        {
            StatusText.Text = "This document is running or has been replaced. Select an idle active photo.";
            return false;
        }

        var (warehouse, gatepass) = CurrentValues();
        var errors = WhatsAppGrnStore.ValidateGrnFields(warehouse, gatepass);
        bool confirmed = ConfirmedCheck.IsChecked == true;
        if (errors.Count > 0 || !confirmed)
        {
            var msg = new List<string>(errors);
            if (!confirmed)
                msg.Add("Check the photo, then tick the review confirmation.");
            StatusText.Text = string.Join("\n", msg);
            return false;
        }

        try
        {
            _store.SaveGrnReview(_selectedId.Value, warehouse, gatepass);
            _dirty = false;
            Refresh();
            StatusText.Text = "Review saved. Fill GRN Form when ready.";
            return true;
        }
        catch (Exception exc) when (exc is ArgumentException or SqliteException)
        {
            StatusText.Text = $"Review could not be saved: {exc.Message}";
            return false;
        }
    }

    public bool FillForm(bool startRun = false)
    {
        RecoverActiveGatepasses();
        if (_store is null)
            return false;
        if (ConfirmedCheck.IsChecked != true)
        {
            StatusText.Text = "Check the photo and warehouse, then tick the review confirmation.";
            return false;
        }
        if (_lanes.Count == 0 && _ensureLanes is not null)
        {
            _lanes = _ensureLanes();
            PopulateLaneCombo();
        }

        var (warehouse, gatepass) = CurrentValues();
        var laneName = LaneCombo.SelectedItem?.ToString() ?? string.Empty;

        try
        {
            WhatsAppGrnStore.FillGrnRequest(_store, _selectedId, warehouse, gatepass, laneName, _lanes, allowRepeat: startRun);
            if (startRun && _selectedId.HasValue)
                WhatsAppGrnStore.LaunchGatepass(_store, _selectedId.Value, "GRN", laneName, _lanes[laneName]);

            _dirty = false;
            Refresh();
            StatusText.Text = startRun
                ? $"GRN running in {laneName}. You can run it again after it finishes or stops."
                : $"Filled {laneName}. Open that lane tab and click Create GRN when ready.";
            return true;
        }
        catch (Exception exc) when (exc is ArgumentException or InvalidOperationException or IOException or SqliteException)
        {
            Refresh();
            StatusText.Text = exc.Message;
            return false;
        }
    }

    private void ImportVisible_Click(object sender, RoutedEventArgs e)
    {
        if (_store is null) return;
        var group = _store.Setting<WhatsAppGroupSetting?>("group", null);
        if (group is null || string.IsNullOrEmpty(group.Id))
        {
            StatusText.Text = "Select a WhatsApp group before scanning GRNs.";
            return;
        }
        if (string.IsNullOrEmpty(_store.DefaultWarehouse(group.Id)))
        {
            StatusText.Text = "Choose and save the default GRN warehouse above first.";
            return;
        }
        _controller?.Start();
        if (!string.IsNullOrEmpty(_controller?.RunId))
            _store.Command(_controller.RunId, "import_photos");
        StatusText.Text = "Scanning loaded incoming GRN photos received within the last hour. Older photos and unverified received times are skipped.";
    }

    private void RetryCapture_Click(object sender, RoutedEventArgs e)
    {
        if (_store is null) return;
        try
        {
            if (_selectedId.HasValue)
                _store.RefreshPhoto(_selectedId.Value, recentOnly: true);
            _store.Retry();
        }
        catch (Exception exc) when (exc is ArgumentException or SqliteException)
        {
            StatusText.Text = exc.Message;
            return;
        }
        _controller?.Start();
        StatusText.Text = "Capture retry requested. Keep the photo message loaded in the Browser tab.";
    }

    private void RetryExtraction_Click(object sender, RoutedEventArgs e)
    {
        if (_store is null || !_selectedId.HasValue)
            return;
        var doc = _store.Document(_selectedId.Value);
        if (doc?.State == "Awaiting original photo")
        {
            StatusText.Text = "Wait for original-photo capture before retrying extraction.";
            return;
        }
        _store.Retry(_selectedId.Value);
        _controller?.Start();
        if (!string.IsNullOrEmpty(_controller?.RunId))
            _store.Command(_controller.RunId, "retry_ocr");
        StatusText.Text = "Extraction retry requested. Saved review corrections are preserved.";
    }

    private void OcrSettings_Click(object sender, RoutedEventArgs e)
    {
        if (_store is null) return;
        var dlg = new GrnOcrSettingsDialog(Window.GetWindow(this), _store);
        dlg.ShowDialog();
    }

    private void RetryCloud_Click(object sender, RoutedEventArgs e)
    {
        if (_store is null || !_selectedId.HasValue)
        {
            StatusText.Text = "Select an unreviewed photo with a previous cloud request.";
            return;
        }
        try
        {
            GrnCloudOcrEngine.RetryCloud(_store, _selectedId.Value);
            _controller?.Start();
            if (!string.IsNullOrEmpty(_controller?.RunId))
                _store.Command(_controller.RunId, "retry_cloud");
            Refresh();
            StatusText.Text = "Cloud retry requested. OCR.space receives a new upload if no completed result is cached.";
        }
        catch (Exception exc) when (exc is ArgumentException or SqliteException)
        {
            StatusText.Text = exc.Message;
        }
    }

    private void ViewFullPhoto_Click(object sender, RoutedEventArgs e)
    {
        if (_store is null || !_selectedId.HasValue)
            return;
        var record = _store.Document(_selectedId.Value);
        var win = new FullPhotoWindow(Window.GetWindow(this), record?.ImagePath);
        win.Show();
    }

    public void Shutdown()
    {
        if (_closed) return;
        _closed = true;
        if (_pollTimer is not null)
        {
            _pollTimer.Stop();
            _pollTimer = null;
        }
        _store?.Close();
    }
}
