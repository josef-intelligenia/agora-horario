"""Salidas alternativas del horario: JSON, CSV e iCalendar."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Sequence

from .api import Clase, a_utc

CAMPOS_CSV = [
    "fecha", "hora", "hora_fin", "duracion_min", "nombre", "sala",
    "monitor", "capacidad", "reservas", "id", "descripcion",
]


def a_json(clases: Sequence[Clase], *, crudo: bool = False, indent: int | None = 2) -> str:
    if crudo:
        datos = [c.crudo for c in clases]
    else:
        datos = [c.as_dict() for c in clases]
        for d in datos:
            d.pop("crudo", None)
    return json.dumps(datos, ensure_ascii=False, indent=indent)


def a_csv(clases: Sequence[Clase]) -> str:
    buf = io.StringIO()
    escritor = csv.DictWriter(buf, fieldnames=CAMPOS_CSV, extrasaction="ignore")
    escritor.writeheader()
    for c in clases:
        escritor.writerow(c.as_dict())
    return buf.getvalue()


def _utc(momento: datetime) -> str:
    return a_utc(momento).strftime("%Y%m%dT%H%M%SZ")


def _escapar(texto: str) -> str:
    return (
        texto.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _plegar(linea: str) -> str:
    """RFC 5545: como mucho 75 octetos por linea."""
    bruto = linea.encode("utf-8")
    if len(bruto) <= 75:
        return linea
    trozos, actual = [], bytearray()
    limite = 75
    for char in linea:
        b = char.encode("utf-8")
        if len(actual) + len(b) > limite:
            trozos.append(bytes(actual))
            actual = bytearray(b" ")
            limite = 74
        actual += b
    trozos.append(bytes(actual))
    return "\r\n".join(t.decode("utf-8") for t in trozos)


def a_ics(clases: Sequence[Clase], *, nombre: str = "AGORA - Actividades colectivas") -> str:
    sello = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lineas = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//agora-horario//ES",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escapar(nombre)}",
        "X-WR-TIMEZONE:Europe/Madrid",
    ]
    for c in clases:
        desc = c.descripcion or ""
        if c.capacidad:
            desc = (desc + "\n\n" if desc else "") + f"Capacidad: {c.capacidad} plazas"
        lineas += [
            "BEGIN:VEVENT",
            f"UID:agora-{c.id}@agoragranada.provis.es",
            f"DTSTAMP:{sello}",
            f"DTSTART:{_utc(c.inicio)}",
            f"DTEND:{_utc(c.fin)}",
            _plegar(f"SUMMARY:{_escapar(c.nombre)}"),
            _plegar(f"LOCATION:{_escapar(c.sala)} - AGORA We Granada"),
            _plegar(f"DESCRIPTION:{_escapar(desc)}"),
            _plegar(f"X-AGORA-MONITOR:{_escapar(c.monitor)}"),
            "END:VEVENT",
        ]
    lineas.append("END:VCALENDAR")
    return "\r\n".join(lineas) + "\r\n"
