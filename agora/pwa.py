"""Piezas para que la pagina se pueda instalar como aplicacion.

Un navegador ofrece instalar una web cuando encuentra tres cosas: un manifiesto
con iconos, un service worker con manejador de fetch, y origen seguro (HTTPS o
localhost). Aqui estan las dos primeras; la tercera la ponen GitHub Pages y el
servidor local.
"""

from __future__ import annotations

import json

ACENTO = "#0E7C7B"
FONDO_CLARO = "#F1F4F3"
FONDO_OSCURO = "#0C1413"

ICONOS = ("icono-192.png", "icono-512.png", "icono-maskable-512.png")

MANIFIESTO = {
    "name": "Horario AGORA · We Granada",
    "short_name": "Horario AGORA",
    "description": "Horario de actividades colectivas del centro deportivo AGORA We Granada.",
    "lang": "es",
    # Relativos a proposito: la web vive en un subdirectorio en GitHub Pages.
    "start_url": "./",
    "scope": "./",
    "display": "standalone",
    "background_color": FONDO_OSCURO,
    "theme_color": ACENTO,
    "icons": [
        {"src": "icono-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "icono-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {"src": "icono-maskable-512.png", "sizes": "512x512", "type": "image/png",
         "purpose": "maskable"},
    ],
}

SERVICE_WORKER = """\
// Service worker de agora-horario.
// El horario es una instantanea que se regenera cada dia: por eso la pagina se
// pide primero a la red y la cache solo es el respaldo para verla sin conexion.
// Los iconos y las fuentes, que no cambian, van al reves.
const CACHE = "agora-v1";
const ESENCIALES = ["./", "./manifest.webmanifest", "./icono-192.png", "./icono-512.png"];

self.addEventListener("install", e => {
  e.waitUntil(
    caches.open(CACHE)
      .then(c => c.addAll(ESENCIALES))
      .catch(() => {})            // si algo no esta, se instala igual
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(claves => Promise.all(claves.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function guardar(peticion, respuesta) {
  if (respuesta && respuesta.ok) {
    const copia = respuesta.clone();
    caches.open(CACHE).then(c => c.put(peticion, copia)).catch(() => {});
  }
  return respuesta;
}

self.addEventListener("fetch", e => {
  const peticion = e.request;
  if (peticion.method !== "GET") return;
  const url = new URL(peticion.url);
  const estable = /fonts\\.(googleapis|gstatic)\\.com$/.test(url.hostname) ||
                  /\\.(png|webmanifest)$/.test(url.pathname);

  if (estable) {                                   // cache primero
    e.respondWith(
      caches.match(peticion).then(hit => hit || fetch(peticion).then(r => guardar(peticion, r)))
    );
    return;
  }
  e.respondWith(                                   // red primero
    fetch(peticion)
      .then(r => guardar(peticion, r))
      .catch(() => caches.match(peticion).then(hit => hit || caches.match("./")))
  );
});
"""

ROBOTS = """\
# Esta pagina reproduce el horario publico de AGORA (agoragranada.provis.es),
# cuyo robots.txt excluye a los rastreadores. Se excluye tambien aqui para no
# competir en buscadores con la web oficial.
User-agent: *
Disallow: /
"""

CABECERA = """\
    <link rel="manifest" href="manifest.webmanifest">
    <link rel="apple-touch-icon" href="icono-192.png">
    <meta name="theme-color" media="(prefers-color-scheme: light)" content="{claro}">
    <meta name="theme-color" media="(prefers-color-scheme: dark)" content="{oscuro}">
    <script>
      // Sin service worker la pagina funciona igual; solo se pierde el modo
      // sin conexion y la opcion de instalar.
      if ("serviceWorker" in navigator) {{
        addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {{}}));
      }}
    </script>"""


def manifiesto() -> str:
    return json.dumps(MANIFIESTO, ensure_ascii=False, indent=2) + "\n"


def cabecera() -> str:
    """Etiquetas que hay que meter en el <head> para poder instalarla."""
    return CABECERA.format(claro=FONDO_CLARO, oscuro=FONDO_OSCURO)
