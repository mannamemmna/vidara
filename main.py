import os, re, json, uuid, time, random, string, subprocess, threading, queue
import requests
from flask import Flask, render_template, request, jsonify, send_from_directory, url_for
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

app = Flask(__name__)
DL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
os.makedirs(DL_DIR, exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
AES_KEY, AES_IV = b"kiemtienmua911ca", b"1234567890oiuytr"

# ─── SITE REGISTRY ────────────────────────────────────────────────────────────
SITES = []

def site(regex):
    def wrap(fn):
        SITES.append((re.compile(regex), fn))
        return fn
    return wrap

# ─── PIPELINE: extract → download_url ────────────────────────────────────────
def _m3u8(html, embed_url=""):
    direct = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html)
    if direct: return direct[0]
    fa = re.search(r'"file"\s*:\s*"([^"]*\.m3u8[^"]*)"', html)
    if fa: return fa.group(1)
    try:
        idx = html.find('eval(function(p,a,c,k,e,d)')
        if idx < 0: return None
        depth, start = 0, idx + 4
        for i in range(start, len(html)):
            if html[i] == '(': depth += 1
            elif html[i] == ')':
                depth -= 1
                if depth == 0:
                    packed = html[start:i + 1]; break
        else: return None
        # Safe: stdin pipe, not f-string injection
        proc = subprocess.Popen(['node', '-e', 'process.stdin.on("data",d=>{var r=eval("("+d+")");process.stdout.write(r);});'],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, err = proc.communicate(input=packed, timeout=15)
        if not out: return None
        lm = re.search(r'links\s*=\s*(\{[^}]*"hls\d?"[^}]*\})', out)
        if lm:
            try:
                links = json.loads(lm.group(1))
                for k in ('hls4', 'hls3', 'hls2'):
                    if links.get(k): return links[k]
            except: pass
        mm = re.findall(r"""['"]((?:https?://|/)[^\s'"<>]*master\.m3u8[^\s'"<>]*)['"]""", out)
        if mm: return mm[0]
    except: pass
    return None

def _abs(url, base_embed):
    if not url: return url
    if url.startswith('//'): return 'https:' + url
    if url.startswith('/'):
        m = re.match(r'(https?://[^/]+)', base_embed)
        return (m.group(1) if m else '') + url
    return url

@site(r'https?://(?:www\.)?vidara\.(?:to|so)/v/([a-zA-Z0-9_-]+)')
def extract_vidara(url, m):
    fc = m.group(1)
    try:
        r = requests.post('https://vidaratem.co/api/stream',
                          json={'filecode': fc, 'device': 'web'}, headers=HEADERS, timeout=10)
        d = r.json()
        return d.get('streaming_url'), f'vidara_{fc}'
    except: pass
    return None, f'vidara_{fc}'

@site(r'https?://(?:www\.)?avtub\.cx/(\d+)/?')
def extract_avtub(url, m):
    pid = m.group(1)
    r = requests.get(url, headers=HEADERS, timeout=10)
    final_url = r.url
    # Follow redirect (avtub often redirects old IDs)
    if final_url != url:
        m2 = re.search(r'avtub\.cx/(\d+)/', final_url)
        if m2: pid = m2.group(1)
    iframe = re.search(r'<iframe[^>]+src="([^"]+)"', r.text, re.I)
    if not iframe: return None, f'avtub_{pid}'
    eu = iframe.group(1)
    r2 = requests.get(eu, headers={**HEADERS, 'Referer': final_url}, timeout=10)
    mu = _m3u8(r2.text, eu)
    return _abs(mu, r2.url), f'avtub_{pid}'

@site(r'https?://(?:www\.)?kurakura21\.com/[^/]+/?')
def extract_kurakura21(url, m):
    r = requests.get(url, headers={**HEADERS, 'Referer': 'https://kurakura21.com/'}, timeout=10)
    pm = re.search(r'data-id="(\d+)"', r.text)
    if not pm: return None, 'kurakura21'
    pid = pm.group(1)
    r2 = requests.post('https://kurakura21.com/wp-admin/admin-ajax.php',
                       data={'action': 'muvipro_player_content', 'tab': 'p1', 'post_id': pid},
                       headers={**HEADERS, 'Referer': 'https://kurakura21.com/'}, timeout=10)
    im = re.search(r'iframe[^>]*src="([^"]*)"', r2.text)
    if not im: return None, f'kurakura21_{pid}'
    src = im.group(1)
    hm = re.search(r'turtle4up\.top/#(.+)', src)
    if hm:
        vid = hm.group(1)
        r3 = requests.get(f'https://turtle4up.top/api/v1/video?id={vid}',
                          headers={**HEADERS, 'Referer': 'https://turtle4up.top/'}, timeout=10)
        c = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
        data = json.loads(unpad(c.decrypt(bytes.fromhex(r3.text.strip())), AES.block_size).decode())
        path = next((data[f] for f in ('hlsVideoTiktok', 'hlsVideoGoogle', 'cf', 'source')
                     if data.get(f) and isinstance(data[f], str) and data[f].strip()), None)
        if not path: return None, f'kurakura21_{pid}'
        title = re.sub(r'[^a-zA-Z0-9_-]', '_', data.get('title', ''))[:50] or f'kurakura21_{pid}'
        return _abs(path, 'https://turtle4up.top'), title
    if 'morencius.com' in src or 'embed/' in src:
        r3 = requests.get(src, headers={**HEADERS, 'Referer': url}, timeout=10)
        mu = _m3u8(r3.text, src)
        return _abs(mu, src), f'kurakura21_{pid}'
    return None, f'kurakura21_{pid}'

@site(r'https?://(?:www\.)?playmogo\.com/e/([a-zA-Z0-9]+)')
def extract_playmogo(url, m):
    fc = m.group(1)
    s = requests.Session()
    r = s.get(url, headers=HEADERS, timeout=10)
    mm = re.search(r'/pass_md5/([^\'"]+)', r.text)
    if not mm: return None, f'playmogo_{fc}'
    r2 = s.get(f'https://playmogo.com{mm.group(0)}',
               headers={**HEADERS, 'Referer': url, 'X-Requested-With': 'XMLHttpRequest'}, timeout=10)
    base = r2.text.strip()
    if base.startswith('<'): return None, f'playmogo_{fc}'
    token = mm.group(0).rstrip("'").split('/')[-1]
    rand = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
    return f'{base}{rand}?token={token}&expiry={int(time.time()*1000)}', f'playmogo_{fc}'

@site(r'https?://(?:www\.)?vid30s\.com/d/([a-zA-Z0-9]+)')
def extract_vid30s(url, m):
    fc = m.group(1)
    r = requests.get(f'https://vid30s.com/embed.php?bucket=temporary&id={fc}',
                     headers={**HEADERS, 'Referer': 'https://vid30s.com/'}, timeout=10)
    sm = re.search(r'<source\s+src="([^"]+)"', r.text)
    return (sm.group(1), f'vid30s_{fc}') if sm else (None, f'vid30s_{fc}')

def resolve(url):
    """Cocokkan URL dengan semua site → (video_url, label)."""
    for regex, fn in SITES:
        m = regex.search(url)
        if m:
            try: return fn(url, m)
            except Exception as e:
                print(f"[{fn.__name__}] {e}")
                return None, 'error'
    return None, None

# ─── DOWNLOAD QUEUE ──────────────────────────────────────────────────────────
MAX_CONCURRENT = 3
q = queue.Queue()
tasks = {}
lock = threading.Lock()
active = 0

def worker():
    global active
    while True:
        item = q.get()
        tid = item['tid']
        # Wait for slot
        while True:
            with lock:
                if active < MAX_CONCURRENT:
                    active += 1; break
            time.sleep(1)
        with lock:
            if tid in tasks: tasks[tid]['status'] = 'downloading'
        err = None
        try:
            cmd = ['yt-dlp', '--newline', '-f', 'best', '-o', item['out'],
                   '--no-check-certificates']
            dl = item['dl_url']
            if 'turtle4up.top' in dl: cmd += ['--referer', 'https://turtle4up.top/']
            elif 'morencius.com' in dl: cmd += ['--referer', 'https://morencius.com/']
            cmd.append(dl)
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
            pct = re.compile(r'\[download\]\s+([\d.]+)%')
            for line in proc.stdout:
                m = pct.search(line)
                if m:
                    try:
                        with lock:
                            if tid in tasks: tasks[tid]['progress'] = float(m.group(1))
                    except: pass
            proc.wait()
            if proc.returncode != 0 or not os.path.exists(item['out']):
                err = 'Download gagal'
        except Exception as e:
            err = str(e)
        with lock:
            active -= 1
            if tid in tasks:
                tasks[tid].update({'status': 'error' if err else 'done',
                                    'progress': 0 if err else 100,
                                    'error_msg': err} if err else {'status': 'done', 'progress': 100})
        q.task_done()

threading.Thread(target=worker, daemon=True).start()

def cleanup():
    while True:
        now = time.time()
        for f in os.listdir(DL_DIR):
            fp = os.path.join(DL_DIR, f)
            if os.path.isfile(fp) and os.stat(fp).st_mtime < now - 3600:
                try: os.remove(fp)
                except: pass
        time.sleep(600)
threading.Thread(target=cleanup, daemon=True).start()

# ─── ROUTES ──────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/start_download', methods=['POST'])
def start_download():
    url = (request.json or {}).get('url', '').strip()
    if not url: return jsonify({'error': 'URL diperlukan'}), 400
    dl_url, label = resolve(url)
    if not dl_url: return jsonify({'error': 'Gagal mengekstrak video. Cek URL atau coba lagi.'}), 400
    tid = str(uuid.uuid4())
    safe = re.sub(r'[^a-zA-Z0-9_-]', '_', label)[:50]
    fn = f'{safe}_{int(time.time())}.mp4'
    t = {'status': 'queued', 'progress': 0, 'filename': fn, 'dl_url': dl_url, 'label': safe, '_created': time.time()}
    with lock: tasks[tid] = t
    q.put({'tid': tid, 'dl_url': dl_url, 'out': os.path.join(DL_DIR, fn)})
    pos = 0
    with lock:
        for i, it in enumerate(list(q.queue)):
            if it['tid'] == tid: pos = i + 1; break
    return jsonify({'task_id': tid, 'queue_position': pos, 'max_concurrent': MAX_CONCURRENT, 'filename': fn})

@app.route('/api/status/<task_id>')
def check_status(task_id):
    with lock: t = tasks.get(task_id)
    if not t: return jsonify({'error': 'Task tidak ditemukan'}), 404
    r = {'status': t['status'], 'progress': t['progress'], 'filename': t.get('filename', '')}
    if t['status'] == 'done': r['download_url'] = url_for('download_file', filename=t['filename'])
    elif t['status'] == 'error': r['error_msg'] = t.get('error_msg', 'Unknown')
    return jsonify(r)

@app.route('/api/tasks')
def list_tasks():
    with lock:
        return jsonify({
            'tasks': [{'task_id': tid, 'status': t['status'], 'progress': t['progress'],
                        'filename': t.get('filename', ''), 'label': t.get('label', ''),
                        'error_msg': t.get('error_msg')}
                       for tid, t in sorted(tasks.items(), key=lambda x: x[1].get('_created', 0), reverse=True)[:50]],
            'max_concurrent': MAX_CONCURRENT})

@app.route('/downloads/<path:filename>')
def download_file(filename):
    path = os.path.normpath(os.path.join(DL_DIR, filename))
    if not path.startswith(DL_DIR): return 'Invalid path', 400
    if not os.path.exists(path): return jsonify({'error': 'File tidak ditemukan atau sudah dihapus (expired 1 jam)'}), 404
    return send_from_directory(DL_DIR, filename, as_attachment=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)