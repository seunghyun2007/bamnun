"""Make frontend/fonts/pretendard.woff2, the app's one font, small enough to
inline: Pretendard (OFL, github.com/orioncactus/pretendard) cut down to
weights 400-800, Latin, the 2,350 common Hangul syllables (KS X 1001) and
every character in the app's own text. Anything else falls back to the
phone's own Korean font.

Run it again after adding text with rare syllables:

    pip install fonttools brotli
    curl -LO https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/web/variable/woff2/PretendardVariable.woff2
    python frontend/build/subset_font.py PretendardVariable.woff2
"""
import glob
import os
import sys
import tempfile

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

HERE = os.path.dirname(os.path.abspath(__file__))
FRONT = os.path.dirname(HERE)


def chars() -> str:
    text = set(chr(c) for c in range(0x20, 0x7F)) | set("·–—…‘’“”•→←↑↓×°%‹›«»")
    for a in range(0xB0, 0xC9):                     # KS X 1001 Hangul rows
        for b in range(0xA1, 0xFF):
            try:
                text.add(bytes([a, b]).decode("euc-kr"))
            except UnicodeDecodeError:
                pass
    for f in glob.glob(os.path.join(FRONT, "screens", "*.html")) + glob.glob(os.path.join(HERE, "*.js")) \
            + glob.glob(os.path.join(HERE, "*.json")) + [os.path.join(HERE, "shell.html")]:
        text |= set(open(f, encoding="utf-8").read())
    return "".join(sorted(c for c in text if ord(c) >= 0x20))


def main(src: str) -> None:
    font = instancer.instantiateVariableFont(TTFont(src), {"wght": (400, 800)})
    with tempfile.NamedTemporaryFile(suffix=".ttf", delete=False) as tmp:
        font.save(tmp.name)
    opts = subset.Options()
    opts.flavor = "woff2"
    opts.layout_features = ["kern", "liga", "calt", "tnum", "ccmp", "locl", "mark", "mkmk"]
    f = subset.load_font(tmp.name, opts)
    s = subset.Subsetter(opts)
    s.populate(text=chars())
    s.subset(f)
    out = os.path.join(FRONT, "fonts", "pretendard.woff2")
    subset.save_font(f, out, opts)
    os.unlink(tmp.name)
    print(out, os.path.getsize(out), "bytes")


if __name__ == "__main__":
    main(sys.argv[1])
