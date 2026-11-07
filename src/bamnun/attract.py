"""The booth's own screens: standby (nobody at the wheel), the visitor
briefing (space or a click), calibration (look at the game screen), and
"learn more": a small pop-up on the dashboard after a visitor has driven a
while, which opens a QR code for the website.

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
    ("center", "카메라에 얼굴을 맞추세요", "Line your face up with the camera",
     "타원이 초록색이 되게 얼굴을 맞추세요.",
     "Move until the oval turns green."),
    ("game", "게임에서 Drive를 누르세요", "Click Drive in the game",
     "게임 화면 왼쪽 아래의 Drive 버튼을 누르면 출발해요.",
     "The Drive button is at the bottom left of the game screen."),
    ("thinking", "15초 동안 눈을 익혀요", "15 seconds to learn your eyes",
     "게임 화면을 보며 평소처럼 눈을 깜빡이세요.",
     "Look at the game screen and blink normally."),
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

# The "learn more" pop-up on the dashboard (1280x720 units): over the camera's
# top-right corner, clear of the face and of the buttons along its bottom.
POPUP = (318, 18, 512, 184)                   # x, y, w, h
# The two cards that use it: "learn more" (a button), and the tip a while into
# a drive to try being sleepy (the dark box is just the instruction).
POPUP_WORDS = {
    "learn": ("밤눈이 궁금하세요?", "Want to learn more about Bamnun?", "QR 코드 보기  ·  Learn more"),
    "sleepy": ("이제 졸린 척 해 보세요", "Now try being sleepy", "눈을 2초 감기  ·  Close your eyes 2 s"),
}
_POPUP_TEXT_X = 150                           # Ollie to the left of this
POPUP_BUTTON = (POPUP[0] + 168, POPUP[1] + 116, 318, 50)
POPUP_CLOSE = (POPUP[0] + POPUP[2] - 48, POPUP[1], 48, 48)


# The learn-more screen's stage cards (1280x720 units): 2 x 2 on the right.
STAGE_CARDS = {
    1: ("파란 불빛", "Blue light", "조금 졸릴 때: 은은한 파란 빛", "A little sleepy: a soft blue glow"),
    2: ("민트 미스트", "Mint mist", "더 졸릴 때: 시원한 민트 향", "Sleepier: a cool puff of mint"),
    3: ("차임과 음성", "Chime and voice", "많이 졸릴 때: 올리가 말해요", "Very sleepy: Ollie speaks up"),
    4: ("알람", "Alarm", "눈을 감았을 때: 커지는 알람", "Eyes shut: a rising alarm"),
}
QR_BACK = (1060, 650, 180, 46)
# The visitor's yes / no under their photo (left panel).
VISIT_BUTTONS = {"visit_yes": (60, 450, 210, 70), "visit_no": (290, 450, 210, 70)}


def _card_rect(n: int) -> tuple[int, int, int, int]:
    w, h, gap = 310, 160, 20
    x0, y0 = _SPLIT + 40, 168
    col, row = (n - 1) % 2, (n - 1) // 2
    return x0 + col * (w + gap), y0 + row * (h + gap), w, h


def learn_hit(x: int, y: int, size: tuple[int, int], asking: bool = False) -> Optional[str]:
    """A click at window (x, y) on the learn-more screen: "stage1".."stage4",
    "qr_back", "visit_yes" / "visit_no" (while ``asking``), or None."""
    f = _Frame(size)
    u, v = (x - f.ox) / f.s, (y - f.oy) / f.s
    def inside(r) -> bool:
        return r[0] <= u < r[0] + r[2] and r[1] <= v < r[1] + r[3]
    for n in STAGE_CARDS:
        if inside(_card_rect(n)):
            return f"stage{n}"
    if asking:
        for name, r in VISIT_BUTTONS.items():
            if inside(r):
                return name
    return "qr_back" if inside(QR_BACK) else None


def face_box(points: np.ndarray, shape: tuple[int, ...]) -> tuple[float, float, float]:
    """(centre x, centre y, width) of the face, as fractions of the image."""
    h, w = shape[:2]
    xs, ys = points[:, 0], points[:, 1]
    return ((xs.min() + xs.max()) / 2 / w, (ys.min() + ys.max()) / 2 / h, (xs.max() - xs.min()) / w)


# The centring page: the oval (a fraction of the camera's width and height)
# and how a face fits it. face = (centre x, centre y, width), all 0-1.
FIT_RX, FIT_RY = 0.2, 0.36
_GOOD = (90, 190, 70)
FIT_WORDS = {
    "good": ("좋아요! 딱 맞아요", "Great, that's it"),
    "none": ("얼굴이 보이지 않아요", "Can't see your face yet"),
    "far": ("조금 더 가까이 오세요", "Come a little closer"),
    "near": ("조금 뒤로 가세요", "Move back a little"),
    "off": ("얼굴을 타원 가운데로", "Move your face into the oval"),
}


def face_fit(face: Optional[tuple[float, float, float]]) -> str:
    """good, none, far, near or off, for the centring page."""
    if face is None:
        return "none"
    cx, cy, fw = face
    if fw < 0.16:
        return "far"
    if fw > 0.6:
        return "near"
    dx, dy = (cx - 0.5) / (FIT_RX * 0.75), (cy - 0.5) / (FIT_RY * 0.75)
    return "good" if dx * dx + dy * dy <= 1.0 else "off"


def popup_hit(x: int, y: int) -> Optional[str]:
    """A click at dashboard (x, y) on the pop-up: "learn_close" on the cross,
    "learn_more" anywhere else on it, None off it."""
    def inside(r) -> bool:
        return r[0] <= x < r[0] + r[2] and r[1] <= y < r[1] + r[3]
    if inside(POPUP_CLOSE):
        return "learn_close"
    return "learn_more" if inside(POPUP) else None


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

    def briefing(self, step: int, t: float, size: tuple[int, int] = (DASH_W, DASH_H),
                 camera: Optional[np.ndarray] = None,
                 face: Optional[tuple[float, float, float]] = None) -> np.ndarray:
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
        elif pic == "center":
            self._draw_center(canvas, f, t, camera, face)
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

    def _draw_center(self, canvas: np.ndarray, f: _Frame, t: float,
                     camera: Optional[np.ndarray], face: Optional[tuple[float, float, float]]) -> None:
        """The centring page's left panel: the live camera with an oval to fit
        the face in (green when it fits), what to do, and an arrow down to
        the camera itself."""
        import cv2

        state = face_fit(face)
        good = state == "good"
        if camera is not None:
            w = f.n(_SPLIT - 70)
            h = int(camera.shape[0] * w / camera.shape[1])
            if h > f.n(380):
                h = f.n(380)
                w = int(camera.shape[1] * h / camera.shape[0])
            view = cv2.resize(camera, (w, h), interpolation=cv2.INTER_AREA)
            if view.ndim == 2:
                view = cv2.cvtColor(view, cv2.COLOR_GRAY2BGR)
            col = _GOOD if good else (255, 255, 255)
            cv2.ellipse(view, (w // 2, h // 2), (int(w * FIT_RX), int(h * FIT_RY)), 0, 0, 360,
                        (0, 0, 0), max(3, f.n(7)), cv2.LINE_AA)
            cv2.ellipse(view, (w // 2, h // 2), (int(w * FIT_RX), int(h * FIT_RY)), 0, 0, 360,
                        col, max(2, f.n(4)), cv2.LINE_AA)
            x, y = f.x(_SPLIT / 2) - w // 2, f.y(30)
            canvas[y:y + h, x:x + w] = view
            edge = f.n(6) if good else 1
            cv2.rectangle(canvas, (x - edge, y - edge), (x + w + edge - 1, y + h + edge - 1),
                          _GOOD if good else (120, 120, 120), edge)
        key = ("fit", state, f.w, f.h)
        if key not in self._cache:
            ko, en = FIT_WORDS[state]
            band = self._base(f)
            if good:
                cv2.rectangle(band, (f.x(70), f.y(424)), (f.x(_SPLIT - 70), f.y(494)), _GOOD, -1, cv2.LINE_AA)
            band, _ = self._text(band, f, [(ko, "bold", 28, _WHITE if good else _BOARD, 430),
                                           (en, "regular", 19, _WHITE if good else (90, 90, 90), 466),
                                           ("밤눈 카메라는 이 아래에 있어요", "bold", 22, _BOARD, 520),
                                           ("The Bamnun camera is down here", "regular", 17, (90, 90, 90), 552)],
                                 cx=_SPLIT / 2, max_w=_SPLIT - 80)
            y0, y1 = f.y(418), f.y(580)
            self._cache[key] = (y0, y1, band[y0:y1, :f.x(_SPLIT)].copy())
        y0, y1, strip = self._cache[key]
        canvas[y0:y1, :strip.shape[1]] = strip
        # A big arrow, nudging down towards the device under the screen.
        bob = f.n(12) * (0.5 + 0.5 * math.sin(t * 4.0))
        cx = f.x(_SPLIT / 2)
        tail, tip = (cx, int(f.y(588) + bob)), (cx, int(f.y(692) + bob))
        cv2.arrowedLine(canvas, tail, tip, _BOARD, f.n(14), cv2.LINE_AA, tipLength=0.45)

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

    # -- the guided tour ----------------------------------------------------- #

    def _tour_card(self, f: _Frame, step: int) -> np.ndarray:
        import cv2

        key = ("tour", step, f.w, f.h)
        if key not in self._cache:
            w, h = TOUR_CARD
            card = np.empty((f.n(h), f.n(w), 3), np.uint8)
            card[:] = (250, 250, 250)
            cf = _Frame((card.shape[1], card.shape[0]))
            cf.s, cf.ox, cf.oy = f.s, 0.0, 0.0
            _r, _x, _y, ko, en, lko, len_ = TOUR[step]
            last = step == len(TOUR) - 1
            card, _ = self._text(card, cf, [
                (f"{step + 1} / {len(TOUR)}", "regular", 15, (130, 130, 130), 12),
                (ko, "bold", 30, _BOARD, 32),
                (en, "regular", 18, (105, 105, 105), 70),
                (lko, "regular", 18, _BOARD, 100),
                (len_, "regular", 14, (105, 105, 105), 124),
                ("클릭: 시작하기  ·  Click: start driving" if last
                 else "클릭: 다음  ·  Click: next     Esc: 건너뛰기", "bold", 14, (60, 60, 60), 148),
            ], cx=w / 2, max_w=w - 30)
            cv2.rectangle(card, (0, 0), (card.shape[1] - 1, card.shape[0] - 1), (205, 205, 205), 1)
            self._cache[key] = card
        return self._cache[key]

    def tour_overlay(self, canvas: np.ndarray, step: int, t: float, age: float) -> None:
        """Dim the window-sized dashboard except one part, outline it, and put
        the step's card beside it."""
        import cv2

        step = max(0, min(step, len(TOUR) - 1))
        f = _Frame((canvas.shape[1], canvas.shape[0]))
        (x, y, w, h), cx, cy, *_ = TOUR[step]
        x0, y0, x1, y1 = f.x(x), f.y(y), f.x(x + w), f.y(y + h)
        k = min(1.0, age / 0.3)
        keep = canvas[y0:y1, x0:x1].copy()
        canvas[:] = (canvas * (1 - 0.68 * k)).astype(np.uint8)
        canvas[y0:y1, x0:x1] = keep
        pulse = f.n(3 + 3 * (0.5 + 0.5 * math.sin(t * 4.0)))
        cv2.rectangle(canvas, (x0 - pulse, y0 - pulse), (x1 + pulse, y1 + pulse), _WHITE,
                      max(2, f.n(3)), cv2.LINE_AA)
        card = self._tour_card(f, step)
        ch, cw = card.shape[:2]
        left, top = f.x(cx), f.y(cy) - int(f.n(14) * (1 - k))
        H, W = canvas.shape[:2]
        left, top = max(0, min(W - cw, left)), max(0, min(H - ch, top))
        canvas[top:top + ch, left:left + cw] = card

    # -- learn more: the pop-up and the QR code --------------------------------- #

    def _popup_card(self, f: _Frame, hot: bool = False, kind: str = "learn") -> tuple[np.ndarray, _Frame]:
        """The pop-up's still parts, drawn once per window size at that size
        (drawn small and scaled up, the text went soft): a white card like a
        website's, a question, a dark button and a close cross. Ollie and the
        button's glow move, so they are added each frame."""
        import cv2

        x, y, w, h = POPUP
        key = ("popup", f.w, f.h, hot, kind)
        if key not in self._cache:
            card = np.empty((f.n(h), f.n(w), 3), np.uint8)
            card[:] = (250, 250, 250)
            cf = _Frame((card.shape[1], card.shape[0]))
            cf.s, cf.ox, cf.oy = f.s, 0.0, 0.0
            bx, by, bw, bh = (POPUP_BUTTON[0] - x, POPUP_BUTTON[1] - y, POPUP_BUTTON[2], POPUP_BUTTON[3])
            # Under the mouse the button lightens, like a link on a website.
            cv2.rectangle(card, (cf.x(bx), cf.y(by)), (cf.x(bx + bw), cf.y(by + bh)),
                          (88, 88, 94) if hot else _BOARD, -1, cv2.LINE_AA)
            tx = _POPUP_TEXT_X + (w - _POPUP_TEXT_X - 46) / 2
            title, sub, box = POPUP_WORDS[kind]
            card, _ = self._text(card, cf, [
                (title, "bold", 36, _BOARD, 22),
                (sub, "regular", 21, (105, 105, 105), 72),
            ], cx=tx, max_w=w - _POPUP_TEXT_X - 60)
            card, _ = self._text(card, cf, [(box, "bold", 24, _WHITE,
                                             by + (bh - 25) / 2)], cx=bx + bw / 2, max_w=bw - 24)
            cx, cy, r = cf.x(w - 24), cf.y(24), cf.n(9)   # the close cross
            for p0, p1 in (((cx - r, cy - r), (cx + r, cy + r)), ((cx - r, cy + r), (cx + r, cy - r))):
                cv2.line(card, p0, p1, (120, 120, 120), cf.n(2.5), cv2.LINE_AA)
            cv2.rectangle(card, (0, 0), (card.shape[1] - 1, card.shape[0] - 1), (205, 205, 205), 1)
            self._cache[key] = (card, cf)
        return self._cache[key]

    def learn_popup(self, canvas: np.ndarray, age: float, t: float, hover: Optional[str] = None,
                    kind: str = "learn") -> None:
        """Draw the pop-up on the window-sized dashboard (fit_to_window's
        layout): it springs down into place, Ollie waves, the button glows."""
        import cv2

        f = _Frame((canvas.shape[1], canvas.shape[0]))
        card, cf = self._popup_card(f, hover == "learn_more" and kind == "learn", kind)
        card = card.copy()
        if hover == "learn_close":                  # a grey disc behind the cross
            cv2.circle(card, (cf.x(w - 24), cf.y(24)), cf.n(19), (222, 222, 222), -1, cv2.LINE_AA)
            r = cf.n(9)
            cx, cy = cf.x(w - 24), cf.y(24)
            for p0, p1 in (((cx - r, cy - r), (cx + r, cy + r)), ((cx - r, cy + r), (cx + r, cy - r))):
                cv2.line(card, p0, p1, (60, 60, 60), cf.n(2.5), cv2.LINE_AA)
        x, y, w, h = POPUP
        # Ollie, waving: a bigger swing than on the slides.
        owl = self._owl("hello" if kind == "learn" else "sleepy", cf.n(132))
        if owl is not None:
            oh, ow = owl.shape[:2]
            m = cv2.getRotationMatrix2D((ow / 2, oh * 0.85), 7.0 * math.sin(t * 3.0), 1.0)
            moved = cv2.warpAffine(owl, m, (ow, oh), flags=cv2.INTER_LINEAR,
                                   borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
            self._paste(card, moved, cf.x(_POPUP_TEXT_X / 2 + 4), cf.y(h / 2 + 4 * math.sin(t * 2.2)))
        # The button breathes: a soft ring that grows and fades.
        bx, by, bw, bh = (POPUP_BUTTON[0] - x, POPUP_BUTTON[1] - y, POPUP_BUTTON[2], POPUP_BUTTON[3])
        ph = (t * 0.8) % 1.0 if kind == "learn" else 0.99   # only a button glows
        grow = cf.n(2 + 9 * ph)
        ring = card.copy()
        cv2.rectangle(ring, (cf.x(bx) - grow, cf.y(by) - grow), (cf.x(bx + bw) + grow, cf.y(by + bh) + grow),
                      _BOARD, cf.n(2.5), cv2.LINE_AA)
        a = 0.55 * (1 - ph)
        card = cv2.addWeighted(ring, a, card, 1 - a, 0)
        cv2.rectangle(card, (cf.x(bx), cf.y(by)), (cf.x(bx + bw), cf.y(by + bh)), _BOARD, 1, cv2.LINE_AA)
        # In: drop from above with a little overshoot, fading in.
        k = min(1.0, max(0.0, age / 0.55))
        c1 = 1.70158
        ease = 1 + (c1 + 1) * (k - 1) ** 3 + c1 * (k - 1) ** 2
        alpha = min(1.0, age / 0.25)
        ch, cw = card.shape[:2]
        left = f.x(x)
        top = int(f.y(y) - f.n(70) * (1 - ease))
        H, W = canvas.shape[:2]
        y0, y1 = max(0, top), min(H, top + ch)
        x1 = min(W, left + cw)
        if y1 <= y0 or x1 <= left:
            return
        sd = f.n(6)                                   # a soft shadow below-right
        sh = canvas[min(H, y0 + sd):min(H, y1 + sd), min(W, left + sd):min(W, x1 + sd)]
        sh[:] = (sh * (1 - 0.4 * alpha)).astype(np.uint8)
        src = card[y0 - top:y1 - top, :x1 - left]
        dst = canvas[y0:y1, left:x1]
        dst[:] = (src * alpha + dst * (1 - alpha)).astype(np.uint8)

    def _qr(self, url: str, px: int) -> Optional[np.ndarray]:
        key = ("qr", url, px)
        if key not in self._images:
            import cv2

            try:
                code = cv2.QRCodeEncoder.create().encode(url)
            except Exception as exc:  # noqa: BLE001
                log.warning("could not make the QR code: %s", exc)
                code = None
            if code is not None and code.size:
                code = cv2.copyMakeBorder(code, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255)
                k = max(1, px // code.shape[0])
                code = cv2.resize(code, (code.shape[1] * k, code.shape[0] * k),
                                  interpolation=cv2.INTER_NEAREST)
                code = cv2.cvtColor(code, cv2.COLOR_GRAY2BGR)
            else:
                code = None
            self._images[key] = code
        return self._images[key]

    def _learn_left(self, c: np.ndarray, f: _Frame, url: str, visit: Optional[dict]) -> np.ndarray:
        """The left panel: the website's QR code; or, for a visitor with a
        drive to take home, their photo and the question, the upload, and
        their own QR code."""
        import cv2

        state = (visit or {}).get("state", "none")
        photo = (visit or {}).get("photo")
        dim = (95, 95, 95)

        def put_qr(link: str, px: float, cy: float) -> None:
            code = self._qr(link, f.n(px))
            if code is not None:
                h, w = code.shape[:2]
                x0, y0 = f.x(_SPLIT / 2) - w // 2, f.y(cy) - h // 2
                pad = f.n(8)
                cv2.rectangle(c, (x0 - pad, y0 - pad), (x0 + w + pad, y0 + h + pad), (255, 255, 255), -1)
                c[y0:y0 + h, x0:x0 + w] = code

        def put_photo(px: float, cy: float) -> None:
            if photo is None:
                return
            side = f.n(px)
            img = cv2.resize(photo, (side, side), interpolation=cv2.INTER_AREA)
            x0, y0 = f.x(_SPLIT / 2) - side // 2, f.y(cy) - side // 2
            c[y0:y0 + side, x0:x0 + side] = img
            cv2.rectangle(c, (x0 - 1, y0 - 1), (x0 + side, y0 + side), _BOARD, max(1, f.n(2)))

        if state == "ask" and photo is not None:
            put_photo(220, 175)
            c, _ = self._text(c, f, [("내 운전 기록을 휴대폰으로 받을까요?", "bold", 26, _BOARD, 305),
                                     ("Take this drive home on your phone?", "regular", 18, dim, 344),
                                     ("사진과 기록은 11월 24일 전시가 끝나면 삭제돼요", "regular", 16, _BOARD, 382),
                                     ("Photos and data are deleted when the exhibition ends, 24 Nov",
                                      "regular", 13, dim, 408)],
                              cx=_SPLIT / 2, max_w=_SPLIT - 50)
            for name, (x, y, w, h) in VISIT_BUTTONS.items():
                yes = name == "visit_yes"
                cv2.rectangle(c, (f.x(x), f.y(y)), (f.x(x + w), f.y(y + h)), _BOARD,
                              -1 if yes else max(1, f.n(2)), cv2.LINE_AA)
                ko, en = ("예, 받을게요", "Yes, please") if yes else ("아니요", "No, thanks")
                c, _ = self._text(c, f, [(ko, "bold", 22, _WHITE if yes else _BOARD, y + 9),
                                         (en, "regular", 15, (200, 200, 200) if yes else dim, y + 38)],
                                  cx=x + w / 2, max_w=w - 16)
            c, _ = self._text(c, f, [("아니요를 누르면 사진은 바로 지워져요  ·  No deletes the photos now",
                                      "regular", 13, dim, 548)], cx=_SPLIT / 2, max_w=_SPLIT - 50)
        elif state == "uploading":
            put_photo(220, 210)
            c, _ = self._text(c, f, [("기록을 올리는 중…", "bold", 28, _BOARD, 350),
                                     ("Saving your drive…", "regular", 20, dim, 392)],
                              cx=_SPLIT / 2, max_w=_SPLIT - 60)
        elif state == "done" and visit.get("link"):
            put_qr(visit["link"], 330, 265)
            c, _ = self._text(c, f, [("내 운전 기록 QR", "bold", 30, _BOARD, 470),
                                     ("Your drive, on your phone", "regular", 21, dim, 514),
                                     ("11월 24일까지 볼 수 있어요  ·  Until 24 Nov", "regular", 17, (115, 115, 115), 552)],
                              cx=_SPLIT / 2, max_w=_SPLIT - 60)
        else:
            put_qr(url, 330, 285)
            short = url.split("://", 1)[-1].rstrip("/")
            lines = [("휴대폰으로 더 알아보기", "bold", 30, _BOARD, 490),
                     ("Learn more on your phone", "regular", 21, dim, 534),
                     (short, "regular", 17, (115, 115, 115), 570)]
            if state == "failed":
                lines.append(("인터넷 연결이 안 돼서 기본 QR이에요  ·  Offline: the general code",
                              "regular", 13, dim, 604))
            c, _ = self._text(c, f, lines, cx=_SPLIT / 2, max_w=_SPLIT - 50)
        return c

    def _learn_static(self, f: _Frame, url: str, lit: int, visit: Optional[dict] = None) -> np.ndarray:
        """The learn-more screen without what moves; ``lit`` is the stage
        card drawn white (playing), 0 none."""
        import cv2

        vkey = ((visit or {}).get("state", "none"), (visit or {}).get("key"))
        key = ("learn", url, f.w, f.h, lit, vkey)
        if key in self._cache:
            return self._cache[key]
        for k in [k for k in self._cache if k[0] == "learn" and k[5] != vkey]:
            del self._cache[k]                       # an earlier visitor's screens
        c = self._learn_left(self._base(f), f, url, visit)
        # Right: the title, four stage cards, a way back.
        c, spans = self._text(c, f, [("깨우기 단계 체험", "bold", 42, _WHITE, 44),
                                     ("Try Bamnun's four wake-up stages", "regular", 23, _GREY, 100)])
        pad = f.n(18)
        cv2.rectangle(c, (f.x(_SPLIT + 40), spans[0][0] - pad), (f.x(DASH_W - 40), spans[1][1] + pad),
                      _WHITE, max(1, f.n(1.5)), cv2.LINE_AA)
        lines = []
        for n, (ko, en, dko, den) in STAGE_CARDS.items():
            x, y, w, h = _card_rect(n)
            on = n == lit
            if on:
                cv2.rectangle(c, (f.x(x), f.y(y)), (f.x(x + w), f.y(y + h)), _WHITE, -1, cv2.LINE_AA)
            else:
                cv2.rectangle(c, (f.x(x), f.y(y)), (f.x(x + w), f.y(y + h)), _GREY, max(1, f.n(1.5)), cv2.LINE_AA)
            fg, dim = (_BOARD, (90, 90, 90)) if on else (_WHITE, _GREY)
            cx = x + w / 2
            lines.append(((f"{n}  ·  {ko}", "bold", 29, fg, y + 20), cx, w))
            lines.append(((en, "regular", 19, dim, y + 58), cx, w))
            lines.append(((dko, "regular", 19, fg, y + 98), cx, w))
            lines.append(((den, "regular", 15, dim, y + 127), cx, w))
        for line, cx, w in lines:
            c, _ = self._text(c, f, [line], cx=cx, max_w=w - 26)
        bx, by, bw, bh = QR_BACK
        cv2.rectangle(c, (f.x(bx), f.y(by)), (f.x(bx + bw), f.y(by + bh)), _GREY, max(1, f.n(1.5)), cv2.LINE_AA)
        c, _ = self._text(c, f, [("‹ 돌아가기  ·  Back", "regular", 19, _WHITE, by + (bh - 20) / 2)],
                          cx=bx + bw / 2, max_w=bw - 16)
        if lit:
            c, _ = self._text(c, f, [(f"밤눈에서 {lit}단계를 켜는 중…", "bold", 28, _WHITE, 540),
                                     (f"Playing stage {lit} on Bamnun…", "regular", 20, _GREY, 582)])
        self._cache[key] = c
        return c

    def learn_more(self, t: float, url: str, size: tuple[int, int] = (DASH_W, DASH_H),
                   playing: int = 0, progress: float = 0.0, hover: Optional[str] = None,
                   visit: Optional[dict] = None) -> np.ndarray:
        """The QR code for the website on the left; on the right, the four
        wake-up stages to click, each played on the real device. ``playing``
        is the stage playing now (lit, with ``progress`` 0-1 along its foot)."""
        import cv2

        f = _Frame(size)
        canvas = self._learn_static(f, url, playing, visit).copy()
        # Under the mouse: the card (or Back) lightens and its edge thickens,
        # so it reads as something to press.
        rect = None
        if hover and hover.startswith("stage") and int(hover[5:]) != playing and not playing:
            rect = _card_rect(int(hover[5:]))
        elif hover == "qr_back":
            rect = QR_BACK
        elif hover in VISIT_BUTTONS and (visit or {}).get("state") == "ask":
            rect = VISIT_BUTTONS[hover]
        if rect is not None:
            x, y, w, h = rect
            x0, y0, x1, y1 = f.x(x), f.y(y), f.x(x + w), f.y(y + h)
            region = canvas[y0:y1, x0:x1]
            region[:] = cv2.addWeighted(region, 0.8, np.full_like(region, 255), 0.2, 0)
            cv2.rectangle(canvas, (x0, y0), (x1, y1), _WHITE, max(2, f.n(3)), cv2.LINE_AA)
        if playing:
            x, y, w, h = _card_rect(playing)
            x1 = x + 10 + (w - 20) * min(1.0, max(0.0, progress))
            cv2.rectangle(canvas, (f.x(x + 10), f.y(y + h - 12)), (f.x(x1), f.y(y + h - 7)), _BOARD, -1)
        else:
            self._prompt(canvas, f, t, "카드를 누르면 밤눈이 실제로 켜져요", "Click a card: Bamnun plays it for real",
                         y=540)
        return canvas


# The guided tour of the dashboard after calibration, like a new app's first
# run: each step lights one part (1280x720 units) and explains it in a card.
# (rect, card x, card y, Korean title, English title, Korean line, English line)
TOUR = [
    ((8, 8, 832, 468), 860, 230, "카메라", "The camera",
     "얼굴 위의 점과 선이 밤눈이 따라가는 곳이에요", "The dots and lines are what Bamnun tracks"),
    ((848, 8, 424, 136), 410, 30, "지금 상태", "Right now",
     "졸음 점수: 깨어 있음부터 위험까지", "How sleepy you are, from alert to danger"),
    ((848, 478, 424, 134), 410, 450, "깨우기 단계", "Wake-up stages",
     "졸리면 불빛, 미스트, 소리, 알람이 여기 켜져요", "Light, mist, sound and alarm light up here"),
    ((666, 422, 172, 48), 420, 230, "설정", "Settings",
     "운전이 끝나면 여기서 QR + STAGES로 기록을 받아요", "After your drive: QR + STAGES here takes it home"),
]
TOUR_CARD = (400, 172)                        # w, h


# The Pi's health (thermal.PiHealth), as a bar across the top of any screen.
HEALTH_WORDS = {
    "warm": ("Pi가 뜨거워지고 있어요", "The Pi is getting warm", (0, 130, 230)),
    "hot": ("Pi가 너무 뜨거워요: 잠시 꺼서 식혀 주세요", "The Pi is too hot: turn it off to cool down",
            (40, 40, 200)),
    "power": ("전원이 약해요: 전원 어댑터를 확인하세요", "Power too weak: check the power adapter",
              (40, 40, 200)),
}


def health_banner(screens: Optional["Screens"], canvas: np.ndarray, level: str,
                  celsius: Optional[float]) -> np.ndarray:
    """``canvas`` with the warning bar on top: the screen is fitted into the
    rest of the height, so the bar covers nothing."""
    import cv2

    from .viz import fit_to_window

    if level not in HEALTH_WORDS:
        return canvas
    ko, en, colour = HEALTH_WORDS[level]
    temp = f" ({celsius:.0f}°C)" if celsius is not None else ""
    h, w = canvas.shape[:2]
    bar = max(28, h // 16)
    key = ("health", level, temp, w, bar)
    cache = screens._cache if screens is not None else {}
    if key not in cache:
        strip = np.empty((bar, w, 3), np.uint8)
        strip[:] = colour
        text = f"{ko}{temp}   ·   {en}"
        if screens is not None and screens._pil and screens.korean:
            from PIL import Image, ImageDraw

            img = Image.fromarray(strip[:, :, ::-1])
            d = ImageDraw.Draw(img)
            px = int(bar * 0.5)
            font = screens._font("bold", px)
            tw = d.textlength(text, font=font)
            if tw > w * 0.96:
                px = max(8, int(px * w * 0.96 / tw))
                font = screens._font("bold", px)
                tw = d.textlength(text, font=font)
            d.text(((w - tw) / 2, (bar - px) / 2 - 1), text, font=font, fill=(255, 255, 255))
            strip = np.asarray(img)[:, :, ::-1].copy()
        else:
            text = f"{en}{temp.replace('°', ' ')}"
            scale = bar / 48.0
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
            cv2.putText(strip, text, ((w - tw) // 2, (bar + th) // 2), cv2.FONT_HERSHEY_SIMPLEX,
                        scale, (255, 255, 255), 2, cv2.LINE_AA)
        cache[key] = strip
    return np.vstack([cache[key], fit_to_window(canvas, w, h - bar)])
