# Phone app redesign plan ("quiet night instrument")

Status (2026-11-07): **part 1 built on `demo-booth`; not published to the website yet** (waiting for the owner's and the friend's OK). Part 2 not started.
The exhibition is **10 Nov 2026** (창보고 전시회). Read `HANDOFF.md` first for
the whole booth setup; this file is only the phone app's new look.

## Why

The phone app (the friend's design, `frontend/`) works but looks AI-generated:

- the same purple-to-pink gradient and frosted-glass cards everywhere;
- twinkling stars, glow, and pill badges on almost everything;
- one condensed display font (Bricolage Grotesque, 800) in every heading;
- every screen is a stack of equal cards with no single main thing.

The booth screens on the Pi look deliberate because they follow one strict
rule (grey/charcoal, serif, one picture per slide). The app gets its own rule.

## The rules

1. **One accent colour, with meaning.** Warm cream/amber only for what
   matters: the sleepiness level, rest stops, the worst hour, the main button.
   Everything else is charcoal and off-white. No gradients, no glass, no glow.
2. **One main thing per screen.** Home: "how am I right now" (one big word,
   e.g. "깨어 있음"). Trip: "what happened" (one sentence). Insights: "what
   should I change" (one finding).
3. **Sentences over dashboards.** "새벽 2시 40분, 칠곡 지나서 두 번
   졸았어요" beats six stat tiles. Numbers support the sentence.
4. **Flat, solid cards, one corner radius,** fewer borders, more space.
5. **Ollie only where he means something** (tips, greetings, the tour),
   not as wallpaper.
6. **A plain Korean UI font** (Pretendard, OFL licence; self-host the woff2 in
   `frontend/fonts/` like the current fonts) instead of the condensed display
   font everywhere.

### Colour tokens

| Token | Value | Use |
| --- | --- | --- |
| background | `#15131A` (or `#1A181C`, the device black) | page |
| card | `#1F1C24` | flat cards |
| card 2 | `#24212A` | tips, map/curve backgrounds |
| line | `#2E2A33` | hairlines, chart grid |
| text | `#F2EEE8` | primary text |
| muted | `#9A93A0` | secondary text |
| accent (cream) | `#E8D7AE` | brand: logo, main button, sleepiness bar, stops |
| Ollie brown | `#8B5A3C` / dark `#7A4E33` | the flat mascot only |
| Ollie orange | `#E7963B` | beak, moon, feet |
| warning | amber `#F2B66D` | only real warnings |

## The mascot (decided)

The owner's device has a simple cream owl on the matte black case. After
several rounds (head-only versions looked like a monkey, then a cat), the
owner approved **keeping Ollie's whole body**: one bean-shaped body with small
ear tufts, big round eyes, a cream belly with an orange crescent moon, little
wings and orange feet. The drafts are in `assets/brand/`:

- `ollie_flat_M.svg`: **the app and website mascot.** The app's Ollie,
  flat: no outlines, texture or blush.
- `app_icon_O.svg`: **the app icon.** Flat Ollie peeking up from the bottom.
- `ollie_device_N.svg`: **next to the device** (posters, the Pi's booth
  screens): the same body in cream on black, belly and wings as lines.

These are hand-drawn SVG drafts. A clean final should be traced from the
original Ollie art (`frontend/ollie/*.webp`) by a designer or the friend.
Ollie's other moods (hello, sleepy, thinking, driving, wake, celebrate…) still
need flat versions: part 2.

Mockups shown to the owner (in the chat, not saved as files): Home with one big
status and a cream sleepiness bar; trip detail with route map, sleepiness
curve and one sentence; insights with "새벽 3시가 가장 위험해요" and an hourly bar
chart with one cream bar.

## Part 1: before the exhibition (one session)

Only the look changes, not how anything works.

1. **Mascot:** put `ollie_flat_M.svg` where the app uses the default Ollie
   (`IMG.idle` / `IMG.hello` in `frontend/build/build.py`, which inlines
   `frontend/ollie/*.webp`). Keep mood images where a mood matters until part 2.
   App icon: `app_icon_O.svg` (`frontend/ios`, `frontend/android` icons only if
   building the native app; the website can use it as the favicon).
2. **Global style** (most of the "AI look" goes with this):
   - `frontend/build/shell.html`: `body` background radial gradients → flat
     `#15131A`; add the Pretendard `@font-face`; body font → Pretendard.
   - `frontend/build/dyn.js` line ~9-10: `GLASS` → flat card
     (`background:#1F1C24;border:0` no blur), `HEAD_FONT` → Pretendard 700,
     normal width.
   - `frontend/screens/*.dc.html`: 87 uses of `linear-gradient` /
     `backdrop-filter`. Replace with the tokens above. Remove the stars and
     glow decorations.
3. **Layouts of what a visitor sees from the QR code:**
   - **Home** (`screens/Home.dc.html`, `dyn.js` `Home`): one big status word +
     cream sleepiness bar; two small tiles (blinks/min, next rest); last trip
     as one row. Keep `#hHello`, `#hTrip`, `#hAvatar` (the visitor photo) and
     the Stages link: `frontend/build/visit.js` tour targets them.
   - **Trips** + trip detail (`dyn.js` `Trips`; map/curve/photo HTML in
     `visit.js` `mapSvg`, `curveSvg`, `caughtHtml`): flat colours, cream route
     line and stops, one summary sentence built from the episodes.
   - **Insights** (`dyn.js` `Insights`): lead with one finding sentence (peak
     hour, breaks effect), then the charts; one cream bar for the peak.
   - **Stages** (wake-up stages preview): flat cards.
4. **Check** at phone size (Browser pane, 375×812) with a test visit (see
   below), Korean and English, and that the 6-step phone tour still lands on
   the right elements.
5. **Publish** (below), then try it on a real phone from the Pi's QR code.

## Part 2: after the exhibition

- Setup screens (Welcome, Name, Vehicle, Night/work hours, Voice, Ladder,
  Permissions, Pair, Privacy, Contact, Account), Settings, Calibrate, Camera,
  Route/Drive (maps), Plan, Meet, Ollie.
- Ollie's moods redrawn flat.
- Replace the Pi booth screens' Ollie (`attract.py`, uses
  `frontend/ollie/*.webp`) with `ollie_device_N.svg` style art, if wanted.

