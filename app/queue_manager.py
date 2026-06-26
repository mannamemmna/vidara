"""Queue manager: multi-worker download queue with speed/ETA tracking.
Key design: re-extracts fresh streaming URL right before download (m3u8 tokens expire fast).
Includes retry with backoff for CDN failures."""
import os, re, time, uuid, threading, queue, subprocess, shutil, json, urllib.request
import requests
from app.config import DL_DIR, MAX_CONCURRENT, CLEANUP_MAX_AGE, CLEANUP_INTERVAL

# ─── State ────────────────────────────────────────────────────────────────────
tasks = {}
lock = threading.Lock()
active = 0
stats = {
    'total_downloads': 0,
    'total_bytes': 0,
    'total_errors': 0,
    'started_at': time.time(),
}

# ─── Webhook ──────────────────────────────────────────────────────────────────
def _send_webhook(webhook_url, task):
    if not webhook_url:
        return
    try:
        data = json.dumps({
            'task_id': task.get('task_id', ''),
            'status': task['status'],
            'filename': task.get('filename', ''),
            'progress': task.get('progress', 0),
            'download_url': task.get('download_url', ''),
            'error_msg': task.get('error_msg', ''),
            'title': task.get('title', ''),
            'source': task.get('source', ''),
        }).encode()
        req = urllib.request.Request(webhook_url, data=data,
            headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f'[webhook] Failed: {e}')

# ─── Helpers ──────────────────────────────────────────────────────────────────
def _get_referer(url):
    """Add referer to avoid CDN blocking."""
    refs = [
        ('turtle4up.top', 'https://turtle4up.top/'),
        ('morencius.com', 'https://morencius.com/'),
        ('vidi64.com', 'https://vid30s.com/'),
        ('playmogo.com', 'https://playmogo.com/'),
        ('vidaratem.co', 'https://vidara.to/'),
        ('sprintcdn', 'https://ystream.id/'),
        ('s1q2105.com', 'https://vidara.to/'),
        ('ystream.id', 'https://ystream.id/'),
    ]
    for domain, ref in refs:
        if domain in url:
            return ref
    return None

def _get_cdn_error(url):
    """Extract CDN hostname for error message."""
    try:
        from urllib.parse import urlparse
        return f'CDN: {urlparse(url).hostname}'
    except:
        return 'CDN timeout — coba video lain'

