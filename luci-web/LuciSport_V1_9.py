import os
import re
import requests
import time
import math
import random
from datetime import datetime, timedelta
import difflib  # Para comparar nombres de equipos (The Odds API)

# ---------- CONFIGURACIÓN ----------
API_KEY_FOOTBALL = "1e5c3ffbc5bb41c7a564388729255308"  # Football-Data.org
API_KEY_ODDS = os.getenv("ODDS_API_KEY", "4717a35d0881dfe407379ce367a992a6")       # Opcional, para cuotas reales
HEADERS = {'X-Auth-Token': API_KEY_FOOTBALL}

# --- CONFIGURACIÓN TELEGRAM ---
TELEGRAM_TOKEN = "8596631931:AAF_4V8F344Cb5yZz6ZiPZIRztp_xR7nk8Y"
TELEGRAM_CHAT_ID = "7002805722"

# --- COLORES CONSOLA ---
G, Y, R, B, C, W = '\033[92m', '\033[93m', '\033[91m', '\033[94m', '\033[96m', '\033[0m'
BOLD = '\033[1m'

# --- FILTRO DE RECOMENDACIONES ---
REC_PROB_MIN = 66          # probabilidad mínima (%)
REC_PROB_MAX = 100          # probabilidad máxima (%)
REC_ODD_MIN = 1.40         # cuota mínima (real si existe, justa si no)
MERCADOS_HEURISTICOS = ("Córners", "Tarjetas", "Tiros", "Remates")  # sin datos reales

# Recomendaciones del último análisis (la usa la web para los picks)
ULTIMAS_RECOMENDACIONES = []

# ---------- UTILIDADES ----------
def color_prob(p):
    if p < 40: return R
    elif p < 60: return Y
    elif p < 80: return B
    return G

def to_odds(p):
    return round(100 / p, 2) if p > 0 else 0.0

def cumple_recomendacion(nombre, prob, odd_real=0):
    """True si el pick está entre REC_PROB_MIN y REC_PROB_MAX y su cuota es >= REC_ODD_MIN."""
    if any(x in nombre for x in MERCADOS_HEURISTICOS):
        return False
    if not (REC_PROB_MIN <= prob <= REC_PROB_MAX):
        return False
    odd = odd_real if odd_real > 0 else to_odds(prob)
    return odd >= REC_ODD_MIN

def calcular_stake(p):
    """Stake del 5% al 30% según probabilidad (solo si p >= 60)."""
    if p < 60:
        return 0
    if p >= 80:
        s = 20 + ((p - 80) * 0.5)
        return int(min(s, 30))
    s = 5 + ((p - 60) * 0.55)
    return int(s)

def poisson(lam, k):
    return (lam**k * math.exp(-lam)) / math.factorial(k) if lam > 0 else 0

def enviar_a_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except:
        pass

def get_deep_data(team_id):
    """Obtiene media de goles a favor y en contra de los últimos 15 partidos."""
    time.sleep(0.6)  # Anti-ban
    url = f"https://api.football-data.org/v4/teams/{team_id}/matches?status=FINISHED&limit=15"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10).json()
        matches = r.get("matches", [])
        if not matches:
            return {"gf": 1.2, "gc": 1.1}
        gf = 0
        gc = 0
        for m in matches:
            if m['homeTeam']['id'] == team_id:
                gf += m['score']['fullTime']['home'] or 0
                gc += m['score']['fullTime']['away'] or 0
            else:
                gf += m['score']['fullTime']['away'] or 0
                gc += m['score']['fullTime']['home'] or 0
        return {"gf": gf / len(matches), "gc": gc / len(matches)}
    except:
        return {"gf": 1.2, "gc": 1.1}

# --- MAPEO PARA THE ODDS API (opcional) ---
ODDS_MAP = {
    "PL": "soccer_epl", "PD": "soccer_spain_la_liga", "SA": "soccer_italy_serie_a",
    "BL1": "soccer_germany_bundesliga", "FL1": "soccer_france_ligue_one",
    "DED": "soccer_netherlands_eredivisie", "PPL": "soccer_portugal_primeira_liga",
    "BSA": "soccer_brazil_campeonato", "ELC": "soccer_efl_champ",
    "CL": "soccer_uefa_champs_league", "ELI": "soccer_uefa_europa_league",
    "CLI": "soccer_conmebol_libertadores", "EC": "soccer_uefa_european_championship",
    "WC": "soccer_fifa_world_cup"
}

