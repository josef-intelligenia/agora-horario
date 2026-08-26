#!/usr/bin/env python3
"""Genera los iconos de la PWA sin dependencias externas.

Los PNG resultantes se versionan en agora/static/, asi que esto solo hay que
volver a ejecutarlo si se cambia el diseno del icono.

    python3 herramientas/generar_iconos.py

El dibujo son rectangulos redondeados: se pinta a 4x y se reduce promediando,
que es antialiasing suficiente para una marca tan simple.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

DESTINO = Path(__file__).resolve().parent.parent / "agora" / "static"

FONDO = (14, 124, 123, 255)   # el teal de la interfaz
BARRA = (241, 244, 243, 255)  # el fondo claro, casi blanco
NADA = (0, 0, 0, 0)           # fuera del cuadrado no se pinta
SUPER = 4                   # factor de supermuestreo


def rect_redondeado(pixeles, ancho, x0, y0, x1, y1, radio, color):
    """Pinta un rectangulo de esquinas redondeadas sobre el lienzo."""
    for y in range(int(y0), int(y1)):
        for x in range(int(x0), int(x1)):
            cx = min(max(x, x0 + radio), x1 - radio)
            cy = min(max(y, y0 + radio), y1 - radio)
            dx, dy = x - cx, y - cy
            if dx * dx + dy * dy <= radio * radio:
                pixeles[y * ancho + x] = color


def reducir(pixeles, ancho, alto, factor):
    """Promedia bloques de factor x factor: el antialiasing."""
    salida = []
    for y in range(0, alto, factor):
        for x in range(0, ancho, factor):
            r = g = b = a = 0
            for j in range(factor):
                fila = (y + j) * ancho
                for i in range(factor):
                    p = pixeles[fila + x + i]
                    # Premultiplicado: si no, los bordes tiran a negro.
                    r += p[0] * p[3]; g += p[1] * p[3]; b += p[2] * p[3]; a += p[3]
            n = factor * factor
            salida.append((r // a, g // a, b // a, a // n) if a else NADA)
    return salida


def escribir_png(ruta: Path, pixeles, lado: int) -> None:
    crudo = b"".join(
        b"\x00" + b"".join(struct.pack("BBBB", *pixeles[y * lado + x]) for x in range(lado))
        for y in range(lado)
    )

    def trozo(tipo: bytes, datos: bytes) -> bytes:
        return (struct.pack(">I", len(datos)) + tipo + datos +
                struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF))

    ruta.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + trozo(b"IHDR", struct.pack(">IIBBBBB", lado, lado, 8, 6, 0, 0, 0))
        + trozo(b"IDAT", zlib.compress(crudo, 9))
        + trozo(b"IEND", b"")
    )


def dibujar(lado: int, *, redondeado: bool, util_rel: float) -> list:
    """Tres barras decrecientes sobre un cuadrado: una parrilla de horarios.

    ``redondeado``  el icono se recorta solo; si no, cubre todo el lienzo porque
                    lo recorta el sistema (Android maskable, iOS).
    ``util_rel``    proporcion del lienzo que ocupa el dibujo. Menos de 1 deja la
                    zona segura que exige un icono maskable.
    """
    g = lado * SUPER
    pixeles = [NADA] * (g * g)

    radio = g * 0.22 if redondeado else 0
    rect_redondeado(pixeles, g, 0, 0, g, g, radio, FONDO)

    util = g * util_rel
    origen = (g - util) / 2
    alto_barra = util * 0.115
    hueco = util * 0.075
    total = 3 * alto_barra + 2 * hueco
    y = origen + (util - total) / 2
    for proporcion in (0.62, 0.46, 0.30):
        x0 = origen + util * 0.19
        rect_redondeado(pixeles, g, x0, y, x0 + util * proporcion, y + alto_barra,
                        alto_barra / 2, BARRA)
        y += alto_barra + hueco

    return reducir(pixeles, g, g, SUPER)


def main() -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    for nombre, lado, redondeado, util in [
        ("icono-192.png", 192, True, 1.0),
        ("icono-512.png", 512, True, 1.0),
        # Android recorta el maskable con su mascara: fondo a sangre, dibujo en
        # la zona segura.
        ("icono-maskable-512.png", 512, False, 0.72),
        # iOS tambien pone su propia mascara y, sobre todo, no admite
        # transparencia: la compone sobre negro. Fondo a sangre y opaco.
        ("icono-apple-180.png", 180, False, 0.86),
    ]:
        ruta = DESTINO / nombre
        escribir_png(ruta, dibujar(lado, redondeado=redondeado, util_rel=util), lado)
        print(f"{ruta}  ({ruta.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
