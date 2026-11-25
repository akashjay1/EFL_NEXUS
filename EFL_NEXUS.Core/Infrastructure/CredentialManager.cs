using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;

namespace EflNexus.Core.Infrastructure;

/// <summary>
/// Windows Credential Manager P/Invoke wrapper compatible with pywin32 win32cred.
/// Stores UTF-16-LE strings inside CRED_TYPE_GENERIC (1) with CRED_PERSIST_LOCAL_MACHINE (3).
/// </summary>
public static class CredentialManager
{
    public const uint CredTypeGeneric = 1;
    public const uint CredPersistLocalMachine = 3;
    private const int ErrorNotFound = 1168;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct CREDENTIAL
    {
        public uint Flags;
        public uint Type;
        public string TargetName;
        public string? Comment;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
        public uint CredentialBlobSize;
        public IntPtr CredentialBlob;
        public uint Persist;
        public uint AttributeCount;
        public IntPtr Attributes;
        public string? TargetAlias;
        public string? UserName;
    }

    [DllImport("advapi32.dll", EntryPoint = "CredReadW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredRead(string target, uint type, int reservedFlag, out IntPtr credentialPtr);

    [DllImport("advapi32.dll", EntryPoint = "CredWriteW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredWrite(ref CREDENTIAL userCredential, uint flags);

    [DllImport("advapi32.dll", EntryPoint = "CredDeleteW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredDelete(string target, uint type, uint flags);

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern void CredFree(IntPtr cred);

    public sealed record CredentialRecord(string TargetName, string UserName, string Secret);

    public static CredentialRecord? Read(string targetName)
    {
        if (!CredRead(targetName, CredTypeGeneric, 0, out var credPtr))
        {
            var err = Marshal.GetLastWin32Error();
            if (err == ErrorNotFound)
                return null;
            throw new Win32Exception(err, $"Windows Credential Manager could not read '{targetName}'.");
        }

        try
        {
            var cred = Marshal.PtrToStructure<CREDENTIAL>(credPtr);
            string secret = string.Empty;
            if (cred.CredentialBlob != IntPtr.Zero && cred.CredentialBlobSize > 0)
            {
                var bytes = new byte[cred.CredentialBlobSize];
                Marshal.Copy(cred.CredentialBlob, bytes, 0, bytes.Length);
                secret = DecodeCredentialBytes(bytes);
            }
            return new CredentialRecord(cred.TargetName ?? targetName, cred.UserName ?? string.Empty, secret);
        }
        finally
        {
            CredFree(credPtr);
        }
    }

    public static void Write(string targetName, string userName, string secret, uint persist = CredPersistLocalMachine)
    {
        var bytes = Encoding.Unicode.GetBytes(secret ?? string.Empty);
        var blobPtr = bytes.Length > 0 ? Marshal.AllocCoTaskMem(bytes.Length) : IntPtr.Zero;
        try
        {
            if (blobPtr != IntPtr.Zero)
                Marshal.Copy(bytes, 0, blobPtr, bytes.Length);

            var cred = new CREDENTIAL
            {
                Flags = 0,
                Type = CredTypeGeneric,
                TargetName = targetName,
                Comment = null,
                CredentialBlobSize = (uint)bytes.Length,
                CredentialBlob = blobPtr,
                Persist = persist,
                AttributeCount = 0,
                Attributes = IntPtr.Zero,
                TargetAlias = null,
                UserName = userName ?? string.Empty
            };

            if (!CredWrite(ref cred, 0))
            {
                var err = Marshal.GetLastWin32Error();
                throw new Win32Exception(err, $"Windows Credential Manager could not write '{targetName}'.");
            }
        }
        finally
        {
            if (blobPtr != IntPtr.Zero)
                Marshal.FreeCoTaskMem(blobPtr);
        }
    }

    public static bool Delete(string targetName)
    {
        if (CredDelete(targetName, CredTypeGeneric, 0))
            return true;
        var err = Marshal.GetLastWin32Error();
        if (err == ErrorNotFound)
            return false;
        throw new Win32Exception(err, $"Windows Credential Manager could not delete '{targetName}'.");
    }

    private static string DecodeCredentialBytes(byte[] bytes)
    {
        // pywin32 encodes Unicode strings as UTF-16-LE; older UTF-8 blobs may also exist.
        if (bytes.Length >= 2 && bytes.Length % 2 == 0)
        {
            var utf16 = Encoding.Unicode.GetString(bytes).TrimEnd('\0');
            if (!utf16.Contains('\uFFFD'))
                return utf16;
        }
        return Encoding.UTF8.GetString(bytes).TrimEnd('\0');
    }
}
