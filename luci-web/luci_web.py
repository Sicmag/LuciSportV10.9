"""Puente web: ejecuta LuciSport_V1_9.py tal cual y captura su salida de consola."""
import contextlib
import html
import importlib.util
import io
import json
import os
import pathlib
import re
from datetime import datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("luci", ROOT / "LuciSport_V1_9.py")
luci = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(luci)

luci.HEADERS = {"X-Auth-Token": os.environ.get("FOOTBALL_API_KEY", "")}
luci.API_KEY_ODDS = os.environ.get("ODDS_API_KEY", luci.API_KEY_ODDS)
luci.enviar_a_telegram = lambda *a, **k: None

CODIGOS_VALIDOS = [v["c"] for v in luci.LIGAS.values()]
ANSI_RE = re.compile(r"\x1b\[([0-9;]*)m")
CLASES = {"92": "c-verde", "93": "c-amarillo", "91": "c-rojo",
          "94": "c-azul", "96": "c-cian", "1": "b"}


def quitar_ansi(texto):
    return ANSI_RE.sub("", texto)


def ansi_a_html(texto):
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


def _obtener_partido(match_id, cid):
    _verificar_clave()
    if cid not in CODIGOS_VALIDOS or cid == "ALL":
        raise ValueError("Liga no válida")
    r = luci.requests.get(f"https://api.football-data.org/v4/matches/{int(match_id)}",
                          headers=luci.HEADERS, timeout=10).json()
    if "homeTeam" not in r:
        raise ValueError(r.get("message", "Partido no encontrado"))
    r["league_code"] = cid
    return r


def partidos(liga, dias):
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
                    "utcDate": m.get("utcDate", ""),
                    "label": f"{estado} {m['homeTeam']['name']} vs {m['awayTeam']['name']}  ({fecha} UTC)",
                })
        except Exception:
            continue
    return {"partidos": resultado}


def analizar(match_id, cid):
    r = _obtener_partido(match_id, cid)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        luci.analizar_titan(r)
    salida = buffer.getvalue()
    return {
        "match": f"{r['homeTeam']['name']} vs {r['awayTeam']['name']}",
        "html": ansi_a_html(salida),
        "texto": quitar_ansi(salida),
    }


def picks(match_id, cid):
    """Picks del partido que cumplen el filtro (sin mercados heurísticos)."""
    r = _obtener_partido(match_id, cid)
    h, a = r["homeTeam"], r["awayTeam"]
    h_s = luci.get_deep_data_v2(h["id"])
    a_s = luci.get_deep_data_v2(a["id"])

    # Temporalmente quitamos el tope de recomendaciones para no perder picks de 66-70%
    tope_original = luci.MAX_RECS_V2
    luci.MAX_RECS_V2 = 1000
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            recs = luci.bloque_v2_mercados(h["name"], a["name"], h_s, a_s)
    finally:
        luci.MAX_RECS_V2 = tope_original

    seleccion = []
    for nombre, prob in recs:
        if luci.cumple_recomendacion(nombre, prob):
            seleccion.append({"nombre": nombre, "prob": prob, "odd": luci.to_odds(prob)})
    return {
        "partido": f"{h['name']} vs {a['name']}",
        "utcDate": r.get("utcDate", ""),
        "picks": sorted(seleccion, key=lambda x: x["prob"], reverse=True),
    }


def responder(handler, codigo, payload, cache=False):
    cuerpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(codigo)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Cache-Control", "s-maxage=120" if cache else "no-store")
    handler.end_headers()
    handler.wfile.write(cuerpo)