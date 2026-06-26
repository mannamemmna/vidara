import re, json, subprocess

# ─── Site Registry ────────────────────────────────────────────────────────────
SITES = []

def site(regex):
    """Decorator: register extractor function with URL regex."""
    def wrap(fn):
        SITES.append((re.compile(regex), fn))
        return fn
    return wrap

# ─── Shared Helpers ───────────────────────────────────────────────────────────
def _m3u8(html, embed_url=""):
    """Extract m3u8 URL from HTML: direct link > file attr > JS eval deobfuscation."""
    direct = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html)
    if direct:
        return direct[0]
    fa = re.search(r'"file"\s*:\s*"([^"]*\.m3u8[^"]*)"', html)
    if fa:
        return fa.group(1)
    try:
        idx = html.find('eval(function(p,a,c,k,e,d)')
        if idx < 0:
            return None
        depth, start = 0, idx + 4
        for i in range(start, len(html)):
            if html[i] == '(':
                depth += 1
            elif html[i] == ')':
                depth -= 1
                if depth == 0:
                    packed = html[start:i + 1]
                    break
        else:
            return None
        proc = subprocess.Popen(
            ['node', '-e',
             'process.stdin.on("data",d=>{var r=eval("("+d+")");process.stdout.write(r);})'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, _ = proc.communicate(input=packed, timeout=15)
        if not out:
            return None
        lm = re.search(r'links\s*=\s*(\{[^}]*"hls\d?"[^}]*\})', out)
        if lm:
            try:
                links = json.loads(lm.group(1))
                for k in ('hls4', 'hls3', 'hls2'):
                    if links.get(k):
                        return links[k]
            except:
                pass
        mm = re.findall(r"""['"]((?:https?://|/)[^\s'"<>]*master\.m3u8[^\s'"<>]*)['"]""", out)
        if mm:
            return mm[0]
    except:
        pass
    return None

def _abs(url, base):
    """Convert relative URL to absolute using base URL."""
    if not url:
        return url
    if url.startswith('//'):
        return 'https:' + url
    if url.startswith('/'):
        m = re.match(r'(https?://[^/]+)', base)
        return (m.group(1) if m else '') + url
    return url

# ─── Import extractors AFTER defining site() to avoid circular import ────────
from app.extractors import vidara, avtub, kurakura21, playmogo, vid30s  # noqa: E402, F401

def resolve(url):
    """Match URL against all registered sites -> (video_url, label)."""
    for regex, fn in SITES:
        m = regex.search(url)
        if m:
            try:
                return fn(url, m)
            except Exception as e:
                print(f"[extractor:{fn.__name__}] {e}")
                return None, f"error_{fn.__name__}"
    return None, None
