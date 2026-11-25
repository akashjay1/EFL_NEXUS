namespace KorberAuditShip.Models;

/// <summary>
/// Credentials required for signing in to Körber One and submitting the RF Fork ID screen.
/// </summary>
public sealed record KorberCredentials(
    string Username,
    string Password,
    string ForkId,
    string Source)
{
    public bool IsComplete =>
        !string.IsNullOrWhiteSpace(Username) &&
        !string.IsNullOrWhiteSpace(Password) &&
        !string.IsNullOrWhiteSpace(ForkId);
}
