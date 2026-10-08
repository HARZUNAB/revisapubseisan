# Manual técnico — RevisaPubSeisan

Arquitectura, scripts, interfaces y parámetros ajustables.
Versión 2.0 — 6 de octubre de 2026.

Documento de referencia para quien mantiene o extiende el sistema. Para el uso
diario, ver `manual_usuario.md`. El esquema de la base de datos está en
`esquema_seiscomp.md` (y su versión para MySQL Workbench en
`esquema_seiscomp_mysql.sql`).

---

## Índice

1. [Arquitectura general](#1-arquitectura-general)
2. [Inventario de módulos](#2-inventario-de-módulos)
3. [Directorios y archivos](#3-directorios-y-archivos)
4. [Flujo por etapa](#4-flujo-por-etapa)
5. [Interfaces de línea de comandos](#5-interfaces-de-línea-de-comandos)
6. [Conexión remota y base de datos](#6-conexión-remota-y-base-de-datos)
7. [Parámetros y dónde ajustarlos](#7-parámetros-y-dónde-ajustarlos)
8. [Entradas y formatos](#8-entradas-y-formatos)
9. [Cómo extender el sistema](#9-cómo-extender-el-sistema)
10. [Verificación y pruebas](#10-verificación-y-pruebas)

---

## 1. Arquitectura general

La aplicación es una **GUI de escritorio** (Tkinter + `ttkbootstrap`) que
**orquesta** módulos de proceso, cada uno ejecutado como **subproceso**
independiente. La GUI **no contiene lógica de negocio**: lanza cada script, lee
su salida estándar para mostrar progreso y registro, y muestra los resultados.

- **Directorio de trabajo**: los subprocesos se lanzan con
  `cwd=os.getcwd()`, así que las rutas relativas (`datos/`, `informes/`,
  `trabajo/`, `ploteo/`, `descargas/`) se resuelven **contra la carpeta desde
  donde se invocó la app**, no contra el código. Ejecutar siempre desde la carpeta
  del proyecto/ejecución.
- **Progreso**: los módulos que importan `prog` emiten líneas
  `@@PROGRESO@@ <fracción>` por stdout. `app.py` las reconoce y actualiza la
  barra. La emisión se activa con la variable de entorno **`RV_PROG`**, que la
  app define en cada subproceso; ejecutado a mano, un módulo no emite progreso.
- **Entregables**: la variable **`RV_ENTREGABLES=1`** habilita la escritura de
  los entregables automáticos del pipeline. Sin ella, esas escrituras van a un
  descarte (ver `rutas.entregable`).

### Mapa de alto nivel

```
supervisor.sh ──► crea .venv e instala requirements.txt
      │
      ▼
solicita_catalogos.py ──► ventana de solicitud (SSH/SCP + exportador SeisComp)
      │                     deja el estado en JSON y abre:
      ▼
app.py ──► ventana principal (orquesta subprocesos)
   ├─ análisis:  proc_query_harz_2 → revisaselect → revisacollect →
   │             compara → (atribución SeisComp) → revisaexcluidos →
   │             repetidosexclu → repetidos
   └─ paneles:   generajson (por fuente) → plotear / revisa_seiscomp
```

---

## 2. Inventario de módulos

| Módulo | Responsabilidad | Entradas | Salidas | Progreso |
|---|---|---|---|---|
| `app.py` | GUI: orquesta etapas, muestra registro y paneles. | `entrada.csv`, `salida.dat`, `estado.json` | — | — |
| `solicita_catalogos.py` | Ventana de solicitud y orquestación de la bajada. | período, contraseña, radio | `datos/select_*.out`, `datos/eventquery_*.csv`, export de SeisComp | — |
| `traer_catalogos.py` | Capa de red (SSH/SCP) sin GUI. | plantilla `select.inp`, fechas | `select.out`, CSV de eventquery | — |
| `rutas.py` | Rutas de salida y flag de entregables. | — | crea carpetas | — |
| `prog.py` | Protocolo `@@PROGRESO@@` por subproceso. | — | stdout | — |
| `proc_query_harz_2.py` | Normaliza el CSV público a formato Seisan y `.dat`. | CSV eventquery | `datos/new_2_*.csv`, `.dat` | Sí |
| `revisaselect.py` | Parsea `select.out`; separa válidos de excluidos. | `select.out` | `trabajo/newcollect.txt`, `trabajo/excluidostmp1.txt` | No |
| `revisacollect.py` | Arma el CSV maestro y los CSV por analista. | `trabajo/newcollect.txt` | `datos/salida_collect.csv` | No |
| `compara.py` | Compara público vs local: **no publicados** y **no actualizados**. | CSV público, CSV local | `datos/no_pub_desde_2_5_*.csv`, `datos/atribucion_*.csv`, `informes/no_act_*.txt` | Sí |
| `comparacion.py` | Comparación numérica de parámetros (funciones puras). | — | — | — |
| `revisaexcluidos.py` | Normaliza excluidos y detecta líneas anómalas. | `informes/excluidos.txt` | `datos/excluidos.csv` | No |
| `repetidos.py` | Detecta repetidos dentro de cada fuente (amplio/estricto). | CSV público, Seisan, SeisComp | `informes/rep_*.txt` | Sí |
| `repetidosexclu.py` | Cruza excluidos contra `select.out`. | CSV excluidos, CSV select | `informes/rep_seisan_exclu.txt` | Sí |
| `generajson.py` | Asigna perfil y clasifica sospechosos; escribe el JSON. | CSV de eventos | `datos/eventos_<vista>.json`, `datos/sospechosos_*.csv`, `datos/conteo_perfiles_*.json` | Sí |
| `asigna_perfiles.py` | Detecta perfiles y asigna uno por evento. | `grillas/slabP*.tmp`, `topoP*.tmp` | — | No |
| `sismicidad.py` | Clasifica un evento como **sospechoso**. | `base_2020_2026.dat` | — | No |
| `plotear.py` | Mapas y panel de análisis (matplotlib). | `eventos_<vista>.json` | figuras / descargas | No |
| `revisa_seiscomp.py` | Revisión de SeisComp: catálogo, parámetros, estaciones, análisis rápido, no actualizados. | CSV de SeisComp | tablas / descargas | — |
| `exporta_ventana_seiscomp.py` | Exporta eventos, fases y sin arribos desde la base de SeisComp. | base PostgreSQL | `datos/seiscomp_<ini>_<fin>*.csv` | — |
| `seiscomp_a_parametros.py` | Convierte la exportación cruda al CSV de 8 columnas. | export CSV | `datos/seiscomp_parametros.csv` | — |
| `verifica_entorno.py` | Diagnóstico de entorno (venv, paquetes, base). | `requirements.txt` | stdout | — |
| `ajuste.py` | Ajuste de tamaño de ventanas (solo crecen). | — | — | — |
| `traequery.py` | Bajada interactiva de eventquery (legado). | input() | CSV | — |
| `supervisor.sh` | Lanzador con entorno virtual. | `requirements.txt` | — | — |
| `seiscomp.sh` | Extracción SeisComp + revisión en un comando. | `catalogo.csv` | CSV por ventana | — |

> `entregables` (CSV/TXT) solo se escriben con `RV_ENTREGABLES=1`.

---

## 3. Directorios y archivos

`rutas.py` es la **fuente única** de las carpetas de salida (relativas al
directorio de trabajo):

| Carpeta | Contenido |
|---|---|
| `datos/` | CSV/JSON de trabajo: `salida_collect.csv`, `new_2_*.csv`, `excluidos.csv`, `seiscomp_parametros.csv`, `atribucion_*.csv`, `no_pub_desde_2_5_*.csv`, `eventos_<vista>.json`, `conteo_perfiles_<vista>.json`. |
| `informes/` | Reportes de texto: `no_pub_*.txt`, `no_act_*.txt`, `rep_*.txt`, `excluidos.txt`, `revisar.txt`. |
| `ploteo/` | Bitácora de la sesión: `percibidos.txt`. |
| `trabajo/` | Intermedios, que se renombran o borran al terminar cada etapa. |
| `descargas/` | Entregables a mano (los botones «Descargar») y los automáticos con `RV_ENTREGABLES=1`. |

Insumos de datos grandes, con rutas **ancladas al módulo** (no dependen del
directorio de trabajo):

| Archivo | Quién lo usa | Función |
|---|---|---|
| `grillas/slabP###.tmp`, `topoP###.tmp` | `asigna_perfiles.py`, `plotear.py` | Perfiles de subducción (pares slab/topo). |
| `base_2020_2026.dat` | `sismicidad.py`, `plotear.py` | Catálogo histórico de referencia. |
| `localidades.csv` | `plotear.py` | Puntos para rotular mapas. |
| `relieve_chile.tif` | `plotear.py` | Relieve regional. |
| `NE2_LR_LC_SR_W_DR.tif` | `plotear.py` | Relieve global de respaldo. |
| `plantillas/select.inp` | `traer_catalogos.py` | Plantilla del `select` de Seisan. |

---

## 4. Flujo por etapa

1. **`proc_query_harz_2.py`** — lee el CSV público, escribe un `.dat` con
   cabecera y `datos/new_2_<base>.csv` ordenado por hora.
2. **`revisaselect.py`** — parsea `select.out` y deja los eventos revisables en
   `trabajo/newcollect.txt`; los que no cumplen (sin agencia, sin magnitud, sin
   coordenadas o sin RMS) van a `informes/excluidos.txt`.
3. **`revisacollect.py`** — normaliza y escribe `datos/salida_collect.csv` (y,
   con entregables, un CSV por analista). Unifica nombres de analista con
   distancia de Levenshtein (`DISTANCIA_MAXIMA = 1`).
4. **`compara.py`** — compara el público contra el local. Un evento es el mismo
   si Δdía 0 y Δsegundos ≤ tolerancia, con Δlat/Δlon ≤ tolerancia (amplio y
   estricto). Escribe no publicados y **`datos/atribucion_<fuente>.csv`** (una
   fila por cruce, con `dt_seg`, `dlat`, `dlon` y los valores local/publicado).
5. **Atribución a SeisComp** — `seiscomp_a_parametros.py` convierte la
   exportación cruda y `compara.py` la usa como fuente.
6. **`revisaexcluidos.py`** — normaliza excluidos a `datos/excluidos.csv`.
7. **`repetidosexclu.py`** y **`repetidos.py`** — detectan repeticiones.
8. **`generajson.py`** — por fuente: asigna perfil (vía `asigna_perfiles.py`),
   clasifica sospechosos (vía `sismicidad.es_sospechoso`) y escribe
   `datos/eventos_<vista>.json` y `datos/conteo_perfiles_<vista>.json`.
9. **`plotear.py` / `revisa_seiscomp.py`** — dibujan los paneles con la GUI.

---

## 5. Interfaces de línea de comandos

Ningún módulo usa `argparse`: los argumentos son posicionales y las opciones se
escriben como `--clave=valor`.

| Comando | Efecto |
|---|---|
| `python3 app.py <entrada.csv> <salida.dat> [estado.json]` | Abre la GUI principal. |
| `python3 generajson.py <csv> <fuente> [--umbral=KM] [--k=K] [--umbral-perp=KM] [--margen-borde=KM] [--salida=NOMBRE]` | Genera JSON, CSV de sospechosos y conteo (`fuente`: seisan, seiscomp, eventquery, nopub). |
| `python3 plotear.py <eventos_<fuente>.json> <fuente>` | Abre los mapas de una fuente. |
| `python3 asigna_perfiles.py --listar` | Lista los perfiles detectados en `grillas/`. |
| `python3 asigna_perfiles.py <lon> <lat> <prof>` | Asigna un perfil a una coordenada. |
| `python3 sismicidad.py [-h] [<eventos_<fuente>.json>]` | Indica si cada evento es sospechoso. |
| `python3 compara.py <csv_publico> <csv_local> [prefijo]` | Compara y escribe reportes. |
| `python3 repetidos.py <csv_publico> <csv_seisan> [csv_seiscomp]` | Detecta repetidos. |
| `python3 repetidosexclu.py <csv_excluidos> <csv_select>` | Cruza excluidos con select. |
| `python3 exporta_ventana_seiscomp.py <catalogo.csv>` | Exporta la ventana de SeisComp. |
| `python3 seiscomp_a_parametros.py <exportacion.csv> [salida.csv]` | Convierte la exportación. |
| `python3 traequery.py` | Bajada interactiva de eventquery (legado). |
| `./seiscomp.sh <catalogo.csv> [--reexportar] [--solo-revision]` | Extracción + revisión. |
| `./supervisor.sh [<entrada.csv> <salida.dat>]` | Lanzador con `.venv`. |

---

## 6. Conexión remota y base de datos

### Servidor de catálogos (SSH/SCP) — `traer_catalogos.py`

- Servidor: `sysopr@10.54.217.9` (`traer_catalogos.py:43-44`).
- Directorio remoto: `tmp`.
- El catálogo público se baja con el binario remoto **`eventquery2`** (la versión
  vieja, `eventquery`, traía soluciones duplicadas).
- La contraseña se pasa con `SSH_ASKPASS` + `SSH_ASKPASS_REQUIRE=force`; no va por
  la línea de comandos.

### Base de SeisComp (PostgreSQL) — `exporta_ventana_seiscomp.py`

- Los parámetros de conexión salen de la línea `database` del `global.cfg` de
  SeisComp. Se busca en `$SEISCOMP_ROOT/etc/global.cfg` o
  `~/seiscomp/etc/global.cfg`.
- `NEWPT_DATA_DIR` fija el directorio de salida de los datos (gana sobre todo).
- Esquema detallado: `esquema_seiscomp.md`; script importable en MySQL Workbench:
  `esquema_seiscomp_mysql.sql`.

---

## 7. Parámetros y dónde ajustarlos

Todos los valores están como constantes de módulo (mayúsculas), fáciles de
ubicar y cambiar. Ubicación `archivo:línea` (puede variar con ediciones).

### Comparación y repetidos

| Constante | Archivo:línea | Valor | Efecto |
|---|---|---|---|
| `MAX_SEG_AMPLIO` | `compara.py:33`, `repetidos.py:21` | `6` | Tolerancia de tiempo (s) del filtro **amplio**. |
| `MAX_LAT_LON_AMPLIO` | `compara.py:34`, `repetidos.py:22` | `2.0` | Tolerancia de coordenadas (°) del amplio. |
| `MAX_SEG_ESTRICTO` | `compara.py:35`, `repetidos.py:23` | `3` | Tolerancia de tiempo (s) del **estricto**. |
| `MAX_LAT_LON_ESTRICTO` | `compara.py:36`, `repetidos.py:24` | `1.0` | Tolerancia de coordenadas (°) del estricto. |
| Magnitud mínima de CSV | `compara.py` (~217) | `2.5` | Umbral para escribir los CSV de no publicados. |

### Precisión de comparación (`comparacion.py`)

| Constante | Línea | Valor | Efecto |
|---|---|---|---|
| `DECIMALES_COORDENADA` | `26` | `3` | Decimales de normalización de lat/lon. |
| `DECIMALES_PROFUNDIDAD` | `27` | `1` | Decimales de profundidad (se compara ignorando el signo). |
| `DECIMALES_MAGNITUD` | `28` | `1` | Decimales de magnitud. |
| `TOLERANCIA_COORDENADA` | `36` | `0.005` | Tolerancia (°) al comparar lat/lon: cubre el redondeo del publicado a 2 decimales. |
| `RADIO_TIERRA_KM` | `39` | `6371.0088` | Radio terrestre para `distancia_km`. |

La función `distancia_km(lat1, lon1, lat2, lon2)` (`comparacion.py:153`) calcula
la distancia haversine que se muestra en la columna **Dist (km)** de «No
actualizados»; `compara.py` la escribe en `atribucion_<fuente>.csv` y
`revisa_seiscomp.py` la recalcula si el CSV es viejo.

### Asignación de perfiles (`asigna_perfiles.py`)

| Constante | Línea | Valor | Efecto |
|---|---|---|---|
| `UMBRAL_DIST_KM` | `89` | `110.0` | Distancia máxima (km) para asignar un perfil. |
| `UMBRAL_PERP_KM` | `96` | `None` | Tope lateral explícito (opcional). |
| `MARGEN_BORDE_KM` | `104` | `0.0` | Margen respecto del borde de la sección. |
| `K_PESO_PROFUNDIDAD` | `116` | `1.0` | Peso del residuo de profundidad en la distancia de asociación. |
| `ANCHO_BIN_KM` | `124` | `1.0` | Ancho de bin (km) al muestrear las grillas. |
| `GRADO_KM_LAT` / `GRADO_KM_LON` | `119-120` | `111.0` | Conversión grados→km. |

### Sospechosos (`sismicidad.py`)

`CRITERIOS_SOSPECHOSO` (`sismicidad.py:76-96`) define la regla efectiva:
`"regla": "ambos_grupos"` (sospechoso si se cumple ≥1 prueba del grupo `slab`
**y** ≥1 del grupo `historica`). Pruebas: `perp_max_km` (inactiva, 55.0),
`residuo_max_km` (**activa**, 30.0), `densidad_local` (inactiva), `knn`
(**activa**, k=5, 15 km), `ventana_aislamiento` (inactiva),
`desvio_mediana_prof` (inactiva). Además, **todo evento sin perfil es
sospechoso**.

### Exportación de SeisComp (`exporta_ventana_seiscomp.py`)

| Constante | Línea | Valor | Efecto |
|---|---|---|---|
| `RADIO_ESTACIONES_KM` | `182` | `400.0` | Radio por defecto de estaciones sin arribos. |
| `ACTIVIDAD_HORAS` | `190` | `24.0` | Semiancho de la ventana de actividad (±24 h). |
| `TAMANO_LOTE` | `165` | `5000` | Filas por lote de lectura. |
| `AVISO_DE_LOTES` | `169` | `200000` | Aviso de exportaciones grandes. |
| `NO_PICADAS_BYTES_FILA` | `1114` | `154` | Bytes/fila para estimar tamaño. |
| `AVISO_NO_PICADAS_MB` | `1118` | `200.0` | Aviso (MB) antes de exportar sin arribos. |

### Interfaz de revisión (`revisa_seiscomp.py`)

| Constante | Línea | Valor | Efecto |
|---|---|---|---|
| `MAX_FILAS` | `60` | `20000` | Máximo de filas mostradas en el panel. |
| `DECIMALES_COORD` | `89` | `3` | Decimales de coordenadas en pantalla. |
| `UMBRAL_CERCANO_KM` | `181` | `50.0` | Umbral de resaltado «cerca» (configurable en la ventana). |
| `ANCHO_ESTACIONES` | `188` | `1400` | Ancho por defecto de la ventana Estaciones. |
| `UMBRAL_AVISO_AMPLIADO` | `231` | `2000` | Filas que disparan el aviso al ampliar. |
| `COLUMNAS_*`, `DETALLE_GRUPOS` | — | — | Columnas y grupos del detalle. |
| `AYUDA_*` | — | — | Textos de ayuda de la interfaz. |

En la ventana **Estaciones del evento** hay dos controles de distancia distintos:
**«Radio a mostrar (km)»** recorta la lista exportada (reconstruye la tabla) y
**«Resaltar cerca ≤ (km)»** solo cambia el color. El retinte del umbral no
reconstruye: lo hace `_retintar_no_picadas(arbol, umbral_cercano)`, que reusa las
filas guardadas en el árbol (`arbol._filas_no_picadas`) para no perder scroll ni
selección; se dispara con retardo (300 ms) al editar el campo. El check
**«Solo cercanas»** agrega el recorte por el umbral cerca.

### Ajuste de ventanas (`ajuste.py`) y arranque (`app.py`)

| Constante | Archivo:línea | Valor | Efecto |
|---|---|---|---|
| `TOPE_MAXIMO` | `ajuste.py:39` | `(1920, 1080)` | Tope de crecimiento de ventanas. |
| `MARGEN` | `ajuste.py:43` | `40` | Margen contra el borde de pantalla. |
| `TAMANIO_INICIAL` | `app.py:86` | `(980, 820)` | Tamaño inicial de la ventana principal. |
| `GRUPOS_PESTANAS` | `app.py:165` | — | Agrupación de pestañas. |
| `REP_FILES` | `app.py:71` | — | Archivos de repetidos que muestra «Ver repetidos». |

### Dibujo (`plotear.py`)

| Constante | Línea | Valor | Efecto |
|---|---|---|---|
| `FIG_SIZE` | `57` | `(15, 7)` | Tamaño de la figura por perfil. |
| `FIG_SIZE_NACIONAL` | `63` | `(7.0, 13.0)` | Figura vertical del Territorio Nacional. |
| `DPI` | `72` | `100` | Resolución. |
| `PROF_MAX_KM` | `78` | `250` | Profundidad máxima del eje vertical. |
| `ALT_MAR_KM` | `82` | `15` | Km sobre el nivel del mar mostrados. |
| `MARGEN_PLANTA_GRADOS` | `86` | `0.6` | Margen en grados del recorte de relieve. |
| `NIVEL_GEO` | `97` | `"50m"` | Escala de costas/fronteras. |
| `MAX_EVENTOS_ETIQUETA` | `143` | `60` | Máximo de eventos con etiqueta de `id`. |
| `HIST_*`, `COLOR_*` | — | — | Estilo de sismicidad histórica y colores. |
| `TERRITORIO_*`, `RELIEVE_LOCAL` | — | — | Límites de territorios y recorte local. |

`plotear.abrir_eventos(eventos, fuente, perfiles=None)` dibuja **planta + perfil
de uno o más eventos sueltos**; `abrir_evento(evento, …)` es el caso de uno
(delega). Es lo que dispara el **doble clic** (o Enter) en los listados de No
publicados (`app.py`) y No actualizados (`revisa_seiscomp.py`). Con un evento:
comportamiento de siempre. Con dos que traen `rol` `'local'` y `'publicado'`
(comparación de un no actualizado): ubica **ambos** en el perfil del evento
local (con `asigna_perfiles.distancia_al_perfil`/`profundidad_slab_en`), los
pinta distinto (`_estilo_marcadores`: el Evento Seisan/SeisComp amarillo
relleno, el publicado como **anillo** —centro blanco, borde `COLOR_PUBLICADO`—),
dibuja la **línea
conectora** y el **Δ ubicación/prof/mag** (`_dibujar_diferencia`, en la esquina
inferior derecha; el Δ mag solo si difiere, con el tipo cuando cambia), y titula
con el catálogo local (`titulo`). El tipo de magnitud viaja en
`datos/atribucion_<fuente>.csv` (`tipo_mag_local`/`tipo_mag_eventquery`, los
escribe `compara.py`). Si el local
no tiene `perfil` (o falta profundidad), cae a `plotear_planta`. Los eventos de
esos listados **no llevan `id`**, así que no se etiquetan sobre el mapa ni
muestran la línea «id:» en la viñeta (`_marcadores_planta` y
`_texto_parametros_evento` omiten el id cuando falta).

---

## 8. Entradas y formatos

- **Exportación de SeisComp** (`datos/seiscomp_<ini>_<fin>.csv`): 16 columnas
  (`id_evento, id_origen, ot_utc, magnitud, tipo_magnitud, fases, rms, azgap,
  latitud, longitud, profundidad_km, agencia, operador, region, estatus,
  base_datos`). Ver `docs/esquema_seiscomp.md`.
- **Fases** (`..._fases.csv`): 33 columnas, con `modo_pick`, `pick_autor`,
  `pick_agencia`, `pick_metodo`, `usada`, etc.
- **Sin arribos** (`..._no_picadas.csv`): 19 columnas, con `distancia_km`,
  `streams_vigentes` y `actividad_ventana`.
- **`datos/atribucion_<fuente>.csv`**: una fila por cruce, con `fecha_local`,
  `lat_local`, `lon_local`, `prof_local`, `mag_local`, `*_eventquery`, `analista`,
  `dt_seg`.
- **`datos/no_pub_desde_2_5_*estricto.csv`**: `Fecha_Hora, Latitud, Longitud,
  Prof., Mag., Tipo_mag., Analista`.
- **`datos/eventos_<vista>.json`**: lista de eventos con `id`, `fecha hora`,
  `latitud`, `longitud`, `prof`, `magnitud`, `tipo`, `perfil`, `along_km`,
  `perp_km`, `residuo_km`, `dist_asoc`, `sospechoso`, `percibido`.
- **CSV vs TXT**: CSV usa `utf-8-sig` (BOM para Excel); TXT va sin BOM y separado
  por tabulaciones.

---

## 9. Cómo extender el sistema

- **Agregar una columna a una tabla**: añadir la tupla `(clave, título, ancho)`
  en la constante `COLUMNAS_*` correspondiente (`revisa_seiscomp.py`) y, si el
  valor necesita formato, actualizar la función `_valores_*` asociada.
- **Cambiar textos de ayuda**: constantes `AYUDA_*` en `revisa_seiscomp.py`.
- **Agregar una fuente/pestaña**: `VISTAS` y `GRUPOS_PESTANAS` en `app.py`.
- **Cambiar un umbral del flujo**: modificar la constante en su módulo (ver la
  tabla de la [sección 7](#7-parámetros-y-dónde-ajustarlos)).
- **Cambiar el esquema de SeisComp consultado**: las consultas están en
  `exporta_ventana_seiscomp.py` (`CONSULTA_*_SQL`), y la documentación en
  `docs/esquema_seiscomp.md`.

---

## 10. Verificación y pruebas

- **Diagnóstico de entorno**: `.venv/bin/python verifica_entorno.py` revisa el
  venv, los paquetes de `requirements.txt`, tkinter y la conexión a la base.
- **Pruebas del revisor**: la suite pura/GUI se ejecuta con
  `.venv/bin/python /tmp/opencode/verif_ventana_estaciones.py` (y las similares
  `verif_no_picadas.py`, `verif_exportacion.py`). Cubren las funciones de lógica
  sin pantalla y la construcción de las ventanas con `ttkbootstrap`.
- **Capturas de los manuales**: `docs/capturas/generar_capturas.py` regenera las
  imágenes de `docs/img/` con datos de demostración.
