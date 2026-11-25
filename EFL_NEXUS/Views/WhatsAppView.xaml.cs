using System.Windows;
using System.Windows.Controls;
using EflNexus.App.Controllers;
using EflNexus.Core.WhatsApp;
using Drawing = System.Drawing;
using UserControl = System.Windows.Controls.UserControl;
using WinForms = System.Windows.Forms;

namespace EflNexus.App.Views;

public partial class WhatsAppView : UserControl
{
    public static readonly (string Label, string Profile)[] WhatsAppLanes =
    [
        ("WhatsApp Lane 1", "whatsapp_lane_1"),
        ("WhatsApp Lane 2", "whatsapp_lane_2")
    ];

    private WhatsAppController? _controller;
    private WhatsAppGrnStore? _grnSettings;
    private readonly Dictionary<string, IKorberLaneTarget> _lanes = new(StringComparer.Ordinal);
    private string _grnGroupId = string.Empty;
    private bool _visible;
    private bool _closed;

    private WinForms.Panel? _browserHostPanel;

    public IReadOnlyDictionary<string, IKorberLaneTarget> Lanes => _lanes;

    public WhatsAppView()
    {
        InitializeComponent();
        GrnWarehouseCombo.ItemsSource = WhatsAppGrnStore.GrnWarehouses;

        Lane1Control.OpenWhatsAppInboxCallback = ShowInbox;
        Lane2Control.OpenWhatsAppInboxCallback = ShowInbox;
        _lanes["WhatsApp Lane 1"] = Lane1Control;
        _lanes["WhatsApp Lane 2"] = Lane2Control;

        InitializeBrowserHost();
    }

    public WhatsAppView(WhatsAppController controller) : this()
    {
        Configure(controller);
    }

    private void InitializeBrowserHost()
    {
        _browserHostPanel = new WinForms.Panel
        {
            BackColor = Drawing.Color.White,
            Dock = WinForms.DockStyle.Fill
        };
        var placeholder = new WinForms.Label
        {
            Text = "Choose Open / Reconnect to load WhatsApp Web inside NEXUS.",
            AutoSize = false,
            TextAlign = Drawing.ContentAlignment.MiddleCenter,
            Dock = WinForms.DockStyle.Fill,
            ForeColor = Drawing.Color.FromArgb(71, 85, 105),
            Font = new Drawing.Font("Segoe UI", 10f)
        };
        _browserHostPanel.Controls.Add(placeholder);
        BrowserHostContainer.Child = _browserHostPanel;
    }

    public void Configure(WhatsAppController controller)
    {
        if (_controller is not null)
            _controller.RemoveListener(OnControllerChanged);

        _controller = controller;
        _grnSettings?.Dispose();
        _grnSettings = new WhatsAppGrnStore(controller.Store.FilePath);

        var configuredGroup = _grnSettings.Setting<WhatsAppGroupSetting?>("group", null);
        _grnGroupId = configuredGroup?.Id ?? string.Empty;
        var savedWh = _grnSettings.DefaultWarehouse(_grnGroupId);
        GrnWarehouseCombo.SelectedItem = WhatsAppGrnStore.GrnWarehouses.Contains(savedWh, StringComparer.Ordinal)
            ? savedWh
            : null;

        if (_browserHostPanel is not null)
            controller.SetHost(_browserHostPanel);

        GdnInboxControl.Configure(_lanes, new WhatsAppGdnStore(controller.Store.FilePath), controller);
        GrnInboxControl.Configure(controller, _lanes);

        controller.AddListener(OnControllerChanged);
        OnControllerChanged(controller);
    }

