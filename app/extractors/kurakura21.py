"""kurakura21.com — WP AJAX → turtle4up.top AES-CBC decrypt."""
import re, json, requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from app.extractors import site, _m3u8, _abs
from app.config import HEADERS, AES_KEY, AES_IV

@site(r'https?://(?:www\.)?kurakura21\.com/[^/]+/?')
def extract(url, m):
    r = requests.get(url, headers={**HEADERS, 'Referer': 'https://kurakura21.com/'}, timeout=10)
    pm = re.search(r'data-id="(\d+)"', r.text)
    if not pm:
        print("[kurakura21] No data-id found")
        return None, 'kurakura21'
    pid = pm.group(1)
    r2 = requests.post('https://kurakura21.com/wp-admin/admin-ajax.php',
                       data={'action': 'muvipro_player_content', 'tab': 'p1', 'post_id': pid},
                       headers={**HEADERS, 'Referer': 'https://kurakura21.com/'}, timeout=10)
    im = re.search(r'iframe[^>]*src="([^"]*)"', r2.text)
    if not im:
        print(f"[kurakura21] No iframe for post_id={pid}")
        return None, f'kurakura21_{pid}'
    src = im.group(1)
    # Path 1: turtle4up.top with AES-CBC decryption
    hm = re.search(r'turtle4up\.top/#(.+)', src)
    if hm:
        vid = hm.group(1)
        r3 = requests.get(f'https://turtle4up.top/api/v1/video?id={vid}',
                          headers={**HEADERS, 'Referer': 'https://turtle4up.top/'}, timeout=10)
        c = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
        data = json.loads(unpad(c.decrypt(bytes.fromhex(r3.text.strip())), AES.block_size).decode())
        path = next((data[f] for f in ('hlsVideoTiktok', 'hlsVideoGoogle', 'cf', 'source')
                     if data.get(f) and isinstance(data[f], str) and data[f].strip()), None)
        if not path:
            print(f"[kurakura21] No video path in decrypted data")
            return None, f'kurakura21_{pid}'
        title = re.sub(r'[^a-zA-Z0-9_-]', '_', data.get('title', ''))[:50] or f'kurakura21_{pid}'
        return _abs(path, 'https://turtle4up.top'), title
    # Path 2: morencius.com / other embed
    if 'morencius.com' in src or 'embed/' in src:
        r3 = requests.get(src, headers={**HEADERS, 'Referer': url}, timeout=10)
        mu = _m3u8(r3.text, src)
        return _abs(mu, r3.url), f'kurakura21_{pid}'
    print(f"[kurakura21] Unknown embed src: {src}")
    return None, f'kurakura21_{pid}'
