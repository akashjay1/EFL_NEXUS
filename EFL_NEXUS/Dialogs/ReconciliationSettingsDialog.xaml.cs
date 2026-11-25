using System.Windows;
using MediaColor = System.Windows.Media.Color;
using SolidBrush = System.Windows.Media.SolidColorBrush;

namespace EflNexus.App.Dialogs;

public partial class ReconciliationSettingsDialog : Window
{
    private readonly Action<bool> _onRememberChanged;
    private readonly Action<bool> _onThemeToggle;

    public ReconciliationSettingsDialog(
        Window? owner,
        bool rememberSettings,
        bool darkMode,
        Action<bool> onRememberChanged,
        Action<bool> onThemeToggle)
    {
        InitializeComponent();
        App.TrySetWindowIcon(this);
        if (owner is not null && owner.IsVisible)
            Owner = owner;
        else
            WindowStartupLocation = WindowStartupLocation.CenterScreen;

        _onRememberChanged = onRememberChanged;
        _onThemeToggle = onThemeToggle;

        RememberCheck.IsChecked = rememberSettings;
        DarkThemeCheck.IsChecked = darkMode;
        ApplyTheme(darkMode);
    }

    private void ApplyTheme(bool dark)
    {
        var bg = new SolidBrush(dark ? MediaColor.FromRgb(0x0B, 0x14, 0x20) : MediaColor.FromRgb(0xFA, 0xF8, 0xF2));
        var fg = new SolidBrush(dark ? MediaColor.FromRgb(0xEC, 0xEC, 0xEC) : MediaColor.FromRgb(0x0F, 0x17, 0x2A));
        Background = bg;
        HeaderText.Foreground = fg;
        RememberCheck.Foreground = fg;
        DarkThemeCheck.Foreground = fg;
    }

    private void RememberCheck_Click(object sender, RoutedEventArgs e)
        => _onRememberChanged(RememberCheck.IsChecked == true);

    private void DarkThemeCheck_Click(object sender, RoutedEventArgs e)
    {
        bool dark = DarkThemeCheck.IsChecked == true;
        ApplyTheme(dark);
        _onThemeToggle(dark);
    }

    private void Close_Click(object sender, RoutedEventArgs e) => Close();
}
