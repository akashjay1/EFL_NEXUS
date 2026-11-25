using System.Text;

namespace EflNexus.Core.Infrastructure;

public static class EncodingInit
{
    private static int _registered;

    public static void EnsureRegistered()
    {
        if (Interlocked.Exchange(ref _registered, 1) == 0)
            Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
    }
}
