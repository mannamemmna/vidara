"""vidara.to / vidara.so — vidaratem.co API."""
import requests, re
from app.extractors import site
from app.config import HEADERS

@site(r'https?://(?:www\.)?vidara\.(?:to|so)/v/([a-zA-Z0-9_-]+)')
def extract(url, m):
    fc = m.group(1)
    try:
        r = requests.post('https://vidaratem.co/api/stream',
                          json={'filecode': fc, 'device': 'web'},
                          headers=HEADERS, timeout=10)
        d = r.json()
        return d.get('streaming_url'), f'vidara_{fc}'
    except Exception as e:
        print(f"[vidara] {e}")
        return None, f'vidara_{fc}'
