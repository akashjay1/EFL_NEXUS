using System.IO;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using EflNexus.Core.Infrastructure;

namespace EflNexus.App.Dialogs;

public partial class ReleaseNotesWindow : Window
{
    private readonly string _version;

    public ReleaseNotesWindow(string version, string notesContent, bool isJustUpdated = true)
    {
        InitializeComponent();
        _version = version;

        VersionBadgeText.Text = version.StartsWith("v", StringComparison.OrdinalIgnoreCase)
            ? version
            : $"v{version}";

        if (!isJustUpdated)
        {
            SubtitleText.Text = $"Release notes and highlights for {VersionBadgeText.Text}:";
        }

        TryLoadLogo();
        PopulateNotes(notesContent);

        KeyDown += ReleaseNotesWindow_KeyDown;
    }

    private void TryLoadLogo()
    {
        try
        {
            var iconPath = AppPaths.ResolveResourcePath("icon_2.ico");
            if (!File.Exists(iconPath))
                iconPath = AppPaths.ResolveResourcePath("icon.ico");
            if (File.Exists(iconPath))
            {
                var bmp = new BitmapImage();
                bmp.BeginInit();
                bmp.CacheOption = BitmapCacheOption.OnLoad;
                bmp.UriSource = new Uri(iconPath, UriKind.Absolute);
                bmp.EndInit();
                bmp.Freeze();

                HeaderLogo.Source = bmp;
                Icon = bmp;
            }
        }
        catch { }
    }

    private void PopulateNotes(string text)
    {
        NotesContentPanel.Children.Clear();

        if (string.IsNullOrWhiteSpace(text))
        {
            var emptyNotice = new TextBlock
            {
                Text = "No release notes were provided for this release.",
                Foreground = new SolidColorBrush(Color.FromRgb(148, 163, 184)),
                FontSize = 12,
                Margin = new Thickness(0, 10, 0, 10)
            };
            NotesContentPanel.Children.Add(emptyNotice);
            return;
        }

        var lines = text.Split(new[] { "\r\n", "\r", "\n" }, StringSplitOptions.None);
        foreach (var rawLine in lines)
        {
            var line = rawLine.Trim();

            if (string.IsNullOrEmpty(line))
            {
                NotesContentPanel.Children.Add(new FrameworkElement { Height = 8 });
                continue;
            }

            // Headings (#, ##, ###)
            if (line.StartsWith("### ", StringComparison.Ordinal))
            {
                var heading = new TextBlock
                {
                    Text = line[4..].Trim(),
                    FontSize = 13.5,
                    FontWeight = FontWeights.SemiBold,
                    Foreground = new SolidColorBrush(Color.FromRgb(56, 189, 248)), // Cyan
                    Margin = new Thickness(0, 10, 0, 4),
                    TextWrapping = TextWrapping.Wrap
                };
                NotesContentPanel.Children.Add(heading);
                continue;
            }

            if (line.StartsWith("## ", StringComparison.Ordinal))
            {
                var heading = new TextBlock
                {
                    Text = line[3..].Trim(),
                    FontSize = 14.5,
                    FontWeight = FontWeights.Bold,
                    Foreground = new SolidColorBrush(Color.FromRgb(248, 250, 252)),
                    Margin = new Thickness(0, 14, 0, 4),
                    TextWrapping = TextWrapping.Wrap
                };
                NotesContentPanel.Children.Add(heading);
                continue;
            }

            if (line.StartsWith("# ", StringComparison.Ordinal))
            {
                var heading = new TextBlock
                {
                    Text = line[2..].Trim(),
                    FontSize = 15.5,
                    FontWeight = FontWeights.Bold,
                    Foreground = new SolidColorBrush(Color.FromRgb(255, 255, 255)),
                    Margin = new Thickness(0, 4, 0, 6),
                    TextWrapping = TextWrapping.Wrap
                };
                NotesContentPanel.Children.Add(heading);
                continue;
            }

            // Bullet points (•, -, *)
            bool isBullet = line.StartsWith("•", StringComparison.Ordinal)
                         || line.StartsWith("-", StringComparison.Ordinal)
                         || line.StartsWith("*", StringComparison.Ordinal);

            if (isBullet)
            {
                var content = line.TrimStart('•', '-', '*', ' ');
                var bulletGrid = new Grid { Margin = new Thickness(6, 2, 0, 3) };
                bulletGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(16) });
                bulletGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

                var dot = new TextBlock
                {
                    Text = "•",
                    Foreground = new SolidColorBrush(Color.FromRgb(0, 229, 255)), // Accent Cyan
                    FontSize = 14,
                    FontWeight = FontWeights.Bold,
                    VerticalAlignment = VerticalAlignment.Top,
                    Margin = new Thickness(0, -1, 0, 0)
                };
                Grid.SetColumn(dot, 0);
                bulletGrid.Children.Add(dot);

                var bodyBlock = CreateFormattedTextBlock(content, Color.FromRgb(226, 232, 240));
                Grid.SetColumn(bodyBlock, 1);
                bulletGrid.Children.Add(bodyBlock);

                NotesContentPanel.Children.Add(bulletGrid);
                continue;
            }

            // Regular paragraph
            var regularBlock = CreateFormattedTextBlock(line, Color.FromRgb(203, 213, 225));
            regularBlock.Margin = new Thickness(0, 2, 0, 4);
            NotesContentPanel.Children.Add(regularBlock);
        }
    }

    private static TextBlock CreateFormattedTextBlock(string markdownText, Color defaultColor)
    {
        var textBlock = new TextBlock
        {
            FontSize = 12,
            Foreground = new SolidColorBrush(defaultColor),
            TextWrapping = TextWrapping.Wrap,
            LineHeight = 18
        };

        // Parse **bold** markdown segments
        var parts = Regex.Split(markdownText, @"(\*\*.*?\*\*)");
        foreach (var part in parts)
        {
            if (part.StartsWith("**", StringComparison.Ordinal) && part.EndsWith("**", StringComparison.Ordinal) && part.Length >= 4)
            {
                var boldRun = new Run(part[2..^2])
                {
                    FontWeight = FontWeights.Bold,
                    Foreground = new SolidColorBrush(Color.FromRgb(255, 255, 255))
                };
                textBlock.Inlines.Add(boldRun);
            }
            else if (!string.IsNullOrEmpty(part))
            {
                textBlock.Inlines.Add(new Run(part));
            }
        }

        return textBlock;
    }

    private void ReleaseNotesWindow_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Escape || e.Key == Key.Enter)
        {
            Close();
        }
    }

    private void GotItButton_Click(object sender, RoutedEventArgs e)
    {
        Close();
    }

    protected override void OnClosed(EventArgs e)
    {
        base.OnClosed(e);
        bool showOnUpdate = ShowOnUpdateCheckBox.IsChecked ?? true;
        ReleaseNotesManager.MarkVersionSeen(_version, showOnUpdate);
    }
}
