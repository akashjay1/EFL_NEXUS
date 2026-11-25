using System.Windows;
using System.Windows.Threading;
using KorberAuditShip.Models;
using KorberAuditShip.Views;
using Microsoft.Win32;

namespace KorberAuditShip.Services;

public sealed class WpfDialogService : IDialogService
{
    private readonly Window? _fixedOwner;
    private readonly Func<Window?>? _ownerProvider;
    private readonly Dispatcher _dispatcher;

    public WpfDialogService(Window? owner = null)
    {
        _fixedOwner = owner;
        _dispatcher = owner?.Dispatcher ?? Application.Current?.Dispatcher ?? Dispatcher.CurrentDispatcher;
    }

    public WpfDialogService(Func<Window?> ownerProvider, Dispatcher? dispatcher = null)
    {
        _ownerProvider = ownerProvider;
        _dispatcher = dispatcher ?? Application.Current?.Dispatcher ?? Dispatcher.CurrentDispatcher;
    }

    private Window? Owner
    {
        get
        {
            if (_fixedOwner != null)
                return _fixedOwner;

            if (_dispatcher != null && !_dispatcher.CheckAccess())
            {
                try
                {
                    return _dispatcher.Invoke(() => _ownerProvider?.Invoke() ?? Application.Current?.MainWindow);
                }
                catch
                {
                    return null;
                }
            }
            return _ownerProvider?.Invoke() ?? Application.Current?.MainWindow;
        }
    }

    public string? OpenExcelFile()
    {
        var dialog = new OpenFileDialog
        {
            Title = "Select Excel File",
            Filter = "Excel Files (*.xls;*.xlsx)|*.xls;*.xlsx",
            CheckFileExists = true
        };
        var owner = Owner;
        return (owner is not null ? dialog.ShowDialog(owner) : dialog.ShowDialog()) == true ? dialog.FileName : null;
    }

    public string? SaveExcelFile(string defaultFileName)
    {
        var dialog = new SaveFileDialog
        {
            Title = "Save Aligned Data as Excel",
            DefaultExt = ".xlsx",
            FileName = defaultFileName,
            Filter = "Excel Workbook (*.xlsx)|*.xlsx"
        };
        var owner = Owner;
        return (owner is not null ? dialog.ShowDialog(owner) : dialog.ShowDialog()) == true ? dialog.FileName : null;
    }

    public string? SavePdfFile(string defaultFileName)
    {
        var dialog = new SaveFileDialog
        {
            Title = "Save Aligned Data as PDF",
            DefaultExt = ".pdf",
            FileName = defaultFileName,
            Filter = "PDF File (*.pdf)|*.pdf"
        };
        var owner = Owner;
        return (owner is not null ? dialog.ShowDialog(owner) : dialog.ShowDialog()) == true ? dialog.FileName : null;
    }

    public string? PromptInput(string title, string prompt, string initialValue = "")
    {
        var dlg = new PromptDialog(title, prompt, initialValue);
        var owner = Owner;
        if (owner is not null)
        {
            dlg.Owner = owner;
        }
        return dlg.ShowDialog() == true ? dlg.ResponseText : null;
    }

    public KorberCredentials? PromptCredentials(KorberCredentials? current, CredentialService credentialService)
    {
        var dlg = new CredentialsDialog(current, credentialService);
        var owner = Owner;
        if (owner is not null)
        {
            dlg.Owner = owner;
        }
        return dlg.ShowDialog() == true ? dlg.SavedCredentials : null;
    }

    public void ShowInfo(string title, string message)
    {
        var owner = Owner;
        if (owner is not null)
            MessageBox.Show(owner, message, title, MessageBoxButton.OK, MessageBoxImage.Information);
        else
            MessageBox.Show(message, title, MessageBoxButton.OK, MessageBoxImage.Information);
    }

    public void ShowWarning(string title, string message)
    {
        var owner = Owner;
        if (owner is not null)
            MessageBox.Show(owner, message, title, MessageBoxButton.OK, MessageBoxImage.Warning);
        else
            MessageBox.Show(message, title, MessageBoxButton.OK, MessageBoxImage.Warning);
    }

    public void ShowError(string title, string message)
    {
        var owner = Owner;
        if (owner is not null)
            MessageBox.Show(owner, message, title, MessageBoxButton.OK, MessageBoxImage.Error);
        else
            MessageBox.Show(message, title, MessageBoxButton.OK, MessageBoxImage.Error);
    }

    public void CopyTextToClipboard(string text)
        => Clipboard.SetText(text);

    public void InvokeOnUiThread(Action action)
    {
        if (_dispatcher != null && !_dispatcher.CheckAccess())
            _dispatcher.Invoke(action);
        else
            action();
    }
}
