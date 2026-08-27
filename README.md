# agora-horario

Consulta el horario de actividades colectivas de **AGORA · We Granada** desde el
terminal, desde un navegador local o desde una página que puedes compartir.

Sin dependencias: solo Python 3.9 o superior.

```
./horario hoy                 # clases de hoy en el terminal
./horario web                 # interfaz web en http://127.0.0.1:8765
./horario publicar            # página autocontenida para compartir
```

## De dónde salen los datos

El endpoint que usa la web oficial:

```
https://agoragranada.provis.es/ActividadesColectivas/ClasesColectivasTimeLinePublic?fecha=AAAA-MM-DDT00:00:00&integration=true
```

No es una API JSON: devuelve la página HTML completa y los datos de cada clase
viajan serializados en el atributo `data-json` del botón de reserva, con 41
campos por clase. Cada petición cubre **7 días naturales** desde `fecha`; si la
fecha es pasada, el servidor la recorta a hoy. Para rangos mayores la aplicación
encadena peticiones de 7 en 7 y descarta duplicados por `Id`.

Dos límites que vienen de origen:

- **La ocupación no es pública.** `ReservasHechas` llega siempre a 0 sin sesión
  iniciada, así que solo se puede mostrar la capacidad de la sala.
- **Las imágenes no se sirven.** `GetImagenActividadColectiva` responde 200 con
  cuerpo vacío para usuarios anónimos.

Las respuestas se cachean 15 minutos en `~/.cache/agora-horario/`.

## Terminal

```
./horario hoy
./horario manana
./horario semana
./horario dia 2026-09-15
./horario rango --desde 2026-09-01 --dias 21
./horario info                        # catálogo de actividades, salas y monitores
```

Los desplegables de la interfaz salen en orden alfabético, ignorando tildes. El
resumen de `info`, en cambio, ordena por frecuencia, que es lo que se quiere ver
ahí.

Filtros, combinables entre sí y con cualquier comando (ignoran mayúsculas y tildes):

```
-a, --actividad TEXTO      -m, --monitor TEXTO      -s, --sala TEXTO
-b, --buscar TEXTO         --desde-hora HH:MM       --hasta-hora HH:MM
--min-duracion MIN         --proximas
```

`-m` busca tanto por el nombre corto como por el apellido, aunque el apellido no
se muestre. `-a`, `-m` y `-s` se pueden repetir para pedir varios valores. Dentro de un
mismo filtro los valores se suman (OR); entre filtros distintos se restringen
(AND). Así, `-a zumba -a pilates -s "sala 2"` da las clases de zumba **o**
pilates que además estén **en** la sala 2. La coincidencia es parcial, lo que de
paso recoge las variantes que el gestor de AGORA arrastra en los nombres
(`ZUMBA`, `ZUMBA.`, `ZUMBA_`).

Formatos de salida con `-f`: `tabla` (por defecto), `agenda`, `json`,
`json-crudo` (los 41 campos originales), `csv`, `ics`. Con `-o` se escribe a un
fichero.

```
./horario semana -a pilates -a yoga --desde-hora 18:00
./horario rango --dias 30 -m "teresa" -f ics -o pilates.ics
./horario semana -s piscina -f csv -o piscina.csv
```

## Interfaz web local

```
./horario web [--puerto 8765] [--host 127.0.0.1] [--no-abrir]
```

Filtros en vivo con **selección múltiple** en actividad, sala y monitor (cada
desplegable tiene su buscador y los valores elegidos aparecen como etiquetas
quitables), navegación por semanas, chips por día, panel de detalle con la
descripción y los datos crudos, y exportación a calendario de lo que haya
filtrado.

En pantallas estrechas la cabecera es pegajosa y los filtros se la comían: ahora
se pliegan tras un botón **Filtros** con el número de criterios activos, y al
abrirse flotan sobre la lista en vez de empujarla. La cabecera pasa de ocupar el
55 % de la pantalla de un móvil a un 23 %.

El botón de tema recorre tres estados —el del navegador, claro fijo y oscuro
fijo— y recuerda la elección en el navegador de quien mira. El servidor hace de proxy porque AGORA solo permite CORS desde el
origen exacto `http://localhost`, sin puerto: el navegador no puede llamar al
endpoint por su cuenta.

## Compartir

```
./horario publicar --dias 21 --sitio site                 # sitio instalable (PWA)
./horario publicar --dias 21 -o horario.html              # un fichero suelto
./horario publicar --dias 21 --fragmento -o pagina.html   # para artifact de Claude
```

Los datos van **incrustados en el HTML**: funciona sin servidor, sin conexión y
en cualquier hosting estático. Como es una instantánea, no se actualiza sola —
hay que regenerarla y volver a subirla.

De los monitores solo se publica el **nombre de pila**. Si dos comparten nombre
se añade la inicial del apellido (`MARIA G.`, `MARIA L.`), y si también coincide
la inicial, el apellido entero. Es un cálculo sobre el conjunto: que un nombre
choque o no depende de quién más haya en la ventana consultada. El nombre
completo se conserva en `Clase.monitor_completo`, que la app local usa para
buscar y para el panel de datos crudos, y que **no se incrusta** en la página
publicada.

Con `--sitio` se genera además el manifiesto, el service worker, los iconos y un
`robots.txt`, de modo que el navegador ofrece **instalarla como aplicación** (de
escritorio o de móvil) y se puede consultar sin conexión. El servidor local sirve
esas mismas piezas, así que desde `localhost` también se puede instalar.

Los iconos están versionados en `agora/static/`; para rehacerlos:
`python3 herramientas/generar_iconos.py`.

### Cautelas al publicar

El horario de AGORA es público, pero su `robots.txt` excluye a los rastreadores
y las descripciones de las actividades son textos con autor. Por eso la página
publicada lleva `noindex` y su propio `robots.txt`, y el cliente se identifica
con un User-Agent que apunta a este repositorio, para que quien mire los logs
sepa de dónde viene el tráfico. La descarga es de tres peticiones al día.

## Publicación automática

El workflow `.github/workflows/publicar.yml` regenera la instantánea de 21 días
cada mañana y la despliega en GitHub Pages. Al terminar actualiza y commitea
`ultima-actualizacion.json`, que deja constancia de cuándo se publicó y qué
cubría.

Ese commit no es cosmético: GitHub **desactiva los workflows programados de un
repositorio público tras 60 días sin actividad**, y las propias ejecuciones no
cuentan como actividad. El commit diario la genera. No provoca un bucle porque
los push hechos con `GITHUB_TOKEN` no disparan nuevas ejecuciones. Si aun así el
workflow apareciese desactivado: `gh workflow enable publicar.yml`.

## Estructura

| Fichero | Qué hace |
| --- | --- |
| `agora/api.py` | descarga, parseo del HTML, modelo `Clase`, filtros y caché |
| `agora/cli.py` | comandos y salida por terminal |
| `agora/web.py` | servidor local y proxy JSON/iCalendar |
| `agora/publicar.py` | generador de la página autocontenida |
| `agora/exportar.py` | JSON, CSV e iCalendar |
| `agora/pwa.py` | manifiesto, service worker y robots.txt del sitio |
| `herramientas/generar_iconos.py` | dibuja los PNG del icono (solo si cambia el diseño) |
| `.github/workflows/publicar.yml` | regenera y despliega la página cada día |
| `agora/static/index.html` | la interfaz, en modo servidor o instantánea |
