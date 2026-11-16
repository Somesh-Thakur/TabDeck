# Extracts high-res (256px) app icons for Start menu AppIDs.
# Usage: icons.ps1 -Out <dir> -Ids <appid1>|<appid2>...   (writes <sha1(appid)>.png)
param([string]$Out, [string]$Ids)
Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @'
using System; using System.Runtime.InteropServices; using System.Drawing; using System.Drawing.Imaging;
public static class Ico {
  [ComImport, Guid("bcc18b79-ba16-442f-80c4-8a59c30c463b"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IShellItemImageFactory { void GetImage(SIZE size, int flags, out IntPtr phbm); }
  [StructLayout(LayoutKind.Sequential)] struct SIZE { public int cx, cy; }
  [DllImport("shell32.dll", CharSet=CharSet.Unicode, PreserveSig=false)]
  static extern void SHCreateItemFromParsingName(string p, IntPtr b, [MarshalAs(UnmanagedType.LPStruct)] Guid r, out IShellItemImageFactory f);
  [DllImport("gdi32.dll")] static extern bool DeleteObject(IntPtr h);
  public static void Save(string path, string png, int px) {
    IShellItemImageFactory f; IntPtr hbm;
    SHCreateItemFromParsingName(path, IntPtr.Zero, typeof(IShellItemImageFactory).GUID, out f);
    var sz = new SIZE(); sz.cx = px; sz.cy = px;
    f.GetImage(sz, 0x1 | 0x4, out hbm);  // BIGGERSIZEOK | ICONONLY
    try {
      using (var tmp = Image.FromHbitmap(hbm)) {
        var rc = new Rectangle(0, 0, tmp.Width, tmp.Height);
        var d = tmp.LockBits(rc, ImageLockMode.ReadOnly, tmp.PixelFormat);
        using (var argb = new Bitmap(d.Width, d.Height, d.Stride, PixelFormat.Format32bppPArgb, d.Scan0))
          argb.Save(png, ImageFormat.Png);
        tmp.UnlockBits(d);
      }
    } finally { DeleteObject(hbm); }
  }
}
'@
$sha = [System.Security.Cryptography.SHA1]::Create()
foreach ($id in $Ids -split '\|') {
  if (-not $id) { continue }
  $h = -join ($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($id)) | ForEach-Object { $_.ToString('x2') })
  try { [Ico]::Save("shell:AppsFolder\$id", (Join-Path $Out "$h.png"), 256) } catch { Write-Output "fail $id" }
}
