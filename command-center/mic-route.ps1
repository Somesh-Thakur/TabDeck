# Routes a running process's audio output to "CABLE Input" (same as Settings > Volume mixer > app > Output device).
# Windows remembers the choice per app, so scrcpy keeps playing into the cable on later launches.
param([int]$ProcessId)
$ErrorActionPreference = 'Stop'

$render = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render'
$cable = Get-ChildItem $render | Where-Object {
    (Get-ItemProperty $_.PSPath).DeviceState -eq 1 -and
    (Get-ItemProperty "$($_.PSPath)\Properties").'{a45c254e-df1c-4efd-8020-67d146a850e0},2' -eq 'CABLE Input'
} | Select-Object -First 1
if (-not $cable) { Write-Output 'no-cable'; exit 2 }
$deviceId = "\\?\SWD#MMDEVAPI#{0.0.0.00000000}.$($cable.PSChildName)#{e6327cad-dcec-4949-ae8a-991e976a79d2}"

Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices;
[Guid("ab3d4648-e242-459f-b02f-541c70306324"), InterfaceType(ComInterfaceType.InterfaceIsIInspectable)]
interface IAudioPolicyConfigFactory {
  int a1(); int a2(); int a3(); int a4(); int a5(); int a6(); int a7(); int a8(); int a9(); int a10();
  int a11(); int a12(); int a13(); int a14(); int a15(); int a16(); int a17(); int a18(); int a19();
  [PreserveSig] int SetPersistedDefaultAudioEndpoint(uint pid, int flow, int role, IntPtr deviceId);
  [PreserveSig] int GetPersistedDefaultAudioEndpoint(uint pid, int flow, int role, [MarshalAs(UnmanagedType.HString)] out string deviceId);
}
public static class Route {
  [DllImport("combase.dll", PreserveSig=false)] static extern void RoGetActivationFactory(IntPtr cls, [MarshalAs(UnmanagedType.LPStruct)] Guid iid, [MarshalAs(UnmanagedType.IUnknown)] out object f);
  [DllImport("combase.dll", PreserveSig=false)] static extern void WindowsCreateString([MarshalAs(UnmanagedType.LPWStr)] string s, int len, out IntPtr h);
  [DllImport("combase.dll")] static extern int WindowsDeleteString(IntPtr h);
  static IAudioPolicyConfigFactory F() {
    IntPtr cls; const string n = "Windows.Media.Internal.AudioPolicyConfig";
    WindowsCreateString(n, n.Length, out cls); object f;
    RoGetActivationFactory(cls, typeof(IAudioPolicyConfigFactory).GUID, out f); WindowsDeleteString(cls);
    return (IAudioPolicyConfigFactory)f;
  }
  public static string Set(uint pid, string dev) {
    var f = F(); IntPtr h; WindowsCreateString(dev, dev.Length, out h);
    int r0 = f.SetPersistedDefaultAudioEndpoint(pid, 0, 0, h);   // eRender, eConsole
    int r1 = f.SetPersistedDefaultAudioEndpoint(pid, 0, 1, h);   // eRender, eMultimedia
    WindowsDeleteString(h);
    string cur; f.GetPersistedDefaultAudioEndpoint(pid, 0, 1, out cur);
    return string.Format("set={0:X}/{1:X} now={2}", r0, r1, cur);
  }
}
'@
Write-Output ([Route]::Set([uint32]$ProcessId, $deviceId))