def get_live_odds(sport_key, home_team, away_team):
    """Mejores cuotas reales desde The Odds API: 1X2 ('1', 'X', '2') y totales ('O2.5', 'U2.5', ...).
    Toma la mejor cuota entre todas las casas disponibles. Devuelve dict o None."""
    if not API_KEY_ODDS or "TU_API_KEY" in API_KEY_ODDS:
        return None
    url = (f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
           f"?apiKey={API_KEY_ODDS}&regions=eu&markets=h2h,totals&oddsFormat=decimal")
    try:
        data = requests.get(url, timeout=10).json()
        if not isinstance(data, list):
            return None
        best_match = None
        highest_ratio = 0
        for event in data:
            ratio_h = difflib.SequenceMatcher(None, home_team.lower(), event['home_team'].lower()).ratio()
            ratio_a = difflib.SequenceMatcher(None, away_team.lower(), event['away_team'].lower()).ratio()
            avg = (ratio_h + ratio_a) / 2
            if avg > highest_ratio and avg > 0.55:
                highest_ratio = avg
                best_match = event
        if not best_match:
            return None
        odds = {}
        for bk in best_match.get('bookmakers', []):
            for mk in bk.get('markets', []):
                if mk['key'] == 'h2h':
                    for o in mk['outcomes']:
                        if o['name'] == best_match['home_team']:
                            clave = '1'
                        elif o['name'] == best_match['away_team']:
                            clave = '2'
                        else:
                            clave = 'X'
                        odds[clave] = max(odds.get(clave, 0), o['price'])
                elif mk['key'] == 'totals':
                    for o in mk['outcomes']:
                        if o.get('point') is None:
                            continue
                        lado = 'O' if o['name'] == 'Over' else 'U'
                        clave = f"{lado}{float(o['point'])}"
                        odds[clave] = max(odds.get(clave, 0), o['price'])
        return odds or None
    except Exception:
        return None

def cuota_real_para(nombre, h_n, a_n, odds):
    """Cuota real (0 si no existe) para el nombre de una recomendación."""
    if not odds:
        return 0
    fijos = {f"Gana {h_n}": '1', f"Gana {a_n}": '2',
             "Más de 1.5 Goles": 'O1.5', "Más de 2.5 Goles": 'O2.5',
             "Menos de 3.5 Goles": 'U3.5'}
    if nombre in fijos:
        return odds.get(fijos[nombre], 0)
    m = re.match(r"Goles total (Más|Menos) de ([0-9.]+)$", nombre)
    if m:
        clave = ('O' if m.group(1) == "Más" else 'U') + str(float(m.group(2)))
        return odds.get(clave, 0)
    return 0

# ---------- LISTA DE LIGAS ----------
LIGAS = {
    "1": {"n": "Premier League", "c": "PL"},
    "2": {"n": "La Liga", "c": "PD"},
    "3": {"n": "Serie A", "c": "SA"},
    "4": {"n": "Bundesliga", "c": "BL1"},
    "5": {"n": "Ligue 1", "c": "FL1"},
    "6": {"n": "Eredivisie", "c": "DED"},
    "7": {"n": "Primeira Liga", "c": "PPL"},
    "8": {"n": "Brasileirão", "c": "BSA"},
    "9": {"n": "Championship", "c": "ELC"},
    "10": {"n": "Champions League", "c": "CL"},
    "11": {"n": "Europa League", "c": "ELI"},
    "12": {"n": "Libertadores", "c": "CLI"},
    "13": {"n": "Copa Sudamericana", "c": "FLC"},
    "14": {"n": "Liga MX", "c": "ELMX"},
    "15": {"n": "Segunda División (ES)", "c": "SD"},
    "16": {"n": "Serie B (IT)", "c": "SB"},
    "0": {"n": "TODAS LAS LIGAS", "c": "ALL"}
}

# ---------- EXTRACTOR DE PICKS PARA COMBINADAS ----------
def extraer_picks_gold(match):
    """Devuelve picks con probabilidad >=60% y cuota calculada >=1.50."""
    h_s = get_deep_data(match['homeTeam']['id'])
    a_s = get_deep_data(match['awayTeam']['id'])
    exH = ((h_s['gf'] + a_s['gc']) / 2) * 1.10
    exA = ((a_s['gf'] + h_s['gc']) / 2) * 0.95
    total_ex = exH + exA

    pL = round(sum(poisson(exH, i) * poisson(exA, j) for i in range(8) for j in range(8) if i > j) * 100)
    pV = round(sum(poisson(exH, i) * poisson(exA, j) for i in range(8) for j in range(8) if j > i) * 100)
    pE = 100 - pL - pV
    o15 = round((1 - sum(poisson(total_ex, i) for i in range(2))) * 100)
    btts = round(((1 - poisson(exH, 0)) * (1 - poisson(exA, 0))) * 100)

    posibles = [
        (f"Gana {match['homeTeam']['name']}", pL),
        (f"Gana {match['awayTeam']['name']}", pV),
        (f"Gana o Empate {match['homeTeam']['name']}", pL + pE),
        (f"Gana o Empate {match['awayTeam']['name']}", pV + pE),
        ("Más de 1.5 Goles", o15),
        ("Ambos Marcan", btts)
    ]

    picks = []
    for nombre, prob in posibles:
        odd = to_odds(prob)
        if prob >= 60 and odd >= 1.50:
            picks.append({"n": nombre, "p": prob, "o": odd, "c": "Goles" if "Goles" in nombre else "1X2/DC"})
    return picks

