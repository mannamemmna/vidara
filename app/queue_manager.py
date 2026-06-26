import os, re, time, threading, queue, subprocess
from app.config import DL_DIR, MAX_CONCURRENT, CLEANUP_MAX_AGE, CLEANUP_INTERVAL

tasks = {}       # {task_id: {...}}
lock = threading.Lock()
active = 0       # currently downloading count

# ─── Worker Thread ────────────────────────────────────────────────────────────
def _worker():
    global active
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
        err = None
        try:
            cmd = ['yt-dlp', '--newline', '-f', 'best', '-o', item['out'],
                   '--no-check-certificates']
            dl = item['dl_url']
            # Add referer based on domain
            for domain, referer in [
                ('turtle4up.top', 'https://turtle4up.top/'),
                ('morencius.com', 'https://morencius.com/'),
                ('vidi64.com', 'https://vid30s.com/'),
                ('playmogo.com', 'https://playmogo.com/'),
                ('vidaratem.co', 'https://vidara.to/'),
            ]:
                if domain in dl:
                    cmd += ['--referer', referer]
                    break
            cmd.append(dl)
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    universal_newlines=True)
            pct_re = re.compile(r'\[download\]\s+([\d.]+)%')
            for line in proc.stdout:
                m = pct_re.search(line)
                if m:
                    try:
                        with lock:
                            if tid in tasks:
                                tasks[tid]['progress'] = float(m.group(1))
                    except:
                        pass
            proc.wait()
            if proc.returncode != 0 or not os.path.exists(item['out']):
                err = 'Download gagal'
        except Exception as e:
            err = str(e)
        with lock:
            active -= 1
            if tid in tasks:
                if err:
                    tasks[tid].update({'status': 'error', 'progress': 0, 'error_msg': err})
                else:
                    tasks[tid].update({'status': 'done', 'progress': 100})
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
def enqueue(dl_url, filename, label):
    """Add download to queue. Returns task_id and queue position."""
    import uuid
    tid = str(uuid.uuid4())
    tasks[tid] = {
        'status': 'queued', 'progress': 0, 'filename': filename,
        'dl_url': dl_url, 'label': label, '_created': time.time()
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
        return tasks.get(task_id)

def get_all_tasks():
    with lock:
        return [
            {'task_id': tid, 'status': t['status'], 'progress': t['progress'],
             'filename': t.get('filename', ''), 'label': t.get('label', ''),
             'error_msg': t.get('error_msg')}
            for tid, t in sorted(tasks.items(), key=lambda x: x[1].get('_created', 0), reverse=True)[:50]
        ]
