"""
routes/api.py
--------------
Dos superficies separadas:

  - Kiosco público ("/"): cámara + confirmación. Es lo único que ve
    el alumno. No tiene ningún link ni forma de llegar al panel de
    la preceptora desde acá.

  - Panel de la preceptora ("/admin"): registros de asistencia del
    día y configuración de horarios por curso. Protegido por PIN
    (ver core/autenticacion.py) — no es un sistema de usuarios
    completo, pero alcanza para que un alumno curioso en el kiosco
    no pueda tocar nada de esto.
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


def create_blueprint(gestor_rostros, registro_asistencia, gestor_horarios, carpeta_rostros, admin_pin):
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
        """El alumno tocó 'Sí, soy yo'. Acá SÍ se escribe al CSV, con el
        estado (PRESENTE/TARDE) calculado según el horario del curso."""
        data = request.get_json(silent=True) or {}
        alumno = (data.get("alumno") or "").strip()
        curso = (data.get("curso") or "").strip()

        if not alumno or not curso:
            return jsonify({"ok": False, "mensaje": "Faltan 'alumno' o 'curso'"}), 400

        estado = gestor_horarios.calcular_estado(curso, datetime.now())
        registrado = registro_asistencia.registrar_presente(alumno, curso, estado)
        return jsonify({"ok": True, "registrado": registrado, "estado": estado})

    # ==================================================================
    # LOGIN — separa el kiosco del panel de la preceptora
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
        hoy = datetime.now().date()
        resultado = {}
        for curso in cursos:
            efectivo = gestor_horarios.obtener(curso, hoy)
            habitual = gestor_horarios.obtener(curso)
            contraturno = gestor_horarios.obtener_contraturno(curso)
            cfg = gestor_horarios.obtener_todos().get(curso, {})
            resultado[curso] = {
                **efectivo,
                "hora_habitual": habitual["hora_entrada"],
                "tolerancia_habitual": habitual["tolerancia_minutos"],
                "hora_contraturno": contraturno["hora_entrada"],
                "tolerancia_contraturno": contraturno["tolerancia_minutos"],
                "modo_hoy": ("contraturno" if (
                    isinstance(cfg, dict) and
                    cfg.get("cambios", {}).get(hoy.strftime("%Y-%m-%d"), {}).get("tipo")
                    in ("contraturno", "contraturno_id")
                ) else None),
                "modificado_hoy": efectivo != habitual,
            }
        # Por si hay horarios guardados de cursos que ya no tienen carpeta
        # (cambiaron de nombre, etc.) — los mostramos igual para no perder
        # la configuración silenciosamente.
        for curso, cfg in horarios_guardados.items():
            habitual_cfg = cfg.get("habitual", cfg)
            contraturno_cfg = cfg.get("contraturno", habitual_cfg)
            cambio_hoy = cfg.get("cambios", {}).get(hoy.strftime("%Y-%m-%d"), {})
            resultado.setdefault(curso, {
                **gestor_horarios.obtener(curso, hoy),
                "hora_habitual": habitual_cfg.get("hora_entrada", "07:20"),
                "tolerancia_habitual": habitual_cfg.get("tolerancia_minutos", 10),
                "hora_contraturno": contraturno_cfg.get("hora_entrada", "07:20"),
                "tolerancia_contraturno": contraturno_cfg.get("tolerancia_minutos", 10),
                "modo_hoy": cambio_hoy.get("tipo"),
                "modificado_hoy": bool(cambio_hoy),
            })

        return jsonify({"horarios": resultado})

    @bp.route("/admin/api/horarios", methods=["POST"])
    @requiere_admin
    def admin_guardar_horario():
        data = request.get_json(silent=True) or {}
        curso = (data.get("curso") or "").strip()
        hora_entrada = (data.get("hora_entrada") or "").strip()
        tolerancia_minutos = data.get("tolerancia_minutos", 10)
        # Las llamadas antiguas siguen guardando el horario habitual;
        # la interfaz nueva envía False explícitamente para un cambio de hoy.
        guardar_habitual = bool(data.get("guardar_habitual", True))
        accion = data.get("accion", "habitual" if guardar_habitual else "especial")

        if accion in ("activar_normal", "activar_contraturno"):
            try:
                gestor_horarios.activar_modo(
                    curso, "normal" if accion == "activar_normal" else "contraturno",
                    fecha=datetime.now().date()
                )
            except ValueError as exc:
                return jsonify({"ok": False, "mensaje": str(exc)}), 400
            return jsonify({"ok": True})

        if not hora_entrada:
            return jsonify({"ok": False, "mensaje": "Faltan 'curso' o 'hora_entrada'"}), 400

        try:
            gestor_horarios.establecer(
                curso, hora_entrada, int(tolerancia_minutos),
                fecha=datetime.now().date(), habitual=accion == "habitual",
                modo="contraturno" if accion == "contraturno" else "especial"
            )
        except (TypeError, ValueError):
            return jsonify({"ok": False, "mensaje": "Revisá la hora (HH:MM) y una tolerancia entre 0 y 120"}), 400

        return jsonify({"ok": True})

    @bp.route("/admin/api/contraturnos", methods=["GET"])
    @requiere_admin
    def admin_obtener_contraturnos():
        return jsonify({"contraturnos": gestor_horarios.obtener_contraturnos()})

    @bp.route("/admin/api/contraturnos", methods=["POST"])
    @requiere_admin
    def admin_crear_contraturno():
        return _guardar_contraturno()

    @bp.route("/admin/api/contraturnos/<identificador>", methods=["PUT"])
    @requiere_admin
    def admin_actualizar_contraturno(identificador):
        return _guardar_contraturno(identificador)

    @bp.route("/admin/api/contraturnos/<identificador>", methods=["DELETE"])
    @requiere_admin
    def admin_eliminar_contraturno(identificador):
        data = request.get_json(silent=True) or {}
        curso = (data.get("curso") or "").strip()
        try:
            gestor_horarios.eliminar_contraturno(identificador, curso)
        except KeyError:
            return jsonify({"ok": False, "mensaje": "Contraturno no encontrado"}), 404
        return jsonify({"ok": True})

    @bp.route("/admin/api/contraturnos/<identificador>/activar", methods=["POST"])
    @requiere_admin
    def admin_activar_contraturno(identificador):
        data = request.get_json(silent=True) or {}
        curso = (data.get("curso") or "").strip()
        try:
            gestor_horarios.activar_contraturno_registro(
                identificador, curso, fecha=datetime.now().date()
            )
        except KeyError:
            return jsonify({"ok": False, "mensaje": "Contraturno no encontrado"}), 404
        return jsonify({"ok": True})

    def _guardar_contraturno(identificador=None):
        data = request.get_json(silent=True) or {}
        curso = (data.get("curso") or "").strip()
        dia = (data.get("dia") or "").strip().lower()
        hora = (data.get("hora_entrada") or "").strip()
        tolerancia = data.get("tolerancia_minutos", 10)
        if not curso or dia not in ("lunes", "martes", "miércoles", "jueves", "viernes"):
            return jsonify({"ok": False, "mensaje": "Elegí un curso y un día válido"}), 400
        try:
            if identificador:
                registro = gestor_horarios.actualizar_contraturno(
                    identificador, curso, dia, hora, tolerancia
                )
            else:
                registro = gestor_horarios.crear_contraturno(curso, dia, hora, tolerancia)
        except KeyError:
            return jsonify({"ok": False, "mensaje": "Contraturno no encontrado"}), 404
        except (TypeError, ValueError):
            return jsonify({"ok": False, "mensaje": "Revisá la hora y la tolerancia (0 a 120)"}), 400
        return jsonify({"ok": True, "contraturno": registro})

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

    return bp