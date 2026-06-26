"""avtub.cx — morencius.com embed → JS deobfuscation → HLS m3u8."""
import re, requests
from app.extractors import site, _m3u8, _abs
from app.config import HEADERS

@site(r'https?://(?:www\.)?avtub\.cx/(\d+)/?')
def extract(url, m):
    pid = m.group(1)
    r = requests.get(url, headers=HEADERS, timeout=10)
    final_url = r.url
    # Follow redirect (avtub often redirects old IDs)
    if final_url != url:
        m2 = re.search(r'avtub\.cx/(\d+)/', final_url)
        if m2:
            pid = m2.group(1)
    iframe = re.search(r'<iframe[^>]+src="([^"]+)"', r.text, re.I)
    if not iframe:
        print(f"[avtub] No iframe found for pid={pid}")
        return None, f'avtub_{pid}'
    eu = iframe.group(1)
    r2 = requests.get(eu, headers={**HEADERS, 'Referer': final_url}, timeout=10)
    mu = _m3u8(r2.text, eu)
    if not mu:
        print(f"[avtub] No m3u8 found in embed {eu}")
        return None, f'avtub_{pid}'
    return _abs(mu, r2.url), f'avtub_{pid}'
