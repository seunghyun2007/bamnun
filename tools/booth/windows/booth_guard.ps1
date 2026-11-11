# Booth guard: visitors can use only the game and the RealVNC window.
#
# While it runs:
# - Euro Truck Simulator 2 and RealVNC work as usual (Alt+Tab between them too),
#   and so does the product film (booth_film.ps1, started here, played from
#   the staff remote).
# - Anything else that comes to the front (Start menu, taskbar, Explorer, a
#   browser, Task Manager...) is covered by a full-screen lock with a big
#   "Back to the game" button and a staff PIN box.
# - The Windows keys, Alt+F4, Ctrl+Esc, Alt+Esc and Ctrl+Shift+Esc do nothing.
# - The right PIN unlocks everything for 10 minutes, then the guard is back.
#   While unlocked, the tray icon (shield) can turn the guard off.
#
# The PIN is chosen at the first start and kept only as a salted hash in
# %APPDATA%\BamnunBoothGuard\pin.txt (delete that file to choose a new one).
# Nothing in Windows is changed: quitting the guard undoes everything.
# Stuck? Ctrl+Alt+Del always works (Windows doesn't let any program block it):
# sign out, or open Task Manager and end "Windows PowerShell".
#
#   booth_guard.ps1              start (runs Booth layout first)
#   booth_guard.ps1 -DryRun      for 10 s, only print what it would lock

param(
    [switch]$DryRun,
    [int]$PauseMinutes = 10
)

$ErrorActionPreference = 'Stop'

Add-Type -ReferencedAssemblies System.Windows.Forms, System.Drawing -TypeDefinition @"
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Windows.Forms;

public static class GuardNative {
    public delegate IntPtr KbProc(int code, IntPtr wParam, IntPtr lParam);
    [StructLayout(LayoutKind.Sequential)]
    public struct KBD { public uint vk, scan, flags, time; public IntPtr extra; }

    [DllImport("user32.dll")] public static extern IntPtr SetWindowsHookEx(int id, KbProc fn, IntPtr mod, uint tid);
    [DllImport("user32.dll")] public static extern bool UnhookWindowsHookEx(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr CallNextHookEx(IntPtr h, int c, IntPtr w, IntPtr l);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] public static extern IntPtr GetModuleHandle(string n);
    [DllImport("user32.dll")] public static extern short GetAsyncKeyState(int vk);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();

    // Windows only lets the active program take the foreground; a tap of Alt
    // lifts that rule for the next SetForegroundWindow.
    public static void Force(IntPtr h) {
        if (h == IntPtr.Zero) return;
        if (IsIconic(h)) ShowWindow(h, 9);
        keybd_event(0x12, 0, 0, UIntPtr.Zero);
        SetForegroundWindow(h);
        keybd_event(0x12, 0, 2, UIntPtr.Zero);
    }

    public static string ClassOf(IntPtr h) {
        var sb = new StringBuilder(256);
        GetClassName(h, sb, sb.Capacity);
        return sb.ToString();
    }

    public static string TitleOf(IntPtr h) {
        var sb = new StringBuilder(256);
        GetWindowText(h, sb, sb.Capacity);
        return sb.ToString();
    }

    public static string ProcOf(IntPtr h) {
        uint pid;
        GetWindowThreadProcessId(h, out pid);
        try { return Process.GetProcessById((int)pid).ProcessName.ToLowerInvariant(); }
        catch { return "?"; }
    }

    public static int PidOf(IntPtr h) {
        uint pid;
        GetWindowThreadProcessId(h, out pid);
        return (int)pid;
    }
}

public static class GuardPin {
    static string Hash(string salt, string pin) {
        using (var s = SHA256.Create())
            return Convert.ToBase64String(s.ComputeHash(Encoding.UTF8.GetBytes(salt + ":" + pin)));
    }

    public static bool Exists(string file) { return File.Exists(file); }

