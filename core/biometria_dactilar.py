"""
core/biometria_dactilar.py
----------------------------
Comunicación por serie con el sensor Suprema (protocolo propio
UniFinger), implementada directamente sobre pyserial siguiendo la
especificación de UF_Protocol_Manual.md. No usa `pysfm` (el SDK
oficial de Python de Suprema): su último release en PyPI fue en 2018
y ya no está disponible para instalar — no es una base confiable para
construir sobre ella.

Estructura del paquete (13 bytes fijos), confirmada con el ejemplo
trabajado del manual (comando ES enrolando ID 0x9929 → checksum 0x07):

    Start(1) | Command(1) | Param(4, little-endian) | Size(4, little-endian) | Flag/Error(1) | Checksum(1) | End(1)

Checksum = suma de los primeros 11 bytes (Start..Flag/Error) mod 256.
Start code = 0x40 siempre. End code = 0x0A siempre.

IMPORTANTE - supuestos pendientes de confirmar con hardware real:
La documentación disponible no detalla el significado exacto del campo
`Param` en las RESPUESTAS de cada comando. Este módulo asume la
convención típica de este protocolo:
  - flag_error == 0x00  →  éxito
  - flag_error != 0x00  →  código de error
  - En la respuesta de IS (identificar), Param trae el ID de la huella
    encontrada.
El logging de paquetes crudos [SEND]/[RECV] queda activo a propósito
(a nivel DEBUG) para poder verificar o corregir estos supuestos mirando
los bytes reales la primera vez que se pruebe con el sensor conectado.

Diferencia importante respecto al AS608 que usábamos antes: acá el ID
de la huella lo elige quien llama a enrolar() (se lo pasamos nosotros
como parámetro), no lo devuelve el sensor. Esto significa que podemos
usar directamente el id del alumno (de la futura tabla ALUMNOS) como
id_huella, sin necesitar un mapeo externo aparte.
"""

import logging
import struct
import threading
import time

import serial

logger = logging.getLogger(__name__)

START_CODE = 0x40
END_CODE = 0x0A
LARGO_PAQUETE = 13

# Comandos usados (ver "Command Summary" en UF_Protocol_Manual.md)
CMD_SS = 0x04  # Check system status — usado solo para probar la conexión
CMD_ES = 0x05  # Enroll by scan
CMD_IS = 0x11  # Identify by scan
CMD_DT = 0x16  # Delete template
CMD_DA = 0x17  # Delete all templates
CMD_LT = 0x18  # List user ID


class PaqueteUF:
    """Arma y valida paquetes de 13 bytes del protocolo UniFinger."""

    @staticmethod
    def construir(command: int, param: int = 0, size: int = 0, flag: int = 0) -> bytes:
        cuerpo = (
            bytes([START_CODE, command])
            + struct.pack("<I", param)
            + struct.pack("<I", size)
            + bytes([flag])
        )  # 11 bytes: Start(1) + Command(1) + Param(4) + Size(4) + Flag(1)
        checksum = sum(cuerpo) % 256
        return cuerpo + bytes([checksum, END_CODE])

    @staticmethod
    def parsear(datos: bytes) -> dict:
        if len(datos) != LARGO_PAQUETE:
            raise ValueError(f"Paquete de tamaño inesperado: {len(datos)} bytes (se esperaban {LARGO_PAQUETE})")
        if datos[0] != START_CODE or datos[12] != END_CODE:
            raise ValueError("Start/End code inválidos en el paquete recibido")

        cuerpo = datos[0:11]
        checksum_calculado = sum(cuerpo) % 256
        if datos[11] != checksum_calculado:
            raise ValueError(f"Checksum inválido: recibido 0x{datos[11]:02X}, esperado 0x{checksum_calculado:02X}")

        return {
            "command": datos[1],
            "param": struct.unpack("<I", datos[2:6])[0],
            "size": struct.unpack("<I", datos[6:10])[0],
            "flag_error": datos[10],
        }


