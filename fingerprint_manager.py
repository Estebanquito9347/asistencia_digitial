"""
fingerprint_manager.py
-----------------------
Encapsula toda la lógica de bajo nivel del sensor óptico AS608 (u otros
sensores compatibles con el protocolo Adafruit/ZFM) conectado por
USB-UART en Linux (típicamente /dev/ttyUSB0).

Se separa de app.py a propósito: si mañana cambian de sensor o el
puerto falla, esto se toca en un solo lugar y el resto del sistema
(Flask, CSV, frontend) no se entera.

Requiere:
    pip install pyfingerprint pyserial

Nota sobre permisos en Arch/Omarchy:
    El usuario que corre el server necesita pertenecer al grupo
    'uucp' o 'dialout' (según distro) para poder abrir /dev/ttyUSB0
    sin sudo:
        sudo usermod -aG uucp $USER   # Arch / Omarchy
    Después hay que cerrar sesión y volver a entrar.
"""

import json
import os
import threading
from datetime import datetime

from pyfingerprint.pyfingerprint import PyFingerprint

MAPEO_HUELLAS = "huellas_mapping.json"
PUERTO_SENSOR = os.environ.get("FP_PORT", "/dev/ttyUSB0")
BAUDRATE = 57600  # valor de fábrica del AS608, no tocar salvo que lo hayan reconfigurado


