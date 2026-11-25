using System.Windows;
using EflNexus.Core.OutlookEmail;

namespace EflNexus.App.Dialogs;

public partial class AddTemplateDialog : Window
{
    private readonly Action<string, string, string> _onSubmit;

    public AddTemplateDialog(Window? owner, Action<string, string, string> onSubmit)
    {
        InitializeComponent();
        App.TrySetWindowIcon(this);
        if (owner is not null && owner.IsVisible)
            Owner = owner;
        else
            WindowStartupLocation = WindowStartupLocation.CenterScreen;

        _onSubmit = onSubmit;
    }

    private void Save_Click(object sender, RoutedEventArgs e)
    {
        string name = (NameEntry.Text ?? string.Empty).Trim();
        string toAddr = RecipientHelpers.NormalizeRecipients((ToEntry.Text ?? string.Empty).Trim());
        string ccAddr = RecipientHelpers.NormalizeRecipients((CcEntry.Text ?? string.Empty).Trim());

        if (string.IsNullOrEmpty(name))
        {
            System.Windows.MessageBox.Show(this, "Please enter a template name.", "Missing name", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }
        if (string.IsNullOrEmpty(toAddr))
        {
            System.Windows.MessageBox.Show(this, "Please enter at least one 'To:' recipient.", "Missing recipients", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        _onSubmit(name, toAddr, ccAddr);
        Close();
    }

    private void Cancel_Click(object sender, RoutedEventArgs e) => Close();
}
