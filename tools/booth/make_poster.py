"""Make the booth's QR code poster: code 1 joins the Wi-Fi, code 2 opens the app.

    pip install qrcode
    python tools/booth/make_poster.py                 # writes tools/booth/poster.html
    python tools/booth/make_poster.py --ssid Other    # if the hotspot is renamed

Open the HTML in a browser and print it (A4 portrait). Both codes are read
by the phone's own camera, one after the other, without leaving it. The app
link is the Pi's address, not a name: an iPhone with iCloud Private Relay
sends names out to the internet, which the booth doesn't have, but keeps
local addresses like 10.42.0.1 on the Wi-Fi.
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path

import qrcode
import qrcode.image.svg

HERE = Path(__file__).resolve().parent
APP_URL = "http://10.42.0.1"

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Bamnun booth poster</title>
<style>
@page {{ size: A4 portrait; margin: 0 }}
html, body {{ margin: 0; background: #17111A }}
body {{ width: 210mm; height: 297mm; box-sizing: border-box; padding: 20mm 14mm 16mm;
       display: flex; flex-direction: column; align-items: center; text-align: center;
       color: #F4EFE6; font-family: -apple-system, "Apple SD Gothic Neo", "Noto Sans KR", system-ui, sans-serif;
       background: radial-gradient(110% 55% at 50% 0%, rgba(168,132,232,.45), rgba(168,132,232,0) 62%), #17111A;
       -webkit-print-color-adjust: exact; print-color-adjust: exact }}
.kicker {{ font-size: 15pt; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: #C4B5FD }}
h1 {{ margin: 4mm 0 0; font-size: 38pt; line-height: 1.05 }}
.sub {{ margin: 4mm 0 0; font-size: 15pt; color: #D7CDD9 }}
.codes {{ margin: 12mm 0 0; display: grid; grid-template-columns: 1fr 1fr; gap: 10mm; width: 100% }}
.code {{ display: flex; flex-direction: column; align-items: center }}
.num {{ width: 14mm; height: 14mm; border-radius: 50%; display: grid; place-items: center;
        background: #F9A8D4; color: #241A26; font-size: 20pt; font-weight: 800 }}
.qr {{ margin-top: 5mm; padding: 5mm; background: #fff; border-radius: 6mm; width: 74mm; height: 74mm }}
.qr svg {{ width: 100%; height: 100% }}
.what {{ margin-top: 5mm; font-size: 17pt; font-weight: 700; line-height: 1.25 }}
.how {{ margin-top: 2mm; font-size: 12pt; color: #D7CDD9; line-height: 1.4 }}
.foot {{ margin-top: auto; font-size: 11.5pt; color: #B3A6B4; line-height: 1.5 }}
.foot b {{ color: #F4EFE6 }}
</style></head><body>
<div class="kicker">밤눈 · Bamnun</div>
<h1>Try Bamnun on your phone<br>휴대폰으로 체험해 보세요</h1>
<p class="sub">Scan both codes with your camera, in order · 카메라로 순서대로 스캔하세요</p>
<div class="codes">
  <div class="code">
    <div class="num">1</div>
    <div class="qr">{wifi}</div>
    <div class="what">Join the Wi-Fi<br>Wi-Fi 연결</div>
    <div class="how">Tap “Join” · “연결” 누르기</div>
  </div>
  <div class="code">
    <div class="num">2</div>
    <div class="qr">{app}</div>
    <div class="what">Open the app<br>앱 열기</div>
    <div class="how">Tap the link · 링크 누르기</div>
  </div>
</div>
<p class="foot">Wi-Fi <b>{ssid}</b> · no password · 비밀번호 없음 · no internet · 인터넷 없음<br>
Or type <b>{url}</b> in Safari or Chrome · Safari나 Chrome에 <b>{url}</b> 입력</p>
</body></html>
"""


def qr_svg(data: str) -> str:
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, border=0,
                      error_correction=qrcode.constants.ERROR_CORRECT_M)
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode()
    return svg[svg.index("<svg"):]


def wifi_data(ssid: str) -> str:
    # The standard Wi-Fi QR format; "nopass" because the booth hotspot is open.
    escaped = "".join("\\" + c if c in "\\;,:\"" else c for c in ssid)
    return f"WIFI:T:nopass;S:{escaped};;"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ssid", default="Bamnun-Demo")
    ap.add_argument("--out", default=str(HERE / "poster.html"))
    args = ap.parse_args()
    Path(args.out).write_text(
        PAGE.format(wifi=qr_svg(wifi_data(args.ssid)), app=qr_svg(APP_URL),
                    ssid=args.ssid, url=APP_URL.removeprefix("http://")),
        encoding="utf-8")
    print(f"wrote {args.out}: open it in a browser and print on A4")


if __name__ == "__main__":
    main()
