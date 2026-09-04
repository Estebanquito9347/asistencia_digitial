"""
core/horarios.py
------------------
Modelo de horarios de la escuela:

  - Cada curso tiene un TURNO HABITUAL: la hora de entrada de todos
    los días (ej: 1°, 2° y 3° entran a las 13:20; el resto a las 7:15).

  - Cada curso puede tener además varios CONTRATURNOS: materias con
    horario especial, cada una con su propio nombre, los días de la
    semana en que ocurre, y su horario de inicio/fin. Un curso puede
    tener muchas — no es "un solo horario alternativo", es una lista
    (ej: 3°A tiene Ed. Física los lunes Y los jueves, más Historia
    los martes, cada una con su propio horario).

  - Existen además GRUPOS TRANSVERSALES (por ahora solo informativos):
    actividades como los Niveles de Inglés, que juntan alumnos de
    distintos cursos según en qué nivel están, no según su curso base.
    Se guardan con el mismo formato de horario que un contraturno,
    pero TODAVÍA NO están conectados al cálculo automático de
    asistencia — eso requiere poder asignar alumnos individuales a un
    grupo (algo transversal a los cursos), que es una funcionalidad
    aparte para más adelante.

Al tomar asistencia, calcular_estado() mira el día de la semana y la
hora actual, arma la lista de franjas válidas para HOY (el turno
habitual siempre cuenta, más los contraturnos cuyo día coincide con
hoy), y elige la más reciente que ya debería haber empezado. Si el
alumno llega antes de que empiece cualquier franja del día, se toma
la más próxima y se considera presente (llegó temprano).
"""

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DIAS_SEMANA = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
TURNO_HABITUAL_DEFAULT = {"hora_entrada": "08:00", "tolerancia_minutos": 10}


def _dia_de_hoy(momento: datetime) -> str:
    return DIAS_SEMANA[momento.weekday()]


