"""Generic extractor — yt-dlp fallback for ANY URL not matched by custom extractors.
Supports: YouTube, TikTok, Instagram, Twitter/X, Facebook, Reddit, Vimeo,
Dailymotion, Twitch, Pornhub, XHamster, SpankBang, Bilibili, and 1700+ more sites.
"""
import json, subprocess

# ─── Supported popular sites (for display) ────────────────────────────────────
POPULAR_SITES = [
    {'name': 'YouTube', 'domain': 'youtube.com', 'icon': '🎬'},
    {'name': 'TikTok', 'domain': 'tiktok.com', 'icon': '🎵'},
    {'name': 'Instagram', 'domain': 'instagram.com', 'icon': '📸'},
    {'name': 'Twitter/X', 'domain': 'x.com', 'icon': '🐦'},
    {'name': 'Facebook', 'domain': 'facebook.com', 'icon': '📘'},
    {'name': 'Reddit', 'domain': 'reddit.com', 'icon': '🤖'},
    {'name': 'Vimeo', 'domain': 'vimeo.com', 'icon': '🎥'},
    {'name': 'Dailymotion', 'domain': 'dailymotion.com', 'icon': '📺'},
    {'name': 'Twitch', 'domain': 'twitch.tv', 'icon': '💜'},
    {'name': 'Pornhub', 'domain': 'pornhub.com', 'icon': '🔞'},
    {'name': 'XHamster', 'domain': 'xhamster.com', 'icon': '🔞'},
    {'name': 'XVideos', 'domain': 'xvideos.com', 'icon': '🔴'},
    {'name': 'SpankBang', 'domain': 'spankbang.com', 'icon': '🔞'},
    {'name': 'RedTube', 'domain': 'redtube.com', 'icon': '🔴'},
    {'name': 'YouPorn', 'domain': 'youporn.com', 'icon': '🟡'},
    {'name': 'Tube8', 'domain': 'tube8.com', 'icon': '🔞'},
    {'name': 'Bilibili', 'domain': 'bilibili.com', 'icon': '📺'},
    {'name': 'Douyin', 'domain': 'douyin.com', 'icon': '🎵'},
    {'name': 'SoundCloud', 'domain': 'soundcloud.com', 'icon': '🔊'},
    {'name': 'VK', 'domain': 'vk.com', 'icon': '🔵'},
    {'name': 'Rumble', 'domain': 'rumble.com', 'icon': '📢'},
    {'name': 'Streamable', 'domain': 'streamable.com', 'icon': '🎞️'},
    {'name': 'Imgur', 'domain': 'imgur.com', 'icon': '🖼️'},
    {'name': 'Pinterest', 'domain': 'pinterest.com', 'icon': '📌'},
    {'name': 'Tumblr', 'domain': 'tumblr.com', 'icon': '📝'},
    {'name': 'LinkedIn', 'domain': 'linkedin.com', 'icon': '💼'},
    {'name': 'Snapchat', 'domain': 'snapchat.com', 'icon': '👻'},
    {'name': 'BitChute', 'domain': 'bitchute.com', 'icon': '🔗'},
    {'name': 'Odysee/LBRY', 'domain': 'odysee.com', 'icon': '🔗'},
    {'name': 'PeerTube', 'domain': 'peertube.*', 'icon': '🔗'},
]

def extract_generic(url):
    """
    Use yt-dlp to extract video info from ANY supported URL.
    Returns dict with url, title, thumbnail, qualities, duration, source.
    """
    try:
        # Get video info first
        cmd = ['yt-dlp', '--no-check-certificates', '--no-warnings',
               '--dump-json', '--no-download', url]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            # Try without dump-json (some sites need --get-url)
            cmd2 = ['yt-dlp', '--no-check-certificates', '--no-warnings',
                     '--get-url', '--get-title', url]
            proc2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=30)
            if proc2.returncode != 0:
                return None
            lines = proc2.stdout.strip().split('\n')
            if len(lines) >= 2:
                title = lines[0].strip()
                video_url = lines[1].strip()
                if video_url.startswith('http'):
                    return {
                        'url': video_url,
                        'title': title,
                        'thumbnail': '',
                        'qualities': [{'label': 'Best', 'url': video_url}],
                        'source': 'ytdlp',
                    }
            return None

        info = json.loads(proc.stdout)
        title = info.get('title', 'video')
        thumbnail = info.get('thumbnail', '')
        duration = info.get('duration', 0)
        extractor = info.get('extractor', 'yt-dlp')

        # Build qualities list
        formats = info.get('formats', [])
        qualities = []
        if formats:
            # Get best video+audio
            seen = set()
            for f in formats:
                h = f.get('height')
                ext = f.get('ext', '')
                if h and h not in seen and ext in ('mp4', 'webm', 'mkv'):
                    seen.add(h)
                    qualities.append({
                        'label': f'{h}p',
                        'url': f.get('url', ''),
                        'format_id': f.get('format_id', ''),
                        'ext': ext,
                        'filesize': f.get('filesize') or f.get('filesize_approx'),
                    })
            qualities.sort(key=lambda x: int(x['label'].replace('p', '')), reverse=True)

        # Best URL
        video_url = info.get('url', '')
        if not video_url and formats:
            # Pick best format
            best = max(formats, key=lambda f: (f.get('height') or 0, f.get('tbr') or 0))
            video_url = best.get('url', '')

        if not video_url:
            return None

        return {
            'url': video_url,
            'title': title,
            'thumbnail': thumbnail,
            'qualities': qualities[:10] if qualities else [{'label': 'Best', 'url': video_url}],
            'duration': duration,
            'source': extractor,
        }
    except subprocess.TimeoutExpired:
        print(f'[ytdlp] Timeout extracting: {url}')
        return None
    except Exception as e:
        print(f'[ytdlp] Error: {e}')
        return None
