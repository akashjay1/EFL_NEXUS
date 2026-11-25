using KorberAuditShip.Models;

namespace KorberAuditShip.Services;

public interface IDialogService
{
    string? OpenExcelFile();
    string? SaveExcelFile(string defaultFileName);
    string? SavePdfFile(string defaultFileName);
    string? PromptInput(string title, string prompt, string initialValue = "");
    KorberCredentials? PromptCredentials(KorberCredentials? current, CredentialService credentialService);
    void ShowInfo(string title, string message);
    void ShowWarning(string title, string message);
    void ShowError(string title, string message);
    void CopyTextToClipboard(string text);
    void InvokeOnUiThread(Action action);
}
