# Bamnun app front end

The Bamnun / 밤눈 phone app, a Capacitor app for Android and iOS. `docs/SPEC.md` in the repo root says how it should behave.

## Folders

- `www/` is the built app. It's generated, so it isn't in git. Don't edit it by hand.
- `android/` and `ios/` are the native projects.
- `fonts/` holds the app's fonts, so it looks right with no internet.
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

Run these from this folder. Node 22 or later is required.

```
npm install        # first time only
npm run build      # screens to www/
npm run sync       # build, then copy into android/ and ios/
```

## Run on an Android phone

Install Android Studio 2025.2.1 or later, and turn on USB debugging on the phone. Then:

```
npm run sync
npx cap run android
```

## Run on an iPhone

This needs a Mac with Xcode 26 or later. See section 12 of the spec.

```
npm run sync
npx cap open ios
```

## Notes

- Screen order and navigation are set by `ORDER` in `build.py`.
- To add a translation, add the English text exactly as it appears on screen to `ko.json`.
- Language (`bn-lang`), sound (`bn-sound`) and sensitivity (`bn-sens`) are saved in localStorage.
