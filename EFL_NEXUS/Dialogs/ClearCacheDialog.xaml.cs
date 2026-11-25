using System.IO;
using System.Windows;
using System.Windows.Input;
using EflNexus.Core.Infrastructure;
using EflNexus.Core.Reconciliation;

namespace EflNexus.App.Dialogs;

public partial class ClearCacheDialog : Window
{
    private readonly string _appDir;
    private readonly Action? _onComplete;

    public ClearCacheDialog(Window? owner, string? appDir = null, Action? onComplete = null)
    {
        InitializeComponent();
        App.TrySetWindowIcon(this);
        if (owner is not null && owner.IsVisible)
            Owner = owner;
        else
            WindowStartupLocation = WindowStartupLocation.CenterScreen;

        _appDir = string.IsNullOrWhiteSpace(appDir) ? AppPaths.AppDir : appDir;
        _onComplete = onComplete;

        int profileCount = 0;
        try
        {
            if (Directory.Exists(_appDir))
                profileCount = Directory.GetDirectories(_appDir, "chrome_automation_profile_*").Length;
        }
        catch { }

        ProfilesDescText.Text =
            $"Removes Chrome session folders & singleton locks ({profileCount} profile folder{(profileCount == 1 ? "" : "s")} found).";

        int templateCount = 0;
        foreach (var t in new[] { "templates.xlsx", "variance_templates.xlsx" })
        {
            if (File.Exists(Path.Combine(_appDir, t)))
                templateCount++;
        }
        TemplatesDescText.Text =
            $"Deletes templates.xlsx and variance_templates.xlsx ({templateCount} file{(templateCount == 1 ? "" : "s")} found).";
    }

    private void SelectAll_Click(object sender, MouseButtonEventArgs e) => SetAll(true);
    private void DeselectAll_Click(object sender, MouseButtonEventArgs e) => SetAll(false);

    private void SetAll(bool value)
    {
        ProfilesCheck.IsChecked = value;
        CacheCheck.IsChecked = value;
        WhatsAppCheck.IsChecked = value;
        TemplatesCheck.IsChecked = value;
        SettingsCheck.IsChecked = value;
    }

    private void Cancel_Click(object sender, RoutedEventArgs e) => Close();

    private void ExecuteClear_Click(object sender, RoutedEventArgs e)
    {
        var clearedItems = new List<string>();
        var errors = new List<string>();

        if (ProfilesCheck.IsChecked == true && Directory.Exists(_appDir))
        {
            int deletedP = 0;
            foreach (var pDir in Directory.GetDirectories(_appDir, "chrome_automation_profile_*"))
            {
                try
                {
                    Directory.Delete(pDir, recursive: true);
                    deletedP++;
                }
                catch (Exception ex)
                {
                    errors.Add($"Profile {Path.GetFileName(pDir)}: {ex.Message}");
                }
            }
            if (deletedP > 0)
                clearedItems.Add($"• {deletedP} Chrome automation profile folder(s)");
        }

        if (CacheCheck.IsChecked == true)
        {
            var wdm = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".wdm");
            if (Directory.Exists(wdm))
            {
                try
                {
                    Directory.Delete(wdm, recursive: true);
                    clearedItems.Add("• WebDriver binary cache (~/.wdm)");
                }
                catch (Exception ex)
                {
                    errors.Add($"WDM cache: {ex.Message}");
                }
            }

            int pycacheCount = 0;
            if (Directory.Exists(_appDir))
            {
                try
                {
                    foreach (var pyc in Directory.GetDirectories(_appDir, "__pycache__", SearchOption.AllDirectories))
                    {
                        try
                        {
                            Directory.Delete(pyc, recursive: true);
                            pycacheCount++;
                        }
                        catch { }
                    }
                }
                catch { }
            }
            if (pycacheCount > 0)
                clearedItems.Add($"• {pycacheCount} Python __pycache__ directory/directories");
        }

        if (WhatsAppCheck.IsChecked == true)
        {
            var waDirs = new[]
            {
                Path.Combine(_appDir, "whatsapp_gdn"),
                Path.Combine(_appDir, "webview_profile"),
                Path.Combine(AppPaths.LocalAppDataDir, "whatsapp_gdn"),
                Path.Combine(AppPaths.LocalAppDataDir, "webview_profile"),
                Path.Combine(AppPaths.LocalAppDataDir, "webview_internal_profile"),
                Path.Combine(AppPaths.LocalAppDataDir, "webview_loading_history_profile")
            };

            int waDeleted = 0;
            foreach (var wDir in waDirs)
            {
                if (Directory.Exists(wDir))
                {
                    try
                    {
                        Directory.Delete(wDir, recursive: true);
                        waDeleted++;
                    }
                    catch (Exception ex)
                    {
                        errors.Add($"WhatsApp/WebView folder {Path.GetFileName(wDir)}: {ex.Message}");
                    }
                }
            }
            if (waDeleted > 0)
                clearedItems.Add($"• {waDeleted} WhatsApp & WebView profile directory/directories (logged out)");
        }

        if (TemplatesCheck.IsChecked == true)
        {
            int tCount = 0;
            foreach (var tFile in new[] { "templates.xlsx", "variance_templates.xlsx" })
            {
                var target = Path.Combine(_appDir, tFile);
                if (File.Exists(target))
                {
                    try
                    {
                        File.Delete(target);
                        tCount++;
                    }
                    catch (Exception ex)
                    {
                        errors.Add($"{tFile}: {ex.Message}");
                    }
                }
            }
            if (tCount > 0)
                clearedItems.Add($"• {tCount} saved template spreadsheet(s)");
        }

        if (SettingsCheck.IsChecked == true)
        {
            var recSet = ReconciliationSettingsStore.SettingsFilePath;
            if (File.Exists(recSet))
            {
                try
                {
                    File.Delete(recSet);
                    clearedItems.Add("• Reconciliation settings (.load_reconciliation_tool_settings.json)");
                }
                catch (Exception ex)
                {
                    errors.Add($"Settings: {ex.Message}");
                }
            }

            var sentL = Path.Combine(_appDir, "sent_log.xlsx");
            if (File.Exists(sentL))
            {
                try
                {
                    File.Delete(sentL);
                    clearedItems.Add("• Outlook send log (sent_log.xlsx)");
                }
                catch (Exception ex)
                {
                    errors.Add($"Sent log: {ex.Message}");
                }
            }
        }

        if (clearedItems.Count == 0 && errors.Count == 0)
        {
            System.Windows.MessageBox.Show(
                this,
                "No matching cache or profile files were found to clear.",
                "Storage & Cache",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
        }
        else
        {
            var msg = "Storage and cache cleanup completed successfully!\n\n";
            if (clearedItems.Count > 0)
                msg += "Items removed:\n" + string.Join("\n", clearedItems) + "\n\n";
            if (errors.Count > 0)
                msg += "Warnings / Skipped locked files:\n" + string.Join("\n", errors) + "\n\n";

            System.Windows.MessageBox.Show(
                this,
                msg,
                "Cleanup Complete",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
        }

        try { _onComplete?.Invoke(); } catch { }
        Close();
    }
}
