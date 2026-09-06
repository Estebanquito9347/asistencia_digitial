"""
core/huella_red.py
--------------------
Conexión al lector de huellas en red (terminal ZKTeco o compatible)
vía TCP/UDP, usando la librería pyzk.

Requiere: pip install pyzk

Cómo funciona el dispositivo (importante para entender el módulo):
  - Guarda TODO en su propia memoria interna: usuarios enrolados y el
    log de marcaciones (fichadas). No sabe nada de "cursos" — cada
    usuario tiene un `user_id` numérico (el que se le asigna al
    enrolar la huella en el dispositivo) y opcionalmente un nombre.
  - Solo admite UNA sesión de comunicación a la vez. Por eso cada
    operación acá abre su propia conexión y la cierra al terminar
    (ver _ConexionZK), en vez de mantener una conexión persistente
    que podría quedar colgada si el proceso Flask se reinicia a mitad
    de una operación.

El mapeo `user_id del dispositivo -> alumno (nombre + curso)` de
nuestra app se guarda en un JSON aparte (mismo patrón que
core/horarios.py) — el dispositivo no tiene ese contexto, hay que
armarlo del lado de la aplicación.

NOTA: `clear_attendance()` (borrar el log del dispositivo tras
sincronizar) existe en versiones recientes de pyzk, pero no lo vi
confirmado en la documentación pública que revisé — antes de usar
`limpiar_dispositivo=True` en producción, confirmá con
`dir(conn)` en tu entorno real que el método está disponible tal
cual, para no perder marcaciones por una llamada que no hace lo
esperado.
"""

import json
import logging
import os
import threading

from zk import ZK
from zk.exception import ZKErrorResponse, ZKNetworkError

logger = logging.getLogger(__name__)


class _ConexionZK:
    """Context manager: conecta, deshabilita el dispositivo durante la
    operación (evita que alguien fiche a mitad de una lectura), y
    garantiza desconectar al final aunque algo falle en el medio."""

    def __init__(self, zk):
        self._zk = zk
        self._conn = None

    def __enter__(self):
        self._conn = self._zk.connect()
        self._conn.disable_device()
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._conn:
            try:
                self._conn.enable_device()
            except Exception:
                logger.exception("No se pudo re-habilitar el dispositivo al cerrar la conexión")
            self._conn.disconnect()