    public static bool Check(string file, string pin) {
        try {
            var l = File.ReadAllLines(file);
            return l.Length >= 2 && Hash(l[0], pin) == l[1];
        } catch { return false; }
    }

    static void Save(string file, string pin) {
        var b = new byte[16];
        using (var r = RandomNumberGenerator.Create()) r.GetBytes(b);
        var salt = Convert.ToBase64String(b);
        Directory.CreateDirectory(Path.GetDirectoryName(file));
        File.WriteAllText(file, salt + "\n" + Hash(salt, pin) + "\n");
    }

    // First start: ask for the staff PIN twice. False if cancelled.
    public static bool Setup(string file) {
        while (true) {
            var f = new Form();
            f.Text = "Booth guard: choose a staff PIN";
            f.FormBorderStyle = FormBorderStyle.FixedDialog;
            f.StartPosition = FormStartPosition.CenterScreen;
            f.MaximizeBox = false; f.MinimizeBox = false; f.TopMost = true;
            f.ClientSize = new Size(380, 190);
            f.Font = new Font("Segoe UI", 10);
            var l1 = new Label { Text = "New PIN (at least 4 characters):", Left = 16, Top = 16, Width = 340 };
            var p1 = new TextBox { Left = 16, Top = 40, Width = 340, UseSystemPasswordChar = true };
            var l2 = new Label { Text = "Same PIN again:", Left = 16, Top = 76, Width = 340 };
            var p2 = new TextBox { Left = 16, Top = 100, Width = 340, UseSystemPasswordChar = true };
            var ok = new Button { Text = "Save", Left = 176, Top = 144, Width = 85, DialogResult = DialogResult.OK };
            var no = new Button { Text = "Cancel", Left = 271, Top = 144, Width = 85, DialogResult = DialogResult.Cancel };
            f.Controls.AddRange(new Control[] { l1, p1, l2, p2, ok, no });
            f.AcceptButton = ok; f.CancelButton = no;
            if (f.ShowDialog() != DialogResult.OK) return false;
            if (p1.Text.Length < 4) { MessageBox.Show("The PIN needs at least 4 characters.", "Booth guard"); continue; }
            if (p1.Text != p2.Text) { MessageBox.Show("The two PINs are different. Try again.", "Booth guard"); continue; }
            Save(file, p1.Text);
            return true;
        }
    }
}

public class LockForm : Form {
    public Button Back;
    public TextBox Pin;
    Label title, sub, pinLabel, msg;
    Button unlock;
    public Func<string, bool> TryPin;
    public Action GoBack;
    Timer cooldown;

    public LockForm() {
        FormBorderStyle = FormBorderStyle.None;
        StartPosition = FormStartPosition.Manual;
        Bounds = Screen.PrimaryScreen.Bounds;
        TopMost = true;
        ShowInTaskbar = false;
        BackColor = Color.FromArgb(21, 19, 26);
        ForeColor = Color.White;

        title = new Label { Text = "직원 전용 · Staff only", Font = new Font("Malgun Gothic", 30, FontStyle.Bold), AutoSize = true };
        sub = new Label { Text = "계속 운전하려면 아래 버튼을 눌러 주세요.\nTo keep driving, press the button below.",
                          Font = new Font("Malgun Gothic", 15), AutoSize = true, ForeColor = Color.FromArgb(200, 200, 205), TextAlign = ContentAlignment.MiddleCenter };
        Back = new Button { Text = "‹  게임으로 돌아가기 · Back to the game", Font = new Font("Malgun Gothic", 18, FontStyle.Bold),
                            Size = new Size(620, 90), BackColor = Color.FromArgb(232, 215, 174), ForeColor = Color.FromArgb(21, 19, 26),
                            FlatStyle = FlatStyle.Flat };
        Back.FlatAppearance.BorderSize = 0;
        pinLabel = new Label { Text = "Staff PIN", Font = new Font("Segoe UI", 11), AutoSize = true, ForeColor = Color.FromArgb(150, 150, 155) };
        Pin = new TextBox { Font = new Font("Segoe UI", 14), Width = 200, UseSystemPasswordChar = true };
        unlock = new Button { Text = "Unlock", Font = new Font("Segoe UI", 11), Size = new Size(100, Pin.Height),
                              FlatStyle = FlatStyle.Flat, ForeColor = Color.White };
        msg = new Label { Text = "", Font = new Font("Segoe UI", 11), AutoSize = true, ForeColor = Color.FromArgb(242, 182, 109) };
        Controls.AddRange(new Control[] { title, sub, Back, pinLabel, Pin, unlock, msg });

        Back.Click += delegate { if (GoBack != null) GoBack(); };
        unlock.Click += delegate { Submit(); };
        Pin.KeyDown += (s, e) => { if (e.KeyCode == Keys.Enter) { e.SuppressKeyPress = true; Submit(); } };
        CancelButton = Back;   // Esc = back to the game

        cooldown = new Timer { Interval = 2000 };
        cooldown.Tick += delegate { cooldown.Stop(); Pin.Enabled = true; unlock.Enabled = true; Pin.Focus(); };
        Layout += delegate { Arrange(); };
    }

