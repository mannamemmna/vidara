"""API routes: all endpoints for Vidara."""
import os, re, time, uuid
from functools import wraps
from flask import Blueprint, request, jsonify, render_template, send_from_directory, url_for
from app.config import DL_DIR, MAX_CONCURRENT
from app.extractors import resolve
from app import queue_manager as qm

bp = Blueprint('main', __name__)

# ─── API Key Auth (optional) ──────────────────────────────────────────────────
API_KEY = os.environ.get('VIDARA_API_KEY', '')

def require_api_key(f):
    """If VIDARA_API_KEY is set, require X-API-Key header or ?api_key= param."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not API_KEY:
            return f(*args, **kwargs)
        key = request.headers.get('X-API-Key') or request.args.get('api_key')
        if key != API_KEY:
            return jsonify({'error': 'Invalid or missing API key'}), 401
        return f(*args, **kwargs)
    return decorated

# ─── Helpers ──────────────────────────────────────────────────────────────────
def _safe_filename(title, ext='mp4'):
    """Generate safe unique filename from title."""
    safe = re.sub(r'[^a-zA-Z0-9_-]', '_', title or 'video')[:50]
    return f'{safe}_{uuid.uuid4().hex[:8]}.{ext}'

# ─── Pages ────────────────────────────────────────────────────────────────────
@bp.route('/')
def index():
    return render_template('index.html')

# ─── API: Start Download ─────────────────────────────────────────────────────
@bp.route('/api/start_download', methods=['POST'])
@require_api_key
def start_download():
    data = request.get_json(silent=True) or {}
    url = data.get('url', '').strip()
    audio_only = data.get('audio_only', False)
    webhook_url = data.get('webhook_url', '').strip()
    if not url:
        return jsonify({'error': 'URL diperlukan'}), 400

    result = resolve(url, audio_only=audio_only)
    if not result or not result.get('url'):
        return jsonify({'error': 'Gagal mengekstrak video. Cek URL atau coba lagi.'}), 400

    title = result.get('title', 'video')
    ext = 'mp3' if audio_only else 'mp4'
    fn = _safe_filename(title, ext)
    tid, pos = qm.enqueue(
        result['url'], fn, re.sub(r'[^a-zA-Z0-9_-]', '_', title)[:50],
        original_url=url,
        title=title,
        source=result.get('source', ''),
        audio_only=audio_only,
        webhook_url=webhook_url or None,
    )
    return jsonify({
        'task_id': tid, 'queue_position': pos, 'max_concurrent': MAX_CONCURRENT,
        'filename': fn, 'title': title, 'source': result.get('source', ''),
        'thumbnail': result.get('thumbnail', ''),
        'qualities': result.get('qualities', []),
    })

# ─── API: Video Info (preview) ───────────────────────────────────────────────
@bp.route('/api/info', methods=['POST'])
@require_api_key
def video_info():
    data = request.get_json(silent=True) or {}
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'error': 'URL diperlukan'}), 400
    result = resolve(url)
    if not result:
        return jsonify({'error': 'URL tidak didukung atau video tidak ditemukan'}), 400
    return jsonify({
        'title': result.get('title', ''),
        'thumbnail': result.get('thumbnail', ''),
        'qualities': result.get('qualities', []),
        'duration': result.get('duration', 0),
        'source': result.get('source', ''),
    })

# ─── API: Batch Download ─────────────────────────────────────────────────────
@bp.route('/api/batch', methods=['POST'])
@require_api_key
def batch_download():
    data = request.get_json(silent=True) or {}
    urls = data.get('urls', [])
    audio_only = data.get('audio_only', False)
    webhook_url = data.get('webhook_url', '').strip()
    if not urls or not isinstance(urls, list):
        return jsonify({'error': 'urls array diperlukan'}), 400
    if len(urls) > 20:
        return jsonify({'error': 'Maksimal 20 URL per batch'}), 400

    results = []
    for url in urls:
        url = url.strip()
        if not url:
            continue
        try:
            result = resolve(url, audio_only=audio_only)
            if result and result.get('url'):
                title = result.get('title', 'video')
                ext = 'mp3' if audio_only else 'mp4'
                fn = _safe_filename(title, ext)
                tid, pos = qm.enqueue(
                    result['url'], fn, re.sub(r'[^a-zA-Z0-9_-]', '_', title)[:50],
                    original_url=url,
                    title=title, source=result.get('source', ''),
                    audio_only=audio_only, webhook_url=webhook_url or None,
                )
                results.append({'url': url, 'task_id': tid, 'queue_position': pos,
                               'title': title, 'status': 'queued'})
            else:
                results.append({'url': url, 'error': 'Gagal extract — URL tidak didukung'})
        except Exception as e:
            results.append({'url': url, 'error': str(e)})
    return jsonify({'results': results, 'total': len(results)})

# ─── API: Quick (bookmarklet/extension) ──────────────────────────────────────
@bp.route('/api/quick')
@require_api_key
def quick_download():
    """GET /api/quick?url=... — for bookmarklet/extension."""
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'url param diperlukan'}), 400
    result = resolve(url)
    if not result or not result.get('url'):
        return jsonify({'error': 'Gagal extract'}), 400
    title = result.get('title', 'video')
    fn = _safe_filename(title, 'mp4')
    tid, pos = qm.enqueue(result['url'], fn, re.sub(r'[^a-zA-Z0-9_-]', '_', title)[:50],
                          original_url=url,
                          title=title, source=result.get('source', ''))
    return jsonify({'task_id': tid, 'queue_position': pos, 'title': title,
                    'status_url': f'/api/status/{tid}'})

# ─── API: Status ─────────────────────────────────────────────────────────────
@bp.route('/api/status/<task_id>')
@require_api_key
def check_status(task_id):
    t = qm.get_task(task_id)
    if not t:
        return jsonify({'error': 'Task tidak ditemukan'}), 404
    r = {
        'status': t['status'], 'progress': t['progress'],
        'filename': t.get('filename', ''), 'title': t.get('title', ''),
        'source': t.get('source', ''), 'speed': t.get('speed', ''),
        'eta': t.get('eta', ''), 'file_size': t.get('file_size', ''),
    }
    if t['status'] == 'done':
        r['download_url'] = url_for('main.download_file', filename=t['filename'])
    elif t['status'] == 'error':
        r['error_msg'] = t.get('error_msg', 'Unknown error')
    return jsonify(r)

# ─── API: Tasks List ─────────────────────────────────────────────────────────
@bp.route('/api/tasks')
@require_api_key
def list_tasks():
    return jsonify({'tasks': qm.get_all_tasks(), 'max_concurrent': MAX_CONCURRENT})

# ─── API: Stats (admin dashboard) ────────────────────────────────────────────
@bp.route('/api/stats')
@require_api_key
def get_stats():
    return jsonify(qm.get_stats())

# ─── API: Supported Sites ────────────────────────────────────────────────────
@bp.route('/api/sites')
def supported_sites():
    from app.extractors import SITES
    from app.extractors.generic import POPULAR_SITES
    sites = []
    for regex, fn in SITES:
        module = fn.__module__.split('.')[-1]
        sites.append({'name': module, 'pattern': regex.pattern, 'type': 'custom'})
    for s in POPULAR_SITES:
        sites.append({'name': s['name'], 'domain': s['domain'], 'icon': s['icon'], 'type': 'ytdlp'})
    return jsonify({'sites': sites, 'total': len(sites), 'custom': len(SITES), 'ytdlp': 1700})

# ─── API: Health ─────────────────────────────────────────────────────────────
@bp.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'max_concurrent': MAX_CONCURRENT})

# ─── Download File ───────────────────────────────────────────────────────────
@bp.route('/downloads/<path:filename>')
def download_file(filename):
    path = os.path.normpath(os.path.join(DL_DIR, filename))
    if not path.startswith(DL_DIR):
        return jsonify({'error': 'Invalid path'}), 400
    if not os.path.exists(path):
        return jsonify({'error': 'File tidak ditemukan atau sudah expired (1 jam)'}), 404
    return send_from_directory(DL_DIR, filename, as_attachment=True)