class FingerprintManager:
    """
    Wrapper de alto nivel. Una sola instancia global (ver app.py) porque
    el sensor solo admite una conexión serie activa a la vez.
    """

    def __init__(self, puerto=PUERTO_SENSOR, baudrate=BAUDRATE):
        self.puerto = puerto
        self.baudrate = baudrate
        self.sensor = None
        self.disponible = False
        # El sensor físico es un recurso compartido: sin este lock,
        # dos requests HTTP simultáneas (enrolar + identificar) podrían
        # pisarse los comandos UART entre sí.
        self.lock = threading.Lock()
        self._mapeo = self._cargar_mapeo()
        self._conectar()

    # ------------------------------------------------------------------
    # Conexión / estado
    # ------------------------------------------------------------------
    def _conectar(self):
        try:
            self.sensor = PyFingerprint(self.puerto, self.baudrate, 0xFFFFFFFF, 0x00000000)
            if not self.sensor.verifyPassword():
                raise ValueError("Contraseña incorrecta del sensor de huellas")
            self.disponible = True
            print(f"🖐️  Sensor de huellas conectado en {self.puerto} "
                  f"({self.sensor.getTemplateCount()} huellas cargadas en el módulo)")
        except Exception as e:
            self.disponible = False
            print(f"⚠️  Sensor de huellas NO disponible ({self.puerto}): {e}")
            print("   El sistema seguirá funcionando solo con reconocimiento facial.")

    def reintentar_conexion(self):
        """Se puede llamar desde una ruta manual si conectan el sensor en caliente."""
        with self.lock:
            self._conectar()
        return self.disponible

    # ------------------------------------------------------------------
    # Mapeo id_huella (interno del sensor) -> alumno/curso
    # ------------------------------------------------------------------
    def _cargar_mapeo(self):
        if os.path.exists(MAPEO_HUELLAS):
            with open(MAPEO_HUELLAS, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _guardar_mapeo(self):
        with open(MAPEO_HUELLAS, "w", encoding="utf-8") as f:
            json.dump(self._mapeo, f, ensure_ascii=False, indent=2)

    def _siguiente_id_libre(self):
        """El AS608 direcciona plantillas por índice numérico (0..~299 según capacidad)."""
        ocupados = set(int(k) for k in self._mapeo.keys())
        i = 0
        while i in ocupados:
            i += 1
        return i

    # ------------------------------------------------------------------
    # Enrolamiento (alta de una huella nueva)
    # ------------------------------------------------------------------
    def enrolar(self, nombre, curso, timeout_seg=15):
        """
        Proceso BLOQUEANTE (por diseño: es un kiosco local, una preceptora
        a la vez frente al sensor). Pide apoyar el dedo dos veces, como
        exige el protocolo del AS608 para generar una plantilla confiable.

        Devuelve un dict {ok, mensaje, id_huella}.
        """
        if not self.disponible:
            return {"ok": False, "mensaje": "Sensor no conectado"}

        with self.lock:
            try:
                # --- Primera lectura ---
                if not self._esperar_dedo(timeout_seg):
                    return {"ok": False, "mensaje": "Tiempo de espera agotado (1er apoyo)"}
                self.sensor.convertImage(0x01)

                # Chequeo anti-duplicados: si ya existe, no la volvemos a dar de alta
                resultado_busqueda = self.sensor.searchTemplate()
                pos_encontrada, _puntaje = resultado_busqueda
                if pos_encontrada >= 0:
                    existente = self._mapeo.get(str(pos_encontrada))
                    nombre_existente = existente["nombre"] if existente else "desconocido"
                    return {"ok": False, "mensaje": f"Esta huella ya está registrada a nombre de {nombre_existente}"}

                self.sensor.createTemplate()  # guarda buffer 0x01 en el módulo, listo para comparar en el paso 2

                # --- Retirar el dedo ---
                self._esperar_retiro(timeout_seg)

                # --- Segunda lectura (confirmación) ---
                if not self._esperar_dedo(timeout_seg):
                    return {"ok": False, "mensaje": "Tiempo de espera agotado (2do apoyo)"}
                self.sensor.convertImage(0x02)

                self.sensor.createTemplate()
                id_libre = self._siguiente_id_libre()
                posicion_final = self.sensor.storeTemplate(id_libre)

                self._mapeo[str(posicion_final)] = {
                    "nombre": nombre,
                    "curso": curso,
                    "fecha_alta": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                self._guardar_mapeo()

                return {"ok": True, "mensaje": "Huella registrada con éxito", "id_huella": posicion_final}

            except Exception as e:
                return {"ok": False, "mensaje": f"Error de hardware durante el enrolamiento: {e}"}

    # ------------------------------------------------------------------
    # Identificación (para marcar presente)
    # ------------------------------------------------------------------
    def identificar(self, timeout_seg=5):
        """
        Lectura única, no bloqueante más allá del timeout: se usa en el loop
        de asistencia, así que si no hay dedo apoyado devuelve rápido
        {"detectado": False} en vez de colgar la request HTTP.
        """
        if not self.disponible:
            return {"detectado": False, "motivo": "sensor_no_disponible"}

        with self.lock:
            try:
                if not self._esperar_dedo(timeout_seg):
                    return {"detectado": False}

                self.sensor.convertImage(0x01)
                posicion, puntaje = self.sensor.searchTemplate()

                if posicion == -1:
                    return {"detectado": False, "motivo": "no_coincide"}

                datos = self._mapeo.get(str(posicion))
                if not datos:
                    # Plantilla existe en el sensor pero no tenemos mapeo (raro, pero posible
                    # si se cargó a mano). La tratamos como no reconocida por seguridad.
                    return {"detectado": False, "motivo": "sin_mapeo"}

                return {
                    "detectado": True,
                    "alumno": datos["nombre"],
                    "curso": datos["curso"],
                    "confianza": puntaje,
                }
            except Exception as e:
                print(f"❌ Error en identificación por huella: {e}")
                return {"detectado": False, "motivo": "error_hardware"}

    # ------------------------------------------------------------------
    # Helpers de polling físico
    # ------------------------------------------------------------------
    def _esperar_dedo(self, timeout_seg):
        import time
        limite = time.time() + timeout_seg
        while time.time() < limite:
            if self.sensor.readImage():
                return True
            time.sleep(0.15)
        return False

    def _esperar_retiro(self, timeout_seg):
        import time
        limite = time.time() + timeout_seg
        while time.time() < limite:
            if not self.sensor.readImage():
                return True
            time.sleep(0.15)
        return False