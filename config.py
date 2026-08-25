import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _resolver_ruta_proyecto(ruta: str) -> str:
    if not ruta:
        return str(BASE_DIR)
    ruta_path = Path(ruta)
    if ruta_path.is_absolute():
        return str(ruta_path)
    return str((BASE_DIR / ruta_path).resolve())


class Config:
    # --- Rutas de datos ---
    CARPETA_ROSTROS = _resolver_ruta_proyecto(os.environ.get("CARPETA_ROSTROS", "rostros"))
    ARCHIVO_MODELO_ROSTROS = _resolver_ruta_proyecto(os.environ.get("ARCHIVO_MODELO_ROSTROS", "rostros_lbp.pkl"))
    ARCHIVO_CASCADA_ROSTROS = _resolver_ruta_proyecto(os.environ.get("ARCHIVO_CASCADA_ROSTROS", "haarcascade_frontalface_default.xml"))

    # --- Reconocimiento facial (embeddings face_recognition; distancia menor = mejor match) ---
    FACE_UMBRAL_DISTANCIA = float(os.environ.get("FACE_UMBRAL_DISTANCIA", "0.45"))
    FACE_MARGEN_MINIMO = float(os.environ.get("FACE_MARGEN_MINIMO", "0.08"))

    # --- Servidor ---
    HOST = os.environ.get("HOST", "0.0.0.0")
    PORT = int(os.environ.get("PORT", "8000"))
    DEBUG = os.environ.get("FLASK_DEBUG", "1") == "1"

    # --- Logging ---
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
