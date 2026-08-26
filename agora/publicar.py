"""Genera una pagina autocontenida con el horario incrustado.

La misma interfaz que sirve la app local, pero con los datos dentro del HTML:
un unico fichero que se puede subir a cualquier hosting estatico, abrir desde
disco o publicar como artifact. No consulta AGORA al abrirse, asi que refleja
el momento en que se genero.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

from . import api
from .api import Clase

PLANTILLA = Path(__file__).parent / "static" / "index.html"

# Campos que la interfaz necesita; el resto (incluido el volcado crudo de la
# API) se descarta para no multiplicar el peso del fichero.
CAMPOS = (
    "id", "nombre", "fecha", "hora", "hora_fin", "inicio", "fin",
    "inicio_utc", "fin_utc", "duracion_min", "sala", "sala_id", "monitor",
    "capacidad", "reservas", "color", "actividad_id", "lista_espera",
)

NOTA = (
    "Vista no oficial del horario publico de "
    '<a href="https://agoragranada.provis.es" target="_blank" rel="noreferrer">'
    "agoragranada.provis.es</a>, generada el {sello}. "
    "Para reservar, entra en la web oficial de AGORA."
)


def _payload(clases: Sequence[Clase]) -> dict:
    # Las descripciones se repiten en todas las sesiones de una misma actividad:
    # se guardan una vez y cada clase referencia su indice.
    textos: list[str] = []
    indice: dict[str, int] = {}
    compactas = []
    for c in clases:
        d = c.as_dict()
        fila = {k: d[k] for k in CAMPOS}
        if c.descripcion:
            if c.descripcion not in indice:
                indice[c.descripcion] = len(textos)
                textos.append(c.descripcion)
            fila["desc"] = indice[c.descripcion]
        compactas.append(fila)

    fechas = sorted({c.fecha for c in clases})
    return {
        "generado": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "rango": [fechas[0].isoformat(), fechas[-1].isoformat()] if fechas else None,
        "catalogo": api.catalogo(clases),
        "descripciones": textos,
        "clases": compactas,
    }


def _fragmento(html: str) -> str:
    """Deja solo titulo, fuentes, estilos y contenido del body.

    El visor de artifacts envuelve lo que se le pasa en su propio esqueleto
    (doctype, html, head, body), asi que esas etiquetas sobran.
    """
    trozos = []
    for patron in (r"<title>.*?</title>",
                   r'<link rel="(?:preconnect|stylesheet)"[^>]*>',
                   r"<style>.*?</style>"):
        trozos += re.findall(patron, html, re.S)
    cuerpo = re.search(r"<body>(.*)</body>", html, re.S)
    if not cuerpo:
        raise api.AgoraError("La plantilla no tiene <body>")
    trozos.append(cuerpo.group(1).strip())
    return "\n".join(trozos) + "\n"


def generar(clases: Sequence[Clase], *, envoltorio: bool = True) -> str:
    if not PLANTILLA.is_file():
        raise api.AgoraError(f"Falta la plantilla {PLANTILLA}")
    html = PLANTILLA.read_text("utf-8")

    datos = json.dumps(_payload(clases), ensure_ascii=False, separators=(",", ":"))
    # </script> dentro de una cadena JSON cerraria la etiqueta antes de tiempo.
    datos = datos.replace("</", "<\\/")
    inyeccion = (
        "<script>\n"
        f"window.AGORA_DATOS = {datos};\n"
        "// Las descripciones van deduplicadas: se reexpanden aqui.\n"
        "for (const c of window.AGORA_DATOS.clases)\n"
        "  c.descripcion = c.desc === undefined ? '' : window.AGORA_DATOS.descripciones[c.desc];\n"
        "</script>"
    )
    html = html.replace("<!--DATOS-->", inyeccion)
    html = html.replace(
        'Datos de <a href="https://agoragranada.provis.es" target="_blank" rel="noreferrer">agoragranada.provis.es</a>.',
        NOTA.format(sello=datetime.now().strftime("%d/%m/%Y a las %H:%M")),
    )
    return html if envoltorio else _fragmento(html)


def escribir(clases: Sequence[Clase], destino: str | Path, *, envoltorio: bool = True) -> Path:
    ruta = Path(destino).expanduser()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(generar(clases, envoltorio=envoltorio), "utf-8")
    return ruta
