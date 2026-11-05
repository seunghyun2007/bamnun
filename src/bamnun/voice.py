"""Ollie's spoken lines, in English and Korean, played on the device speaker.

docs/SPEC.md, section 2: Ollie always speaks through the Bamnun device, never
the phone. Each line is a clip in both languages:

    assets/voice/en/<key>.wav
    assets/voice/ko/<key>.wav

``tools/make_voice.py`` generates them offline (Supertonic, voice M1, one
voice for both languages), and ``tools/record_prompts.py --lang en|ko``
records the team instead, replacing a clip. A clip that hasn't been
recorded yet is skipped, not fatal, exactly like the ladder's audio: the
speaker part shows as "simulated" and the phone still gets a ``say`` event
with the text, so the line can be read on screen.

Lines play one after another on a worker thread, so "Korean greeting, then
English greeting" never overlaps, and the caller never waits for audio.
"""

from __future__ import annotations

import logging
import queue
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("bamnun.voice")


def repo_root() -> Path:
    # Not session.repo_root: this module is stdlib only, so the recorder
    # (tools/record_prompts.py) can load it without the venv.
    return Path(__file__).resolve().parents[2]

LANGS = ("en", "ko")

# key -> (English, Korean). One voice, one way of talking (spec section 6).
LINES: dict[str, tuple[str, str]] = {
    "greet": ("Hi! I'm Ollie. Which language should I speak?",
              "안녕하세요! 저는 올리예요. 어떤 언어로 말할까요?"),
    "sample": ("I'll keep watch while you drive.",
               "운전하는 동안 제가 지켜볼게요."),
    "stage3": ("Your eyes are closing. Let's find a place to rest.",
               "눈이 감기고 있어요. 쉴 곳을 찾아봐요."),
    "stage4": ("Wake up! Pull over now.",
               "일어나세요! 지금 차를 세우세요."),
    "rest_soon": ("Plan a break in the next few minutes.",
                  "몇 분 안에 휴식을 계획하세요."),
    "break_due": ("Two hours in. Time for a break.",
                  "두 시간 운전했어요. 쉬어갈 시간이에요."),
    "open_window": ("The air is stale. Open a window.",
                    "공기가 탁해요. 창문을 열어주세요."),
    "emergency_check": ("Are you OK? Say something or tap your phone.",
                        "괜찮으세요? 휴대폰을 눌러주세요."),
    # Guided calibration and device test (spec section 8).
    "cal_position": ("Sit like you're driving and look at me.",
                     "운전할 때처럼 앉아서 저를 봐주세요."),
    "cal_no_face": ("I can't see you. Check the camera faces you.",
                    "얼굴이 안 보여요. 카메라가 나를 향하는지 확인해주세요."),
    "cal_look": ("Look straight ahead and blink normally.",
                 "정면을 보며 평소처럼 눈을 깜빡이세요."),
    "cal_close": ("Now close your eyes… and open.",
                  "이제 눈을 감았다가… 떠주세요."),
    "cal_hear": ("Can you hear me?", "제 목소리가 들리세요?"),
    "cal_chime": ("That's my wake-up chime.", "이게 깨우는 차임 소리예요."),
    "cal_light": ("See the blue light?", "파란 불빛이 보이세요?"),
    "cal_mist": ("Mist is coming out now. Smell the mint?",
                 "지금 미스트가 나와요. 민트 향이 나나요?"),
    "cal_done": ("All set. I've got your eyes.", "준비 완료. 눈을 잘 익혔어요."),
}


def line_text(key: str, lang: str) -> str:
    en, ko = LINES.get(key, (key, key))
    return ko if lang == "ko" else en


def clip_path(key: str, lang: str, root: Optional[Path] = None) -> Path:
    return (root or repo_root()) / "assets" / "voice" / lang / f"{key}.wav"


def find_player() -> Optional[str]:
    for candidate in ("aplay", "paplay", "afplay", "ffplay"):
        if shutil.which(candidate):
            return candidate
    return None


def play_cmd(player: str, path: Path) -> list[str]:
    cmd = [player]
    if player == "ffplay":
        cmd += ["-nodisp", "-autoexit", "-loglevel", "quiet"]
    return cmd + [str(path)]


class Speaker:
    """Plays Ollie's lines in order on a worker thread. Never blocks the caller.

    ``on_say`` is called (on the caller's thread) with each line as it is
    queued, which is how the phone hears about it.
    """

    def __init__(self, root: Optional[Path] = None,
                 on_say: Optional[Callable[[dict], None]] = None,
                 player: Optional[str] = "auto") -> None:
        self.root = root or repo_root()
        self.player = find_player() if player == "auto" else player
        self.on_say = on_say
        self._q: "queue.Queue[Optional[Path]]" = queue.Queue(maxsize=16)
        self._thread: Optional[threading.Thread] = None

    def present(self, lang: str) -> int:
        """How many of the lines are recorded in this language."""
        return sum(clip_path(k, lang, self.root).exists() for k in LINES)

    @property
    def real(self) -> bool:
        return self.player is not None and any(self.present(lang) for lang in LANGS)

    def say(self, key: str, lang: str) -> dict:
        """Queue one line. Returns what was done, as sent to the phone."""
        lang = lang if lang in LANGS else "en"
        path = clip_path(key, lang, self.root)
        if key not in LINES:
            result = "unknown"
        elif self.player is None or not path.exists():
            result = "simulated"
        else:
            try:
                self._q.put_nowait(path)
                self._ensure_worker()
                result = "played"
            except queue.Full:
                result = "busy"
        event = {"type": "say", "line": key, "lang": lang,
                 "text": line_text(key, lang), "result": result}
        log.info("say %s/%s: %s (%s)", lang, key, event["text"], result)
        if self.on_say is not None:
            try:
                self.on_say(event)
            except Exception:  # noqa: BLE001 - telling the phone is best-effort
                pass
        return event

    def _ensure_worker(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, name="bamnun-voice",
                                            daemon=True)
            self._thread.start()

    def _run(self) -> None:  # pragma: no cover - plays through hardware
        while True:
            path = self._q.get()
            if path is None:
                return
            try:
                subprocess.run(play_cmd(self.player, path), stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=30)
            except Exception as exc:  # noqa: BLE001
                log.warning("voice %s failed: %s", path.name, exc)

    def close(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            try:
                self._q.put_nowait(None)
            except queue.Full:
                pass
