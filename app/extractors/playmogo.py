"""playmogo.com — DoodStream pass_md5 → CDN direct MP4."""
import re, time, random, string, requests
from app.extractors import site
from app.config import HEADERS

@site(r'https?://(?:www\.)?playmogo\.com/e/([a-zA-Z0-9]+)')
def extract(url, m):
    fc = m.group(1)
    s = requests.Session()
    r = s.get(url, headers=HEADERS, timeout=10)
    mm = re.search(r'/pass_md5/([^\'"]+)', r.text)
    if not mm:
        print(f"[playmogo] No pass_md5 found for {fc}")
        return None, f'playmogo_{fc}'
    r2 = s.get(f'https://playmogo.com{mm.group(0)}',
               headers={**HEADERS, 'Referer': url, 'X-Requested-With': 'XMLHttpRequest'},
               timeout=10)
    base = r2.text.strip()
    if base.startswith('<') or not base:
        print(f"[playmogo] Invalid CDN base: {base[:100]}")
        return None, f'playmogo_{fc}'
    token = mm.group(0).rstrip("'").split('/')[-1]
    rand = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
    return f'{base}{rand}?token={token}&expiry={int(time.time() * 1000)}', f'playmogo_{fc}'
