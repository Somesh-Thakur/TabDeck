# Puts a signature PNG on the clipboard twice: as "PNG" (keeps transparency: Word, PowerPoint, Google Docs, Paint.NET)
# and as a normal bitmap on white (everything else), so it never pastes with a black background.
param([string]$Path)
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$bytes = [IO.File]::ReadAllBytes($Path)
$img = [Drawing.Image]::FromStream((New-Object IO.MemoryStream (, $bytes)))
$bmp = New-Object Drawing.Bitmap $img.Width, $img.Height
$g = [Drawing.Graphics]::FromImage($bmp); $g.Clear([Drawing.Color]::White); $g.DrawImage($img, 0, 0, $img.Width, $img.Height); $g.Dispose()
$data = New-Object Windows.Forms.DataObject
$data.SetData('PNG', (New-Object IO.MemoryStream (, $bytes)))
$data.SetImage($bmp)
[Windows.Forms.Clipboard]::SetDataObject($data, $true)
