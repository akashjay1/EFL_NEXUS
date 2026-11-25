using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using EflNexus.App.Helpers;
using EflNexus.Core.Infrastructure;
using EflNexus.Core.OutlookEmail;
using EflNexus.Core.Reconciliation;
using MediaColor = System.Windows.Media.Color;
using SolidBrush = System.Windows.Media.SolidColorBrush;

namespace EflNexus.App.Dialogs;

public partial class SendVarianceDialog : Window
{
    private const string PresetPlaceholder = "-- Select Client / Site Manager --";

    private readonly bool _isDarkMode;
    private readonly Func<(string Client, string JobId, string Gatepass)>? _jobDetailsResolver;
    private readonly Action<string, string>? _logCallback;
    private readonly TemplateStore _templateStore;
    private readonly OutlookComClient _outlookClient = new();
    private readonly List<string> _attachmentPaths = [];

    private string? _recipientJobId;

    public SendVarianceDialog(
        Window? owner,
        string? initialAttachment = null,
        bool isDarkMode = false,
        Func<(string Client, string JobId, string Gatepass)>? jobDetailsResolver = null,
        Action<string, string>? logCallback = null)
    {
        InitializeComponent();
        App.TrySetWindowIcon(this);
        ImageLoader.SizeAndCenterDialog(this, owner, 0.75, 0.85, 680, 620, 800, 750);

        _isDarkMode = isDarkMode;
        _jobDetailsResolver = jobDetailsResolver;
        _logCallback = logCallback;

        var templatesPath = Path.Combine(AppPaths.AppDir, "variance_templates.xlsx");
        _templateStore = new TemplateStore(templatesPath);
        if (!File.Exists(templatesPath))
        {
            try { _templateStore.Save(); } catch { }
        }

        if (!string.IsNullOrWhiteSpace(initialAttachment) && File.Exists(initialAttachment))
            _attachmentPaths.Add(initialAttachment);

        RichTextTableHelper.ConfigureFlatParagraphSpacing(BodyEditor);
        RichTextTableHelper.SetPlainText(BodyEditor, "Dear ,\n\nPlease check and advise the variance below.\n");

        ReloadPresetCombo(PresetPlaceholder);
        RefreshAttachmentList();
        RefreshSubject();
        ApplyTheme();
    }

    private void ApplyTheme()
    {
        var bg = new SolidBrush(_isDarkMode ? MediaColor.FromRgb(0x0B, 0x14, 0x20) : MediaColor.FromRgb(0xFA, 0xF8, 0xF2));
        var fg = new SolidBrush(_isDarkMode ? MediaColor.FromRgb(0xEC, 0xEC, 0xEC) : MediaColor.FromRgb(0x0F, 0x17, 0x2A));
        var entryBg = new SolidBrush(_isDarkMode ? MediaColor.FromRgb(0x16, 0x2E, 0x4C) : MediaColor.FromRgb(0xFF, 0xFF, 0xFF));

        Background = bg;
        HeaderTitle.Foreground = fg;
        TemplateGroup.Foreground = fg;
        FieldsGroup.Foreground = fg;
        BodyGroup.Foreground = fg;
        AttachGroup.Foreground = fg;
        IncludeSignatureCheck.Foreground = fg;

        ToBox.Background = entryBg;
        ToBox.Foreground = fg;
        CcBox.Background = entryBg;
        CcBox.Foreground = fg;
        SubjectBox.Background = entryBg;
        SubjectBox.Foreground = fg;
        BodyEditor.Background = entryBg;
        BodyEditor.Foreground = fg;
        AttachListBox.Background = entryBg;
        AttachListBox.Foreground = fg;
    }

    private void ReloadPresetCombo(string selectName)
    {
        var names = new List<string> { PresetPlaceholder };
        names.AddRange(_templateStore.GetNames());
        TemplateCombo.ItemsSource = names;
        TemplateCombo.SelectedItem = names.Contains(selectName) ? selectName : PresetPlaceholder;
    }

    public void RefreshSubject()
    {
        var (client, jobId, gatepass) = ResolveJobDetails();
        SubjectBox.Text = (!string.IsNullOrEmpty(client) && !string.IsNullOrEmpty(jobId) && !string.IsNullOrEmpty(gatepass))
            ? $"{client} - {jobId} - {gatepass}"
            : string.Empty;

        if (jobId == _recipientJobId)
            return;

        _recipientJobId = jobId;
        var template = !string.IsNullOrEmpty(client) ? _templateStore.GetTemplate(client) : null;
        if (template is not null)
        {
            TemplateCombo.SelectedItem = template.Name;
            ApplySelectedTemplate();
        }
        else
        {
            TemplateCombo.SelectedItem = PresetPlaceholder;
            ToBox.Text = string.Empty;
            CcBox.Text = string.Empty;
        }
    }

