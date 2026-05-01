# Changelog

All notable changes to this project will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Cardboard uses [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added

- **Player profile photos** — upload a custom photo for any player via the player profile panel (click a player's name to open it, then hover the avatar circle and click the camera icon). Photos are stored in `data/avatars/` and replace the coloured-initials circle everywhere a player avatar appears: player list, player profile panel, co-player rows in the profile, quick-log player chips, and the stats leaderboard. Existing photos can be removed with the × button that appears on hover. Profile photos are included in ZIP backups and restored automatically.
- **Default SVG avatar presets** — eight built-in SVG avatars are now available to choose from in the player profile panel alongside the custom photo upload: Meeple, Dice, Robot, Crown, Cat, Fox, Bear, and Knight. Hover the avatar circle in the profile panel and click the person icon to open a picker grid; the active selection is highlighted. Choosing a preset clears any custom upload, and uploading a custom photo clears any active preset. The × button removes either type. Preset avatars appear everywhere player avatars are rendered.
- **Persistent collection filters** — the active search text, never-played toggle, player count, play-time cap, mechanic chips, category chips, and location filter are now saved to localStorage and restored on page reload alongside the existing sort and view-mode preferences. The active-filter indicator bar is shown immediately on load if any filter was in effect when the page was last closed.
- **Search across designers, mechanics, and categories** — collection search now matches against a game's designers, mechanics, and categories in addition to its name. Multi-word queries are tokenised (stop words shorter than 2 characters are dropped) and each token must match somewhere across all four fields, so "deck building" finds games with that mechanic regardless of name, and "hargrave" finds all games by Elizabeth Hargrave.
- **"Cooling Off" stats section** — a new section on the Stats page lists owned base games last played between 3 months and 1 year ago, surfacing games that are starting to cool off before they go fully dormant. The section appears between "Shelf of Shame" and "Dormant Games" and can be toggled and reordered like any other stats section.
- **Player win-rate trend and recent form** — the player profile panel now shows three new data points for each player: a W/L pip row for their last 10 decided sessions (newest-first), a current streak badge when they have 2+ consecutive wins or losses, and a monthly win-rate bar chart for the last 12 months (only over sessions with a recorded winner). All three are computed server-side.
- **Head-to-head rivalry stats fixed** — the per-co-player W/L query was previously an N+1 loop (two scalar subqueries per co-player). It is now a single aggregated query using conditional sums, reducing database round-trips from `1 + 2N` to `2` for a player with N co-players.

### Changed

- **Game-night suggestion and similar-games scoring overhauled** — suggestions now incorporate per-session average ratings alongside user ratings, with a priority-ordered quality signal (user rating → session average → BGG rating). A discovery bonus scales with BGG rating, explicitly low user ratings are penalised, and a diversity cap limits results to at most 3 games per difficulty band. Similar-games scoring gains IDF-weighted category and mechanic matching with normalisation, player-count Jaccard overlap, and graduated difficulty scoring. Tests extended to cover session ratings, BGG fallback, penalty logic, and IDF-based ranking.

### Fixed

- **Crash on player sessions endpoint** — `GET /api/players/{id}/sessions` always returned 500 because the query referenced `models.Game.title`, which does not exist; the column is `name`. The query now uses `models.Game.name` and the result mapping is updated to match.
- **XSS in static HTML export** — game names or descriptions containing `</script>` could break out of the inline `<script>` block in the exported HTML file. `json.dumps()` does not escape `</` by default; the serialised payload is now post-processed to replace every `</` with `<\/` before embedding.
- **Restore endpoint loaded entire backup into RAM** — `await file.read(500 MB)` allocated a single buffer equal to the upload size before writing it to disk, risking OOM on large backups. The upload is now streamed to the temp file in 64 KB chunks with the size limit enforced incrementally.
- **BGG rate-limiter dict grew without bound** — per-IP timestamp lists were pruned on each request, but the dict keys (IP addresses) were never removed. On servers that see many unique IPs (DHCP churn, VPN) the dict accumulated indefinitely. Empty entries are now deleted whenever the dict exceeds 1 000 keys.
- **Settings endpoint accepted unbounded value length** — `PUT /api/settings/{key}` had no length constraint on the value field, allowing arbitrarily large writes. The `SettingValue` schema now enforces `max_length=10 000`.
- **Theme-flash script threw in private-browsing mode** — the inline `<script>` in `<head>` of `index.html` and `share.html` called `localStorage.getItem()` without a try/catch. Browsers that block storage access in private mode throw a `SecurityError` at that point, preventing all subsequent scripts from loading. The call is now wrapped in `try { … } catch (_) {}`.
- **Escape keydown listener accumulated across stats reloads** — `wireStatsView` added a `document.addEventListener('keydown', …)` handler on every call (initial load and background refresh) with no cleanup, so each stats view render stacked another live listener. The handler is now registered with an `AbortController` signal; each `wireStatsView` call aborts the previous controller before creating a new one.
- **Missing Content-Security-Policy header** — the security-headers middleware set `X-Content-Type-Options`, `X-Frame-Options`, and `Referrer-Policy` but omitted `Content-Security-Policy`. A CSP is now added restricting resources to same-origin by default, allowing `data:` and `blob:` image sources (used by the gallery and static export), and blocking `object-src` entirely.

- **Stats drill-down modals always showed "No sessions logged for this period"** — the click handlers for every bar chart (sessions by month, heatmap cells, day-of-week columns, rating buckets) looked up games using `state.games`, which is the paginated collection view capped at 200 entries per server request. Any played game beyond that first page was simply not found and filtered out, producing an empty list. The handlers now use the full `allGames` array already fetched by `loadStats` (up to 5000 games, no filters), which is passed through to `wireStatsView`.
- **Stats page stuck on endless loading spinner** — three separate bugs combined to prevent the Stats tab from ever rendering. (1) The `most_played` query joined `Game` to itself instead of joining `PlaySession`, causing a 500 error on any database with logged play sessions. (2) The `GET /api/games/` endpoint capped `limit` at 2000, but `loadStats` requests `limit=5000`; FastAPI returned 422 before the query ran. (3) The error state rendered inside the same `loading-spinner` container as the real spinner, so both failures were visually indistinguishable from an infinite load.
- **"Cooling Off" stats section never rendered** — `show_cooling_off` and the `cooling_off` key were present in `SECTION_DEFAULTS` inside `buildStatsView` but absent from `STATS_PREFS_DEFAULTS` in `app.js`. Because `loadStatsPrefs` normalises `section_order` against `STATS_PREFS_DEFAULTS`, the section was silently dropped before the ordered HTML was assembled, so it never appeared in the stats grid regardless of the toggle setting.

- **Heatmap scroll position incorrect on first render** — the 52-week activity heatmap's scroll-to-current-week logic ran synchronously after the element was inserted, reading `scrollWidth = 0` because layout had not yet completed. The scroll is now deferred to the next animation frame so the element is fully laid out before the offset is calculated.
- **IntersectionObserver fired immediately with `isIntersecting: false`** — observer targets were registered before the elements were appended to the document, so the initial callback always saw them as out-of-view. Observe calls are now deferred to the next animation frame, after the elements are in the DOM.
- **Coach tour could start multiple times on concurrent load paths** — `maybeStartTour` had no guard against being called concurrently; each invocation could independently pass the localStorage check and fire the first-visit tour. An in-progress flag (`_tourCheckDone`) is now set before the async settings fetch and on tour completion, preventing duplicate tours and redundant server round-trips.
- **Opening a game from certain contexts could fail silently** — `onOpenGame` was called with a raw numeric ID instead of the resolved game object. If the ID didn't match a loaded game the callback received `undefined` and produced no visible error. The call site now looks up the full game object from `allGames` first and skips the callback entirely if no match is found.
- **Player profile sessions-by-month chart always showed equal-height bars** — `.player-sessions-bar` had `flex: 1` which caused the flex algorithm to ignore the `height: ${pct}%` inline style, giving every bar the same height regardless of play count. Bars now use pixel heights calculated relative to the fixed chart area and the column uses `justify-content: flex-end` so bars grow from the bottom correctly.
- **Cost/hr on game modal was inflated when sessions lacked recorded duration** — sessions without a logged duration contributed 0 minutes to the total, causing the denominator (hours played) to be understated and the $/hr figure to be too high. For example, 10 plays where only 2 had duration recorded would compute cost over 2 hours instead of 10. Unrecorded sessions now use the game's `min_playtime` as their duration estimate; if `min_playtime` is not set, the average of sessions that do have duration is used instead. Sessions that are entirely without recorded or estimated duration still suppress the display.
- **Static HTML export had no CSS and showed no games** — two bugs combined: (1) `style.css` was referenced as `/css/style.css`, an absolute path that a browser rejects when opening a local file; (2) `window.__STATIC_COLLECTION__` was injected just before `</body>`, after the inline script that reads it, so the variable was always `null` when the page initialised. The export now inlines the full CSS as a `<style>` block, inlines `shared-utils.js` with the data variable appended to the same script (guaranteeing it is defined before the main script block runs), and embeds the logo icon as a base64 data URL so no network requests are needed at all.

---

## [0.2.2] — 2026-04-22

### Fixed

- **Restore silently loaded no data after success** — after `os.replace` atomically swapped the database file, SQLAlchemy's connection pool still held open connections to the previous file descriptor (SQLite WAL keeps the old inode alive). All subsequent reads returned the pre-restore collection. `engine.dispose()` is now called immediately after the file swap, flushing all pooled connections so the next request opens a fresh connection against the restored database.
- **Star ratings only highlighted the hovered star** — hovering over star 3 (for example) lit up only that star instead of stars 1–3. The quick-log popup, the log-session form, and the session-edit form all lacked `mouseover`/`mouseleave` handlers; only click was wired. Each picker now highlights all stars up to the hovered value on hover, and restores the committed selection on mouse-leave.
- **Welcome tagline and empty-tab messages not centred** — the `#empty-state` container is a flex column, but the JS was toggling it with `display: block`, disabling `align-items: center` and leaving the tagline left-aligned. Changed to `display: flex`. The "No owned/wishlist/sold games yet" messages were injected as a child of the `games-grid` CSS grid and only occupied one narrow column cell; added `grid-column: 1 / -1` to `.empty-search-state` so it spans the full grid width.

---

## [0.2.1] — 2026-04-22

### Added

- **Stats section info popovers** — every stats section now has an ⓘ button that reveals an explanatory popover. Only one popover is open at a time; pressing Escape closes the active one.
- **Goals & Challenges breakdown** — the Goals info popover now lists all supported goal types (unique games, play count, total hours, win rate, categories covered, sessions per month) with descriptions.

### Fixed

- **Restore failed: [errno 18] invalid cross-device link** — the restore endpoint created its temporary ZIP in `/tmp`, which is a different filesystem from `/app/data` inside Docker. `os.replace` requires both paths to be on the same filesystem. The temp file is now written directly into `DATA_DIR`, making the rename atomic.
- **ZIP path traversal in restore** — a crafted backup could contain entries like `images/../../../etc/passwd` that escaped `DATA_DIR` when extracted. The restore endpoint now resolves every destination path with `os.realpath` and rejects anything that does not start within `DATA_DIR`.
- **"Welcome to Cardboard" shown on non-empty filtered tabs** — switching to the Owned, Wishlist, or Sold tab when that tab had zero games incorrectly displayed the new-user welcome screen. The check now distinguishes a truly empty collection (all tabs, no games, no filters) from an empty filtered view and shows a tab-specific message instead ("No wishlist games yet.", etc.).
- **Theme toggle flicker** — element-level CSS transitions fired simultaneously with the View Transitions API cross-fade, causing buttons and backgrounds to double-animate. A `html.view-transitioning` class now suppresses all element transitions for the duration of the page-level overlay.
- **Rating Delta section not toggling with Ratings** — hiding the Ratings section in the stats panel did not hide the Rating Delta subsection below it. Both sections are now toggled together.
- **BGG import uses wrong game name** — the BGG XML export uses `sortindex="1"` to mark the canonical title (e.g. "The Castles of Burgundy" vs "Castles of Burgundy, The"). The importer now prefers the `sortindex="1"` element and falls back to the generic `<name>` element, matching BGG's own display behaviour.
- **Shortcuts panel used inconsistent UI** — the keyboard shortcuts overlay used a bespoke modal with opacity-only animation. It now uses the same `openModal`/`closeModal` system as all other panels (spring scale + blur backdrop, focus trap, scroll lock, Escape to close).
- **"Import from BGG" on empty homepage showed file picker immediately** — clicking the button on the empty-collection screen opened a file picker with no context. It now navigates to the Stats page, opens the Settings panel, scrolls the BGG import row into view, and flashes a highlight so the user understands where to proceed.
- **Exception chain lost when saving tags** — `_save_tags` wrapped errors in a generic HTTP 500 without `from e`, discarding the original traceback. The chain is now preserved for easier production debugging.

### Changed

- **Settings panel reorganised** — the Stats settings panel has been reduced from six action rows to three clearer ones: **Backup & Restore** (download ZIP + restore from ZIP), **Import** (BGG Collection, BGG Plays, CSV — all in one row), and **Export Data** (JSON + CSV with field picker). The "Share collection" and "Static HTML Export" rows have been removed since both are already accessible from the footer's Share modal.
- **Difficulty precision** — game difficulty now accepts and displays values to two decimal places (e.g. 2.75) instead of one.

### Tests

- Added 18 tests in `backend/tests/test_backup_restore.py` covering the full backup/restore lifecycle with a real file-based SQLite fixture: valid backup format, SQLite magic header, images included, roundtrip data integrity, gallery and instructions extraction, double roundtrip, and all error cases (missing `cardboard.db`, corrupt database, non-ZIP file, empty ZIP, path traversal, unknown subdirs).

---

## [0.2.0] — 2026-04-22

### Added

- **Static HTML export** — download a self-contained `.html` file of your collection (Settings → Stats backup panel, or Share → Static HTML Export). The file embeds all game data and cached cover images as base64, so recipients can open it in any browser with no server, no account, and no network access required. Only games marked "hidden from share" are excluded, consistent with the live share link behaviour.
- **Smooth theme transitions** — switching between dark and light mode now animates instead of snapping. Chrome and Edge use the native View Transitions API for a full-page cross-fade; Safari and Firefox use an opacity fade fallback. Both paths take ~360–380 ms.

### Fixed

- **Backup restore crash** — importing a `.zip` backup via the Settings restore button threw `TypeError: validate_file_extension() missing 1 required positional argument: 'detail'`, making restores impossible. The missing argument has been added.
- **Collection Health score wrong for empty collections** — with no rated games the Avg Rating factor defaulted to 5/10 internally, producing a misleading score of 20/100 and a half-filled bar graph. It now correctly defaults to 0, so a brand-new empty collection shows 0/100.
- **Footer links pointed to old repository** — the GitHub and Report Bug links in the app footer still referenced `cardboard-v2`. Both now point to the correct `cardboard` repository, with the bug report link deep-linking directly to the bug report issue template.

### Changed

- **Collection Health grade label** — the lowest tier (0–39) has been renamed from "Needs Attention" to "Just Starting", and the score-key legend in the info popover updated to match. The previous label was alarming for new users who haven't yet added or played any games.
- **Light mode color palette** — the warm beige (`#dbd4ca`) palette has been replaced with a cool neutral gray (`#eaeaee` base). Text contrast is improved and button/input outlines are sharper against the gray backgrounds.
- **Docker defaults baked into image** — `DATABASE_URL` and `FRONTEND_PATH` are now set as `ENV` defaults in the Dockerfile. Users no longer need to define them in `docker-compose.yml` or `docker run` commands; the correct values for the container's layout are applied automatically. Both can still be overridden if needed (e.g. pointing `DATABASE_URL` at a PostgreSQL instance).

---

## [0.1.0] — 2026-04-22

Initial public release.

### Added

- Collection management — add, edit, bulk-edit, and delete games with detailed fields (players, playtime, difficulty, rating, labels, categories, mechanics, designers, publishers, condition, purchase info, storage location)
- BoardGameGeek integration — search and auto-fill metadata; parent/expansion linking
- Play tracking — log sessions with date, duration, players, winner, notes, and per-session rating; quick-log overlay; solo mode
- Player profiles — per-player stats, win rates, top games, co-player leaderboard with head-to-head records
- Stats dashboard — totals, most-played, player leaderboard, rating distribution, added/sessions-by-month charts, 52-week activity heatmap, day-of-week breakdown, shelf of shame, collection value
- Goals & challenges — progress-tracked goals with auto-complete detection
- Media — cover images, multi-image photo gallery with captions, instruction PDF upload with inline viewer, 3D scan support (USDZ/GLB) with AR and in-browser viewing
- Sharing — token-based read-only share links with optional expiry; visitors can submit "want to play" requests
- Game night — suggestion engine filtered by player count and playtime; random "Pick for Me" selector
- CSV import
- Dark and light theme, keyboard shortcuts overlay, milestone confetti, PWA support
- Single Docker container deployment; Unraid instructions included
- Pre-built images published to GHCR on version tags (`ghcr.io/noideadeveloper/cardboard`)

[Unreleased]: https://github.com/NoIdeaDeveloper/cardboard/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/NoIdeaDeveloper/cardboard/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/NoIdeaDeveloper/cardboard/releases/tag/v0.1.0
