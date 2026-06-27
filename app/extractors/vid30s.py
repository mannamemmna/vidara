"""vid30s.com — multiple embed methods (direct MP4 via embed.php)."""
import re, html, requests
from app.extractors import site
from app.config import HEADERS

@site(r'https?://(?:www\.)?vid30s\.com/d/([a-zA-Z0-9]+)')
def extract(url, m):
    fid = m.group(1)
    headers = {**HEADERS, 'Referer': 'https://vid30s.com/'}
    try:
        r = requests.get(url, headers=headers, timeout=10)

        # Title & thumbnail
        tm = re.search(r'<title>([^<]+)</title>', r.text)
        title = tm.group(1).strip() if tm else f'vid30s_{fid}'
        thumb_m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', r.text)
        thumbnail = thumb_m.group(1) if thumb_m else ''

        # Strategy A: iframe → embed.php → direct MP4 (current)
        iframe_id_match = re.search(r"iframeId\s*=\s*'([a-f0-9]+)'", r.text)
        if iframe_id_match:
            hex_id = iframe_id_match.group(1)
            iframe_url = f'https://vid30s.com/ip129jk?id={hex_id}'
            r2 = requests.get(iframe_url, headers={**headers, 'Referer': url}, timeout=10)

            # Find embed.php URL (may contain &amp; — HTML unescape)
            embed_match = re.search(r'href="([^"]*embed\.php[^"]*)"', r2.text)
            if embed_match:
                embed_url = html.unescape(embed_match.group(1))
            else:
                # Direct construction as fallback
                embed_url = f'https://vid30s.com/embed.php?bucket=temporary&id={fid}'

            r3 = requests.get(embed_url, headers={**headers, 'Referer': iframe_url}, timeout=10)

            # Extract video source
            src_match = re.search(r'<source\s+[^>]*src="([^"]+)"', r3.text)
            if not src_match:
                src_match = re.search(r'(https?://[^"\'\\s<>]*vidi64[^"\'\\s<>]+)', r3.text)

            if src_match:
                dl_url = src_match.group(1)
                return {'url': dl_url, 'title': title, 'thumbnail': thumbnail,
                        'qualities': [{'label': 'Best', 'url': dl_url}]}

        # Strategy B: old pass_md5 (DoodStream fallback)
        token_m = re.search(r"/pass_md5/([^'\"\\s]+)", r.text)
        if token_m:
            token = token_m.group(1)
            import time, random, string
            r2 = requests.get(f'https://vid30s.com/pass_md5/{token}',
                headers={**headers, 'X-Requested-With': 'XMLHttpRequest'}, timeout=10)
            if r2.status_code == 200:
                cdn = r2.text.strip()
                if cdn:
                    random_chars = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
                    ts = int(time.time())
                    dl_url = f'{cdn}{random_chars}?token={token}&expiry={ts}'
                    return {'url': dl_url, 'title': title, 'thumbnail': thumbnail,
                            'qualities': [{'label': 'Best', 'url': dl_url}]}

        return None
    except Exception as e:
        print(f"[vid30s] {e}")
        return None