# Bamnun app front end

Front-end prototype of the Bamnun / 밤눈 phone app, with no back end yet. Open `Bamnun_app.html` in any browser to try it.

## Folders

- `Bamnun_app.html` is the built app: a single file with everything inside. Don't edit it by hand. Rebuild it instead.
- `screens/` holds the source for each screen (`*.dc.html`). Each one has a `<helmet>` with that screen's CSS, then the markup.
  - Links between screens are written as `href="Name.dc.html"`.
  - Images are referenced as `/_blob/<id>`, and `build.py` swaps in the files from `ollie/`.
- `ollie/` holds the mascot images (idle, hello, thinking, sleepy, wake, celebrate, peek, driving, cup).
- `build/` holds the build files:
  - `build.py` turns the screens into one HTML file.
  - `shell.html` is the phone frame, navigation, sound effects (Web Audio) and the Korean/English switching.
  - `dyn.js` holds the interactive screens: work week, Ollie's style, wake-up ladder, device search and settings.
  - `ko.json` is the Korean translation, as an English → Korean text map. The `html` part covers sentences that contain bold or line breaks.

## Rebuild

```
python3 build/build.py screens build/out.html ollie
```

`out.html` is missing the doctype and charset at the top. The browser handles that, but if you need them, wrap it the same way as `Bamnun_app.html`.

## Notes

- Screen order and navigation are set by `ORDER` in `build.py`.
- To add a translation, add the English text exactly as it appears on screen to `ko.json`.
- Language (`bn-lang`), sound (`bn-sound`) and sensitivity (`bn-sens`) are saved in localStorage.
