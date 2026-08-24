"""
escritorio.py
--------------
Versión de escritorio del portal: arranca el mismo Flask de siempre
(create_app() de app.py, sin tocar nada de esa lógica) en un hilo de
fondo, y lo muestra en una ventana nativa con pywebview en vez de
requerir que la preceptora abra un navegador y tipee localhost:8000.

Esto es lo que se empaqueta como ejecutable con PyInstaller (ver
instrucciones al final de este archivo).

Requiere: pip install pywebview
"""

import threading
import time

import webview

from app import create_app
from config import Config


def _levantar_servidor():
    app = create_app()
    # use_reloader=False es clave: el reloader de Flask intenta relanzar
    # el proceso completo, lo cual no tiene sentido corriendo dentro de
    # un ejecutable empaquetado ni en un hilo secundario.
    app.run(host="127.0.0.1", port=Config.PORT, debug=False, use_reloader=False)


def main():
    hilo_servidor = threading.Thread(target=_levantar_servidor, daemon=True)
    hilo_servidor.start()

    # Pequeño margen para que Flask termine de levantar (entrenar rostros,
    # etc.) antes de que la ventana intente cargar la página.
    time.sleep(1.5)

    webview.create_window(
        "Sistema Biométrico Escolar",
        f"http://127.0.0.1:{Config.PORT}",
        width=1280,
        height=800,
        min_size=(1000, 700),
    )
    webview.start()


if __name__ == "__main__":
    main()

# ----------------------------------------------------------------------
# Cómo empaquetarlo como ejecutable (Linux):
#
#   pip install pyinstaller
#   pyinstaller --name asistencia-escolar \
#       --add-data "templates:templates" \
#       --add-data "static:static" \
#       --hidden-import=engineio.async_drivers.threading \
#       escritorio.py
#
# El ejecutable queda en dist/asistencia-escolar/asistencia-escolar.
# Las carpetas rostros/, asistencia/, y los archivos de config
# (rostros_cache.pkl, huellas_mapping.json) se siguen leyendo/escribiendo
# relativos al directorio desde donde se ejecuta el binario — conviene
# correrlo siempre parado en ~/reconocimiento_de_cara/, o fijar rutas
# absolutas vía las variables de entorno de config.py.
# ----------------------------------------------------------------------