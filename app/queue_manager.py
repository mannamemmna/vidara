import os, re, time, threading, queue, subprocess, shutil, json, urllib.request
from app.config import DL_DIR, MAX_CONCURRENT, CLEANUP_MAX_AGE, CLEANUP_INTERVAL

tasks = {}       # {task_id: {...}}
lock = threading.Lock()
active = 0       # currently downloading count
stats = {
    'total_downloads': 0,
    'total_bytes': 0,
    'total_errors': 0,
    'started_at': time.time(),
}

# ─── Webhook ──────────────────────────────────────────────────────────────────
def _send_webhook(webhook_url, task):
    """POST task result to webhook URL."""
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

            cmd = ['yt-dlp', '--newline', '--no-check-certificates']
            if audio_only:
                cmd += ['-x', '--audio-format', 'mp3', '--audio-quality', '0']
            else:
                cmd += ['-f', 'best']
            cmd += ['-o', item['out']]

            # Add referer based on domain
            dl = item['dl_url']
            for domain, referer in [
                ('turtle4up.top', 'https://turtle4up.top/'),
                ('morencius.com', 'https://morencius.com/'),
                ('vidi64.com', 'https://vid30s.com/'),
                ('playmogo.com', 'https://playmogo.com/'),
                ('vidaratem.co', 'https://vidara.to/'),
                ('sprintcdn', 'https://ystream.id/'),
                ('s1q2105.com', 'https://vidara.to/'),
            ]:
                if domain in dl:
                    cmd += ['--referer', referer]
                    break
            cmd.append(dl)

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
            if proc.returncode != 0 or not os.path.exists(item['out']):
                err = 'Download gagal'
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

        # Send webhook notification
        if webhook_url:
            with lock:
                t = tasks.get(tid, {})
                if t['status'] == 'done':
                    t['download_url'] = f'/downloads/{t.get("filename", "")}'
                t['task_id'] = tid
            _send_webhook(webhook_url, t)

        _queue.task_done()

_queue = queue.Queue()
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
def enqueue(dl_url, filename, label, title='', source='', audio_only=False, webhook_url=None):
    """Add download to queue. Returns task_id and queue position."""
    import uuid
    tid = str(uuid.uuid4())
    tasks[tid] = {
        'status': 'queued', 'progress': 0, 'filename': filename,
        'dl_url': dl_url, 'label': label, '_created': time.time(),
        'title': title, 'source': source, 'audio_only': audio_only,
        'webhook_url': webhook_url, 'speed': '', 'eta': '',
        'file_size': '', 'file_size_bytes': 0,
    }
    _queue.put({'tid': tid, 'dl_url': dl_url, 'out': os.path.join(DL_DIR, filename)})
    # Count queue position
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
    """Return global stats."""
    disk_used = 0
    disk_files = 0
    try:
        for f in os.listdir(DL_DIR):
            fp = os.path.join(DL_DIR, f)
            if os.path.isfile(fp):
                disk_used += os.stat(fp).st_size
                disk_files += 1
    except:
        pass
    # Disk total
    total, used, free = shutil.disk_usage(DL_DIR) if os.path.exists(DL_DIR) else (0, 0, 0)
    with lock:
        queued = _queue.qsize()
        return {
            **stats,
            'active_downloads': active,
            'queued': queued,
            'disk_files': disk_files,
            'disk_used_mb': round(disk_used / 1048576, 1),
            'disk_total_gb': round(total / 1073741824, 1),
            'disk_free_gb': round(free / 1073741824, 1),
            'max_concurrent': MAX_CONCURRENT,
            'uptime_seconds': int(time.time() - stats['started_at']),
        }
