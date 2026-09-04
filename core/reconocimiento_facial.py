"""
core/reconocimiento_facial.py
------------------------------
dlib/face_recognition, con cache en disco, margen anti-ambigüedad y
detección con downscale.
"""

import logging
import os
import pickle

import face_recognition
import numpy as np

logger = logging.getLogger(__name__)


class GestorRostros:
    def __init__(self, carpeta_rostros: str, archivo_cache: str = "rostros_cache.pkl",
                 tolerancia: float = 0.5, margen_minimo: float = 0.04,
                 escala_deteccion: float = 0.5):
        self.carpeta_rostros = carpeta_rostros
        self.archivo_cache = archivo_cache
        self.tolerancia = tolerancia
        self.margen_minimo = margen_minimo
        self.escala_deteccion = escala_deteccion

        self.rostros_codificados: list = []
        self.nombres_rostros: list = []
        self.cursos_rostros: list = []

        self._cache: dict = {}

    def entrenar(self, forzar: bool = False) -> None:
        self._cache = {} if forzar else self._cargar_cache()

        self.rostros_codificados.clear()
        self.nombres_rostros.clear()
        self.cursos_rostros.clear()

        if not os.path.exists(self.carpeta_rostros):
            logger.error("No se encuentra la carpeta de rostros: %s", self.carpeta_rostros)
            return

        nuevos, reutilizados, fallidos = 0, 0, 0
        rutas_vistas = set()

        for raiz, _dirs, archivos in os.walk(self.carpeta_rostros):
            curso_actual = os.path.basename(raiz)
            if curso_actual == os.path.basename(self.carpeta_rostros.rstrip("/")):
                continue

            for archivo in archivos:
                if not archivo.lower().endswith((".jpg", ".png", ".jpeg")):
                    continue

                ruta = os.path.abspath(os.path.join(raiz, archivo))
                rutas_vistas.add(ruta)
                mtime_actual = os.path.getmtime(ruta)

                cacheado = self._cache.get(ruta)
                if cacheado and cacheado["mtime"] == mtime_actual:
                    self._agregar(cacheado["encoding"], cacheado["nombre"], cacheado["curso"])
                    reutilizados += 1
                    continue

                nombre_limpio = os.path.splitext(archivo)[0].replace("_", " ").replace("-", " ").strip().title()

                try:
                    encoding = self._codificar_imagen(ruta)
                    if encoding is None:
                        fallidos += 1
                        continue

                    self._agregar(encoding, nombre_limpio, curso_actual)
                    self._cache[ruta] = {
                        "mtime": mtime_actual, "encoding": encoding,
                        "nombre": nombre_limpio, "curso": curso_actual,
                    }
                    nuevos += 1
                except Exception:
                    logger.exception("Error al procesar %s", archivo)
                    fallidos += 1

        self._cache = {r: v for r, v in self._cache.items() if r in rutas_vistas}
        self._guardar_cache()

        logger.info("Entrenamiento facial: %d alumnos (%d nuevos/modificados, %d desde cache, %d con error)",
                    len(self.nombres_rostros), nuevos, reutilizados, fallidos)

    def _agregar(self, encoding, nombre, curso):
        self.rostros_codificados.append(encoding)
        self.nombres_rostros.append(nombre)
        self.cursos_rostros.append(curso)

    def _codificar_imagen(self, ruta: str):
        img = face_recognition.load_image_file(ruta)
        ubicaciones = face_recognition.face_locations(img)

        if not ubicaciones:
            logger.warning("Ningún rostro detectado en %s, se omite.", os.path.basename(ruta))
            return None

        if len(ubicaciones) > 1:
            logger.warning("%s tiene %d rostros detectados, se usa el más grande.",
                          os.path.basename(ruta), len(ubicaciones))
            ubicaciones = [max(ubicaciones, key=self._area_rostro)]

        encodings = face_recognition.face_encodings(img, known_face_locations=ubicaciones)
        return encodings[0] if encodings else None

    @staticmethod
    def _area_rostro(ubicacion):
        top, right, bottom, left = ubicacion
        return (right - left) * (bottom - top)

    def _cargar_cache(self) -> dict:
        if os.path.exists(self.archivo_cache):
            try:
                with open(self.archivo_cache, "rb") as f:
                    return pickle.load(f)
            except Exception:
                logger.exception("No se pudo leer el cache de rostros, se reconstruye desde cero.")
        return {}

    def _guardar_cache(self) -> None:
        try:
            with open(self.archivo_cache, "wb") as f:
                pickle.dump(self._cache, f)
        except Exception:
            logger.exception("No se pudo guardar el cache de rostros.")

    def alumnos_de_curso(self, curso: str) -> list:
        """Nombres únicos de alumnos entrenados para ese curso (deduplicado,
        por si hay más de una foto por alumno). Sirve para saber el total
        del curso y poder calcular quiénes faltan en el panel en vivo."""
        return sorted({
            nombre for nombre, c in zip(self.nombres_rostros, self.cursos_rostros)
            if c == curso
        })

    def buscar_en_frame(self, rgb_frame: np.ndarray, curso_esperado: str = None) -> dict:
        if not self.rostros_codificados:
            return {"detectado": False}

        paso = max(int(1 / self.escala_deteccion), 1)
        frame_chico = np.ascontiguousarray(rgb_frame[::paso, ::paso]) if paso > 1 else rgb_frame

        ubicaciones_chicas = face_recognition.face_locations(frame_chico)
        if not ubicaciones_chicas:
            return {"detectado": False}

        ubicaciones_originales = [
            (top * paso, right * paso, bottom * paso, left * paso)
            for (top, right, bottom, left) in ubicaciones_chicas
        ]

        codificaciones = face_recognition.face_encodings(rgb_frame, known_face_locations=ubicaciones_originales)

        for cara_codificada in codificaciones:
            distancias = face_recognition.face_distance(self.rostros_codificados, cara_codificada)
            if len(distancias) == 0:
                continue

            orden = np.argsort(distancias)
            idx_mejor = orden[0]
            mejor_distancia = distancias[idx_mejor]

            if mejor_distancia > self.tolerancia:
                logger.info("Sin match: más cercano es %s a distancia %.3f (tolerancia %.2f)",
                            self.nombres_rostros[idx_mejor], mejor_distancia, self.tolerancia)
                continue

            if len(orden) > 1:
                segunda_distancia = distancias[orden[1]]
                if (segunda_distancia - mejor_distancia) < self.margen_minimo:
                    logger.warning("Match ambiguo entre %s (%.3f) y %s (%.3f), se descarta por seguridad.",
                                  self.nombres_rostros[idx_mejor], mejor_distancia,
                                  self.nombres_rostros[orden[1]], segunda_distancia)
                    continue

            nombre_det = self.nombres_rostros[idx_mejor]
            curso_det = self.cursos_rostros[idx_mejor]

            if curso_esperado is not None and curso_det != curso_esperado:
                logger.info("Reconocido %s (curso real: %s) pero el curso seleccionado es %s, se descarta.",
                            nombre_det, curso_det, curso_esperado)
                continue

            logger.info("MATCH: %s (%s) a distancia %.3f", nombre_det, curso_det, mejor_distancia)
            return {
                "detectado": True, "alumno": nombre_det, "curso": curso_det,
                "distancia": float(mejor_distancia),
            }

        return {"detectado": False}