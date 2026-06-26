"""Queue manager: multi-worker download queue with speed/ETA tracking.
Key design: re-extracts fresh streaming URL right before download (m3u8 tokens expire fast)."""
import os, re, time, uuid, threading, queue, subprocess, shutil, json, urllib.request
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

            # ── Re-extract fresh streaming URL (m3u8 tokens expire in ~30s) ──
            dl_url = item['dl_url']
            if original_url:
                try:
                    from app.extractors import resolve
                    fresh = resolve(original_url, audio_only=audio_only)
                    if fresh and fresh.get('url'):
                        dl_url = fresh['url']
                        print(f'[worker] Re-extracted fresh URL for {tid[:8]}')
                    else:
                        print(f'[worker] Re-extract returned empty, using cached URL')
                except Exception as e:
                    print(f'[worker] Re-extract failed: {e}, using cached URL')

            cmd = ['yt-dlp', '--newline', '--no-check-certificates', '--no-warnings']
            if audio_only:
                cmd += ['-x', '--audio-format', 'mp3', '--audio-quality', '0']
            cmd += ['-o', item['out']]

            # Add referer based on domain
            referers = [
                ('turtle4up.top', 'https://turtle4up.top/'),
                ('morencius.com', 'https://morencius.com/'),
                ('vidi64.com', 'https://vid30s.com/'),
                ('playmogo.com', 'https://playmogo.com/'),
                ('vidaratem.co', 'https://vidara.to/'),
                ('sprintcdn', 'https://ystream.id/'),
                ('s1q2105.com', 'https://vidara.to/'),
                ('es3.', 'https://vidara.to/'),
            ]
            for domain, referer in referers:
                if domain in dl_url:
                    cmd += ['--referer', referer]
                    break
            cmd.append(dl_url)

            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    universal_newlines=True)
            pct_re = re.compile(r'\[download\]\s+([\d.]+)%')
            size_re = re.compile(r'of\s+~?\s*([\d.]+\s*\w+)')
            speed_re = re.compile(r'at\s+([\d.]+\w+/s)')
            eta_re = re.compile(r'ETA\s+(\S+)')
            for line in proc.stdout:
                m = pct_re.search(line)
                if m:
                    try:
                        pct = float(m.group(1))
                        sm = size_re.search(line)
                        sp = speed_re.search(line)
                        em = eta_re.search(line)
                        with lock:
                            if tid in tasks:
                                tasks[tid]['progress'] = pct
                                if sm:
                                    tasks[tid]['file_size'] = sm.group(1)
                                if sp:
                                    tasks[tid]['speed'] = sp.group(1)
                                if em:
                                    tasks[tid]['eta'] = em.group(1)
                    except:
                        pass
            proc.wait()

            # Check success: file exists with content > 1KB
            if os.path.exists(item['out']) and os.path.getsize(item['out']) > 1024:
                pass  # Success
            else:
                # yt-dlp failed — try ffmpeg fallback for m3u8
                if os.path.exists(item['out']):
                    os.remove(item['out'])
                if '.m3u8' in dl_url:
                    try:
                        print(f'[worker] yt-dlp failed, trying ffmpeg for {tid[:8]}')
                        ffmpeg_cmd = ['ffmpeg', '-y', '-headers', 'Referer: https://vidara.to/\r\n',
                                      '-i', dl_url, '-c', 'copy', '-bsf:a', 'aac_adtstoasc',
                                      item['out']]
                        if audio_only:
                            ffmpeg_cmd = ['ffmpeg', '-y', '-headers', 'Referer: https://vidara.to/\r\n',
                                          '-i', dl_url, '-vn', '-acodec', 'libmp3lame', '-q:a', '0',
                                          item['out']]
                        fp = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=300)
                        if os.path.exists(item['out']) and os.path.getsize(item['out']) > 1024:
                            pass  # ffmpeg succeeded
                        else:
                            err = 'Download gagal (yt-dlp + ffmpeg keduanya gagal)'
                            if os.path.exists(item['out']):
                                os.remove(item['out'])
                    except Exception as e2:
                        err = f'Download gagal: {e2}'
                else:
                    err = 'Download gagal (file tidak ditemukan atau kosong)'
        except Exception as e:
            err = str(e)

        # Get final file size
        final_size = 0
        if not err and os.path.exists(item['out']):
            final_size = os.path.getsize(item['out'])

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
                if t['status'] == 'done':
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
    """Add download to queue. Returns (task_id, queue_position).
    Stores original_url for re-extraction before download (fresh tokens)."""
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
