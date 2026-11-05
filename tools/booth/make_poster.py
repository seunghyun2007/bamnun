"""Make the booth's QR code poster: one code that joins the demo Wi-Fi.

    pip install qrcode
    python tools/booth/make_poster.py                 # writes tools/booth/poster.html
    python tools/booth/make_poster.py --ssid Other    # if the hotspot is renamed

Open the HTML in a browser and print it (A4 portrait). Scanning the code with
the phone's camera offers to join the Wi-Fi; joining pops the app up
(server.py, booth mode). The address underneath is for the few phones that
don't pop it up on their own.
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path

import qrcode
import qrcode.image.svg

HERE = Path(__file__).resolve().parent

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Bamnun booth poster</title>
<style>
@page {{ size: A4 portrait; margin: 0 }}
html, body {{ margin: 0; background: #17111A }}
body {{ width: 210mm; height: 297mm; box-sizing: border-box; padding: 22mm 18mm;
       display: flex; flex-direction: column; align-items: center; text-align: center;
       color: #F4EFE6; font-family: -apple-system, "Apple SD Gothic Neo", "Noto Sans KR", system-ui, sans-serif;
       background: radial-gradient(110% 55% at 50% 0%, rgba(168,132,232,.45), rgba(168,132,232,0) 62%), #17111A;
       -webkit-print-color-adjust: exact; print-color-adjust: exact }}
.kicker {{ font-size: 15pt; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: #C4B5FD }}
h1 {{ margin: 4mm 0 0; font-size: 40pt; line-height: 1.05 }}
.sub {{ margin: 4mm 0 0; font-size: 15pt; color: #D7CDD9 }}
.qr {{ margin: 12mm 0 0; padding: 7mm; background: #fff; border-radius: 8mm; width: 118mm; height: 118mm }}
.qr svg {{ width: 100%; height: 100% }}
.steps {{ margin: 10mm 0 0; display: grid; grid-template-columns: repeat(3, 1fr); gap: 6mm; width: 100% }}
.step b {{ display: block; font-size: 22pt; color: #F9A8D4 }}
.step span {{ display: block; margin-top: 1mm; font-size: 12.5pt; line-height: 1.35 }}
.foot {{ margin-top: auto; font-size: 11.5pt; color: #B3A6B4; line-height: 1.5 }}
.foot code {{ color: #F4EFE6; font-size: 13pt }}
</style></head><body>
<div class="kicker">밤눈 · Bamnun</div>
<h1>Try Bamnun on your phone<br>휴대폰으로 체험해 보세요</h1>
<p class="sub">Scan with your camera · 카메라로 스캔하세요</p>
<div class="qr">{qr}</div>
<div class="steps">
  <div class="step"><b>1</b><span>Scan the code<br>코드 스캔</span></div>
  <div class="step"><b>2</b><span>Tap “Join” for {ssid}<br>“{ssid}” 연결</span></div>
  <div class="step"><b>3</b><span>The app opens<br>앱이 열려요</span></div>
</div>
<p class="foot">App didn't open? In Safari or Chrome go to <code>http://bamnun.demo</code><br>
앱이 열리지 않으면 Safari나 Chrome에서 <code>http://bamnun.demo</code> 로 들어가세요<br>
Wi-Fi: <b>{ssid}</b> (no password · 비밀번호 없음, no internet · 인터넷 없음)</p>
</body></html>
"""


def wifi_qr_svg(ssid: str) -> str:
    # The standard Wi-Fi QR format; "nopass" because the booth hotspot is open.
    escaped = "".join("\\" + c if c in "\\;,:\"" else c for c in ssid)
    img = qrcode.make(f"WIFI:T:nopass;S:{escaped};;",
                      image_factory=qrcode.image.svg.SvgPathImage, border=0,
                      error_correction=qrcode.constants.ERROR_CORRECT_M)
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode()
    return svg[svg.index("<svg"):]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ssid", default="Bamnun-Demo")
    ap.add_argument("--out", default=str(HERE / "poster.html"))
    args = ap.parse_args()
    Path(args.out).write_text(PAGE.format(qr=wifi_qr_svg(args.ssid), ssid=args.ssid),
                              encoding="utf-8")
    print(f"wrote {args.out}: open it in a browser and print on A4")


if __name__ == "__main__":
    main()