def _run_cmd(cmd, log_prefix=''):
    """Run a subprocess, yield parsed progress lines."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            universal_newlines=True)
    pct_re = re.compile(r'\[download\]\s+([\d.]+)%')
    size_re = re.compile(r'of\s+~?\s*([\d.]+\s*\w+)')
    speed_re = re.compile(r'at\s+([\d.]+\w+/s)')
    eta_re = re.compile(r'ETA\s+(\S+)')
    for line in proc.stdout:
        if log_prefix:
            print(f'[{log_prefix}] {line.rstrip()[:200]}')
        m = pct_re.search(line)
        if m:
            try:
                pct = float(m.group(1))
                sm = size_re.search(line)
                sp = speed_re.search(line)
                em = eta_re.search(line)
                yield (pct, sm.group(1) if sm else None,
                       sp.group(1) if sp else None, em.group(1) if em else None)
            except:
                pass
    proc.wait()

def _download_via_requests(dl_url, outpath, timeout=300):
    """Direct HTTP download (for direct MP4 links, not m3u8)."""
    try:
        r = requests.get(dl_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': _get_referer(dl_url) or 'https://vidara.to/',
        }, stream=True, timeout=30)
        if r.status_code != 200:
            return False
        total = int(r.headers.get('content-length', 0))
        downloaded = 0
        with open(outpath, 'wb') as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
        return os.path.getsize(outpath) > 1024
    except Exception as e:
        print(f'[requests_dl] {e}')
        return False

# ─── Worker Thread ────────────────────────────────────────────────────────────
def _worker():
    global active, stats
    while True:
        item = _queue.get()
        tid = item['tid']
        # Wait for available slot
        while True:
            with lock:
                if active < MAX_CONCURRENT:
                    active += 1
                    break
            time.sleep(1)
        with lock:
            if tid in tasks:
                tasks[tid]['status'] = 'downloading'
                tasks[tid]['started_at'] = time.time()

        err = None
        try:
            with lock:
                task = tasks.get(tid, {})
                audio_only = task.get('audio_only', False)
                original_url = task.get('original_url', '')
                dl_url = item['dl_url']
                outpath = item['out']

            # ── Re-extract fresh streaming URL (m3u8 tokens expire ~30s) ──
            max_retries = 3
            for attempt in range(max_retries):
                if original_url and attempt > 0:
                    try:
                        from app.extractors import resolve
                        fresh = resolve(original_url, audio_only=audio_only)
                        if fresh and fresh.get('url'):
                            dl_url = fresh['url']
                            print(f'[worker] Fresh URL attempt {attempt+1} for {tid[:8]}')
                    except Exception as e:
                        print(f'[worker] Re-extract error: {e}')

                # ── Strategy A: yt-dlp ──
                cmd = ['yt-dlp', '--newline', '--no-check-certificates', '--no-warnings']
                if audio_only:
                    cmd += ['-x', '--audio-format', 'mp3', '--audio-quality', '0']
                cmd += ['-o', outpath]
                ref = _get_referer(dl_url)
                if ref:
                    cmd += ['--referer', ref]
                cmd.append(dl_url)

                success = True
                for pct, fsize, spd, eta in _run_cmd(cmd, f'ytdlp/{tid[:8]}'):
                    with lock:
                        if tid in tasks:
                            tasks[tid]['progress'] = pct
                            if fsize:
                                tasks[tid]['file_size'] = fsize
                            if spd:
                                tasks[tid]['speed'] = spd
                            if eta:
                                tasks[tid]['eta'] = eta

                # Check success
                if os.path.exists(outpath) and os.path.getsize(outpath) > 1024:
                    success = True
                    err = None
                    break
                else:
                    if os.path.exists(outpath):
                        os.remove(outpath)
                    # ── Strategy B: ffmpeg for m3u8 ──
                    if '.m3u8' in dl_url:
                        try:
                            print(f'[worker] Attempt {attempt+1}: ffmpeg fallback for {tid[:8]}')
                            ff = ['ffmpeg', '-y']
                            if ref:
                                ff += ['-headers', f'Referer: {ref}\r\nUser-Agent: Mozilla/5.0\r\n']
                            ff += ['-i', dl_url, '-c', 'copy', '-bsf:a', 'aac_adtstoasc', outpath]
                            if audio_only:
                                ff = ['ffmpeg', '-y']
                                if ref:
                                    ff += ['-headers', f'Referer: {ref}\r\nUser-Agent: Mozilla/5.0\r\n']
                                ff += ['-i', dl_url, '-vn', '-acodec', 'libmp3lame', '-q:a', '0', outpath]
                            sp = subprocess.run(ff, capture_output=True, text=True, timeout=300)
                            if os.path.exists(outpath) and os.path.getsize(outpath) > 1024:
                                success = True
                                err = None
                                break
                        except Exception as e2:
                            print(f'[worker] ffmpeg error: {e2}')

                    # ── Strategy C: requests (direct MP4) ──
                    if '.mp4' in dl_url or '.m4v' in dl_url:
                        print(f'[worker] Attempt {attempt+1}: direct HTTP for {tid[:8]}')
                        if _download_via_requests(dl_url, outpath):
                            success = True
                            err = None
                            break

                    # If still failing, mark error after all retries
                    if attempt < max_retries - 1:
                        wait = 3 * (attempt + 1)
                        print(f'[worker] Retry {attempt+2}/{max_retries} in {wait}s for {tid[:8]}')
                        # Update progress to show retry
                        with lock:
                            if tid in tasks:
                                tasks[tid]['status'] = 'retrying'
                                tasks[tid]['progress'] = 0
                                tasks[tid]['speed'] = f'retry {attempt+2}/{max_retries}'
                        time.sleep(wait)
                    else:
                        err = f'Download gagal — server CDN (video host) sedang bermasalah untuk video ini. Coba lagi nanti atau cari link video lain. ({_get_cdn_error(dl_url)})'
                        if os.path.exists(outpath):
                            os.remove(outpath)

        except Exception as e:
            err = str(e)

        # Get final file size
        final_size = 0
        if not err and os.path.exists(outpath):
            final_size = os.path.getsize(outpath)

        with lock:
            active -= 1
            if tid in tasks:
                webhook_url = tasks[tid].get('webhook_url')
                if err:
                    tasks[tid].update({'status': 'error', 'progress': 0, 'error_msg': err})
                    stats['total_errors'] += 1
                else:
                    tasks[tid].update({
                        'status': 'done', 'progress': 100,
                        'file_size_bytes': final_size,
                    })
                    stats['total_downloads'] += 1
                    stats['total_bytes'] += final_size
            else:
                webhook_url = None

        if webhook_url:
            with lock:
                t = tasks.get(tid, {})
                if t.get('status') == 'done':
                    t['download_url'] = f'/downloads/{t.get("filename", "")}'
                t['task_id'] = tid
            _send_webhook(webhook_url, t)

        _queue.task_done()

# ─── Queue + Workers ──────────────────────────────────────────────────────────
_queue = queue.Queue()
for _ in range(MAX_CONCURRENT):
    threading.Thread(target=_worker, daemon=True).start()

# ─── Cleanup Thread ──────────────────────────────────────────────────────────
def _cleanup():
    while True:
        now = time.time()
        try:
            for f in os.listdir(DL_DIR):
                fp = os.path.join(DL_DIR, f)
                if os.path.isfile(fp) and os.stat(fp).st_mtime < now - CLEANUP_MAX_AGE:
                    os.remove(fp)
        except:
            pass
        time.sleep(CLEANUP_INTERVAL)

threading.Thread(target=_cleanup, daemon=True).start()

# ─── Public API ──────────────────────────────────────────────────────────────
def enqueue(dl_url, filename, label, original_url='', title='', source='', audio_only=False, webhook_url=None):
    """Add download to queue. Returns (task_id, queue_position)."""
    tid = str(uuid.uuid4())
    base, ext = os.path.splitext(filename)
    unique_fn = f'{base}_{uuid.uuid4().hex[:8]}{ext}'
    tasks[tid] = {
        'status': 'queued', 'progress': 0, 'filename': unique_fn,
        'dl_url': dl_url, 'original_url': original_url, 'label': label,
        '_created': time.time(), 'title': title, 'source': source,
        'audio_only': audio_only, 'webhook_url': webhook_url,
        'speed': '', 'eta': '', 'file_size': '', 'file_size_bytes': 0,
    }
    _queue.put({'tid': tid, 'dl_url': dl_url, 'out': os.path.join(DL_DIR, unique_fn)})
    pos = 0
    with lock:
        for i, it in enumerate(list(_queue.queue)):
            if it['tid'] == tid:
                pos = i + 1
                break
    return tid, pos

def get_task(task_id):
    with lock:
        t = tasks.get(task_id)
        if t and t['status'] == 'done':
            t['download_url'] = f'/downloads/{t.get("filename", "")}'
        return t

def get_all_tasks():
    with lock:
        return [
            {'task_id': tid, 'status': t['status'], 'progress': t['progress'],
             'filename': t.get('filename', ''), 'label': t.get('label', ''),
             'title': t.get('title', ''), 'source': t.get('source', ''),
             'speed': t.get('speed', ''), 'eta': t.get('eta', ''),
             'file_size': t.get('file_size', ''),
             'error_msg': t.get('error_msg')}
            for tid, t in sorted(tasks.items(), key=lambda x: x[1].get('_created', 0), reverse=True)[:50]
        ]

def get_stats():
    import requests  # local import for _download_via_requests
    disk_used = disk_files = 0
    try:
        for f in os.listdir(DL_DIR):
            fp = os.path.join(DL_DIR, f)
            if os.path.isfile(fp):
                disk_used += os.stat(fp).st_size
                disk_files += 1
    except:
        pass
    total, used, free = shutil.disk_usage(DL_DIR) if os.path.exists(DL_DIR) else (0, 0, 0)
    with lock:
        return {
            **stats,
            'active_downloads': active,
            'queued': _queue.qsize(),
            'disk_files': disk_files,
            'disk_used_mb': round(disk_used / 1048576, 1),
            'disk_total_gb': round(total / 1073741824, 1),
            'disk_free_gb': round(free / 1073741824, 1),
            'max_concurrent': MAX_CONCURRENT,
            'uptime_seconds': int(time.time() - stats['started_at']),
        }