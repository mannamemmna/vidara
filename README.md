# Vidara.to Downloader (Web App)

A web-based UI to extract and download MP4/M3U8 videos from vidara.to. Designed to bypass the Telegram 50MB file limit by running fully on your server.

## Features
- Extractor API (reverse engineered) to pull direct streaming URLs from vidara.to.
- Unlimited file sizes (only bounded by your VPS storage).
- Realtime progress bar on the web UI.
- Auto-Cleanup mechanism (downloads older than 1 hour are automatically deleted to save VPS disk space).

## Installation

```bash
git clone https://github.com/mannamemmna/vidara.git
cd vidara

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Running the Web App (Development)

```bash
python main.py
```
App will be accessible at `http://<your-ip>:5000`.

## Production Setup (Gunicorn + systemd)

Run the app in the background robustly:

```bash
gunicorn -w 4 -b 0.0.0.0:5000 main:app --daemon
```