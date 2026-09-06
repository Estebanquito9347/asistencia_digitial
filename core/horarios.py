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
MINUTOS_ANTICIPACION = 20


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
        """Un contraturno manda SOLO mientras dura (de su hora de inicio
        a su hora de fin, más el margen de tolerancia). Fuera de esa
        ventana puntual, rige directamente el turno habitual del curso
        — así una clase que ya terminó hace horas no se queda "pegada"
        como si siguiera pasando."""
        cfg = self.obtener(curso)
        dia_hoy = _dia_de_hoy(momento)
        
        # --- NUEVO: Verificar si hay una excepción de horario para ESTA fecha exacta ---
        fecha_str = momento.strftime("%Y-%m-%d")
        excepciones_fecha = cfg.get("excepciones_fecha", {})
        
        if fecha_str in excepciones_fecha:
            exc = excepciones_fecha[fecha_str]
            # Creamos un habitual temporal con la hora modificada por la preceptora
            habitual = {
                "hora_entrada": exc["hora_entrada"],
                "tolerancia_minutos": exc.get("tolerancia_minutos", cfg.get("turno_habitual", {}).get("tolerancia_minutos", 10))
            }
        else:
            habitual = cfg["turno_habitual"]
        # -----------------------------------------------------------------------------

        contraturnos_de_hoy = [c for c in cfg["contraturnos"] if dia_hoy in c["dias"]]
        activos_ahora = []
        for c in contraturnos_de_hoy:
            inicio = datetime.strptime(c["hora_inicio"], "%H:%M").time()
            fin = datetime.strptime(c["hora_fin"], "%H:%M").time()

            limite_temprano = (
                datetime.combine(momento.date(), inicio) - timedelta(minutes=MINUTOS_ANTICIPACION)
            ).time()
            limite_tarde = (
                datetime.combine(momento.date(), fin) + timedelta(minutes=c["tolerancia_minutos"])
            ).time()

            if limite_temprano <= momento.time() <= limite_tarde:
                activos_ahora.append(c)

        if activos_ahora:
            # Si por algún motivo se superponen dos contraturnos, gana el
            # que empezó más tarde (el más específico para este momento).
            elegido = max(activos_ahora, key=lambda c: datetime.strptime(c["hora_inicio"], "%H:%M").time())
            return elegido["materia"], elegido

        return "Habitual", habitual

    def franja_vigente(self, curso: str, momento: datetime) -> str:
        """Nombre de la franja horaria vigente AHORA MISMO para ese curso
        ('Habitual' o el nombre de la materia en curso), sin registrar
        nada ni calcular tardanza — pensado para un panel en tiempo real."""
        nombre, _franja = self._elegir_franja_vigente(curso, momento)
        return nombre

    def calcular_estado(self, curso: str, momento: datetime) -> dict:
        """Devuelve {'turno': <nombre de la franja vigente>, 'estado': 'PRESENTE'|'TARDE'}."""
        nombre, franja = self._elegir_franja_vigente(curso, momento)
        hora_inicio = datetime.strptime(self._hora_inicio(franja), "%H:%M").time()

        if momento.time() < hora_inicio:
            # Llegó antes de que empezara esta franja: presente, llegó temprano.
            return {"turno": nombre, "estado": "PRESENTE"}

        limite = (
            datetime.combine(momento.date(), hora_inicio) + timedelta(minutes=franja["tolerancia_minutos"])
        ).time()

        estado = "PRESENTE" if momento.time() <= limite else "TARDE"
        return {"turno": nombre, "estado": estado}
    # ------------------------------------------------------------------
    # Excepciones por fecha
    # ------------------------------------------------------------------
    def agregar_excepcion_fecha(self, curso: str, fecha: str, hora_entrada: str, tolerancia_minutos: int = 10) -> None:
        self._validar_hora(hora_entrada)
        with self._lock:
            self._datos["cursos"].setdefault(curso, {})
            self._datos["cursos"][curso].setdefault("excepciones_fecha", {})
            self._datos["cursos"][curso]["excepciones_fecha"][fecha] = {
                "hora_entrada": hora_entrada,
                "tolerancia_minutos": int(tolerancia_minutos),
            }
            self._guardar()
            logger.info("Excepción de fecha agregada a %s para el día %s: entra %s", curso, fecha, hora_entrada)

    def obtener_excepciones(self) -> dict:
        """Devuelve un diccionario con las excepciones de todos los cursos."""
        resultado = {}
        for curso, cfg in self._datos["cursos"].items():
            excepciones = cfg.get("excepciones_fecha", {})
            if excepciones:
                resultado[curso] = excepciones
        return resultado

    def eliminar_excepcion_fecha(self, curso: str, fecha: str) -> bool:
        with self._lock:
            excepciones = self._datos["cursos"].get(curso, {}).get("excepciones_fecha", {})
            if fecha in excepciones:
                del excepciones[fecha]
                self._guardar()
                logger.info("Excepción de fecha eliminada para %s en el día %s", curso, fecha)
                return True
        return False