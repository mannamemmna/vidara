import os, re, json, uuid, time, random, string, subprocess, threading, queue
import requests
from flask import Flask, render_template, request, jsonify, send_from_directory, url_for
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

app = Flask(__name__)
DL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
os.makedirs(DL_DIR, exist_ok=True)

# ─── REGEX ────────────────────────────────────────────────────────────────────
VIDARA_REGEX       = re.compile(r'https?://(?:www\.)?vidara\.(?:to|so)/v/([a-zA-Z0-9_-]+)')
AVTUB_REGEX        = re.compile(r'https?://(?:www\.)?avtub\.cx/(\d+)/?([^/]*)?/?')
KURAKURA21_REGEX   = re.compile(r'https?://(?:www\.)?kurakura21\.com/[^/]+/?')
PLAYMOGO_REGEX     = re.compile(r'https?://(?:www\.)?playmogo\.com/e/([a-zA-Z0-9]+)')
VID30S_REGEX       = re.compile(r'https?://(?:www\.)?vid30s\.com/d/([a-zA-Z0-9]+)')

# ─── TURTLE4UP AES ────────────────────────────────────────────────────────────
TURTLE_KEY = "kiemtienmua911ca".encode()
TURTLE_IV  = "1234567890oiuytr".encode()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ─── MULTI-USER DOWNLOAD QUEUE ────────────────────────────────────────────────
MAX_CONCURRENT = 3       # download berapa banyak dalam satu waktu
download_queue = queue.Queue()
active_downloads = {}    # {task_id: {...}} — yang sedang/selesai
active_count = 0
queue_lock = threading.Lock()

def queue_worker():
    """Background worker: ambil task dari queue, download, update status."""
    global active_count
    while True:
        task = download_queue.get()
        tid = task['tid']
        with queue_lock:
            if tid in active_downloads:
                active_downloads[tid]['status'] = 'queued'
        # Tunggu giliran: max MAX_CONCURRENT berjalan bersamaan
        while True:
            with queue_lock:
                if active_count < MAX_CONCURRENT:
                    active_count += 1
                    break
            time.sleep(1)

        with queue_lock:
            if tid in active_downloads:
                active_downloads[tid]['status'] = 'downloading'
                active_downloads[tid]['progress'] = 0

        # ── Download ──
        url     = task['url']
        out     = task['out']
        dl_url  = task['dl_url']
        err_msg = None
        try:
            cmd = ['yt-dlp', '--newline', '-f', 'best',
                   '-o', out, '--no-check-certificates']
            if 'turtle4up.top' in dl_url:
                cmd += ['--referer', 'https://turtle4up.top/']
            elif 'morencius.com' in dl_url:
                cmd += ['--referer', 'https://morencius.com/']
            cmd.append(dl_url)

            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True)
            pct_re = re.compile(r'\[download\]\s+([\d\.]+)%')
            for line in proc.stdout:
                m = pct_re.search(line)
                if m:
                    try:
                        pct = float(m.group(1))
                        with queue_lock:
                            if tid in active_downloads:
                                active_downloads[tid]['progress'] = pct
                    except ValueError:
                        pass
            proc.wait()
            if proc.returncode != 0 or not os.path.exists(out):
                err_msg = 'Download gagal'
        except Exception as e:
            err_msg = str(e)

        with queue_lock:
            active_count -= 1
            if tid in active_downloads:
                if err_msg:
                    active_downloads[tid]['status'] = 'error'
                    active_downloads[tid]['error_msg'] = err_msg
                else:
                    active_downloads[tid]['status'] = 'done'
                    active_downloads[tid]['progress'] = 100
                    active_downloads[tid]['filename'] = os.path.basename(out)
        download_queue.task_done()

threading.Thread(target=queue_worker, daemon=True).start()

# ─── FILE CLEANUP ─────────────────────────────────────────────────────────────
def cleanup_loop():
    while True:
        now = time.time()
        for f in os.listdir(DL_DIR):
            fp = os.path.join(DL_DIR, f)
            if os.path.isfile(fp) and os.stat(fp).st_mtime < now - 3600:
                try: os.remove(fp)
                except: pass
        time.sleep(600)
threading.Thread(target=cleanup_loop, daemon=True).start()

# ═══════════════════════════════════════════════════════════════════════════════
# SITE EXTRACTORS
# ═══════════════════════════════════════════════════════════════════════════════

def extract_vidara(url):
    m = VIDARA_REGEX.search(url)
    if not m: return None, 'vidara'
    fc = m.group(1)
    try:
        r = requests.post('https://vidaratem.co/api/stream',
                          json={'filecode': fc, 'device': 'web'},
                          headers=HEADERS, timeout=10)
        d = r.json()
        if 'streaming_url' in d:
            return d['streaming_url'], f'vidara_{fc}'
    except: pass
    return None, f'vidara_{fc}'

