"""
core/horarios.py
------------------
Configuración de horario de entrada por curso. Además del horario
habitual, se pueden guardar cambios puntuales por fecha (por ejemplo,
si una docente falta y un curso entra más tarde).

Se guarda en un JSON simple (horarios.json) — no hace falta una base
de datos para esto todavía.

Los contraturnos pueden marcarse como "permanente": true para que no 
puedan ser editados ni eliminados desde la interfaz.

Sincronización NTP:
- Se sincroniza automáticamente con un servidor NTP al iniciar
- Asegura que la hora sea precisa incluso en sistemas sin reloj exacto
"""

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta, time as time_cls
import socket

logger = logging.getLogger(__name__)

DEFAULT_HORA_ENTRADA_MANANA = "07:20"
DEFAULT_HORA_ENTRADA_TARDE = "13:20"
DEFAULT_TOLERANCIA_MIN = 10

# Servidores NTP públicos
SERVIDORES_NTP = [
    "pool.ntp.org",
    "time.nist.gov",
    "time.google.com",
]


def obtener_hora_ntp() -> datetime:
    """
    Obtiene la hora actual desde un servidor NTP.
    Si falla, devuelve la hora local del sistema.
    """
    import struct
    
    for servidor in SERVIDORES_NTP:
        try:
            cliente = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            cliente.settimeout(2)
            
            # Datos NTP: versión 3, modo cliente
            datos = b'\x1b' + (47 * b'\0')
            cliente.sendto(datos, (servidor, 123))
            
            respuesta, _ = cliente.recvfrom(1024)
            cliente.close()
            
            # Parsear respuesta NTP (timestamp en segundos desde 1900)
            timestamp = struct.unpack('!12I', respuesta)[10]
            # Convertir a época Unix (resta 70 años)
            timestamp_unix = timestamp - 2208988800
            return datetime.fromtimestamp(timestamp_unix)
            
        except Exception as e:
            logger.warning(f"No se pudo obtener hora de {servidor}: {e}")
            continue
    
    logger.warning("No se pudo sincronizar con NTP, usando hora del sistema")
    return datetime.now()


