namespace KorberAuditShip.Models;

public enum RowStepOutcome
{
    Done,
    Skipped
}

public enum CriticalPopupOutcome
{
    None,
    DeviceIdWaitCompleted,
    WorkflowEngineDownClosed
}

public sealed record WorkflowResult(
    bool Success,
    string Message,
    int DoneCount = 0,
    int SkippedCount = 0);

public enum StatusTone
{
    Accent,
    Info,
    Success,
    Warning,
    Error
}
