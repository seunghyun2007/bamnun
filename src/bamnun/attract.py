"""The booth's own screens: standby, when nobody is at the wheel, and the quick
briefing that a visitor starts with the space bar (or a click).

Both are drawn on the dashboard's 1280x720 canvas (viz.DASH_W, DASH_H), so
the window fits them the same way. Text is in English and Korean; OpenCV's
fonts have no Korean, so the text goes through Pillow with a Korean font
(fonts-nanum on the Pi, installed by setup_pi.sh). Without one, only the
English is shown, never boxes.

The static parts of each screen are drawn once and kept; a frame only adds
the live camera thumbnail and the blinking prompt.
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

# (Ollie, English title, Korean title, English line, Korean line)
STEPS = [
    ("hello", "Hi, I'm Ollie", "안녕하세요, 저는 올리예요",
     "Bamnun watches your eyes while you drive, and wakes you before it's too late.",
     "밤눈은 운전하는 동안 눈을 지켜보고, 너무 늦기 전에 깨워 줘요."),
    ("driving", "Sit at the wheel", "핸들 앞에 앉으세요",
     "Look at the road on the screen, not at the camera on your left.",
     "왼쪽의 카메라 말고 화면 속 도로를 보세요."),
    ("thinking", "First, 15 seconds to learn your eyes", "먼저 15초 동안 눈을 익혀요",
     "Keep looking at the road and blink normally. Ollie learns how your eyes look open.",
     "도로를 보며 평소처럼 눈을 깜빡이세요. 올리가 눈을 뜬 모습을 익혀요."),
    ("sleepy", "Then try being sleepy", "그다음 졸린 척 해 보세요",
     "Close your eyes for 2 seconds, let your head nod, or look away from the road.",
     "2초 동안 눈을 감거나, 고개를 떨구거나, 도로에서 눈을 떼 보세요."),
    ("wake", "Bamnun wakes you in four steps", "밤눈은 네 단계로 깨워요",
     "Blue light, then mint mist, then a chime and Ollie's voice, then a rising alarm.",
     "파란 불빛, 민트 미스트, 차임과 올리의 목소리, 그리고 점점 커지는 알람."),
]


def _first(paths: tuple[str, ...]) -> Optional[str]:
    return next((p for p in paths if Path(p).exists()), None)


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
        self._owls: dict[str, Optional[np.ndarray]] = {}
        self._cache: dict[str, np.ndarray] = {}

    # -- drawing helpers ---------------------------------------------------- #

    def _font(self, kind: str, size: int):
        from PIL import ImageFont

        key = (kind, size)
        if key not in self._fonts:
            self._fonts[key] = ImageFont.truetype(self._bold if kind == "bold" else self._regular, size)
        return self._fonts[key]

    def _owl(self, name: str, height: int) -> Optional[np.ndarray]:
        key = f"{name}@{height}"
        if key not in self._owls:
            import cv2

            img = cv2.imread(str(self.root / "frontend" / "ollie" / f"{name}.webp"), cv2.IMREAD_UNCHANGED)
            if img is not None and img.ndim == 3 and img.shape[2] == 4:
                w = int(img.shape[1] * height / img.shape[0])
                img = cv2.resize(img, (w, height), interpolation=cv2.INTER_AREA)
            else:
                img = None
            self._owls[key] = img
        return self._owls[key]

    @staticmethod
    def _paste(canvas: np.ndarray, rgba: np.ndarray, cx: int, top: int) -> None:
        h, w = rgba.shape[:2]
        x0 = cx - w // 2
        x1, y1 = min(DASH_W, x0 + w), min(DASH_H, top + h)
        x0c, y0c = max(0, x0), max(0, top)
        src = rgba[y0c - top:y1 - top, x0c - x0:x1 - x0]
        a = src[:, :, 3:4].astype(np.float32) / 255.0
        dst = canvas[y0c:y1, x0c:x1]
        dst[:] = (src[:, :, :3] * a + dst * (1.0 - a)).astype(np.uint8)

    def _text(self, canvas: np.ndarray, lines: list[tuple[str, str, int, tuple, int]]) -> np.ndarray:
        """Draw centred lines: (text, 'bold'|'regular', size, BGR colour, y).
        Korean lines are dropped when there's no Korean font."""
        if self._pil and self.korean:
            from PIL import Image, ImageDraw

            img = Image.fromarray(canvas[:, :, ::-1])
            d = ImageDraw.Draw(img)
            for text, kind, size, colour, y in lines:
                font = self._font(kind, size)
                w = d.textlength(text, font=font)
                d.text(((DASH_W - w) / 2, y), text, font=font, fill=colour[::-1])
            return np.asarray(img)[:, :, ::-1].copy()
        import cv2

        for text, kind, size, colour, y in lines:
            if any(ord(ch) > 0x2FFF for ch in text):
                continue
            scale = size / 34.0
            thick = 2 if kind == "bold" else 1
            (w, _h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
            cv2.putText(canvas, text, ((DASH_W - w) // 2, y + size), cv2.FONT_HERSHEY_SIMPLEX,
                        scale, colour, thick, cv2.LINE_AA)
        return canvas

    @staticmethod
    def _background() -> np.ndarray:
        """The app's night-sky gradient: a lavender glow from the top."""
        yy, xx = np.mgrid[0:DASH_H, 0:DASH_W].astype(np.float32)
        glow = np.exp(-(((xx - DASH_W / 2) / (DASH_W * 0.6)) ** 2 + (yy / (DASH_H * 0.75)) ** 2))
        base = np.array(_BG, np.float32)
        tint = np.array((232, 132, 168), np.float32)            # BGR lavender
        img = base + glow[..., None] * (tint - base) * 0.35
        return img.clip(0, 255).astype(np.uint8)

    # -- the screens --------------------------------------------------------- #

    def standby(self, t: float, camera: Optional[np.ndarray] = None) -> np.ndarray:
        """Nobody at the wheel: invite the next visitor."""
        if "standby" not in self._cache:
            c = self._background()
            owl = self._owl("hello", 250)
            if owl is not None:
                self._paste(c, owl, DASH_W // 2, 70)
            self._cache["standby"] = self._text(c, [
                ("Sit here and try Bamnun!", "bold", 54, _INK, 345),
                ("여기 앉아서 밤눈을 체험해 보세요!", "bold", 44, _ACCENT, 415),
                ("A drowsiness co-pilot for drivers at night · 야간 운전자를 위한 졸음 지킴이",
                 "regular", 24, _MUTED, 482),
            ])
        canvas = self._cache["standby"].copy()
        self._prompt(canvas, t, "standby_prompt", "Press SPACE or click to start   ·   스페이스바를 누르거나 클릭하세요")
        if camera is not None:
            self._thumbnail(canvas, camera)
        return canvas

    def briefing(self, step: int, t: float) -> np.ndarray:
        """One page of the briefing, with progress dots."""
        step = max(0, min(step, len(STEPS) - 1))
        key = f"brief{step}"
        if key not in self._cache:
            owl_name, en_title, ko_title, en_line, ko_line = STEPS[step]
            c = self._background()
            owl = self._owl(owl_name, 230)
            if owl is not None:
                self._paste(c, owl, DASH_W // 2, 60)
            c = self._text(c, [
                (en_title, "bold", 50, _INK, 318),
                (ko_title, "bold", 40, _ACCENT, 384),
                (en_line, "regular", 26, _INK, 456),
                (ko_line, "regular", 26, _MUTED, 498),
            ])
            import cv2

            n = len(STEPS)
            for i in range(n):
                x = DASH_W // 2 + (i - (n - 1) / 2) * 30
                cv2.circle(c, (int(x), 580), 7 if i == step else 5,
                           _INK if i == step else (90, 80, 90), -1, cv2.LINE_AA)
            self._cache[key] = c
        canvas = self._cache[key].copy()
        last = step == len(STEPS) - 1
        self._prompt(canvas, t, "brief_prompt_last" if last else "brief_prompt",
                     "SPACE or click: start calibrating   ·   스페이스바 또는 클릭: 보정 시작" if last
                     else "SPACE or click: next   ·   스페이스바 또는 클릭: 다음")
        return canvas

    def _prompt(self, canvas: np.ndarray, t: float, key: str, text: str) -> None:
        """A gently pulsing line near the bottom."""
        if key not in self._cache:
            band = self._text(np.full((DASH_H, DASH_W, 3), _BG, np.uint8),
                              [(text, "bold", 26, _PINK, 625)])
            self._cache[key] = band[615:675].copy()
        strip = self._cache[key]
        mkey = key + "_mask"
        if mkey not in self._cache:
            self._cache[mkey] = (strip.astype(np.int16) - np.array(_BG, np.int16)).any(axis=2)
        mask = self._cache[mkey]
        a = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(t * 3.0))
        region = canvas[615:675]
        region[mask] = (strip[mask] * a + region[mask] * (1 - a)).astype(np.uint8)

    @staticmethod
    def _thumbnail(canvas: np.ndarray, camera: np.ndarray) -> None:
        """The live camera, small, top right: people see themselves."""
        import cv2

        w = 240
        h = int(camera.shape[0] * w / camera.shape[1])
        thumb = cv2.resize(camera, (w, h), interpolation=cv2.INTER_AREA)
        if thumb.ndim == 2:
            thumb = cv2.cvtColor(thumb, cv2.COLOR_GRAY2BGR)
        x, y = DASH_W - w - 20, 20
        canvas[y:y + h, x:x + w] = thumb
        cv2.rectangle(canvas, (x - 1, y - 1), (x + w, y + h), (120, 110, 120), 1)