    void Arrange() {
        int cx = ClientSize.Width / 2, y = ClientSize.Height / 2 - 220;
        title.Location = new Point(cx - title.Width / 2, y); y += title.Height + 24;
        sub.Location = new Point(cx - sub.Width / 2, y); y += sub.Height + 40;
        Back.Location = new Point(cx - Back.Width / 2, y); y += Back.Height + 90;
        int row = pinLabel.Width + 12 + Pin.Width + 8 + unlock.Width;
        int x = cx - row / 2;
        pinLabel.Location = new Point(x, y + (Pin.Height - pinLabel.Height) / 2); x += pinLabel.Width + 12;
        Pin.Location = new Point(x, y); x += Pin.Width + 8;
        unlock.Location = new Point(x, y);
        y += Pin.Height + 14;
        msg.Location = new Point(cx - msg.Width / 2, y);
    }

    public void Reset() {
        Pin.Text = ""; msg.Text = ""; Pin.Enabled = true; unlock.Enabled = true;
        Bounds = Screen.PrimaryScreen.Bounds;
    }

    void Submit() {
        if (Pin.Text.Length == 0 || TryPin == null) return;
        if (TryPin(Pin.Text)) return;
        msg.Text = "PIN이 틀렸어요 · Wrong PIN";
        Arrange();
        Pin.Text = ""; Pin.Enabled = false; unlock.Enabled = false;
        cooldown.Start();
    }

    protected override void OnFormClosing(FormClosingEventArgs e) {
        if (e.CloseReason == CloseReason.UserClosing) e.Cancel = true;
        base.OnFormClosing(e);
    }
}

public class BoothGuard : ApplicationContext {
    // Programs visitors may use. Process names, lower case.
    static readonly string[] Allowed = { "eurotrucks2", "rvncconnect", "vncviewer" };
    // Explorer's Alt+Tab / task switcher, so staff can still switch game <-> VNC.
    static readonly string[] Switcher = { "XamlExplorerHostIslandWindow", "MultitaskingViewFrame", "ForegroundStaging", "TaskSwitcherWnd" };
    // Shell windows that must not be minimised when going back to the game.
    static readonly string[] ShellProcs = { "explorer", "startmenuexperiencehost", "searchhost", "shellexperiencehost", "?" };

    readonly string pinFile;
    readonly int pauseMinutes;
    readonly bool dryRun;
    readonly int myPid = Process.GetCurrentProcess().Id;
    NotifyIcon tray;
    Timer timer;
    LockForm lockForm;
    DateTime pausedUntil = DateTime.MinValue;
    DateTime armedAt;
    IntPtr hook = IntPtr.Zero;
    GuardNative.KbProc hookProc;
    IntPtr offender = IntPtr.Zero;
    string offenderProc = "";
    string lastSeen = "";

