using System.Globalization;
using System.Windows;
using EflNexus.Core.GrnOcr;
using EflNexus.Core.WhatsApp;
using Microsoft.Data.Sqlite;

namespace EflNexus.App.Dialogs;

public partial class GrnOcrSettingsDialog : Window
{
    private readonly WhatsAppGrnStore _store;

    public GrnOcrSettingsDialog(Window? owner, WhatsAppGrnStore store)
    {
        InitializeComponent();
        App.TrySetWindowIcon(this);
        if (owner is not null && owner.IsVisible)
            Owner = owner;
        else
            WindowStartupLocation = WindowStartupLocation.CenterScreen;

        _store = store;
        var config = GrnCloudOcrEngine.CloudSettings(store);
        bool isSpace = GrnCloudOcrEngine.IsOcrSpace(config.Endpoint);

        EnabledCheck.IsChecked = isSpace && config.Enabled;
        EndpointBox.Text = isSpace ? config.Endpoint : GrnCloudOcrEngine.OcrSpaceEndpoint;
        LimitBox.Text = config.DailyLimit > 0 ? config.DailyLimit.ToString(CultureInfo.InvariantCulture) : string.Empty;

        int usage = 0;
        try { usage = GrnCloudOcrEngine.UsageToday(store); } catch { }

        UsageText.Text =
            $"Uploads reserved today: {usage}. The day follows this PC’s local date.\n" +
            "Uncertain uploads count toward the limit. Retry Cloud uploads them again and may incur another charge.\n" +
            "OCR.space returns results in one request. Lost responses cannot be resumed; retry sends another upload.";
    }

    private void Close_Click(object sender, RoutedEventArgs e) => Close();

    private void Save_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            string rawEndpoint = (EndpointBox.Text ?? string.Empty).Trim();
            string endpoint = string.IsNullOrEmpty(rawEndpoint) ? string.Empty : GrnCloudOcrEngine.ValidateEndpoint(rawEndpoint);
            if (!string.IsNullOrEmpty(endpoint) && !GrnCloudOcrEngine.IsOcrSpace(endpoint))
                throw new ArgumentException("Enter your OCR.space /parse/image API endpoint.");

            string rawLimit = (LimitBox.Text ?? string.Empty).Trim();
            int limit = 0;
            if (!string.IsNullOrEmpty(rawLimit))
            {
                if (!int.TryParse(rawLimit, NumberStyles.Integer, CultureInfo.InvariantCulture, out limit))
                    throw new ArgumentException("Enter a valid positive whole number for the daily upload limit.");
            }
            if (limit < 0)
                throw new ArgumentException("The daily upload limit cannot be negative.");

            bool enabled = EnabledCheck.IsChecked == true;
            if (enabled && (string.IsNullOrEmpty(endpoint) || limit < 1))
                throw new ArgumentException("Enter the resource endpoint and a positive daily upload limit before enabling uploads.");

            string key = (KeyBox.Password ?? string.Empty).Trim();
            if (!string.IsNullOrEmpty(key))
            {
                if (string.IsNullOrEmpty(endpoint))
                    throw new ArgumentException("Enter the OCR.space API endpoint before saving its key.");
                GrnCloudOcrEngine.SaveCredential(endpoint, key);
                KeyBox.Password = string.Empty;
            }

            if (enabled && string.IsNullOrEmpty(GrnCloudOcrEngine.LoadCredential(endpoint)))
                throw new ArgumentException("Save your OCR.space API key before enabling uploads.");

            _store.SetSetting("grn_cloud_ocr", new
            {
                provider = "ocr_space",
                enabled,
                endpoint,
                daily_limit = limit
            });

            StatusText.Text = "Saved. New difficult photos use this setting. Use Retry Extraction for an existing photo.";
        }
        catch (Exception exc) when (exc is ArgumentException or InvalidOperationException or System.IO.IOException or SqliteException)
        {
            StatusText.Text = exc.Message;
        }
    }
}
