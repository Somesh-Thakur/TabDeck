# Removes bloat from the tablet for the current user only (reversible). Writes restore.ps1 to undo.
$adb = Join-Path $PSScriptRoot '..\tools\platform-tools\adb.exe'
$remove = @(
  # Google apps not needed on a dedicated dashboard
  'com.google.android.apps.kids.home', 'com.google.android.apps.googleassistant', 'com.google.android.youtube',
  'com.google.android.apps.youtube.music', 'com.google.android.apps.youtube.music.setupwizard',
  'com.google.android.apps.youtube.kids', 'com.google.android.apps.books', 'com.google.android.videos',
  'com.google.android.gm', 'com.google.android.apps.maps', 'com.google.android.apps.photos',
  'com.google.android.apps.docs', 'com.google.android.apps.docs.editors.docs', 'com.google.android.apps.docs.editors.sheets',
  'com.google.android.apps.docs.editors.slides', 'com.google.android.calendar', 'com.google.android.apps.messaging',
  'com.google.android.apps.tachyon', 'com.google.android.apps.subscriptions.red', 'com.google.android.apps.fitness',
  'com.google.android.apps.magazines', 'com.google.android.apps.chromecast.app', 'com.google.android.apps.nbu.files',
  'com.google.android.googlequicksearchbox', 'com.google.android.projection.gearhead', 'com.google.android.marvin.talkback',
  'com.google.android.apps.wellbeing', 'com.google.android.apps.mediahome.launcher', 'com.google.android.gms.location.history',
  'com.google.android.printservice.recommendation', 'com.google.android.feedback',
  # Lenovo extras / analytics
  'com.tblenovo.center', 'com.lenovo.ue.device', 'com.lenovo.dsa', 'com.tblenovo.landscapevision.lenovolandscapevision',
  'com.lenovo.screenassistant'
)
$installed = (& $adb shell pm list packages) -replace 'package:', ''
$done = @()
foreach ($p in $remove) {
  if ($installed -notcontains $p) { continue }
  $r = & $adb shell pm uninstall -k --user 0 $p
  if ($r -match 'Success') { $done += $p; "removed  $p" } else { "skipped  $p ($r)" }
}
$restore = "# Restores the apps removed by debloat.ps1`n`$adb = Join-Path `$PSScriptRoot '..\tools\platform-tools\adb.exe'`n" +
           (($done | ForEach-Object { "& `$adb shell cmd package install-existing $_" }) -join "`n")
Add-Content -Path (Join-Path $PSScriptRoot 'restore.ps1') -Value $restore -Encoding utf8
"{0} apps removed. Undo any time with tablet-app\restore.ps1" -f $done.Count
