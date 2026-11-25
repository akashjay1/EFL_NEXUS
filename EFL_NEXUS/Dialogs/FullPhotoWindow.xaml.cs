using System.Windows;
using System.Windows.Media.Imaging;
using EflNexus.App.Helpers;

namespace EflNexus.App.Dialogs;

public partial class FullPhotoWindow : Window
{
    private readonly BitmapSource? _bitmap;
    private readonly double _fitScale = 1.0;

    public FullPhotoWindow(Window? owner, string? imagePath)
    {
        InitializeComponent();
        App.TrySetWindowIcon(this);
        if (owner is not null && owner.IsVisible)
            Owner = owner;
        else
            WindowStartupLocation = WindowStartupLocation.CenterScreen;

        _bitmap = ImageLoader.LoadOrientedBitmap(imagePath);
        if (_bitmap is null)
        {
            ControlsBar.Visibility = Visibility.Collapsed;
            PhotoScroller.Visibility = Visibility.Collapsed;
            UnavailableText.Visibility = Visibility.Visible;
            SizeToContent = SizeToContent.WidthAndHeight;
            return;
        }

        double width = Math.Min(1100, Math.Max(400, SystemParameters.PrimaryScreenWidth - 100));
        double height = Math.Min(850, Math.Max(300, SystemParameters.PrimaryScreenHeight - 120));
        Width = width;
        Height = height;

        DimensionsText.Text = $"Captured image: {_bitmap.PixelWidth} × {_bitmap.PixelHeight} pixels";
        PhotoImage.Source = _bitmap;

        _fitScale = Math.Min(
            1.0,
            Math.Min((width - 25.0) / _bitmap.PixelWidth, (height - 60.0) / _bitmap.PixelHeight));
        DrawScale(_fitScale);
    }

    private void DrawScale(double scale)
    {
        if (_bitmap is null)
            return;
        PhotoImage.Width = Math.Max(1.0, Math.Round(_bitmap.PixelWidth * scale));
        PhotoImage.Height = Math.Max(1.0, Math.Round(_bitmap.PixelHeight * scale));
    }

    private void Fit_Click(object sender, RoutedEventArgs e) => DrawScale(_fitScale);
    private void OneHundred_Click(object sender, RoutedEventArgs e) => DrawScale(1.0);
    private void TwoHundred_Click(object sender, RoutedEventArgs e) => DrawScale(2.0);
}
