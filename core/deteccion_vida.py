"""
core/deteccion_vida.py
------------------------
Chequeo de "vida" antes de confirmar una asistencia por cámara: en vez
de solo hacer clic en "sí, soy yo", se le pide al alumno una acción
concreta -abrir la boca o mostrar la palma de la mano- que una foto
impresa o la pantalla de un celular no puede reproducir en el momento.

Nota técnica: usa la API nueva de MediaPipe Tasks (HandLandmarker) y
no la vieja `mp.solutions.hands`, porque Google discontinuó esa API
legacy a partir de mediapipe 0.10.31 (con 1.0.1 ya no existe más).

Requiere:
    pip install mediapipe

Y el modelo de manos descargado una sola vez (no viene con el pip
install, hay que bajarlo aparte):
    wget -O hand_landmarker.task \
      https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
"""

import logging
import os
import random

import face_recognition
import numpy as np
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions, RunningMode

logger = logging.getLogger(__name__)

DESAFIOS = [
    {"tipo": "mueca", "instruccion": "Abrí la boca bien grande 😮"},
    {"tipo": "mano", "instruccion": "Mostrá la palma de tu mano abierta ✋"},
]

# Modelo de mano de 21 puntos: punta de cada dedo y su articulación media
# (PIP). Si la punta está más arriba que el PIP, el dedo está extendido.
# Estos índices no cambiaron entre la API vieja y la nueva.
PUNTAS_DEDOS = [8, 12, 16, 20]   # índice, medio, anular, meñique
PIPS_DEDOS = [6, 10, 14, 18]


class DetectorVida:
    def __init__(self, umbral_boca: float = 0.45, dedos_minimos: int = 3,
                 ruta_modelo_mano: str = "hand_landmarker.task"):
        self.umbral_boca = umbral_boca
        self.dedos_minimos = dedos_minimos
        self.ruta_modelo_mano = ruta_modelo_mano
        # Carga perezosa: el modelo de manos es la parte más pesada en RAM
        # de todo el arranque (mediapipe + TFLite runtime). Si lo cargamos
        # acá en __init__, un arranque con poca memoria libre puede morir
        # ANTES de que el resto del sistema (cámara, reconocimiento facial)
        # llegue a levantar. Difiriéndolo, el server arranca igual y recién
        # se paga ese costo la primera vez que alguien saca el desafío "mano".
        self._detector_manos = None
        self._intento_carga_fallido = False

    def _obtener_detector_manos(self):
        if self._detector_manos is not None or self._intento_carga_fallido:
            return self._detector_manos

        if not os.path.exists(self.ruta_modelo_mano):
            logger.warning(
                "No se encontró el modelo de manos en '%s'. El desafío 'mano' va a fallar siempre "
                "hasta que lo descargues (ver docstring de core/deteccion_vida.py).", self.ruta_modelo_mano
            )
            self._intento_carga_fallido = True
            return None

        try:
            opciones = HandLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=self.ruta_modelo_mano),
                running_mode=RunningMode.IMAGE,
                num_hands=1,
                min_hand_detection_confidence=0.5,
            )
            self._detector_manos = HandLandmarker.create_from_options(opciones)
            logger.info("Modelo de manos cargado bajo demanda desde %s", self.ruta_modelo_mano)
        except Exception:
            logger.exception("No se pudo inicializar el detector de manos de MediaPipe")
            self._intento_carga_fallido = True

        return self._detector_manos

    def elegir_desafio(self) -> dict:
        # Sin cargar el modelo todavía: si el archivo ni siquiera existe en
        # disco, no ofrecemos ese desafío. Si existe pero falla al cargar,
        # eso se descubre recién en el primer intento real (ver verificar()).
        opciones = DESAFIOS if os.path.exists(self.ruta_modelo_mano) else [d for d in DESAFIOS if d["tipo"] != "mano"]
        return random.choice(opciones)

    def verificar(self, tipo: str, rgb_frame: np.ndarray) -> bool:
        if tipo == "mueca":
            return self._boca_abierta(rgb_frame)
        if tipo == "mano":
            return self._mano_abierta(rgb_frame)
        logger.warning("Tipo de desafío desconocido: %s", tipo)
        return False

    # ------------------------------------------------------------------
    def _boca_abierta(self, rgb_frame: np.ndarray) -> bool:
        landmarks_por_cara = face_recognition.face_landmarks(rgb_frame)
        if not landmarks_por_cara:
            return False

        landmarks = landmarks_por_cara[0]
        top_lip = landmarks.get("top_lip")
        bottom_lip = landmarks.get("bottom_lip")
        if not top_lip or not bottom_lip:
            return False

        interior_sup = np.array(top_lip[9])
        interior_inf = np.array(bottom_lip[9])
        apertura = np.linalg.norm(interior_sup - interior_inf)

        ancho_boca = np.linalg.norm(np.array(top_lip[0]) - np.array(top_lip[6]))
        if ancho_boca == 0:
            return False

        ratio = apertura / ancho_boca
        logger.debug("Apertura de boca: ratio=%.3f (umbral=%.2f)", ratio, self.umbral_boca)
        return ratio > self.umbral_boca

    def _mano_abierta(self, rgb_frame: np.ndarray) -> bool:
        detector = self._obtener_detector_manos()
        if detector is None:
            return False

        imagen_mp = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        resultado = detector.detect(imagen_mp)

        if not resultado.hand_landmarks:
            return False

        puntos = resultado.hand_landmarks[0]  # lista de 21 landmarks normalizados
        dedos_extendidos = sum(
            1 for punta, pip in zip(PUNTAS_DEDOS, PIPS_DEDOS)
            if puntos[punta].y < puntos[pip].y
        )
        logger.debug("Dedos extendidos detectados: %d/4", dedos_extendidos)
        return dedos_extendidos >= self.dedos_minimos