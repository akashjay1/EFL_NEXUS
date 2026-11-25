using System.Collections.ObjectModel;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using EflNexus.Core.PackingList;
using Microsoft.Win32;

namespace EflNexus.App.Views;

public partial class PackingListView : UserControl
{
    private readonly PackingListService _service = new();
    private readonly ObservableCollection<PackingListLocationSummary> _locationSummaries = [];
    private readonly List<string> _selectedFiles = [];
    private Dictionary<string, string> _emailMap = new(StringComparer.OrdinalIgnoreCase);
    private DispatcherTimer? _notifTimer;

    public PackingListView()
    {
        InitializeComponent();
        LocationDataGrid.ItemsSource = _locationSummaries;
        LoadSavedMailConfig();
    }

    private void LoadSavedMailConfig()
    {
        try
        {
            var savedPath = _service.LoadSavedMailExcelPath();
            if (!string.IsNullOrWhiteSpace(savedPath) && File.Exists(savedPath))
            {
                _emailMap = _service.ProcessMailExcel(savedPath);
                MailExcelStatus.Text = $"Mail Mapping: {Path.GetFileName(savedPath)} ({_emailMap.Count} contacts)";
            }
        }
        catch (Exception ex)
        {
            MailExcelStatus.Text = $"Mail Mapping Error: {ex.Message}";
        }
    }

