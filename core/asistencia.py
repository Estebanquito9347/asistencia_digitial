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

El "Estado" (PRESENTE/TARDE) lo calcula quien llama (routes/api.py,
usando GestorHorarios) — este módulo solo persiste.
"""

import logging
import os
import threading
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)

COLUMNAS = ["Fecha", "Hora", "Alumno", "Curso", "Estado"]


class RegistroAsistencia:
    def __init__(self, carpeta_asistencia: str):
        self.carpeta_asistencia = carpeta_asistencia
        self._lock = threading.Lock()

    def _ruta_archivo(self, curso: str, fecha: str) -> str:
        carpeta_curso = os.path.join(self.carpeta_asistencia, curso)
        os.makedirs(carpeta_curso, exist_ok=True)
        return os.path.join(carpeta_curso, f"{fecha}.csv")

    def registrar_presente(self, alumno: str, curso: str, estado: str) -> bool:
        ahora = datetime.now()
        fecha = ahora.strftime("%Y-%m-%d")
        hora = ahora.strftime("%H:%M:%S")
        ruta = self._ruta_archivo(curso, fecha)

        fila_nueva = pd.DataFrame([{
            "Fecha": fecha, "Hora": hora, "Alumno": alumno, "Curso": curso, "Estado": estado,
        }], columns=COLUMNAS)

        with self._lock:
            if not os.path.exists(ruta):
                fila_nueva.to_csv(ruta, index=False, sep=";")
                logger.info("Asistencia creada para %s. Primer registro: %s - %s", curso, alumno, estado)
                return True

            df = pd.read_csv(ruta, sep=";")
            if (df["Alumno"] == alumno).any():
                logger.debug("Duplicado ignorado: %s ya tiene registro hoy en %s", alumno, curso)
                return False

            fila_nueva.to_csv(ruta, mode="a", header=False, index=False, sep=";")
            logger.info("Registrado: %s (%s) - %s", alumno, curso, estado)
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
        """Si curso es None, junta los registros de HOY de todos los cursos."""
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
        """Cantidad de presentes por curso, para un vistazo rápido en el panel."""
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