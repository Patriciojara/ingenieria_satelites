# Cómo usar `mapa_tiempo_real.py`

Este script se corre en el PC de la estación terrena. Revisa el Gmail donde Rock7 entrega los mensajes del RockBLOCK, saca la posición de cada mensaje y la dibuja en un mapa en el navegador. A medida que llegan mensajes va trazando la trayectoria de la sonda y la guarda en un CSV.

Solo usa la biblioteca estándar de Python 3, así que no hay que instalar nada. El mapa necesita internet para cargar el fondo de OpenStreetMap.

```
RPi + RockBLOCK  →  satélite Iridium  →  Rock7  →  Gmail  →  mapa_tiempo_real.py  →  navegador
```

---

## 1. Iniciar el mapa

Desde la carpeta donde está el script:

```bash
export IMAP_USUARIO=satelites295@gmail.com
python3 mapa_tiempo_real.py
```

- Pide la **contraseña de aplicación** de Gmail: 16 letras, sin espacios. No es la contraseña normal de la cuenta. Pídesela a quien administra el correo. Para que no la pida cada vez, se puede dejar en la variable `IMAP_CLAVE` (`export IMAP_CLAVE=...`).
- Se abre solo el navegador en **http://localhost:8000**.
- Para detenerlo: `Ctrl+C`.

Al iniciar, la consola muestra algo así:

```
Trayectoria nueva: se guarda en .../trayectorias/trayectoria_2026-11-17_143012.csv
Solo se dibujan mensajes transmitidos desde las 14:30:12
Mapa en http://localhost:8000  (Ctrl+C para salir)
[14:30:14] 0 puntos en la trayectoria (5 correos anteriores al inicio, no dibujados)
  + 14:32:58  -33.46036, -70.66072  alt 549 m  (correo 2026-11-17 14:32:58)
[14:32:44] 1 puntos en la trayectoria ...
```

Cada línea que empieza con `+` es un punto nuevo agregado a la trayectoria.

---

## 2. Cómo funciona la trayectoria

**Cada ejecución es una trayectoria nueva.** Al iniciar el script:

1. Solo se dibujan los mensajes **transmitidos después de iniciar el script**, según la hora de transmisión de Iridium. Los correos anteriores del día se ignoran, así no se mezclan con pruebas viejas.
2. Cada punto nuevo se agrega a un CSV propio de esa ejecución, dentro de la carpeta `trayectorias/`, junto al script:
   `trayectorias/trayectoria_AAAA-MM-DD_HHMMSS.csv`
   (la fecha y hora son las de inicio). La carpeta y el archivo se crean solos al llegar el primer punto.
3. Los puntos se ordenan por hora de transmisión. Si un mensaje llega dos veces (por ejemplo, el original y un reenvío), se dibuja una sola vez, porque se identifica por IMEI + MOMSN.

**Recomendación para el día del lanzamiento:** iniciar el script poco antes de encender la sonda y no cerrarlo hasta recuperarla.

### Si el script se cerró a mitad de vuelo

Volver a iniciarlo con `--continuar` y el CSV de esa trayectoria:

```bash
python3 mapa_tiempo_real.py --continuar trayectorias/trayectoria_2026-11-17_143012.csv
```

Así recarga los puntos que ya tenía, recupera los mensajes que llegaron mientras estuvo cerrado y sigue guardando en el mismo archivo.

---

## 3. El mapa

- **Línea azul con flechas:** la trayectoria, en el orden en que se transmitieron los mensajes.
- **Punto verde:** inicio de la trayectoria. **Punto rojo:** última posición recibida.
- **Círculo gris punteado:** zona donde la red Iridium estima que estaba el RockBLOCK (sirve para comparar con el GPS).
- **Clic en un punto:** muestra el número de punto, la hora, las coordenadas, la altitud, la velocidad, los datos de sensores (si vienen), el MOMSN y la estimación de Iridium.

**Panel (arriba a la derecha):** última posición, enlace a Google Maps, cantidad de puntos, km recorridos, minutos de vuelo, altitud máxima, hora de la última revisión del correo y nombre del CSV. Si hay un error de conexión o de contraseña, aparece en rojo.

**Controles (abajo a la izquierda):**

- **Seguir la sonda:** cuando llega un punto nuevo, el mapa se mueve hacia él. Si se desmarca, se puede mover el mapa libremente.
- **Ver trayectoria completa:** ajusta el zoom para ver toda la ruta.

### Cada cuánto se actualiza

- El script revisa el correo **cada 30 segundos** (se cambia con `--intervalo`).
- La página pide los datos al script cada 15 segundos.
- A eso se suma lo que tarda Rock7 en mandar el correo.

En total, un punto nuevo aparece en el mapa hasta unos 45 segundos después de que el correo llega a Gmail.

---

## 4. Mensajes que entiende

El script busca la posición en el texto del correo, en el campo `Data` (hexadecimal) y en el adjunto `.bin`. Acepta tres formatos:

