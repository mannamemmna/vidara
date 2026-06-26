"""vid30s.com — DoodStream embed.php → direct MP4."""
import re, requests
from app.extractors import site
from app.config import HEADERS

@site(r'https?://(?:www\.)?vid30s\.com/d/([a-zA-Z0-9]+)')
def extract(url, m):
    fid = m.group(1)
    try:
        embed_url = f'https://vid30s.com/d/{fid}'
        r = requests.get(embed_url, headers={**HEADERS, 'Referer': 'https://vid30s.com/'}, timeout=10)

        # Title
        tm = re.search(r'<title>([^<]+)</title>', r.text)
        title = tm.group(1).strip() if tm else f'vid30s_{fid}'

        thumb_m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', r.text)
        thumbnail = thumb_m.group(1) if thumb_m else ''

        token_m = re.search(r"/pass_md5/([^'\"]+)", r.text)
        if not token_m:
            return None
        token = token_m.group(1)

        import time, random, string
        r2 = requests.get(f'https://vid30s.com/pass_md5/{token}',
            headers={**HEADERS, 'Referer': embed_url, 'X-Requested-With': 'XMLHttpRequest'}, timeout=10)
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
        print(f"[vid30s] {e}")
        return None
