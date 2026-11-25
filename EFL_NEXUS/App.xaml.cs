using System.IO;
using System.Windows;
using System.Windows.Media.Imaging;
using EflNexus.Core.Infrastructure;

namespace EflNexus.App;

public partial class App : System.Windows.Application
{
    public static void TrySetWindowIcon(Window window)
    {
        try
        {
            var iconPath = AppPaths.ResolveResourcePath("icon_2.ico");
            if (!File.Exists(iconPath))
                iconPath = AppPaths.ResolveResourcePath("icon.ico");
            if (File.Exists(iconPath))
            {
                window.Icon = BitmapFrame.Create(new Uri(iconPath, UriKind.Absolute));
            }
        }
        catch { }
    }
}
