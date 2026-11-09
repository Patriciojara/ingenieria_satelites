# Patricio Jara Q
# 09-11-2026
# Test sensor bme

import time
import board
import adafruit_bmp280

# Inicializar I2C
i2c = board.I2C()

# Detectar dirección del BMP280
bmp280 = None

for direccion in [0x76, 0x77]:
    try:
        bmp280 = adafruit_bmp280.Adafruit_BMP280_I2C(
            i2c, address=direccion
        )
        print(f"BMP280 detectado en {hex(direccion)}")
        break
    except (ValueError, OSError):
        continue

if bmp280 is None:
    raise RuntimeError("No se encontró el BMP280")

# Lectura continua
try:
    while True:
        temperatura = bmp280.temperature
        presion_hpa = bmp280.pressure
        presion_pa = presion_hpa * 100

        print(
            f"Temperatura: {temperatura:.2f} °C | "
            f"Presión: {presion_hpa:.2f} hPa | "
            f"{presion_pa:.2f} Pa"
        )

        time.sleep(1)

except KeyboardInterrupt:
    print("\nLectura detenida.")
