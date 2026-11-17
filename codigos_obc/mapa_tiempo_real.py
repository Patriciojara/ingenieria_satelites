# Descripcion: lee los correos que entrega RockBLOCK, extrae las posiciones
# enviadas por envia_ubicacion.py y las muestra en un mapa que se actualiza solo.
# Se ejecuta en el PC de la estacion terrena (no en la RPi). Solo usa la
# biblioteca estandar de Python; el mapa usa Leaflet + OpenStreetMap (internet).
#
# Uso con el correo (IMAP):
#   export IMAP_USUARIO=tu_correo@ug.uchile.cl
#   export IMAP_CLAVE=contraseña_de_aplicacion     # si no, la pide al iniciar
#   python3 mapa_tiempo_real.py
#   -> abrir http://localhost:8000
#
# Trayectoria por ejecucion: cada vez que se inicia el script empieza una
# trayectoria nueva. El mapa dibuja solo los mensajes transmitidos desde que se
# inicio, y cada punto se agrega a trayectorias/trayectoria_AAAA-MM-DD_HHMMSS.csv.
#   --continuar archivo.csv   si el script se cerro a mitad de vuelo: recarga
#                             esa trayectoria y sigue agregando al mismo archivo
#   --incluir-anteriores      dibujar tambien los correos de antes de iniciar
#                             (desde --desde, por defecto hoy)
#   --csv ""                  no guardar CSV
#
# Uso sin correo, con archivos .eml descargados en una carpeta (para probar):
#   python3 mapa_tiempo_real.py --eml carpeta_correos
#
# Mensajes aceptados:
#   - de envia_ubicacion.py:  HHMMSS,lat,lon,alt_m,vel_kmh   (hora local de la RPi)
#   - NMEA resumido:          RMC,lat,lon,ddmmaa,hhmmss.sss,vel_nudos,rumbo,var,
#                             GGA,lat,lon,fix,sats,hdop,alt_m,geoide   (hora UTC)
#   - sensores + GPS:         temp_C pres_hPa hum_% lat lon   (separados por espacio,
#                             sin hora: se usa el Transmit Time de Iridium)
# Se leen los correos de rock7 y tambien los reenviados (asunto con "RockBLOCK").

import argparse
import csv
import email
import getpass
import imaplib
import json
import os
import re
import threading
import time
import webbrowser
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MENSAJE_RE = re.compile(
    rb'(\d{6}),(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)')
# Formato NMEA resumido (visto en el correo real de RockBLOCK, MOMSN 253):
# RMC,lat,lon,ddmmaa,hhmmss.sss,vel_nudos,rumbo,var_mag,GGA,lat,lon,fix,sats,hdop,alt_m,geoide
RMC_RE = re.compile(rb'RMC,[^\r\n<]*')
NUDO_KMH = 1.852
# Formato con sensores (MOMSN 268): "22.7 949.0 49.2 -33.460359 -70.660723"
# = temperatura C, presion hPa, humedad %, lat, lon. Una sola linea, espacios.
_NUM = rb'(-?\d+(?:\.\d+)?)'
SENSORES_RE = re.compile(
    rb'(?m)^[ \t]*' + _NUM + rb'[ \t]+' + _NUM + rb'[ \t]+' + _NUM +
    rb'[ \t]+(-?\d{1,2}\.\d+)[ \t]+(-?\d{1,3}\.\d+)[ \t]*\r?$')
