"""
app.py
------
Punto de entrada. Arma la aplicación Flask con dos superficies
separadas: el kiosco público (cámara + confirmación, para el alumno)
y el panel de la preceptora (/admin, protegido por PIN).
"""

import logging

from flask import Flask

from config import Config
from core.asistencia import RegistroAsistencia
from core.horarios import GestorHorarios
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
    app.secret_key = Config.SECRET_KEY

    registro_asistencia = RegistroAsistencia(carpeta_asistencia=Config.CARPETA_ASISTENCIA)
    gestor_horarios = GestorHorarios(archivo_horarios=Config.ARCHIVO_HORARIOS)

    gestor_rostros = GestorRostros(
        carpeta_rostros=Config.CARPETA_ROSTROS,
        archivo_cache=Config.ARCHIVO_CACHE_ROSTROS,
        tolerancia=Config.FACE_TOLERANCIA,
        margen_minimo=Config.FACE_MARGEN_MINIMO,
        escala_deteccion=Config.FACE_ESCALA_DETECCION,
    )
    gestor_rostros.entrenar()

    bp = create_blueprint(
        gestor_rostros=gestor_rostros,
        registro_asistencia=registro_asistencia,
        gestor_horarios=gestor_horarios,
        carpeta_rostros=Config.CARPETA_ROSTROS,
        admin_pin=Config.ADMIN_PIN,
    )
    app.register_blueprint(bp)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)