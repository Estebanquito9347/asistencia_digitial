"""
core/asistencia.py
-------------------
Un CSV con todos los presentes del día. El "Estado" (PRESENTE/TARDE)
lo calcula quien llama (ver routes/api.py), usando GestorHorarios —
este módulo solo persiste, no decide reglas de horario.
"""

import logging
import os
import threading
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)

COLUMNAS = ["Fecha", "Hora", "Alumno", "Curso", "Estado"]


class RegistroAsistencia:
    def __init__(self, archivo_csv: str):
        self.archivo_csv = archivo_csv
        self._lock = threading.Lock()

    def registrar_presente(self, alumno: str, curso: str, estado: str) -> bool:
        ahora = datetime.now()
        fecha = ahora.strftime("%Y-%m-%d")
        hora = ahora.strftime("%H:%M:%S")

        fila_nueva = pd.DataFrame([{
            "Fecha": fecha, "Hora": hora, "Alumno": alumno, "Curso": curso, "Estado": estado,
        }], columns=COLUMNAS)

        with self._lock:
            if not os.path.exists(self.archivo_csv):
                fila_nueva.to_csv(self.archivo_csv, index=False, sep=";")
                logger.info("Asistencia creada. Primer registro: %s (%s) - %s", alumno, curso, estado)
                return True

            df = pd.read_csv(self.archivo_csv, sep=";")
            if ((df["Alumno"] == alumno) & (df["Fecha"] == fecha)).any():
                logger.debug("Duplicado ignorado: %s ya tiene registro hoy", alumno)
                return False

            fila_nueva.to_csv(self.archivo_csv, mode="a", header=False, index=False, sep=";")
            logger.info("Registrado: %s (%s) - %s", alumno, curso, estado)
            return True

    def registros_de_hoy(self) -> list:
        if not os.path.exists(self.archivo_csv):
            return []
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        df = pd.read_csv(self.archivo_csv, sep=";")
        df_hoy = df[df["Fecha"] == fecha_hoy].sort_values("Hora", ascending=False)
        return df_hoy.to_dict(orient="records")

    def existe_archivo(self) -> bool:
        return os.path.exists(self.archivo_csv)