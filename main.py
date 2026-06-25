import os
import re
import json
import uuid
import time
import subprocess
import requests
import threading
from flask import Flask, render_template, request, jsonify, send_from_directory, url_for, Response, stream_with_context
from urllib.parse import quote as url_quote
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

app = Flask(__name__)
app.config['DOWNLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__name__)), 'downloads')

os.makedirs(app.config['DOWNLOAD_FOLDER'], exist_ok=True)

VIDARA_REGEX = re.compile(r'https?://(?:www\.)?vidara\.to/v/([a-zA-Z0-9_-]+)')
AVTUB_REGEX = re.compile(r'https?://(?:www\.)?avtub\.cx/(\d+)/?([^/]*)?/?')
KURAKURA21_REGEX = re.compile(r'https?://(?:www\.)?kurakura21\.com/[^/]+/?')

# Turtle4up.top AES-CBC decryption constants (static for all videos)
TURTLE4UP_KEY = "kiemtienmua911ca".encode('utf-8')
TURTLE4UP_IV = "1234567890oiuytr".encode('utf-8')

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

tasks = {}

# ─── SITE-SPECIFIC EXTRACTORS ────────────────────────────────────────────────

def extract_vidara_link(url):
    """Extract m3u8 URL from vidara.to"""
    match = VIDARA_REGEX.search(url)
    if not match:
        return None, "vidara"
    filecode = match.group(1)
    try:
        resp = requests.post("https://vidaratem.co/api/stream",
                             json={"filecode": filecode, "device": "web"},
                             headers=HEADERS, timeout=10)
        data = resp.json()
        if "streaming_url" in data:
            return data["streaming_url"], f"vidara_{filecode}"
    except Exception as e:
        print(f"Vidara extract error: {e}")
    return None, f"vidara_{filecode}"


def extract_avtub_link(url):
    """Extract m3u8 URL from avtub.cx via morencius.com embed"""
    match = AVTUB_REGEX.search(url)
    if not match:
        return None, "avtub"
    post_id = match.group(1)

    try:
        # 1. Fetch the avtub.cx video page
        resp = requests.get(url, headers=HEADERS, timeout=10)
        html = resp.text

        # 2. Find the embed iframe URL
        iframe_match = re.search(
            r'<IFRAME\s+SRC="(https?://[^"]+/embed/[^"]+)"', html, re.IGNORECASE
        )
        if not iframe_match:
            iframe_match = re.search(
                r'<iframe[^>]+src="(https?://[^"]+/embed/[^"]+)"', html, re.IGNORECASE
            )
        if not iframe_match:
            return None, f"avtub_{post_id}"

        embed_url = iframe_match.group(1)

        # 3. Fetch the embed page
        resp2 = requests.get(embed_url, headers={**HEADERS, "Referer": url}, timeout=10)
        embed_html = resp2.text

        # 4. Extract m3u8 from embed page
        m3u8_url = extract_m3u8_from_embed(embed_html, embed_url)

        if m3u8_url:
            # Make relative URLs absolute
            if m3u8_url.startswith('/'):
                domain_match = re.match(r'(https?://[^/]+)', embed_url)
                embed_domain = domain_match.group(1) if domain_match else ""
                m3u8_url = embed_domain + m3u8_url
            return m3u8_url, f"avtub_{post_id}"

    except Exception as e:
        print(f"Avtub extract error: {e}")

    return None, f"avtub_{post_id}"


def decrypt_turtle4up(encrypted_hex):
    """Decrypt AES-CBC encrypted response from turtle4up.top"""
    encrypted = bytes.fromhex(encrypted_hex.strip())
    cipher = AES.new(TURTLE4UP_KEY, AES.MODE_CBC, TURTLE4UP_IV)
    decrypted = unpad(cipher.decrypt(encrypted), AES.block_size)
    return json.loads(decrypted.decode('utf-8'))


def extract_kurakura21_link(url):
    """Extract m3u8 URL from kurakura21.com via turtle4up.top encrypted embed"""
    if not KURAKURA21_REGEX.search(url):
        return None, "kurakura21"

    try:
        # 1. Fetch kurakura21 page to get post ID
        resp = requests.get(url, headers=HEADERS, timeout=10)
        post_match = re.search(r'data-id="(\d+)"', resp.text)
        if not post_match:
            return None, "kurakura21"
        post_id = post_match.group(1)

        # 2. AJAX to get iframe embed URL
        resp2 = requests.post(
            "https://kurakura21.com/wp-admin/admin-ajax.php",
            data={"action": "muvipro_player_content", "tab": "p1", "post_id": post_id},
            headers=HEADERS, timeout=10
        )
        iframe_match = re.search(r'iframe[^>]*src="([^"]*)"', resp2.text)
        if not iframe_match:
            return None, f"kurakura21_{post_id}"

        iframe_src = iframe_match.group(1)

        # 3. Extract video ID from turtle4up.top URL
        hash_match = re.search(r'turtle4up\.top/#(.+)', iframe_src)
        if not hash_match:
            # Check if it's a morencius.com or other embed
            if "morencius.com" in iframe_src or "embed/" in iframe_src:
                # Fall through to avtub-style extraction
                resp3 = requests.get(iframe_src, headers={**HEADERS, "Referer": url}, timeout=10)
                m3u8 = extract_m3u8_from_embed(resp3.text, iframe_src)
                if m3u8:
                    if m3u8.startswith('/'):
                        domain = re.match(r'(https?://[^/]+)', iframe_src)
                        m3u8 = (domain.group(1) if domain else "") + m3u8
                    return m3u8, f"kurakura21_{post_id}"
            return None, f"kurakura21_{post_id}"

        video_id = hash_match.group(1)

        # 4. Fetch encrypted video info from turtle4up.top
        resp3 = requests.get(
            f"https://turtle4up.top/api/v1/video?id={video_id}",
            headers={**HEADERS, "Referer": "https://turtle4up.top/"},
            timeout=10
        )
        data = decrypt_turtle4up(resp3.text)

        # 5. Find m3u8 URL from various source fields
        m3u8_path = None
        for field in ['hlsVideoTiktok', 'hlsVideoGoogle', 'cf', 'source']:
            val = data.get(field, "")
            if val and isinstance(val, str) and val.strip():
                m3u8_path = val.strip()
                break

        if not m3u8_path:
            return None, f"kurakura21_{post_id}"

        # 6. Build full URL
        if m3u8_path.startswith("//"):
            m3u8_url = "https:" + m3u8_path
        elif m3u8_path.startswith("/"):
            m3u8_url = "https://turtle4up.top" + m3u8_path
        else:
            m3u8_url = m3u8_path

        title = data.get("title", f"kurakura21_{post_id}")
        safe_label = re.sub(r'[^a-zA-Z0-9_-]', '_', title)[:50]
        return m3u8_url, f"kurakura21_{safe_label}"

    except Exception as e:
        print(f"Kurakura21 extract error: {e}")

    return None, "kurakura21"


def extract_m3u8_from_embed(html, embed_url=""):
    """Extract m3u8 URL from an embed page (morencius-style JWPlayer)"""

    # Method 1: m3u8 directly in HTML
    direct = re.findall(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html)
    if direct:
        return direct[0]

    # Method 2: "file": "xxx.m3u8"
    file_attr = re.search(r'"file"\s*:\s*"([^"]*\.m3u8[^"]*)"', html)
    if file_attr:
        return file_attr.group(1)

    # Method 3: Deobfuscate eval-packed JWPlayer config via Node.js
    try:
        # Find the eval block with balanced parentheses
        idx = html.find("eval(function(p,a,c,k,e,d)")
        if idx < 0:
            return None

        depth = 0
        start = idx + 4  # after "eval"
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

        # Unpack: replace eval(X) → just evaluate X (the unpacker returns a string)
        node_script = f"var result = {packed}; process.stdout.write(result);"

        result = subprocess.run(
            ["node", "-e", node_script],
            capture_output=True, text=True, timeout=15
        )

        unpacked = result.stdout
        if not unpacked:
            return None

        # Look for the links object: links={"hls4":"...", "hls2":"...", "hls3":"..."}
        links_match = re.search(
            r'links\s*=\s*(\{[^}]*"hls\d?"\s*:\s*"[^"]*"[^}]*\})', unpacked
        )
        if links_match:
            try:
                links = json.loads(links_match.group(1))
                # Priority: hls4 > hls3 > hls2
                for key in ("hls4", "hls3", "hls2"):
                    if key in links and links[key]:
                        return links[key]
            except json.JSONDecodeError:
                pass

        # Fallback: find any m3u8 in unpacked code
        m3u8_matches = re.findall(r'[\'"]((?:https?://|/)[^\s\'"<>]*master\.m3u8[^\s\'"<>]*)[\'"]', unpacked)
        if m3u8_matches:
            return m3u8_matches[0]

    except Exception as e:
        print(f"Deobfuscation error: {e}")

    return None


# ─── CLEANUP ─────────────────────────────────────────────────────────────────

def cleanup_old_files():
    """Hapus file yang sudah lebih dari 1 jam."""
    while True:
        now = time.time()
        for filename in os.listdir(app.config['DOWNLOAD_FOLDER']):
            filepath = os.path.join(app.config['DOWNLOAD_FOLDER'], filename)
            if os.path.isfile(filepath):
                if os.stat(filepath).st_mtime < now - 3600:
                    try:
                        os.remove(filepath)
                        print(f"Cleaned up: {filepath}")
                    except Exception as e:
                        print(f"Cleanup error: {e}")
        time.sleep(600)

threading.Thread(target=cleanup_old_files, daemon=True).start()


# ─── DOWNLOAD WORKER ─────────────────────────────────────────────────────────

def download_worker(task_id, m3u8_url, output_path):
    """Download video using yt-dlp with progress tracking."""
    cmd = [
        "yt-dlp", "--newline", "-f", "best",
        "-o", output_path, "--no-check-certificates"
    ]

    # Add referer for turtle4up.top / kurakura21 embeds
    if "turtle4up.top" in m3u8_url:
        cmd += ["--referer", "https://turtle4up.top/"]
    elif "morencius.com" in m3u8_url:
        cmd += ["--referer", "https://morencius.com/"]

    cmd.append(m3u8_url)

    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True
    )
    percent_regex = re.compile(r'\[download\]\s+([\d\.]+)%')

    for line in process.stdout:
        match = percent_regex.search(line)
        if match:
            try:
                tasks[task_id]["progress"] = float(match.group(1))
            except ValueError:
                pass

    process.wait()

    if process.returncode == 0 and os.path.exists(output_path):
        tasks[task_id]["status"] = "done"
        tasks[task_id]["progress"] = 100
    else:
        tasks[task_id]["status"] = "error"
        tasks[task_id]["error_msg"] = "Gagal mendownload menggunakan yt-dlp"


