using UserControl = System.Windows.Controls.UserControl;

namespace EflNexus.App.Views;

public partial class KorberToolView : UserControl
{
    private Action? _openWhatsAppInboxCallback;

    public Action? OpenWhatsAppInboxCallback
    {
        get => _openWhatsAppInboxCallback;
        set
        {
            _openWhatsAppInboxCallback = value;
            LaneA.OpenWhatsAppInboxCallback = value;
            LaneB.OpenWhatsAppInboxCallback = value;
        }
    }

    public KorberToolView()
    {
        InitializeComponent();
    }

    public IReadOnlyDictionary<string, KorberLaneControl> GetLanes()
        => new Dictionary<string, KorberLaneControl>(StringComparer.Ordinal)
        {
            ["Lane A"] = LaneA,
            ["Lane B"] = LaneB
        };

    public void TerminateAllSessions()
    {
        try { LaneA.Engine.TerminateSession(); } catch { }
        try { LaneB.Engine.TerminateSession(); } catch { }
    }
}