    private (string Client, string JobId, string Gatepass) ResolveJobDetails()
    {
        if (_jobDetailsResolver is null)
            return ("", "", "");
        return _jobDetailsResolver();
    }

    private void TemplateCombo_SelectionChanged(object sender, SelectionChangedEventArgs e)
        => ApplySelectedTemplate();

    private void ApplySelectedTemplate()
    {
        if (TemplateCombo.SelectedItem is not string name || name == PresetPlaceholder)
            return;

        var tpl = _templateStore.GetTemplate(name);
        if (tpl is not null)
        {
            ToBox.Text = tpl.To;
            CcBox.Text = tpl.Cc;
        }
        else
        {
            ToBox.Text = string.Empty;
            CcBox.Text = string.Empty;
        }
    }

    private void AddPreset_Click(object sender, RoutedEventArgs e)
    {
        var dlg = new AddTemplateDialog(this, (name, toAddr, ccAddr) =>
        {
            _templateStore.AddOrUpdateTemplate(name, toAddr, ccAddr);
            ReloadPresetCombo(name);
            ApplySelectedTemplate();
        });
        dlg.ShowDialog();
    }

    private void BodyEditor_PreviewKeyDown(object sender, System.Windows.Input.KeyEventArgs e)
    {
        if (e.Key == Key.V && (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control)
        {
            if (RichTextTableHelper.TryPasteExcelOrText(BodyEditor))
                e.Handled = true;
        }
    }

    private void InsertVariance_Click(object sender, RoutedEventArgs e)
    {
        string? excelPath = _attachmentPaths.FirstOrDefault(p =>
            File.Exists(p) &&
            (p.EndsWith(".xlsx", StringComparison.OrdinalIgnoreCase)
             || p.EndsWith(".xls", StringComparison.OrdinalIgnoreCase)
             || p.EndsWith(".xlsm", StringComparison.OrdinalIgnoreCase)
             || p.EndsWith(".xlsb", StringComparison.OrdinalIgnoreCase)));

        if (excelPath is null)
        {
            var dlg = new Microsoft.Win32.OpenFileDialog
            {
                Title = "Select Reconciliation Report with Variance Sheet",
                Filter = "Excel files (*.xlsx;*.xls;*.xlsm;*.xlsb)|*.xlsx;*.xls;*.xlsm;*.xlsb|All files (*.*)|*.*"
            };
            if (dlg.ShowDialog(this) != true)
                return;

            excelPath = dlg.FileName;
            if (!_attachmentPaths.Contains(excelPath))
            {
                _attachmentPaths.Add(excelPath);
                RefreshAttachmentList();
            }
        }

        try
        {
            var sheetNames = ExcelReaderHelper.GetSheetNames(excelPath);
            string targetSheet = sheetNames.FirstOrDefault(s => s.Contains("variance", StringComparison.OrdinalIgnoreCase))
                ?? sheetNames.FirstOrDefault()
                ?? "Sheet1";

            var grid = ExcelReaderHelper.ReadVarianceSheetGrid(excelPath);
            RichTextTableHelper.InsertGridTable(BodyEditor, grid);
            System.Windows.MessageBox.Show(
                this,
                $"Successfully inserted {Math.Max(0, grid.Count - 1)} rows from '{targetSheet}' sheet into message body.",
                "Variance Inserted",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
        }
        catch (Exception exc)
        {
            System.Windows.MessageBox.Show(
                this,
                $"Could not read variance sheet from Excel file:\n\n{exc.Message}",
                "Read Error",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
        }
    }

    private void AttachFiles_Click(object sender, RoutedEventArgs e)
    {
        var dlg = new Microsoft.Win32.OpenFileDialog
        {
            Title = "Select Files to Attach",
            Multiselect = true,
            Filter = "Excel and PDF files (*.xlsx;*.xls;*.pdf)|*.xlsx;*.xls;*.pdf|Excel files (*.xlsx;*.xls)|*.xlsx;*.xls|PDF files (*.pdf)|*.pdf|All files (*.*)|*.*"
        };
        if (dlg.ShowDialog(this) == true)
        {
            foreach (var p in dlg.FileNames)
            {
                if (!_attachmentPaths.Contains(p))
                    _attachmentPaths.Add(p);
            }
            RefreshAttachmentList();
        }
    }

    private void RemoveAttachment_Click(object sender, RoutedEventArgs e)
    {
        var indices = AttachListBox.SelectedItems
            .Cast<object>()
            .Select(item => AttachListBox.Items.IndexOf(item))
            .Where(idx => idx >= 0)
            .OrderByDescending(idx => idx)
            .ToList();

        foreach (int idx in indices)
        {
            if (idx < _attachmentPaths.Count)
                _attachmentPaths.RemoveAt(idx);
        }
        RefreshAttachmentList();
    }

    private void ClearAttachments_Click(object sender, RoutedEventArgs e)
    {
        _attachmentPaths.Clear();
        RefreshAttachmentList();
    }

    private void RefreshAttachmentList()
    {
        AttachListBox.ItemsSource = null;
        AttachListBox.ItemsSource = _attachmentPaths.Select(p => $"📄 {Path.GetFileName(p)}").ToList();
    }

    private (string To, string Cc, string Subject, string Body)? GatherAndValidate()
    {
        string toAddr = (ToBox.Text ?? string.Empty).Trim();
        string ccAddr = (CcBox.Text ?? string.Empty).Trim();
        var (client, jobId, gatepass) = ResolveJobDetails();
        string subject = (!string.IsNullOrEmpty(client) && !string.IsNullOrEmpty(jobId) && !string.IsNullOrEmpty(gatepass))
            ? $"{client} - {jobId} - {gatepass}"
            : (SubjectBox.Text ?? string.Empty).Trim();
        SubjectBox.Text = subject;
        string body = RichTextTableHelper.GetPlainText(BodyEditor);

        if (string.IsNullOrEmpty(toAddr))
        {
            System.Windows.MessageBox.Show(this, "Please enter at least one 'To:' recipient email.", "Missing Recipient", MessageBoxButton.OK, MessageBoxImage.Warning);
            return null;
        }

        if (string.IsNullOrEmpty(subject))
        {
            System.Windows.MessageBox.Show(
                this,
                "The client code, Job ID, and gatepass are required for the subject. Check that the corresponding job in Pending Jobs has all three values.",
                "Missing Job Details",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
            return null;
        }

        return (toAddr, ccAddr, subject, body);
    }

    private async void PreviewEmail_Click(object sender, RoutedEventArgs e)
    {
        var data = GatherAndValidate();
        if (data is null)
            return;

        var (toAddr, ccAddr, subject, body) = data.Value;
        bool includeSig = IncludeSignatureCheck.IsChecked == true;
        var existingFiles = _attachmentPaths.Where(File.Exists).ToList();
        var fragment = VarianceHtmlFormatter.ComposeVarianceBodyFragment(body);

        PreviewBtn.IsEnabled = false;
        SendBtn.IsEnabled = false;
        try
        {
            await _outlookClient.PreviewAsync(toAddr, ccAddr, subject, fragment, existingFiles, includeSig, isRawHtmlFragment: true);
        }
        catch (Exception exc)
        {
            System.Windows.MessageBox.Show(this, $"Could not preview email in Outlook:\n\n{exc.Message}", "Outlook Error", MessageBoxButton.OK, MessageBoxImage.Error);
        }
        finally
        {
            PreviewBtn.IsEnabled = true;
            SendBtn.IsEnabled = true;
        }
    }

    private async void SendEmail_Click(object sender, RoutedEventArgs e)
    {
        var data = GatherAndValidate();
        if (data is null)
            return;

        var (toAddr, ccAddr, subject, body) = data.Value;
        string attachNames = _attachmentPaths.Count > 0
            ? string.Join("\n", _attachmentPaths.Select(p => $"  • {Path.GetFileName(p)}"))
            : "  (none)";

        string confirm =
            $"To: {toAddr}\n" +
            $"CC: {(string.IsNullOrEmpty(ccAddr) ? "(none)" : ccAddr)}\n" +
            $"Subject: {subject}\n" +
            $"Attachments:\n{attachNames}\n\n" +
            "Send this variance email via Outlook now?";

        if (System.Windows.MessageBox.Show(this, confirm, "Confirm Send", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes)
            return;

        bool includeSig = IncludeSignatureCheck.IsChecked == true;
        var existingFiles = _attachmentPaths.Where(File.Exists).ToList();
        var fragment = VarianceHtmlFormatter.ComposeVarianceBodyFragment(body);

        PreviewBtn.IsEnabled = false;
        SendBtn.IsEnabled = false;
        try
        {
            await _outlookClient.SendAsync(toAddr, ccAddr, subject, fragment, existingFiles, includeSig, isRawHtmlFragment: true);
            System.Windows.MessageBox.Show(this, "Variance email was successfully sent via Outlook.", "Email Sent", MessageBoxButton.OK, MessageBoxImage.Information);
            _logCallback?.Invoke($"📧 Variance email sent to: {toAddr} (Subject: {subject})", "SUCCESS");
            Close();
        }
        catch (Exception exc)
        {
            System.Windows.MessageBox.Show(this, $"Could not send email:\n\n{exc.Message}", "Outlook Error", MessageBoxButton.OK, MessageBoxImage.Error);
        }
        finally
        {
            PreviewBtn.IsEnabled = true;
            SendBtn.IsEnabled = true;
        }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e) => Close();
}
