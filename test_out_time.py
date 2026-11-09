# Patricio Jara Q
# 09-11-2026
# Test actuadores Radiosonda

from gpiozero import OutputDevice
from gpiozero.pins.lgpio import LGPIOFactory
from time import sleep

# Asignación de nombres a GPIO (numeración BCM)
PINES = {
    "abrir": 21,
    "cerrar": 23,
    "extractor": 18,
    "up": 20
}

factory = LGPIOFactory()
gpio = None

try:
    print("Acciones disponibles:")
    for nombre in PINES:
        print(f" - {nombre}")

    accion = input("\nIngrese la acción: ").strip().lower()

    if accion not in PINES:
        raise ValueError("Acción no válida.")

    tiempo = float(input("Ingrese el tiempo en segundos: "))

    if tiempo <= 0:
        raise ValueError("El tiempo debe ser mayor que cero.")

    pin = PINES[accion]

    gpio = OutputDevice(
        pin,
        active_high=True,
        initial_value=False,
        pin_factory=factory
    )

    print(f"\nActivando '{accion}' durante {tiempo} segundos...")

    gpio.on()
    sleep(tiempo)
    gpio.off()

    print(f"Acción '{accion}' finalizada.")

except KeyboardInterrupt:
    print("\nPrograma interrumpido.")

except ValueError as e:
    print(f"Error: {e}")

finally:
    if gpio is not None:
        gpio.off()
        gpio.close()

    factory.close()
    print("GPIO apagado y liberado.")