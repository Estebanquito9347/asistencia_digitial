"""
core/horarios.py
------------------
Configuración de horario de entrada por curso. La preceptora define,
para cada curso, a qué hora entra y cuántos minutos de tolerancia hay
antes de marcar "TARDE" en vez de "PRESENTE".

Se guarda en un JSON simple (horarios.json) — no hace falta una base
de datos para esto todavía.
"""

import json
import logging
import os
import threading
from datetime import datetime, timedelta, time as time_cls

logger = logging.getLogger(__name__)

DEFAULT_HORA_ENTRADA = "08:00"
DEFAULT_TOLERANCIA_MIN = 10


class GestorHorarios:
    def __init__(self, archivo_horarios: str):
        self.archivo_horarios = archivo_horarios
        self._lock = threading.Lock()
        self._horarios = self._cargar()

    def _cargar(self) -> dict:
        if os.path.exists(self.archivo_horarios):
            try:
                with open(self.archivo_horarios, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                logger.exception("No se pudo leer %s, se arranca con horarios vacíos", self.archivo_horarios)
        return {}

    def _guardar(self) -> None:
        try:
            with open(self.archivo_horarios, "w", encoding="utf-8") as f:
                json.dump(self._horarios, f, ensure_ascii=False, indent=2)
        except Exception:
            logger.exception("No se pudo guardar %s", self.archivo_horarios)

    def obtener_todos(self) -> dict:
        return dict(self._horarios)

    def obtener(self, curso: str) -> dict:
        return self._horarios.get(curso, {
            "hora_entrada": DEFAULT_HORA_ENTRADA,
            "tolerancia_minutos": DEFAULT_TOLERANCIA_MIN,
        })

    def establecer(self, curso: str, hora_entrada: str, tolerancia_minutos: int) -> None:
        # Validamos el formato acá para no guardar basura que después
        # rompa calcular_estado() en silencio.
        datetime.strptime(hora_entrada, "%H:%M")

        with self._lock:
            self._horarios[curso] = {
                "hora_entrada": hora_entrada,
                "tolerancia_minutos": int(tolerancia_minutos),
            }
            self._guardar()
            logger.info("Horario actualizado para %s: entra %s, tolerancia %d min",
                        curso, hora_entrada, tolerancia_minutos)

    def calcular_estado(self, curso: str, momento: datetime) -> str:
        """Devuelve 'PRESENTE' o 'TARDE' según el horario configurado del curso."""
        cfg = self.obtener(curso)
        hora_entrada = datetime.strptime(cfg["hora_entrada"], "%H:%M").time()
        limite = (
            datetime.combine(momento.date(), hora_entrada) + timedelta(minutes=cfg["tolerancia_minutos"])
        ).time()
        return "PRESENTE" if momento.time() <= limite else "TARDE"