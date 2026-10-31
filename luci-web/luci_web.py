"""Puente web: ejecuta LuciSport_V1_9.py tal cual y captura su salida de consola.
Así la página muestra exactamente lo mismo que la terminal."""
import contextlib
import html
import importlib.util
import io
import os
import pathlib
import re
import json
from datetime import datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("luci", ROOT / "LuciSport_V1_9.py")
luci = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(luci)

# Claves por variables de entorno (no dejar claves en el código del repositorio)
luci.HEADERS = {"X-Auth-Token": os.environ.get("FOOTBALL_API_KEY", "")}
luci.API_KEY_ODDS = os.environ.get("ODDS_API_KEY", luci.API_KEY_ODDS)
# En la web no se envían mensajes a Telegram automáticamente
luci.enviar_a_telegram = lambda *a, **k: None

CODIGOS_VALIDOS = [v["c"] for v in luci.LIGAS.values()]  # incluye "ALL"

ANSI_RE = re.compile(r"\x1b\[([0-9;]*)m")
CLASES = {"92": "c-verde", "93": "c-amarillo", "91": "c-rojo",
          "94": "c-azul", "96": "c-cian", "1": "b"}


def quitar_ansi(texto):
    return ANSI_RE.sub("", texto)


def ansi_a_html(texto):
    """Convierte colores ANSI de la consola en <span> con clases CSS (texto escapado)."""
    out, abiertos, pos = [], 0, 0
    for m in ANSI_RE.finditer(texto):
        out.append(html.escape(texto[pos:m.start()]))
        pos = m.end()
        code = m.group(1)
        if code in ("", "0"):
            out.append("</span>" * abiertos)
            abiertos = 0
        elif code in CLASES:
            out.append(f'<span class="{CLASES[code]}">')
            abiertos += 1
    out.append(html.escape(texto[pos:]))
    out.append("</span>" * abiertos)
    return "".join(out)


def _verificar_clave():
    if not luci.HEADERS["X-Auth-Token"]:
        raise RuntimeError("Falta la variable de entorno FOOTBALL_API_KEY en Vercel")


def partidos(liga, dias):
    """Lista de partidos pendientes, igual que la opción de partidos del menú original."""
    _verificar_clave()
    if liga not in CODIGOS_VALIDOS:
        raise ValueError("Liga no válida")
    codigos = [c for c in CODIGOS_VALIDOS if c != "ALL"] if liga == "ALL" else [liga]
    dias = max(0, min(int(dias), 14))
    desde = datetime.now().strftime("%Y-%m-%d")
    hasta = (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d")

    resultado = []
    for cid in codigos:
        try:
            url = (f"https://api.football-data.org/v4/competitions/{cid}/matches"
                   f"?dateFrom={desde}&dateTo={hasta}")
            data = luci.requests.get(url, headers=luci.HEADERS, timeout=10).json()
            for m in data.get("matches", []):
                if m.get("status") == "FINISHED":
                    continue
                estado = "[LIVE]" if m.get("status") in ("IN_PLAY", "PAUSED") else "[PRE]"
                fecha = m.get("utcDate", "")[:16].replace("T", " ")
                resultado.append({
                    "id": m["id"],
                    "league_code": cid,
                    "label": f"{estado} {m['homeTeam']['name']} vs {m['awayTeam']['name']}  ({fecha} UTC)",
                })
        except Exception:
            continue
    return {"partidos": resultado}


def analizar(match_id, cid):
    """Ejecuta analizar_titan del archivo original y devuelve su salida."""
    _verificar_clave()
    if cid not in CODIGOS_VALIDOS or cid == "ALL":
        raise ValueError("Liga no válida")
    r = luci.requests.get(f"https://api.football-data.org/v4/matches/{int(match_id)}",
                          headers=luci.HEADERS, timeout=10).json()
    if "homeTeam" not in r:
        raise ValueError(r.get("message", "Partido no encontrado"))
    r["league_code"] = cid

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        luci.analizar_titan(r)
    salida = buffer.getvalue()
    return {
        "match": f"{r['homeTeam']['name']} vs {r['awayTeam']['name']}",
        "html": ansi_a_html(salida),
        "texto": quitar_ansi(salida),
    }


def responder(handler, codigo, payload, cache=False):
    cuerpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(codigo)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Cache-Control", "s-maxage=120" if cache else "no-store")
    handler.end_headers()
    handler.wfile.write(cuerpo)
