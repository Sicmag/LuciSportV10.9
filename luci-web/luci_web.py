"""Puente web: ejecuta LuciSport_V1_9.py tal cual y captura su salida de consola."""
import contextlib
import html
import itertools
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


def categoria(nombre):
    """Agrupa un pick por tipo de mercado para mostrarlo ordenado en la web."""
    if "Córners" in nombre:
        return "Córners"
    if "Tarjetas" in nombre:
        return "Tarjetas"
    if "Tiros" in nombre or "Remates" in nombre:
        return "Tiros y remates"
    if "Goles" in nombre or nombre.startswith(("Más de", "Menos de", "Ambos")):
        return "Goles"
    if nombre.startswith(("Gana ", "1X ", "X2 ")):
        return "Resultado"
    return "Otros"


def picks(match_id, cid):
    """Picks del partido: solo recomendaciones que cumplen el filtro (prob. 60-70%, cuota >= 1.40)."""
    r = _obtener_partido(match_id, cid)
    tope_original = luci.MAX_RECS_V2
    luci.MAX_RECS_V2 = 1000  # que el tope V2 no oculte picks válidos
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            luci.analizar_titan(r)
    finally:
        luci.MAX_RECS_V2 = tope_original

    seleccion = []
    for rec in luci.ULTIMAS_RECOMENDACIONES:
        real = rec.get("odd_real", 0)
        seleccion.append({
            "nombre": rec["nombre"],
            "mercado": categoria(rec["nombre"]),
            "prob": rec["prob"],
            "odd": real if real > 0 else rec["odd_calc"],
            "fuente": "real" if real > 0 else "justa",
        })
    return {
        "partido": f"{r['homeTeam']['name']} vs {r['awayTeam']['name']}",
        "utcDate": r.get("utcDate", ""),
        "picks": sorted(seleccion, key=lambda x: x["prob"], reverse=True),
    }


def combinada(pares, objetivo=None):
    """Combinadas a partir de los partidos elegidos (2 o 3).
    Con objetivo: las combinaciones cuya cuota total está más cerca de la cuota deseada.
    Sin objetivo: las de mayor probabilidad. Devuelve hasta 3 opciones."""
    if not 2 <= len(pares) <= 3:
        raise ValueError("Elige entre 2 y 3 partidos")
    if objetivo is not None and not (1.01 <= objetivo <= 100):
        raise ValueError("La cuota deseada debe estar entre 1.01 y 100")

    candidatos, nombres = [], []
    for mid, cid in pares:
        r = _obtener_partido(mid, cid)
        nombre_p = f"{r['homeTeam']['name']} vs {r['awayTeam']['name']}"
        nombres.append(nombre_p)
        opciones = []
        for x in luci.recomendaciones_partido(r):
            real = x.get("odd_real", 0)
            opciones.append({
                "match_id": int(mid), "partido": nombre_p, "utcDate": r.get("utcDate", ""),
                "nombre": x["nombre"], "prob": x["prob"],
                "odd": real if real > 0 else x["odd_calc"],
                "fuente": "real" if real > 0 else "justa",
            })
        opciones.sort(key=lambda o: (-o["prob"], -o["odd"]))
        candidatos.append(opciones[:12])

    sin_pick = [nombres[i] for i, c in enumerate(candidatos) if not c]
    if sin_pick:
        return {"opciones": [], "sin_pick": sin_pick, "objetivo": objetivo}

    combos = []
    for combo in itertools.product(*candidatos):
        prob, cuota = 1.0, 1.0
        for p in combo:
            prob *= p["prob"] / 100
            cuota *= p["odd"]
        combos.append({"pasos": list(combo), "prob": round(prob * 100, 1), "cuota": round(cuota, 2)})

    if objetivo is None:
        combos.sort(key=lambda c: (-c["prob"], -c["cuota"]))
    else:
        combos.sort(key=lambda c: (abs(c["cuota"] - objetivo), -c["prob"]))

    opciones, vistos = [], set()
    for c in combos:
        clave = tuple((p["match_id"], p["nombre"]) for p in c["pasos"])
        if clave in vistos:
            continue
        vistos.add(clave)
        opciones.append(c)
        if len(opciones) == 3:
            break
    return {"opciones": opciones, "sin_pick": [], "objetivo": objetivo}


def responder(handler, codigo, payload, cache=False):
    cuerpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(codigo)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Cache-Control", "s-maxage=120" if cache else "no-store")
    handler.end_headers()
    handler.wfile.write(cuerpo)
