"""
core/asistencia.py
-------------------
Guarda la asistencia organizada por curso:

    asistencia/
    ├── 1A/
    │   ├── 2026-08-26.csv
    │   └── 2026-08-27.csv
    ├── 1B/
    │   └── 2026-08-26.csv
    └── ...

El "Estado" (PRESENTE/TARDE) y el "Turno" los calcula quien llama
(routes/api.py, usando GestorHorarios) — este módulo solo persiste.

`registrar_presente` acepta un `momento` opcional: la cámara lo deja
en None (usa "ahora"), pero la sincronización del lector de huella en
red SÍ lo pasa explícito — las marcaciones que baja el dispositivo
ya pasaron antes, no en el instante de sincronizar, y hay que guardar
la hora real de la fichada, no la de la sincronización.
"""

import logging
import os
import threading
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)

COLUMNAS = ["Fecha", "Hora", "Alumno", "Curso", "Turno", "Estado"]


class RegistroAsistencia:
    def __init__(self, carpeta_asistencia: str):
        self.carpeta_asistencia = carpeta_asistencia
        self._lock = threading.Lock()

    def _ruta_archivo(self, curso: str, fecha: str) -> str:
        carpeta_curso = os.path.join(self.carpeta_asistencia, curso)
        os.makedirs(carpeta_curso, exist_ok=True)
        return os.path.join(carpeta_curso, f"{fecha}.csv")

    def registrar_presente(self, alumno: str, curso: str, turno: str, estado: str,
                            momento: datetime = None) -> bool:
        momento = momento or datetime.now()
        fecha = momento.strftime("%Y-%m-%d")
        hora = momento.strftime("%H:%M:%S")
        ruta = self._ruta_archivo(curso, fecha)

        fila_nueva = pd.DataFrame([{
            "Fecha": fecha, "Hora": hora, "Alumno": alumno, "Curso": curso, "Turno": turno, "Estado": estado,
        }], columns=COLUMNAS)

        with self._lock:
            if not os.path.exists(ruta):
                fila_nueva.to_csv(ruta, index=False, sep=";")
                logger.info("Asistencia creada para %s. Primer registro: %s - %s (%s)", curso, alumno, estado, turno)
                return True

            df = pd.read_csv(ruta, sep=";")
            # Duplicado por (Alumno, Turno): un alumno puede tener DOS
            # registros legítimos el mismo día si el curso tiene turno
            # y contraturno.
            if ((df["Alumno"] == alumno) & (df["Turno"] == turno)).any():
                logger.debug("Duplicado ignorado: %s ya tiene registro hoy en %s (%s)", alumno, curso, turno)
                return False

            fila_nueva.to_csv(ruta, mode="a", header=False, index=False, sep=";")
            logger.info("Registrado: %s (%s) - %s (%s)", alumno, curso, estado, turno)
            return True

    def ruta_para(self, curso: str, fecha: str):
        ruta = os.path.join(self.carpeta_asistencia, curso, f"{fecha}.csv")
        return ruta if os.path.exists(ruta) else None

    def _listar_cursos_con_carpeta(self) -> list:
        if not os.path.exists(self.carpeta_asistencia):
            return []
        return [d for d in os.listdir(self.carpeta_asistencia)
                if os.path.isdir(os.path.join(self.carpeta_asistencia, d))]

    def registros_de_hoy(self, curso: str = None) -> list:
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        cursos = [curso] if curso else self._listar_cursos_con_carpeta()

        registros = []
        for c in cursos:
            ruta = self.ruta_para(c, fecha_hoy)
            if not ruta:
                continue
            try:
                df = pd.read_csv(ruta, sep=";")
                registros.extend(df.to_dict(orient="records"))
            except Exception:
                logger.exception("No se pudo leer %s", ruta)

        registros.sort(key=lambda r: r.get("Hora", ""), reverse=True)
        return registros

    def resumen_del_dia(self) -> list:
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        resultado = []

        for curso in sorted(self._listar_cursos_con_carpeta()):
            ruta = self.ruta_para(curso, fecha_hoy)
            cantidad = 0
            if ruta:
                try:
                    cantidad = len(pd.read_csv(ruta, sep=";"))
                except Exception:
                    logger.exception("No se pudo leer %s", ruta)
            resultado.append({"curso": curso, "presentes": cantidad})

        return resultado