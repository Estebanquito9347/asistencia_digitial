"""
app.py
------
Punto de entrada. Arma la aplicación Flask a partir de las piezas de
core/ y registra el blueprint de rutas.
"""

import logging

from flask import Flask

from config import Config
from core.asistencia import RegistroAsistencia
from core.biometria_dactilar import GestorHuellas
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

    registro_asistencia = RegistroAsistencia(archivo_csv=Config.ARCHIVO_ASISTENCIA)

    gestor_rostros = GestorRostros(
        carpeta_rostros=Config.CARPETA_ROSTROS,
        archivo_modelo=Config.ARCHIVO_MODELO_ROSTROS,
        archivo_etiquetas=Config.ARCHIVO_ETIQUETAS_ROSTROS,
        umbral_confianza=Config.FACE_UMBRAL_CONFIANZA,
    )
    gestor_rostros.entrenar()

    gestor_huellas = GestorHuellas(
        puerto=Config.FP_PUERTO,
        baudrate=Config.FP_BAUDRATE,
    )

    bp = create_blueprint(
        gestor_rostros=gestor_rostros,
        gestor_huellas=gestor_huellas,
        registro_asistencia=registro_asistencia,
        carpeta_rostros=Config.CARPETA_ROSTROS,
    )
    app.register_blueprint(bp)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)