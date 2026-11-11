# Booth film: the staff remote's "▶ 영상 재생" plays the product film full
# screen on this PC's game monitor, with sound; "■ 영상 정지", the end of the
# film, a click or Esc goes back to the game.
#
# Runs in the background (Booth guard starts it; or run it by hand). It asks
# Supabase once a second for the remote's film commands (take_film_commands;
# the Pi leaves those for this PC).
#
# First start: it fetches what it needs from the Pi over `ssh inpi` (the same
# Tailscale SSH that already works on this PC) and keeps it in
# %APPDATA%\BamnunFilm: config.txt (Supabase address, public key, staff code)
# and film.mp4 (the film with sound, from ~/bamnun/assets/booth/film_pc.mp4).
# Nothing secret is in git. To fetch again (a new film): booth_film.ps1 -Setup
#
#   booth_film.ps1           start (does nothing if it's already running)
#   booth_film.ps1 -Setup    fetch the settings and the film again, then start
#   booth_film.ps1 -Test     play the film once now (no remote needed)

param(
    [switch]$Setup,
    [switch]$Test
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase, System.Windows.Forms

$mutex = New-Object System.Threading.Mutex($false, 'Local\BamnunBoothFilm')
if (-not $mutex.WaitOne(0)) { exit }   # already running

$dir = Join-Path $env:APPDATA 'BamnunFilm'
$cfgFile = Join-Path $dir 'config.txt'
$film = Join-Path $dir 'film.mp4'
$logFile = Join-Path $dir 'film.log'
New-Item -ItemType Directory -Force -Path $dir | Out-Null

function Log($msg) {
    try { Add-Content -Path $logFile -Value ((Get-Date -Format 'MM-dd HH:mm:ss') + '  ' + $msg) -Encoding UTF8 } catch {}
}

function Say($msg) {
    [System.Windows.MessageBox]::Show($msg, 'Bamnun film') | Out-Null
}

# --- first start: settings and film from the Pi --------------------------------
# (Continue: in Windows PowerShell a line ssh prints on stderr would otherwise stop the script.)
$ErrorActionPreference = 'Continue'
if ($Setup -or -not (Test-Path $cfgFile)) {
    Log 'fetching settings from the Pi'
    $lines = & ssh -o BatchMode=yes -o ConnectTimeout=15 inpi "grep -E '^(SUPABASE_URL|SUPABASE_ANON_KEY|STAFF_CODE)=' ~/bamnun/frontend/.env" 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $lines) {
        Log 'ssh inpi failed'
        Say "Couldn't reach the Pi (ssh inpi). Turn the Pi on and check Tailscale, then start this again."
        exit 1
    }
    Set-Content -Path $cfgFile -Value $lines -Encoding UTF8
}
if ($Setup -or -not (Test-Path $film)) {
    Log 'fetching the film from the Pi'
    & scp -o BatchMode=yes -o ConnectTimeout=15 'inpi:bamnun/assets/booth/film_pc.mp4' "$film" 2>$null
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $film)) {
        Log 'scp failed; asking for the file'
        $dlg = New-Object System.Windows.Forms.OpenFileDialog
        $dlg.Title = 'Choose the Bamnun film (mp4, with sound)'
        $dlg.Filter = 'Video (*.mp4)|*.mp4'
        if ($dlg.ShowDialog() -ne 'OK') { exit 1 }
        Copy-Item $dlg.FileName $film -Force
    }
}

$ErrorActionPreference = 'Stop'
$cfg = @{}
foreach ($line in Get-Content $cfgFile -Encoding UTF8) {
    $i = $line.IndexOf('=')
    if ($i -gt 0) { $cfg[$line.Substring(0, $i).Trim()] = $line.Substring($i + 1).Trim().Trim('"').Trim("'") }
}
$url = ($cfg['SUPABASE_URL'] + '').TrimEnd('/')
$key = $cfg['SUPABASE_ANON_KEY'] + ''
$code = $cfg['STAFF_CODE'] + ''
if (-not $url -or -not $key -or -not $code) {
    Say "The settings from the Pi are incomplete. Run: booth_film.ps1 -Setup"
    exit 1
}

