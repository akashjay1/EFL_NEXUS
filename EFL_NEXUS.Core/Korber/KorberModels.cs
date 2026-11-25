namespace EflNexus.Core.Korber;

public enum KorberDocType
{
    GDN,
    GRN
}

public enum KorberQueueStatus
{
    Queued,
    Running,
    Done,
    Failed,
    Stopped
}

public static class KorberWarehouses
{
    public static readonly string[] GdnWarehouses =
        ["EGDC", "ESKD", "NUGE", "LPPL", "LPIC", "LPSP", "INMM01"];

    public static readonly string[] GrnWarehouses =
        ["EGDC", "ESKD", "NUGE", "LPPL", "LPSP", "INMM01"];
}

public sealed record KorberCredentials(string KorberUrl, string Username, string Password);

public sealed class KorberFlowRequest
{
    public string DocType { get; set; } = "GDN";
    public string WarehouseId { get; set; } = "";
    public string ClientCode { get; set; } = "";
    public string GatePassNumber { get; set; } = "";
    public string DeliveryLocation { get; set; } = "";
    public string SealNumber { get; set; } = "";
}

public sealed class KorberQueueItem
{
    public string Id { get; init; } = Guid.NewGuid().ToString("N");
    public string DocType { get; init; } = "GDN";
    public string WarehouseId { get; init; } = "";
    public string ClientCode { get; init; } = "";
    public string GatePassNumber { get; init; } = "";
    public string DeliveryLocation { get; init; } = "";
    public string SealNumber { get; init; } = "";
    public KorberQueueStatus Status { get; set; } = KorberQueueStatus.Queued;
    public volatile bool StopRequested;
}
