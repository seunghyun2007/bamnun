# To do on the booth PC (Windows) — 2026-11-12

For Claude Code running on the booth PC, in the bamnun folder. Read the
2026-11-12 entry in HANDOFF.md first.

1. Get the new code: `git checkout demo-booth`, then `git pull`.
2. Stop Booth guard starting at sign-in, and start the film player at sign-in
   instead (the owner finds the guard annoying; staff are always at the booth):
   `powershell -ExecutionPolicy Bypass -File tools\booth\windows\booth_film.ps1 -Autostart`
   It prints what it removed from the Startup folder. If it reports a scheduled
   task that starts the guard, ask the owner before disabling it in Task Scheduler.
   The guard must still work from its desktop shortcut.
3. Start the film player now, without signing out:
   `powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File tools\booth\windows\booth_film.ps1`
4. Check: the owner presses ▶ 영상 재생 on the staff remote. The film should
   cover the game within about 1 s; ■ 영상 정지 brings the game back. If not,
   read `%APPDATA%\BamnunFilm\film.log`.
5. These PowerShell changes (the `-Autostart` switch in booth_film.ps1, and Booth
   guard restarting the film player within 30 s if it's missing) were written
   on a Mac and never run on Windows. Fix anything that fails, then commit and
   push to `demo-booth` (never `main`), and add a line to HANDOFF.md.
6. Ask the owner before changing any other Windows settings.
