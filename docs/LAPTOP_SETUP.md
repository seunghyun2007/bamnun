# Booth on one laptop: game ⅔, Bamnun ⅓

The exhibition allows no personal monitors, but a personal laptop is allowed
when a Raspberry Pi is connected to it. So the teammate's **Windows laptop**
is the only screen: Euro Truck Simulator on the left two thirds, the Pi's
Bamnun window on the right third. The Pi still does everything itself
(camera, detection, light, mist, speaker, uploads); the laptop only shows its
screen.

## What's already set up on the Pi

- **VNC screen sharing is on** (wayvnc, port 5900). Log in with the Pi's user
  `inpi` and its password.
- **Cable profile `bamnun-laptop`:** with an Ethernet cable between the Pi and
  the laptop, the Pi is always **10.43.0.1** and gives the laptop an address
  automatically. It gives no internet route, so the laptop keeps its own Wi-Fi.
- The Pi uses its own Wi-Fi for the internet (uploads for the visitor QR).
  Saved networks include `Yonsei`, `Yonsei-new`, `Yonsei_Web` and a phone
  hotspot. If the venue Wi-Fi needs a web sign-in, use a phone hotspot.
- **Bamnun adapts to a tall window by itself:** when its window is taller than
  wide, the dashboard stacks (camera on top, state/eyes/head/wake-up stages
  below) and every slide stacks (picture on top, words below). The
  calibration arrow then points **left**, at the game.

## Things to bring

- Ethernet cable. If the laptop has no Ethernet port: a **USB-C (or USB-A) to
  Ethernet adapter**.
- The Pi's power supply, the camera device, speaker, etc. as usual.
- No monitor for the Pi.

## Setting up the laptop (once, at home first)

1. Install **RealVNC Viewer** (free): https://www.realvnc.com/en/connect/download/viewer/
2. Install **Microsoft PowerToys** (optional, for "always on top" and exact
   window sizes with FancyZones).
3. Euro Truck Simulator 2: Options → Graphics → **windowed / borderless**
   (not full screen), so it can share the screen.

## At the booth, every time

1. Power the Pi; connect the cable Pi ↔ laptop. Wait ~1 minute.
2. RealVNC Viewer → address **10.43.0.1** → log in as `inpi`.
   - Not connecting? Backup 1: Pi Connect in a browser
     (connect.raspberrypi.com). Backup 2: `inpi.local` in RealVNC Viewer.
3. In the VNC window, open **bamnun** from the Pi's desktop icon.
4. Arrange the windows (Windows Snap, or a FancyZones ⅔ / ⅓ layout):
   - Game: drag to the left, make it two thirds wide, full height.
     The game renders at the window's size; it isn't stretched.
   - RealVNC Viewer: right third, full height. In the viewer, set scaling to
     "fit to window" so Bamnun sees a tall window.
5. Click once on the game so the wheel drives it.

## During the demo

- **Focus:** clicking in the Bamnun window takes the keyboard/wheel focus
  away from the game. After using Bamnun's SETTINGS, **click the game again**.
  Visitors don't need to click Bamnun except the consent buttons and stage
  cards on the QR screen; pop-ups go away by themselves.
- **Next visitor:** SETTINGS → NEXT PERSON.
- **Sound:** Ollie's voice and alarms come from the Pi's own speaker, not the
  laptop.

## If something goes wrong

| Problem | Fix |
| --- | --- |
| VNC can't connect | Unplug/replug the cable, wait 30 s; try `inpi.local`; else Pi Connect in a browser |
| Bamnun looks tiny / landscape | The window isn't taller than wide: narrow the VNC window or set the viewer to "fit to window" |
| Wheel stops working | Click the game window |
| The visitor's QR says offline | The Pi has no internet: switch the Pi to a phone hotspot (Pi Connect or VNC → Wi-Fi menu) |
| Pi too hot banner | Let it cool; check the fan |

## Before Tuesday

- Do one full dry run on the real laptop: cable, VNC, layout, a visitor flow
  end to end (briefing → drive → QR → phone).
- Record a 1-minute video of a full demo as a fallback (OBS or Windows
  Game Bar, Win+Alt+R), also useful for the 5-page slides.
