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
    CARPETA_ASISTENCIA = os.environ.get("CARPETA_ASISTENCIA", "asistencia")
    ARCHIVO_HORARIOS = os.environ.get("ARCHIVO_HORARIOS", "horarios.json")

    # --- Reconocimiento facial (dlib/face_recognition) ---
    FACE_TOLERANCIA = float(os.environ.get("FACE_TOLERANCIA", "0.5"))
    FACE_MARGEN_MINIMO = float(os.environ.get("FACE_MARGEN_MINIMO", "0.04"))
    FACE_ESCALA_DETECCION = float(os.environ.get("FACE_ESCALA_DETECCION", "0.5"))

    # --- Lector de huella en red (ZKTeco / pyzk) ---
    HUELLA_RED_IP = os.environ.get("HUELLA_RED_IP", "192.168.120.37")
    HUELLA_RED_PUERTO = int(os.environ.get("HUELLA_RED_PUERTO", "4370"))
    HUELLA_RED_PASSWORD = int(os.environ.get("HUELLA_RED_PASSWORD", "0"))
    HUELLA_RED_TIMEOUT = int(os.environ.get("HUELLA_RED_TIMEOUT", "5"))
    ARCHIVO_MAPEO_HUELLA_RED = os.environ.get("ARCHIVO_MAPEO_HUELLA_RED", "huella_red_mapeo.json")

    # --- Panel de la preceptora ---
    ADMIN_PIN = os.environ.get("ADMIN_PIN", "1234")
    SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))

    # --- Servidor ---
    HOST = os.environ.get("HOST", "0.0.0.0")
    PORT = int(os.environ.get("PORT", "8000"))
    DEBUG = os.environ.get("FLASK_DEBUG", "1") == "1"

    # --- Logging ---
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")