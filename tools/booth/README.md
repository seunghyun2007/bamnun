# Demo booth

Visitors scan one QR code, join the Pi's Wi-Fi, and the Bamnun app pops up on
their phone. The Pi's monitor shows the camera full screen with what Bamnun
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
- Join `Bamnun-Demo` from a laptop and `ssh <user>@10.42.0.1`, then
  `tools/booth/booth.sh off` (works at the venue too).
- An Ethernet cable to the router keeps the Pi online, so Pi Connect keeps
  working while the hotspot is on.

The Pi needs desktop auto-login (Raspberry Pi OS's default) for the booth to
start by itself after a power cut. Log: `~/bamnun-booth.log`.

## Poster

On any computer: `pip install qrcode`, then
`python tools/booth/make_poster.py`, open `tools/booth/poster.html` and print it
on A4. The QR code only joins the Wi-Fi; joining is what opens the app.

## How the pop-up works

Every phone checks for internet right after joining Wi-Fi by fetching a known
page (`captive.apple.com/hotspot-detect.html`, `/generate_204`, ...). The DNS
sends that to the Pi, and the app's server, started with `--booth`, answers
with a redirect to its welcome page, so the phone shows it as a Wi-Fi sign-in
sheet. After the visitor taps **Open the Bamnun app**, that phone gets the
normal answer and stays on the network. Phones that don't pop it up can open
`http://bamnun.demo`.

There's no internet on this Wi-Fi, so Google sign-in and the Kakao map don't
work at the booth. Video stays on the booth's Wi-Fi.

## Before the event

- Try it with five to ten phones at once, iPhone and Android, watching the
  Camera screen: the live video is the heaviest part for the Pi.
- Check the "why we chose it" text on the Product control cards with the team.
