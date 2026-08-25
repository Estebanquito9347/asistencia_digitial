"""
routes/api.py
--------------
Versión mínima: solo lo necesario para que la cámara identifique un
candidato y el frontend muestre "¿sos vos?". No escribe nada a disco
todavía — ni CSV de asistencia ni nada de huella. Eso se retoma en una
pasada aparte.
"""

import base64
import logging
import os

import cv2
import numpy as np
from flask import Blueprint, jsonify, render_template, request

logger = logging.getLogger(__name__)


def _decodificar_frame(imagen_raw: str):
    """base64 (dataURL) -> frame RGB. face_recognition/dlib esperan RGB,
    a diferencia de OpenCV que trabaja nativamente en BGR."""
    if not imagen_raw or "," not in imagen_raw:
        return None
    imagen_base64 = imagen_raw.split(",")[1]
    img_bytes = base64.b64decode(imagen_base64)
    nparr = np.frombuffer(img_bytes, np.uint8)
    frame_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if frame_bgr is None:
        return None
    return cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)


def create_blueprint(gestor_rostros, carpeta_rostros):
    bp = Blueprint("api", __name__)

    @bp.route("/")
    def index():
        return render_template("index.html")

    @bp.route("/obtener_cursos", methods=["GET"])
    def obtener_cursos():
        if os.path.exists(carpeta_rostros):
            cursos = [d for d in os.listdir(carpeta_rostros) if os.path.isdir(os.path.join(carpeta_rostros, d))]
            return jsonify({"cursos": sorted(cursos)})
        return jsonify({"cursos": []})

    @bp.route("/procesar_fotograma", methods=["POST"])
    def procesar_fotograma():
        data = request.get_json(silent=True) or {}
        curso_seleccionado = data.get("curso")

        try:
            frame_rgb = _decodificar_frame(data.get("imagen"))
            if frame_rgb is None:
                return jsonify({"detectado": False})

            resultado = gestor_rostros.buscar_en_frame(frame_rgb, curso_esperado=curso_seleccionado)
            if resultado["detectado"]:
                return jsonify({
                    "detectado": True,
                    "alumno": resultado["alumno"],
                    "curso": resultado["curso"],
                })
        except Exception:
            logger.exception("Error en procesamiento de fotograma")

        return jsonify({"detectado": False})

    @bp.route("/reentrenar_rostros", methods=["POST"])
    def reentrenar_rostros():
        forzar = bool((request.get_json(silent=True) or {}).get("forzar", False))
        gestor_rostros.entrenar(forzar=forzar)
        return jsonify({"ok": True, "alumnos_cargados": len(gestor_rostros.nombres_rostros)})

    return bp