P0_HPA = 1013.25   # presion al nivel del mar para la altitud barometrica
# Cabecera Rock7: sirve para ordenar y para no duplicar el mismo mensaje.
TX_RE = re.compile(rb'Transmit Time:\s*(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)', re.I)
MOMSN_RE = re.compile(rb'MOMSN:\s*(\d+)', re.I)
IMEI_RE = re.compile(rb'IMEI:\s*(\d{15})', re.I)
HEX_RE = re.compile(rb'\b(?:[0-9a-fA-F]{2}){12,}\b')
# Posicion estimada por la red Iridium (formato Rock7 y formato Iridium clasico).
IRI_LAT_RE = re.compile(rb'iridium[_ ]lat(?:itude)?[\s:="]*(-?\d+\.\d+)', re.I)
IRI_LON_RE = re.compile(rb'iridium[_ ]lon(?:gitude)?[\s:="]*(-?\d+\.\d+)', re.I)
IRI_CLASICO_RE = re.compile(rb'Lat\s*=\s*(-?\d+\.\d+)\s+Long\s*=\s*(-?\d+\.\d+)', re.I)
IRI_CEP_RE = re.compile(rb'(?:iridium[_ ]cep|CEPradius)\W*(\d+(?:\.\d+)?)', re.I)

posiciones = {}          # clave -> dict; clave = Message-ID del correo
historial = {'ruta': None}   # archivo CSV de la trayectoria de esta ejecucion
# Mensajes transmitidos antes de este instante no son parte de la trayectoria
# (None = aceptar todos). Se fija en main().
filtro = {'desde_ts': None, 'ignorados': set()}

# Columnas del CSV. Los campos que un formato no trae quedan vacios.
COLUMNAS = ['_id', 'recibido', 'hora_gps', 'lat', 'lon', 'alt', 'vel',
            'temp', 'pres', 'hum', 'sats', 'momsn',
            'iri_lat', 'iri_lon', 'iri_cep_km', 'formato', 'asunto', 'orden']
ENTEROS = {'sats', 'momsn'}
TEXTOS = {'_id', 'recibido', 'hora_gps', 'formato', 'asunto'}
candado = threading.Lock()
estado = {'ultima_revision': None, 'error': None}


# ---------------------------------------------------------------- parseo ----
def contenidos(msg):
    """Todos los bytes del correo donde podria venir el mensaje de la sonda."""
    trozos = []
    for parte in msg.walk():
        if parte.is_multipart():
            continue
        datos = parte.get_payload(decode=True) or b''
        trozos.append(datos)
        # Rock7 suele entregar el payload en hexadecimal en el cuerpo.
        for h in HEX_RE.findall(datos):
            try:
                trozos.append(bytes.fromhex(h.decode()))
            except ValueError:
                pass
    return trozos


def buscar(regex, trozos):
    for t in trozos:
        m = regex.search(t)
        if m:
            return m
    return None


def _num(campos, i, defecto=0.0):
    try:
        return float(campos[i])
    except (IndexError, ValueError):
        return defecto


def posicion_rmc(trozos):
    """Formato 'RMC,...,GGA,...'. Devuelve dict o None si no hay fix."""
    m = buscar(RMC_RE, trozos)
    if not m:
        return None
    c = m.group(0).decode('ascii', errors='ignore').split(',')
    lat, lon = _num(c, 1, None), _num(c, 2, None)
    if lat is None or lon is None or (lat == 0 and lon == 0):
        return None
    hora = c[4].split('.')[0] if len(c) > 4 else ''
    p = {'hhmmss': hora if len(hora) == 6 else '000000',
         'lat': lat, 'lon': lon,
         'vel': _num(c, 5) * NUDO_KMH,          # RMC entrega la velocidad en nudos
         'alt': 0.0, 'formato': 'RMC/GGA (hora UTC)'}
    if 'GGA' in c:
        g = c[c.index('GGA'):]                  # GGA,lat,lon,fix,sats,hdop,alt,geoide
        if g[3:4] == ['0']:
            return None                         # GGA dice que no hay fix
        p['alt'] = _num(g, 6)
        if len(g) > 4 and g[4].isdigit():
            p['sats'] = int(g[4])
    return p