    public void ShowNotification(string message, string type = "info")
    {
        NotificationText.Text = message;

        var (bg, border, fg) = type.ToLowerInvariant() switch
        {
            "success" => (Color.FromRgb(0xF0, 0xFD, 0xF4), Color.FromRgb(0x86, 0xEF, 0xAC), Color.FromRgb(0x15, 0x80, 0x3D)),
            "warning" => (Color.FromRgb(0xFF, 0xFB, 0xEB), Color.FromRgb(0xFD, 0xE6, 0x8A), Color.FromRgb(0xB4, 0x53, 0x09)),
            "error" => (Color.FromRgb(0xFE, 0xF2, 0xF2), Color.FromRgb(0xFC, 0xA5, 0xA5), Color.FromRgb(0xB9, 0x1C, 0x1C)),
            _ => (Color.FromRgb(0xEB, 0xF8, 0xFF), Color.FromRgb(0x93, 0xC5, 0xFD), Color.FromRgb(0x1D, 0x4E, 0xD8))
        };

        NotificationBorder.Background = new SolidColorBrush(bg);
        NotificationBorder.BorderBrush = new SolidColorBrush(border);
        NotificationText.Foreground = new SolidColorBrush(fg);
        NotificationBorder.Visibility = Visibility.Visible;

        _notifTimer?.Stop();
        _notifTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(4) };
        _notifTimer.Tick += (s, e) =>
        {
            _notifTimer?.Stop();
            NotificationBorder.Visibility = Visibility.Collapsed;
        };
        _notifTimer.Start();
    }

    private void UploadMailBtn_Click(object sender, RoutedEventArgs e)
    {
        var dlg = new OpenFileDialog
        {
            Title = "Select Mail Report Excel",
            Filter = "Excel Files (*.xlsx;*.xls)|*.xlsx;*.xls|All Files (*.*)|*.*"
        };

        if (dlg.ShowDialog() == true)
        {
            var path = dlg.FileName;
            try
            {
                _emailMap = _service.ProcessMailExcel(path);
                _service.SaveMailExcelPath(path);
                MailExcelStatus.Text = $"Mail Mapping: {Path.GetFileName(path)} ({_emailMap.Count} contacts)";
                ShowNotification("Mail Excel loaded and remembered successfully.", "success");
            }
            catch (Exception ex)
            {
                ShowNotification($"Mail Excel Error: {ex.Message}", "error");
            }
        }
    }

    private void UploadFileBtn_Click(object sender, RoutedEventArgs e)
    {
        var dlg = new OpenFileDialog
        {
            Title = "Select up to 4 Excel Loading Reports",
            Filter = "Excel Files (*.xlsx;*.xls)|*.xlsx;*.xls|All Files (*.*)|*.*",
            Multiselect = true
        };

        if (dlg.ShowDialog() == true)
        {
            if (dlg.FileNames.Length > 4)
            {
                ShowNotification("Error: Please select a maximum of 4 files.", "error");
                _selectedFiles.Clear();
                StatusLabel.Text = "No files selected";
                return;
            }

            _selectedFiles.Clear();
            _selectedFiles.AddRange(dlg.FileNames);
            StatusLabel.Text = $"Selected {_selectedFiles.Count} file(s) ready to run.";
            ShowNotification($"Selected {_selectedFiles.Count} file(s) ready to run.", "success");
        }
    }

    private async void RunBtn_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedFiles.Count == 0)
        {
            ShowNotification("Please upload file(s) first.", "warning");
            return;
        }

        RunBtn.IsEnabled = false;
        ShowNotification("Processing Excel data...", "info");
        StatusLabel.Text = "Processing Excel loading report...";

        try
        {
            var file = _selectedFiles[0];
            var summaries = await Task.Run(() => _service.ProcessLoadingReport(file));

            _locationSummaries.Clear();
            foreach (var s in summaries)
            {
                _locationSummaries.Add(s);
            }

            StatusLabel.Text = $"Processed {summaries.Count} locations from {Path.GetFileName(file)}.";
            ShowNotification($"Successfully processed {summaries.Count} locations.", "success");
        }
        catch (Exception ex)
        {
            ShowNotification($"Error: {ex.Message}", "error");
            StatusLabel.Text = "Error processing file.";
        }
        finally
        {
            RunBtn.IsEnabled = true;
        }
    }

    private void ClearBtn_Click(object sender, RoutedEventArgs e)
    {
        _selectedFiles.Clear();
        _locationSummaries.Clear();
        StatusLabel.Text = "No files selected";
        NotificationBorder.Visibility = Visibility.Collapsed;
    }

    private bool ValidateInputs(PackingListLocationSummary summary)
    {
        if (string.IsNullOrWhiteSpace(summary.GdnNumber) || string.IsNullOrWhiteSpace(summary.VehicleNumber))
        {
            ShowNotification($"Please fill in GDN No & Vehicle No for {summary.Location}.", "warning");
            return false;
        }
        return true;
    }

    private void SaveRowBtn_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button btn || btn.DataContext is not PackingListLocationSummary summary)
            return;

        if (!ValidateInputs(summary))
            return;

        var dlg = new SaveFileDialog
        {
            Title = $"Save Packing List - {summary.Location}",
            FileName = $"Packing List - {summary.Location}.xlsx",
            DefaultExt = ".xlsx",
            Filter = "Excel Files (*.xlsx)|*.xlsx"
        };

        if (dlg.ShowDialog() == true)
        {
            if (_service.CreateExcelFile(summary, dlg.FileName))
            {
                ShowNotification($"Packing list for {summary.Location} saved successfully!", "success");
            }
            else
            {
                ShowNotification($"Failed to save packing list for {summary.Location}.", "error");
            }
        }
    }

    private void PdfRowBtn_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button btn || btn.DataContext is not PackingListLocationSummary summary)
            return;

        var dlg = new OpenFileDialog
        {
            Title = $"Select GDN PDF for {summary.Location}",
            Filter = "PDF Files (*.pdf)|*.pdf|All Files (*.*)|*.*"
        };

        if (dlg.ShowDialog() == true)
        {
            summary.AttachedPdfPath = dlg.FileName;
            ShowNotification($"Attached: {Path.GetFileName(dlg.FileName)}", "success");
        }
    }

    private async void MailRowBtn_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button btn || btn.DataContext is not PackingListLocationSummary summary)
            return;

        if (!ValidateInputs(summary))
            return;

        if (string.IsNullOrWhiteSpace(summary.AttachedPdfPath) || !File.Exists(summary.AttachedPdfPath))
        {
            ShowNotification($"Please attach a PDF for {summary.Location} before mailing.", "warning");
            return;
        }

        var toEmail = string.Empty;
        if (!string.IsNullOrWhiteSpace(summary.CleanAddr) && _emailMap.TryGetValue(summary.CleanAddr, out var mappedEmail))
        {
            toEmail = mappedEmail;
        }
        else
        {
            ShowNotification($"No email found for code '{summary.CleanAddr}' in Mail Excel. Opening draft with CC list.", "warning");
        }

        btn.IsEnabled = false;
        try
        {
            await _service.SendMailAsync(summary, toEmail);

            if (!string.IsNullOrWhiteSpace(toEmail))
            {
                ShowNotification($"Email drafted to {toEmail} (CC added).", "success");
            }
            else
            {
                ShowNotification("Email drafted (No 'To' recipient, CC added).", "warning");
            }
        }
        catch (Exception ex)
        {
            ShowNotification($"Failed to draft email: {ex.Message}", "error");
        }
        finally
        {
            btn.IsEnabled = true;
        }
    }
}
