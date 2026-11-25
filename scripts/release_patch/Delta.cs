using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;

public static class RedemptionDelta
{
    [StructLayout(LayoutKind.Sequential)]
    private struct Input
    {
        public IntPtr Pointer;
        public UIntPtr Size;
        public int Editable;
    }

    [DllImport("msdelta.dll", ExactSpelling = true, SetLastError = true, CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool ApplyDeltaW(long flags, string source, string delta, string target);

    [DllImport("msdelta.dll", ExactSpelling = true, SetLastError = true, CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateDeltaW(long fileType, long set, long reset, string source,
        string target, string sourceOptions, string targetOptions, Input globalOptions,
        IntPtr timestamp, uint hash, string delta);

    private static bool ApplyZipMembers(string source, string patch, string target)
    {
        using (var delta = new BinaryReader(File.OpenRead(patch)))
        {
            if (delta.BaseStream.Length < 8 || delta.ReadUInt32() != 0x31505a52) return false;
            var count = delta.ReadUInt32();
            var buffer = new byte[65536];
            using (var original = File.OpenRead(source))
            using (var output = new FileStream(target, FileMode.CreateNew))
            {
                for (uint i = 0; i < count; ++i)
                {
                    long offset = delta.ReadInt64();
                    int size = delta.ReadInt32();
                    Stream input = offset == -1 ? delta.BaseStream : original;
                    if (size < 0 || offset < -1 ||
                        (offset >= 0 && (offset > original.Length || size > original.Length - offset)))
                        throw new InvalidDataException("Invalid Nod archive delta span");
                    if (offset >= 0) original.Position = offset;
                    while (size > 0)
                    {
                        int read = input.Read(buffer, 0, Math.Min(buffer.Length, size));
                        if (read == 0) throw new EndOfStreamException("Incomplete Nod archive delta");
                        output.Write(buffer, 0, read);
                        size -= read;
                    }
                }
                if (delta.BaseStream.Position != delta.BaseStream.Length)
                    throw new InvalidDataException("Trailing Nod archive delta bytes");
            }
        }
        return true;
    }

    public static void Run(string source, string second, string destination, bool create)
    {
        source = Path.GetFullPath(source);
        second = Path.GetFullPath(second);
        destination = Path.GetFullPath(destination);
        if (File.Exists(destination)) throw new IOException("Delta output already exists: " + destination);
        if (!create && ApplyZipMembers(source, second, destination)) return;
        const long rawFile = 1;
        const long ignoreSizeLimit = 0x20000;
        bool success = create
            ? CreateDeltaW(rawFile, ignoreSizeLimit, 0, source, second, null, null,
                new Input(), IntPtr.Zero, 32, destination)
            : ApplyDeltaW(0, source, second, destination);
        if (!success) throw new Win32Exception(Marshal.GetLastWin32Error());
    }
}