class GestorHuellas:
    def __init__(self, puerto: str, baudrate: int = 115200, timeout_seg: float = 3.0):
        self.puerto = puerto
        self.baudrate = baudrate
        self.timeout_seg = timeout_seg
        self._serial = None
        self.disponible = False
        # Un solo lock: el sensor solo aguanta una transacción por vez.
        self._lock = threading.Lock()
        self._conectar()

    def _conectar(self) -> None:
        try:
            self._serial = serial.Serial(self.puerto, self.baudrate, timeout=self.timeout_seg)
            time.sleep(0.3)  # margen para que el módulo termine de inicializar tras abrir el puerto
            respuesta = self._transaccion(PaqueteUF.construir(CMD_SS))
            self.disponible = respuesta is not None
            if self.disponible:
                logger.info("Sensor Suprema conectado en %s (flag/error=0x%02X)", self.puerto, respuesta["flag_error"])
            else:
                logger.warning("Sensor Suprema en %s no respondió al chequeo de estado (SS).", self.puerto)
        except Exception as e:
            self.disponible = False
            logger.warning(
                "Sensor Suprema no disponible en %s (%s). El sistema sigue funcionando solo con reconocimiento facial.",
                self.puerto, e,
            )

    def reintentar_conexion(self) -> bool:
        with self._lock:
            self._conectar()
        return self.disponible

    # ------------------------------------------------------------------
    # Envío/recepción de paquetes crudos
    # ------------------------------------------------------------------
    def _enviar(self, paquete: bytes) -> None:
        logger.debug("[SEND] %s", paquete.hex(" "))
        self._serial.reset_input_buffer()
        self._serial.write(paquete)

    def _recibir(self):
        datos = self._serial.read(LARGO_PAQUETE)
        if len(datos) < LARGO_PAQUETE:
            logger.warning("Respuesta incompleta del sensor: %d/%d bytes", len(datos), LARGO_PAQUETE)
            return None
        logger.debug("[RECV] %s", datos.hex(" "))
        try:
            return PaqueteUF.parsear(datos)
        except ValueError as e:
            logger.warning("Paquete de respuesta inválido: %s", e)
            return None

    def _transaccion(self, paquete: bytes):
        """Envía un paquete y espera UNA respuesta de 13 bytes."""
        self._enviar(paquete)
        return self._recibir()

    # ------------------------------------------------------------------
    # Identificación (1:N) — la usa el loop de asistencia
    # ------------------------------------------------------------------
    def identificar(self, timeout_seg: float = 3.0) -> dict:
        if not self.disponible:
            return {"detectado": False, "motivo": "sensor_no_disponible"}

        with self._lock:
            timeout_previo = self._serial.timeout
            try:
                self._serial.timeout = timeout_seg
                respuesta = self._transaccion(PaqueteUF.construir(CMD_IS))

                if respuesta is None:
                    return {"detectado": False, "motivo": "sin_respuesta"}
                if respuesta["flag_error"] != 0x00:
                    return {"detectado": False, "motivo": f"error_0x{respuesta['flag_error']:02X}"}

                return {"detectado": True, "id_huella": respuesta["param"]}
            except Exception:
                logger.exception("Error identificando por huella")
                return {"detectado": False, "motivo": "error_hardware"}
            finally:
                self._serial.timeout = timeout_previo

    # ------------------------------------------------------------------
    # Enrolamiento
    # ------------------------------------------------------------------
    def enrolar(self, id_huella: int, timeout_seg: float = 15.0) -> dict:
        """
        El módulo, con la configuración de fábrica (Enroll Mode = 2
        templates), pide escanear el dedo y responde con DOS paquetes:
        uno intermedio (aviso de escaneo completado) y uno final
        (resultado real). Leemos ambos y nos quedamos con el resultado.
        """
        if not self.disponible:
            return {"ok": False, "mensaje": "Sensor no conectado"}

        with self._lock:
            timeout_previo = self._serial.timeout
            try:
                self._serial.timeout = timeout_seg
                self._enviar(PaqueteUF.construir(CMD_ES, param=id_huella))

                intermedia = self._recibir()
                final = self._recibir()
                respuesta = final or intermedia

                if respuesta is None:
                    return {"ok": False, "mensaje": "El sensor no respondió al enrolamiento"}
                if respuesta["flag_error"] != 0x00:
                    return {"ok": False, "mensaje": f"El sensor devolvió un error (0x{respuesta['flag_error']:02X})"}

                return {"ok": True, "mensaje": "Huella registrada con éxito", "id_huella": id_huella}
            except Exception as e:
                logger.exception("Error de hardware durante el enrolamiento")
                return {"ok": False, "mensaje": f"Error de hardware: {e}"}
            finally:
                self._serial.timeout = timeout_previo

    def borrar(self, id_huella: int) -> dict:
        if not self.disponible:
            return {"ok": False, "mensaje": "Sensor no conectado"}
        with self._lock:
            respuesta = self._transaccion(PaqueteUF.construir(CMD_DT, param=id_huella))
            if respuesta is None:
                return {"ok": False, "mensaje": "El sensor no respondió"}
            ok = respuesta["flag_error"] == 0x00
            return {"ok": ok, "mensaje": "Huella borrada" if ok else f"Error 0x{respuesta['flag_error']:02X}"}