    public BoothGuard(string pinFile, int pauseMinutes, bool dryRun) {
        this.pinFile = pinFile;
        this.pauseMinutes = pauseMinutes;
        this.dryRun = dryRun;

        lockForm = new LockForm();
        lockForm.TryPin = TryPin;
        lockForm.GoBack = BackToGame;

        var menu = new ContextMenuStrip();
        menu.Items.Add("Turn the guard on now", null, delegate { Resume(); });
        menu.Items.Add("Quit Booth guard", null, delegate { Quit(); });
        tray = new NotifyIcon { Icon = SystemIcons.Shield, Text = "Booth guard: on", Visible = true, ContextMenuStrip = menu };

        if (!dryRun) {
            hookProc = KeyHook;
            hook = GuardNative.SetWindowsHookEx(13, hookProc, GuardNative.GetModuleHandle("user32"), 0);  // WH_KEYBOARD_LL
        } else {
            tray.Text = "Booth guard: dry run";
            var stop = new Timer { Interval = 10000 };
            stop.Tick += delegate { stop.Stop(); Console.WriteLine("dry run over"); Quit(true); };
            stop.Start();
        }

        if (!dryRun) BringGame();
        armedAt = DateTime.Now.AddSeconds(3);   // let the game come to the front first
        timer = new Timer { Interval = 250 };
        timer.Tick += Tick;
        timer.Start();
        if (!dryRun)
            tray.ShowBalloonTip(4000, "Booth guard is on", "Only the game and RealVNC can be used. Staff PIN unlocks for " + pauseMinutes + " min.", ToolTipIcon.Info);
    }

    bool Paused { get { return DateTime.Now < pausedUntil; } }

    IntPtr KeyHook(int code, IntPtr w, IntPtr l) {
        if (code >= 0 && !Paused) {
            var k = (GuardNative.KBD)Marshal.PtrToStructure(l, typeof(GuardNative.KBD));
            bool alt = (k.flags & 0x20) != 0;
            bool ctrl = (GuardNative.GetAsyncKeyState(0x11) & 0x8000) != 0;
            if (k.vk == 0x5B || k.vk == 0x5C) return (IntPtr)1;   // Windows keys
            if (k.vk == 0x1B && (ctrl || alt)) return (IntPtr)1;    // Ctrl+Esc, Alt+Esc, Ctrl+Shift+Esc
            if (k.vk == 0x73 && alt) return (IntPtr)1;              // Alt+F4
        }
        return GuardNative.CallNextHookEx(hook, code, w, l);
    }

    bool IsAllowed(IntPtr h, out string proc) {
        proc = GuardNative.ProcOf(h);
        if (GuardNative.PidOf(h) == myPid) return true;
        if (Array.IndexOf(Allowed, proc) >= 0) return true;
        // The product film over the game (booth_film.ps1), played from the remote.
        if (proc == "powershell" && GuardNative.TitleOf(h) == "Bamnun film") return true;
        if (proc == "explorer" && Array.IndexOf(Switcher, GuardNative.ClassOf(h)) >= 0) return true;
        return false;
    }

    void Tick(object s, EventArgs e) {
        if (Paused) {
            int left = (int)Math.Ceiling((pausedUntil - DateTime.Now).TotalMinutes);
            tray.Text = "Booth guard: unlocked (" + left + " min left)";
            return;
        }
        if (pausedUntil != DateTime.MinValue) {   // a pause just ran out
            pausedUntil = DateTime.MinValue;
            tray.Text = "Booth guard: on";
            tray.ShowBalloonTip(3000, "Booth guard is on again", "Only the game and RealVNC can be used.", ToolTipIcon.Info);
        }
        if (lockForm.Visible) { lockForm.TopMost = true; return; }
        if (DateTime.Now < armedAt) return;

        IntPtr h = GuardNative.GetForegroundWindow();
        if (h == IntPtr.Zero) return;
        string proc;
        bool ok = IsAllowed(h, out proc);
        if (dryRun) {
            string line = (ok ? "allowed     " : "WOULD LOCK  ") + proc + " (" + GuardNative.ClassOf(h) + ")";
            if (line != lastSeen) { Console.WriteLine(line); lastSeen = line; }
            return;
        }
        if (!ok) ShowLock(h, proc);
    }

