using System.Windows;
using KorberAuditShip.Models;
using KorberAuditShip.Services;

namespace KorberAuditShip.Views;

public partial class CredentialsDialog : Window
{
    private readonly CredentialService _credentialService;

    public KorberCredentials? SavedCredentials { get; private set; }

    public CredentialsDialog(KorberCredentials? existing, CredentialService credentialService)
    {
        InitializeComponent();
        _credentialService = credentialService;

        if (existing is not null)
        {
            UsernameBox.Text = existing.Username;
            PasswordBox.Password = existing.Password;
            ForkIdBox.Text = existing.ForkId;
            SourceInfoText.Text = $"Loaded from: {existing.Source}. Saving stores encrypted credentials locally using Windows DPAPI.";
        }
        else
        {
            SourceInfoText.Text = "Saved locally per Windows user via DPAPI encryption, or automatically overridden when AUDITSHIP_* / config.json is set.";
        }

        Loaded += (_, _) => UsernameBox.Focus();
    }

    private void SaveButton_Click(object sender, RoutedEventArgs e)
    {
        var user = UsernameBox.Text.Trim();
        var pass = PasswordBox.Password;
        var fork = string.IsNullOrWhiteSpace(ForkIdBox.Text) ? user : ForkIdBox.Text.Trim();

        if (string.IsNullOrWhiteSpace(user) || string.IsNullOrWhiteSpace(pass) || string.IsNullOrWhiteSpace(fork))
        {
            MessageBox.Show(this, "Username, Password, and Fork ID are required.", "Validation", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        _credentialService.SaveLocalCredentials(user, pass, fork);
        SavedCredentials = new KorberCredentials(user, pass, fork, "Local Encrypted Settings (DPAPI)");
        DialogResult = true;
    }

    private void ClearButton_Click(object sender, RoutedEventArgs e)
    {
        _credentialService.ClearLocalCredentials();
        UsernameBox.Text = string.Empty;
        PasswordBox.Password = string.Empty;
        ForkIdBox.Text = string.Empty;
        SavedCredentials = null;
        MessageBox.Show(this, "Local saved credentials removed.", "Credentials Cleared", MessageBoxButton.OK, MessageBoxImage.Information);
    }

    private void CancelButton_Click(object sender, RoutedEventArgs e)
    {
        DialogResult = false;
    }
}
