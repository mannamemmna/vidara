"""playmogo.com — DoodStream pass_md5 → CDN direct MP4."""
import re, time, random, string, requests
from app.extractors import site
from app.config import HEADERS

@site(r'https?://(?:www\.)?playmogo\.com/e/([a-zA-Z0-9_-]+)')
def extract(url, m):
    fid = m.group(1)
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)

        # Title
        tm = re.search(r'<title>([^<]+)</title>', r.text)
        title = tm.group(1).strip() if tm else f'playmogo_{fid}'

        thumb_m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', r.text)
        thumbnail = thumb_m.group(1) if thumb_m else ''

        token_m = re.search(r"/pass_md5/([^'\"]+)", r.text)
        if not token_m:
            return None
        token = token_m.group(1)

        r2 = requests.get(f'https://playmogo.com/pass_md5/{token}',
            headers={**HEADERS, 'Referer': url, 'X-Requested-With': 'XMLHttpRequest'}, timeout=10)
        if r2.status_code != 200:
            return None
        cdn = r2.text.strip()
        if not cdn:
            return None

        random_chars = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
        ts = int(time.time())
        mp4_url = f'{cdn}{random_chars}?token={token}&expiry={ts}'
        return {'url': mp4_url, 'title': title, 'thumbnail': thumbnail,
                'qualities': [{'label': 'Best', 'url': mp4_url}]}
    except Exception as e:
        print(f"[playmogo] {e}")
        return None
