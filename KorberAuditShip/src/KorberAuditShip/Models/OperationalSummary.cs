namespace KorberAuditShip.Models;

/// <summary>
/// Aggregate metrics displayed in the Operational Summary card and status bar.
/// </summary>
public sealed record OperationalSummary(
    int TotalWhIds,
    int TotalGatePassIds,
    int TotalUniqueLoadIds,
    string DoorLocation)
{
    public string CardSummaryText =>
        $"Total WH IDs: {TotalWhIds}    |    Total Gate Pass IDs: {TotalGatePassIds}    |    Total Unique Load IDs: {TotalUniqueLoadIds}    |    Door Location: {DoorLocation}";

    public string LoadedStatusText =>
        $"Loaded successfully | WH Count: {TotalWhIds} | Gate Pass Count: {TotalGatePassIds} | Unique Loads: {TotalUniqueLoadIds:N0} | Door Location: {DoorLocation}";
}
