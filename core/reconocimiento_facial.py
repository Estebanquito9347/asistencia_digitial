"""
core/reconocimiento_facial.py
------------------------------
Reconocimiento facial con OpenCV (LBPHFaceRecognizer) en vez de
dlib/face_recognition. Se instala con opencv-contrib-python, sin
compilación ni Visual Studio Build Tools de por medio en Windows.

Trade-off consciente: LBPH es menos preciso que el encoding de dlib
(más sensible a luz/ángulo). Se compensa con el paso de confirmación
manual ("¿sos vos?") que ya tiene el frontend — el reconocimiento acá
solo necesita acercar un candidato, no decidir solo.

LBPH devuelve una "confianza" que es una distancia: CUANTO MÁS BAJA,
mejor el match (0 = idéntico). Es lo opuesto a un puntaje de similitud.
"""

import logging
import os
import pickle

import cv2
import numpy as np

logger = logging.getLogger(__name__)

TAMANO_ROSTRO = (200, 200)


class GestorRostros:
    def __init__(self, carpeta_rostros: str, archivo_modelo: str = "rostros_lbph.yml",
                 archivo_etiquetas: str = "rostros_etiquetas.pkl", umbral_confianza: float = 70.0):
        self.carpeta_rostros = carpeta_rostros
        self.archivo_modelo = archivo_modelo
        self.archivo_etiquetas = archivo_etiquetas
        self.umbral_confianza = umbral_confianza  # LBPH: menor = mejor match

        self.detector_caras = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        self.recognizer = cv2.face.LBPHFaceRecognizer_create()
        self.etiqueta_a_alumno = {}  # int label -> {"nombre":.., "curso":..}
        self.entrenado = False

    # ------------------------------------------------------------------
    # Entrenamiento
    # ------------------------------------------------------------------
    def entrenar(self, forzar: bool = False) -> None:
        if not forzar and self._cargar_modelo():
            return

        rostros, etiquetas = [], []
        self.etiqueta_a_alumno = {}
        siguiente_label = 0

        if not os.path.exists(self.carpeta_rostros):
            logger.error("No se encuentra la carpeta de rostros: %s", self.carpeta_rostros)
            return

        for raiz, _dirs, archivos in os.walk(self.carpeta_rostros):
            curso_actual = os.path.basename(raiz)
            if curso_actual == os.path.basename(self.carpeta_rostros.rstrip("/")):
                continue

            for archivo in archivos:
                if not archivo.lower().endswith((".jpg", ".png", ".jpeg")):
                    continue

                ruta = os.path.join(raiz, archivo)
                nombre = os.path.splitext(archivo)[0].replace("_", " ").replace("-", " ").strip().title()

                img = cv2.imread(ruta, cv2.IMREAD_GRAYSCALE)
                if img is None:
                    logger.warning("No se pudo leer %s, se omite.", archivo)
                    continue

                caras = self.detector_caras.detectMultiScale(img, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
                if len(caras) == 0:
                    logger.warning("Ningún rostro detectado en %s, se omite.", archivo)
                    continue
                if len(caras) > 1:
                    logger.warning("%s tiene %d rostros detectados, se usa el más grande.", archivo, len(caras))
                    caras = [max(caras, key=lambda c: c[2] * c[3])]

                x, y, w, h = caras[0]
                rostro = cv2.resize(img[y:y + h, x:x + w], TAMANO_ROSTRO)

                label = siguiente_label
                self.etiqueta_a_alumno[label] = {"nombre": nombre, "curso": curso_actual}
                rostros.append(rostro)
                etiquetas.append(label)
                siguiente_label += 1

        if not rostros:
            logger.error("No se pudo entrenar: ningún rostro válido encontrado en %s", self.carpeta_rostros)
            self.entrenado = False
            return

        self.recognizer.train(rostros, np.array(etiquetas))
        self.entrenado = True
        self._guardar_modelo()
        logger.info("Entrenamiento facial (OpenCV LBPH): %d alumnos cargados", len(self.etiqueta_a_alumno))

    # ------------------------------------------------------------------
    # Cache del modelo entrenado (evita reprocesar todas las fotos en cada reinicio)
    # ------------------------------------------------------------------
    def _guardar_modelo(self) -> None:
        try:
            self.recognizer.save(self.archivo_modelo)
            with open(self.archivo_etiquetas, "wb") as f:
                pickle.dump(self.etiqueta_a_alumno, f)
        except Exception:
            logger.exception("No se pudo guardar el modelo facial en cache")

    def _cargar_modelo(self) -> bool:
        if not (os.path.exists(self.archivo_modelo) and os.path.exists(self.archivo_etiquetas)):
            return False
        try:
            self.recognizer.read(self.archivo_modelo)
            with open(self.archivo_etiquetas, "rb") as f:
                self.etiqueta_a_alumno = pickle.load(f)
            self.entrenado = True
            logger.info("Modelo facial cargado desde cache (%d alumnos)", len(self.etiqueta_a_alumno))
            return True
        except Exception:
            logger.exception("No se pudo cargar el modelo facial cacheado, se reentrena desde cero")
            return False

    # ------------------------------------------------------------------
    # Búsqueda sobre un frame de cámara
    # ------------------------------------------------------------------
    def buscar_en_frame(self, frame_bgr: np.ndarray, curso_esperado: str = None) -> dict:
        if not self.entrenado:
            return {"detectado": False}

        gris = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        caras = self.detector_caras.detectMultiScale(gris, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80))
        if len(caras) == 0:
            return {"detectado": False}

        # La cara más grande = la persona más cerca de la cámara
        x, y, w, h = max(caras, key=lambda c: c[2] * c[3])
        rostro = cv2.resize(gris[y:y + h, x:x + w], TAMANO_ROSTRO)

        label, confianza = self.recognizer.predict(rostro)
        logger.info("Cara detectada. Mejor match: label=%s confianza=%.1f (umbral=%.1f, menor=mejor)",
                    label, confianza, self.umbral_confianza)

        if confianza > self.umbral_confianza:
            return {"detectado": False}

        datos = self.etiqueta_a_alumno.get(label)
        if not datos:
            return {"detectado": False}

        if curso_esperado is not None and datos["curso"] != curso_esperado:
            logger.info("Reconocido %s (curso real: %s) pero el curso seleccionado es %s, se descarta.",
                        datos["nombre"], datos["curso"], curso_esperado)
            return {"detectado": False}

        return {"detectado": True, "alumno": datos["nombre"], "curso": datos["curso"], "confianza": float(confianza)}