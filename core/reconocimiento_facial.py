"""
core/reconocimiento_facial.py
------------------------------
Reconocimiento facial con Local Binary Patterns (LBP) implementado a
mano en vez de usar cv2.face.LBPHFaceRecognizer. Dos motivos:

  1. El motor built-in de OpenCV solo devuelve el MEJOR match, sin
     acceso a los siguientes candidatos. Eso nos impedía replicar el
     chequeo de "margen anti-ambigüedad" que teníamos con dlib (si el
     2do candidato está casi tan cerca como el 1ro, se descarta el
     match en vez de forzarlo) — y esa es justo la causa más probable
     de que confunda alumnos parecidos.
  2. cv2.face viene de opencv-contrib-python, y el error de
     'haarcascade...xobjdetect' que arrastramos venía de un módulo de
     contrib con empaquetado inconsistente. Al no necesitar cv2.face,
     alcanza con opencv-python (el núcleo), más liviano y estable.

Además, esta versión:
  - Ecualiza el histograma de cada rostro (cv2.equalizeHist) antes de
    comparar. Es la corrección más efectiva contra diferencias de luz
    entre la foto de entrenamiento y el frame de la webcam — causa
    típica de confusión con LBPH.
  - Soporta MÚLTIPLES fotos por alumno de forma natural: cada foto se
    guarda como una muestra más bajo el mismo nombre+curso, no hace
    falta agruparlas a mano. Cuantas más fotos (ángulos/luz distintos)
    por alumno, mejor generaliza.

Distancia usada: chi-cuadrado entre histogramas LBP por grilla — la
métrica estándar para este tipo de comparación, MENOR = mejor match
(igual que antes).
"""

import logging
import os
import pickle

import cv2
import numpy as np

logger = logging.getLogger(__name__)

TAMANO_ROSTRO = (200, 200)
GRILLA = (8, 8)  # divide la cara en 8x8 celdas para el histograma LBP


