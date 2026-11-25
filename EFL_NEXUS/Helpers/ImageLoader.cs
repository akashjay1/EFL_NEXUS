using System.IO;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using OpenCvSharp;

namespace EflNexus.App.Helpers;

public static class ImageLoader
{
    public static BitmapSource? LoadOrientedBitmap(string? path)
    {
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
            return null;

        try
        {
            var bytes = File.ReadAllBytes(path);
            using var mat = Cv2.ImDecode(bytes, ImreadModes.Color);
            if (mat.Empty() || mat.Width <= 0 || mat.Height <= 0)
                return null;

            int stride = (int)mat.Step();
            int bufferSize = stride * mat.Height;
            var bmp = BitmapSource.Create(
                mat.Width,
                mat.Height,
                96,
                96,
                PixelFormats.Bgr24,
                null,
                mat.Data,
                bufferSize,
                stride);
            bmp.Freeze();
            return bmp;
        }
        catch
        {
            return null;
        }
    }

    public static void SizeAndCenterDialog(System.Windows.Window dialog, System.Windows.Window? owner, double widthRatio, double heightRatio, double minWidth, double minHeight, double maxWidth = double.PositiveInfinity, double maxHeight = double.PositiveInfinity)
    {
        if (owner is not null && owner.IsVisible)
        {
            dialog.Owner = owner;
            double pw = owner.ActualWidth > 0 ? owner.ActualWidth : 1200;
            double ph = owner.ActualHeight > 0 ? owner.ActualHeight : 850;
            double w = Math.Max(minWidth, Math.Min(maxWidth, pw * widthRatio));
            double h = Math.Max(minHeight, Math.Min(maxHeight, ph * heightRatio));
            dialog.Width = w;
            dialog.Height = h;
            dialog.WindowStartupLocation = WindowStartupLocation.CenterOwner;
        }
        else
        {
            double sw = SystemParameters.WorkArea.Width;
            double sh = SystemParameters.WorkArea.Height;
            double w = Math.Max(minWidth, Math.Min(maxWidth, sw * widthRatio));
            double h = Math.Max(minHeight, Math.Min(maxHeight, sh * heightRatio));
            dialog.Width = w;
            dialog.Height = h;
            dialog.WindowStartupLocation = WindowStartupLocation.CenterScreen;
        }
    }
}