def extract_avtub(url):
    m = AVTUB_REGEX.search(url)
    if not m: return None, 'avtub'
    pid = m.group(1)
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        iframe = re.search(r'<iframe[^>]+src="([^"]+)"', r.text, re.I)
        if not iframe: return None, f'avtub_{pid}'
        eu = iframe.group(1)
        r2 = requests.get(eu, headers={**HEADERS, 'Referer': url}, timeout=10)
        mu = _extract_m3u8(r2.text, eu)
        if mu:
            if mu.startswith('/'):
                dom = re.match(r'(https?://[^/]+)', eu)
                mu = (dom.group(1) if dom else '') + mu
            return mu, f'avtub_{pid}'
    except: pass
    return None, f'avtub_{pid}'

def decrypt_turtle(hex_data):
    c = AES.new(TURTLE_KEY, AES.MODE_CBC, TURTLE_IV)
    return json.loads(unpad(c.decrypt(bytes.fromhex(hex_data.strip())), AES.block_size).decode())

def extract_kurakura21(url):
    if not KURAKURA21_REGEX.search(url): return None, 'kurakura21'
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        pm = re.search(r'data-id="(\d+)"', r.text)
        if not pm: return None, 'kurakura21'
        pid = pm.group(1)
        r2 = requests.post('https://kurakura21.com/wp-admin/admin-ajax.php',
                           data={'action': 'muvipro_player_content', 'tab': 'p1', 'post_id': pid},
                           headers=HEADERS, timeout=10)
        im = re.search(r'iframe[^>]*src="([^"]*)"', r2.text)
        if not im: return None, f'kurakura21_{pid}'
        src = im.group(1)
        hm = re.search(r'turtle4up\.top/#(.+)', src)
        if not hm:
            if 'morencius.com' in src or 'embed/' in src:
                r3 = requests.get(src, headers={**HEADERS, 'Referer': url}, timeout=10)
                mu = _extract_m3u8(r3.text, src)
                if mu:
                    if mu.startswith('/'):
                        dom = re.match(r'(https?://[^/]+)', src)
                        mu = (dom.group(1) if dom else '') + mu
                    return mu, f'kurakura21_{pid}'
            return None, f'kurakura21_{pid}'
        vid = hm.group(1)
        r3 = requests.get(f'https://turtle4up.top/api/v1/video?id={vid}',
                          headers={**HEADERS, 'Referer': 'https://turtle4up.top/'}, timeout=10)
        data = decrypt_turtle(r3.text)
        path = None
        for f in ['hlsVideoTiktok', 'hlsVideoGoogle', 'cf', 'source']:
            v = data.get(f, '')
            if v and isinstance(v, str) and v.strip():
                path = v.strip(); break
        if not path: return None, f'kurakura21_{pid}'
        if path.startswith('//'): mu = 'https:' + path
        elif path.startswith('/'): mu = 'https://turtle4up.top' + path
        else: mu = path
        title = data.get('title', f'kurakura21_{pid}')
        safe = re.sub(r'[^a-zA-Z0-9_-]', '_', title)[:50]
        return mu, f'kurakura21_{safe}'
    except: pass
    return None, 'kurakura21'

def extract_playmogo(url):
    m = PLAYMOGO_REGEX.search(url)
    if not m: return None, None, 'playmogo'
    fc = m.group(1)
    try:
        s = requests.Session()
        r = s.get(url, headers=HEADERS, timeout=10)
        mm = re.search(r"/pass_md5/([^'\"]+)", r.text)
        if not mm: return None, None, f'playmogo_{fc}'
        md5_url = f'https://playmogo.com{mm.group(0)}'
        r2 = s.get(md5_url, headers={**HEADERS, 'Referer': url, 'X-Requested-With': 'XMLHttpRequest'}, timeout=10)
        base = r2.text.strip()
        if base.startswith('<'): return None, None, f'playmogo_{fc}'
        token = mm.group(0).rstrip("'").split('/')[-1]
        return base, token, f'playmogo_{fc}'
    except: pass
    return None, None, f'playmogo_{fc}'

def extract_vid30s(url):
    m = VID30S_REGEX.search(url)
    if not m: return None, 'vid30s'
    fc = m.group(1)
    try:
        r = requests.get(f'https://vid30s.com/embed.php?bucket=temporary&id={fc}',
                         headers=HEADERS, timeout=10)
        sm = re.search(r'<source\s+src="([^"]+)"', r.text)
        if sm: return sm.group(1), f'vid30s_{fc}'
    except: pass
    return None, f'vid30s_{fc}'

