import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import luci_web  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        ruta = q.get("r", [""])[0]
        try:
            if ruta == "partidos":
                payload = luci_web.partidos(q.get("liga", ["PD"])[0], q.get("dias", ["2"])[0])
                luci_web.responder(self, 200, payload, cache=True)
            elif ruta == "analizar":
                payload = luci_web.analizar(int(q.get("id", [""])[0]), q.get("liga", [""])[0])
                luci_web.responder(self, 200, payload)
            elif ruta == "picks":
                payload = luci_web.picks(int(q.get("id", [""])[0]), q.get("liga", [""])[0])
                luci_web.responder(self, 200, payload)
            elif ruta == "combinada":
                # partidos=ID:LIGA,ID:LIGA  y opcionalmente objetivo=2.50
                pares = []
                for par in q.get("partidos", [""])[0].split(","):
                    if ":" in par:
                        mid, liga = par.split(":", 1)
                        pares.append((int(mid), liga))
                obj = q.get("objetivo", [""])[0]
                objetivo = float(obj) if obj else None
                luci_web.responder(self, 200, luci_web.combinada(pares, objetivo))
            else:
                luci_web.responder(self, 404, {"error": "Ruta no válida"})
        except Exception as e:
            luci_web.responder(self, 500, {"error": str(e)})