| Formato | Ejemplo | Notas |
|---|---|---|
| **Sensores + GPS** (el actual) | `22.7 949.0 49.2 -33.460359 -70.660723` | temperatura °C, presión hPa, humedad %, latitud, longitud, separados por espacios. No trae hora: se usa la hora de transmisión de Iridium. La altitud se calcula a partir de la presión (altitud barométrica). |
| **Corto** (`envia_ubicacion.py`) | `151339,-33.45712,-70.66321,520,12` | HHMMSS (hora de la RPi), lat, lon, altitud m, velocidad km/h |
| **NMEA resumido** | `RMC,-33.458126,-70.661880,...,GGA,...` | hora UTC del GPS, velocidad en nudos (se convierte a km/h) |

Los mensajes con posición `0 0` (GPS sin señal) se descartan.

> **Ojo:** el orden de los campos del formato con sensores (temperatura, presión, humedad) es una suposición a partir del mensaje MOMSN 268. Si el script de la sonda los manda en otro orden, hay que cambiar la línea `temp, pres, hum, lat, lon = ...` en la función `posicion_sensores()`.

Correos aceptados: los que vienen de un remitente de **rock7**, o los que tienen **"RockBLOCK"** en el asunto (así también sirven los reenvíos).

---

## 5. El CSV

Una fila por punto, con estas columnas:

| Columna | Contenido |
|---|---|
| `_id` | IMEI#MOMSN, identificador único del mensaje |
| `recibido` | fecha y hora de transmisión (hora local) |
| `hora_gps` | hora del mensaje (o de transmisión si el formato no la trae) |
| `lat`, `lon` | posición GPS |
| `alt` | altitud en m (GPS o barométrica, según el formato) |
| `vel` | velocidad en km/h (0 si el formato no la trae) |
| `temp`, `pres`, `hum` | sensores (vacío en los otros formatos) |
| `sats` | satélites GPS (solo formato NMEA) |
| `momsn` | número correlativo del mensaje |
| `iri_lat`, `iri_lon`, `iri_cep_km` | estimación de Iridium y su margen en km |
| `formato`, `asunto` | formato detectado y asunto del correo |
| `orden` | hora de transmisión en segundos (timestamp Unix) |

Se abre directo con Excel, LibreOffice o pandas (`pd.read_csv(...)`).

---

## 6. Todas las opciones

| Opción | Por defecto | Para qué |
|---|---|---|
| `--intervalo S` | `30` | segundos entre revisiones del correo |
| `--continuar CSV` | — | retomar una trayectoria guardada |
| `--incluir-anteriores` | no | dibujar también los mensajes transmitidos antes de iniciar (desde `--desde`) |
| `--desde AAAA-MM-DD` | hoy | desde qué fecha buscar correos |
| `--csv ARCHIVO` | uno nuevo en `trayectorias/` | guardar en otro archivo; `--csv ""` no guarda nada |
| `--eml CARPETA` | — | leer archivos `.eml` de una carpeta en vez de Gmail (pruebas sin internet). Dibuja todos los correos de la carpeta. |
| `--remitente TEXTO` | `rock7` | filtro de remitente; `--remitente ""` lee todos los correos |
| `--asunto TEXTO` | `RockBLOCK` | también acepta correos con este texto en el asunto |
| `--usuario CORREO` | `IMAP_USUARIO` | cuenta de correo |
| `--servidor` / `--carpeta` | `imap.gmail.com` / `INBOX` | servidor y carpeta IMAP |
| `--puerto N` | `8000` | puerto del mapa en localhost |
| `--no-abrir` | no | no abrir el navegador automáticamente |

Ejemplos:

```bash
# Ver en el mapa todo lo que llegó hoy, no solo desde ahora
python3 mapa_tiempo_real.py --incluir-anteriores

# Ver los mensajes de otro día
python3 mapa_tiempo_real.py --incluir-anteriores --desde 2026-11-12

# Probar sin internet con correos descargados (.eml)
python3 mapa_tiempo_real.py --eml correos_prueba
```

El script **solo lee** el correo: no borra mensajes ni los marca como leídos.

---

## 7. Si algo falla

| Lo que aparece | Causa probable | Qué hacer |
|---|---|---|
| "Esperando el primer mensaje…" | Todavía no llega un mensaje transmitido después de iniciar el script | Esperar. Si ya debería haber llegado, revisar la bandeja de Gmail y la entrega en el panel de Rock7. Para ver mensajes anteriores: `--incluir-anteriores`. |
| "N correos anteriores al inicio, no dibujados" | Son correos de antes de iniciar el script | Es normal. Usar `--incluir-anteriores` o `--continuar` si se necesitan. |
| Error de login (en rojo en el panel) | Contraseña incorrecta | Usar la contraseña de aplicación, sin espacios. |
| "Sin conexion con mapa_tiempo_real.py" en la página | El script se cerró | Volver a iniciarlo, con `--continuar` si era un vuelo en curso. |
| Llegó el correo pero no aparece el punto | El mensaje no tiene uno de los formatos de la sección 4, o la posición es `0 0` | Revisar el campo `Data` del correo. |
| Un correo de prueba escrito a mano no aparece | No viene de rock7 ni dice "RockBLOCK" en el asunto | Usar `--remitente ""`. |
| "Address already in use" | Ya hay otro mapa corriendo en el puerto 8000 | Cerrar el otro o usar `--puerto 8001`. |
| Fondo del mapa gris | Sin internet en el PC | Los puntos se siguen guardando en el CSV; el fondo vuelve al recuperar la conexión. |