def _extract_m3u8(html, embed_url=''):
    # Method 1: m3u8 in HTML
    d = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html)
    if d: return d[0]
    # Method 2: "file": "xxx.m3u8"
    fa = re.search(r'"file"\s*:\s*"([^"]*\.m3u8[^"]*)"', html)
    if fa: return fa.group(1)
    # Method 3: JS deobfuscation
    try:
        idx = html.find('eval(function(p,a,c,k,e,d)')
        if idx < 0: return None
        depth = 0
        start = idx + 4
        for i in range(start, len(html)):
            if html[i] == '(': depth += 1
            elif html[i] == ')':
                depth -= 1
                if depth == 0:
                    packed = html[start:i+1]; break
        else: return None
        node = f'var result = {packed}; process.stdout.write(result);'
        r = subprocess.run(['node', '-e', node], capture_output=True, text=True, timeout=15)
        out = r.stdout
        if not out: return None
        lm = re.search(r'links\s*=\s*(\{[^}]*"hls\d?"\s*:\s*"[^"]*"[^}]*\})', out)
        if lm:
            try:
                links = json.loads(lm.group(1))
                for k in ('hls4','hls3','hls2'):
                    if k in links and links[k]: return links[k]
            except: pass
        mm = re.findall(r"['\"]((?:https?://|/)[^\s'\"<>]*master\.m3u8[^\s'\"<>]*)['\"]", out)
        if mm: return mm[0]
    except: pass
    return None

def resolve_video_url(url):
    """Extract download URL + label from any supported site."""
    if VIDARA_REGEX.search(url):
        return extract_vidara(url)
    elif AVTUB_REGEX.search(url):
        return extract_avtub(url)
    elif KURAKURA21_REGEX.search(url):
        return extract_kurakura21(url)
    elif PLAYMOGO_REGEX.search(url):
        base, token, label = extract_playmogo(url)
        if token:
            rand = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
            return f'{base}{rand}?token={token}&expiry={int(time.time()*1000)}', label
        return None, label
    elif VID30S_REGEX.search(url):
        return extract_vid30s(url)
    return None, None

# ═══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/start_download', methods=['POST'])
def start_download():
    """Submit URL → extract → queue download → return task_id."""
    url = (request.json or {}).get('url', '').strip()
    if not url:
        return jsonify({'error': 'URL diperlukan'}), 400

    # Extract video source
    dl_url, label = resolve_video_url(url)
    if not dl_url:
        return jsonify({'error': 'Gagal mengekstrak video. Cek URL atau coba lagi.'}), 400

    tid = str(uuid.uuid4())
    safe = re.sub(r'[^a-zA-Z0-9_-]', '_', label)[:50]
    filename = f'{safe}_{int(time.time())}.mp4'
    out_path = os.path.join(DL_DIR, filename)

    task = {
        'status': 'queued',
        'progress': 0,
        'filename': filename,
        'dl_url': dl_url,
        'url': url,
        'label': safe,
    }
    with queue_lock:
        active_downloads[tid] = task

    download_queue.put({'tid': tid, 'url': url, 'dl_url': dl_url, 'out': out_path})

    # Info queue position
    pos = 0
    with queue_lock:
        pending = list(download_queue.queue)
        for i, t in enumerate(pending):
            if t['tid'] == tid:
                pos = i + 1
                break

    return jsonify({
        'task_id': tid,
        'queue_position': pos,
        'max_concurrent': MAX_CONCURRENT,
        'filename': filename,
    })

@app.route('/api/status/<task_id>')
def check_status(task_id):
    with queue_lock:
        task = active_downloads.get(task_id)
    if not task:
        return jsonify({'error': 'Task tidak ditemukan'}), 404

    resp = {
        'status': task['status'],
        'progress': task['progress'],
        'filename': task.get('filename', ''),
    }
    if task['status'] == 'done':
        resp['download_url'] = url_for('download_file', filename=task['filename'])
    elif task['status'] == 'error':
        resp['error_msg'] = task.get('error_msg', 'Unknown error')

    # Queue position
    pos = 0
    with queue_lock:
        for i, t in enumerate(list(download_queue.queue)):
            if t['tid'] == task_id:
                pos = i + 1
                break
    resp['queue_position'] = pos

    return jsonify(resp)

@app.route('/api/tasks')
def list_tasks():
    """Return all tasks (ringkasan)."""
    with queue_lock:
        result = []
        for tid, t in sorted(active_downloads.items(),
                             key=lambda x: x[1].get('_created', 0), reverse=True):
            result.append({
                'task_id': tid,
                'status': t['status'],
                'progress': t['progress'],
                'filename': t.get('filename', ''),
                'label': t.get('label', ''),
                'error_msg': t.get('error_msg'),
            })
    return jsonify({'tasks': result[:50], 'max_concurrent': MAX_CONCURRENT})

@app.route('/downloads/<filename>')
def download_file(filename):
    return send_from_directory(DL_DIR, filename, as_attachment=True)

# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)