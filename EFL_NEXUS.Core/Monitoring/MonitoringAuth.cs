namespace EflNexus.Core.Monitoring;

public static class MonitoringAuth
{
    public const bool ReadyForDevicePilot = false;

    public static bool IsMonitoringAuthorized()
    {
        var pilot = Environment.GetEnvironmentVariable("EFL_PILOT_DEVICE_ACTIVE") ?? "";
        if (pilot is "1" || pilot.Equals("true", StringComparison.OrdinalIgnoreCase))
            return true;

        try
        {
            var cred = MonitoringSecurity.LoadMachineCredential();
            if (cred is not null && MonitoringSecurity.IsMachineActive())
                return true;
            return DeviceIdentity.AutoRegisterMachine();
        }
        catch
        {
            return false;
        }
    }
}
