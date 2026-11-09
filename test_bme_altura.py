# Patricio Jara Q
# 09-11-2026
# Test sensor altura en metros 

import time
import board
from adafruit_bme280 import basic as adafruit_bme280

# Inicializar I2C
i2c = board.I2C()

# Inicializar BME280
sensor = adafruit_bme280.Adafruit_BME280_I2C(
    i2c, address=0x76
)

# Presión de referencia a nivel del mar (hPa)
sensor.sea_level_pressure = 1013.25

print("BME280 conectado correctamente")
print("Presiona Ctrl+C para detener.\n")

try:
    while True:
        temperatura = sensor.temperature
        presion_hpa = sensor.pressure
        humedad = sensor.relative_humidity
        altura = sensor.altitude

        print(
            f"Temperatura: {temperatura:.2f} °C | "
            f"Presión: {presion_hpa:.2f} hPa | "
            f"Humedad: {humedad:.2f} % | "
            f"Altura: {altura:.2f} m"
        )

        time.sleep(1)

except KeyboardInterrupt:
    print("\nLectura finalizada.")
