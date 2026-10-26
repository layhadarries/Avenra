"""CSP hashes come from trusted shipped files, never rendered/request HTML."""
import base64
from functools import lru_cache
import hashlib
from html.parser import HTMLParser
from pathlib import Path


class InlineScripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.active=False
        self.parts=[]
        self.scripts=[]

    def handle_starttag(self,tag,attrs):
        if tag=='script' and 'src' not in dict(attrs):
            self.active=True
            self.parts=[]

    def handle_data(self,data):
        if self.active: self.parts.append(data)

    def handle_endtag(self,tag):
        if tag=='script' and self.active:
            self.scripts.append(''.join(self.parts))
            self.active=False


@lru_cache(maxsize=1)
def policy():
    root=Path(__file__).resolve().parents[1]/'static'/'survivor'
    hashes=set()
    for path in sorted(root.glob('*.html')):
        parser=InlineScripts(); parser.feed(path.read_text(encoding='utf-8'))
        for source in parser.scripts:
            hashes.add("'sha256-"+base64.b64encode(hashlib.sha256(source.encode()).digest()).decode()+"'")
    return '; '.join((
        "default-src 'none'",
        "script-src 'self' "+' '.join(sorted(hashes)),
        "script-src-attr 'none'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob: https://tile.openstreetmap.org",
        "font-src 'self'",
        "connect-src 'self' https://api.open-meteo.com https://geocoding-api.open-meteo.com https://api.bigdatacloud.net",
        "worker-src 'self'",
        "manifest-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
    ))
