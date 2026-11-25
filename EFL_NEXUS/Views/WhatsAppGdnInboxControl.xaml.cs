using System.Collections.ObjectModel;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using EflNexus.App.Controllers;
using EflNexus.Core.WhatsApp;
using Microsoft.Data.Sqlite;
using UserControl = System.Windows.Controls.UserControl;

namespace EflNexus.App.Views;

public sealed class GdnInboxRowViewModel
{
    public long Id { get; init; }
    public string Gatepass { get; init; } = string.Empty;
    public string Source { get; init; } = string.Empty;
    public string RunState { get; init; } = string.Empty;
    public string Received { get; init; } = string.Empty;
}

public partial class WhatsAppGdnInboxControl : UserControl
{
    private WhatsAppGdnStore? _store;
    private IReadOnlyDictionary<string, IKorberLaneTarget> _lanes = new Dictionary<string, IKorberLaneTarget>();
    private WhatsAppController? _controller;
    private Func<IReadOnlyDictionary<string, IKorberLaneTarget>>? _ensureLanes;
    private DispatcherTimer? _pollTimer;

    private long? _selectedId;
    private readonly Dictionary<long, string> _runStates = [];
    private long _lastVersion = -1;
    private bool _closed;
    private bool _suppressSelection;

    public ObservableCollection<GdnInboxRowViewModel> Rows { get; } = [];

    public WhatsAppGdnInboxControl()
    {
        InitializeComponent();
        RequestsGrid.ItemsSource = Rows;
    }

    public WhatsAppGdnInboxControl(
        IReadOnlyDictionary<string, IKorberLaneTarget> lanes,
        WhatsAppGdnStore? store = null,
        WhatsAppController? controller = null,
        Func<IReadOnlyDictionary<string, IKorberLaneTarget>>? ensureLanes = null) : this()
    {
        Configure(lanes, store, controller, ensureLanes);
    }

    public void Configure(
        IReadOnlyDictionary<string, IKorberLaneTarget> lanes,
        WhatsAppGdnStore? store = null,
        WhatsAppController? controller = null,
        Func<IReadOnlyDictionary<string, IKorberLaneTarget>>? ensureLanes = null)
    {
        _lanes = lanes;
        _store = store ?? new WhatsAppGdnStore();
        _controller = controller;
        _ensureLanes = ensureLanes;

        RecoverActiveGatepasses();
        PopulateLaneCombo();
        Refresh();

        try { _lastVersion = _store.Version(); } catch { _lastVersion = 0; }

        _pollTimer?.Stop();
        _pollTimer = new DispatcherTimer(DispatcherPriority.Background, Dispatcher)
        {
            Interval = TimeSpan.FromMilliseconds(750)
        };
        _pollTimer.Tick += PollTimer_Tick;
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
        if (_store is null)
            return;
        var activeRunIds = _lanes.Values
            .Select(l => l.WhatsappRunId)
            .Where(id => !string.IsNullOrWhiteSpace(id))
            .ToHashSet(StringComparer.Ordinal);
        _store.RecoverGatepassRuns(activeRunIds, "GDN");
    }

    private void PollTimer_Tick(object? sender, EventArgs e)
    {
        if (_closed || _store is null)
            return;
        try
        {
            var version = _store.Version();
            if (version != _lastVersion)
            {
                _lastVersion = version;
                Refresh();
            }
        }
        catch (SqliteException exc)
        {
            StatusText.Text = $"Could not refresh inbox ({exc.Message}).";
        }
    }

