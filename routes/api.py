"""
routes/api.py
--------------
Tres superficies:

  - Kiosco público ("/"): cámara + confirmación, lo único que ve el
    alumno.
  - Panel de la preceptora ("/admin"): registros, horarios, descarga
    de CSV por curso. Protegido por PIN.
  - Endpoints del lector de huella en red ("/api/..."): conectar y
    sincronizar el terminal ZKTeco. También protegidos por PIN — es
    una operación administrativa (toca hardware compartido y escribe
    en los mismos CSV de asistencia), no algo que el alumno dispare.
"""

import base64
import logging
import os
from datetime import datetime

import cv2
import numpy as np
from flask import Blueprint, jsonify, render_template, request, send_file, redirect, session, url_for

from core.autenticacion import requiere_admin

logger = logging.getLogger(__name__)


def _decodificar_frame(imagen_raw: str):
    """base64 (dataURL) -> frame RGB. face_recognition/dlib esperan RGB."""
    if not imagen_raw or "," not in imagen_raw:
        return None
    imagen_base64 = imagen_raw.split(",")[1]
    img_bytes = base64.b64decode(imagen_base64)
    nparr = np.frombuffer(img_bytes, np.uint8)
    frame_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if frame_bgr is None:
        return None
    return cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)


def create_blueprint(gestor_rostros, registro_asistencia, gestor_horarios, gestor_huella_red,
                      carpeta_rostros, admin_pin):
    bp = Blueprint("api", __name__)

    # ==================================================================
    # KIOSCO PÚBLICO — lo único que ve el alumno
    # ==================================================================
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

    @bp.route("/confirmar_asistencia", methods=["POST"])
    def confirmar_asistencia():
        """El alumno tocó 'Sí, soy yo'. Mismo camino que usa la
        sincronización del lector de huella: RegistroAsistencia +
        GestorHorarios, terminan en el mismo CSV."""
        data = request.get_json(silent=True) or {}
        alumno = (data.get("alumno") or "").strip()
        curso = (data.get("curso") or "").strip()

        if not alumno or not curso:
            return jsonify({"ok": False, "mensaje": "Faltan 'alumno' o 'curso'"}), 400

        resultado_horario = gestor_horarios.calcular_estado(curso, datetime.now())
        registrado = registro_asistencia.registrar_presente(
            alumno, curso, resultado_horario["turno"], resultado_horario["estado"]
        )
        return jsonify({"ok": True, "registrado": registrado, "estado": resultado_horario["estado"],
                         "turno": resultado_horario["turno"]})

    # ==================================================================
    # LOGIN
    # ==================================================================
    @bp.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            if request.form.get("pin") == admin_pin:
                session["admin_autenticado"] = True
                return redirect(url_for("api.admin"))
            error = "PIN incorrecto"
        return render_template("login.html", error=error)

    @bp.route("/logout")
    def logout():
        session.pop("admin_autenticado", None)
        return redirect(url_for("api.login"))

    # ==================================================================
    # PANEL DE LA PRECEPTORA — protegido
    # ==================================================================
    @bp.route("/admin")
    @requiere_admin
    def admin():
        return render_template("admin.html")

    @bp.route("/admin/api/registros", methods=["GET"])
    @requiere_admin
    def admin_registros():
        curso = request.args.get("curso") or None
        return jsonify({"registros": registro_asistencia.registros_de_hoy(curso=curso)})

    @bp.route("/admin/api/resumen", methods=["GET"])
    @requiere_admin
    def admin_resumen():
        return jsonify({"cursos": registro_asistencia.resumen_del_dia()})

    @bp.route("/admin/api/horarios", methods=["GET"])
    @requiere_admin
    def admin_obtener_horarios():
        cursos = []
        if os.path.exists(carpeta_rostros):
            cursos = sorted(d for d in os.listdir(carpeta_rostros) if os.path.isdir(os.path.join(carpeta_rostros, d)))

        horarios_guardados = gestor_horarios.obtener_todos()
        resultado = {curso: gestor_horarios.obtener(curso) for curso in cursos}
        for curso, cfg in horarios_guardados.items():
            resultado.setdefault(curso, cfg)

        return jsonify({"horarios": resultado})

    @bp.route("/admin/api/horarios", methods=["POST"])
    @requiere_admin
    def admin_guardar_horario():
        data = request.get_json(silent=True) or {}
        curso = (data.get("curso") or "").strip()
        turno = data.get("turno")
        contraturno = data.get("contraturno")

        if not curso or not turno:
            return jsonify({"ok": False, "mensaje": "Faltan 'curso' o 'turno'"}), 400

        try:
            gestor_horarios.establecer(curso, turno, contraturno)
        except (ValueError, KeyError):
            return jsonify({"ok": False, "mensaje": "Formato de horario inválido (hora_entrada debe ser HH:MM)"}), 400

        return jsonify({"ok": True})

    @bp.route("/admin/api/horarios/aplicar_multiple", methods=["POST"])
    @requiere_admin
    def admin_aplicar_horario_multiple():
        data = request.get_json(silent=True) or {}
        cursos = data.get("cursos") or []
        turno = data.get("turno")
        contraturno = data.get("contraturno")

        if not cursos or not turno:
            return jsonify({"ok": False, "mensaje": "Faltan 'cursos' o 'turno'"}), 400

        try:
            gestor_horarios.establecer_multiple(cursos, turno, contraturno)
        except (ValueError, KeyError):
            return jsonify({"ok": False, "mensaje": "Formato de horario inválido (hora_entrada debe ser HH:MM)"}), 400

        return jsonify({"ok": True, "cursos_actualizados": len(cursos)})

    @bp.route("/admin/descargar_asistencia/<curso>")
    @requiere_admin
    def admin_descargar_asistencia(curso):
        fecha = request.args.get("fecha") or datetime.now().strftime("%Y-%m-%d")
        ruta = registro_asistencia.ruta_para(curso, fecha)
        if ruta:
            return send_file(ruta, as_attachment=True, download_name=f"asistencia_{curso}_{fecha}.csv")
        return f"No hay registros para {curso} en {fecha}", 404

    @bp.route("/admin/reentrenar_rostros", methods=["POST"])
    @requiere_admin
    def admin_reentrenar_rostros():
        forzar = bool((request.get_json(silent=True) or {}).get("forzar", False))
        gestor_rostros.entrenar(forzar=forzar)
        return jsonify({"ok": True, "alumnos_cargados": len(gestor_rostros.nombres_rostros)})

    # ==================================================================
    # LECTOR DE HUELLA EN RED (ZKTeco) — protegido, igual que el resto
    # de operaciones administrativas
    # ==================================================================
    @bp.route("/api/conectar-lector", methods=["GET"])
    @requiere_admin
    def api_conectar_lector():
        return jsonify(gestor_huella_red.conectar())

    @bp.route("/admin/api/huella_red/usuarios", methods=["GET"])
    @requiere_admin
    def admin_huella_red_usuarios():
        """Usuarios cargados en el dispositivo — para que la preceptora
        vea qué user_id corresponde a qué persona y arme el mapeo."""
        try:
            return jsonify({"usuarios": gestor_huella_red.obtener_usuarios_dispositivo()})
        except Exception as e:
            logger.exception("Error obteniendo usuarios del lector de huella")
            return jsonify({"ok": False, "mensaje": str(e)}), 502

    @bp.route("/admin/api/huella_red/mapeo", methods=["POST"])
    @requiere_admin
    def admin_huella_red_mapeo():
        """Asocia un user_id del dispositivo con un alumno (nombre + curso)
        de nuestra app. Sin esto, sus marcaciones llegan sin poder
        identificarse (ver /api/sincronizar-asistencia)."""
        data = request.get_json(silent=True) or {}
        user_id = data.get("user_id")
        nombre = (data.get("nombre") or "").strip()
        curso = (data.get("curso") or "").strip()

        if user_id is None or not nombre or not curso:
            return jsonify({"ok": False, "mensaje": "Faltan 'user_id', 'nombre' o 'curso'"}), 400

        gestor_huella_red.registrar_mapeo(user_id, nombre, curso)
        return jsonify({"ok": True})

    @bp.route("/api/sincronizar-asistencia", methods=["POST"])
    @requiere_admin
    def api_sincronizar_asistencia():
        """Descarga las marcaciones del lector y las escribe en
        asistencia/<curso>/<fecha>.csv — el MISMO archivo y el mismo
        cálculo de estado (PRESENTE/TARDE vía GestorHorarios) que usa
        la cámara. Es la unificación pedida: no importa si vino de la
        cara o del dedo, termina en el mismo historial.

        Las marcaciones de un user_id sin mapear NO se pierden: se
        devuelven en 'sin_mapear' para que la preceptora las resuelva
        desde /admin/api/huella_red/mapeo y vuelva a sincronizar.
        """
        limpiar = bool((request.get_json(silent=True) or {}).get("limpiar_dispositivo", False))

        try:
            marcaciones = gestor_huella_red.obtener_marcaciones(limpiar_dispositivo=limpiar)
        except Exception as e:
            logger.exception("Error sincronizando con el lector de huella")
            return jsonify({"ok": False, "mensaje": str(e)}), 502

        registradas, duplicadas, sin_mapear = 0, 0, []

        for m in marcaciones:
            if not m["alumno"] or not m["curso"]:
                sin_mapear.append(m["user_id"])
                continue

            momento = m["timestamp"]  # datetime real de la fichada, no el de ahora
            resultado_horario = gestor_horarios.calcular_estado(m["curso"], momento)
            registrado = registro_asistencia.registrar_presente(
                m["alumno"], m["curso"], resultado_horario["turno"], resultado_horario["estado"],
                momento=momento,
            )
            if registrado:
                registradas += 1
            else:
                duplicadas += 1

        return jsonify({
            "ok": True,
            "total_marcaciones": len(marcaciones),
            "registradas": registradas,
            "duplicadas": duplicadas,
            "sin_mapear": sorted(set(sin_mapear)),
        })

    return bp