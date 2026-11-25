using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.CompilerServices;
using System.Windows;
using EflNexus.Core.Infrastructure;
using EflNexus.Core.Korber;
using EflNexus.Core.WhatsApp;
using MediaBrush = System.Windows.Media.Brush;
using MediaColor = System.Windows.Media.Color;
using SolidBrush = System.Windows.Media.SolidColorBrush;
using UserControl = System.Windows.Controls.UserControl;

namespace EflNexus.App.Views;

public sealed class KorberQueueRowViewModel : INotifyPropertyChanged
{
    private KorberQueueStatus _status;

    public KorberQueueItem Model { get; }

    public string DocType => Model.DocType;
    public string GatePassNumber => Model.GatePassNumber;

    public string StatusText => _status.ToString();

    public MediaBrush StatusForeground => _status switch
    {
        KorberQueueStatus.Queued => new SolidBrush(MediaColor.FromRgb(0x64, 0x74, 0x8B)),
        KorberQueueStatus.Running => new SolidBrush(MediaColor.FromRgb(0x0B, 0x14, 0x20)),
        KorberQueueStatus.Done => new SolidBrush(MediaColor.FromRgb(0x10, 0xB9, 0x81)),
        KorberQueueStatus.Failed => new SolidBrush(MediaColor.FromRgb(0xDC, 0x26, 0x26)),
        KorberQueueStatus.Stopped => new SolidBrush(MediaColor.FromRgb(0xB4, 0x53, 0x09)),
        _ => new SolidBrush(MediaColor.FromRgb(0x1F, 0x29, 0x37))
    };

    public FontWeight StatusFontWeight =>
        _status == KorberQueueStatus.Running ? FontWeights.Bold : FontWeights.Normal;

    public KorberQueueRowViewModel(KorberQueueItem model)
    {
        Model = model;
        _status = model.Status;
    }

