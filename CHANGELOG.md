# Changelog

All notable changes to this project will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Cardboard uses [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

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
