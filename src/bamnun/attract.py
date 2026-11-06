"""The booth's own screens: standby, when nobody is at the wheel, and the quick
briefing that a visitor starts with the space bar (or a click).

They are drawn at the window's own size, not on the dashboard's 1280x720
canvas and stretched: stretched text came out soft on a full-screen
monitor. The layout is written in 1280x720 units and scaled. Korean comes
first, English under it. OpenCV's fonts have no Korean, so text goes
through Pillow with a Korean font (fonts-nanum on the Pi, installed by
setup_pi.sh); without one only the English is shown, never boxes.

The static parts of each screen are drawn once per window size and kept; a
frame only adds the live camera thumbnail and the pulsing prompt.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Optional

import numpy as np

from .viz import DASH_H, DASH_W

log = logging.getLogger("bamnun.attract")

FONTS_BOLD = ("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
              "/System/Library/Fonts/AppleSDGothicNeo.ttc")
FONTS_REGULAR = ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
                 "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                 "/System/Library/Fonts/AppleSDGothicNeo.ttc")

_BG = (26, 17, 23)          # BGR of the app's #17111A
_INK = (230, 239, 244)      # #F4EFE6
_MUTED = (180, 166, 179)
_ACCENT = (253, 181, 196)   # the app's lavender, #C4B5FD
_PINK = (212, 168, 249)

# (Ollie, Korean title, English title, Korean line, English line)
STEPS = [
    ("hello", "안녕하세요, 저는 올리예요", "Hi, I'm Ollie",
     "밤눈은 운전하는 동안 눈을 지켜보고, 너무 늦기 전에 깨워 줘요.",
     "Bamnun watches your eyes while you drive, and wakes you before it's too late."),
    ("driving", "핸들 앞에 앉으세요", "Sit at the wheel",
     "왼쪽의 카메라 말고 화면 속 도로를 보세요.",
     "Look at the road on the screen, not at the camera on your left."),
    ("thinking", "먼저 15초 동안 눈을 익혀요", "First, 15 seconds to learn your eyes",
     "도로를 보며 평소처럼 눈을 깜빡이세요. 올리가 눈을 뜬 모습을 익혀요.",
     "Keep looking at the road and blink normally. Ollie learns how your eyes look open."),
    ("sleepy", "그다음 졸린 척 해 보세요", "Then try being sleepy",
     "2초 동안 눈을 감거나, 고개를 떨구거나, 도로에서 눈을 떼 보세요.",
     "Close your eyes for 2 seconds, let your head nod, or look away from the road."),
    ("wake", "밤눈은 네 단계로 깨워요", "Bamnun wakes you in four steps",
     "파란 불빛, 민트 미스트, 차임과 올리의 목소리, 그리고 점점 커지는 알람.",
     "Blue light, then mint mist, then a chime and Ollie's voice, then a rising alarm."),
]

# Where things go, in 1280x720 units (y is each line's top).
_STANDBY = {"owl": ("hello", 230, 40), "lines": [
    ("여기 앉아서 밤눈을 체험해 보세요!", "bold", 64, _ACCENT, 290),
    ("Sit here and try Bamnun!", "bold", 46, _INK, 372),
    ("야간 운전자를 위한 졸음 지킴이", "regular", 30, _INK, 446),
    ("A drowsiness co-pilot for drivers at night", "regular", 26, _MUTED, 490)]}
_STANDBY_PROMPT = [("스페이스바를 누르거나 클릭하세요", "bold", 36, _PINK, 0),
                   ("Press SPACE or click to start", "bold", 28, _PINK, 48)]
_PROMPT_TOP, _PROMPT_H = 578, 110
_BRIEF_PROMPT = [("스페이스바 또는 클릭: 다음", "bold", 32, _PINK, 8),
                 ("SPACE or click: next", "bold", 26, _PINK, 52)]
_BRIEF_PROMPT_LAST = [("스페이스바 또는 클릭: 보정 시작", "bold", 32, _PINK, 8),
                      ("SPACE or click: start calibrating", "bold", 26, _PINK, 52)]


def _first(paths: tuple[str, ...]) -> Optional[str]:
    return next((p for p in paths if Path(p).exists()), None)


class _Frame:
    """One window size: the 1280x720 design scaled to fit, centred."""

    def __init__(self, size: tuple[int, int]) -> None:
        w, h = size
        self.w, self.h = max(int(w), 320), max(int(h), 180)
        self.s = min(self.w / DASH_W, self.h / DASH_H)
        self.ox = (self.w - DASH_W * self.s) / 2.0
        self.oy = (self.h - DASH_H * self.s) / 2.0

    def x(self, v: float) -> int:
        return int(round(self.ox + v * self.s))

    def y(self, v: float) -> int:
        return int(round(self.oy + v * self.s))

    def n(self, v: float) -> int:
        return max(1, int(round(v * self.s)))


class Screens:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        try:
            from PIL import ImageFont  # noqa: F401
            self._pil = True
        except ImportError:
            self._pil = False
        self._bold = _first(FONTS_BOLD) if self._pil else None
        self._regular = _first(FONTS_REGULAR) if self._pil else None
        self.korean = self._bold is not None and self._regular is not None
        if not self.korean:
            log.warning("no Korean font (sudo apt install fonts-nanum); booth screens in English only")
        self._fonts: dict[tuple[str, int], object] = {}
        self._owls: dict[tuple[str, int], Optional[np.ndarray]] = {}
        self._cache: dict[tuple, object] = {}

    # -- drawing helpers ---------------------------------------------------- #

    def _font(self, kind: str, px: int):
        from PIL import ImageFont

        key = (kind, px)
        if key not in self._fonts:
            self._fonts[key] = ImageFont.truetype(self._bold if kind == "bold" else self._regular, px)
        return self._fonts[key]

    def _owl(self, name: str, height: int) -> Optional[np.ndarray]:
        key = (name, height)
        if key not in self._owls:
            import cv2

            img = cv2.imread(str(self.root / "frontend" / "ollie" / f"{name}.webp"), cv2.IMREAD_UNCHANGED)
            if img is not None and img.ndim == 3 and img.shape[2] == 4:
                w = int(img.shape[1] * height / img.shape[0])
                img = cv2.resize(img, (w, height),
                                 interpolation=cv2.INTER_AREA if height < img.shape[0] else cv2.INTER_CUBIC)
            else:
                img = None
            self._owls[key] = img
        return self._owls[key]

    @staticmethod
    def _paste(canvas: np.ndarray, rgba: np.ndarray, cx: int, top: int) -> None:
        h, w = rgba.shape[:2]
        H, W = canvas.shape[:2]
        x0 = cx - w // 2
        x1, y1 = min(W, x0 + w), min(H, top + h)
        x0c, y0c = max(0, x0), max(0, top)
        src = rgba[y0c - top:y1 - top, x0c - x0:x1 - x0]
        a = src[:, :, 3:4].astype(np.float32) / 255.0
        dst = canvas[y0c:y1, x0c:x1]
        dst[:] = (src[:, :, :3] * a + dst * (1.0 - a)).astype(np.uint8)

    def _text(self, canvas: np.ndarray, f: _Frame, lines, top: float = 0.0) -> np.ndarray:
        """Centred lines (text, 'bold'|'regular', size, BGR, y), in design
        units from ``top``. A line too wide for the screen gets smaller.
        Korean lines are left out when there's no Korean font."""
        max_w = DASH_W * 0.92 * f.s
        if self._pil and self.korean:
            from PIL import Image, ImageDraw

            img = Image.fromarray(canvas[:, :, ::-1])
            d = ImageDraw.Draw(img)
            for text, kind, size, colour, y in lines:
                px = f.n(size)
                font = self._font(kind, px)
                w = d.textlength(text, font=font)
                if w > max_w:
                    px = max(8, int(px * max_w / w))
                    font = self._font(kind, px)
                    w = d.textlength(text, font=font)
                d.text(((f.w - w) / 2, f.y(top + y)), text, font=font, fill=colour[::-1])
            return np.asarray(img)[:, :, ::-1].copy()
        import cv2

        for text, kind, size, colour, y in lines:
            if any(ord(ch) > 0x2FFF for ch in text):
                continue
            scale, thick = size * f.s / 34.0, 2 if kind == "bold" else 1
            (w, _h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
            if w > max_w:
                scale *= max_w / w
                (w, _h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
            cv2.putText(canvas, text, (int((f.w - w) / 2), f.y(top + y + size)),
                        cv2.FONT_HERSHEY_SIMPLEX, scale, colour, thick, cv2.LINE_AA)
        return canvas

    @staticmethod
    def _background(f: _Frame) -> np.ndarray:
        """The app's night-sky gradient: a lavender glow from the top."""
        yy, xx = np.mgrid[0:f.h, 0:f.w].astype(np.float32)
        glow = np.exp(-(((xx - f.w / 2) / (f.w * 0.6)) ** 2 + (yy / (f.h * 0.75)) ** 2))
        base = np.array(_BG, np.float32)
        tint = np.array((232, 132, 168), np.float32)            # BGR lavender
        return (base + glow[..., None] * (tint - base) * 0.35).clip(0, 255).astype(np.uint8)

    # -- the screens --------------------------------------------------------- #

    def standby(self, t: float, camera: Optional[np.ndarray] = None,
                size: tuple[int, int] = (DASH_W, DASH_H)) -> np.ndarray:
        """Nobody at the wheel: invite the next visitor."""
        f = _Frame(size)
        key = ("standby", f.w, f.h)
        if key not in self._cache:
            c = self._background(f)
            name, height, top = _STANDBY["owl"]
            owl = self._owl(name, f.n(height))
            if owl is not None:
                self._paste(c, owl, f.w // 2, f.y(top))
            self._cache[key] = self._text(c, f, _STANDBY["lines"])
        canvas = self._cache[key].copy()
        self._prompt(canvas, f, t, _STANDBY_PROMPT)
        if camera is not None:
            self._thumbnail(canvas, f, camera)
        return canvas

    def briefing(self, step: int, t: float, size: tuple[int, int] = (DASH_W, DASH_H)) -> np.ndarray:
        """One page of the briefing, with progress dots."""
        f = _Frame(size)
        step = max(0, min(step, len(STEPS) - 1))
        key = ("brief", step, f.w, f.h)
        if key not in self._cache:
            owl_name, ko_title, en_title, ko_line, en_line = STEPS[step]
            c = self._background(f)
            owl = self._owl(owl_name, f.n(200))
            if owl is not None:
                self._paste(c, owl, f.w // 2, f.y(30))
            c = self._text(c, f, [
                (ko_title, "bold", 58, _ACCENT, 248),
                (en_title, "bold", 42, _INK, 324),
                (ko_line, "regular", 32, _INK, 396),
                (en_line, "regular", 27, _MUTED, 446),
            ])
            import cv2

            n = len(STEPS)
            for i in range(n):
                cx = f.x(DASH_W / 2 + (i - (n - 1) / 2) * 34)
                cv2.circle(c, (cx, f.y(536)), f.n(8 if i == step else 6),
                           _INK if i == step else (90, 80, 90), -1, cv2.LINE_AA)
            self._cache[key] = c
        canvas = self._cache[key].copy()
        last = step == len(STEPS) - 1
        self._prompt(canvas, f, t, _BRIEF_PROMPT_LAST if last else _BRIEF_PROMPT)
        return canvas

    def _prompt(self, canvas: np.ndarray, f: _Frame, t: float, lines) -> None:
        """The pulsing lines near the bottom."""
        key = ("prompt", lines[0][0], f.w, f.h)
        if key not in self._cache:
            band = self._text(np.full((f.h, f.w, 3), _BG, np.uint8), f, lines, top=_PROMPT_TOP)
            y0, y1 = f.y(_PROMPT_TOP), min(f.h, f.y(_PROMPT_TOP + _PROMPT_H))
            strip = band[y0:y1].copy()
            mask = (strip.astype(np.int16) - np.array(_BG, np.int16)).any(axis=2)
            self._cache[key] = (y0, y1, strip, mask)
        y0, y1, strip, mask = self._cache[key]
        a = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(t * 3.0))
        region = canvas[y0:y1]
        region[mask] = (strip[mask] * a + region[mask] * (1 - a)).astype(np.uint8)

    @staticmethod
    def _thumbnail(canvas: np.ndarray, f: _Frame, camera: np.ndarray) -> None:
        """The live camera, small, top right: people see themselves."""
        import cv2

        w = f.n(240)
        h = int(camera.shape[0] * w / camera.shape[1])
        thumb = cv2.resize(camera, (w, h), interpolation=cv2.INTER_AREA)
        if thumb.ndim == 2:
            thumb = cv2.cvtColor(thumb, cv2.COLOR_GRAY2BGR)
        x, y = f.x(DASH_W - 20) - w, f.y(20)
        canvas[y:y + h, x:x + w] = thumb
        cv2.rectangle(canvas, (x - 1, y - 1), (x + w, y + h), (120, 110, 120), 1)