    public void Refresh(long? selectId = null)
    {
        if (_store is null)
            return;

        var selected = selectId ?? _selectedId;
        var previousStates = new Dictionary<long, string>(_runStates);
        _runStates.Clear();

        var records = _store.Records();
        _suppressSelection = true;
        try
        {
            Rows.Clear();
            foreach (var record in records)
            {
                _runStates[record.Id] = record.RunState;
                Rows.Add(new GdnInboxRowViewModel
                {
                    Id = record.Id,
                    Gatepass = record.Fields.TryGetValue("gatepass", out var gp) ? gp : string.Empty,
                    Source = record.Source,
                    RunState = record.RunState,
                    Received = WhatsAppGdnParser.ReceivedLabel(record.MessageTime, record.ReceivedAt)
                });
            }

            if (selected.HasValue)
            {
                var match = Rows.FirstOrDefault(r => r.Id == selected.Value);
                if (match is not null)
                {
                    RequestsGrid.SelectedItem = match;
                    RequestsGrid.ScrollIntoView(match);
                    if (_runStates.TryGetValue(selected.Value, out var state) &&
                        previousStates.TryGetValue(selected.Value, out var prevState) &&
                        prevState == "Running" && state != "Running")
                    {
                        StatusText.Text = $"GDN state: {state}. You can use Run Gatepass again.";
                    }
                }
                else
                {
                    ResetSelection();
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
        _suppressSelection = true;
        try
        {
            RequestsGrid.SelectedItem = null;
        }
        finally
        {
            _suppressSelection = false;
        }
        WhBox.Text = string.Empty;
        ClientBox.Text = string.Empty;
        GatePassBox.Text = string.Empty;
        DeliveryBox.Text = string.Empty;
        SealBox.Text = string.Empty;
        DoorText.Text = string.Empty;
        RawTextBox.Text = string.Empty;
        WarningsText.Text = "Select a request to review.";
    }

    private void ClearList_Click(object sender, RoutedEventArgs e)
    {
        if (_store is null) return;
        try
        {
            int count = _store.ClearList();
            ResetSelection();
            Refresh();
            StatusText.Text = $"Cleared {count} requests from this list. History and duplicate protection are retained.";
        }
        catch (SqliteException exc)
        {
            StatusText.Text = $"Could not clear the list: {exc.Message}";
        }
    }

    private void RequestsGrid_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_suppressSelection || RequestsGrid.SelectedItem is not GdnInboxRowViewModel row)
            return;
        if (row.Id == _selectedId)
            return; // Incoming requests must not overwrite unsaved review edits.
        _selectedId = row.Id;
        LoadSelected();
    }

    public void LoadSelected()
    {
        if (_store is null || !_selectedId.HasValue)
            return;

        var record = _store.Get(_selectedId.Value);
        if (record is null || !string.IsNullOrEmpty(record.HiddenReason))
        {
            ResetSelection();
            return;
        }

        WhBox.Text = record.Fields.TryGetValue("warehouse", out var wh) ? wh : string.Empty;
        ClientBox.Text = record.Fields.TryGetValue("client", out var cli) ? cli : string.Empty;
        GatePassBox.Text = record.Fields.TryGetValue("gatepass", out var gp) ? gp : string.Empty;
        DeliveryBox.Text = record.Fields.TryGetValue("delivery_location", out var deliv) ? deliv : string.Empty;
        SealBox.Text = record.Fields.TryGetValue("seal", out var seal) ? seal : string.Empty;
        DoorText.Text = record.Fields.TryGetValue("door_location", out var door) ? door : string.Empty;
        RawTextBox.Text = record.RawText;

        ShowWarnings(record, record.Fields);
    }

    private Dictionary<string, string> ReadEditorFields()
    {
        return new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["warehouse"] = (WhBox.Text ?? string.Empty).Trim().ToUpperInvariant(),
            ["client"] = (ClientBox.Text ?? string.Empty).Trim(),
            ["gatepass"] = (GatePassBox.Text ?? string.Empty).Trim(),
            ["delivery_location"] = (DeliveryBox.Text ?? string.Empty).Trim(),
            ["seal"] = (SealBox.Text ?? string.Empty).Trim(),
            ["door_location"] = DoorText.Text ?? string.Empty
        };
    }

    private IReadOnlySet<string> Warehouses()
    {
        if (_lanes.Count == 0 && _ensureLanes is not null)
        {
            _lanes = _ensureLanes();
            PopulateLaneCombo();
        }
        var set = new HashSet<string>(StringComparer.Ordinal);
        foreach (var lane in _lanes.Values)
        {
            foreach (var v in lane.AvailableWarehouses)
                set.Add(v.ToUpperInvariant());
        }
        return set;
    }

    private void ShowWarnings(GdnRequestRecord record, IReadOnlyDictionary<string, string> fields)
    {
        if (_store is null) return;
        var warnings = new List<string>(record.Warnings);
        warnings.AddRange(WhatsAppGdnParser.ValidateFields(fields, Warehouses()));
        if (_store.Related(fields, record.Id).Count > 0)
            warnings.Add("Another request uses this warehouse, client, and gate pass. Compare the originals.");

        WarningsText.Text = warnings.Count > 0
            ? string.Join("\n", warnings)
            : "Check the values against the original, then fill the form or queue.";
    }

    public long? ImportMessage(string text, string source = "Clipboard", string messageId = "", bool select = true)
    {
        if (_store is null) return null;
        var (recordId, result) = _store.Add(text, source, messageId);
        if (recordId.HasValue)
        {
            StatusText.Text = result;
            Refresh(select ? recordId : null);
            if (select)
            {
                _selectedId = recordId;
                LoadSelected();
            }
        }
        else if (select)
        {
            StatusText.Text = result;
        }
        return recordId;
    }

