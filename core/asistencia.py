"""
core/asistencia.py
-------------------
Versión simplificada: un único CSV con todos los presentes del día,
sin la estructura por curso pensada para CIDI (eso se retoma más
adelante). Por ahora el objetivo es solo dejar constancia de quién
fue confirmado como presente.
"""

import logging
import os
import threading
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)

COLUMNAS = ["Fecha", "Hora", "Alumno", "Curso", "Método", "Estado"]


class RegistroAsistencia:
    def __init__(self, archivo_csv: str):
        self.archivo_csv = archivo_csv
        self._lock = threading.Lock()

    def registrar_presente(self, alumno: str, curso: str, metodo: str) -> bool:
        ahora = datetime.now()
        fecha = ahora.strftime("%Y-%m-%d")
        hora = ahora.strftime("%H:%M:%S")

        fila_nueva = pd.DataFrame([{
            "Fecha": fecha, "Hora": hora, "Alumno": alumno,
            "Curso": curso, "Método": metodo, "Estado": "PRESENTE",
        }], columns=COLUMNAS)

        with self._lock:
            if not os.path.exists(self.archivo_csv):
                fila_nueva.to_csv(self.archivo_csv, index=False, sep=";")
                logger.info("Asistencia creada. Primer registro: %s (%s) vía %s", alumno, curso, metodo)
                return True

            df = pd.read_csv(self.archivo_csv, sep=";")
            if ((df["Alumno"] == alumno) & (df["Fecha"] == fecha)).any():
                logger.debug("Duplicado ignorado: %s ya tiene presente hoy", alumno)
                return False

            fila_nueva.to_csv(self.archivo_csv, mode="a", header=False, index=False, sep=";")
            logger.info("Presente registrado: %s (%s) vía %s", alumno, curso, metodo)
            return True

    def existe_archivo(self) -> bool:
        return os.path.exists(self.archivo_csv)