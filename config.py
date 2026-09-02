"""
config.py
---------
Configuración vía variables de entorno.
"""

import os
import secrets


def _obtener_secret_key() -> str:
    """
    Carga o genera una SECRET_KEY persistente.
    Se guarda en .secret_key para que no se pierda entre reinicios.
    Esto es crítico para que las cookies de sesión sigan siendo válidas
    después de reiniciar el servidor.
    """
    archivo_secret = ".secret_key"
    if os.path.exists(archivo_secret):
        try:
            with open(archivo_secret, "r") as f:
                return f.read().strip()
        except Exception:
            pass
    
    # Si no existe o hay error, generar uno nuevo y guardarlo
    secret = secrets.token_hex(32)
    try:
        with open(archivo_secret, "w") as f:
            f.write(secret)
    except Exception:
        # Si no se puede guardar (permisos), al menos funciona esta sesión
        pass
    return secret


class Config:
    # --- Rutas de datos ---
    CARPETA_ROSTROS = os.environ.get("CARPETA_ROSTROS", "rostros")
    ARCHIVO_CACHE_ROSTROS = os.environ.get("ARCHIVO_CACHE_ROSTROS", "rostros_cache.pkl")
    CARPETA_ASISTENCIA = os.environ.get("CARPETA_ASISTENCIA", "asistencia")
    ARCHIVO_HORARIOS = os.environ.get("ARCHIVO_HORARIOS", "horarios.json")

    # --- Reconocimiento facial (dlib/face_recognition) ---
    FACE_TOLERANCIA = float(os.environ.get("FACE_TOLERANCIA", "0.5"))
    FACE_MARGEN_MINIMO = float(os.environ.get("FACE_MARGEN_MINIMO", "0.04"))
    FACE_ESCALA_DETECCION = float(os.environ.get("FACE_ESCALA_DETECCION", "0.5"))

    # --- Panel de la preceptora ---
    # Cambiar el PIN por defecto antes de usar esto con alumnos reales.
    ADMIN_PIN = os.environ.get("ADMIN_PIN", "1234")
    # SECRET_KEY persistente: se guarda en disco para que las cookies
    # sigan siendo válidas después de reiniciar el servidor.
    # Esto es especialmente importante en Linux donde se ejecuta la web.
    SECRET_KEY = os.environ.get("SECRET_KEY", _obtener_secret_key())

    # --- Servidor ---
    HOST = os.environ.get("HOST", "0.0.0.0")
    PORT = int(os.environ.get("PORT", "8000"))
    DEBUG = os.environ.get("FLASK_DEBUG", "1") == "1"

    # --- Logging ---
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