    private void ImportPasted_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            ImportMessage(PasteTextBox.Text ?? string.Empty, source: "Pasted text");
        }
        catch (Exception exc) when (exc is IOException or SqliteException)
        {
            ShowError("Import failed", exc.Message);
        }
    }

    private void ImportClipboard_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            if (!System.Windows.Clipboard.ContainsText())
            {
                StatusText.Text = "Clipboard has no text. Copy a WhatsApp message first.";
                return;
            }
            var clipText = System.Windows.Clipboard.GetText();
            ImportMessage(clipText, source: "Clipboard");
        }
        catch (Exception exc) when (exc is IOException or SqliteException or System.Runtime.InteropServices.ExternalException)
        {
            ShowError("Import failed", exc.Message);
        }
    }

    private void SaveReview_Click(object sender, RoutedEventArgs e) => SaveReview();
    private void FillForm_Click(object sender, RoutedEventArgs e) => ApplyRequest(enqueue: false, startRun: false);
    private void RunGatepass_Click(object sender, RoutedEventArgs e) => ApplyRequest(enqueue: false, startRun: true);
    private void AddToQueue_Click(object sender, RoutedEventArgs e) => ApplyRequest(enqueue: true, startRun: false);

    public void SaveReview()
    {
        if (_store is null || !_selectedId.HasValue)
        {
            StatusText.Text = "Select a request first.";
            return;
        }
        var record = _store.Get(_selectedId.Value);
        if (record is null || !string.IsNullOrEmpty(record.HiddenReason))
        {
            ResetSelection();
            StatusText.Text = "This request was cleared or marked DONE.";
            return;
        }
        if (record.RunState == "Running")
        {
            StatusText.Text = "This request is running. Wait for it to finish or stop its lane.";
            return;
        }
        var fields = ReadEditorFields();
        try
        {
            _store.SaveReview(_selectedId.Value, fields);
        }
        catch (Exception exc) when (exc is ArgumentException or SqliteException)
        {
            ShowError("Save failed", exc.Message);
            return;
        }
        Refresh();
        ShowWarnings(record, fields);
        StatusText.Text = "Review saved. Complete any missing fields before filling or queuing.";
    }

    public bool ApplyRequest(bool enqueue, bool startRun = false)
    {
        RecoverActiveGatepasses();
        if (_store is null || !_selectedId.HasValue)
        {
            StatusText.Text = "Select a request first.";
            return false;
        }
        var record = _store.Get(_selectedId.Value);
        if (record is null || !string.IsNullOrEmpty(record.HiddenReason))
        {
            ResetSelection();
            StatusText.Text = "This request was cleared or marked DONE.";
            return false;
        }
        if (record.RunState == "Running")
        {
            StatusText.Text = "This request is running. Wait for it to finish or stop its lane.";
            return false;
        }

        var fields = ReadEditorFields();
        var errors = WhatsAppGdnParser.ValidateFields(fields, Warehouses());
        if (errors.Count > 0)
        {
            WarningsText.Text = string.Join("\n", errors);
            StatusText.Text = "Complete the highlighted details. Enter N/A explicitly if appropriate.";
            return false;
        }

        var laneName = LaneCombo.SelectedItem?.ToString() ?? string.Empty;
        if (!_lanes.TryGetValue(laneName, out var lane))
        {
            StatusText.Text = "Select an available target lane.";
            return false;
        }

        if (lane.IsQueueRunning || lane.IsBusy)
        {
            StatusText.Text = $"{laneName} is busy. Choose another lane or wait for it to finish.";
            return false;
        }

        bool relatedRunning = _store.Related(fields, _selectedId.Value).Any(r => r.RunState == "Running");
        bool activeInLanes = _lanes.Values.Any(l =>
            l.HasActiveGatepass("GDN", fields["warehouse"], fields["client"], fields["gatepass"]));

        if (relatedRunning || activeInLanes)
        {
            StatusText.Text = "This warehouse, client, and gate pass is already queued or running. Wait for that job to finish or stop it.";
            return false;
        }

        try
        {
            // Persist edits before changing any lane state.
            _store.SaveReview(_selectedId.Value, fields);
            var form = WhatsAppGdnParser.FormFields(fields);
            lane.PrefillGdn(
                form["warehouse"],
                form["client"],
                form["gatepass"],
                form["delivery_location"],
                form["seal"]);
            lane.SetStatus($"Prefilled GDN from WhatsApp inbox (GP={fields["gatepass"]})");
            if (enqueue)
                lane.AddToQueue("GDN");
            var action = enqueue ? $"Queued: {laneName}" : $"Filled: {laneName}";
            _store.SaveReview(_selectedId.Value, fields, action);
            if (startRun)
                WhatsAppGrnStore.LaunchGatepass(_store, _selectedId.Value, "GDN", laneName, lane);

            Refresh();
            ShowWarnings(record, fields);
            StatusText.Text = startRun
                ? $"GDN running in {laneName}. Its state changes to Completed when the flow finishes; you can then run it again."
                : $"{action}. No GDN has been created automatically.";
            return true;
        }
        catch (Exception exc) when (exc is ArgumentException or InvalidOperationException or IOException or SqliteException)
        {
            Refresh();
            StatusText.Text = $"Could not start the action: {exc.Message}";
            return false;
        }
    }

    private void ShowError(string title, string message)
    {
        var owner = Window.GetWindow(this);
        if (owner is not null && owner.IsVisible)
            System.Windows.MessageBox.Show(owner, message, title, MessageBoxButton.OK, MessageBoxImage.Error);
        else
            System.Windows.MessageBox.Show(message, title, MessageBoxButton.OK, MessageBoxImage.Error);
    }

    public void Shutdown()
    {
        if (_closed) return;
        _closed = true;
        if (_pollTimer is not null)
        {
            _pollTimer.Stop();
            _pollTimer.Tick -= PollTimer_Tick;
            _pollTimer = null;
        }
        _store?.Close();
    }
}