## How to work on it

- **Build:** `cd frontend && npm run build` (reads `frontend/.env`: Supabase
  URL + public anon key, not in git). Output `frontend/www/index.html`.
  It also rewrites `frontend/Bamnun_app.html` (left uncommitted so far).
- **Preview:** serve `frontend/www` (`python3 -m http.server 8123 --directory
  frontend/www`; in the desktop app there's a "website" entry in
  `~/Downloads/.claude/launch.json`) and open
  `http://localhost:8123/?demo#Home` at 375×812. `?demo` makes it run the
  built-in demo drive like the real website does.
- **Test visit** (a fake booth visitor with photo + drive): generate a payload
  with `src/bamnun/visit.py` (`Visit.start` / `frame` / `payload`, see
  `tests/test_visit.py`) and POST it to Supabase `visits` with the anon key
  (`curl`; the Mac's python lacks SSL certs), code like `zztest0003`, then open
  `?demo&v=zztest0003#Home`. **Delete test rows afterwards** in the Supabase
  SQL editor: `delete from public.visits where code like 'zztest%';`
- **Publish the website** (GitHub Pages, branch `gh-pages`, only `index.html`
  + `.nojekyll`): copy `frontend/www/index.html` onto `gh-pages` in a
  temporary worktree, commit, push; Pages rebuilds in about 1 minute.
  **Rollback:** push the previous `index.html` back (`git log gh-pages`).
- Commit source changes to `demo-booth` (PR #5 into `main` is open; don't
  merge or push `main` without asking). Update `HANDOFF.md` with every change.

## Things to ask the owner

- Has the friend seen and agreed to the restyle? (It's their design.)
- Is there an original logo file for the case (SVG / print file)?
- Part 1 only before 10 Nov, part 2 after: confirm.
