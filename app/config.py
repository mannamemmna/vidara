import os

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DL_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(DL_DIR, exist_ok=True)

# ─── HTTP ─────────────────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
}

# ─── AES (kurakura21 / turtle4up.top) ────────────────────────────────────────
AES_KEY = b"kiemtienmua911ca"
AES_IV  = b"1234567890oiuytr"

# ─── Queue ────────────────────────────────────────────────────────────────────
MAX_CONCURRENT = 10
CLEANUP_MAX_AGE = 3600   # 1 jam
CLEANUP_INTERVAL = 600   # 10 menit
