"""Acceso a los datos de clases colectivas de AGORA.

El endpoint publico devuelve una pagina HTML, no JSON: los datos de cada clase
viajan serializados en el atributo ``data-json`` del boton de reserva. Cada
peticion cubre 7 dias naturales a partir de ``fecha``; las fechas pasadas las
recorta el servidor al dia de hoy.
"""

from __future__ import annotations

import html
import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

try:  # zoneinfo esta en la stdlib desde 3.9
    from zoneinfo import ZoneInfo

    MADRID: Any = ZoneInfo("Europe/Madrid")
except Exception:  # pragma: no cover - entornos sin tzdata
    MADRID = None

BASE = "https://agoragranada.provis.es"
ENDPOINT = BASE + "/ActividadesColectivas/ClasesColectivasTimeLinePublic"
DIAS_POR_PETICION = 7
USER_AGENT = "agora-horario/1.0 (+consulta de horario publico)"

CACHE_DIR = Path.home() / ".cache" / "agora-horario"
CACHE_TTL = 900  # segundos

_DATA_JSON = re.compile(r'data-json="([^"]*)"')
# Sufijos de puntuacion que el gestor arrastra en los nombres: "ZUMBA.", "CORE_"...
_SUFIJO_SUCIO = re.compile(r"[\s._/\-]+$")


def a_utc(momento: datetime) -> datetime:
    """Las horas de AGORA son hora local de Granada, sin zona explicita."""
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=MADRID) if MADRID else momento.astimezone()
    return momento.astimezone(timezone.utc)


class AgoraError(RuntimeError):
    """Fallo al obtener o interpretar los datos del servidor."""


# --------------------------------------------------------------------------- #
# Modelo
# --------------------------------------------------------------------------- #

@dataclass
class Clase:
    id: int
    nombre: str
    nombre_norm: str
    inicio: datetime
    fin: datetime
    duracion_min: int
    sala: str
    sala_id: int
    monitor: str
    monitor_id: int
    capacidad: int
    reservas: int
    color: str
    descripcion: str
    actividad_id: int
    agrupacion: str
    lista_espera: bool
    caducada: bool
    motivo_reserva: str
    crudo: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def fecha(self) -> date:
        return self.inicio.date()

    @property
    def libres(self) -> int | None:
        """Plazas libres, o ``None`` si el dato no es fiable (sesion anonima)."""
        if self.capacidad <= 0:
            return None
        return max(self.capacidad - self.reservas, 0)

    @property
    def franja(self) -> str:
        h = self.inicio.hour
        if h < 12:
            return "manana"
        if h < 17:
            return "mediodia"
        return "tarde"

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["inicio"] = self.inicio.isoformat()
        d["fin"] = self.fin.isoformat()
        d["fecha"] = self.fecha.isoformat()
        d["hora"] = self.inicio.strftime("%H:%M")
        d["hora_fin"] = self.fin.strftime("%H:%M")
        d["inicio_utc"] = a_utc(self.inicio).strftime("%Y-%m-%dT%H:%M:%SZ")
        d["fin_utc"] = a_utc(self.fin).strftime("%Y-%m-%dT%H:%M:%SZ")
        d["libres"] = self.libres
        d["franja"] = self.franja
        return d


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #

def sin_acentos(texto: str) -> str:
    """Minusculas sin tildes, para buscar y comparar sin sorpresas."""
    desc = unicodedata.normalize("NFD", texto)
    return "".join(c for c in desc if unicodedata.category(c) != "Mn").lower()


