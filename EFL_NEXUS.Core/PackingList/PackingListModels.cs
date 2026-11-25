using System.ComponentModel;
using System.Runtime.CompilerServices;

namespace EflNexus.Core.PackingList;

public sealed class PackingListGroupedItem
{
    public string ShipToCity { get; set; } = string.Empty;
    public string OrderNumber { get; set; } = string.Empty;
    public string Mlp { get; set; } = string.Empty;
    public string ItemNumber { get; set; } = string.Empty;
    public string Description { get; set; } = string.Empty;
    public string LotNumber { get; set; } = string.Empty;
    public string ExpirationDate { get; set; } = string.Empty;
    public double ActualQty { get; set; }
    public int CountOfLPs { get; set; }
    public string GatePassId { get; set; } = string.Empty;
    public string DeliveryAddr1 { get; set; } = string.Empty;
}

public sealed class PackingListLocationSummary : INotifyPropertyChanged
{
    private string _gdnDate = DateTime.Today.ToString("dd-MM-yyyy");
    private string _gdnNumber = string.Empty;
    private string _vehicleNumber = string.Empty;
    private string _attachedPdfPath = string.Empty;
    private string _attachedPdfName = string.Empty;
    private bool _hasSentMail;

    public string Location { get; set; } = string.Empty;
    public double TotalQty { get; set; }
    public string GatePass { get; set; } = string.Empty;
    public string DeliveryAddr { get; set; } = string.Empty;
    public string CleanAddr { get; set; } = string.Empty;

    public string GdnDate
    {
        get => _gdnDate;
        set => SetField(ref _gdnDate, value);
    }

    public string GdnNumber
    {
        get => _gdnNumber;
        set => SetField(ref _gdnNumber, value);
    }

    public string VehicleNumber
    {
        get => _vehicleNumber;
        set => SetField(ref _vehicleNumber, value);
    }

    public string AttachedPdfPath
    {
        get => _attachedPdfPath;
        set
        {
            if (SetField(ref _attachedPdfPath, value))
            {
                AttachedPdfName = string.IsNullOrWhiteSpace(value) ? string.Empty : System.IO.Path.GetFileName(value);
            }
        }
    }

    public string AttachedPdfName
    {
        get => _attachedPdfName;
        private set => SetField(ref _attachedPdfName, value);
    }

    public bool HasSentMail
    {
        get => _hasSentMail;
        set
        {
            if (SetField(ref _hasSentMail, value))
            {
                OnPropertyChanged(nameof(StatusDot));
            }
        }
    }

    public string StatusDot => HasSentMail ? "●" : string.Empty;

    public List<PackingListGroupedItem> Items { get; set; } = [];

    public event PropertyChangedEventHandler? PropertyChanged;

    private bool SetField<T>(ref T field, T value, [CallerMemberName] string? propertyName = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value)) return false;
        field = value;
        OnPropertyChanged(propertyName);
        return true;
    }

    private void OnPropertyChanged([CallerMemberName] string? propertyName = null)
    {
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}
