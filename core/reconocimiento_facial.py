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

try:
    import face_recognition  # type: ignore
except ImportError:  # pragma: no cover - depende del entorno
    face_recognition = None

logger = logging.getLogger(__name__)

TAMANO_ROSTRO = (200, 200)
GRILLA = (8, 8)  # divide la cara en 8x8 celdas para el histograma LBP
MIN_TAMANIO_CARA = (30, 30)  # tamaño mínimo realista para webcam/rostros pequeños


class GestorRostros:
    def __init__(self, carpeta_rostros: str, archivo_modelo: str = "rostros_lbp.pkl",
                 umbral_distancia: float = 0.45, margen_minimo: float = 0.08,
                 archivo_cascada: str = "haarcascade_frontalface_default.xml"):
        self.carpeta_rostros = self._resolver_ruta_proyecto(carpeta_rostros)
        self.archivo_modelo = self._resolver_ruta_proyecto(archivo_modelo)
        self.umbral_distancia = umbral_distancia
        self.margen_minimo = margen_minimo
        self._face_recognition = face_recognition
        self.usar_face_recognition = self._face_recognition is not None

        if self.usar_face_recognition:
            logger.info("face_recognition habilitado: comparar embeddings faciales en lugar de histograma LBP.")

        self.detector_caras = cv2.CascadeClassifier(self._resolver_ruta_cascada(archivo_cascada))
        if self.detector_caras.empty():
            raise RuntimeError(
                f"No se pudo cargar el clasificador de rostros. Revisá que '{archivo_cascada}' "
                "exista en la carpeta del proyecto (bajalo de "
                "https://raw.githubusercontent.com/opencv/opencv/master/data/haarcascades/"
                "haarcascade_frontalface_default.xml si no lo tenés)."
            )

        self.muestras = []  # [{"hist": np.ndarray, "nombre": str, "curso": str}, ...] o embedding
        self.entrenado = False

    @staticmethod
    def _resolver_ruta_proyecto(ruta: str) -> str:
        if not ruta:
            return ruta
        ruta_path = os.path.abspath(ruta)
        if os.path.isabs(ruta):
            return ruta
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        return os.path.abspath(os.path.join(base_dir, ruta))

    @staticmethod
    def _resolver_ruta_cascada(archivo_cascada: str) -> str:
        if os.path.exists(archivo_cascada):
            return archivo_cascada
        if not os.path.isabs(archivo_cascada):
            ruta_proyecto = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", archivo_cascada))
            if os.path.exists(ruta_proyecto):
                return ruta_proyecto
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
    def _seleccionar_cara_mas_grande(self, caras):
        if caras is None:
            return None
        if len(caras) == 0:
            return None
        return max(caras, key=lambda c: c[2] * c[3])

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

                img_color = cv2.imread(ruta, cv2.IMREAD_COLOR)
                if img_color is None:
                    logger.warning("No se pudo leer %s, se omite.", archivo)
                    continue

                if self.usar_face_recognition:
                    rgb = cv2.cvtColor(img_color, cv2.COLOR_BGR2RGB)
                    ubicaciones = self._face_recognition.face_locations(rgb, model="hog")
                    if not ubicaciones:
                        logger.warning("Ningún rostro detectado en %s, se omite.", archivo)
                        continue
                    cara = self._seleccionar_cara_mas_grande(ubicaciones)
                    encodings = self._face_recognition.face_encodings(
                        rgb,
                        known_face_locations=[cara],
                        num_jitters=1,
                        model="small",
                    )
                    if not encodings:
                        continue
                    self.muestras.append({"embedding": encodings[0], "nombre": nombre, "curso": curso_actual})
                    continue

                img = cv2.imread(ruta, cv2.IMREAD_GRAYSCALE)
                caras = self.detector_caras.detectMultiScale(
                    img,
                    scaleFactor=1.1,
                    minNeighbors=4,
                    minSize=MIN_TAMANIO_CARA,
                )
                if len(caras) == 0:
                    logger.warning("Ningún rostro detectado en %s, se omite.", archivo)
                    continue
                if len(caras) > 1:
                    logger.warning("%s tiene %d rostros detectados, se usa el más grande.", archivo, len(caras))
                    caras = [self._seleccionar_cara_mas_grande(caras)]

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
        metodo = "embeddings face_recognition" if self.usar_face_recognition else "LBP"
        logger.info("Entrenamiento facial (%s): %d muestras, %d alumnos únicos",
                    metodo, len(self.muestras), len(personas_unicas))

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
    def _buscar_en_frame_embeddings(self, frame_bgr: np.ndarray, curso_esperado: str = None) -> dict:
        embeddings = [m["embedding"] for m in self.muestras if "embedding" in m and m.get("embedding") is not None]
        if not embeddings:
            return {"detectado": False}

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        ubicaciones = self._face_recognition.face_locations(rgb, model="hog")
        if not ubicaciones:
            return {"detectado": False}

        cara = self._seleccionar_cara_mas_grande(ubicaciones)
        codigos = self._face_recognition.face_encodings(
            rgb,
            known_face_locations=[cara],
            num_jitters=1,
            model="small",
        )
        if not codigos:
            return {"detectado": False}

        consulta = codigos[0]
        distancias = [
            (float(dist), muestra)
            for dist, muestra in zip(self._face_recognition.face_distance(embeddings, consulta), self.muestras)
            if "embedding" in muestra and muestra.get("embedding") is not None
        ]
        if not distancias:
            return {"detectado": False}

        distancias.sort(key=lambda par: par[0])
        mejor_dist, mejor = distancias[0]
        logger.info("Cara detectada con embeddings. Mejor match: %s (%s) distancia=%.4f (umbral=%.3f)",
                    mejor["nombre"], mejor["curso"], mejor_dist, self.umbral_distancia)

        if mejor_dist > self.umbral_distancia:
            return {"detectado": False}

        for dist, muestra in distancias[1:]:
            if (muestra["nombre"], muestra["curso"]) != (mejor["nombre"], mejor["curso"]):
                if (dist - mejor_dist) < self.margen_minimo:
                    logger.warning("Match ambiguo entre %s (%.4f) y %s (%.4f), se descarta por seguridad.",
                                   mejor["nombre"], mejor_dist, muestra["nombre"], dist)
                    return {"detectado": False}
                break

        if curso_esperado is not None and mejor["curso"] != curso_esperado:
            logger.info("Reconocido %s (curso real: %s) pero el curso seleccionado es %s, se descarta.",
                        mejor["nombre"], mejor["curso"], curso_esperado)
            return {"detectado": False}

        return {"detectado": True, "alumno": mejor["nombre"], "curso": mejor["curso"], "distancia": mejor_dist}

    def buscar_en_frame(self, frame_bgr: np.ndarray, curso_esperado: str = None) -> dict:
        if not self.entrenado:
            return {"detectado": False}

        if self.usar_face_recognition:
            resultado = self._buscar_en_frame_embeddings(frame_bgr, curso_esperado)
            if resultado["detectado"] or any("embedding" in m for m in self.muestras):
                return resultado

        gris = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        caras = self.detector_caras.detectMultiScale(
            gris,
            scaleFactor=1.1,
            minNeighbors=4,
            minSize=MIN_TAMANIO_CARA,
        )
        if len(caras) == 0:
            return {"detectado": False}

        x, y, w, h = self._seleccionar_cara_mas_grande(caras)
        rostro = cv2.resize(gris[y:y + h, x:x + w], TAMANO_ROSTRO)
        hist_consulta = self._extraer_histograma(rostro)

        distancias = [
            (self._distancia_chi_cuadrado(hist_consulta, m["hist"]), m)
            for m in self.muestras
            if "hist" in m
        ]
        if not distancias:
            return {"detectado": False}

        distancias.sort(key=lambda par: par[0])

        mejor_dist, mejor = distancias[0]
        logger.info("Cara detectada. Mejor match: %s (%s) distancia=%.2f (umbral=%.1f, menor=mejor)",
                    mejor["nombre"], mejor["curso"], mejor_dist, self.umbral_distancia)

        if mejor_dist > self.umbral_distancia:
            return {"detectado": False}

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
