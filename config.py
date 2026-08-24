"""
config.py
---------
Toda constante configurable del sistema vive acá, tomada de variables
de entorno con un default razonable.

Ejemplo:
    set FACE_UMBRAL_CONFIANZA=60
    python app.py
"""

import os


class Config:
    # --- Rutas de datos ---
    CARPETA_ROSTROS = os.environ.get("CARPETA_ROSTROS", "rostros")
    ARCHIVO_ASISTENCIA = os.environ.get("ARCHIVO_ASISTENCIA", "asistencia.csv")
    ARCHIVO_MODELO_ROSTROS = os.environ.get("ARCHIVO_MODELO_ROSTROS", "rostros_lbph.yml")
    ARCHIVO_ETIQUETAS_ROSTROS = os.environ.get("ARCHIVO_ETIQUETAS_ROSTROS", "rostros_etiquetas.pkl")

    # --- Reconocimiento facial (OpenCV LBPH: menor confianza = mejor match) ---
    FACE_UMBRAL_CONFIANZA = float(os.environ.get("FACE_UMBRAL_CONFIANZA", "70.0"))

    # --- Sensor de huellas Suprema (UniFinger SFM3520-OP) ---
    # En Windows el puerto es tipo "COM3", no "/dev/ttyUSB0" como en Linux.
    FP_PUERTO = os.environ.get("FP_PORT", "COM3")
    FP_BAUDRATE = int(os.environ.get("FP_BAUDRATE", "115200"))  # default de fábrica del módulo

    # --- Servidor ---
    HOST = os.environ.get("HOST", "0.0.0.0")
    PORT = int(os.environ.get("PORT", "8000"))
    DEBUG = os.environ.get("FLASK_DEBUG", "1") == "1"

    # --- Logging ---
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")