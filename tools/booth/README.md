# Demo booth

Visitors scan two QR codes with their phone's camera: the first joins the
Pi's Wi-Fi, the second opens the Bamnun app in Safari or Chrome. The Pi's monitor shows the camera full screen with what Bamnun
sees. The Welcome screen offers **Product demo** (the app on a demo drive) and
**Product control** (the four wake-up stages, played on the real device, one
phone at a time).

## Once, on the Pi

```
cd ~/bamnun            # wherever the repo is
git pull               # this branch
bash tools/booth/setup_booth.sh
```

It prepares an open hotspot `Bamnun-Demo` at 10.42.0.1, DNS on it that sends
every name to the Pi, port 80 for the app, and a `Bamnun booth` menu entry. It
doesn't switch anything on.

## Practising at home

`tools/booth/booth.sh home` runs the booth program on the Pi's normal Wi-Fi:
camera full screen on the monitor, the app for phones on the same Wi-Fi at
the Pi's address, and the Pi stays reachable over Tailscale and Pi Connect.
`booth.sh stop` stops it. In every booth mode the device fires nothing by
itself (no light, mist, voice or alarm, no break reminder or emergency
check); only Product control's stage buttons play the parts.

## At the venue

```
tools/booth/booth.sh on       # hotspot on; the booth starts now and at every login
tools/booth/booth.sh status
tools/booth/booth.sh off      # afterwards: normal Wi-Fi back
```

`booth.sh on` takes the Pi off your normal Wi-Fi, so an SSH or Pi Connect
session over Wi-Fi drops. Ways to drive it without a keyboard and monitor:

- `tools/booth/booth.sh try 10` from Pi Connect or SSH: the booth for 10
  minutes, then back on normal Wi-Fi by itself, and the session comes back.
  Nothing is set to start at boot, so unplugging the Pi also undoes it.
- Join `Bamnun-Demo` from a laptop and run
  `ssh <user>@10.42.0.1 bamnun/tools/booth/booth.sh off` (works at the venue too).
- An Ethernet cable to the router keeps the Pi online, so Pi Connect keeps
  working while the hotspot is on.

The Pi needs desktop auto-login (Raspberry Pi OS's default) for the booth to
start by itself after a power cut. Log: `~/bamnun-booth.log`.

## From your laptop

`tools/booth/pi.sh status|on|off|try 10|restart|logs|update|ssh` runs the
same commands on the Pi from a laptop. It goes over Tailscale while the Pi is
online, and over the booth's Wi-Fi (join `Bamnun-Demo`, Pi at 10.42.0.1) while
the booth is on. The second way needs the laptop's SSH key on the Pi once:
`ssh-copy-id inpi`.

## Poster

On any computer: `pip install qrcode`, then
`python tools/booth/make_poster.py`, open `tools/booth/poster.html` and print it
on A4. Code 1 joins `Bamnun-Demo`; code 2 opens `http://10.42.0.1`.

## Why two codes

A phone that joins Wi-Fi checks for internet by fetching a known page. A
wrong answer would pop up a sign-in sheet, but on an iPhone that sheet only
appears after leaving the Camera app, and it's a cut-down browser. So the
booth (`--booth`) gives every phone the expected answer and it stays on the
Wi-Fi quietly; the second code opens the app in the real browser. The link
is the Pi's address rather than a name, because iCloud Private Relay sends
names out to the internet, which the booth doesn't have.

There's no internet on this Wi-Fi, so Google sign-in and the Kakao map don't
work at the booth. Video stays on the booth's Wi-Fi.

## Before the event

- Try it with five to ten phones at once, iPhone and Android, watching the
  Camera screen: the live video is the heaviest part for the Pi.
- Check the "why we chose it" text on the Product control cards with the team.
