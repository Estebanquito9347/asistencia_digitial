import base64
import logging
import os

import cv2
import numpy as np
from flask import Blueprint, jsonify, render_template, request, send_file

logger = logging.getLogger(__name__)


def _decodificar_frame(imagen_raw: str):
    if not imagen_raw or "," not in imagen_raw:
        return None
    imagen_base64 = imagen_raw.split(",")[1]
    img_bytes = base64.b64decode(imagen_base64)
    nparr = np.frombuffer(img_bytes, np.uint8)
    return cv2.imdecode(nparr, cv2.IMREAD_COLOR)


def create_blueprint(gestor_rostros, carpeta_rostros, registro_asistencia=None):
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
            frame_bgr = _decodificar_frame(data.get("imagen"))
            if frame_bgr is None:
                return jsonify({"detectado": False, "motivo": "imagen_invalida"})

            resultado = gestor_rostros.buscar_en_frame(frame_bgr, curso_esperado=curso_seleccionado)
            if resultado["detectado"]:
                return jsonify({
                    "detectado": True,
                    "alumno": resultado["alumno"],
                    "curso": resultado["curso"],
                    "distancia": resultado.get("distancia"),
                    "confianza": resultado.get("confianza", max(0.0, 1.0 - float(resultado.get("distancia", 0.0)) / 1.5)),
                })
            return jsonify({
                "detectado": False,
                "motivo": resultado.get("motivo", "desconocido"),
                "curso_real": resultado.get("curso"),
                "distancia": resultado.get("distancia"),
                "confianza": resultado.get("confianza"),
            })
        except Exception:
            logger.exception("Error en procesamiento de fotograma")

        return jsonify({"detectado": False, "motivo": "error_procesamiento"})

    @bp.route("/confirmar_asistencia", methods=["POST"])
    def confirmar_asistencia():
        data = request.get_json(silent=True) or {}
        alumno = (data.get("alumno") or "").strip()
        curso = (data.get("curso") or "").strip()
        metodo = (data.get("metodo") or "FACIAL").strip()

        if not alumno or not curso:
            return jsonify({"registrado": False, "motivo": "faltan_datos"})

        if registro_asistencia is None:
            return jsonify({"registrado": False, "motivo": "sin_registro"})

        registrado = registro_asistencia.registrar_presente(alumno, curso, metodo)
        return jsonify({"registrado": registrado, "motivo": "ya_registrado" if not registrado else "ok"})

    @bp.route("/descargar_asistencia", methods=["GET"])
    def descargar_asistencia():
        if registro_asistencia is None:
            return jsonify({"ok": False, "mensaje": "Sin registro de asistencia"})

        archivo = registro_asistencia.archivo_csv
        if not os.path.exists(archivo):
            with open(archivo, "w", encoding="utf-8") as fh:
                fh.write("Fecha;Hora;Alumno;Curso;Método;Estado\n")

        return send_file(archivo, mimetype="text/csv", as_attachment=True, download_name="asistencia.csv")

    @bp.route("/estado_hardware", methods=["GET"])
    def estado_hardware():
        return jsonify({"sensor_huella_disponible": False})

    @bp.route("/reentrenar_rostros", methods=["POST"])
    def reentrenar_rostros():
        forzar = bool((request.get_json(silent=True) or {}).get("forzar", False))
        gestor_rostros.entrenar(forzar=forzar)
        return jsonify({"ok": True, "muestras_cargadas": len(gestor_rostros.muestras)})

    return bp
