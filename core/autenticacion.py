"""
core/autenticacion.py
-----------------------
Protección simple por PIN para /admin. No es un sistema de usuarios
completo (no hace falta para una sola preceptora por PC), pero evita
que cualquiera que llegue al kiosco de los alumnos pueda tocar
horarios o ver el panel de registros con un clic.
"""

from functools import wraps

from flask import redirect, session, url_for


def requiere_admin(vista):
    @wraps(vista)
    def envoltorio(*args, **kwargs):
        if not session.get("admin_autenticado"):
            return redirect(url_for("api.login"))
        return vista(*args, **kwargs)
    return envoltorio