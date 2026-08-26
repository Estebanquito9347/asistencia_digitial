"""
config.py
---------
Configuración vía variables de entorno.
"""

import os
import secrets


class Config:
    # --- Rutas de datos ---
    CARPETA_ROSTROS = os.environ.get("CARPETA_ROSTROS", "rostros")
    ARCHIVO_CACHE_ROSTROS = os.environ.get("ARCHIVO_CACHE_ROSTROS", "rostros_cache.pkl")
    ARCHIVO_ASISTENCIA = os.environ.get("ARCHIVO_ASISTENCIA", "asistencia.csv")
    ARCHIVO_HORARIOS = os.environ.get("ARCHIVO_HORARIOS", "horarios.json")

    # --- Reconocimiento facial (dlib/face_recognition) ---
    FACE_TOLERANCIA = float(os.environ.get("FACE_TOLERANCIA", "0.5"))
    FACE_MARGEN_MINIMO = float(os.environ.get("FACE_MARGEN_MINIMO", "0.04"))
    FACE_ESCALA_DETECCION = float(os.environ.get("FACE_ESCALA_DETECCION", "0.5"))

    # --- Panel de la preceptora ---
    # Cambiar el PIN por defecto antes de usar esto con alumnos reales.
    ADMIN_PIN = os.environ.get("ADMIN_PIN", "1234")
    # Sin esto Flask no puede firmar las cookies de sesión (login). Si no
    # se define por variable de entorno, se genera una al azar en cada
    # arranque — suficiente para un solo proceso local, pero significa
    # que reiniciar el server cierra la sesión de la preceptora.
    SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))

    # --- Servidor ---
    HOST = os.environ.get("HOST", "0.0.0.0")
    PORT = int(os.environ.get("PORT", "8000"))
    DEBUG = os.environ.get("FLASK_DEBUG", "1") == "1"

    # --- Logging ---
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")