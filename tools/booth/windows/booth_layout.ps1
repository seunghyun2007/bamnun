# Booth layout: Euro Truck Simulator 2 on the left 2/3, RealVNC on the right 1/3.
#
# Why: Windows Snap can't place ETS2 when its window is as big as the screen
# (the title bar sits off the top, nothing to grab). This script places both
# windows directly, in real screen pixels, whatever the display scaling.
#
# Use: open the game and the RealVNC window to the Pi first, then double-click
# the "Booth layout" shortcut (or: powershell -ExecutionPolicy Bypass -File booth_layout.ps1).
# Run it again any time a window gets moved. It changes nothing permanent.

param(
    [double]$GameShare = 2.0 / 3.0   # part of the screen width for the game
)

Add-Type @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public static class BoothWin {
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
    delegate bool EnumProc(IntPtr h, IntPtr p);

    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc f, IntPtr p);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] static extern IntPtr GetWindow(IntPtr h, uint cmd);
    [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr v);
    [DllImport("user32.dll")] public static extern bool SystemParametersInfo(int a, int b, ref RECT r, int c);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint f);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("dwmapi.dll")] public static extern int DwmGetWindowAttribute(IntPtr h, int a, out RECT r, int size);

    public class Win { public IntPtr Handle; public uint Pid; public string Title; public int Area; }

    // Visible top-level windows with a title (no owned pop-ups).
    public static List<Win> List() {
        var all = new List<Win>();
        EnumWindows((h, p) => {
            if (!IsWindowVisible(h) || GetWindow(h, 4) != IntPtr.Zero) return true;
            var sb = new StringBuilder(512);
            GetWindowText(h, sb, sb.Capacity);
            if (sb.Length == 0) return true;
            uint pid; GetWindowThreadProcessId(h, out pid);
            RECT r; GetWindowRect(h, out r);
            all.Add(new Win { Handle = h, Pid = pid, Title = sb.ToString(), Area = (r.R - r.L) * (r.B - r.T) });
            return true;
        }, IntPtr.Zero);
        return all;
    }

    // Put the window's VISIBLE frame exactly at x,y,w,h (Windows 10/11 windows
    // have invisible resize borders around the visible frame).
    public static void Place(IntPtr h, int x, int y, int w, int ht) {
        ShowWindow(h, 9);  // SW_RESTORE: un-maximise / un-minimise
        SetWindowPos(h, IntPtr.Zero, x, y, w, ht, 0x0014);  // NOZORDER | NOACTIVATE
        RECT outer, vis;
        GetWindowRect(h, out outer);
        if (DwmGetWindowAttribute(h, 9, out vis, Marshal.SizeOf(typeof(RECT))) == 0) {  // EXTENDED_FRAME_BOUNDS
            int l = vis.L - outer.L, t = vis.T - outer.T, r = outer.R - vis.R, b = outer.B - vis.B;
            SetWindowPos(h, IntPtr.Zero, x - l, y - t, w + l + r, ht + t + b, 0x0014);
        }
    }
}
"@

# Work in real pixels, not scaled ones (PER_MONITOR_AWARE_V2).
[BoothWin]::SetProcessDpiAwarenessContext([IntPtr](-4)) | Out-Null

$work = New-Object BoothWin+RECT
[BoothWin]::SystemParametersInfo(0x30, 0, [ref]$work, 0) | Out-Null   # SPI_GETWORKAREA: screen minus taskbar
$W = $work.R - $work.L
$H = $work.B - $work.T
$gameW = [int][Math]::Round($W * $GameShare)

$names = @{}
Get-Process | ForEach-Object { $names[[uint32]$_.Id] = $_.ProcessName }
$wins = [BoothWin]::List() | ForEach-Object {
    $_ | Add-Member -NotePropertyName Proc -NotePropertyValue ($names[$_.Pid]) -PassThru
}

$game = $wins | Where-Object { $_.Proc -match '^eurotrucks2' -or $_.Title -match 'Euro Truck Simulator' } |
    Sort-Object Area -Descending | Select-Object -First 1
# The VNC viewer, by program name only (a browser tab titled "RealVNC" must not
# match). Prefer the window showing the Pi; the address book window is titled
# just "RealVNC Connect Viewer" / "VNC Viewer" and can't be made narrow.
$vncAll = $wins | Where-Object { $_.Proc -match 'vnc' }
$vnc = $vncAll | Where-Object { $_.Title -match '10\.43\.0\.1|inpi|raspberry|bamnun' } |
    Sort-Object Area -Descending | Select-Object -First 1
if (-not $vnc) {
    $vnc = $vncAll | Where-Object { $_.Title -notmatch '^(RealVNC Connect Viewer|VNC Viewer|RealVNC Connect)$' } |
        Sort-Object Area -Descending | Select-Object -First 1
}

$missing = @()
if ($game) { [BoothWin]::Place($game.Handle, $work.L, $work.T, $gameW, $H) } else { $missing += 'Euro Truck Simulator 2' }
if ($vnc)  { [BoothWin]::Place($vnc.Handle, $work.L + $gameW, $work.T, $W - $gameW, $H) } else { $missing += 'RealVNC (connected to the Pi)' }

# Give the game the focus last, so the wheel drives it straight away.
if ($game) { [BoothWin]::SetForegroundWindow($game.Handle) | Out-Null }

if ($missing.Count -gt 0) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        "Not open yet: " + ($missing -join ', ') + "`nOpen it, then run Booth layout again.",
        "Booth layout") | Out-Null
} else {
    Write-Host ("Game {0}x{1} left, RealVNC {2}x{1} right." -f $gameW, $H, ($W - $gameW))
}