class GestorHuellaRed:
    def __init__(self, ip: str, puerto: int = 4370, timeout_seg: int = 5,
                 password: int = 0, archivo_mapeo: str = "huella_red_mapeo.json"):
        self.ip = ip
        self.puerto = puerto
        self.timeout_seg = timeout_seg
        self.password = password
        self.archivo_mapeo = archivo_mapeo

        self._lock = threading.Lock()
        self.disponible = False
        self._mapeo = self._cargar_mapeo()  # {"<user_id>": {"nombre":.., "curso":..}}

    # ------------------------------------------------------------------
    def _nueva_conexion(self) -> _ConexionZK:
        zk = ZK(self.ip, port=self.puerto, timeout=self.timeout_seg,
                password=self.password, force_udp=False, ommit_ping=False)
        return _ConexionZK(zk)

    # ------------------------------------------------------------------
    # 1) Conexión
    # ------------------------------------------------------------------
    def conectar(self) -> dict:
        """Prueba la conexión y devuelve info básica del dispositivo.
        No hace falta llamarlo antes de cada operación — get_usuarios()
        y obtener_marcaciones() abren su propia conexión igual — pero
        sirve como chequeo rápido de estado desde el panel de la
        preceptora."""
        with self._lock:
            try:
                with self._nueva_conexion() as conn:
                    info = {
                        "conectado": True,
                        "ip": self.ip,
                        "firmware": conn.get_firmware_version(),
                        "serial": conn.get_serialnumber(),
                        "hora_dispositivo": str(conn.get_time()),
                    }
                self.disponible = True
                logger.info("Lector de huellas en red conectado: %s", info)
                return info
            except (ZKNetworkError, ZKErrorResponse) as e:
                self.disponible = False
                logger.warning("No se pudo conectar al lector en %s:%d (%s)", self.ip, self.puerto, e)
                return {"conectado": False, "error": str(e)}
            except Exception:
                self.disponible = False
                logger.exception("Error inesperado conectando al lector en %s:%d", self.ip, self.puerto)
                return {"conectado": False, "error": "Error inesperado, ver logs del servidor"}

    # ------------------------------------------------------------------
    # Usuarios cargados en el dispositivo (para armar el mapeo)
    # ------------------------------------------------------------------
    def obtener_usuarios_dispositivo(self) -> list:
        """Lista cruda de usuarios enrolados en el lector, tal como
        están ahí (uid interno, user_id, nombre). Sirve para que la
        preceptora vea qué user_id corresponde a qué persona y arme
        el mapeo con registrar_mapeo()."""
        with self._lock:
            with self._nueva_conexion() as conn:
                usuarios = conn.get_users()
                return [
                    {
                        "uid": u.uid,
                        "user_id": u.user_id,
                        "nombre_dispositivo": u.name,
                        "mapeado": self.resolver_alumno(u.user_id) is not None,
                    }
                    for u in usuarios
                ]

    # ------------------------------------------------------------------
    # Mapeo user_id (del lector) -> alumno (nombre + curso) de la app
    # ------------------------------------------------------------------
    def _cargar_mapeo(self) -> dict:
        if os.path.exists(self.archivo_mapeo):
            try:
                with open(self.archivo_mapeo, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                logger.exception("No se pudo leer %s, se arranca vacío", self.archivo_mapeo)
        return {}

    def _guardar_mapeo(self) -> None:
        try:
            with open(self.archivo_mapeo, "w", encoding="utf-8") as f:
                json.dump(self._mapeo, f, ensure_ascii=False, indent=2)
        except Exception:
            logger.exception("No se pudo guardar %s", self.archivo_mapeo)

    def registrar_mapeo(self, user_id, nombre: str, curso: str) -> None:
        with self._lock:
            self._mapeo[str(user_id)] = {"nombre": nombre, "curso": curso}
            self._guardar_mapeo()
            logger.info("Mapeo actualizado: user_id %s -> %s (%s)", user_id, nombre, curso)

    def resolver_alumno(self, user_id):
        return self._mapeo.get(str(user_id))

    # ------------------------------------------------------------------
    # 2) Descarga de marcaciones (fichadas)
    # ------------------------------------------------------------------
    def obtener_marcaciones(self, limpiar_dispositivo: bool = False) -> list:
        """Baja las marcaciones acumuladas en el lector y las traduce
        usando el mapeo user_id -> alumno. Las marcaciones de un
        user_id sin mapear se devuelven igual (con alumno=None,
        curso=None) para que quien llame decida qué hacer — no se
        pierden en silencio."""
        with self._lock:
            with self._nueva_conexion() as conn:
                marcaciones_crudas = conn.get_attendance()

                resultado = []
                for m in marcaciones_crudas:
                    alumno = self.resolver_alumno(m.user_id)
                    resultado.append({
                        "user_id": m.user_id,
                        "timestamp": m.timestamp,
                        "alumno": alumno["nombre"] if alumno else None,
                        "curso": alumno["curso"] if alumno else None,
                    })

                if limpiar_dispositivo:
                    if hasattr(conn, "clear_attendance"):
                        conn.clear_attendance()
                        logger.info("Log de marcaciones borrado del dispositivo tras sincronizar")
                    else:
                        logger.warning(
                            "Se pidió limpiar el dispositivo pero esta versión de pyzk no tiene "
                            "clear_attendance(); el log NO se borró, la próxima sincronización "
                            "va a volver a traer estas mismas marcaciones."
                        )

                return resultado