class GestorHorarios:
    def __init__(self, archivo_horarios: str, sincronizar_ntp: bool = True):
        self.archivo_horarios = archivo_horarios
        self._lock = threading.Lock()
        self._horarios = self._cargar()
        self._hora_ajuste = timedelta(0)
        
        if sincronizar_ntp:
            self._sincronizar_ntp()
    
    def _sincronizar_ntp(self) -> None:
        """Sincroniza la hora con un servidor NTP."""
        try:
            hora_ntp = obtener_hora_ntp()
            hora_local = datetime.now()
            self._hora_ajuste = hora_ntp - hora_local
            logger.info(f"Sincronización NTP exitosa. Ajuste: {self._hora_ajuste.total_seconds()}s")
        except Exception as e:
            logger.error(f"Error al sincronizar NTP: {e}")
    
    def obtener_hora_actual(self) -> datetime:
        """Devuelve la hora actual sincronizada con NTP."""
        return datetime.now() + self._hora_ajuste

    def _cargar(self) -> dict:
        if os.path.exists(self.archivo_horarios):
            try:
                with open(self.archivo_horarios, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                logger.exception("No se pudo leer %s, se arranca con horarios vacíos", self.archivo_horarios)
        return {}

    def _guardar(self) -> None:
        try:
            with open(self.archivo_horarios, "w", encoding="utf-8") as f:
                json.dump(self._horarios, f, ensure_ascii=False, indent=2)
        except Exception:
            logger.exception("No se pudo guardar %s", self.archivo_horarios)

    def obtener_todos(self) -> dict:
        return dict(self._horarios)

    @staticmethod
    def _predeterminado(curso: str = "") -> dict:
        try:
            numero = int("".join(c for c in curso if c.isdigit()))
        except ValueError:
            numero = 0
        return {
            "hora_entrada": DEFAULT_HORA_ENTRADA_TARDE if 1 <= numero <= 3
            else DEFAULT_HORA_ENTRADA_MANANA,
            "tolerancia_minutos": DEFAULT_TOLERANCIA_MIN,
        }

    def obtener(self, curso: str, fecha=None) -> dict:
        """Obtiene el horario efectivo para una fecha, con compatibilidad
        para el formato anterior de horarios.json."""
        cfg = self._horarios.get(curso, self._predeterminado(curso))
        if "habitual" in cfg:
            habitual = cfg["habitual"]
            contraturno = self.obtener_contraturno(curso, fecha)
            cambios = cfg.get("cambios", {})
        else:
            habitual = {
                "hora_entrada": cfg.get("hora_entrada", self._predeterminado(curso)["hora_entrada"]),
                "tolerancia_minutos": cfg.get("tolerancia_minutos", DEFAULT_TOLERANCIA_MIN),
            }
            contraturno = dict(habitual)
            cambios = {}
        cambio = cambios.get(self._fecha_str(fecha)) if fecha else None
        if cambio and cambio.get("tipo") == "contraturno_id":
            for registro in self.obtener_contraturnos(curso):
                if registro.get("id") == cambio.get("id"):
                    return {
                        "hora_entrada": registro["hora_entrada"],
                        "tolerancia_minutos": registro["tolerancia_minutos"],
                    }
        if cambio and cambio.get("tipo") == "contraturno":
            return dict(contraturno)
        if cambio and cambio.get("tipo") == "normal":
            return dict(habitual)
        return dict(cambio or habitual)

    def obtener_contraturnos(self, curso: str = None) -> list:
        cursos = [curso] if curso else list(self._horarios)
        resultado = []
        for nombre in cursos:
            cfg = self._horarios.get(nombre, {})
            registros = cfg.get("contraturnos")
            if registros is None and "contraturno" in cfg:
                registros = [{
                    "id": f"legacy-{nombre}",
                    "curso": nombre,
                    "dia": "todos",
                    **cfg["contraturno"],
                }]
            for registro in registros or []:
                resultado.append({**registro, "curso": nombre})
        return resultado

    def obtener_contraturno(self, curso: str, fecha=None) -> dict:
        """
        Obtiene el contraturno para un curso en una fecha específica.
        Valida que el día del contraturno coincida con el día de la fecha.
        """
        cfg = self._horarios.get(curso, self._predeterminado(curso))
        registros = self.obtener_contraturnos(curso)
        dias = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
        
        # Usar fecha actual sincronizada con NTP
        if fecha is None:
            fecha = self.obtener_hora_actual().date()
        
        dia_actual = dias[fecha.weekday()] if hasattr(fecha, "weekday") else None
        
        # Buscar contraturno que coincida con el día actual
        for registro in registros:
            dia_contraturno = registro.get("dia", "").lower().strip()
            
            # Validar que el día del contraturno coincida con el día actual
            if dia_contraturno in (dia_actual, "todos"):
                logger.debug(f"Contraturno activo para {curso} el {dia_actual}: {registro['hora_entrada']}")
                return {
                    "hora_entrada": registro["hora_entrada"],
                    "tolerancia_minutos": registro["tolerancia_minutos"],
                }
        
        # Si no hay contraturno para hoy, devolver horario habitual
        if "habitual" not in cfg:
            return dict(cfg)
        return dict(cfg.get("contraturno", cfg["habitual"]))

    def _es_permanente(self, identificador: str, curso: str) -> bool:
        """Verifica si un contraturno está marcado como permanente."""
        for registro in self.obtener_contraturnos(curso):
            if registro.get("id") == identificador:
                return registro.get("permanente", False)
        return False

    def crear_contraturno(self, curso: str, dia: str, hora_entrada: str,
                          tolerancia_minutos: int) -> dict:
        self._validar_horario(hora_entrada, tolerancia_minutos)
        self._validar_dia(dia)
        registro = {
            "id": uuid.uuid4().hex,
            "curso": curso,
            "dia": dia.lower().strip(),
            "hora_entrada": hora_entrada,
            "tolerancia_minutos": int(tolerancia_minutos),
        }
        with self._lock:
            cfg = self._horarios.setdefault(curso, {
                "habitual": self._predeterminado(curso),
                "cambios": {},
            })
            cfg.setdefault("contraturnos", []).append(registro)
            self._guardar()
        logger.info(f"Contraturno creado para {curso} el {dia}: {hora_entrada}")
        return registro

    def actualizar_contraturno(self, identificador: str, curso: str, dia: str,
                               hora_entrada: str, tolerancia_minutos: int) -> dict:
        if self._es_permanente(identificador, curso):
            raise ValueError("No se puede modificar un contraturno permanente")
        
        self._validar_horario(hora_entrada, tolerancia_minutos)
        self._validar_dia(dia)
        with self._lock:
            for registro in self.obtener_contraturnos(curso):
                if registro.get("id") == identificador:
                    registro.update({
                        "dia": dia.lower().strip(), "hora_entrada": hora_entrada,
                        "tolerancia_minutos": int(tolerancia_minutos),
                    })
                    self._horarios[curso].setdefault("contraturnos", [])
                    reemplazar = self._horarios[curso]["contraturnos"]
                    for indice, actual in enumerate(reemplazar):
                        if actual.get("id") == identificador:
                            reemplazar[indice] = registro
                    self._guardar()
                    logger.info(f"Contraturno actualizado para {curso}: {dia} {hora_entrada}")
                    return registro
        raise KeyError("Contraturno no encontrado")

    def eliminar_contraturno(self, identificador: str, curso: str) -> None:
        if self._es_permanente(identificador, curso):
            raise ValueError("No se puede eliminar un contraturno permanente")
        
        with self._lock:
            cfg = self._horarios.get(curso, {})
            registros = cfg.get("contraturnos", [])
            nuevos = [r for r in registros if r.get("id") != identificador]
            if len(nuevos) == len(registros):
                raise KeyError("Contraturno no encontrado")
            cfg["contraturnos"] = nuevos
            self._guardar()
            logger.info(f"Contraturno eliminado para {curso}")

    def activar_contraturno_registro(self, identificador: str, curso: str, fecha=None) -> None:
        if not any(r.get("id") == identificador for r in self.obtener_contraturnos(curso)):
            raise KeyError("Contraturno no encontrado")
        with self._lock:
            cfg = self._horarios.setdefault(curso, {
                "habitual": self._predeterminado(curso), "cambios": {}
            })
            cfg.setdefault("cambios", {})
            cfg["cambios"][self._fecha_str(fecha)] = {
                "tipo": "contraturno_id", "id": identificador
            }
            self._guardar()

    @staticmethod
    def _validar_horario(hora_entrada: str, tolerancia_minutos: int) -> None:
        datetime.strptime(hora_entrada, "%H:%M")
        if int(tolerancia_minutos) < 0 or int(tolerancia_minutos) > 120:
            raise ValueError("La tolerancia debe estar entre 0 y 120 minutos")

    @staticmethod
    def _validar_dia(dia: str) -> None:
        """Valida que el día sea uno válido de la semana."""
        dias_validos = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo", "todos")
        if dia.lower().strip() not in dias_validos:
            raise ValueError(f"Día inválido. Debe ser uno de: {', '.join(dias_validos)}")

    @staticmethod
    def _fecha_str(fecha) -> str:
        if fecha is None:
            return datetime.now().strftime("%Y-%m-%d")
        return fecha.strftime("%Y-%m-%d") if hasattr(fecha, "strftime") else str(fecha)

    def establecer(self, curso: str, hora_entrada: str, tolerancia_minutos: int,
                  fecha=None, habitual: bool = False, modo: str = "especial") -> None:
        # Validamos el formato acá para no guardar basura que después
        # rompa calcular_estado() en silencio.
        datetime.strptime(hora_entrada, "%H:%M")

        tolerancia = int(tolerancia_minutos)
        if tolerancia < 0 or tolerancia > 120:
            raise ValueError("La tolerancia debe estar entre 0 y 120 minutos")

        with self._lock:
            actual = self._horarios.get(curso, {})
            if "habitual" not in actual:
                horario_anterior = {
                    "hora_entrada": actual.get(
                        "hora_entrada", self._predeterminado(curso)["hora_entrada"]
                    ),
                    "tolerancia_minutos": actual.get("tolerancia_minutos", DEFAULT_TOLERANCIA_MIN),
                }
                actual = {
                    "habitual": horario_anterior,
                    "contraturno": dict(horario_anterior),
                    "cambios": {},
                }
            actual.setdefault("contraturno", dict(actual["habitual"]))
            actual.setdefault("cambios", {})
            nuevo = {"hora_entrada": hora_entrada, "tolerancia_minutos": tolerancia}
            if habitual:
                actual["habitual"] = nuevo
            elif modo == "contraturno":
                actual["contraturno"] = nuevo
            else:
                actual["cambios"][self._fecha_str(fecha)] = {
                    **nuevo, "tipo": "especial"
                }
            self._horarios[curso] = actual
            self._guardar()
            alcance = "habitual" if habitual else (
                "contraturno" if modo == "contraturno"
                else f"la fecha {self._fecha_str(fecha)}"
            )
            logger.info("Horario actualizado para %s (%s): entra %s, tolerancia %d min",
                        curso, alcance, hora_entrada, tolerancia)

    def activar_modo(self, curso: str, modo: str, fecha=None) -> None:
        if modo not in ("normal", "contraturno"):
            raise ValueError("Modo de horario inválido")
        with self._lock:
            actual = self._horarios.get(curso, {})
            if "habitual" not in actual:
                base = {
                    "hora_entrada": actual.get("hora_entrada", self._predeterminado(curso)["hora_entrada"]),
                    "tolerancia_minutos": actual.get("tolerancia_minutos", DEFAULT_TOLERANCIA_MIN),
                }
                actual = {"habitual": base, "contraturno": dict(base), "cambios": {}}
            actual.setdefault("contraturno", dict(actual["habitual"]))
            actual.setdefault("cambios", {})
            actual["cambios"][self._fecha_str(fecha)] = {"tipo": modo}
            self._horarios[curso] = actual
            self._guardar()

    def calcular_estado(self, curso: str, momento: datetime = None) -> str:
        """Devuelve 'PRESENTE' o 'TARDE' según el horario configurado del curso."""
        if momento is None:
            momento = self.obtener_hora_actual()
        
        cfg = self.obtener(curso, momento.date())
        hora_entrada = datetime.strptime(cfg["hora_entrada"], "%H:%M").time()
        limite = (
            datetime.combine(momento.date(), hora_entrada) + timedelta(minutes=cfg["tolerancia_minutos"])
        ).time()
        return "PRESENTE" if momento.time() <= limite else "TARDE"