    private void OnControllerChanged(WhatsAppController controller)
    {
        if (!Dispatcher.CheckAccess())
        {
            Dispatcher.InvokeAsync(() => OnControllerChanged(controller));
            return;
        }
        if (_closed) return;

        StatusText.Text = $"{controller.State}: {controller.Detail}";
        var group = controller.Store.Setting<WhatsAppGroupSetting?>("group", null);
        if (group is not null && !string.IsNullOrEmpty(group.Id) && group.Id != _grnGroupId)
        {
            _grnGroupId = group.Id;
            var wh = _grnSettings?.DefaultWarehouse(group.Id) ?? string.Empty;
            GrnWarehouseCombo.SelectedItem = WhatsAppGrnStore.GrnWarehouses.Contains(wh, StringComparer.Ordinal)
                ? wh
                : null;
        }

        GroupText.Text = group is not null && !string.IsNullOrEmpty(group.Name)
            ? $"Selected group: {group.Name}"
            : "No group selected";

        bool enabled = controller.Store.Setting("enabled", false);
        SelectGroupBtn.IsEnabled = !(group is not null && enabled);

        GdnInboxTab.Header = $"  GDN Inbox ({controller.NewCount} new)  ";
        GrnInboxTab.Header = $"  GRN Inbox ({controller.GrnNewCount} new)  ";

        var gapLines = new List<string>();
        if (controller.Gap)
            gapLines.Add("Possible capture gap. Compare recent group messages and import any missing requests.");
        var doneNotice = controller.Store.Setting("done_reply_notice", string.Empty);
        if (!string.IsNullOrWhiteSpace(doneNotice))
            gapLines.Add(doneNotice);

        GapText.Text = string.Join("\n", gapLines);
        AckGapBtn.Visibility = controller.Gap ? Visibility.Visible : Visibility.Collapsed;
    }

    private void Open_Click(object sender, RoutedEventArgs e)
    {
        MainTabControl.SelectedItem = BrowserTab;
        _controller?.Start();
        UpdateVisibility();
    }

    private void SaveGrnWarehouse_Click(object sender, RoutedEventArgs e)
    {
        if (_grnSettings is null) return;
        var group = _grnSettings.Setting<WhatsAppGroupSetting?>("group", null);
        var warehouse = GrnWarehouseCombo.SelectedItem?.ToString() ?? string.Empty;
        if (group is null || string.IsNullOrEmpty(group.Id) ||
            !WhatsAppGrnStore.GrnWarehouses.Contains(warehouse, StringComparer.Ordinal))
        {
            GrnSetupStatusText.Text = "Select a group and warehouse first.";
            return;
        }
        _grnSettings.SetDefaultWarehouse(group.Id, warehouse);
        GrnSetupStatusText.Text = "Saved for this group.";
    }

    private void SelectGroup_Click(object sender, RoutedEventArgs e)
        => _controller?.SelectGroup(ImportVisibleCheck.IsChecked == true);

    private void Pause_Click(object sender, RoutedEventArgs e)
        => _controller?.Pause();

    private void Resume_Click(object sender, RoutedEventArgs e)
        => _controller?.Resume();

    private void Reload_Click(object sender, RoutedEventArgs e)
        => _controller?.Reload();

    private void AckGap_Click(object sender, RoutedEventArgs e)
        => _controller?.AcknowledgeGap();

    public void ShowInbox()
    {
        MainTabControl.SelectedItem = GdnInboxTab;
        UpdateVisibility();
    }

    public void SetVisible(bool visible)
    {
        _visible = visible;
        UpdateVisibility();
    }

    private void UpdateVisibility()
    {
        if (_controller is null) return;
        bool showBrowser = _visible && ReferenceEquals(MainTabControl.SelectedItem, BrowserTab);
        _controller.SetVisible(showBrowser);
    }

    private void MainTabControl_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (ReferenceEquals(e.OriginalSource, MainTabControl))
            UpdateVisibility();
    }

    private void BrowserHostContainer_SizeChanged(object sender, SizeChangedEventArgs e)
    {
        _controller?.Resize();
    }

    public void Shutdown()
    {
        if (_closed) return;
        _closed = true;

        if (_controller is not null)
        {
            _controller.RemoveListener(OnControllerChanged);
            _controller.SetVisible(false);
        }

        _grnSettings?.Dispose();
        _grnSettings = null;
        GdnInboxControl.Shutdown();
        GrnInboxControl.Shutdown();
    }
}
