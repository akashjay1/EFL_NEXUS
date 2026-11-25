using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media.Imaging;
using EflNexus.Core.Infrastructure;
using MediaColor = System.Windows.Media.Color;
using MediaColorConverter = System.Windows.Media.ColorConverter;
using SolidBrush = System.Windows.Media.SolidColorBrush;
using UserControl = System.Windows.Controls.UserControl;

namespace EflNexus.App.Views;

public partial class DashboardView : UserControl
{
    private static readonly SolidBrush CardBorderDefault = new(MediaColor.FromRgb(0xE2, 0xE8, 0xF0));
    private static readonly SolidBrush BtnBgDefault = new(MediaColor.FromRgb(0x0D, 0x1B, 0x2A));
    private static readonly SolidBrush BtnFgDefault = new(System.Windows.Media.Colors.White);
    private static readonly SolidBrush BtnFgHover = new(MediaColor.FromRgb(0x0B, 0x14, 0x20));

    private static readonly SolidBrush OnlineBg = new(MediaColor.FromRgb(0xE2, 0xFD, 0xF2));
    private static readonly SolidBrush OnlineBorder = new(MediaColor.FromRgb(0x49, 0xCF, 0x9E));
    private static readonly SolidBrush OnlineFg = new(MediaColor.FromRgb(0x06, 0x5F, 0x46));

    private static readonly SolidBrush OfflineBg = new(MediaColor.FromRgb(0xFE, 0xF2, 0xF2));
    private static readonly SolidBrush OfflineBorder = new(MediaColor.FromRgb(0xEF, 0x44, 0x44));
    private static readonly SolidBrush OfflineFg = new(MediaColor.FromRgb(0x99, 0x1B, 0x1B));

    public Action<string>? OnNavigateRequested { get; set; }

    public DashboardView()
    {
        InitializeComponent();
        LoadAuroraBackdrop();
        SetOnlineStatus(true);
    }

    private void LoadAuroraBackdrop()
    {
        try
        {
            var path = AppPaths.ResolveResourcePath(Path.Combine("assets", "aurora_bg.png"));
            if (!File.Exists(path))
                path = AppPaths.ResolveResourcePath("aurora_bg.png");
            if (File.Exists(path))
            {
                var bmp = new BitmapImage();
                bmp.BeginInit();
                bmp.CacheOption = BitmapCacheOption.OnLoad;
                bmp.UriSource = new Uri(path, UriKind.Absolute);
                bmp.EndInit();
                bmp.Freeze();
                AuroraBgImage.Source = bmp;
            }
        }
        catch
        {
            // Keep warm parchment base fallback (#FAF8F2)
        }
    }

    public void SetOnlineStatus(bool isOnline)
    {
        DashStatusPill.Background = isOnline ? OnlineBg : OfflineBg;
        DashStatusPill.BorderBrush = isOnline ? OnlineBorder : OfflineBorder;
        DashStatusText.Foreground = isOnline ? OnlineFg : OfflineFg;
        DashStatusText.Text = isOnline ? "●  SYSTEM OPERATIONAL" : "●  SYSTEM OFFLINE";
    }

    private void Card_Click(object sender, MouseButtonEventArgs e)
    {
        if (sender is FrameworkElement { Tag: string tag })
        {
            var key = tag.Split('|')[0];
            OnNavigateRequested?.Invoke(key);
        }
    }

    private void Card_MouseEnter(object sender, System.Windows.Input.MouseEventArgs e)
    {
        if (sender is not Border card || card.Tag is not string tag)
            return;
        var parts = tag.Split('|');
        if (parts.Length < 2)
            return;

        var accent = new SolidBrush((MediaColor)MediaColorConverter.ConvertFromString(parts[1]));
        card.BorderBrush = accent;
        card.BorderThickness = new Thickness(2);

        var (btn, txt) = ResolveActionButton(parts[0]);
        if (btn is not null && txt is not null)
        {
            btn.Background = accent;
            txt.Foreground = BtnFgHover;
        }
    }

    private void Card_MouseLeave(object sender, System.Windows.Input.MouseEventArgs e)
    {
        if (sender is not Border card || card.Tag is not string tag)
            return;
        var parts = tag.Split('|');
        if (parts.Length < 1)
            return;

        card.BorderBrush = CardBorderDefault;
        card.BorderThickness = new Thickness(1);

        var (btn, txt) = ResolveActionButton(parts[0]);
        if (btn is not null && txt is not null)
        {
            btn.Background = BtnBgDefault;
            txt.Foreground = BtnFgDefault;
        }
    }

    private (Border? Btn, TextBlock? Txt) ResolveActionButton(string key) => key switch
    {
        "tool1" => (BtnTool1, BtnTextTool1),
        "tool2" => (BtnTool2, BtnTextTool2),
        "tool3" => (BtnTool3, BtnTextTool3),
        "tool4" => (BtnTool4, BtnTextTool4),
        "tool5" => (BtnTool5, BtnTextTool5),
        "tool6" => (BtnTool6, BtnTextTool6),
        "packinglist" => (BtnPackingList, BtnTextPackingList),
        _ => (null, null)
    };
}
