using System.Windows;
using System.Windows.Threading;
using EflNexus.Core.Monitoring;

namespace EflNexus.App.Dialogs;

public partial class PresenceSettingsDialog : Window
{
    private readonly MonitoringService? _service;
    private readonly DispatcherTimer _timer;

    public PresenceSettingsDialog(Window? owner, MonitoringService? service)
    {
        InitializeComponent();
        App.TrySetWindowIcon(this);
        if (owner is not null && owner.IsVisible)
            Owner = owner;
        else
            WindowStartupLocation = WindowStartupLocation.CenterScreen;

        _service = service;
        RefreshStatus();

        _timer = new DispatcherTimer
        {
            Interval = TimeSpan.FromMilliseconds(1000)
        };
        _timer.Tick += (_, _) => RefreshStatus();
        _timer.Start();

        Closed += (_, _) => _timer.Stop();
    }

    private void RefreshStatus()
    {
        if (_service is not null)
        {
            InstallationUuidBox.Text = _service.InstallationUuid;
            StatusText.Text = _service.Status();
        }
        else
        {
            InstallationUuidBox.Text = string.Empty;
            StatusText.Text = "Service inactive.";
        }
    }

    private void Close_Click(object sender, RoutedEventArgs e) => Close();
}
