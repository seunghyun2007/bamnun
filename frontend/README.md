# Bamnun app front end

The Bamnun / 밤눈 phone app, a Capacitor app for Android and iOS. `docs/SPEC.md` in the repo root says how it should behave.

## See it now, with nothing installed

Double-click `Bamnun_app.html`. It opens in any browser and plays a simulated driver (labelled "Demo · simulated driver"), so the live Home and Camera screens move. To see a real device instead, open the address the Pi prints when it runs with `--serve` (see the main README).

## Folders

- `Bamnun_app.html` is the whole app in one file, with images and fonts inside. It's built, and kept in git so it can be opened without building. Don't edit it by hand.
- `www/index.html` is the same build, for Capacitor and the Pi's server. It's generated and not in git.
- `android/` and `ios/` are the native projects.
- `fonts/` holds the app's fonts and their licences. The build puts the fonts inside the HTML, so the app looks right with no internet.
- `screens/` holds the source for each screen (`*.dc.html`). Each one has a `<helmet>` with that screen's CSS, then the markup.
  - Links between screens are written as `href="Name.dc.html"`.
  - Images are referenced as `/_blob/<id>`, and `build.py` swaps in the files from `ollie/`.
  - Elements marked `data-live="..."` are filled in with live data by `live.js`.
- `ollie/` holds the mascot images (idle, hello, thinking, sleepy, wake, celebrate, peek, driving, cup).
- `build/` holds the build files:
  - `build.py` turns the screens into one HTML file.
  - `shell.html` is the phone frame, navigation, sound effects (Web Audio) and the Korean/English switching.
  - `dyn.js` holds the interactive screens: work week, Ollie's style, wake-up ladder, device search and settings.
  - `live.js` connects to the device's `/ws` and paints the live values; it also holds the demo driver.
  - `ko.json` is the Korean translation, as an English → Korean text map. The `html` part covers sentences that contain bold or line breaks. Text with `{n}`-style placeholders is filled in by `BN_T`.

## Live data

`live.js` decides where the device is:

1. `?pi=host:port` in the address, which is then remembered;
2. otherwise, if the page was served by the Pi, the Pi that served it;
3. otherwise the last remembered address, or the hotspot default `10.42.0.1:8000`.

It reconnects by itself, and the Home chip shows Connecting… / Bamnun connected / Not connected. The demo driver runs only when the file is opened from disk or the address has `?demo`; it never stands in for a lost connection.

## Rebuild

Run these from this folder.

```
python build/build.py screens www/index.html,Bamnun_app.html ollie
```

That needs only Python. With Node 22 or later installed, the same thing is:

```
npm install        # first time only
npm run build      # writes www/index.html and Bamnun_app.html
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
- Language (`bn-lang`), sound (`bn-sound`), sensitivity (`bn-sens`) and the device address (`bn-pi`) are saved in localStorage.
