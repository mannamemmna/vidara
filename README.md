# Vidara — Multi-User Video Downloader

Download video dari berbagai situs. Multi-user queue, auto-cleanup.

## Supported Sites

| Site | Method |
|------|--------|
| vidara.to / vidara.so | vidaratem.co API |
| avtub.cx | morencius.com embed → JS deobfuscation → HLS |
| kurakura21.com | WP AJAX → turtle4up.top AES-CBC decrypt |
| playmogo.com | DoodStream pass_md5 → CDN |
| vid30s.com | DoodStream embed.php → direct MP4 |

## Architecture

```
main.py                     # Entry point (gunicorn main:app)
app/
├── __init__.py             # create_app() factory
├── config.py               # Constants, AES keys, headers
├── routes.py               # Flask Blueprint routes
├── queue_manager.py        # Multi-user download queue + worker
└── extractors/
    ├── __init__.py          # @site registry + resolve() + helpers
    ├── vidara.py            # vidara.to / vidara.so
    ├── avtub.py             # avtub.cx
    ├── kurakura21.py        # kurakura21.com
    ├── playmogo.py          # playmogo.com
    └── vid30s.py            # vid30s.com
templates/index.html         # Frontend UI
```

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web UI |
| `/api/start_download` | POST | Start download `{"url":"..."}` |
| `/api/status/<task_id>` | GET | Check task progress |
| `/api/tasks` | GET | List all tasks |
| `/api/health` | GET | Health check |
| `/downloads/<filename>` | GET | Download file |

## Run

```bash
pip install -r requirements.txt
gunicorn main:app --bind 0.0.0.0:5000 --workers 1 --threads 4
```

## Deploy (Railway)

Auto-deploy from GitHub. Needs:
- `Procfile` — startup command
- `nixpacks.toml` — install Node.js + yt-dlp
- `requirements.txt` — Python deps
