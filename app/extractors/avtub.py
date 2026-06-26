"""avtub.cx — multi-source embed (ystream.id, morencius.com, etc.) → AES-256-GCM decrypt or m3u8."""
import re, json, base64, requests
from app.extractors import site
from app.config import HEADERS

try:
    from Crypto.Cipher import AES
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

def _b64url_decode(s):
    s = s.replace('-', '+').replace('_', '/')
    s += '=' * (4 - len(s) % 4)
    return base64.b64decode(s)

def _decrypt_ystream(video_code):
    """ystream.id: AES-256-GCM encrypted playback → m3u8 URL."""
    try:
        r = requests.get(f'https://ystream.id/api/videos/{video_code}/',
                         headers={**HEADERS, 'Referer': f'https://ystream.id/e/{video_code}/'},
                         timeout=10)
        data = r.json()
        pb = data.get('playback')
        if not pb or not pb.get('key_parts'):
            return None, {}

        if not HAS_CRYPTO:
            print('[avtub] pycryptodome not installed, cannot decrypt ystream.id')
            return None, {}

        ver = int(pb.get('version', '1'))
        indices = [ver, 31 - ver]
        selected = [pb['key_parts'][i - 1] for i in indices if 1 <= i <= len(pb['key_parts'])]
        key = b''.join(_b64url_decode(p) for p in selected)
        iv = _b64url_decode(pb['iv'])
        payload = _b64url_decode(pb['payload'])

        cipher = AES.new(key, AES.MODE_GCM, nonce=iv)
        plaintext = cipher.decrypt(payload)
        text = plaintext.decode('utf-8', errors='replace')
        m = re.search(r'\{.*\}', text)
        if not m:
            return None, {}
        sources = json.loads(m.group())
        best = sources.get('sources', [{}])[0] if sources.get('sources') else {}
        return best.get('url'), {
            'title': data.get('title', ''),
            'thumbnail': data.get('poster_url', ''),
            'qualities': [{'label': s.get('label', 'Unknown'), 'url': s.get('url')} for s in sources.get('sources', [])],
            'duration': data.get('duration_seconds', 0),
        }
    except Exception as e:
        print(f'[avtub] ystream decrypt error: {e}')
        return None, {}

def _extract_morencius(embed_url):
    """morencius.com: packed JS → m3u8."""
    try:
        r = requests.get(embed_url, headers={**HEADERS, 'Referer': 'https://avtub.cx/'}, timeout=10)
        from app.extractors import _m3u8, _abs
        mu = _m3u8(r.text, embed_url)
        return _abs(mu, r.url) if mu else None
    except Exception:
        return None

@site(r'https?://(?:www\.)?avtub\.cx/(\d+)(?:/[^/]*)?/?')
def extract(url, m):
    pid = m.group(1)
    try:
        r = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        final_url = r.url
        m2 = re.search(r'avtub\.cx/(\d+)', final_url)
        if m2:
            pid = m2.group(1)

        # Extract title from page
        title_m = re.search(r'<title>([^<]+)</title>', r.text)
        title = title_m.group(1).strip().replace(' - AVTub', '').strip() if title_m else f'avtub_{pid}'

        # Extract thumbnail
        thumb_m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', r.text)
        thumbnail = thumb_m.group(1) if thumb_m else ''

        iframe = re.search(r'<iframe[^>]+src="([^"]+)"', r.text, re.I)
        if not iframe:
            print(f"[avtub] No iframe found for pid={pid}")
            return None
        eu = iframe.group(1)

        # Detect source
        if 'ystream.id' in eu:
            code_m = re.search(r'/e/([a-zA-Z0-9_]+)', eu)
            if code_m:
                video_url, meta = _decrypt_ystream(code_m.group(1))
                if video_url:
                    return {
                        'url': video_url,
                        'title': meta.get('title', title),
                        'thumbnail': meta.get('thumbnail', thumbnail),
                        'qualities': meta.get('qualities', []),
                        'duration': meta.get('duration', 0),
                    }
        elif 'morencius.com' in eu:
            video_url = _extract_morencius(eu)
            if video_url:
                return {'url': video_url, 'title': title, 'thumbnail': thumbnail}
        else:
            # Generic: try m3u8 extraction
            r2 = requests.get(eu, headers={**HEADERS, 'Referer': final_url}, timeout=10)
            from app.extractors import _m3u8, _abs
            mu = _m3u8(r2.text, eu)
            if mu:
                return {'url': _abs(mu, r2.url), 'title': title, 'thumbnail': thumbnail}

        print(f"[avtub] Could not extract video from {eu}")
        return None
    except Exception as e:
        print(f"[avtub] Error: {e}")
        return None
