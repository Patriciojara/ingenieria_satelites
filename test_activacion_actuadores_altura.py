# Patricio Jara Q
# 09-11-2026
# Test Pueba de activacion de actuadores segun altura se activa si es menor a 505 metros sobre el nivel del mar.
# Parte apagado y cerrado, si es mayot los actuadores de cerran y apagan.

import time
import board
from gpiozero import OutputDevice
from gpiozero.pins.lgpio import LGPIOFactory
from adafruit_bme280 import basic as adafruit_bme280

# =====================================
# CONFIGURACION
# =====================================

ALTURA_UMBRAL = 505.0
PRESION_REFERENCIA = 1013.25  # hPa
INTERVALO = 0.5                # segundos
PAUSA_CAMBIO = 0.1             # segundos

PIN_CERRAR = 16
PIN_ABRIR = 20
PIN_EXTRACTOR = 21

# =====================================
# INICIALIZACION GPIO
# =====================================

factory = LGPIOFactory()

cerrar = None
abrir = None
extractor = None

try:
    cerrar = OutputDevice(
        PIN_CERRAR,
        active_high=True,
        initial_value=False,
        pin_factory=factory
    )

    abrir = OutputDevice(
        PIN_ABRIR,
        active_high=True,
        initial_value=False,
        pin_factory=factory
    )

    extractor = OutputDevice(
        PIN_EXTRACTOR,
        active_high=True,
        initial_value=False,
        pin_factory=factory
    )

    # Estado inicial: valvula cerrada
    cerrar.on()
    estado = "CERRADA"

    print("Sistema iniciado: cerrando valvula.")

    # =====================================
    # INICIALIZACION BME280
    # =====================================

    i2c = board.I2C()

    sensor = adafruit_bme280.Adafruit_BME280_I2C(
        i2c, address=0x76
    )

    sensor.sea_level_pressure = PRESION_REFERENCIA

    print("BME280 conectado correctamente.")
    print(f"Umbral de altura: {ALTURA_UMBRAL} m")
    print("Presiona Ctrl+C para detener.\n")

    # Encabezados
    print(
        f"{'Tiempo':<12}"
        f"{'Temp (C)':<12}"
        f"{'Presion (hPa)':<16}"
        f"{'Humedad (%)':<14}"
        f"{'Altura (m)':<14}"
        f"{'Cerrar':<10}"
        f"{'Abrir':<10}"
        f"{'Extractor':<12}"
    )

    print("-" * 100)

    # =====================================
    # BUCLE PRINCIPAL
    # =====================================

    while True:

        temperatura = sensor.temperature
        presion = sensor.pressure
        humedad = sensor.relative_humidity
        altura = sensor.altitude

        # Si altura menor a 505 m:
        # Abrir valvula y activar extractor
        if altura < ALTURA_UMBRAL and estado != "ABIERTA":

            cerrar.off()
            time.sleep(PAUSA_CAMBIO)

            abrir.on()
            extractor.on()

            estado = "ABIERTA"

        # Si altura mayor o igual a 505 m:
        # Apagar extractor y cerrar valvula
        elif altura >= ALTURA_UMBRAL and estado != "CERRADA":

            extractor.off()
            abrir.off()
            time.sleep(PAUSA_CAMBIO)

            cerrar.on()

            estado = "CERRADA"

        # Estados de las salidas
        estado_cerrar = "ON" if cerrar.is_active else "OFF"
        estado_abrir = "ON" if abrir.is_active else "OFF"
        estado_extractor = "ON" if extractor.is_active else "OFF"

        tiempo = time.strftime("%H:%M:%S")

        # Mensaje completo
        mensaje = (
            f"{tiempo:<12}"
            f"{temperatura:<12.2f}"
            f"{presion:<16.2f}"
            f"{humedad:<14.2f}"
            f"{altura:<14.2f}"
            f"{estado_cerrar:<10}"
            f"{estado_abrir:<10}"
            f"{estado_extractor:<12}"
        )

        print(mensaje, flush=True)

        time.sleep(INTERVALO)

except KeyboardInterrupt:
    print("\nPrograma detenido por el usuario.")

except Exception as e:
    print(f"\nError: {e}")

finally:
    # Apagar todas las salidas
    for salida in [extractor, abrir, cerrar]:
        if salida is not None:
            salida.off()
            salida.close()

    factory.close()

    print("Todos los GPIO desactivados.")
