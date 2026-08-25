"""
config.py
---------
Configuración vía variables de entorno.
"""

import os


class Config:
    # --- Rutas de datos ---
    CARPETA_ROSTROS = os.environ.get("CARPETA_ROSTROS", "rostros")
    ARCHIVO_CACHE_ROSTROS = os.environ.get("ARCHIVO_CACHE_ROSTROS", "rostros_cache.pkl")

    # --- Reconocimiento facial (dlib/face_recognition) ---
    FACE_TOLERANCIA = float(os.environ.get("FACE_TOLERANCIA", "0.5"))
    FACE_MARGEN_MINIMO = float(os.environ.get("FACE_MARGEN_MINIMO", "0.04"))
    FACE_ESCALA_DETECCION = float(os.environ.get("FACE_ESCALA_DETECCION", "0.5"))

    # --- Servidor ---
    HOST = os.environ.get("HOST", "0.0.0.0")
    PORT = int(os.environ.get("PORT", "8000"))
    DEBUG = os.environ.get("FLASK_DEBUG", "1") == "1"

    # --- Logging ---
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")