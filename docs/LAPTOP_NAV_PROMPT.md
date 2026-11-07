# Prompt for the laptop's Claude Code (switching between the game and Bamnun)

Copy everything in the box below into Claude Code on the Windows laptop.

```text
I'm running an exhibition booth on this Windows laptop (Windows 11) on
10 Nov 2026. The screen is split: Euro Truck Simulator 2 (ETS2) in a
borderless window on the left two thirds, and RealVNC Viewer on the right
third, showing a Raspberry Pi app called Bamnun (a drowsiness monitor) at
10.43.0.1. Visitors drive with a steering wheel; the operator and sometimes
visitors need to click buttons in the Bamnun window (consent buttons, "stage"
cards, a SETTINGS menu), then go back to driving.

Problem: ETS2 captures the mouse while driving, so the cursor can't leave the
game window. Alt+Tab works, but ordinary visitors and volunteers don't know
it. Clicking into the RealVNC window also takes focus from the game, so the
wheel stops steering until someone clicks the game again.

Goal: make switching effortless for non-technical people, with no keyboard
shortcuts to remember. Please investigate and set up the most reliable option
on this laptop, test it with ETS2 running, and explain it to me simply.
Ideas to evaluate (pick what actually works here):

1. ETS2 settings that stop it grabbing the mouse in windowed mode (Options ->
   Controls: mouse steering off; check config.cfg / controls.sii in
   Documents\Euro Truck Simulator 2\profiles for cursor/mouse capture
   settings). Back up any file before editing it.
2. A tiny AutoHotkey v2 script (install AutoHotkey if needed) that:
   - maps a spare button on the steering wheel (or one big easy key like F1,
     or a mouse side button) to "bring RealVNC Viewer to the front and free
     the cursor", and another to "bring ETS2 back to the front";
   - or shows a small always-on-top button/bar (e.g. "Bamnun" / "Game") at
     the edge of the screen that switches focus when clicked or touched;
   - optionally returns focus to ETS2 automatically a few seconds after the
     last click in RealVNC, so the wheel always works again.
   Start the script automatically at login, and give it a tray icon to quit.
3. If the laptop has a touch screen: whether tapping the RealVNC window works
   while ETS2 holds the mouse.

Constraints: don't change anything on the Raspberry Pi; don't install
anything sketchy (AutoHotkey from autohotkey.com is fine); keep the game in
borderless/windowed mode on the left 2/3 and RealVNC on the right 1/3; the
steering wheel must keep working in the game. When done, write a short
how-to (Korean and English) I can print for the booth, and list exactly what
you installed or changed so it can be undone after the exhibition.
```
