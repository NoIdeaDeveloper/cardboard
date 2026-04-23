# Changelog

All notable changes to this project will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Cardboard uses [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added

- **Player profile photos** — upload a custom photo for any player via the player profile panel (click a player's name to open it, then hover the avatar circle and click the camera icon). Photos are stored in `data/avatars/` and replace the coloured-initials circle everywhere a player avatar appears: player list, player profile panel, co-player rows in the profile, quick-log player chips, and the stats leaderboard. Existing photos can be removed with the × button that appears on hover. Profile photos are included in ZIP backups and restored automatically.

### Fixed

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