def posicion_sensores(trozos):
    """Formato 'temp pres hum lat lon'. Devuelve dict o None."""
    m = buscar(SENSORES_RE, trozos)
    if not m:
        return None
    temp, pres, hum, lat, lon = (float(g) for g in m.groups())
    if lat == 0 and lon == 0:
        return None                             # sin fix GPS
    # Altitud barometrica (atmosfera estandar); el mensaje no trae altitud GPS.
    alt = 44330.0 * (1 - (pres / P0_HPA) ** 0.1903) if pres > 0 else 0.0
    return {'hhmmss': None, 'lat': lat, 'lon': lon, 'alt': alt, 'vel': 0.0,
            'temp': temp, 'pres': pres, 'hum': hum,
            'formato': 'sensores (temp pres hum lat lon), alt. barométrica'}


def parsear_correo(crudo):
    msg = email.message_from_bytes(crudo)
    trozos = contenidos(msg)
    m = buscar(MENSAJE_RE, trozos)
    if m:
        hhmmss, lat, lon, alt, vel = (g.decode() for g in m.groups())
        base = {'hhmmss': hhmmss, 'lat': float(lat), 'lon': float(lon),
                'alt': float(alt), 'vel': float(vel), 'formato': 'envia_ubicacion.py'}
    else:
        base = posicion_sensores(trozos) or posicion_rmc(trozos)
        if base is None:
            return None
    hhmmss, lat, lon = base['hhmmss'], base['lat'], base['lon']
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None

    # Hora de transmision Iridium (UTC); si no esta, la fecha del correo.
    tx = buscar(TX_RE, trozos)
    try:
        if tx:
            recibido = datetime.fromisoformat(tx.group(1).decode() + '+00:00').astimezone()
        else:
            recibido = parsedate_to_datetime(msg['Date']).astimezone()
    except (TypeError, ValueError):
        recibido = None

    if hhmmss is None:      # el formato no trae hora: se usa la de transmision
        hhmmss = recibido.strftime('%H%M%S') if recibido else '000000'
    p = {
        'hora_gps': f'{hhmmss[:2]}:{hhmmss[2:4]}:{hhmmss[4:]}',
        'lat': lat, 'lon': lon, 'alt': base['alt'], 'vel': base['vel'],
        'formato': base['formato'],
        'recibido': recibido.strftime('%Y-%m-%d %H:%M:%S') if recibido else '',
        'orden': recibido.timestamp() if recibido else 0,
        'asunto': msg.get('Subject', ''),
    }
    for k in ('sats', 'temp', 'pres', 'hum'):
        if k in base:
            p[k] = base[k]
    momsn = buscar(MOMSN_RE, trozos)
    if momsn:
        p['momsn'] = int(momsn.group(1))

    # Estimacion de Iridium (opcional, sirve para comparar con el GPS).
    la, lo = buscar(IRI_LAT_RE, trozos), buscar(IRI_LON_RE, trozos)
    if la and lo:
        p['iri_lat'], p['iri_lon'] = float(la.group(1)), float(lo.group(1))
    else:
        c = buscar(IRI_CLASICO_RE, trozos)
        if c:
            p['iri_lat'], p['iri_lon'] = float(c.group(1)), float(c.group(2))
    cep = buscar(IRI_CEP_RE, trozos)
    if cep and 'iri_lat' in p:
        p['iri_cep_km'] = float(cep.group(1))

    # IMEI+MOMSN identifica el mensaje aunque llegue el original y un reenvio.
    imei = buscar(IMEI_RE, trozos)
    if momsn and imei:
        p['_id'] = f'{imei.group(1).decode()}#{p["momsn"]}'
    else:
        p['_id'] = msg.get('Message-ID') or f"{p['recibido']}|{lat},{lon}"
    return p


def guardar_en_historial(p):
    ruta = historial['ruta']
    if not ruta:
        return
    try:
        nuevo_archivo = not ruta.exists() or ruta.stat().st_size == 0
        with open(ruta, 'a', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=COLUMNAS, extrasaction='ignore')
            if nuevo_archivo:
                w.writeheader()
            w.writerow(p)
    except OSError as e:
        print(f'  ! No se pudo guardar en {ruta}: {e}', flush=True)