    void ShowLock(IntPtr h, string proc) {
        offender = h; offenderProc = proc;
        lockForm.Reset();
        lockForm.Show();
        lockForm.TopMost = true;
        GuardNative.Force(lockForm.Handle);
        lockForm.Back.Focus();
    }

    void BringGame() {
        var g = Process.GetProcessesByName("eurotrucks2");
        if (g.Length > 0) GuardNative.Force(g[0].MainWindowHandle);
    }

    void BackToGame() {
        lockForm.Hide();
        if (offender != IntPtr.Zero && Array.IndexOf(ShellProcs, offenderProc) < 0)
            GuardNative.ShowWindow(offender, 6);   // SW_MINIMIZE the window that wasn't allowed
        offender = IntPtr.Zero;
        BringGame();
        armedAt = DateTime.Now.AddSeconds(1.5);
    }

    bool TryPin(string pin) {
        if (!GuardPin.Check(pinFile, pin)) return false;
        pausedUntil = DateTime.Now.AddMinutes(pauseMinutes);
        lockForm.Hide();
        offender = IntPtr.Zero;
        tray.ShowBalloonTip(4000, "Booth guard unlocked", "Everything works for " + pauseMinutes + " min. Tray shield > Turn the guard on now, or Quit.", ToolTipIcon.Info);
        return true;
    }

    void Resume() {
        if (!Paused) return;
        pausedUntil = DateTime.Now;   // Tick turns it back on
        BringGame();
        armedAt = DateTime.Now.AddSeconds(1.5);
    }

    void Quit() { Quit(false); }

    void Quit(bool force) {
        if (!force && !Paused) {   // only while unlocked with the PIN
            IntPtr h = GuardNative.GetForegroundWindow();
            ShowLock(h, GuardNative.ProcOf(h));
            return;
        }
        timer.Stop();
        if (hook != IntPtr.Zero) GuardNative.UnhookWindowsHookEx(hook);
        tray.Visible = false;
        tray.Dispose();
        lockForm.Dispose();
        ExitThread();
    }
}
"@

$mutex = New-Object System.Threading.Mutex($false, 'Local\BamnunBoothGuard')
if (-not $mutex.WaitOne(0)) { exit }   # already running

# Put the windows in place first (game left 2/3, RealVNC right 1/3), in its
# own process so its screen-pixel setting doesn't clash with this one.
$layout = Join-Path $PSScriptRoot 'booth_layout.ps1'
if (-not $DryRun -and (Test-Path $layout)) {
    Start-Process powershell -WindowStyle Hidden -Wait -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$layout`"")
}

# The product film player (the remote's ▶ 영상 재생 plays it over the game).
$film = Join-Path $PSScriptRoot 'booth_film.ps1'
if (-not $DryRun -and (Test-Path $film)) {
    Start-Process powershell -WindowStyle Hidden -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-STA', '-File', "`"$film`"")
}

[GuardNative]::SetProcessDPIAware() | Out-Null
[System.Windows.Forms.Application]::EnableVisualStyles()

$pinFile = Join-Path $env:APPDATA 'BamnunBoothGuard\pin.txt'
if (-not $DryRun -and -not [GuardPin]::Exists($pinFile)) {
    if (-not [GuardPin]::Setup($pinFile)) { exit }
}

[System.Windows.Forms.Application]::Run((New-Object BoothGuard($pinFile, $PauseMinutes, [bool]$DryRun)))
