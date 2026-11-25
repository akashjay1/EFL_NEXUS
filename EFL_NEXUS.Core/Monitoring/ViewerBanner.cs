using System.Drawing;
using System.Windows.Forms;

namespace EflNexus.Core.Monitoring;

/// <summary>
/// Always-on-top notice shown on the operator's screen while an administrator is viewing it.
/// Runs on its own STA thread so it works regardless of which thread starts the stream.
/// </summary>
public static class ViewerBanner
{
    private static readonly object Gate = new();
    private static Form? _form;
    private static Thread? _thread;

    public static void Show(string admin, string reason)
    {
        Hide();
        var text = string.IsNullOrWhiteSpace(reason)
            ? $"Your screen is being viewed by {admin}"
            : $"Your screen is being viewed by {admin}  ·  Reason: {reason}";

        var ready = new ManualResetEventSlim(false);
        var thread = new Thread(() =>
        {
            Form form;
            try
            {
                form = BuildForm(text);
            }
            catch
            {
                ready.Set();
                return;
            }
            lock (Gate)
            {
                // Hidden (or replaced) before the window existed: don't show it.
                if (!ReferenceEquals(_thread, Thread.CurrentThread))
                {
                    form.Dispose();
                    ready.Set();
                    return;
                }
                _form = form;
            }
            form.Shown += (_, _) => ready.Set();
            try { Application.Run(form); } catch { }
            lock (Gate) { if (ReferenceEquals(_form, form)) _form = null; }
            ready.Set();
        })
        {
            IsBackground = true,
            Name = "screen-view-banner"
        };
        thread.SetApartmentState(ApartmentState.STA);
        lock (Gate) { _thread = thread; }
        thread.Start();
        ready.Wait(2000);
    }

    public static void Hide()
    {
        Form? form;
        lock (Gate)
        {
            form = _form;
            _form = null;
            _thread = null;
        }
        if (form is null) return;
        try
        {
            if (form.IsHandleCreated)
                form.BeginInvoke(new Action(form.Close));
        }
        catch { }
    }

    private static Form BuildForm(string text)
    {
        var screen = Screen.PrimaryScreen?.WorkingArea ?? new Rectangle(0, 0, 1280, 720);
        var label = new Label
        {
            AutoSize = false,
            Dock = DockStyle.Fill,
            TextAlign = ContentAlignment.MiddleCenter,
            ForeColor = Color.White,
            Font = new Font("Segoe UI", 10.5f, FontStyle.Bold),
            Text = "●  " + text
        };
        var width = Math.Min(760, screen.Width - 40);
        var form = new Form
        {
            FormBorderStyle = FormBorderStyle.None,
            ShowInTaskbar = false,
            TopMost = true,
            StartPosition = FormStartPosition.Manual,
            BackColor = Color.FromArgb(180, 35, 24),
            Size = new Size(width, 38),
            Location = new Point(screen.Left + (screen.Width - width) / 2, screen.Top + 8),
            Text = "EFL NEXUS screen view"
        };
        form.Controls.Add(label);
        return form;
    }
}
