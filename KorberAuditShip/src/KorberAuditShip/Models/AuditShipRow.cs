using System.ComponentModel;
using System.Globalization;
using System.Runtime.CompilerServices;

namespace KorberAuditShip.Models;

/// <summary>
/// Represents one normalized, deduplicated row in the Aligned Data Table.
/// </summary>
public sealed class AuditShipRow : INotifyPropertyChanged
{
    private string _loadAuditStatus = string.Empty;
    private string _shippingStatus = string.Empty;

    public int RowIndex { get; set; }

    public string WhId { get; init; } = string.Empty;

    public string LoadId { get; init; } = string.Empty;

    public string GatePassId { get; init; } = string.Empty;

    public string DoorLocation { get; init; } = string.Empty;

    public string LoadAuditStatus
    {
        get => _loadAuditStatus;
        set
        {
            var normalized = CleanValue(value);
            if (_loadAuditStatus == normalized) return;
            _loadAuditStatus = normalized;
            OnPropertyChanged();
        }
    }

    public string ShippingStatus
    {
        get => _shippingStatus;
        set
        {
            var normalized = CleanValue(value);
            if (_shippingStatus == normalized) return;
            _shippingStatus = normalized;
            OnPropertyChanged();
        }
    }

    public int DisplayRowNumber => RowIndex + 1;

    public event PropertyChangedEventHandler? PropertyChanged;

    private void OnPropertyChanged([CallerMemberName] string? propertyName = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));

    /// <summary>
    /// Converts arbitrary Excel/object values into clean single-string cell text,
    /// mirroring pandas NaN/None handling without spurious ".0" suffixes on integral numbers.
    /// </summary>
    public static string CleanValue(object? value)
    {
        if (value is null || value == DBNull.Value)
            return string.Empty;

        return value switch
        {
            double d when double.IsNaN(d) || double.IsInfinity(d) => string.Empty,
            double d => d == Math.Truncate(d)
                ? d.ToString("0", CultureInfo.InvariantCulture)
                : d.ToString("0.###############", CultureInfo.InvariantCulture),
            float f when float.IsNaN(f) || float.IsInfinity(f) => string.Empty,
            float f => f == Math.Truncate(f)
                ? f.ToString("0", CultureInfo.InvariantCulture)
                : f.ToString("0.#######", CultureInfo.InvariantCulture),
            decimal m => m == Math.Truncate(m)
                ? m.ToString("0", CultureInfo.InvariantCulture)
                : m.ToString("0.############################", CultureInfo.InvariantCulture),
            string s => s.Trim(),
            _ => value.ToString()?.Trim() ?? string.Empty
        };
    }

    /// <summary>
    /// Uppercases and trims a value (matches Python's normalize_value).
    /// </summary>
    public static string NormalizeValue(object? value)
        => CleanValue(value).ToUpperInvariant();
}