def cargar_historial(ruta):
    """Carga una trayectoria guardada (para --continuar)."""
    if not ruta.exists():
        return 0
    n = 0
    with open(ruta, newline='', encoding='utf-8') as f:
        for fila in csv.DictReader(f):
            p = {}
            for k, v in fila.items():
                if k not in COLUMNAS or v in (None, ''):
                    continue
                try:
                    p[k] = v if k in TEXTOS else (int(v) if k in ENTEROS else float(v))
                except ValueError:
                    pass
            if all(k in p for k in ('_id', 'lat', 'lon')):
                p.setdefault('alt', 0.0); p.setdefault('vel', 0.0)
                p.setdefault('orden', 0.0); p.setdefault('hora_gps', '')
                p.setdefault('recibido', ''); p.setdefault('formato', '')
                posiciones[p['_id']] = p
                n += 1
    return n


def agregar(p):
    if p is None:
        return False
    # Mensaje anterior al inicio de esta ejecucion: no es parte de la trayectoria.
    if filtro['desde_ts'] is not None and p['orden'] < filtro['desde_ts']:
        if p['_id'] not in posiciones:
            filtro['ignorados'].add(p['_id'])
        return False
    with candado:
        nuevo = p['_id'] not in posiciones
        posiciones[p['_id']] = p
    if nuevo:
        guardar_en_historial(p)
        print(f"  + {p['hora_gps']}  {p['lat']:.5f}, {p['lon']:.5f}  "
              f"alt {p['alt']:.0f} m  (correo {p['recibido']})", flush=True)
    return nuevo


# --------------------------------------------------------------- fuentes ----
class FuenteIMAP:
    def __init__(self, args):
        self.args = args
        self.usuario = args.usuario or os.environ.get('IMAP_USUARIO') or input('Correo: ')
        self.clave = os.environ.get('IMAP_CLAVE') or getpass.getpass('Contraseña de aplicación: ')
        self.vistos = set()

    def revisar(self):
        # Se conecta en cada ciclo: es mas robusto que mantener la sesion abierta.
        with imaplib.IMAP4_SSL(self.args.servidor) as imap:
            imap.login(self.usuario, self.clave)
            imap.select(f'"{self.args.carpeta}"', readonly=True)  # no marca como leido
            criterio = ['SINCE', self.args.desde.strftime('%d-%b-%Y')]
            # Remitente rock7 O asunto "RockBLOCK" (asi tambien entran los reenvios).
            if self.args.remitente and self.args.asunto:
                criterio += ['OR', 'FROM', f'"{self.args.remitente}"',
                             'SUBJECT', f'"{self.args.asunto}"']
            elif self.args.remitente:
                criterio += ['FROM', f'"{self.args.remitente}"']
            tipo, datos = imap.uid('SEARCH', None, *criterio)
            if tipo != 'OK':
                raise RuntimeError(f'Busqueda IMAP fallida: {datos}')
            nuevos = [u for u in datos[0].split() if u not in self.vistos]
            for uid in nuevos:
                tipo, partes = imap.uid('FETCH', uid, '(BODY.PEEK[])')
                if tipo == 'OK' and partes and isinstance(partes[0], tuple):
                    agregar(parsear_correo(partes[0][1]))
                self.vistos.add(uid)


class FuenteEML:
    def __init__(self, args):
        self.carpeta = Path(args.eml)
        self.vistos = set()

    def revisar(self):
        for ruta in sorted(self.carpeta.glob('*.eml')):
            if ruta not in self.vistos:
                agregar(parsear_correo(ruta.read_bytes()))
                self.vistos.add(ruta)


def bucle(fuente, intervalo):
    while True:
        try:
            fuente.revisar()
            estado['error'] = None
        except Exception as e:  # sin internet, clave mala, etc.: se reintenta
            estado['error'] = f'{type(e).__name__}: {e}'
            print(f'  ! Error al revisar correo: {estado["error"]}', flush=True)
        estado['ultima_revision'] = datetime.now().strftime('%H:%M:%S')
        ign = len(filtro['ignorados'])
        print(f"[{estado['ultima_revision']}] {len(posiciones)} puntos en la trayectoria"
              + (f" ({ign} correos anteriores al inicio, no dibujados)" if ign else ''),
              flush=True)
        time.sleep(intervalo)


