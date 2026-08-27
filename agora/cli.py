"""Interfaz de linea de comandos de agora-horario."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta

from . import __version__, api, exportar
from .api import AgoraError, Clase

DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


# --------------------------------------------------------------------------- #
# Presentacion
# --------------------------------------------------------------------------- #

def _color_activo(stream) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return hasattr(stream, "isatty") and stream.isatty()


class Pintor:
    def __init__(self, activo: bool) -> None:
        self.activo = activo

    def rgb(self, texto: str, hexcolor: str) -> str:
        if not self.activo:
            return texto
        try:
            r, g, b = (int(hexcolor[i:i + 2], 16) for i in (1, 3, 5))
        except (ValueError, IndexError):
            return texto
        return f"\x1b[38;2;{r};{g};{b}m{texto}\x1b[0m"

    def estilo(self, texto: str, codigo: str) -> str:
        return f"\x1b[{codigo}m{texto}\x1b[0m" if self.activo else texto

    def negrita(self, texto: str) -> str:
        return self.estilo(texto, "1")

    def tenue(self, texto: str) -> str:
        return self.estilo(texto, "2")


def fecha_larga(d: date) -> str:
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}"


def _ancho(clases, atributo, minimo) -> int:
    return max([minimo] + [len(getattr(c, atributo)) for c in clases])


def tabla(clases: list[Clase], p: Pintor, *, ahora: datetime | None = None) -> str:
    if not clases:
        return p.tenue("No hay clases que cumplan los filtros.")
    ahora = ahora or datetime.now()
    an_nombre = min(_ancho(clases, "nombre", 12), 34)
    an_sala = min(_ancho(clases, "sala", 8), 18)
    an_monitor = min(_ancho(clases, "monitor", 8), 20)

    lineas: list[str] = []
    for dia, delta in api.por_dia(clases):
        titulo = fecha_larga(dia)
        if dia == date.today():
            titulo += "  (hoy)"
        elif dia == date.today() + timedelta(days=1):
            titulo += "  (manana)"
        lineas.append("")
        lineas.append(p.negrita(titulo.upper()))
        lineas.append(p.tenue("-" * max(len(titulo), 40)))
        for c in delta:
            pasada = c.fin < ahora
            horas = f"{c.inicio:%H:%M}-{c.fin:%H:%M}"
            nombre = c.nombre[:an_nombre].ljust(an_nombre)
            fila = (
                f"  {p.tenue(horas) if pasada else horas}  "
                f"{p.rgb('#', c.color)} {nombre if pasada else p.negrita(nombre)}  "
                f"{c.sala[:an_sala].ljust(an_sala)}  "
                f"{c.monitor[:an_monitor].ljust(an_monitor)}  "
                f"{p.tenue(f'{c.duracion_min:>3} min')}  "
                f"{p.tenue(f'{c.capacidad:>3} pl.')}"
            )
            lineas.append(p.tenue(fila) if pasada else fila)
    lineas.append("")
    lineas.append(p.tenue(f"{len(clases)} clases en {len(api.por_dia(clases))} dias"))
    return "\n".join(lineas)


def agenda(clases: list[Clase], p: Pintor) -> str:
    """Vista extendida con descripcion, para pocas clases."""
    if not clases:
        return p.tenue("No hay clases que cumplan los filtros.")
    bloques = []
    for c in clases:
        cabecera = f"{c.inicio:%d/%m %H:%M}-{c.fin:%H:%M}  {c.nombre}"
        cuerpo = [
            p.rgb("* ", c.color) + p.negrita(cabecera),
            f"    Sala      {c.sala}",
            f"    Monitor   {c.monitor}",
            f"    Duracion  {c.duracion_min} min   Capacidad  {c.capacidad} plazas",
        ]
        if c.descripcion:
            cuerpo.append(p.tenue(f"    {c.descripcion}"))
        bloques.append("\n".join(cuerpo))
    return "\n\n".join(bloques)


def resumen_catalogo(clases: list[Clase], p: Pintor) -> str:
    cat = api.catalogo(clases, orden="frecuencia")
    partes = [p.negrita(f"Catalogo sobre {len(clases)} clases")]
    for titulo, clave in (("Actividades", "actividades"), ("Salas", "salas"), ("Monitores", "monitores")):
        partes.append("")
        partes.append(p.negrita(f"{titulo} ({len(cat[clave])})"))
        for e in cat[clave]:
            marca = p.rgb("#", e["color"]) + " " if e.get("color") else ""
            partes.append(f"  {marca}{e['nombre'][:38].ljust(38)} {e['clases']:>3}")
    return "\n".join(partes)


# --------------------------------------------------------------------------- #
# Argumentos
# --------------------------------------------------------------------------- #

def construir_parser() -> argparse.ArgumentParser:
    padre = argparse.ArgumentParser(add_help=False)
    f = padre.add_argument_group("filtros")
    f.add_argument("-a", "--actividad", action="append", metavar="TEXTO",
                   help="actividad (parcial, sin tildes); repetible para varias")
    f.add_argument("-m", "--monitor", action="append", metavar="TEXTO",
                   help="monitor; repetible para varios")
    f.add_argument("-s", "--sala", action="append", metavar="TEXTO",
                   help="sala o zona; repetible para varias")
    f.add_argument("-b", "--buscar", help="texto libre en nombre, monitor, sala o descripcion")
    f.add_argument("--desde-hora", metavar="HH:MM", help="no mostrar clases que empiecen antes")
    f.add_argument("--hasta-hora", metavar="HH:MM", help="no mostrar clases que empiecen despues")
    f.add_argument("--min-duracion", type=int, metavar="MIN", help="duracion minima en minutos")
    f.add_argument("--proximas", action="store_true", help="ocultar las clases ya terminadas")

    s = padre.add_argument_group("salida")
    s.add_argument("-f", "--formato", default="tabla",
                   choices=["tabla", "agenda", "json", "json-crudo", "csv", "ics"],
                   help="formato de salida (por defecto: tabla)")
    s.add_argument("-o", "--salida", metavar="FICHERO", help="escribir en un fichero en vez de stdout")
    s.add_argument("--sin-color", action="store_true", help="desactivar color ANSI")

    r = padre.add_argument_group("red")
    r.add_argument("--sin-cache", action="store_true", help="forzar descarga ignorando la cache local")
    r.add_argument("--cache-ttl", type=int, default=api.CACHE_TTL, metavar="SEG",
                   help=f"validez de la cache en segundos (por defecto {api.CACHE_TTL})")
    r.add_argument("--timeout", type=float, default=20.0, metavar="SEG")

    parser = argparse.ArgumentParser(
        prog="agora",
        description="Consulta el horario de actividades colectivas de AGORA (We Granada).",
        epilog="Ejemplos:\n"
               "  agora hoy\n"
               "  agora semana -a pilates -a yoga\n"
               "  agora dia manana --desde-hora 18:00\n"
               "  agora rango --desde 2026-09-01 --dias 14 -f ics -o clases.ics\n"
               "  agora web",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-V", "--version", action="version", version=f"agora-horario {__version__}")
    sub = parser.add_subparsers(dest="comando")

    sub.add_parser("hoy", parents=[padre], help="clases de hoy")
    sub.add_parser("manana", parents=[padre], help="clases de manana")
    sub.add_parser("semana", parents=[padre], help="los proximos 7 dias")

    p_dia = sub.add_parser("dia", parents=[padre], help="un dia concreto")
    p_dia.add_argument("fecha", help="AAAA-MM-DD, dd/mm/aaaa, hoy, manana o +N")

    p_rango = sub.add_parser("rango", parents=[padre], help="un rango de dias")
    p_rango.add_argument("--desde", default="hoy", help="fecha inicial (por defecto hoy)")
    p_rango.add_argument("--dias", type=int, default=7, help="numero de dias (por defecto 7)")

    p_info = sub.add_parser("info", parents=[padre], help="catalogo de actividades, salas y monitores")
    p_info.add_argument("--desde", default="hoy")
    p_info.add_argument("--dias", type=int, default=7)

    p_pub = sub.add_parser("publicar", parents=[padre],
                           help="generar una pagina HTML autocontenida para compartir")
    p_pub.add_argument("--desde", default="hoy")
    p_pub.add_argument("--dias", type=int, default=14)
    p_pub.add_argument("--sitio", metavar="DIRECTORIO",
                       help="generar un sitio completo e instalable (PWA) en vez de un HTML suelto")
    p_pub.add_argument("--estado", metavar="FICHERO",
                       help="escribir tambien un JSON con el resumen de la publicacion")
    p_pub.add_argument("--fragmento", action="store_true",
                       help="sin doctype/head/body, para publicar como artifact de Claude")
    # -o/--salida ya viene del grupo comun de opciones de salida.

    p_web = sub.add_parser("web", help="abrir la interfaz web local")
    p_web.add_argument("-p", "--puerto", type=int, default=8765)
    p_web.add_argument("--host", default="127.0.0.1")
    p_web.add_argument("--no-abrir", action="store_true", help="no lanzar el navegador")

    sub.add_parser("limpiar-cache", help="borrar la cache local de respuestas")
    return parser


def _ventana(args) -> tuple[str | date, int]:
    cmd = args.comando
    if cmd == "hoy":
        return "hoy", 1
    if cmd == "manana":
        return "manana", 1
    if cmd == "semana":
        return "hoy", 7
    if cmd == "dia":
        return args.fecha, 1
    return args.desde, args.dias


def _emitir(texto: str, args) -> None:
    if getattr(args, "salida", None):
        with open(args.salida, "w", encoding="utf-8", newline="") as fh:
            fh.write(texto if texto.endswith("\n") else texto + "\n")
        print(f"Escrito {args.salida}", file=sys.stderr)
    else:
        print(texto)


def main(argv: list[str] | None = None) -> int:
    parser = construir_parser()
    args = parser.parse_args(argv)

    if args.comando is None:
        args = parser.parse_args(["hoy"] + list(argv or []))

    if args.comando == "limpiar-cache":
        print(f"Cache borrada ({api.limpiar_cache()} ficheros) en {api.CACHE_DIR}")
        return 0

    if args.comando == "web":
        from .web import servir
        return servir(host=args.host, puerto=args.puerto, abrir=not args.no_abrir)

    p = Pintor(_color_activo(sys.stdout) and not args.sin_color)

    try:
        desde, dias = _ventana(args)
        clases = api.horario(
            desde, dias,
            ttl=0 if args.sin_cache else args.cache_ttl,
            timeout=args.timeout,
        )
        clases = api.filtrar(
            clases,
            actividad=args.actividad,
            monitor=args.monitor,
            sala=args.sala,
            texto=args.buscar,
            desde_hora=args.desde_hora,
            hasta_hora=args.hasta_hora,
            duracion_min=args.min_duracion,
            solo_proximas=args.proximas,
        )
    except AgoraError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130

    if args.comando == "publicar":
        from .publicar import escribir, escribir_sitio
        if args.sitio:
            carpeta = escribir_sitio(clases, args.sitio)
            kb = sum(f.stat().st_size for f in carpeta.iterdir()) / 1024
            print(f"{carpeta}/  ({len(clases)} clases, {len(list(carpeta.iterdir()))} ficheros, {kb:.0f} KB)")
        else:
            ruta = escribir(clases, args.salida or "horario-agora.html",
                            envoltorio=not args.fragmento)
            kb = ruta.stat().st_size / 1024
            print(f"{ruta}  ({len(clases)} clases, {kb:.0f} KB)")
        if args.estado:
            from .publicar import escribir_estado
            print(escribir_estado(clases, args.estado))
        return 0

    if args.comando == "info":
        _emitir(resumen_catalogo(clases, p), args)
        return 0

    salidas = {
        "tabla": lambda: tabla(clases, p),
        "agenda": lambda: agenda(clases, p),
        "json": lambda: exportar.a_json(clases),
        "json-crudo": lambda: exportar.a_json(clases, crudo=True),
        "csv": lambda: exportar.a_csv(clases),
        "ics": lambda: exportar.a_ics(clases),
    }
    _emitir(salidas[args.formato](), args)
    return 0