def _color_hex(valor: int | None) -> str:
    """El servidor manda el color como entero ARGB con signo (java-style)."""
    if valor is None:
        return "#6B7280"
    v = valor & 0xFFFFFFFF
    return "#%02X%02X%02X" % ((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF)


def _limpiar(texto: str | None) -> str:
    return re.sub(r"\s+", " ", (texto or "")).strip()


def _normalizar_nombre(nombre: str) -> str:
    return _SUFIJO_SUCIO.sub("", _limpiar(nombre)).upper()


def parse_fecha(valor: str | date | datetime) -> date:
    """Acepta ``hoy``, ``manana``, ``ayer``, ``+3``, ``dd/mm/aaaa`` o ISO."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    txt = sin_acentos(str(valor).strip())
    hoy = date.today()
    if txt in ("hoy", "today"):
        return hoy
    if txt in ("manana", "tomorrow"):
        return hoy + timedelta(days=1)
    if txt in ("ayer", "yesterday"):
        return hoy - timedelta(days=1)
    if re.fullmatch(r"[+-]\d+", txt):
        return hoy + timedelta(days=int(txt))
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(txt, fmt).date()
        except ValueError:
            continue
    raise AgoraError(f"No entiendo la fecha {valor!r} (usa AAAA-MM-DD, dd/mm/aaaa, hoy, manana o +N)")


# --------------------------------------------------------------------------- #
# Descarga y parseo
# --------------------------------------------------------------------------- #

def _ruta_cache(dia: date) -> Path:
    return CACHE_DIR / f"{dia.isoformat()}.json"


def _leer_cache(dia: date, ttl: int) -> list[dict[str, Any]] | None:
    ruta = _ruta_cache(dia)
    try:
        edad = time.time() - ruta.stat().st_mtime
    except OSError:
        return None
    if edad > ttl:
        return None
    try:
        return json.loads(ruta.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def _escribir_cache(dia: date, crudos: list[dict[str, Any]]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _ruta_cache(dia).with_suffix(".tmp")
        tmp.write_text(json.dumps(crudos, ensure_ascii=False), "utf-8")
        tmp.replace(_ruta_cache(dia))
    except OSError:
        pass  # la cache es un lujo, no un requisito


def _descargar(dia: date, timeout: float) -> str:
    url = f"{ENDPOINT}?fecha={dia.isoformat()}T00:00:00&integration=true"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise AgoraError(f"El servidor respondio {exc.code} para {dia}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AgoraError(f"No se pudo conectar con AGORA: {exc}") from exc


def _extraer_crudos(pagina: str) -> list[dict[str, Any]]:
    crudos: list[dict[str, Any]] = []
    for bruto in _DATA_JSON.findall(pagina):
        try:
            crudos.append(json.loads(html.unescape(bruto)))
        except ValueError:
            continue
    if not crudos and "ClasesColectivas" not in pagina:
        raise AgoraError("La respuesta no parece la pagina de clases colectivas")
    return crudos


def _a_clase(c: dict[str, Any]) -> Clase | None:
    try:
        inicio = datetime.fromisoformat(c["HoraInicio"])
        fin = datetime.fromisoformat(c["HoraFin"])
    except (KeyError, TypeError, ValueError):
        return None
    nombre = _limpiar(c.get("Nombre")) or "(sin nombre)"
    monitor = _limpiar(f"{c.get('NombreTrabajador') or ''} {c.get('ApellidosTrabajador') or ''}")
    return Clase(
        id=int(c.get("Id", 0)),
        nombre=nombre,
        nombre_norm=_normalizar_nombre(nombre),
        inicio=inicio,
        fin=fin,
        duracion_min=max(int((fin - inicio).total_seconds() // 60), 0),
        sala=_limpiar(c.get("nombreZona")) or "(sin sala)",
        sala_id=int(c.get("Zona") or 0),
        monitor=monitor or "(sin asignar)",
        monitor_id=int(c.get("IDTrabajador") or 0),
        capacidad=int(c.get("Capacidad") or 0),
        reservas=int(c.get("ReservasHechas") or 0),
        color=_color_hex(c.get("color")),
        descripcion=_limpiar(c.get("Descripcion")),
        actividad_id=int(c.get("IDActividadColectiva") or 0),
        agrupacion=_limpiar(c.get("NombreAgrupacion")),
        lista_espera=bool(c.get("PermiteListaDeEspera")),
        caducada=bool(c.get("Caducada")),
        motivo_reserva=_limpiar(c.get("razonReserva")),
        crudo=c,
    )


def clases_desde(dia: date, *, ttl: int = CACHE_TTL, timeout: float = 20.0) -> list[Clase]:
    """Clases de la ventana de 7 dias que abre ``dia`` (tal cual las da el servidor)."""
    crudos = _leer_cache(dia, ttl)
    if crudos is None:
        crudos = _extraer_crudos(_descargar(dia, timeout))
        _escribir_cache(dia, crudos)
    clases = [cl for cl in map(_a_clase, crudos) if cl is not None]
    clases.sort(key=lambda c: (c.inicio, c.sala, c.nombre))
    return clases


def horario(
    desde: str | date = "hoy",
    dias: int = 7,
    *,
    ttl: int = CACHE_TTL,
    timeout: float = 20.0,
) -> list[Clase]:
    """Horario de ``dias`` dias a partir de ``desde``, encadenando ventanas de 7."""
    inicio = parse_fecha(desde)
    dias = max(int(dias), 1)
    hasta = inicio + timedelta(days=dias)

    vistas: dict[int, Clase] = {}
    ancla = inicio
    while ancla < hasta:
        for clase in clases_desde(ancla, ttl=ttl, timeout=timeout):
            vistas.setdefault(clase.id, clase)
        ancla += timedelta(days=DIAS_POR_PETICION)

    dentro = [c for c in vistas.values() if inicio <= c.fecha < hasta]
    dentro.sort(key=lambda c: (c.inicio, c.sala, c.nombre))
    return dentro


# --------------------------------------------------------------------------- #
# Filtrado y agrupacion
# --------------------------------------------------------------------------- #

Criterio = "str | Sequence[str] | None"


def _patrones(valor) -> list[str]:
    """Un criterio puede ser un texto o una lista de textos."""
    if valor is None:
        return []
    if isinstance(valor, str):
        valor = [valor]
    return [sin_acentos(v) for v in valor if v]


def _encaja(campo: str, patrones: list[str]) -> bool:
    """Sin patrones no filtra; con varios basta con que encaje uno (OR)."""
    if not patrones:
        return True
    plano = sin_acentos(campo)
    return any(p in plano for p in patrones)


def filtrar(
    clases: Iterable[Clase],
    *,
    actividad=None,
    monitor=None,
    sala=None,
    texto: str | None = None,
    desde_hora: str | None = None,
    hasta_hora: str | None = None,
    duracion_min: int | None = None,
    solo_proximas: bool = False,
    ahora: datetime | None = None,
) -> list[Clase]:
    """Los criterios se combinan con AND; dentro de cada uno, con OR.

    ``actividad``, ``monitor`` y ``sala`` aceptan un texto o una lista.
    Las comparaciones de texto son parciales y no distinguen mayusculas ni tildes.
    """
    ahora = ahora or datetime.now()

    def hhmm(valor: str) -> int:
        m = re.fullmatch(r"(\d{1,2})(?::?(\d{2}))?", valor.strip())
        if not m:
            raise AgoraError(f"Hora no valida: {valor!r} (usa HH:MM)")
        return int(m.group(1)) * 60 + int(m.group(2) or 0)

    lim_min = hhmm(desde_hora) if desde_hora else None
    lim_max = hhmm(hasta_hora) if hasta_hora else None
    p_act, p_mon, p_sala = _patrones(actividad), _patrones(monitor), _patrones(sala)
    n_txt = sin_acentos(texto) if texto else None

    salida = []
    for c in clases:
        if not _encaja(c.nombre, p_act):
            continue
        if not _encaja(c.monitor, p_mon):
            continue
        if not _encaja(c.sala, p_sala):
            continue
        if n_txt and n_txt not in sin_acentos(f"{c.nombre} {c.monitor} {c.sala} {c.descripcion}"):
            continue
        minutos = c.inicio.hour * 60 + c.inicio.minute
        if lim_min is not None and minutos < lim_min:
            continue
        if lim_max is not None and minutos > lim_max:
            continue
        if duracion_min is not None and c.duracion_min < duracion_min:
            continue
        if solo_proximas and c.fin < ahora:
            continue
        salida.append(c)
    return salida


def por_dia(clases: Sequence[Clase]) -> list[tuple[date, list[Clase]]]:
    grupos: dict[date, list[Clase]] = {}
    for c in clases:
        grupos.setdefault(c.fecha, []).append(c)
    return sorted(grupos.items())


def catalogo(clases: Sequence[Clase]) -> dict[str, list[dict[str, Any]]]:
    """Valores distintos con su numero de clases, para poblar filtros."""
    def cuenta(clave, color=None) -> list[dict[str, Any]]:
        acc: dict[str, dict[str, Any]] = {}
        for c in clases:
            k = clave(c)
            entrada = acc.setdefault(k, {"nombre": k, "clases": 0})
            entrada["clases"] += 1
            if color:
                entrada["color"] = color(c)
        return sorted(acc.values(), key=lambda e: (-e["clases"], e["nombre"]))

    return {
        "actividades": cuenta(lambda c: c.nombre_norm, lambda c: c.color),
        "salas": cuenta(lambda c: c.sala),
        "monitores": cuenta(lambda c: c.monitor),
    }


def iter_semanas(desde: date, dias: int) -> Iterator[date]:
    ancla, hasta = desde, desde + timedelta(days=dias)
    while ancla < hasta:
        yield ancla
        ancla += timedelta(days=DIAS_POR_PETICION)


def limpiar_cache() -> int:
    borrados = 0
    for f in CACHE_DIR.glob("*.json"):
        try:
            f.unlink()
            borrados += 1
        except OSError:
            pass
    return borrados
