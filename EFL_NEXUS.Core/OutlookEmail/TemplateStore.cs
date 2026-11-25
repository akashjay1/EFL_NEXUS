using System.IO;
using ClosedXML.Excel;
using EflNexus.Core.Infrastructure;

namespace EflNexus.Core.OutlookEmail;

public sealed class RecipientTemplate
{
    public string Name { get; set; } = "";
    public string To { get; set; } = "";
    public string Cc { get; set; } = "";
}

public static class RecipientHelpers
{
    public static string NormalizeRecipients(string? rawText)
    {
        if (string.IsNullOrEmpty(rawText))
            return "";
        var replaced = rawText.Replace(',', ';');
        var parts = replaced
            .Split(';')
            .Select(p => p.Trim())
            .Where(p => !string.IsNullOrEmpty(p));
        return string.Join("; ", parts);
    }
}

public sealed class TemplateStore
{
    public const string Placeholder = "-- Select Template --";

    public string FilePath { get; }
    public List<RecipientTemplate> Templates { get; private set; }

    public TemplateStore(string? path = null)
    {
        FilePath = string.IsNullOrWhiteSpace(path)
            ? AppPaths.ResolveResourcePath("templates.xlsx")
            : path;
        Templates = Load();
    }

    public List<RecipientTemplate> Load()
    {
        if (!File.Exists(FilePath))
            return [];

        try
        {
            using var wb = new XLWorkbook(FilePath);
            var ws = wb.Worksheets.FirstOrDefault();
            if (ws is null)
                return [];

            var rows = ws.RangeUsed()?.Rows().ToList();
            if (rows is null || rows.Count == 0)
                return [];

            var firstRow = rows[0];
            var colCount = Math.Max(3, firstRow.CellCount());
            var header = Enumerable.Range(1, colCount)
                .Select(c => firstRow.Cell(c).GetString().Trim().ToLowerInvariant())
                .ToList();

            int nameIdx = header.IndexOf("name");
            int toIdx = header.IndexOf("to");
            int ccIdx = header.IndexOf("cc");
            if (nameIdx < 0 || toIdx < 0 || ccIdx < 0)
            {
                nameIdx = 0;
                toIdx = 1;
                ccIdx = 2;
            }

            var results = new List<RecipientTemplate>();
            foreach (var row in rows.Skip(1))
            {
                var name = row.Cell(nameIdx + 1).GetFormattedString().Trim();
                var toAddr = row.Cell(toIdx + 1).GetFormattedString().Trim();
                var ccAddr = row.Cell(ccIdx + 1).GetFormattedString().Trim();
                if (string.IsNullOrEmpty(name) && string.IsNullOrEmpty(toAddr) && string.IsNullOrEmpty(ccAddr))
                    continue;

                if (!string.IsNullOrEmpty(name))
                {
                    results.Add(new RecipientTemplate
                    {
                        Name = name,
                        To = RecipientHelpers.NormalizeRecipients(toAddr),
                        Cc = RecipientHelpers.NormalizeRecipients(ccAddr)
                    });
                }
            }

            return results
                .OrderBy(t => t.Name, StringComparer.OrdinalIgnoreCase)
                .ToList();
        }
        catch
        {
            return [];
        }
    }

    public void Save()
    {
        var dir = Path.GetDirectoryName(Path.GetFullPath(FilePath));
        if (!string.IsNullOrEmpty(dir))
            Directory.CreateDirectory(dir);

        using var wb = new XLWorkbook();
        var ws = wb.AddWorksheet("Templates");
        ws.Cell(1, 1).Value = "Name";
        ws.Cell(1, 2).Value = "To";
        ws.Cell(1, 3).Value = "CC";

        for (int i = 0; i < Templates.Count; i++)
        {
            var r = i + 2;
            ws.Cell(r, 1).Value = Templates[i].Name;
            ws.Cell(r, 2).Value = Templates[i].To;
            ws.Cell(r, 3).Value = Templates[i].Cc;
        }

        ws.Column(1).Width = 25;
        ws.Column(2).Width = 40;
        ws.Column(3).Width = 40;
        wb.SaveAs(FilePath);
    }

    public void AddOrUpdateTemplate(string name, string toAddr, string ccAddr)
    {
        var cleanName = name.Trim();
        var cleanTo = RecipientHelpers.NormalizeRecipients(toAddr);
        var cleanCc = RecipientHelpers.NormalizeRecipients(ccAddr);

        var existing = Templates.FirstOrDefault(t => string.Equals(t.Name, cleanName, StringComparison.OrdinalIgnoreCase));
        if (existing is not null)
        {
            existing.Name = cleanName;
            existing.To = cleanTo;
            existing.Cc = cleanCc;
        }
        else
        {
            Templates.Add(new RecipientTemplate
            {
                Name = cleanName,
                To = cleanTo,
                Cc = cleanCc
            });
            Templates = Templates.OrderBy(t => t.Name, StringComparer.OrdinalIgnoreCase).ToList();
        }
        Save();
    }

    public List<string> GetNames() => Templates.Select(t => t.Name).ToList();

    public RecipientTemplate? GetTemplate(string? name)
    {
        if (string.IsNullOrWhiteSpace(name))
            return null;
        var clean = name.Trim();
        return Templates.FirstOrDefault(t => string.Equals(t.Name, clean, StringComparison.OrdinalIgnoreCase));
    }
}
