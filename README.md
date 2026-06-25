# Video Downloader (Vidara.to, Avtub.cx & Kurakura21.com)

Web-based video downloader that supports multiple sites. Bypasses the Telegram 50MB upload limit by downloading videos to a VPS and serving them via HTTP.

## Supported Sites

| Site | URL Format | Status |
|------|-----------|--------|
| vidara.to | `https://vidara.to/v/{id}` | ✅ Working |
| avtub.cx | `https://avtub.cx/{id}/{slug}/` | ✅ Working |
| kurakura21.com | `https://kurakura21.com/{slug}/` | ✅ Working |

## Features

- Download videos in best available quality (up to 1080p)
- Live progress bar (0-100%) during download
- No file size limits (bypasses Telegram 50MB bot API limit)
- Auto-cleanup: files older than 1 hour are deleted automatically
- Dark UI with Tailwind CSS
- AES-CBC decryption for turtle4up.top embeds (kurakura21.com)

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run in development
python main.py

# Run in production
gunicorn -w 4 -b 0.0.0.0:5000 main:app
```

## How It Works

1. User pastes a video URL (vidara.to, avtub.cx, or kurakura21.com)
2. Backend extracts the direct m3u8/mp4 streaming URL
3. `yt-dlp` downloads the video to the VPS (`downloads/` folder)
4. User downloads the file via browser
5. File auto-deletes after 1 hour

## Deployment

This project is designed for platforms like Railway, Render, or any VPS with Python:

```
web: gunicorn main:app
```

## Environment

- Python 3.10+
- `yt-dlp` (for video downloading)
- `node` (required for avtub.cx JS deobfuscation)

## License

MIT