# ---------- ANALIZADOR PRINCIPAL (SIN MULTIGOL) ----------
def analizar_titan(match):
    h_n = match['homeTeam']['name']
    a_n = match['awayTeam']['name']
    h_s = get_deep_data(match['homeTeam']['id'])
    a_s = get_deep_data(match['awayTeam']['id'])

    exH = ((h_s['gf'] + a_s['gc']) / 2) * 1.10
    exA = ((a_s['gf'] + h_s['gc']) / 2) * 0.95
    total_ex = exH + exA

    # Probabilidades 1X2
    pL_raw = sum(poisson(exH, i) * poisson(exA, j) for i in range(8) for j in range(8) if i > j)
    pV_raw = sum(poisson(exH, i) * poisson(exA, j) for i in range(8) for j in range(8) if j > i)
    pE_raw = 1 - pL_raw - pV_raw
    pL, pE, pV = round(pL_raw * 100), round(pE_raw * 100), round(pV_raw * 100)

    # Cuotas reales (opcional)
    sport_key = ODDS_MAP.get(match.get('league_code', ''))
    real_odds = get_live_odds(sport_key, h_n, a_n) if sport_key else None
    odd_1 = real_odds.get('1', 0) if real_odds else 0
    odd_X = real_odds.get('X', 0) if real_odds else 0
    odd_2 = real_odds.get('2', 0) if real_odds else 0

    # --- CABECERA CONSOLA ---
    print(f"\n{B}{BOLD}╔" + "═" * 70 + "╗")
    print(f"║  LUCI SPORT ANALYSIS: {h_n.upper()} vs {a_n.upper()} ║")
    print("╚" + "═" * 70 + "╝" + W)

    # --- RECOLECCIÓN DE RECOMENDACIONES (p >=60 y odd_calc >=1.50) ---
    recomendaciones = []

    def agregar_recomendacion(nombre, prob, odd_real=0):
        if odd_real == 0:
            odd_real = cuota_real_para(nombre, h_n, a_n, real_odds)
        if not cumple_recomendacion(nombre, prob, odd_real):
            return
        odd_calc = to_odds(prob)
        valor = (odd_real > odd_calc) if odd_real > 0 else False
        stake = calcular_stake(prob)
        if valor:
            stake = min(30, stake + 5)
        recomendaciones.append({
            "nombre": nombre,
            "prob": prob,
            "odd_calc": odd_calc,
            "stake": stake,
            "valor": valor,
            "odd_real": odd_real
        })

    # --- BLOQUE 1: 1X2 ---
    print(f"\n{C}{BOLD}⚽ MERCADOS PRINCIPALES (1X2 & DC){W}")
    print(f"  * Gana Local: {color_prob(pL)}{pL}%{W} (Min: {to_odds(pL)})" + (f" | Real: {odd_1}" if odd_1 else ""))
    print(f"  * Empate: {color_prob(pE)}{pE}%{W} (Min: {to_odds(pE)})" + (f" | Real: {odd_X}" if odd_X else ""))
    print(f"  * Gana Visita: {color_prob(pV)}{pV}%{W} (Min: {to_odds(pV)})" + (f" | Real: {odd_2}" if odd_2 else ""))
    print(f"  * 1X (Local/Empate): {color_prob(pL + pE)}{pL + pE}%{W}")
    print(f"  * X2 (Visita/Empate): {color_prob(pV + pE)}{pV + pE}%{W}")
    agregar_recomendacion(f"Gana {h_n}", pL, odd_1)
    agregar_recomendacion(f"Gana {a_n}", pV, odd_2)
    agregar_recomendacion(f"1X {h_n}", pL + pE)
    agregar_recomendacion(f"X2 {a_n}", pV + pE)

    # --- BLOQUE 2: GOLES ---
    print(f"\n{C}{BOLD}🎯 MERCADOS DE GOLES{W}")
    o15 = round((1 - sum(poisson(total_ex, i) for i in range(2))) * 100)
    o25 = round((1 - sum(poisson(total_ex, i) for i in range(3))) * 100)
    u35 = round(sum(poisson(total_ex, i) for i in range(4)) * 100)
    btts = round(((1 - poisson(exH, 0)) * (1 - poisson(exA, 0))) * 100)

    print(f"  * Más de 1.5 goles: {color_prob(o15)}{o15}%{W}")
    print(f"  * Más de 2.5 goles: {color_prob(o25)}{o25}%{W}")
    print(f"  * Menos de 3.5 goles: {color_prob(u35)}{u35}%{W}")
    print(f"  * Ambos marcan: {color_prob(btts)}{btts}%{W}")
    agregar_recomendacion("Más de 1.5 Goles", o15)
    agregar_recomendacion("Más de 2.5 Goles", o25)
    agregar_recomendacion("Menos de 3.5 Goles", u35)
    agregar_recomendacion("Ambos Marcan", btts)

    # --- BLOQUE 3: DISPAROS A PUERTA (ESCALONADO) ---
    print(f"\n{C}{BOLD}🎯 DISPAROS A PUERTA (ESCALONADO){W}")
    shots_total = (exH * 4.4 + exA * 4.1)
    base_shots = 7.5
    for i in range(9):
        th = base_shots + i
        p_step = max(5, min(95, round((shots_total * 8.5) - (i * 9))))
        print(f"  Más de {th:<11} | {color_prob(p_step)}{p_step}%{W}")
        agregar_recomendacion(f"Tiros Puerta +{th}", p_step)

    # --- BLOQUE 4: CÓRNERS (ESCALONADO) ---
    print(f"\n{C}{BOLD}🚩 CÓRNERS TOTALES (ESCALONADO){W}")
    est_corners = 3.5 + (h_s['gf'] + a_s['gf']) * 2.2
    base_c = 6.5
    for i in range(8):
        th = base_c + i
        p_c = max(5, min(95, round((est_corners * 9.5) - (i * 10))))
        print(f"  Más de {th:<11} | {color_prob(p_c)}{p_c}%{W}")
        agregar_recomendacion(f"Córners +{th}", p_c)

    # --- BLOQUE 5: TARJETAS ---
    print(f"\n{Y}{BOLD}🟨 TARJETAS POR EQUIPO{W}")
    p_h_tarj, p_a_tarj = 65, 72
    for i in range(3):
        th = 1.5 + i
        p_h = max(5, round(p_h_tarj - (i * 20)))
        p_a = max(5, round(p_a_tarj - (i * 20)))
        print(f"  {h_n} +{th:<7} | {color_prob(p_h)}{p_h}%{W}   ||   {a_n} +{th:<7} | {color_prob(p_a)}{p_a}%{W}")
        agregar_recomendacion(f"Tarjetas {h_n} +{th}", p_h)
        agregar_recomendacion(f"Tarjetas {a_n} +{th}", p_a)

    # --- BLOQUE 6: REMATES TOTALES ---
    print(f"\n{C}{BOLD}🚀 REMATES TOTALES (FUERA + PORTERÍA){W}")
    est_remates = shots_total * 2.8
    base_r = 18.5
    for i in range(5):
        th = base_r + (i * 2)
        p_r = max(5, min(95, round((est_remates * 4.5) - (i * 12))))
        print(f"  Más de {th:<11} | {color_prob(p_r)}{p_r}%{W}")
        agregar_recomendacion(f"Remates Totales +{th}", p_r)

    # --- BLOQUE 7: PORTERÍA A CERO ---
    print(f"\n{C}{BOLD}🧤 PORTERÍA A CERO{W}")
    p_csc_h = round(poisson(exA, 0) * 100)
    p_csc_a = round(poisson(exH, 0) * 100)
    print(f"  * {h_n} Portería a cero: {color_prob(p_csc_h)}{p_csc_h}%{W}")
    print(f"  * {a_n} Portería a cero: {color_prob(p_csc_a)}{p_csc_a}%{W}")

    # --- MEJORAS V2: DIXON-COLES, LÍNEAS MÁS/MENOS, CÓRNERS, TARJETAS Y TIROS ---
    for nombre_v2, prob_v2 in bloque_v2_mercados(h_n, a_n, h_s, a_s):
        agregar_recomendacion(nombre_v2, prob_v2)
    # --- LISTA DE RECOMENDACIONES (ordenadas de mayor a menor probabilidad) ---
    print(f"\n{Y}{BOLD}🔥 RECOMENDACIONES (Prob >=60% | Cuota >=1.50){W}")

    # Ordenar por probabilidad descendente
    recomendaciones.sort(key=lambda x: x['prob'], reverse=True)

    if not recomendaciones:
        print(f"   {R}No hay recomendaciones que cumplan los criterios para este evento.{W}")
    else:
        for rec in recomendaciones:
            # Mostrar diamante si prob >= 80
            diamante = f"{G} 💎{W}" if rec['prob'] >= 80 else ""
            valor_txt = f"{G} (Value){W}" if rec['valor'] else ""
            print(f"   {diamante} {rec['nombre']:<28} | Prob: {BOLD}{rec['prob']}%{W} | Cuota: {rec['odd_calc']} {valor_txt}")
            print(f"      ↳ {C}Stake sugerido: {rec['stake']}%{W}")

    print(f"\n{B}—" * 70 + f"{W}")

    # --- ENVÍO A TELEGRAM (lista completa) ---
    msg = f"🛰️ *LUCI SPORT ANALYSIS*\n"
    msg += f"⚽ {h_n} vs {a_n}\n\n"
    msg += f"📊 1X2: L {pL}% | E {pE}% | V {pV}%\n"
    msg += f"🎯 Goles: +1.5 {o15}% | +2.5 {o25}% | BTTS {btts}%\n\n"
    if recomendaciones:
        msg += f"🔥 *RECOMENDACIONES (ordenadas por confianza):*\n"
        for rec in recomendaciones:
            estrella = "💎" if rec['prob'] >= 80 else "⭐"
            valor_txt = " (Value)" if rec['valor'] else ""
            msg += f"{estrella} {rec['nombre']} – {rec['prob']}% (Cuota {rec['odd_calc']}, Stake {rec['stake']}%){valor_txt}\n"
    else:
        msg += "Sin recomendaciones.\n"
    msg += f"\n🤖 _Análisis generado por LuciSport_"
    ULTIMAS_RECOMENDACIONES[:] = recomendaciones
    enviar_a_telegram(msg)