class GestorRostros:
    def __init__(self, carpeta_rostros: str, archivo_modelo: str = "rostros_lbp.pkl",
                 umbral_distancia: float = 12.0, margen_minimo: float = 1.5,
                 archivo_cascada: str = "haarcascade_frontalface_default.xml"):
        self.carpeta_rostros = carpeta_rostros
        self.archivo_modelo = archivo_modelo
        self.umbral_distancia = umbral_distancia  # chi-cuadrado: menor = mejor match
        self.margen_minimo = margen_minimo  # diferencia mínima exigida vs. la mejor OTRA persona

        self.detector_caras = cv2.CascadeClassifier(self._resolver_ruta_cascada(archivo_cascada))
        if self.detector_caras.empty():
            raise RuntimeError(
                f"No se pudo cargar el clasificador de rostros. Revisá que '{archivo_cascada}' "
                "exista en la carpeta del proyecto (bajalo de "
                "https://raw.githubusercontent.com/opencv/opencv/master/data/haarcascades/"
                "haarcascade_frontalface_default.xml si no lo tenés)."
            )

        self.muestras = []  # [{"hist": np.ndarray, "nombre": str, "curso": str}, ...]
        self.entrenado = False

    @staticmethod
    def _resolver_ruta_cascada(archivo_cascada: str) -> str:
        if os.path.exists(archivo_cascada):
            return archivo_cascada
        ruta_paquete = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        logger.warning("No se encontró '%s' en el proyecto, se intenta con la ruta interna de OpenCV (%s).",
                        archivo_cascada, ruta_paquete)
        return ruta_paquete

    # ------------------------------------------------------------------
    # LBP: extracción de features (numpy puro, sin cv2.face)
    # ------------------------------------------------------------------
    @staticmethod
    def _lbp_codigo(img_gris: np.ndarray) -> np.ndarray:
        """LBP clásico de 8 vecinos, radio 1 (el círculo coincide exacto
        con los 8 píxeles de la ventana 3x3, sin necesidad de interpolar)."""
        centro = img_gris[1:-1, 1:-1]
        vecinos = [
            img_gris[0:-2, 0:-2], img_gris[0:-2, 1:-1], img_gris[0:-2, 2:],
            img_gris[1:-1, 2:], img_gris[2:, 2:], img_gris[2:, 1:-1],
            img_gris[2:, 0:-2], img_gris[1:-1, 0:-2],
        ]
        codigo = np.zeros_like(centro, dtype=np.uint8)
        for i, v in enumerate(vecinos):
            codigo |= ((v >= centro).astype(np.uint8) << i)
        return codigo

    def _extraer_histograma(self, rostro_gris: np.ndarray) -> np.ndarray:
        """Ecualiza, calcula LBP, y arma un histograma concatenado por
        celdas de la grilla (más discriminativo que un histograma global:
        conserva algo de información espacial de la cara).

        Cada histograma de celda se normaliza (divide por su suma) antes
        de concatenar — sin esto, la distancia chi-cuadrado queda en una
        escala dominada por el conteo de píxeles de cada celda en vez de
        la FORMA de la distribución, haciendo inútil cualquier umbral fijo."""
        rostro_eq = cv2.equalizeHist(rostro_gris)
        codigos = self._lbp_codigo(rostro_eq)

        alto, ancho = codigos.shape
        filas, columnas = GRILLA
        celda_h, celda_w = alto // filas, ancho // columnas

        histogramas = []
        for i in range(filas):
            for j in range(columnas):
                celda = codigos[i * celda_h:(i + 1) * celda_h, j * celda_w:(j + 1) * celda_w]
                hist, _ = np.histogram(celda, bins=256, range=(0, 256))
                hist = hist.astype(np.float32)
                hist /= (hist.sum() + 1e-7)  # normalizar: cada celda queda como distribución de probabilidad
                histogramas.append(hist)
        return np.concatenate(histogramas)

    @staticmethod
    def _distancia_chi_cuadrado(h1: np.ndarray, h2: np.ndarray, eps: float = 1e-10) -> float:
        return float(0.5 * np.sum(((h1 - h2) ** 2) / (h1 + h2 + eps)))

    # ------------------------------------------------------------------
    # Entrenamiento
    # ------------------------------------------------------------------
    def entrenar(self, forzar: bool = False) -> None:
        if not forzar and self._cargar_modelo():
            return

        self.muestras = []

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
                hist = self._extraer_histograma(rostro)

                self.muestras.append({"hist": hist, "nombre": nombre, "curso": curso_actual})

        if not self.muestras:
            logger.error("No se pudo entrenar: ningún rostro válido encontrado en %s", self.carpeta_rostros)
            self.entrenado = False
            return

        self.entrenado = True
        self._guardar_modelo()

        personas_unicas = {(m["nombre"], m["curso"]) for m in self.muestras}
        logger.info("Entrenamiento facial (LBP): %d muestras, %d alumnos únicos",
                    len(self.muestras), len(personas_unicas))

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------
    def _guardar_modelo(self) -> None:
        try:
            with open(self.archivo_modelo, "wb") as f:
                pickle.dump(self.muestras, f)
        except Exception:
            logger.exception("No se pudo guardar el modelo facial en cache")

    def _cargar_modelo(self) -> bool:
        if not os.path.exists(self.archivo_modelo):
            return False
        try:
            with open(self.archivo_modelo, "rb") as f:
                self.muestras = pickle.load(f)
            self.entrenado = bool(self.muestras)
            logger.info("Modelo facial cargado desde cache (%d muestras)", len(self.muestras))
            return self.entrenado
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

        x, y, w, h = max(caras, key=lambda c: c[2] * c[3])
        rostro = cv2.resize(gris[y:y + h, x:x + w], TAMANO_ROSTRO)
        hist_consulta = self._extraer_histograma(rostro)

        # Distancia contra CADA muestra guardada (todas las fotos de todos los alumnos)
        distancias = [
            (self._distancia_chi_cuadrado(hist_consulta, m["hist"]), m)
            for m in self.muestras
        ]
        distancias.sort(key=lambda par: par[0])

        mejor_dist, mejor = distancias[0]
        logger.info("Cara detectada. Mejor match: %s (%s) distancia=%.2f (umbral=%.1f, menor=mejor)",
                    mejor["nombre"], mejor["curso"], mejor_dist, self.umbral_distancia)

        if mejor_dist > self.umbral_distancia:
            return {"detectado": False}

        # Margen anti-ambigüedad: comparar contra la mejor distancia de una
        # persona DISTINTA (no simplemente el 2do lugar — si el alumno tiene
        # varias fotos propias, esas ocupan los primeros puestos sin ser
        # ambigüedad real).
        for dist, m in distancias[1:]:
            if (m["nombre"], m["curso"]) != (mejor["nombre"], mejor["curso"]):
                if (dist - mejor_dist) < self.margen_minimo:
                    logger.warning("Match ambiguo entre %s (%.2f) y %s (%.2f), se descarta por seguridad.",
                                   mejor["nombre"], mejor_dist, m["nombre"], dist)
                    return {"detectado": False}
                break

        if curso_esperado is not None and mejor["curso"] != curso_esperado:
            logger.info("Reconocido %s (curso real: %s) pero el curso seleccionado es %s, se descarta.",
                        mejor["nombre"], mejor["curso"], curso_esperado)
            return {"detectado": False}

        return {"detectado": True, "alumno": mejor["nombre"], "curso": mejor["curso"], "distancia": mejor_dist}