# ------------------------------------------------------------------ web -----
PAGINA = """<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<title>Sonda - ubicacion en tiempo real</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
 html,body{margin:0;height:100%;font-family:system-ui,sans-serif}
 #mapa{position:absolute;inset:0}
 #panel{position:absolute;top:10px;right:10px;z-index:1000;background:#fff;
   padding:10px 14px;border-radius:8px;box-shadow:0 1px 6px #0004;font-size:14px;
   max-width:300px;line-height:1.5}
 #panel b{font-size:15px} .err{color:#b00020} .gris{color:#666}
 #controles{position:absolute;bottom:22px;left:10px;z-index:1000;background:#fff;
   padding:6px 10px;border-radius:8px;box-shadow:0 1px 6px #0004;font-size:13px}
 #controles button{font-size:13px;margin-left:6px}
</style></head><body>
<div id="mapa"></div>
<div id="panel">Cargando…</div>
<div id="controles">
  <label><input type="checkbox" id="seguir" checked> Seguir la sonda</label>
  <button id="ver_todo">Ver trayectoria completa</button>
</div>
<script>
const REFRESCO_S = __REFRESCO__;
const mapa = L.map('mapa').setView([-33.45, -70.66], 6);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  {maxZoom: 19, attribution: '&copy; OpenStreetMap'}).addTo(mapa);
const capa = L.layerGroup().addTo(mapa);
let n_anterior = -1;
let ruta_actual = [];

function distancia_km(a, b) {            // haversine
  const R = 6371, rad = Math.PI / 180;
  const dlat = (b[0] - a[0]) * rad, dlon = (b[1] - a[1]) * rad;
  const h = Math.sin(dlat/2)**2 +
            Math.cos(a[0]*rad) * Math.cos(b[0]*rad) * Math.sin(dlon/2)**2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

function ver_todo() {
  if (ruta_actual.length > 1) mapa.fitBounds(L.latLngBounds(ruta_actual),
    {paddingTopLeft: [40, 230], paddingBottomRight: [340, 70]});   // deja libre el panel
  else if (ruta_actual.length) mapa.setView(ruta_actual[0], 14);
}
document.getElementById('ver_todo').onclick = () => {
  document.getElementById('seguir').checked = false; ver_todo(); };

function sensores(p) {
  if (p.temp === undefined) return '';
  return `<br>${p.temp.toFixed(1)} °C · ${p.pres.toFixed(1)} hPa · ${p.hum.toFixed(1)} % hum.`;
}

function popup(p, i, n) {
  let s = `<b>Punto ${i + 1} de ${n} · ${p.hora_gps}</b><br>${p.lat.toFixed(5)}, ${p.lon.toFixed(5)}` +
          `<br>Altitud ${p.alt.toFixed(0)} m · ${p.vel.toFixed(0)} km/h` +
          (p.sats !== undefined ? ` · ${p.sats} satélites` : '') +
          sensores(p) +
          `<br><span class="gris">Transmitido: ${p.recibido}` +
          (p.momsn !== undefined ? ` · MOMSN ${p.momsn}` : '') + `</span>` +
          `<br><span class="gris">Formato: ${p.formato}</span>`;
  if (p.iri_lat !== undefined)
    s += `<br><span class="gris">Iridium: ${p.iri_lat.toFixed(3)}, ${p.iri_lon.toFixed(3)}</span>`;
  return s;
}

async function actualizar() {
  let d;
  try { d = await (await fetch('posiciones.json', {cache: 'no-store'})).json(); }
  catch (e) { document.getElementById('panel').innerHTML =
      '<span class="err">Sin conexion con mapa_tiempo_real.py</span>'; return; }

  const ps = d.posiciones;
  const ruta = ps.map(p => [p.lat, p.lon]);
  let dist = 0;
  for (let i = 1; i < ruta.length; i++) dist += distancia_km(ruta[i - 1], ruta[i]);

  let html = '';
  if (ps.length) {
    const u = ps[ps.length - 1], p0 = ps[0];
    const gmaps = `https://www.google.com/maps?q=${u.lat},${u.lon}`;
    const alt_max = Math.max(...ps.map(p => p.alt));
    const min = Math.round((u.orden - p0.orden) / 60);
    html += `<b>Ultima posicion</b><br>${u.lat.toFixed(5)}, ${u.lon.toFixed(5)}<br>` +
            `Alt ${u.alt.toFixed(0)} m · ${u.vel.toFixed(0)} km/h · ${u.hora_gps}` +
            sensores(u) + `<br>` +
            `<a href="${gmaps}" target="_blank">Abrir en Google Maps</a><br>` +
            `<b>Trayectoria</b><br>${ps.length} puntos · ${dist.toFixed(2)} km recorridos<br>` +
            `${min} min de vuelo · alt. máx ${alt_max.toFixed(0)} m<br>`;
  } else html += '<b>Esperando el primer mensaje…</b><br>' +
                 `<span class="gris">Trayectoria iniciada ${d.inicio || ''}</span><br>`;
  html += `<span class="gris">Correo revisado ${d.ultima_revision || '-'}`;
  if (d.csv) html += `<br>Guardando en ${d.csv}`;
  html += `</span>`;
  if (d.error) html += `<br><span class="err">${d.error}</span>`;
  document.getElementById('panel').innerHTML = html;

  if (ps.length === n_anterior) return;   // nada nuevo: no tocar el zoom
  ruta_actual = ruta;
  capa.clearLayers();
  if (ruta.length > 1) {
    L.polyline(ruta, {color: '#1565c0', weight: 4, opacity: 0.85}).addTo(capa);
    // flechas de direccion en la mitad de cada tramo
    for (let i = 1; i < ruta.length; i++) {
      const a = ruta[i - 1], b = ruta[i];
      if (distancia_km(a, b) < 0.005) continue;
      const ang = Math.atan2(b[0] - a[0], (b[1] - a[1]) * Math.cos(a[0] * Math.PI / 180)) * 180 / Math.PI;
      L.marker([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], {interactive: false, icon: L.divIcon({
        className: '', iconSize: [14, 14], iconAnchor: [7, 7],
        html: `<div style="transform:rotate(${90 - ang}deg);color:#1565c0;font-size:14px;line-height:14px">▲</div>`
      })}).addTo(capa);
    }
  }
  ps.forEach((p, i) => {
    const ultimo = i === ps.length - 1, primero = i === 0;
    const color = ultimo ? '#c62828' : (primero ? '#2e7d32' : '#1565c0');
    L.circleMarker([p.lat, p.lon], {radius: ultimo ? 9 : (primero ? 7 : 4), weight: 2,
      color: color, fillOpacity: 0.85})
      .bindPopup(popup(p, i, ps.length) + (primero ? '<br><b>Inicio</b>' : '')).addTo(capa);
    if (ultimo && p.iri_lat !== undefined && p.iri_cep_km)
      L.circle([p.iri_lat, p.iri_lon], {radius: p.iri_cep_km * 1000, color: '#888',
        weight: 1, fillOpacity: 0.08, dashArray: '4'}).bindPopup('Estimacion Iridium').addTo(capa);
  });
  if (ps.length) {
    const u = ps[ps.length - 1];
    if (n_anterior <= 0) ver_todo();
    else if (document.getElementById('seguir').checked) mapa.panTo([u.lat, u.lon]);
  }
  n_anterior = ps.length;
}
actualizar();
setInterval(actualizar, REFRESCO_S * 1000);
</script></body></html>
"""


