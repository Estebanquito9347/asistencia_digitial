"""
routes/api.py
--------------
Versión simplificada, enfocada en lo esencial: la cámara detecta un
candidato, la preceptora confirma manualmente que es esa persona, y
(si el sensor está conectado) la huella funciona en paralelo. Nada de
estructura CIDI todavía — eso vuelve más adelante.
"""

import base64
import logging
import os

import cv2
import numpy as np
from flask import Blueprint, jsonify, render_template, request, send_file

logger = logging.getLogger(__name__)


def _decodificar_frame(imagen_raw: str):
    """base64 (dataURL) -> frame BGR, listo para OpenCV. Sin conversión de color:
    OpenCV trabaja nativamente en BGR, a diferencia de face_recognition/dlib."""
    if not imagen_raw or "," not in imagen_raw:
        return None
    imagen_base64 = imagen_raw.split(",")[1]
    img_bytes = base64.b64decode(imagen_base64)
    nparr = np.frombuffer(img_bytes, np.uint8)
    return cv2.imdecode(nparr, cv2.IMREAD_COLOR)


def create_blueprint(gestor_rostros, gestor_huellas, registro_asistencia, carpeta_rostros):
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

    @bp.route("/estado_hardware", methods=["GET"])
    def estado_hardware():
        return jsonify({"sensor_huella_disponible": gestor_huellas.disponible})

    # ------------------------------------------------------------------
    # Reconocimiento facial (identifica; la preceptora confirma)
    # ------------------------------------------------------------------
    @bp.route("/procesar_fotograma", methods=["POST"])
    def procesar_fotograma():
        data = request.get_json(silent=True) or {}
        curso_seleccionado = data.get("curso")

        try:
            frame_bgr = _decodificar_frame(data.get("imagen"))
            if frame_bgr is None:
                return jsonify({"detectado": False})

            resultado = gestor_rostros.buscar_en_frame(frame_bgr, curso_esperado=curso_seleccionado)
            if resultado["detectado"]:
                return jsonify({
                    "detectado": True,
                    "alumno": resultado["alumno"],
                    "curso": resultado["curso"],
                })
        except Exception:
            logger.exception("Error en procesamiento de fotograma")

        return jsonify({"detectado": False})

    @bp.route("/confirmar_asistencia", methods=["POST"])
    def confirmar_asistencia():
        """La preceptora tocó 'Sí, soy yo/es' en el frontend."""
        data = request.get_json(silent=True) or {}
        alumno = (data.get("alumno") or "").strip()
        curso = (data.get("curso") or "").strip()
        metodo = (data.get("metodo") or "FACIAL").strip()

        if not alumno or not curso:
            return jsonify({"ok": False, "mensaje": "Faltan 'alumno' o 'curso'"}), 400

        registrado = registro_asistencia.registrar_presente(alumno, curso, metodo)
        return jsonify({"ok": True, "registrado": registrado})

    @bp.route("/reentrenar_rostros", methods=["POST"])
    def reentrenar_rostros():
        forzar = bool((request.get_json(silent=True) or {}).get("forzar", False))
        gestor_rostros.entrenar(forzar=forzar)
        return jsonify({"ok": True, "alumnos_cargados": len(gestor_rostros.etiqueta_a_alumno)})

    # ------------------------------------------------------------------
    # Biometría dactilar (sensor Suprema)
    # ------------------------------------------------------------------
    @bp.route("/identificar_huella", methods=["POST"])
    def identificar_huella():
        resultado = gestor_huellas.identificar(timeout_seg=1)
        # NOTA: todavía no tenemos el mapeo id_huella -> alumno resuelto acá
        # (eso llega con la tabla ALUMNOS). Por ahora esto solo confirma que
        # el sensor identificó ALGÚN id — falta unirlo con el nombre.
        return jsonify(resultado)

    @bp.route("/enrolar_huella", methods=["POST"])
    def enrolar_huella():
        data = request.get_json(silent=True) or {}
        id_huella = data.get("id_huella")

        if id_huella is None:
            return jsonify({"ok": False, "mensaje": "Falta 'id_huella'"}), 400
        if not gestor_huellas.disponible:
            return jsonify({"ok": False, "mensaje": "El sensor de huellas no está conectado"}), 503

        resultado = gestor_huellas.enrolar(int(id_huella))
        return jsonify(resultado), (200 if resultado["ok"] else 409)

    @bp.route("/reconectar_sensor", methods=["POST"])
    def reconectar_sensor():
        ok = gestor_huellas.reintentar_conexion()
        return jsonify({"sensor_huella_disponible": ok})

    # ------------------------------------------------------------------
    @bp.route("/descargar_asistencia")
    def descargar_asistencia():
        if registro_asistencia.existe_archivo():
            return send_file(registro_asistencia.archivo_csv, as_attachment=True)
        return "No hay registros guardados hoy", 404

    return bp