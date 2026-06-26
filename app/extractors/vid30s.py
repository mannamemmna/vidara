"""vid30s.com — DoodStream embed.php → direct MP4."""
import re, requests
from app.extractors import site
from app.config import HEADERS

@site(r'https?://(?:www\.)?vid30s\.com/d/([a-zA-Z0-9]+)')
def extract(url, m):
    fc = m.group(1)
    r = requests.get(f'https://vid30s.com/embed.php?bucket=temporary&id={fc}',
                     headers={**HEADERS, 'Referer': 'https://vid30s.com/'}, timeout=10)
    sm = re.search(r'<source\s+src="([^"]+)"', r.text)
    if not sm:
        print(f"[vid30s] No <source> found for {fc}")
        return None, f'vid30s_{fc}'
    return sm.group(1), f'vid30s_{fc}'
