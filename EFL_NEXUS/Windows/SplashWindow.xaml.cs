using System.Windows;
using System.Windows.Threading;

namespace EflNexus.App.Windows;

public partial class SplashWindow : Window
{
    public SplashWindow()
    {
        InitializeComponent();
        App.TrySetWindowIcon(this);
    }

    public void SetStatus(string message, double progress)
    {
        StatusText.Text = message;
        Progress.Value = Math.Clamp(progress, 0, 100);
        PumpEvents();
    }

    public void Finish()
    {
        SetStatus("Ready", 100);
        Close();
    }

    public static void PumpEvents()
    {
        var frame = new DispatcherFrame();
        Dispatcher.CurrentDispatcher.BeginInvoke(
            DispatcherPriority.Background,
            new DispatcherOperationCallback(_ =>
            {
                frame.Continue = false;
                return null;
            }),
            null);
        try
        {
            Dispatcher.PushFrame(frame);
        }
        catch { }
    }
}
