import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import luci_web  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        try:
            match_id = int(q.get("id", [""])[0])
            cid = q.get("liga", [""])[0]
            luci_web.responder(self, 200, luci_web.analizar(match_id, cid))
        except Exception as e:
            luci_web.responder(self, 500, {"error": str(e)})
