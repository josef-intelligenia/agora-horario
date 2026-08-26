"""Servidor local que sirve la interfaz web y hace de proxy contra AGORA.

El proxy es necesario porque AGORA solo permite CORS desde el origen exacto
``http://localhost`` (sin puerto), asi que el navegador no puede llamar
directamente al endpoint.
"""

from __future__ import annotations

import json
import sys
import threading
import webbrowser
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import api, exportar, pwa
from .api import AgoraError

ESTATICOS = Path(__file__).parent / "static"
MAX_DIAS = 60


def _params(consulta: dict[str, list[str]]) -> dict:
    def uno(clave, defecto=None):
        valor = consulta.get(clave, [None])[0]
        return valor if valor not in (None, "") else defecto

    def varios(clave):
        """actividad=X&actividad=Y -> ["X", "Y"]."""
        return [v for v in consulta.get(clave, []) if v]

    dias = uno("dias", "7")
    try:
        dias = max(1, min(int(dias), MAX_DIAS))
    except ValueError:
        dias = 7
    return {
        "desde": uno("desde", "hoy"),
        "dias": dias,
        "actividad": varios("actividad"),
        "monitor": varios("monitor"),
        "sala": varios("sala"),
        "texto": uno("q"),
        "desde_hora": uno("desde_hora"),
        "hasta_hora": uno("hasta_hora"),
        "solo_proximas": uno("proximas") in ("1", "true", "si"),
        "refrescar": uno("refrescar") in ("1", "true"),
    }


def _consultar(p: dict):
    """Devuelve (ventana completa, subconjunto filtrado).

    El catalogo de filtros se calcula sobre la ventana completa: si se calculase
    sobre el resultado, al elegir una actividad los demas desplegables se
    quedarian sin opciones.
    """
    todas = api.horario(p["desde"], p["dias"], ttl=0 if p["refrescar"] else api.CACHE_TTL)
    return todas, api.filtrar(
        todas,
        actividad=p["actividad"],
        monitor=p["monitor"],
        sala=p["sala"],
        texto=p["texto"],
        desde_hora=p["desde_hora"],
        hasta_hora=p["hasta_hora"],
        solo_proximas=p["solo_proximas"],
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "agora-horario"

    def log_message(self, formato, *args):  # silencio salvo errores
        if not str(args[1] if len(args) > 1 else "").startswith(("2", "3")):
            sys.stderr.write("%s - %s\n" % (self.address_string(), formato % args))

    # -- utilidades de respuesta ------------------------------------------- #

    def _responder(self, cuerpo: bytes, tipo: str, codigo: int = 200, extra: dict | None = None):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(cuerpo)

    def _json(self, datos, codigo: int = 200):
        self._responder(json.dumps(datos, ensure_ascii=False).encode("utf-8"),
                        "application/json; charset=utf-8", codigo)

    def _error(self, mensaje: str, codigo: int = 500):
        self._json({"error": mensaje}, codigo)

    # -- rutas -------------------------------------------------------------- #

    def do_GET(self):
        ruta = urlparse(self.path)
        consulta = parse_qs(ruta.query)
        try:
            if ruta.path in ("/", "/index.html"):
                # En local tambien se puede instalar: localhost cuenta como origen seguro.
                pagina = (ESTATICOS / "index.html").read_text("utf-8")
                pagina = pagina.replace("<!--PWA-->", pwa.cabecera())
                return self._responder(pagina.encode("utf-8"), "text/html; charset=utf-8")
            if ruta.path == "/api/clases":
                return self._api_clases(consulta)
            if ruta.path == "/api/ics":
                return self._api_ics(consulta)
            if ruta.path == "/manifest.webmanifest":
                return self._responder(pwa.manifiesto().encode("utf-8"),
                                       "application/manifest+json; charset=utf-8")
            if ruta.path == "/sw.js":
                return self._responder(pwa.SERVICE_WORKER.encode("utf-8"),
                                       "text/javascript; charset=utf-8")
            if ruta.path.lstrip("/") in pwa.ICONOS:
                return self._estatico(ruta.path.lstrip("/"), "image/png")
            if ruta.path == "/api/salud":
                return self._json({"ok": True, "hoy": date.today().isoformat()})
            return self._error("Ruta no encontrada", HTTPStatus.NOT_FOUND)
        except AgoraError as exc:
            return self._error(str(exc), HTTPStatus.BAD_GATEWAY)
        except BrokenPipeError:
            return
        except Exception as exc:  # el servidor local no debe caerse por una peticion
            return self._error(f"{type(exc).__name__}: {exc}")

    do_HEAD = do_GET

    def _estatico(self, nombre: str, tipo: str):
        ruta = (ESTATICOS / nombre).resolve()
        if not ruta.is_file() or ESTATICOS.resolve() not in ruta.parents:
            return self._error("No encontrado", HTTPStatus.NOT_FOUND)
        self._responder(ruta.read_bytes(), tipo)

    def _api_clases(self, consulta):
        p = _params(consulta)
        todas, clases = _consultar(p)
        self._json({
            "generado": date.today().isoformat(),
            "desde": api.parse_fecha(p["desde"]).isoformat(),
            "dias": p["dias"],
            "total": len(clases),
            "total_ventana": len(todas),
            "catalogo": api.catalogo(todas),
            "clases": [
                {k: v for k, v in c.as_dict().items() if k != "crudo"} | {"crudo": c.crudo}
                for c in clases
            ],
        })

    def _api_ics(self, consulta):
        _, clases = _consultar(_params(consulta))
        cuerpo = exportar.a_ics(clases).encode("utf-8")
        self._responder(cuerpo, "text/calendar; charset=utf-8", 200,
                        {"Content-Disposition": 'attachment; filename="agora-clases.ics"'})


def servir(host: str = "127.0.0.1", puerto: int = 8765, abrir: bool = True) -> int:
    try:
        servidor = ThreadingHTTPServer((host, puerto), Handler)
    except OSError as exc:
        print(f"error: no se pudo abrir {host}:{puerto} ({exc})", file=sys.stderr)
        return 1

    url = f"http://{host}:{servidor.server_port}/"
    print(f"AGORA horario en {url}   (Ctrl+C para parar)")
    if abrir:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nParado.")
    finally:
        servidor.server_close()
    return 0
