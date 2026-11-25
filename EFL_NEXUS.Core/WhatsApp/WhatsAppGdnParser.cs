using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace EflNexus.Core.WhatsApp;

/// <summary>
/// Local GDN message extraction and validation (1:1 parity with whatsapp_gdn.py).
/// </summary>
public static partial class WhatsAppGdnParser
{
    public static readonly string[] GdnFields =
    [
        "warehouse",
        "client",
        "gatepass",
        "delivery_location",
        "seal"
    ];

    public static readonly IReadOnlyDictionary<string, string> FieldLabels =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["warehouse"] = "Warehouse ID",
            ["client"] = "Client Code",
            ["gatepass"] = "Gate Pass No.",
            ["delivery_location"] = "Delivery Location (Note)",
            ["seal"] = "Seal No.",
            ["door_location"] = "Door Location"
        };

    [GeneratedRegex(
        @"^\s*[*_~`]*\s*(WH\s*ID|Warehouse(?:\s*ID)?|Client\s*Code|Gate\s*Pass(?:\s*(?:No\.?|Number|#))?|Door\s*Location|Seal\s*(?:Numbers?|Nos?\.?|#)|Note|Delivery\s*Location)\s*[*_~`]*\s*[:#=\-]\s*[*_~`]*\s*(.*?)\s*$",
        RegexOptions.IgnoreCase)]
    private static partial Regex LabelRegex();

    [GeneratedRegex(@"[\s.#]")]
    private static partial Regex LabelNormalizeRegex();

    public static string DataDirectory()
    {
        var baseDir = Environment.GetEnvironmentVariable("LOCALAPPDATA");
        if (string.IsNullOrWhiteSpace(baseDir))
            baseDir = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (string.IsNullOrWhiteSpace(baseDir))
            baseDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".local", "share");
        return Path.Combine(baseDir, "EFL_NEXUS", "whatsapp_gdn");
    }

    public static ParsedGdn ParseGdnMessage(string? text)
    {
        var fields = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["warehouse"] = "",
            ["client"] = "",
            ["gatepass"] = "",
            ["delivery_location"] = "",
            ["seal"] = "",
            ["door_location"] = ""
        };
        var warnings = new List<string>();
        bool activeNote = false;
        var normalizedText = (text ?? "").Replace("\r\n", "\n").Replace('\r', '\n');
        foreach (var line in normalizedText.Split('\n'))
        {
            var match = LabelRegex().Match(line);
            if (!match.Success)
            {
                if (activeNote && !string.IsNullOrWhiteSpace(line) && !line.Contains(':', StringComparison.Ordinal))
                {
                    fields["delivery_location"] += "\n" + line.Trim().Trim('*', '_', '~', '`');
                }
                else
                {
                    activeNote = false;
                }
                continue;
            }

            var label = LabelNormalizeRegex().Replace(match.Groups[1].Value, "").ToLowerInvariant();
            string key;
            if (label.StartsWith("wh", StringComparison.Ordinal) || label.StartsWith("warehouse", StringComparison.Ordinal))
                key = "warehouse";
            else if (label.StartsWith("client", StringComparison.Ordinal))
                key = "client";
            else if (label.StartsWith("gate", StringComparison.Ordinal))
                key = "gatepass";
            else if (label.StartsWith("door", StringComparison.Ordinal))
                key = "door_location";
            else if (label.StartsWith("seal", StringComparison.Ordinal))
                key = "seal";
            else
                key = "delivery_location";

            var value = match.Groups[2].Value.Trim().Trim('*', '_', '~', '`').Trim();
            if (value == "-")
                value = "";

            if (!string.IsNullOrEmpty(fields[key]) && !string.Equals(fields[key], value, StringComparison.Ordinal))
                warnings.Add($"Conflicting {FieldLabels[key]} values: {fields[key]} / {value}");
            else
                fields[key] = value;

            activeNote = key == "delivery_location" && !string.IsNullOrEmpty(value);
        }

        int count = GdnFields.Count(k => !string.IsNullOrEmpty(fields[k]));
        bool candidate = count >= 2 &&
            (!string.IsNullOrEmpty(fields["warehouse"]) ||
             !string.IsNullOrEmpty(fields["client"]) ||
             !string.IsNullOrEmpty(fields["gatepass"]));

        return new ParsedGdn
        {
            Fields = fields,
            Warnings = warnings,
            Candidate = candidate
        };
    }

    public static List<string> ValidateFields(IReadOnlyDictionary<string, string> fields, IReadOnlySet<string> warehouses)
    {
        var errors = new List<string>();
        foreach (var key in GdnFields)
        {
            var val = fields.TryGetValue(key, out var raw) ? (raw ?? "").Trim() : "";
            if (val is "" or "-")
                errors.Add($"Missing {FieldLabels[key]}");
        }

        foreach (var key in GdnFields)
        {
            var raw = fields.TryGetValue(key, out var v) ? (v ?? "") : "";
            var allowCrLf = key == "delivery_location";
            if (raw.Any(ch => ch < 32 && (!allowCrLf || (ch != '\r' && ch != '\n'))))
                errors.Add($"Remove control characters from {FieldLabels[key]}");
        }

        var warehouse = (fields.TryGetValue("warehouse", out var whRaw) ? whRaw ?? "" : "").Trim().ToUpperInvariant();
        if (!string.IsNullOrEmpty(warehouse) && warehouses.Count > 0 && !warehouses.Contains(warehouse))
            errors.Add($"Unknown Warehouse ID: {warehouse}");

        return errors;
    }

    public static Dictionary<string, string> FormFields(IReadOnlyDictionary<string, string> fields)
    {
        var result = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var key in GdnFields)
            result[key] = fields.TryGetValue(key, out var v) ? (v ?? "") : "";

        var deliv = result["delivery_location"].Replace("\r\n", "\n").Replace('\r', '\n');
        var parts = deliv.Split('\n').Select(l => l.Trim()).Where(l => l.Length > 0);
        result["delivery_location"] = string.Join(" ", parts);
        return result;
    }

    public static string ContentFingerprint(string? text)
    {
        var tokens = (text ?? "").Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries);
        var normalized = string.Join(" ", tokens);
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(normalized));
        return Convert.ToHexStringLower(hash);
    }

    public static string ReceivedLabel(string? messageTime, string? receivedAt, string? capturedAt = null)
    {
        if (!string.IsNullOrEmpty(messageTime))
            return messageTime;
        var captured = !string.IsNullOrEmpty(receivedAt) ? receivedAt : capturedAt;
        if (!string.IsNullOrEmpty(captured) &&
            DateTimeOffset.TryParse(captured, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind, out var dto))
        {
            var local = dto.ToLocalTime();
            return "Captured " + local.ToString("dd MMM yyyy HH:mm", CultureInfo.InvariantCulture);
        }
        return "Time unavailable";
    }
}
