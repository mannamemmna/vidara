"""kurakura21.com — WP AJAX → turtle4up.top AES-CBC decrypt."""
import re, json, requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from app.extractors import site, _m3u8, _abs
from app.config import HEADERS, AES_KEY, AES_IV

@site(r'https?://(?:www\.)?kurakura21\.com/[^/]+/?')
def extract(url, m):
    try:
        r = requests.get(url, headers={**HEADERS, 'Referer': 'https://kurakura21.com/'}, timeout=10)
        pm = re.search(r'data-id="(\d+)"', r.text)
        if not pm:
            return None
        post_id = pm.group(1)

        # Title
        tm = re.search(r'<title>([^<]+)</title>', r.text)
        title = tm.group(1).strip().replace(' - Kurakura21', '') if tm else f'kurakura21_{post_id}'

        # Thumbnail
        thumb_m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', r.text)
        thumbnail = thumb_m.group(1) if thumb_m else ''

        ajax = requests.post('https://kurakura21.com/wp-admin/admin-ajax.php',
            data=f'action=get_player&id={post_id}',
            headers={**HEADERS,
                'Referer': 'https://kurakura21.com/',
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-Requested-With': 'XMLHttpRequest'},
            timeout=10)
        enc_b64 = ajax.text.strip()

        enc = __import__('base64').b64decode(enc_b64)
        cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
        dec = unpad(cipher.decrypt(enc), AES.BlockSize)
        d = json.loads(dec.decode())

        mu = d.get('source') or d.get('file') or d.get('url')
        if not mu:
            for v in (d if isinstance(d, list) else [d]):
                if isinstance(v, dict):
                    mu = v.get('file') or v.get('source')
                    if mu:
                        break
        if mu:
            return {'url': _abs(mu, ajax.url), 'title': title, 'thumbnail': thumbnail}
        return None
    except Exception as e:
        print(f"[kurakura21] {e}")
        return None
