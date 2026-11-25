using System.Windows;
using EflNexus.Core.Infrastructure;

namespace EflNexus.App.Dialogs;

public partial class EmailSettingsDialog : Window
{
    private readonly ConfigStore _configStore;
    private readonly Action? _onSave;

    public EmailSettingsDialog(Window? owner, ConfigStore configStore, Action? onSave = null)
    {
        InitializeComponent();
        App.TrySetWindowIcon(this);
        if (owner is not null && owner.IsVisible)
            Owner = owner;
        else
            WindowStartupLocation = WindowStartupLocation.CenterScreen;

        _configStore = configStore;
        _onSave = onSave;

        WebAppEntry.Text = configStore.GetWebappUrl();
        SheetEntry.Text = configStore.GetSheetUrl();
    }

    private void Save_Click(object sender, RoutedEventArgs e)
    {
        string webappUrl = (WebAppEntry.Text ?? string.Empty).Trim();
        string sheetUrl = (SheetEntry.Text ?? string.Empty).Trim();
        _configStore.Save(webappUrl: webappUrl, sheetUrl: sheetUrl);
        _onSave?.Invoke();
        System.Windows.MessageBox.Show(
            this,
            "Settings saved successfully.",
            "Saved",
            MessageBoxButton.OK,
            MessageBoxImage.Information);
        Close();
    }

    private void Cancel_Click(object sender, RoutedEventArgs e) => Close();
}