# =====================================================================
#  MEJORAS V2 (bloques añadidos; el código original no se modificó)
# =====================================================================
DECAY_XI = 0.0019            # decaimiento temporal diario (vida media ~1 año)
SHRINK_K = 5                 # shrinkage hacia la media de liga con pocos partidos
MEDIA_LIGA_GOLES = 1.35      # media aproximada de goles por equipo
RHO_DC = -0.10               # corrección Dixon-Coles para marcadores bajos
MAX_GOLES = 10
MAX_RECS_V2 = 25             # tope de recomendaciones V2 (evita pasar el límite de Telegram)

# Parámetros HEURÍSTICOS para mercados que la fuente gratuita no publica
# (córners, tarjetas, tiros al arco). Reemplazar con datos reales cuando existan.
ALPHA_CORNERS = 0.08         # dispersión binomial negativa
ALPHA_TARJETAS = 0.15
ALPHA_TIROS = 0.10
TARJETAS_BASE_H = 2.0        # tarjetas esperadas por equipo
TARJETAS_BASE_A = 2.2

def poisson_seguro(lam, k):
    """Poisson correcto también cuando lam = 0 (el poisson original devuelve 0 para k=0)."""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(k * math.log(lam) - lam - math.lgamma(k + 1))

def nb_pmf(mu, alpha, k):
    """Binomial negativa con var = mu + alpha*mu^2 (alpha = 0 equivale a Poisson)."""
    if mu <= 0:
        return 1.0 if k == 0 else 0.0
    if alpha <= 1e-9:
        return poisson_seguro(mu, k)
    r = 1.0 / alpha
    p = r / (r + mu)
    return math.exp(math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)
                    + r * math.log(p) + k * math.log(1 - p))