# ─── ROUTES ──────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/start_download', methods=['POST'])
def start_download():
    data = request.json
    url = data.get('url', '').strip()

    if not url:
        return jsonify({"error": "URL diperlukan"}), 400

    # Detect site
    if VIDARA_REGEX.search(url):
        m3u8_url, label = extract_vidara_link(url)
    elif AVTUB_REGEX.search(url):
        m3u8_url, label = extract_avtub_link(url)
    elif KURAKURA21_REGEX.search(url):
        m3u8_url, label = extract_kurakura21_link(url)
    else:
        return jsonify({"error": "URL tidak didukung. Gunakan link vidara.to, avtub.cx, atau kurakura21.com"}), 400

    if not m3u8_url:
        return jsonify({"error": "Video tidak ditemukan. Pastikan URL valid."}), 400

    task_id = str(uuid.uuid4())
    filename = f"{label}_{int(time.time())}.mp4"
    output_path = os.path.join(app.config['DOWNLOAD_FOLDER'], filename)

    tasks[task_id] = {
        "status": "downloading",
        "progress": 0,
        "filename": filename,
        "m3u8_url": m3u8_url
    }

    threading.Thread(target=download_worker, args=(task_id, m3u8_url, output_path)).start()

    return jsonify({"task_id": task_id, "m3u8_url": m3u8_url})