class GestorHorarios:
    def __init__(self, archivo_horarios: str):
        self.archivo_horarios = archivo_horarios
        self._lock = threading.Lock()
        self._datos = self._cargar()

    def _cargar(self) -> dict:
        if os.path.exists(self.archivo_horarios):
            try:
                with open(self.archivo_horarios, "r", encoding="utf-8") as f:
                    datos = json.load(f)
                datos.setdefault("cursos", {})
                datos.setdefault("grupos_transversales", {})
                return datos
            except Exception:
                logger.exception("No se pudo leer %s, se arranca vacío", self.archivo_horarios)
        return {"cursos": {}, "grupos_transversales": {}}

    def _guardar(self) -> None:
        try:
            with open(self.archivo_horarios, "w", encoding="utf-8") as f:
                json.dump(self._datos, f, ensure_ascii=False, indent=2)
        except Exception:
            logger.exception("No se pudo guardar %s", self.archivo_horarios)

    # ------------------------------------------------------------------
    # Lectura
    # ------------------------------------------------------------------
    def obtener_todos_los_cursos(self) -> dict:
        return dict(self._datos["cursos"])

    def obtener(self, curso: str) -> dict:
        cfg = self._datos["cursos"].get(curso, {})
        return {
            "turno_habitual": cfg.get("turno_habitual", dict(TURNO_HABITUAL_DEFAULT)),
            "contraturnos": cfg.get("contraturnos", []),
        }

    def obtener_grupos_transversales(self) -> dict:
        """Solo informativo por ahora — ver docstring del módulo."""
        return dict(self._datos["grupos_transversales"])

    # ------------------------------------------------------------------
    # Validación
    # ------------------------------------------------------------------
    @staticmethod
    def _validar_hora(hora: str) -> str:
        datetime.strptime(hora, "%H:%M")
        return hora

    @classmethod
    def _validar_dias(cls, dias: list) -> list:
        dias_validos = [d for d in dias if d in DIAS_SEMANA]
        if not dias_validos:
            raise ValueError("Hay que elegir al menos un día válido")
        return dias_validos

    @staticmethod
    def _hora_inicio(franja: dict) -> str:
        return franja.get("hora_inicio") or franja["hora_entrada"]

    # ------------------------------------------------------------------
    # Turno habitual
    # ------------------------------------------------------------------
    def establecer_turno_habitual(self, curso: str, hora_entrada: str, tolerancia_minutos: int = 10) -> None:
        self._validar_hora(hora_entrada)
        with self._lock:
            self._datos["cursos"].setdefault(curso, {})
            self._datos["cursos"][curso]["turno_habitual"] = {
                "hora_entrada": hora_entrada, "tolerancia_minutos": int(tolerancia_minutos),
            }
            self._guardar()
            logger.info("Turno habitual de %s actualizado: entra %s (tolerancia %d min)",
                        curso, hora_entrada, tolerancia_minutos)

    def establecer_turno_habitual_multiple(self, cursos: list, hora_entrada: str, tolerancia_minutos: int = 10) -> None:
        self._validar_hora(hora_entrada)
        with self._lock:
            for curso in cursos:
                self._datos["cursos"].setdefault(curso, {})
                self._datos["cursos"][curso]["turno_habitual"] = {
                    "hora_entrada": hora_entrada, "tolerancia_minutos": int(tolerancia_minutos),
                }
            self._guardar()
            logger.info("Turno habitual aplicado a %d cursos: entra %s", len(cursos), hora_entrada)

    # ------------------------------------------------------------------
    # Contraturnos (lista por curso)
    # ------------------------------------------------------------------
    def agregar_contraturno(self, curso: str, materia: str, dias: list,
                             hora_inicio: str, hora_fin: str, tolerancia_minutos: int = 10) -> str:
        self._validar_hora(hora_inicio)
        self._validar_hora(hora_fin)
        dias_validados = self._validar_dias(dias)

        contraturno_id = uuid.uuid4().hex[:8]
        with self._lock:
            self._datos["cursos"].setdefault(curso, {})
            self._datos["cursos"][curso].setdefault("contraturnos", [])
            self._datos["cursos"][curso]["contraturnos"].append({
                "id": contraturno_id, "materia": materia, "dias": dias_validados,
                "hora_inicio": hora_inicio, "hora_fin": hora_fin,
                "tolerancia_minutos": int(tolerancia_minutos),
            })
            self._guardar()
            logger.info("Contraturno agregado a %s: %s (%s) %s-%s",
                        curso, materia, dias_validados, hora_inicio, hora_fin)
        return contraturno_id

    def editar_contraturno(self, curso: str, contraturno_id: str, **cambios) -> bool:
        if "hora_inicio" in cambios:
            self._validar_hora(cambios["hora_inicio"])
        if "hora_fin" in cambios:
            self._validar_hora(cambios["hora_fin"])
        if "dias" in cambios:
            cambios["dias"] = self._validar_dias(cambios["dias"])
        if "tolerancia_minutos" in cambios:
            cambios["tolerancia_minutos"] = int(cambios["tolerancia_minutos"])

        with self._lock:
            contraturnos = self._datos["cursos"].get(curso, {}).get("contraturnos", [])
            for c in contraturnos:
                if c["id"] == contraturno_id:
                    c.update(cambios)
                    self._guardar()
                    logger.info("Contraturno %s de %s actualizado", contraturno_id, curso)
                    return True
        return False

    def eliminar_contraturno(self, curso: str, contraturno_id: str) -> bool:
        with self._lock:
            contraturnos = self._datos["cursos"].get(curso, {}).get("contraturnos", [])
            largo_previo = len(contraturnos)
            contraturnos[:] = [c for c in contraturnos if c["id"] != contraturno_id]
            if len(contraturnos) < largo_previo:
                self._guardar()
                logger.info("Contraturno %s de %s eliminado", contraturno_id, curso)
                return True
        return False

    # ------------------------------------------------------------------
    # Grupos transversales (informativo por ahora)
    # ------------------------------------------------------------------
    def establecer_grupo_transversal(self, nombre: str, dias: list, hora_inicio: str,
                                      hora_fin: str, tolerancia_minutos: int = 10) -> None:
        self._validar_hora(hora_inicio)
        self._validar_hora(hora_fin)
        dias_validados = self._validar_dias(dias)
        with self._lock:
            self._datos["grupos_transversales"][nombre] = {
                "dias": dias_validados, "hora_inicio": hora_inicio, "hora_fin": hora_fin,
                "tolerancia_minutos": int(tolerancia_minutos),
            }
            self._guardar()
            logger.info("Grupo transversal '%s' actualizado", nombre)

    def eliminar_grupo_transversal(self, nombre: str) -> bool:
        with self._lock:
            if nombre in self._datos["grupos_transversales"]:
                del self._datos["grupos_transversales"][nombre]
                self._guardar()
                return True
        return False

    # ------------------------------------------------------------------
    # Cálculo de estado al tomar asistencia
    # ------------------------------------------------------------------
    def _elegir_franja_vigente(self, curso: str, momento: datetime):
        cfg = self.obtener(curso)
        dia_hoy = _dia_de_hoy(momento)

        turno_hab_raw = cfg["turno_habitual"]
        
        # Obtenemos el habitual del día actual de forma segura
        if dia_hoy in turno_hab_raw and isinstance(turno_hab_raw[dia_hoy], dict):
            habitual_hoy = turno_hab_raw[dia_hoy]
        elif "hora_entrada" in turno_hab_raw:
            # Compatibilidad con formato viejo si lo hubiera
            habitual_hoy = {"hora_entrada": turno_hab_raw["hora_entrada"], "hora_fin": "18:00", "tolerancia_minutos": turno_hab_raw.get("tolerancia_minutos", 10)}
        else:
            habitual_hoy = {"hora_entrada": "08:00", "hora_fin": "12:00", "tolerancia_minutos": 10}

        candidatos = []

        # Verificamos si el turno habitual de hoy ya terminó o sigue vigente
        if "hora_fin" in habitual_hoy:
            hora_fin_hab = datetime.strptime(habitual_hoy["hora_fin"], "%H:%M").time()
            limite_fin_hab = (datetime.combine(momento.date(), hora_fin_hab) + timedelta(minutes=habitual_hoy.get("tolerancia_minutos", 10))).time()
            if momento.time() <= limite_fin_hab:
                candidatos.append(("Habitual", habitual_hoy))
        else:
            candidatos.append(("Habitual", habitual_hoy))

        # Sumamos los contraturnos válidos que no hayan terminado
        for c in cfg["contraturnos"]:
            if dia_hoy in c["dias"]:
                hora_fin_c = datetime.strptime(c["hora_fin"], "%H:%M").time()
                limite_fin_c = (datetime.combine(momento.date(), hora_fin_c) + timedelta(minutes=c["tolerancia_minutos"])).time()
                
                if momento.time() <= limite_fin_c:
                    candidatos.append((c["materia"], c))

        if not candidatos:
            # Si por horario ya pasó todo, devolvemos el habitual por defecto para no romper
            return ("Habitual", habitual_hoy)

        # Filtramos cuáles candidatos ya empezaron
        vigentes = [
            (nombre, franja) for nombre, franja in candidatos
            if datetime.strptime(self._hora_inicio(franja), "%H:%M").time() <= momento.time()
        ]

        if vigentes:
            return max(vigentes, key=lambda par: datetime.strptime(self._hora_inicio(par[1]), "%H:%M").time())
        return min(candidatos, key=lambda par: datetime.strptime(self._hora_inicio(par[1]), "%H:%M").time())

    def franja_vigente(self, curso: str, ahora: datetime) -> str:
        """Método público que llama el panel de tiempo real de Flask"""
        nombre_franja, _ = self._elegir_franja_vigente(curso, ahora)
        return nombre_franja