class Manejador(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/posiciones.json'):
            with candado:
                lista = sorted(posiciones.values(), key=lambda p: (p['orden'], p['hora_gps']))
                lista = [{k: v for k, v in p.items() if not k.startswith('_')} for p in lista]
            extra = {'csv': historial['ruta'].name if historial['ruta'] else None}
            cuerpo = json.dumps({'posiciones': lista, **estado, **extra}).encode()
            tipo = 'application/json'
        elif self.path in ('/', '/index.html'):
            cuerpo = PAGINA.replace('__REFRESCO__', '15').encode()
            tipo = 'text/html; charset=utf-8'
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', tipo)
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *a):
        pass  # silenciar el log de cada peticion


def main():
    ap = argparse.ArgumentParser(description='Mapa en tiempo real de la sonda (RockBLOCK por correo)')
    ap.add_argument('--intervalo', type=float, default=30, help='segundos entre revisiones del correo')
    ap.add_argument('--puerto', type=int, default=8000)
    ap.add_argument('--eml', help='leer archivos .eml de esta carpeta en vez de IMAP')
    ap.add_argument('--servidor', default='imap.gmail.com', help='servidor IMAP')
    ap.add_argument('--usuario', help='correo (o variable IMAP_USUARIO)')
    ap.add_argument('--carpeta', default='INBOX', help='carpeta IMAP donde llegan los mensajes')
    ap.add_argument('--remitente', default='rock7',
                    help='filtro FROM (texto contenido en el remitente); "" = leer todos los correos')
    ap.add_argument('--asunto', default='RockBLOCK',
                    help='tambien acepta correos con este texto en el asunto (reenvios)')
    ap.add_argument('--desde', type=date.fromisoformat, default=date.today(),
                    help='revisar correos desde esta fecha AAAA-MM-DD (por defecto hoy)')
    ap.add_argument('--csv', help='CSV donde guardar la trayectoria (por defecto uno nuevo en '
                    'trayectorias/ con la fecha y hora de inicio; "" = no guardar)')
    ap.add_argument('--continuar', metavar='CSV',
                    help='recargar una trayectoria guardada y seguir agregando a ese archivo')
    ap.add_argument('--incluir-anteriores', action='store_true',
                    help='dibujar tambien los mensajes transmitidos antes de iniciar el script')
    ap.add_argument('--no-abrir', action='store_true', help='no abrir el navegador')
    args = ap.parse_args()

    inicio = datetime.now().astimezone()
    estado['inicio'] = inicio.strftime('%Y-%m-%d %H:%M:%S')
    # Con --eml se prueba con correos viejos: se aceptan todos.
    if not (args.incluir_anteriores or args.eml or args.continuar):
        filtro['desde_ts'] = inicio.timestamp()

    if args.continuar:
        historial['ruta'] = Path(args.continuar)
        n = cargar_historial(historial['ruta'])
        if n:   # sigue desde el primer punto de esa trayectoria
            filtro['desde_ts'] = min(p['orden'] for p in posiciones.values())
        print(f'Continuando {historial["ruta"]} ({n} puntos cargados)')
    elif args.csv != '':
        if args.csv:
            historial['ruta'] = Path(args.csv)
        else:
            carpeta = Path(__file__).with_name('trayectorias')
            carpeta.mkdir(exist_ok=True)
            historial['ruta'] = carpeta / f"trayectoria_{inicio.strftime('%Y-%m-%d_%H%M%S')}.csv"
        print(f'Trayectoria nueva: se guarda en {historial["ruta"]}')
    if filtro['desde_ts'] is not None and not args.continuar:
        print(f"Solo se dibujan mensajes transmitidos desde las {inicio.strftime('%H:%M:%S')}")
    fuente = FuenteEML(args) if args.eml else FuenteIMAP(args)
    threading.Thread(target=bucle, args=(fuente, args.intervalo), daemon=True).start()

    url = f'http://localhost:{args.puerto}'
    print(f'Mapa en {url}  (Ctrl+C para salir)')
    if not args.no_abrir:
        webbrowser.open(url)
    try:
        ThreadingHTTPServer(('127.0.0.1', args.puerto), Manejador).serve_forever()
    except KeyboardInterrupt:
        print('\nDetenido.')


if __name__ == '__main__':
    main()
