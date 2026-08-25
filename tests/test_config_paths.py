import base64
import importlib
import io
import sys
import types
from pathlib import Path

import numpy as np
from flask import Flask

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.asistencia import RegistroAsistencia
from core.reconocimiento_facial import GestorRostros
from routes.api import create_blueprint


def test_rostros_paths_are_resolved_from_project_root(monkeypatch):
    monkeypatch.setenv("CARPETA_ROSTROS", "rostros")
    monkeypatch.setenv("ARCHIVO_MODELO_ROSTROS", "rostros_lbp.pkl")
    monkeypatch.setenv("ARCHIVO_CASCADA_ROSTROS", "haarcascade_frontalface_default.xml")

    import config
    importlib.reload(config)

    assert Path(config.Config.CARPETA_ROSTROS) == PROJECT_ROOT / "rostros"
    assert Path(config.Config.ARCHIVO_MODELO_ROSTROS) == PROJECT_ROOT / "rostros_lbp.pkl"
    assert Path(config.Config.ARCHIVO_CASCADA_ROSTROS) == PROJECT_ROOT / "haarcascade_frontalface_default.xml"


def test_buscar_en_frame_uses_small_min_size_for_face_detection(monkeypatch):
    class FakeDetector:
        def __init__(self):
            self.calls = []

        def empty(self):
            return False

        def detectMultiScale(self, img, scaleFactor, minNeighbors, minSize):
            self.calls.append((scaleFactor, minNeighbors, minSize))
            return np.array([[0, 0, 200, 200]], dtype=np.int32)

    fake_detector = FakeDetector()
    monkeypatch.setattr("cv2.CascadeClassifier", lambda *_args, **_kwargs: fake_detector)

    gestor = GestorRostros(carpeta_rostros="rostros", archivo_modelo="rostros_lbp.pkl")
    gestor.entrenado = True
    gestor.muestras = [{"hist": np.array([1.0, 1.0], dtype=np.float32), "nombre": "Ana", "curso": "1A"}]
    monkeypatch.setattr(gestor, "_extraer_histograma", lambda *_args, **_kwargs: np.array([1.0, 1.0], dtype=np.float32))

    gestor.buscar_en_frame(np.zeros((400, 400, 3), dtype=np.uint8))

    assert fake_detector.calls
    assert fake_detector.calls[0][2] == (30, 30)


def test_uses_face_recognition_embeddings_when_available(monkeypatch):
    fake_face_recognition = types.SimpleNamespace(
        face_locations=lambda image, number_of_times_to_upsample=1, model="hog": [(0, 40, 40, 0)],
        face_encodings=lambda image, known_face_locations=None, num_jitters=1, model="small": [np.array([0.1, 0.2, 0.3], dtype=np.float64)],
        face_distance=lambda encodings, comparison: np.array([0.22, 0.9], dtype=np.float64),
    )
    monkeypatch.setitem(sys.modules, "face_recognition", fake_face_recognition)

    import core.reconocimiento_facial as reconocimiento_facial
    importlib.reload(reconocimiento_facial)

    gestor = reconocimiento_facial.GestorRostros(carpeta_rostros="rostros", archivo_modelo="rostros_lbp.pkl")
    gestor.entrenado = True
    gestor.muestras = [
        {"nombre": "Ana", "curso": "1A", "embedding": np.array([0.1, 0.2, 0.3], dtype=np.float64)},
        {"nombre": "Lucas", "curso": "3B", "embedding": np.array([0.8, 0.8, 0.8], dtype=np.float64)},
    ]

    assert gestor.usar_face_recognition is True
    resultado = gestor.buscar_en_frame(np.zeros((80, 80, 3), dtype=np.uint8), curso_esperado="1A")
    assert resultado["detectado"] is True
    assert resultado["alumno"] == "Ana"
    assert resultado["curso"] == "1A"


def test_wrong_course_returns_explicit_reason(monkeypatch):
    fake_face_recognition = types.SimpleNamespace(
        face_locations=lambda image, number_of_times_to_upsample=1, model="hog": [(0, 40, 40, 0)],
        face_encodings=lambda image, known_face_locations=None, num_jitters=1, model="small": [np.array([0.1, 0.2, 0.3], dtype=np.float64)],
        face_distance=lambda encodings, comparison: np.array([0.22, 0.9], dtype=np.float64),
    )
    monkeypatch.setitem(sys.modules, "face_recognition", fake_face_recognition)

    import core.reconocimiento_facial as reconocimiento_facial
    importlib.reload(reconocimiento_facial)

    gestor = reconocimiento_facial.GestorRostros(carpeta_rostros="rostros", archivo_modelo="rostros_lbp.pkl")
    gestor.entrenado = True
    gestor.muestras = [
        {"nombre": "Ana", "curso": "1A", "embedding": np.array([0.1, 0.2, 0.3], dtype=np.float64)},
        {"nombre": "Lucas", "curso": "3B", "embedding": np.array([0.8, 0.8, 0.8], dtype=np.float64)},
    ]

    resultado = gestor.buscar_en_frame(np.zeros((80, 80, 3), dtype=np.uint8), curso_esperado="3B")
    assert resultado["detectado"] is False
    assert resultado["motivo"] == "curso_incorrecto"


def test_api_confirms_assistance_and_exposes_confidence(tmp_path):
    class DummyGestor:
        def buscar_en_frame(self, frame_bgr, curso_esperado=None):
            return {
                "detectado": True,
                "alumno": "Ana",
                "curso": "1A",
                "distancia": 0.21,
                "confianza": 0.79,
            }

    app = Flask(__name__)
    registro = RegistroAsistencia(str(tmp_path / "asistencia.csv"))
    app.register_blueprint(create_blueprint(gestor_rostros=DummyGestor(), carpeta_rostros="rostros", registro_asistencia=registro))

    frame = np.zeros((20, 20, 3), dtype=np.uint8)
    img_bytes = io.BytesIO()
    import PIL.Image
    PIL.Image.fromarray(frame).save(img_bytes, format="JPEG")
    frame_b64 = "data:image/jpeg;base64," + base64.b64encode(img_bytes.getvalue()).decode("ascii")

    client = app.test_client()
    resp = client.post("/procesar_fotograma", json={"imagen": frame_b64, "curso": "1A"})
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["detectado"] is True
    assert payload["alumno"] == "Ana"
    assert payload["confianza"] == 0.79

    confirm = client.post("/confirmar_asistencia", json={"alumno": "Ana", "curso": "1A", "metodo": "FACIAL"})
    assert confirm.status_code == 200
    assert confirm.get_json()["registrado"] is True

    download = client.get("/descargar_asistencia")
    assert download.status_code == 200
    assert b"Alumno" in download.data
