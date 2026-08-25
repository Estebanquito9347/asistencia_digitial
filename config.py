import os


class Config:
    # --- Rutas de datos ---
    CARPETA_ROSTROS = os.environ.get("CARPETA_ROSTROS", "rostros")
    ARCHIVO_MODELO_ROSTROS = os.environ.get("ARCHIVO_MODELO_ROSTROS", "rostros_lbp.pkl")
    ARCHIVO_CASCADA_ROSTROS = os.environ.get("ARCHIVO_CASCADA_ROSTROS", "haarcascade_frontalface_default.xml")

    # --- Reconocimiento facial (LBP propio: menor distancia = mejor match) ---
    FACE_UMBRAL_DISTANCIA = float(os.environ.get("FACE_UMBRAL_DISTANCIA", "12.0"))
    FACE_MARGEN_MINIMO = float(os.environ.get("FACE_MARGEN_MINIMO", "1.5"))

    # --- Servidor ---
    HOST = os.environ.get("HOST", "0.0.0.0")
    PORT = int(os.environ.get("PORT", "8000"))
    DEBUG = os.environ.get("FLASK_DEBUG", "1") == "1"

    # --- Logging ---
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