@app.route('/api/status/<task_id>')
def check_status(task_id):
    if task_id not in tasks:
        return jsonify({"error": "Task tidak ditemukan"}), 404

    task = tasks[task_id]
    response = {"status": task["status"], "progress": task["progress"]}

    if task["status"] == "done":
        response["download_url"] = url_for('download_file', filename=task["filename"])
    elif task["status"] == "error":
        response["error_msg"] = task.get("error_msg", "Unknown error")
        response["m3u8_url"] = task.get("m3u8_url")

    return jsonify(response)


@app.route('/downloads/<filename>')
def download_file(filename):
    return send_from_directory(app.config['DOWNLOAD_FOLDER'], filename, as_attachment=True)


# ─── STREAMING (langsung ke user, tanpa simpan di server) ────────────────────

def resolve_m3u8_url(url):
    """Resolve any supported URL to an m3u8 streaming URL."""
    if VIDARA_REGEX.search(url):
        return extract_vidara_link(url)
    elif AVTUB_REGEX.search(url):
        return extract_avtub_link(url)
    elif KURAKURA21_REGEX.search(url):
        return extract_kurakura21_link(url)
    return None, None


@app.route('/api/extract', methods=['POST'])
def extract_video():
    """Extract m3u8 URL and return it + a player URL."""
    data = request.json
    url = data.get('url', '').strip() if data else ''

    if not url:
        return jsonify({"error": "URL diperlukan"}), 400

    if VIDARA_REGEX.search(url):
        m3u8_url, label = extract_vidara_link(url)
    elif AVTUB_REGEX.search(url):
        m3u8_url, label = extract_avtub_link(url)
    elif KURAKURA21_REGEX.search(url):
        m3u8_url, label = extract_kurakura21_link(url)
    else:
        return jsonify({"error": "URL tidak didukung"}), 400

    if not m3u8_url:
        return jsonify({"error": "Video tidak ditemukan"}), 400

    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', label)[:50]

    # Determine referer for proxying
    referer = ""
    if "turtle4up.top" in m3u8_url:
        referer = "https://turtle4up.top/"
    elif "morencius.com" in m3u8_url:
        referer = "https://morencius.com/"

    return jsonify({
        "m3u8_url": m3u8_url,
        "label": safe_name,
        "referer": referer,
        "player_url": f"/player?url={url_quote(m3u8_url)}&ref={url_quote(referer)}&title={url_quote(safe_name)}"
    })


