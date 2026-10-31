# LuciSport Web (Vercel)

Página que ejecuta `LuciSport_V1_9.py` en Vercel y muestra la misma salida que la terminal.

Estructura:
- `index.html`: interfaz (elegir liga, buscar partidos, analizar)
- `api/partidos.py`: lista de partidos
- `api/analizar.py`: ejecuta el análisis del archivo original
- `luci_web.py`: puente que captura la salida de consola
- `LuciSport_V1_9.py`: tu archivo original, sin cambios de lógica

Despliegue: sube esta carpeta a GitHub, importa el repositorio en Vercel y define
la variable `FOOTBALL_API_KEY` en Settings > Environment Variables.
