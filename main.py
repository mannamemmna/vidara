import os
import re
import uuid
import time
import subprocess
import requests
import threading
from flask import Flask, render_template, request, jsonify, send_from_directory, url_for
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['DOWNLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__name__)), 'downloads')

# Pastikan folder downloads ada
os.makedirs(app.config['DOWNLOAD_FOLDER'], exist_ok=True)

# Regex to match vidara.to URLs
VIDARA_REGEX = re.compile(r'https?://(?:www\.)?vidara\.to/v/([a-zA-Z0-9_-]+)')

# In-memory progress tracker { task_id: {"status": "downloading|done|error", "progress": 50, "filename": "x.mp4", "url": "m3u8...", "error_msg": ""} }
tasks = {}

def extract_vidara_direct_link(url: str) -> str:
    match = VIDARA_REGEX.search(url)
    if not match:
        return None, None
        
    filecode = match.group(1)
    api_url = "https://vidaratem.co/api/stream"
    payload = {
        "filecode": filecode,
        "device": "web"
    }
    
    try:
        response = requests.post(api_url, json=payload, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = response.json()
        if "streaming_url" in data:
            return data["streaming_url"], filecode
    except Exception as e:
        print(f"Error extracting link: {e}")
    
    return None, filecode

def cleanup_old_files():
    """Hapus file yang sudah lebih dari 1 jam di folder downloads."""
    while True:
        now = time.time()
        for filename in os.listdir(app.config['DOWNLOAD_FOLDER']):
            filepath = os.path.join(app.config['DOWNLOAD_FOLDER'], filename)
            if os.path.isfile(filepath):
                # Hapus jika file berumur lebih dari 1 jam (3600 detik)
                if os.stat(filepath).st_mtime < now - 3600:
                    try:
                        os.remove(filepath)
                        print(f"Cleaned up old file: {filepath}")
                    except Exception as e:
                        print(f"Error removing {filepath}: {e}")
        time.sleep(600)  # Cek setiap 10 menit

# Mulai background thread untuk auto-cleanup
threading.Thread(target=cleanup_old_files, daemon=True).start()

def download_worker(task_id, m3u8_url, output_path):
    cmd = [
        "yt-dlp",
        "--newline",
        "-f", "best", # Ambil resolusi terbaik karena ngga ada limit 50mb lagi
        "-o", output_path,
        m3u8_url
    ]
    
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    
    percent_regex = re.compile(r'\[download\]\s+([\d\.]+)%')
    
    for line in process.stdout:
        match = percent_regex.search(line)
        if match:
            try:
                percent = float(match.group(1))
                tasks[task_id]["progress"] = percent
            except ValueError:
                pass
                
    process.wait()
    
    if process.returncode == 0 and os.path.exists(output_path):
        tasks[task_id]["status"] = "done"
        tasks[task_id]["progress"] = 100
    else:
        tasks[task_id]["status"] = "error"
        tasks[task_id]["error_msg"] = "Gagal mendownload menggunakan yt-dlp"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/start_download', methods=['POST'])
def start_download():
    data = request.json
    url = data.get('url')
    
    if not url:
        return jsonify({"error": "URL diperlukan"}), 400
        
    m3u8_url, filecode = extract_vidara_direct_link(url)
    
    if not m3u8_url:
        return jsonify({"error": "URL Vidara tidak valid atau video tidak ditemukan"}), 400
        
    task_id = str(uuid.uuid4())
    filename = f"vidara_{filecode}_{int(time.time())}.mp4"
    output_path = os.path.join(app.config['DOWNLOAD_FOLDER'], filename)
    
    tasks[task_id] = {
        "status": "downloading",
        "progress": 0,
        "filename": filename,
        "m3u8_url": m3u8_url
    }
    
    # Jalankan download di thread terpisah agar tidak memblokir HTTP request
    threading.Thread(target=download_worker, args=(task_id, m3u8_url, output_path)).start()
    
    return jsonify({"task_id": task_id, "m3u8_url": m3u8_url})

@app.route('/api/status/<task_id>')
def check_status(task_id):
    if task_id not in tasks:
        return jsonify({"error": "Task tidak ditemukan"}), 404
        
    task = tasks[task_id]
    
    response = {
        "status": task["status"],
        "progress": task["progress"]
    }
    
    if task["status"] == "done":
        response["download_url"] = url_for('download_file', filename=task["filename"])
    elif task["status"] == "error":
        response["error_msg"] = task.get("error_msg", "Unknown error")
        response["m3u8_url"] = task.get("m3u8_url")
        
    return jsonify(response)

@app.route('/downloads/<filename>')
def download_file(filename):
    return send_from_directory(app.config['DOWNLOAD_FOLDER'], filename, as_attachment=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)