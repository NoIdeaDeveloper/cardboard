# Cardboard

A self-hosted board game collection tracker. FastAPI + vanilla JS frontend in a single Docker container, backed by SQLite. No external dependencies beyond optional BoardGameGeek lookups.

<details>
<summary>Screenshots</summary>
<br>
<table>
<tr>
<td width="33%" align="center"><a href="docs/screenshots/collection.png"><img src="docs/screenshots/collection.png" alt="Collection"></a></td>
<td width="33%" align="center"><a href="docs/screenshots/add-game.png"><img src="docs/screenshots/add-game.png" alt="Add a Game"></a></td>
<td width="33%" align="center"><a href="docs/screenshots/stats.png"><img src="docs/screenshots/stats.png" alt="Stats"></a></td>
</tr>
<tr>
<td align="center"><b>Collection</b><br><sub>Browse, search, and filter your library</sub></td>
<td align="center"><b>Add a Game</b><br><sub>Search BGG or enter details manually</sub></td>
<td align="center"><b>Stats</b><br><sub>Insights, charts, and play activity</sub></td>
</tr>
</table>
</details>

## Quick Start

```bash
git clone https://github.com/NoIdeaDeveloper/cardboard-v2.git cardboard
cd cardboard
cp .env.example .env          # optional — edit to change port, data path, etc.
docker compose up -d
```

Open `http://localhost:8000`. Data is persisted to `./data/` on the host.

**Update:**

```bash
git pull && docker compose up -d --build
```

## Features

- **Collection management** — add, edit, bulk-edit, and delete games with detailed fields (players, playtime, difficulty, rating, labels, categories, mechanics, designers, publishers, condition, purchase info, storage location)
- **BGG integration** — search and auto-fill from BoardGameGeek; import collections (XML) and play history; parent/expansion linking
- **Import** — CSV and BGG XML collection import
- **Media** — cover images, multi-image photo gallery with captions, instruction PDF upload with inline viewer, 3D scan upload (USDZ/GLB) with AR and in-browser viewer
- **Play tracking** — log sessions with date, duration, players, winner, notes, and per-session rating; quick-log overlay on game cards; solo mode
- **Player profiles** — per-player stats, win rates, top games, co-player leaderboard with head-to-head records
- **Stats dashboard** — totals, most-played, player leaderboard, rating distribution, added/sessions-by-month charts, 52-week activity heatmap, day-of-week breakdown, shelf of shame, collection value
- **Goals & challenges** — progress-tracked goals (total sessions, play all owned, unique mechanics, etc.) with auto-complete detection
- **Sharing** — token-based read-only share links with optional expiry; visitors can browse, filter, and submit "want to play" requests
- **Game night** — suggestion engine filtered by player count and playtime; random "Pick for Me" selector
- **Quality of life** — dark/light theme, keyboard shortcuts overlay, milestone confetti, PWA support, ETag caching

## Configuration

Set via environment variables (or `.env` for Docker):

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8000` | Host port |
| `DATA_PATH` | `./data` | Host path for the data bind mount |
| `DATABASE_URL` | `sqlite:////app/data/cardboard.db` | SQLAlchemy connection string |
| `ALLOWED_ORIGINS` | `*` | CORS origins (set to your domain in production) |
| `LOG_LEVEL` | `INFO` | Python log level |

## Backups

**In-app:** Settings panel > Download ZIP (database + all media).

**Manual:** Copy the `data/` directory. Restore by replacing it and restarting the container.

```
data/
├── cardboard.db       # database
├── images/            # cover images
├── gallery/           # photo galleries
├── instructions/      # PDFs
└── scans/             # 3D files (GLB/USDZ)
```

## Development

```bash
cd backend && pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Frontend is plain HTML/CSS/JS in `frontend/` — edit and refresh, no build step. API docs at `/api/docs`.

## Tech Stack

Python, FastAPI, SQLAlchemy, Alembic, SQLite, vanilla JS/CSS, Docker.
