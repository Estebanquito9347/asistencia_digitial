"""
app.py
------
Punto de entrada. Versión mínima: solo cámara + reconocimiento facial
+ confirmación manual. Asistencia (CSV) y huella quedan aparte, para
retomar más adelante.
"""

import logging

from flask import Flask

from config import Config
from core.reconocimiento_facial import GestorRostros
from routes.api import create_blueprint


def configurar_logging():
    logging.basicConfig(
        level=getattr(logging, Config.LOG_LEVEL, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def create_app() -> Flask:
    configurar_logging()
    app = Flask(__name__)

    gestor_rostros = GestorRostros(
        carpeta_rostros=Config.CARPETA_ROSTROS,
        archivo_modelo=Config.ARCHIVO_MODELO_ROSTROS,
        umbral_distancia=Config.FACE_UMBRAL_DISTANCIA,
        margen_minimo=Config.FACE_MARGEN_MINIMO,
        archivo_cascada=Config.ARCHIVO_CASCADA_ROSTROS,
    )
    gestor_rostros.entrenar()

    bp = create_blueprint(
        gestor_rostros=gestor_rostros,
        carpeta_rostros=Config.CARPETA_ROSTROS,
    )
    app.register_blueprint(bp)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
