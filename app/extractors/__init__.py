import re, json, subprocess

# ─── Site Registry ────────────────────────────────────────────────────────────
SITES = []

def site(regex):
    """Decorator: register extractor function with URL regex."""
    def wrapper(fn):
        SITES.append((re.compile(regex, re.I), fn))
        return fn
    return wrapper

# ─── Shared Helpers ───────────────────────────────────────────────────────────

def _m3u8(html, embed_url=""):
    """Extract m3u8 URL from HTML."""
    direct = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html)
    if direct:
        return direct[0]
    fa = re.search(r'"file"\s*:\s*"([^"]*\.m3u8[^"]*)"', html)
    if fa:
        return fa.group(1)
    packed = _packed(html)
    if not packed:
        return None
    try:
        r = subprocess.run(['node', '-e', 'process.stdout.write(require("child_process").execSync("node -e "+process.argv[1]).toString())', packed],
            capture_output=True, text=True, timeout=15)
        urls = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', r.stdout)
        return urls[0] if urls else None
    except Exception:
        return None

def _packed(html):
    """Extract packed JS from eval(function(p,a,c,k,e,d)) blocks."""
    for m in re.finditer(r'eval\(function\(p,a,c,k,e,d\)\{.+?\}\((.+?)\)\)', html, re.S):
        parts = m.group(1)
        qm = re.match(r"'(.+?)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'(.+?)'", parts, re.S)
        if qm:
            return parts
    return None

def _abs(url, base):
    """Make URL absolute."""
    if not url:
        return None
    if url.startswith('//'):
        return 'https:' + url
    if url.startswith('/'):
        from urllib.parse import urlparse
        p = urlparse(base)
        return f'{p.scheme}://{p.netloc}{url}'
    return url

# ─── Resolve Function ─────────────────────────────────────────────────────────

def resolve(url, audio_only=False):
    """
    Match URL to site extractor.
    Returns dict: {url, title, thumbnail, qualities, duration, source, audio_only}
    or None if no match / extraction failed.
    """
    for regex, fn in SITES:
        m = regex.search(url)
        if m:
            try:
                result = fn(url, m)
            except Exception as e:
                print(f'[extractor] {fn.__module__} error: {e}')
                result = None
            if result and result.get('url'):
                result.setdefault('source', fn.__module__.split('.')[-1])
                result.setdefault('title', result['source'])
                result['audio_only'] = audio_only
                return result
            return None
    # ─── Fallback: yt-dlp (supports 1700+ sites) ─────────────────────────
    from app.extractors.generic import extract_generic
    result = extract_generic(url)
    if result and result.get('url'):
        result['audio_only'] = audio_only
        return result
    return None

# ─── Import Extractors (triggers @site registration) ──────────────────────────
from app.extractors import vidara, avtub, kurakura21, playmogo, vid30s