@app.route('/player')
def player_page():
    """HLS.js player page — plays video directly without saving to server."""
    m3u8_url = request.args.get('url', '')
    referer = request.args.get('ref', '')
    title = request.args.get('title', 'Video')

    if not m3u8_url:
        return "Missing url parameter", 400

    return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - Vidara Player</title>
    <script src="https://cdn.jsdelivr.net/npm/hls.js@1"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ background: #0f0f0f; color: #fff; font-family: system-ui; display: flex;
               flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; }}
        .player-wrap {{ width: 100%; max-width: 900px; padding: 16px; }}
        video {{ width: 100%; border-radius: 8px; background: #000; }}
        h2 {{ font-size: 16px; color: #aaa; margin-bottom: 12px; text-align: center; }}
        .status {{ text-align: center; color: #888; font-size: 14px; margin-top: 8px; }}
        .btn-row {{ display: flex; gap: 8px; justify-content: center; margin-top: 12px; }}
        .btn {{ padding: 8px 20px; border-radius: 6px; border: none; cursor: pointer; font-size: 14px; }}
        .btn-dl {{ background: #e53935; color: #fff; }}
        .btn-dl:hover {{ background: #c62828; }}
    </style>
</head>
<body>
    <div class="player-wrap">
        <h2>{title}</h2>
        <video id="video" controls autoplay playsinline></video>
        <div class="status" id="status">Loading...</div>
        <div class="btn-row">
            <button class="btn btn-dl" id="dlBtn" onclick="downloadVideo()">Download Video</button>
        </div>
    </div>
    <script>
        const videoSrc = "/proxy/m3u8?url=" + encodeURIComponent("{m3u8_url}") + "&ref=" + encodeURIComponent("{referer}");
        const video = document.getElementById('video');
        const status = document.getElementById('status');

        if (Hls.isSupported()) {{
            const hls = new Hls({{
                xhrSetup: (xhr, url) => {{
                    // Proxy all requests through our server
                    if (url.startsWith('http')) {{
                        xhr.open('GET', '/proxy/segment?url=' + encodeURIComponent(url) + '&ref=' + encodeURIComponent("{referer}"), true);
                    }}
                }}
            }});
            hls.loadSource(videoSrc);
            hls.attachMedia(video);
            hls.on(Hls.Events.MANIFEST_PARSED, () => {{ status.textContent = "Ready — klik play"; video.play(); }});
            hls.on(Hls.Events.ERROR, (e, d) => {{ status.textContent = "Error: " + (d.error?.message || "unknown"); }});
        }} else if (video.canPlayType('application/vnd.apple.mpegurl')) {{
            video.src = videoSrc;
            video.addEventListener('loadedmetadata', () => video.play());
        }} else {{
            status.textContent = "Browser tidak support HLS";
        }}

        function downloadVideo() {{
            status.textContent = "Downloading... file akan tersimpan ke device kamu (tidak disimpan di server)";
            fetch('/api/stream', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ url: document.referrer || prompt("Masukkan URL asli:") }})
            }})
            .then(r => {{
                if (!r.ok) return r.json().then(e => {{ throw new Error(e.error) }});
                const disposition = r.headers.get('Content-Disposition');
                let fn = '{title}.mp4';
                if (disposition) {{ const m = disposition.match(/filename="?([^"]+)"?/); if (m) fn = m[1]; }}
                return r.blob().then(b => {{
                    const a = document.createElement('a'); a.href = URL.createObjectURL(b);
                    a.download = fn; a.click(); URL.revokeObjectURL(a.href);
                    status.textContent = "Download selesai!";
                }});
            }})
            .catch(e => status.textContent = "Error: " + e.message);
        }}
    </script>
</body>
</html>'''


@app.route('/proxy/m3u8')
def proxy_m3u8():
    """Proxy m3u8 manifest — rewrites segment URLs to go through our proxy."""
    m3u8_url = request.args.get('url', '')
    referer = request.args.get('ref', '')

    if not m3u8_url:
        return "Missing url", 400

    headers = {**HEADERS}
    if referer:
        headers["Referer"] = referer

    try:
        resp = requests.get(m3u8_url, headers=headers, timeout=10)
        content = resp.text

        # Rewrite relative/absolute segment URLs to go through our proxy
        base_url = m3u8_url.rsplit('/', 1)[0] + '/'

        def rewrite_url(match):
            seg_url = match.group(1).strip()
            if seg_url.startswith('#'):
                return match.group(0)  # Keep HLS tags as-is
            # Make absolute
            if seg_url.startswith('/'):
                from urllib.parse import urlparse
                parsed = urlparse(m3u8_url)
                seg_url = f"{parsed.scheme}://{parsed.netloc}{seg_url}"
            elif not seg_url.startswith('http'):
                seg_url = base_url + seg_url
            return f'/proxy/segment?url={url_quote(seg_url)}&ref={url_quote(referer)}'

        # Rewrite URLs in m3u8 lines
        lines = content.split('\n')
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('#'):
                # Check for URI= in tags (e.g. #EXT-X-KEY:URI="...")
                uri_match = re.search(r'URI="([^"]+)"', stripped)
                if uri_match:
                    uri = uri_match.group(1)
                    if uri.startswith('/'):
                        from urllib.parse import urlparse
                        parsed = urlparse(m3u8_url)
                        uri = f"{parsed.scheme}://{parsed.netloc}{uri}"
                    elif not uri.startswith('http'):
                        uri = base_url + uri
                    proxied = f'/proxy/segment?url={url_quote(uri)}&ref={url_quote(referer)}'
                    new_lines.append(stripped.replace(uri_match.group(0), f'URI="{proxied}"'))
                else:
                    new_lines.append(stripped)
            elif stripped:
                # This is a segment/sub-playlist URL
                if stripped.startswith('/'):
                    from urllib.parse import urlparse
                    parsed = urlparse(m3u8_url)
                    seg_url = f"{parsed.scheme}://{parsed.netloc}{stripped}"
                elif not stripped.startswith('http'):
                    seg_url = base_url + stripped
                else:
                    seg_url = stripped
                new_lines.append(f'/proxy/segment?url={url_quote(seg_url)}&ref={url_quote(referer)}')
            else:
                new_lines.append(stripped)

        return Response('\n'.join(new_lines), content_type='application/vnd.apple.mpegurl',
                       headers={'Access-Control-Allow-Origin': '*'})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/proxy/segment')
def proxy_segment():
    """Proxy a single video segment or sub-playlist — streams through without saving."""
    seg_url = request.args.get('url', '')
    referer = request.args.get('ref', '')

    if not seg_url:
        return "Missing url", 400

    headers = {**HEADERS}
    if referer:
        headers["Referer"] = referer

    try:
        resp = requests.get(seg_url, headers=headers, timeout=30)
        content_type = resp.headers.get('Content-Type', 'application/octet-stream')

        # If this is an m3u8 sub-playlist, rewrite it like /proxy/m3u8 does
        if 'mpegurl' in content_type or seg_url.endswith('.m3u8') or '.m3u8?' in seg_url:
            content = resp.text
            base_url = seg_url.split('?')[0].rsplit('/', 1)[0] + '/'

            lines = content.split('\n')
            new_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped.startswith('#'):
                    uri_match = re.search(r'URI="([^"]+)"', stripped)
                    if uri_match:
                        uri = uri_match.group(1)
                        if uri.startswith('/'):
                            from urllib.parse import urlparse
                            parsed = urlparse(seg_url)
                            uri = f"{parsed.scheme}://{parsed.netloc}{uri}"
                        elif not uri.startswith('http'):
                            uri = base_url + uri
                        proxied = f'/proxy/segment?url={url_quote(uri)}&ref={url_quote(referer)}'
                        new_lines.append(stripped.replace(uri_match.group(0), f'URI="{proxied}"'))
                    else:
                        new_lines.append(stripped)
                elif stripped:
                    if stripped.startswith('/'):
                        from urllib.parse import urlparse
                        parsed = urlparse(seg_url)
                        s_url = f"{parsed.scheme}://{parsed.netloc}{stripped}"
                    elif not stripped.startswith('http'):
                        s_url = base_url + stripped
                    else:
                        s_url = stripped
                    new_lines.append(f'/proxy/segment?url={url_quote(s_url)}&ref={url_quote(referer)}')
                else:
                    new_lines.append(stripped)

            return Response('\n'.join(new_lines), content_type='application/vnd.apple.mpegurl',
                           headers={'Access-Control-Allow-Origin': '*'})

        # Regular segment — stream through
        def generate():
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    yield chunk

        return Response(
            stream_with_context(generate()),
            content_type=content_type,
            headers={
                'Access-Control-Allow-Origin': '*',
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
