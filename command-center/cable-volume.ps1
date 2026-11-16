# Reads (and with -Set, sets to 100% / unmuted) the VB-CABLE playback and mic levels.
param([switch]$Set)
Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices;
[ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator { int a(); int b(); [PreserveSig] int GetDevice([MarshalAs(UnmanagedType.LPWStr)] string id, out IMMDevice d); }
[ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice { [PreserveSig] int Activate([MarshalAs(UnmanagedType.LPStruct)] Guid iid, int ctx, IntPtr p, [MarshalAs(UnmanagedType.IUnknown)] out object o); }
[ComImport, Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {
  int RegisterNotify(IntPtr p); int UnregisterNotify(IntPtr p); int GetChannelCount(out uint c);
  int SetMasterVolumeLevel(float db, IntPtr g); int SetMasterVolumeLevelScalar(float v, IntPtr g);
  int GetMasterVolumeLevel(out float db); int GetMasterVolumeLevelScalar(out float v);
  int SetChannelVolumeLevel(uint ch, float db, IntPtr g); int SetChannelVolumeLevelScalar(uint ch, float v, IntPtr g);
  int GetChannelVolumeLevel(uint ch, out float db); int GetChannelVolumeLevelScalar(uint ch, out float v);
  int SetMute([MarshalAs(UnmanagedType.Bool)] bool m, IntPtr g); int GetMute([MarshalAs(UnmanagedType.Bool)] out bool m);
}
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDE {}
public static class Vol {
  public static string Do(string id, bool set) {
    var e = (IMMDeviceEnumerator)new MMDE(); IMMDevice d; e.GetDevice(id, out d); object o;
    d.Activate(typeof(IAudioEndpointVolume).GUID, 23, IntPtr.Zero, out o); var v = (IAudioEndpointVolume)o;
    float s, db; bool m; v.GetMasterVolumeLevelScalar(out s); v.GetMasterVolumeLevel(out db); v.GetMute(out m);
    string before = string.Format("{0:N0}% ({1:N1} dB) muted={2}", s * 100, db, m);
    if (!set) return before;
    v.SetMasterVolumeLevelScalar(1f, IntPtr.Zero); v.SetMute(false, IntPtr.Zero);
    v.GetMasterVolumeLevelScalar(out s); v.GetMasterVolumeLevel(out db);
    return before + "  ->  " + string.Format("{0:N0}% ({1:N1} dB)", s * 100, db);
  }
}
'@
function Find($kind, $name) {
  $k = Get-ChildItem "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\$kind" | Where-Object {
    (Get-ItemProperty $_.PSPath).DeviceState -eq 1 -and
    (Get-ItemProperty "$($_.PSPath)\Properties").'{a45c254e-df1c-4efd-8020-67d146a850e0},2' -eq $name } | Select-Object -First 1
  $flow = if ($kind -eq 'Render') { '0' } else { '1' }
  "{0.0.$flow.00000000}.$($k.PSChildName)"
}
"CABLE Input  (into cable): " + [Vol]::Do((Find 'Render' 'CABLE Input'), $Set)
"CABLE Output (the mic)   : " + [Vol]::Do((Find 'Capture' 'CABLE Output'), $Set)
