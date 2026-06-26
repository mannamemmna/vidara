import os, re
from flask import Blueprint, request, jsonify, render_template, send_from_directory, url_for
from app.config import DL_DIR, MAX_CONCURRENT
from app.extractors import resolve
from app import queue_manager as qm

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    return render_template('index.html')

@bp.route('/api/start_download', methods=['POST'])
def start_download():
    data = request.get_json(silent=True) or {}
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'error': 'URL diperlukan'}), 400
    dl_url, label = resolve(url)
    if not dl_url:
        return jsonify({'error': f'Gagal mengekstrak video dari URL tersebut. Pastikan URL valid dan didukung.'}), 400
    safe = re.sub(r'[^a-zA-Z0-9_-]', '_', label)[:50]
    fn = f'{safe}_{int(__import__("time").time())}.mp4'
    tid, pos = qm.enqueue(dl_url, fn, safe)
    return jsonify({'task_id': tid, 'queue_position': pos, 'max_concurrent': MAX_CONCURRENT, 'filename': fn})

@bp.route('/api/status/<task_id>')
def check_status(task_id):
    t = qm.get_task(task_id)
    if not t:
        return jsonify({'error': 'Task tidak ditemukan'}), 404
    r = {'status': t['status'], 'progress': t['progress'], 'filename': t.get('filename', '')}
    if t['status'] == 'done':
        r['download_url'] = url_for('main.download_file', filename=t['filename'])
    elif t['status'] == 'error':
        r['error_msg'] = t.get('error_msg', 'Unknown error')
    return jsonify(r)

@bp.route('/api/tasks')
def list_tasks():
    return jsonify({'tasks': qm.get_all_tasks(), 'max_concurrent': MAX_CONCURRENT})

@bp.route('/downloads/<path:filename>')
def download_file(filename):
    path = os.path.normpath(os.path.join(DL_DIR, filename))
    if not path.startswith(DL_DIR):
        return jsonify({'error': 'Invalid path'}), 400
    if not os.path.exists(path):
        return jsonify({'error': 'File tidak ditemukan atau sudah expired (1 jam)'}), 404
    return send_from_directory(DL_DIR, filename, as_attachment=True)

@bp.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'max_concurrent': MAX_CONCURRENT})