def pmf_nb(mu, alpha, kmax=60):
    return [nb_pmf(mu, alpha, k) for k in range(kmax + 1)]

def convolucion(a, b):
    out = [0.0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            out[i + j] += x * y
    return out

def prob_mas_de(pmf, linea):
    """P(X > linea). Con líneas .5: 2.5 -> P(X >= 3)."""
    return sum(p for k, p in enumerate(pmf) if k > linea)

def matriz_dixon_coles(lh, la, rho=RHO_DC, n=MAX_GOLES):
    M = [[poisson_seguro(lh, i) * poisson_seguro(la, j) for j in range(n + 1)] for i in range(n + 1)]
    M[0][0] *= 1 - lh * la * rho
    M[0][1] *= 1 + lh * rho
    M[1][0] *= 1 + la * rho
    M[1][1] *= 1 - rho
    s = sum(sum(fila) for fila in M)
    return [[v / s for v in fila] for fila in M]

def _lineas(rng):
    lo, hi = rng
    return [round(lo + i, 1) for i in range(int(round(hi - lo)) + 1)]

def _par(p):
    return f"+{p * 100:4.1f}%/-{(1 - p) * 100:4.1f}%"

def _recs_linea(etiqueta, linea, p_mas):
    return [(f"{etiqueta} Más de {linea}", round(p_mas * 100)),
            (f"{etiqueta} Menos de {linea}", round((1 - p_mas) * 100))]

def _resumen_pesado(team_id, partidos, ref):
    """Media de goles a favor y en contra ponderada por antigüedad, con shrinkage."""
    sw = gf = gc = 0.0
    for m in partidos:
        try:
            fecha = datetime.strptime(m['utcDate'][:10], "%Y-%m-%d")
            dias = max(0, (ref - fecha).days)
            w = math.exp(-DECAY_XI * dias)
            local = m['homeTeam']['id'] == team_id
            ft = m['score']['fullTime']
            f = (ft['home'] if local else ft['away']) or 0
            c = (ft['away'] if local else ft['home']) or 0
            sw += w
            gf += w * f
            gc += w * c
        except Exception:
            continue
    gf_avg = (gf + SHRINK_K * MEDIA_LIGA_GOLES) / (sw + SHRINK_K)
    gc_avg = (gc + SHRINK_K * MEDIA_LIGA_GOLES) / (sw + SHRINK_K)
    return {"gf": gf_avg, "gc": gc_avg, "n": len(partidos)}

def get_deep_data_v2(team_id, limit=15):
    """Versión ponderada de get_deep_data: partidos recientes pesan más."""
    time.sleep(0.6)
    url = f"https://api.football-data.org/v4/teams/{team_id}/matches?status=FINISHED&limit={limit}"
    try:
        partidos = requests.get(url, headers=HEADERS, timeout=10).json().get("matches", [])
        return _resumen_pesado(team_id, partidos, datetime.now())
    except Exception:
        return {"gf": MEDIA_LIGA_GOLES, "gc": MEDIA_LIGA_GOLES, "n": 0}

def estimar_mercados_v2(h_s, a_s):
    """Mismas fórmulas de goles esperados del original, con datos ponderados."""
    exH = ((h_s['gf'] + a_s['gc']) / 2) * 1.10
    exA = ((a_s['gf'] + h_s['gc']) / 2) * 0.95
    return max(exH, 0.05), max(exA, 0.05)

def _bloque_conteo(titulo, etiqueta, mu_h, mu_a, alpha, lineas, h_n, a_n):
    ph = pmf_nb(mu_h, alpha)
    pa = pmf_nb(mu_a, alpha)
    pt = convolucion(ph, pa)
    recs = []
    print(f"\n{C}{BOLD}{titulo} (esperado total {mu_h + mu_a:.1f}){W}")
    for L in lineas:
        mt, mh, ma = prob_mas_de(pt, L), prob_mas_de(ph, L), prob_mas_de(pa, L)
        print(f"  Línea {L:<5} | Total {_par(mt)} | {h_n[:12]} {_par(mh)} | {a_n[:12]} {_par(ma)}")
        recs += _recs_linea(f"{etiqueta} total", L, mt)
        recs += _recs_linea(f"{etiqueta} {h_n}", L, mh)
        recs += _recs_linea(f"{etiqueta} {a_n}", L, ma)
    return recs

def bloque_v2_mercados(h_n, a_n, h_s, a_s):
    """Imprime los mercados V2 y devuelve [(nombre, prob)] para las recomendaciones."""
    exH, exA = estimar_mercados_v2(h_s, a_s)
    M = matriz_dixon_coles(exH, exA)
    n = len(M)
    pL = sum(M[i][j] for i in range(n) for j in range(n) if i > j)
    pE = sum(M[i][i] for i in range(n))
    pV = 1 - pL - pE

    # Distribuciones de goles: total (anti-diagonales), local y visitante (marginales)
    tot = [0.0] * (2 * n - 1)
    gh = [0.0] * n
    ga = [0.0] * n
    for i in range(n):
        for j in range(n):
            tot[i + j] += M[i][j]
            gh[i] += M[i][j]
            ga[j] += M[i][j]

    recs = []
    print(f"\n{C}{BOLD}🧮 MODELO V2 (Dixon-Coles + ponderación temporal){W}")
    print(f"  * Goles esperados: {h_n} {exH:.2f} | {a_n} {exA:.2f}")
    print(f"  * 1X2 Dixon-Coles: L {pL * 100:.1f}% | E {pE * 100:.1f}% | V {pV * 100:.1f}%")

    print(f"\n{C}{BOLD}📏 GOLES MÁS / MENOS (0.5 a 7.5){W}")
    for L in _lineas((0.5, 7.5)):
        mt, mh, ma = prob_mas_de(tot, L), prob_mas_de(gh, L), prob_mas_de(ga, L)
        print(f"  Línea {L:<4} | Total {_par(mt)} | {h_n[:12]} {_par(mh)} | {a_n[:12]} {_par(ma)}")
        recs += _recs_linea("Goles total", L, mt)
        recs += _recs_linea(f"Goles {h_n}", L, mh)
        recs += _recs_linea(f"Goles {a_n}", L, ma)

    # Córners: mismo total estimado que el bloque original, repartido 55/45
    est_corners = 3.5 + (h_s['gf'] + a_s['gf']) * 2.2
    recs += _bloque_conteo("🚩 CÓRNERS V2", "Córners", est_corners * 0.55, est_corners * 0.45,
                           ALPHA_CORNERS, _lineas((5.5, 14.5)), h_n, a_n)
    recs += _bloque_conteo("🟨 TARJETAS V2", "Tarjetas", TARJETAS_BASE_H, TARJETAS_BASE_A,
                           ALPHA_TARJETAS, _lineas((1.5, 8.5)), h_n, a_n)
    recs += _bloque_conteo("🥅 TIROS AL ARCO V2", "Tiros arco", exH * 3.2 + 1.0, exA * 3.2 + 0.8,
                           ALPHA_TIROS, _lineas((1.5, 12.5)), h_n, a_n)

    recs = sorted([r for r in recs if r[1] >= 60], key=lambda x: x[1], reverse=True)
    print(f"  {Y}(V2 aporta {min(len(recs), MAX_RECS_V2)} de {len(recs)} opciones con prob >=60%){W}")
    return recs[:MAX_RECS_V2]

def backtest_v2(cid, n_partidos=40):
    """Evalúa el 1X2 del modelo V2 sobre los últimos partidos terminados de una competición.
    Brier y log-loss menores son mejores. Azar: Brier 0.667, log-loss 1.099."""
    print(f"{Y}Descargando partidos terminados de {cid}...{W}")
    try:
        data = requests.get(f"https://api.football-data.org/v4/competitions/{cid}/matches?status=FINISHED",
                            headers=HEADERS, timeout=15).json().get("matches", [])
    except Exception as e:
        print(f"{R}Error al descargar: {e}{W}")
        return
    data = sorted(data, key=lambda m: m['utcDate'])[-n_partidos:]

    cache = {}
    def historial(team_id):
        if team_id not in cache:
            time.sleep(6.5)  # plan gratuito: ~10 peticiones por minuto
            try:
                r = requests.get(f"https://api.football-data.org/v4/teams/{team_id}/matches?status=FINISHED&limit=60",
                                 headers=HEADERS, timeout=15).json()
                cache[team_id] = r.get("matches", [])
            except Exception:
                cache[team_id] = []
        return cache[team_id]

    brier = ll = 0.0
    aciertos = evaluados = 0
    for m in data:
        ft = m['score']['fullTime']
        if ft['home'] is None or ft['away'] is None:
            continue
        fecha_m = m['utcDate'][:10]
        ref = datetime.strptime(fecha_m, "%Y-%m-%d")

        def previos(tid):
            ps = [x for x in historial(tid) if x['id'] != m['id'] and x['utcDate'][:10] < fecha_m]
            ps.sort(key=lambda x: x['utcDate'], reverse=True)
            return _resumen_pesado(tid, ps[:15], ref)

        exH, exA = estimar_mercados_v2(previos(m['homeTeam']['id']), previos(m['awayTeam']['id']))
        M = matriz_dixon_coles(exH, exA)
        n = len(M)
        pL = sum(M[i][j] for i in range(n) for j in range(n) if i > j)
        pE = sum(M[i][i] for i in range(n))
        probs = [pL, pE, 1 - pL - pE]
        real = [ft['home'] > ft['away'], ft['home'] == ft['away'], ft['home'] < ft['away']]
        y = [1.0 if r else 0.0 for r in real]
        brier += sum((p - t) ** 2 for p, t in zip(probs, y))
        ll += -math.log(max(probs[y.index(1.0)], 1e-9))
        aciertos += int(probs.index(max(probs)) == y.index(1.0))
        evaluados += 1

    if evaluados == 0:
        print(f"{R}Sin partidos evaluables.{W}")
        return
    print(f"\n{BOLD}RESULTADOS BACKTEST V2 - {cid} ({evaluados} partidos){W}")
    print(f"  Brier 1X2: {brier / evaluados:.4f}  (azar = 0.6667, menor es mejor)")
    print(f"  Log-loss : {ll / evaluados:.4f}  (azar = 1.0986)")
    print(f"  Acierto del favorito: {aciertos / evaluados:.1%}")
# ---------- PROGRAMA PRINCIPAL ----------
def main():
    while True:
        print(f"\n{C}{BOLD}🔥 LUCI SPORT - SISTEMA PREDICTIVO{W}")
        for k, v in LIGAS.items():
            print(f"  {BOLD}{C}{k}.{W} {v['n']}")
        print(f"  {BOLD}{C}b.{W} Backtest del modelo V2")
        sel_l = input(f"\n{Y}Selecciona liga (q=salir): {W}")
        if sel_l.lower() == 'q':
            break
        if sel_l.lower() == 'b':
            cid_bt = input(f"{Y}Código de competición (ej: PD, PL, SA): {W}").strip().upper()
            backtest_v2(cid_bt)
            continue

        try:
            dias = int(input(f"{Y}Días a futuro: {W}"))
            if sel_l == "0":
                codigos = [v['c'] for k, v in LIGAS.items() if v['c'] != "ALL"]
            else:
                codigos = [LIGAS[sel_l]['c']]
        except:
            print(f"{R}Opción inválida.{W}")
            continue

        partidos = []
        for cid in codigos:
            try:
                url = f"https://api.football-data.org/v4/competitions/{cid}/matches?dateFrom={datetime.now().strftime('%Y-%m-%d')}&dateTo={(datetime.now() + timedelta(days=dias)).strftime('%Y-%m-%d')}"
                data = requests.get(url, headers=HEADERS).json()
                for m in data.get("matches", []):
                    if m['status'] != 'FINISHED':
                        m['league_code'] = cid
                        partidos.append(m)
            except:
                pass

        if not partidos:
            print(f"{R}No hay partidos en ese rango.{W}")
            continue

        while True:
            print(f"\n{B}{BOLD}📅 PARTIDOS DISPONIBLES:{W}")
            for i, p in enumerate(partidos, 1):
                estado = f"{R}[LIVE]{W}" if p['status'] in ['IN_PLAY', 'PAUSED'] else f"{G}[PRE]{W}"
                print(f"  {i}. {estado} {p['homeTeam']['name']} vs {p['awayTeam']['name']}")
            print(f"  C. {BOLD}CREAR COMBINADA INTELIGENTE{W}")

            opc = input(f"\n{Y}Opción (m=menú principal): {W}")
            if opc.lower() == 'm':
                break

            if opc.lower() == 'c':
                ids_str = input(f"{Y}IDs de partidos separados por coma (ej: 1,3,5): {W}")
                ids_list = ids_str.split(',')
                cuota_total = 1.0
                descripcion = ""
                for idp in ids_list:
                    try:
                        idx = int(idp.strip()) - 1
                        if idx < 0 or idx >= len(partidos):
                            continue
                        picks = extraer_picks_gold(partidos[idx])
                        if picks:
                            # Usar el de mayor probabilidad
                            mejor_pick = max(picks, key=lambda x: x['p'])
                            descripcion += f"🔹 {partidos[idx]['homeTeam']['name']} vs {partidos[idx]['awayTeam']['name']}\n   Pick: *{mejor_pick['n']}* ({mejor_pick['p']}%)\n"
                            cuota_total *= mejor_pick['o']
                    except:
                        continue
                if descripcion:
                    mensaje = f"🚀 *LUCI SPORT SMART COMBO*\n\n{descripcion}\n📈 *Cuota Total: {round(cuota_total, 2)}*\n💰 *Stake sugerido: 5%*"
                    enviar_a_telegram(mensaje)
                    print(f"{G}Combinada enviada por Telegram.{W}")
                else:
                    print(f"{R}No se pudieron generar picks para esos partidos.{W}")
                continue

            try:
                idx = int(opc) - 1
                if 0 <= idx < len(partidos):
                    analizar_titan(partidos[idx])
                    input(f"\n{G}Presiona ENTER para continuar...{W}")
            except:
                pass

if __name__ == "__main__":
    main()