# --- the poller: its own thread, so the film never stutters on the network -----
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$sync = [hashtable]::Synchronized(@{ Cmds = [System.Collections.ArrayList]::Synchronized((New-Object System.Collections.ArrayList)); Stop = $false; Err = '' })
$poller = [powershell]::Create()
[void]$poller.AddScript({
    param($sync, $url, $key, $code)
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $headers = @{ apikey = $key; Authorization = "Bearer $key" }
    $body = '{"k":"' + $code + '"}'
    while (-not $sync.Stop) {
        try {
            $rows = Invoke-RestMethod -Method Post -Uri "$url/rest/v1/rpc/take_film_commands" -Headers $headers -ContentType 'application/json' -Body $body -TimeoutSec 5
            foreach ($r in @($rows | Sort-Object id)) { if ($r.cmd) { [void]$sync.Cmds.Add([string]$r.cmd) } }
            $sync.Err = ''
        } catch { $sync.Err = $_.Exception.Message }
        Start-Sleep -Milliseconds 1000
    }
}).AddArgument($sync).AddArgument($url).AddArgument($key).AddArgument($code)
$pollHandle = $poller.BeginInvoke()

# --- bring a window to the front (Windows only lets the active program do it;
# a tap of Alt lifts that rule, as in the guard) ---------------------------------
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class FilmNative {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
    public static void Force(IntPtr h) {
        if (h == IntPtr.Zero) return;
        if (IsIconic(h)) ShowWindow(h, 9);
        keybd_event(0x12, 0, 0, UIntPtr.Zero);
        SetForegroundWindow(h);
        keybd_event(0x12, 0, 2, UIntPtr.Zero);
    }
}
"@

# --- the film window: borderless, black, on top, on the main (game) monitor ------
$win = New-Object System.Windows.Window
$win.Title = 'Bamnun film'          # Booth guard allows this window by its title
$win.WindowStyle = 'None'
$win.ResizeMode = 'NoResize'
$win.Background = [System.Windows.Media.Brushes]::Black
$win.Topmost = $true
$win.ShowInTaskbar = $false
$win.ShowActivated = $true
$win.WindowStartupLocation = 'Manual'
$win.Cursor = [System.Windows.Input.Cursors]::None

$media = New-Object System.Windows.Controls.MediaElement
$media.LoadedBehavior = 'Manual'
$media.UnloadedBehavior = 'Stop'
$media.Stretch = 'Uniform'
$media.Volume = 1.0
$win.Content = $media

$script:playing = $false

function Back-ToGame {
    $media.Stop()
    $media.Close()
    $win.Hide()
    $script:playing = $false
    $g = Get-Process -Name eurotrucks2 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($g) { [FilmNative]::Force($g.MainWindowHandle) }
    Log 'back to the game'
}

function Play-Film {
    $media.Stop()
    $media.Source = New-Object System.Uri($film)
    $screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $win.WindowState = 'Normal'
    $win.Left = $screen.X
    $win.Top = $screen.Y
    $win.Show()
    $win.WindowState = 'Maximized'
    $win.Topmost = $true
    $win.Activate() | Out-Null
    [FilmNative]::Force((New-Object System.Windows.Interop.WindowInteropHelper($win)).Handle)
    $media.Position = [TimeSpan]::Zero
    $media.Play()
    $script:playing = $true
    Log 'playing'
}

$media.Add_MediaEnded({ Back-ToGame })
$media.Add_MediaFailed({ param($s, $e) Log ('film failed: ' + $e.ErrorException.Message); Back-ToGame })
$win.Add_MouseLeftButtonUp({ Back-ToGame })
$win.Add_KeyDown({ param($s, $e) if ($e.Key -eq 'Escape') { Back-ToGame } })
$win.Add_Closing({ param($s, $e) $e.Cancel = $true; Back-ToGame })   # Alt+F4 only hides it

# --- the loop: act on the remote's commands --------------------------------------
$lastErr = ''
$timer = New-Object System.Windows.Threading.DispatcherTimer
$timer.Interval = [TimeSpan]::FromMilliseconds(200)
$timer.Add_Tick({
    while ($sync.Cmds.Count -gt 0) {
        $c = $sync.Cmds[0]; $sync.Cmds.RemoveAt(0)
        Log ('remote: ' + $c)
        if ($c -eq 'video') { Play-Film }
        elseif ($c -eq 'video_stop' -and $script:playing) { Back-ToGame }
    }
    if ($sync.Err -ne $script:lastErr) { $script:lastErr = $sync.Err; if ($sync.Err) { Log ('remote offline: ' + $sync.Err) } }
})
$timer.Start()

Log ('started; film ' + $film)
if ($Test) { Play-Film }

try { [System.Windows.Threading.Dispatcher]::Run() } finally {
    $sync.Stop = $true
    $poller.EndInvoke($pollHandle) | Out-Null
}
