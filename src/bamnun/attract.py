"""The booth's own screens: standby (nobody at the wheel), the visitor
briefing (space or a click), and calibration (look at the game screen).

The look follows a plain lecture slide: a light grey panel on the left with
one picture (Ollie, gently moving, or the game's Drive button), a charcoal
panel on the right with white serif text, the title in a thin white box.
Korean comes first, English under it.

They are drawn at the window's own size (stretched text went soft), laid
out in 1280x720 units. OpenCV's fonts have no Korean, so text goes through
Pillow with a Korean font (fonts-nanum on the Pi, installed by
setup_pi.sh); without one only the English is shown, never boxes. The
static parts are drawn once per window size and kept; a frame adds only
what moves.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Optional

import numpy as np

from .viz import DASH_H, DASH_W

log = logging.getLogger("bamnun.attract")

FONTS_BOLD = ("/usr/share/fonts/truetype/nanum/NanumMyeongjoBold.ttf",
              "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
              "/System/Library/Fonts/Supplemental/AppleMyungjo.ttf",
              "/System/Library/Fonts/AppleSDGothicNeo.ttc")
FONTS_REGULAR = ("/usr/share/fonts/truetype/nanum/NanumMyeongjo.ttf",
                 "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
                 "/System/Library/Fonts/Supplemental/AppleMyungjo.ttf",
                 "/System/Library/Fonts/AppleSDGothicNeo.ttc")

# Three colours and white: nothing else.
_PANEL = (230, 230, 228)     # the light left panel (BGR)
_BOARD = (40, 40, 42)        # the charcoal right panel
_WHITE = (245, 245, 245)
_GREY = (170, 170, 170)

_SPLIT = 560                 # left panel width, in design units
_CX = (_SPLIT + DASH_W) / 2  # centre of the text panel
_TEXT_W = DASH_W - _SPLIT - 70

# (picture, Korean title, English title, Korean line, English line).
# "game" is the game's own screen with an arrow at Drive.
STEPS = [
    ("hello", "안녕하세요, 저는 올리예요", "Hi, I'm Ollie",
     "운전하는 동안 눈을 지켜보고, 졸면 깨워 줘요.",
     "I watch your eyes while you drive, and wake you if you doze."),
    ("driving", "핸들 앞에 앉으세요", "Sit at the wheel",
     "왼쪽 카메라 말고, 오른쪽 게임 화면을 보세요.",
     "Look at the game screen on the right, not the camera."),
    ("game", "게임에서 Drive를 누르세요", "Click Drive in the game",
     "게임 화면 왼쪽 아래의 Drive 버튼을 누르면 출발해요.",
     "The Drive button is at the bottom left of the game screen."),
    ("thinking", "15초 동안 눈을 익혀요", "15 seconds to learn your eyes",
     "게임 화면을 보며 평소처럼 눈을 깜빡이세요.",
     "Look at the game screen and blink normally."),
    ("sleepy", "졸린 척 해 보세요", "Then try being sleepy",
     "2초 동안 눈을 감거나, 고개를 떨구거나, 화면에서 눈을 떼 보세요.",
     "Close your eyes for 2 s, let your head nod, or look away."),
    ("wake", "네 단계로 깨워요", "Four steps to wake you",
     "파란 불빛, 민트 미스트, 차임과 목소리, 점점 커지는 알람.",
     "Blue light, mint mist, chime and voice, rising alarm."),
]

# The calibrator's live hints (eyes.Calibrator), in both languages.
HINTS = {"no_face": ("얼굴이 보이지 않아요", "Can't see your face"),
         "closer": ("조금 더 가까이 오세요", "Move a little closer"),
         "farther": ("조금 뒤로 가세요", "Move back a little"),
         "dark": ("너무 어두워요", "Too dark"),
         "bright": ("너무 밝아요", "Too bright"),
         "face_camera": ("고개를 조금만 카메라 쪽으로", "Turn a little towards the camera"),
         "still": ("움직이지 마세요", "Hold still")}

# The Drive button in assets/booth/game_drive.jpg (1600 x 999 pixels).
_DRIVE_AT = (326, 915)


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
        self._images: dict[tuple, Optional[np.ndarray]] = {}
        self._cache: dict[tuple, object] = {}

    # -- pieces -------------------------------------------------------------- #

    def _font(self, kind: str, px: int):
        from PIL import ImageFont

        key = (kind, px)
        if key not in self._fonts:
            self._fonts[key] = ImageFont.truetype(self._bold if kind == "bold" else self._regular, px)
        return self._fonts[key]

    def _owl(self, name: str, height: int) -> Optional[np.ndarray]:
        key = ("owl", name, height)
        if key not in self._images:
            import cv2

            img = cv2.imread(str(self.root / "frontend" / "ollie" / f"{name}.webp"), cv2.IMREAD_UNCHANGED)
            if img is not None and img.ndim == 3 and img.shape[2] == 4:
                w = int(img.shape[1] * height / img.shape[0])
                img = cv2.resize(img, (w, height),
                                 interpolation=cv2.INTER_AREA if height < img.shape[0] else cv2.INTER_CUBIC)
                # Room to sway without clipping the wings.
                pad = height // 8
                img = cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(0, 0, 0, 0))
            else:
                img = None
            self._images[key] = img
        return self._images[key]

    @staticmethod
    def _paste(canvas: np.ndarray, rgba: np.ndarray, cx: int, cy: int) -> None:
        """Alpha-blend ``rgba`` centred on (cx, cy)."""
        h, w = rgba.shape[:2]
        H, W = canvas.shape[:2]
        x0, top = cx - w // 2, cy - h // 2
        x1, y1 = min(W, x0 + w), min(H, top + h)
        x0c, y0c = max(0, x0), max(0, top)
        if x1 <= x0c or y1 <= y0c:
            return
        src = rgba[y0c - top:y1 - top, x0c - x0:x1 - x0]
        a = src[:, :, 3:4].astype(np.float32) / 255.0
        dst = canvas[y0c:y1, x0c:x1]
        dst[:] = (src[:, :, :3] * a + dst * (1.0 - a)).astype(np.uint8)

    def _draw_owl(self, canvas: np.ndarray, f: _Frame, name: str, t: float,
                  height: float = 300, cy: float = 330) -> None:
        """Ollie breathing: a slow bob and a slight sway."""
        import cv2

        owl = self._owl(name, f.n(height))
        if owl is None:
            return
        angle = 3.5 * math.sin(t * 1.6)
        h, w = owl.shape[:2]
        m = cv2.getRotationMatrix2D((w / 2, h * 0.85), angle, 1.0 + 0.015 * math.sin(t * 3.2))
        moved = cv2.warpAffine(owl, m, (w, h), flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
        self._paste(canvas, moved, f.x(_SPLIT / 2), f.y(cy + 10 * math.sin(t * 2.2)))

    def _game(self, f: _Frame) -> Optional[np.ndarray]:
        """The game's screen, fitted to the left panel, Drive circled."""
        key = ("game", f.w, f.h)
        if key not in self._images:
            import cv2

            img = cv2.imread(str(self.root / "assets" / "booth" / "game_drive.jpg"))
            if img is not None:
                w = f.n(_SPLIT - 40)
                h = int(img.shape[0] * w / img.shape[1])
                k = w / img.shape[1]
                img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
                cx, cy = int(_DRIVE_AT[0] * k), int(_DRIVE_AT[1] * k)
                cv2.circle(img, (cx, cy), f.n(40), (0, 0, 0), f.n(7), cv2.LINE_AA)
                cv2.circle(img, (cx, cy), f.n(40), (255, 255, 255), f.n(3), cv2.LINE_AA)
                img = (img, cx, cy)
            self._images[key] = img
        return self._images[key]

    def _draw_game(self, canvas: np.ndarray, f: _Frame, t: float) -> None:
        import cv2

        got = self._game(f)
        if got is None:
            return
        img, cx, cy = got
        h, w = img.shape[:2]
        x0, y0 = f.x(20), f.y(360) - h // 2
        canvas[y0:y0 + h, x0:x0 + w] = img
        cv2.rectangle(canvas, (x0 - 1, y0 - 1), (x0 + w, y0 + h), (90, 90, 90), 1)
        # A thick arrow coming down onto Drive, nudging towards it.
        bob = f.n(14) * (0.5 + 0.5 * math.sin(t * 4.0))
        tip = (x0 + cx, int(y0 + cy - f.n(48) - bob))
        tail = (tip[0] + f.n(70), tip[1] - f.n(120))
        cv2.arrowedLine(canvas, tail, tip, (0, 0, 0), f.n(16), cv2.LINE_AA, tipLength=0.35)
        cv2.arrowedLine(canvas, tail, tip, (255, 255, 255), f.n(9), cv2.LINE_AA, tipLength=0.35)

    def _text(self, canvas: np.ndarray, f: _Frame, lines, cx: float = _CX,
              max_w: float = _TEXT_W) -> tuple[np.ndarray, list[tuple[int, int]]]:
        """Centred lines (text, 'bold'|'regular', size, BGR, y) in design
        units. A line too wide shrinks. Korean lines are left out with no
        Korean font. Returns the canvas and each line's (top, bottom)."""
        spans: list[tuple[int, int]] = []
        mw = max_w * f.s
        if self._pil and self.korean:
            from PIL import Image, ImageDraw

            img = Image.fromarray(canvas[:, :, ::-1])
            d = ImageDraw.Draw(img)
            for text, kind, size, colour, y in lines:
                px = f.n(size)
                font = self._font(kind, px)
                w = d.textlength(text, font=font)
                if w > mw:
                    px = max(8, int(px * mw / w))
                    font = self._font(kind, px)
                    w = d.textlength(text, font=font)
                top = f.y(y)
                d.text((f.x(cx) - w / 2, top), text, font=font, fill=colour[::-1])
                spans.append((top, top + px))
            return np.asarray(img)[:, :, ::-1].copy(), spans
        import cv2

        for text, kind, size, colour, y in lines:
            if any(ord(ch) > 0x2FFF for ch in text):
                continue
            scale, thick = size * f.s / 34.0, 2 if kind == "bold" else 1
            (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
            if w > mw:
                scale *= mw / w
                (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
            cv2.putText(canvas, text, (int(f.x(cx) - w / 2), f.y(y) + h), cv2.FONT_HERSHEY_SIMPLEX,
                        scale, colour, thick, cv2.LINE_AA)
            spans.append((f.y(y), f.y(y) + h))
        return canvas, spans

    def _base(self, f: _Frame) -> np.ndarray:
        """Grey panel left, charcoal right."""
        c = np.empty((f.h, f.w, 3), np.uint8)
        c[:] = _BOARD
        c[:, :f.x(_SPLIT)] = _PANEL
        return c

    def _titled(self, f: _Frame, ko: str, en: str, body: list[tuple[str, str]],
                title_y: float = 150) -> np.ndarray:
        """The right panel: a title in a thin box, then body lines."""
        import cv2

        c = self._base(f)
        lines = [(ko, "bold", 50, _WHITE, title_y), (en, "regular", 32, _GREY, title_y + 70)]
        y = title_y + 160
        for k, e in body:
            lines += [(k, "regular", 30, _WHITE, y), (e, "regular", 24, _GREY, y + 42)]
            y += 100
        c, spans = self._text(c, f, lines)
        if spans:
            top, bottom = spans[0][0], spans[min(1, len(spans) - 1)][1]
            pad = f.n(26)
            cv2.rectangle(c, (f.x(_SPLIT + 40), top - pad), (f.x(DASH_W - 40), bottom + pad),
                          _WHITE, max(1, f.n(1.5)), cv2.LINE_AA)
        return c

    def _prompt(self, canvas: np.ndarray, f: _Frame, t: float, ko: str, en: str, y: float = 600) -> None:
        """The pulsing lines at the foot of the text panel."""
        key = ("prompt", ko, f.w, f.h)
        if key not in self._cache:
            band, _ = self._text(self._base(f), f, [(ko, "bold", 30, _WHITE, y), (en, "regular", 22, _GREY, y + 44)])
            y0, y1 = f.y(y - 6), min(f.h, f.y(y + 80))
            x0 = f.x(_SPLIT)
            strip = band[y0:y1, x0:].copy()
            mask = (strip.astype(np.int16) - np.array(_BOARD, np.int16)).any(axis=2)
            self._cache[key] = (y0, y1, x0, strip, mask)
        y0, y1, x0, strip, mask = self._cache[key]
        a = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(t * 3.0))
        region = canvas[y0:y1, x0:]
        region[mask] = (strip[mask] * a + region[mask] * (1 - a)).astype(np.uint8)

    # -- the screens --------------------------------------------------------- #

    def standby(self, t: float, camera: Optional[np.ndarray] = None,
                size: tuple[int, int] = (DASH_W, DASH_H)) -> np.ndarray:
        """Nobody at the wheel: invite the next visitor."""
        f = _Frame(size)
        key = ("standby", f.w, f.h)
        if key not in self._cache:
            self._cache[key] = self._titled(f, "여기 앉아서 체험해 보세요", "Sit here and try Bamnun",
                                            [("야간 운전자를 위한 졸음 지킴이, 밤눈",
                                              "Bamnun, a drowsiness co-pilot for night drivers")])
        canvas = self._cache[key].copy()
        if camera is not None:            # Ollie up top, the camera big below him
            self._draw_owl(canvas, f, "hello", t, height=210, cy=165)
            self._thumbnail(canvas, f, camera)
        else:
            self._draw_owl(canvas, f, "hello", t)
        self._prompt(canvas, f, t, "스페이스바를 누르거나 클릭하세요", "Press SPACE or click to start")
        return canvas

    def briefing(self, step: int, t: float, size: tuple[int, int] = (DASH_W, DASH_H)) -> np.ndarray:
        """One page of the briefing, with progress dots."""
        import cv2

        f = _Frame(size)
        step = max(0, min(step, len(STEPS) - 1))
        pic, ko_title, en_title, ko_line, en_line = STEPS[step]
        key = ("brief", step, f.w, f.h)
        if key not in self._cache:
            c = self._titled(f, ko_title, en_title, [(ko_line, en_line)])
            n = len(STEPS)
            for i in range(n):
                cx = f.x(_CX + (i - (n - 1) / 2) * 30)
                cv2.circle(c, (cx, f.y(548)), f.n(7 if i == step else 5),
                           _WHITE if i == step else (95, 95, 95), -1, cv2.LINE_AA)
            self._cache[key] = c
        canvas = self._cache[key].copy()
        if pic == "game":
            self._draw_game(canvas, f, t)
        else:
            self._draw_owl(canvas, f, pic, t)
        if step == len(STEPS) - 1:
            self._prompt(canvas, f, t, "스페이스바 또는 클릭: 보정 시작", "SPACE or click: start calibrating")
        else:
            self._prompt(canvas, f, t, "스페이스바 또는 클릭: 다음", "SPACE or click: next")
        return canvas

    def calibrating(self, t: float, progress: float, hint: str = "",
                    size: tuple[int, int] = (DASH_W, DASH_H)) -> np.ndarray:
        """Calibration: look at the game screen (to the right), blink normally."""
        import cv2

        f = _Frame(size)
        key = ("calibrating", f.w, f.h)
        if key not in self._cache:
            self._cache[key] = self._titled(f, "게임 화면을 보세요", "Look at the game screen",
                                            [("평소처럼 눈을 깜빡이세요", "Blink normally")], title_y=110)
        canvas = self._cache[key].copy()
        self._draw_owl(canvas, f, "thinking", t)
        # The big arrow, sliding to the right, towards the game.
        slide = (0.5 + 0.5 * math.sin(t * 3.0)) * 60
        y = f.y(430)
        x0, x1 = f.x(_SPLIT + 130 + slide), f.x(DASH_W - 150 + slide)
        cv2.arrowedLine(canvas, (x0, y), (x1, y), _WHITE, f.n(22), cv2.LINE_AA, tipLength=0.28)
        # Progress, thin and white.
        bx0, bx1, by = f.x(_SPLIT + 60), f.x(DASH_W - 60), f.y(540)
        cv2.rectangle(canvas, (bx0, by), (bx1, by + f.n(10)), (95, 95, 95), -1)
        cv2.rectangle(canvas, (bx0, by), (int(bx0 + (bx1 - bx0) * max(0.0, min(1.0, progress))),
                                          by + f.n(10)), _WHITE, -1)
        if hint in HINTS:
            ko, en = HINTS[hint]
            key = ("hint", hint, f.w, f.h)
            if key not in self._cache:
                band, _ = self._text(self._base(f), f, [(ko, "bold", 30, _WHITE, 590), (en, "regular", 22, _GREY, 634)])
                y0, y1, xs = f.y(584), min(f.h, f.y(670)), f.x(_SPLIT)
                self._cache[key] = (y0, y1, xs, band[y0:y1, xs:].copy())
            y0, y1, xs, strip = self._cache[key]
            canvas[y0:y1, xs:] = strip
        return canvas

    @staticmethod
    def _thumbnail(canvas: np.ndarray, f: _Frame, camera: np.ndarray) -> None:
        """The live camera across the grey panel: people see themselves, and
        the face mesh the tracker draws on them."""
        import cv2

        w = f.n(_SPLIT - 60)
        h = int(camera.shape[0] * w / camera.shape[1])
        if h > f.n(DASH_H - 330):                 # a tall camera: fit the height instead
            h = f.n(DASH_H - 330)
            w = int(camera.shape[1] * h / camera.shape[0])
        thumb = cv2.resize(camera, (w, h), interpolation=cv2.INTER_AREA)
        if thumb.ndim == 2:
            thumb = cv2.cvtColor(thumb, cv2.COLOR_GRAY2BGR)
        x, y = f.x(_SPLIT / 2) - w // 2, f.y(310)
        canvas[y:y + h, x:x + w] = thumb
        cv2.rectangle(canvas, (x - 1, y - 1), (x + w, y + h), (120, 120, 120), 1)