    public void RefreshStatus()
    {
        _status = Model.Status;
        OnPropertyChanged(nameof(StatusText));
        OnPropertyChanged(nameof(StatusForeground));
        OnPropertyChanged(nameof(StatusFontWeight));
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    private void OnPropertyChanged([CallerMemberName] string? name = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}

public partial class KorberLaneControl : UserControl, IKorberLaneTarget
{
    private string _profileName = "default";
    private KorberAutomationEngine _engine = null!;

    public ObservableCollection<KorberQueueRowViewModel> QueueRows { get; } = [];

    public Action? OpenWhatsAppInboxCallback { get; set; }

    public KorberAutomationEngine Engine => _engine;

    public string LaneName { get; set; } = "Lane";
    public string WhatsappRunId { get; set; } = string.Empty;
    public bool IsBusy => _engine.FlowActive || _engine.QueueRunning || !GdnRunBtn.IsEnabled;
    public bool IsQueueRunning => _engine.QueueRunning;
    public IReadOnlyList<string> AvailableWarehouses => KorberWarehouses.GdnWarehouses;

    public bool HasActiveGatepass(string docType, string warehouseId, string clientCode, string gatePassNumber)
    {
        var kind = (docType ?? "").Trim().ToUpperInvariant();
        var wh = (warehouseId ?? "").Trim().ToLowerInvariant();
        var cli = kind == "GRN" ? "" : (clientCode ?? "").Trim().ToLowerInvariant();
        var gp = (gatePassNumber ?? "").Trim().ToLowerInvariant();

        if (_engine.FlowActive && _engine.FlowRequest is { } req &&
            string.Equals(req.DocType, kind, StringComparison.OrdinalIgnoreCase))
        {
            var rWh = (req.WarehouseId ?? "").Trim().ToLowerInvariant();
            var rCli = kind == "GRN" ? "" : (req.ClientCode ?? "").Trim().ToLowerInvariant();
            var rGp = (req.GatePassNumber ?? "").Trim().ToLowerInvariant();
            if (rWh == wh && rCli == cli && rGp == gp)
                return true;
        }

        foreach (var item in _engine.Queue.ToArray())
        {
            if (item.Status is not (KorberQueueStatus.Queued or KorberQueueStatus.Running))
                continue;
            if (!string.Equals(item.DocType, kind, StringComparison.OrdinalIgnoreCase))
                continue;
            var iWh = (item.WarehouseId ?? "").Trim().ToLowerInvariant();
            var iCli = kind == "GRN" ? "" : (item.ClientCode ?? "").Trim().ToLowerInvariant();
            var iGp = (item.GatePassNumber ?? "").Trim().ToLowerInvariant();
            if (iWh == wh && iCli == cli && iGp == gp)
                return true;
        }

        return false;
    }

    public string ProfileName
    {
        get => _profileName;
        set
        {
            var next = string.IsNullOrWhiteSpace(value) ? "default" : value.Trim();
            if (_profileName == next && _engine is not null)
                return;
            _profileName = next;
            AttachEngine(new KorberAutomationEngine(_profileName));
        }
    }

    public KorberLaneControl()
    {
        InitializeComponent();
        GdnWarehouseCombo.ItemsSource = KorberWarehouses.GdnWarehouses;
        GrnWarehouseCombo.ItemsSource = KorberWarehouses.GrnWarehouses;
        QueueGrid.ItemsSource = QueueRows;
        AttachEngine(new KorberAutomationEngine(_profileName));
    }

    private void AttachEngine(KorberAutomationEngine engine)
    {
        if (_engine is not null)
        {
            _engine.StatusChanged -= Engine_StatusChanged;
            _engine.ProgressActiveChanged -= Engine_ProgressActiveChanged;
            _engine.ControlsEnabledChanged -= Engine_ControlsEnabledChanged;
            _engine.QueueItemUpdated -= Engine_QueueItemUpdated;
            _engine.FlowErrorDialogRequested -= Engine_FlowErrorDialogRequested;
            _engine.QueueFinishedDialogRequested -= Engine_QueueFinishedDialogRequested;
        }

        _engine = engine;
        _engine.StatusChanged += Engine_StatusChanged;
        _engine.ProgressActiveChanged += Engine_ProgressActiveChanged;
        _engine.ControlsEnabledChanged += Engine_ControlsEnabledChanged;
        _engine.QueueItemUpdated += Engine_QueueItemUpdated;
        _engine.FlowErrorDialogRequested += Engine_FlowErrorDialogRequested;
        _engine.QueueFinishedDialogRequested += Engine_QueueFinishedDialogRequested;
    }

    private void Engine_StatusChanged(string text)
        => Dispatcher.InvokeAsync(() => StatusText.Text = text);

    private void Engine_ProgressActiveChanged(bool active)
        => Dispatcher.InvokeAsync(() =>
        {
            StatusProgressBar.IsIndeterminate = active;
            if (!active)
                StatusProgressBar.Value = 0;
        });

    private void Engine_ControlsEnabledChanged(bool enabled)
        => Dispatcher.InvokeAsync(() =>
        {
            GdnRunBtn.IsEnabled = enabled;
            GrnRunBtn.IsEnabled = enabled;
            RunQueueBtn.IsEnabled = enabled;
            if (_engine.QueueRunning)
            {
                ClearQueueBtn.IsEnabled = false;
            }
            else
            {
                GdnQueueBtn.IsEnabled = enabled;
                GrnQueueBtn.IsEnabled = enabled;
                ClearQueueBtn.IsEnabled = enabled;
            }
        });

    private void Engine_QueueItemUpdated(KorberQueueItem item)
        => Dispatcher.InvokeAsync(() =>
        {
            var vm = QueueRows.FirstOrDefault(r => ReferenceEquals(r.Model, item) || r.Model.Id == item.Id);
            vm?.RefreshStatus();
        });

    private void Engine_FlowErrorDialogRequested(string details)
        => Dispatcher.InvokeAsync(() =>
        {
            var owner = Window.GetWindow(this);
            if (owner is not null && owner.IsVisible)
                System.Windows.MessageBox.Show(owner, details, "Failed", MessageBoxButton.OK, MessageBoxImage.Error);
            else
                System.Windows.MessageBox.Show(details, "Failed", MessageBoxButton.OK, MessageBoxImage.Error);

            StatusText.Text = "Cancelled after failure — fill in details and try again";
        });

    private void Engine_QueueFinishedDialogRequested(string summary)
        => Dispatcher.InvokeAsync(() =>
        {
            var owner = Window.GetWindow(this);
            if (owner is not null && owner.IsVisible)
                System.Windows.MessageBox.Show(owner, summary, "Queue finished", MessageBoxButton.OK, MessageBoxImage.Information);
            else
                System.Windows.MessageBox.Show(summary, "Queue finished", MessageBoxButton.OK, MessageBoxImage.Information);
        });

    public void SetStatus(string text)
        => StatusText.Text = text;

    public void ClearFields()
    {
        GdnWarehouseCombo.SelectedIndex = -1;
        GdnClientBox.Text = string.Empty;
        GdnGatePassBox.Text = string.Empty;
        GdnDeliveryBox.Text = string.Empty;
        GdnSealBox.Text = string.Empty;
        GrnWarehouseCombo.SelectedIndex = -1;
        GrnGatePassBox.Text = string.Empty;
        SetStatus("Fields cleared");
    }

    public void PrefillGdn(
        string warehouse = "",
        string client = "",
        string gatepass = "",
        string deliveryLocation = "",
        string seal = "")
    {
        DocTabControl.SelectedIndex = 0;

        if (!string.IsNullOrWhiteSpace(warehouse))
        {
            var whTrim = warehouse.Trim();
            var matched = KorberWarehouses.GdnWarehouses.FirstOrDefault(v =>
                string.Equals(v.Trim(), whTrim, StringComparison.OrdinalIgnoreCase))
                ?? KorberWarehouses.GdnWarehouses.FirstOrDefault(v =>
                    whTrim.Contains(v.Trim(), StringComparison.OrdinalIgnoreCase) ||
                    v.Trim().Contains(whTrim, StringComparison.OrdinalIgnoreCase));
            GdnWarehouseCombo.SelectedItem = matched ?? warehouse;
        }

        GdnClientBox.Text = client ?? string.Empty;
        GdnGatePassBox.Text = gatepass ?? string.Empty;

        var delivText = (deliveryLocation ?? string.Empty).Trim();
        if (string.IsNullOrEmpty(delivText) || delivText == "-")
            delivText = "N/A";
        GdnDeliveryBox.Text = delivText;

        var sealText = (seal ?? string.Empty).Trim();
        if (string.IsNullOrEmpty(sealText) || sealText == "-")
            sealText = "N/A";
        GdnSealBox.Text = sealText;

        var parts = new List<string>();
        if (!string.IsNullOrWhiteSpace(gatepass)) parts.Add($"GP={gatepass}");
        if (!string.IsNullOrWhiteSpace(warehouse)) parts.Add($"WH={warehouse}");
        if (!string.IsNullOrWhiteSpace(client)) parts.Add($"Client={client}");
        var desc = parts.Count > 0 ? $" ({string.Join(", ", parts)})" : string.Empty;
        SetStatus($"Prefilled GDN fields from Pending Jobs{desc}");
    }

    public void PrefillGrn(string warehouse = "", string gatepass = "")
    {
        DocTabControl.SelectedIndex = 1;

        if (!string.IsNullOrWhiteSpace(warehouse))
        {
            var whTrim = warehouse.Trim();
            var matched = KorberWarehouses.GrnWarehouses.FirstOrDefault(v =>
                string.Equals(v.Trim(), whTrim, StringComparison.OrdinalIgnoreCase))
                ?? KorberWarehouses.GrnWarehouses.FirstOrDefault(v =>
                    whTrim.Contains(v.Trim(), StringComparison.OrdinalIgnoreCase) ||
                    v.Trim().Contains(whTrim, StringComparison.OrdinalIgnoreCase));
            GrnWarehouseCombo.SelectedItem = matched ?? warehouse;
        }

        GrnGatePassBox.Text = gatepass ?? string.Empty;

        var parts = new List<string>();
        if (!string.IsNullOrWhiteSpace(gatepass)) parts.Add($"GP={gatepass}");
        if (!string.IsNullOrWhiteSpace(warehouse)) parts.Add($"WH={warehouse}");
        var desc = parts.Count > 0 ? $" ({string.Join(", ", parts)})" : string.Empty;
        SetStatus($"Prefilled GRN fields from Pending Jobs{desc}");
    }

    public bool RunFlow(string docType, Action<bool, string>? onComplete = null)
    {
        if (_engine.FlowActive || _engine.QueueRunning)
            return false;

        var req = BuildValidatedRequest(docType);
        if (req is null)
            return false;

        return _engine.RunFlow(req, onComplete);
    }

    private KorberFlowRequest? BuildValidatedRequest(string docType)
    {
        var owner = Window.GetWindow(this);
        if (docType == "GDN")
        {
            var wh = (GdnWarehouseCombo.SelectedItem?.ToString() ?? GdnWarehouseCombo.Text ?? "").Trim();
            var client = (GdnClientBox.Text ?? "").Trim();
            var gp = (GdnGatePassBox.Text ?? "").Trim();
            var deliv = (GdnDeliveryBox.Text ?? "").Trim();
            if (string.IsNullOrEmpty(deliv) || deliv == "-")
            {
                deliv = "N/A";
                GdnDeliveryBox.Text = "N/A";
            }
            var seal = (GdnSealBox.Text ?? "").Trim();
            if (string.IsNullOrEmpty(seal) || seal == "-")
            {
                seal = "N/A";
                GdnSealBox.Text = "N/A";
            }

            if (string.IsNullOrEmpty(wh) || string.IsNullOrEmpty(client) || string.IsNullOrEmpty(gp) ||
                string.IsNullOrEmpty(deliv) || string.IsNullOrEmpty(seal))
            {
                ShowMessage(owner, "Missing info", "Please fill in all five GDN fields first.", MessageBoxImage.Warning);
                return null;
            }

            return new KorberFlowRequest
            {
                DocType = "GDN",
                WarehouseId = wh,
                ClientCode = client,
                GatePassNumber = gp,
                DeliveryLocation = deliv,
                SealNumber = seal
            };
        }
        else
        {
            var wh = (GrnWarehouseCombo.SelectedItem?.ToString() ?? GrnWarehouseCombo.Text ?? "").Trim();
            var gp = (GrnGatePassBox.Text ?? "").Trim();
            if (string.IsNullOrEmpty(wh) || string.IsNullOrEmpty(gp))
            {
                ShowMessage(owner, "Missing info", "Please fill in the GRN Warehouse ID and Gate Pass Number first.", MessageBoxImage.Warning);
                return null;
            }

            return new KorberFlowRequest
            {
                DocType = "GRN",
                WarehouseId = wh,
                GatePassNumber = gp
            };
        }
    }

    public void AddToQueue(string docType)
    {
        var req = BuildValidatedRequest(docType);
        if (req is null)
            return;

        var item = _engine.AddToQueue(req);
        QueueRows.Add(new KorberQueueRowViewModel(item));

        if (docType == "GDN")
        {
            GdnGatePassBox.Text = string.Empty;
            GdnSealBox.Text = string.Empty;
            GdnGatePassBox.Focus();
        }
        else
        {
            GrnGatePassBox.Text = string.Empty;
            GrnGatePassBox.Focus();
        }
    }

    private void CreateGdn_Click(object sender, RoutedEventArgs e) => RunFlow("GDN");
    private void CreateGrn_Click(object sender, RoutedEventArgs e) => RunFlow("GRN");
    private void AddGdnToQueue_Click(object sender, RoutedEventArgs e) => AddToQueue("GDN");
    private void AddGrnToQueue_Click(object sender, RoutedEventArgs e) => AddToQueue("GRN");
    private void ClearFields_Click(object sender, RoutedEventArgs e) => ClearFields();

    private void WhatsAppInbox_Click(object sender, RoutedEventArgs e)
        => OpenWhatsAppInboxCallback?.Invoke();

    private void RunQueue_Click(object sender, RoutedEventArgs e)
    {
        if (_engine.QueueRunning || _engine.FlowActive)
            return;
        if (!_engine.Queue.Any(it => it.Status == KorberQueueStatus.Queued))
        {
            ShowMessage(Window.GetWindow(this), "Queue empty", "Add at least one GDN or GRN to the queue first.", MessageBoxImage.Information);
            return;
        }
        GdnQueueBtn.IsEnabled = true;
        GrnQueueBtn.IsEnabled = true;
        ClearQueueBtn.IsEnabled = false;
        _engine.RunQueue();
    }

    private void StopSelected_Click(object sender, RoutedEventArgs e)
    {
        var owner = Window.GetWindow(this);
        if (QueueGrid.SelectedItem is not KorberQueueRowViewModel rowVm)
        {
            ShowMessage(owner, "Nothing selected", "Select an item in the queue list first.", MessageBoxImage.Information);
            return;
        }

        var result = _engine.StopQueueItem(rowVm.Model);
        rowVm.RefreshStatus();
        if (result.StartsWith("AlreadyFinished:", StringComparison.Ordinal))
        {
            var st = result.Split(':', 2)[1];
            ShowMessage(owner, "Already finished", $"This item is already '{st}' and can't be stopped.", MessageBoxImage.Information);
        }
    }

    private void ClearQueue_Click(object sender, RoutedEventArgs e)
    {
        var owner = Window.GetWindow(this);
        if (_engine.QueueRunning)
        {
            ShowMessage(owner, "Queue running", "Can't clear the queue while it's running.", MessageBoxImage.Warning);
            return;
        }
        _engine.ClearQueue();
        QueueRows.Clear();
    }

    private void Terminate_Click(object sender, RoutedEventArgs e)
    {
        var owner = Window.GetWindow(this);
        const string msg =
            "This will close the current browser session. The app stays open -- no restart.\n\n" +
            "Any queue item currently running or still queued will be stopped, not paused. Afterwards, just click Create GDN, Create GRN, or Run Queue to start a new browser session. Continue?";
        var confirm = owner is not null && owner.IsVisible
            ? System.Windows.MessageBox.Show(owner, msg, "Terminate Session", MessageBoxButton.YesNo, MessageBoxImage.Question)
            : System.Windows.MessageBox.Show(msg, "Terminate Session", MessageBoxButton.YesNo, MessageBoxImage.Question);

        if (confirm != MessageBoxResult.Yes)
            return;

        _engine.TerminateSession();
    }

    private void Restart_Click(object sender, RoutedEventArgs e)
    {
        var owner = Window.GetWindow(this);
        const string msg =
            "This will close the browser and restart the app completely.\n\n" +
            "Any queue item currently running will be stopped, not paused. Continue?";
        var confirm = owner is not null && owner.IsVisible
            ? System.Windows.MessageBox.Show(owner, msg, "Terminate & Restart", MessageBoxButton.YesNo, MessageBoxImage.Question)
            : System.Windows.MessageBox.Show(msg, "Terminate & Restart", MessageBoxButton.YesNo, MessageBoxImage.Question);

        if (confirm != MessageBoxResult.Yes)
            return;

        _engine.TerminateSession();
        SetStatus("Restarting app...");

        try
        {
            var exePath = AppPaths.ResolveAppExecutable();
            if (!string.IsNullOrWhiteSpace(exePath) && File.Exists(exePath))
            {
                Process.Start(new ProcessStartInfo(exePath) { UseShellExecute = true });
                System.Windows.Application.Current?.Shutdown();
            }
        }
        catch { }
    }

    private void About_Click(object sender, RoutedEventArgs e)
    {
        ShowMessage(
            Window.GetWindow(this),
            "About",
            "Körber Automation Bot\n\n" +
            "Built with ☕ by the 3PL EFL CSS Team\n" +
            "Automating GDN/GRN creation, one click at a time.",
            MessageBoxImage.Information);
    }

    private static void ShowMessage(Window? owner, string title, string text, MessageBoxImage icon)
    {
        if (owner is not null && owner.IsVisible)
            System.Windows.MessageBox.Show(owner, text, title, MessageBoxButton.OK, icon);
        else
            System.Windows.MessageBox.Show(text, title, MessageBoxButton.OK, icon);
    }
}
