#!/usr/bin/env python3
"""
plotear.py
==========
Plotea eventos de subducción sobre sus perfiles y la vista en planta,
usando matplotlib + cartopy (misma tecnología de mapasOPA/ploteo),
con los perfiles detectados dinámicamente desde la carpeta "grillas".

Uso:
    python3 plotear.py <archivo_json> <fuente>

    archivo_json : archivo JSON generado por generajson.py
                   (eventos_seisan.json o eventos_eventquery.json)
    fuente       : "seisan" | "eventquery"

Cada archivo JSON contiene UNA lista con todos los eventos, cada uno con su
campo "perfil" (id del perfil asignado o None si no corresponde a ninguno).
Este script agrupa los eventos en memoria por perfil y abre una ventana por
perfil (planta a la izquierda, perfil a la derecha). Los eventos sin perfil
se plotean solo sobre la planta.
"""

import os
import sys
import json
import math
import csv
import textwrap

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import cartopy.io.shapereader as shpreader
from PIL import Image
from adjustText import adjust_text

import asigna_perfiles as ap

Image.MAX_IMAGE_PIXELS = None  # desactiva el límite de seguridad de PIL


# =========================================================================
# PARÁMETROS CONFIGURABLES (EDITAR SEGÚN SEA NECESARIO)
# =========================================================================

# FIG_SIZE: tamaño (pulgadas) de la figura que se abre por perfil.
# La planta ocupa el subplot izquierdo y el perfil el derecho.
FIG_SIZE = (15, 7)

# FIG_SIZE_NACIONAL: tamaño (pulgadas) de la figura del mapa del Territorio
# Nacional (Chile completo, largo y angosto). Se usa una figura vertical para
# agrandar el mapa sin deformar su geografía (aspecto PlateCarree ~0.31).
# Configurable: subir la altura agranda el mapa (limitado por la pantalla).
FIG_SIZE_NACIONAL = (7.0, 13.0)

# ANCHO_TEXTO_NACIONAL: caracteres máximos por línea del texto que va a la
# izquierda del mapa Nacional (título + subtítulo). Se usa con textwrap.fill
# para que el texto no se monte sobre el mapa. Configurable.
ANCHO_TEXTO_NACIONAL = 30

# DPI: resolución de la figura. A mayor DPI, mapas más nítidos (y algo más
# lentos al dibujar). Default 100 (buen equilibrio pantalla).
DPI = 100

# PROF_MAX_KM: profundidad máxima (km) mostrada en el eje vertical del perfil.
# El eje va desde -PROF_MAX_KM (abajo) hasta ALT_MAR_KM (arriba).
PROF_MAX_KM = 250

# ALT_MAR_KM: kilómetros positivos por encima del nivel del mar que se muestran
# en la parte superior del perfil (para ver la topografía).
ALT_MAR_KM = 15

# MARGEN_PLANTA_GRADOS: margen en grados alrededor de la extensión del perfil
# para recortar la imagen de planta desde el relieve (local o global).
MARGEN_PLANTA_GRADOS = 0.6

# RESOLUCION_RELIEVE_PLANTA: alto (px) al que se redimensiona el recorte de
# relieve de la planta al proyectarlo. Controla la nitidez del fondo.
# Configurable: bajar a ~400-500 acelera bastante el render del fondo del mapa
# (el imshow) con una pérdida de nitidez apenas perceptible en pantalla;
# subir hacia 900/1000 la mejora para exportar/ampliar a costa de velocidad.
RESOLUCION_RELIEVE_PLANTA = 500

# NIVEL COASTLINE/BORDES como en capturar.py:
# NIVEL_GEO = "50m" coastlines y bordes de países.
NIVEL_GEO = "50m"

# COLOR_FRONTERA / GROSOR_FRONTERA / ESTILO_FRONTERA: estilo de las fronteras
# internacionales (Chile-Argentina/Perú/Bolivia) en la planta. Línea sólida,
# oscura y moderada para que se note sin recargar el mapa. Configurable.
COLOR_FRONTERA = '#000000'
GROSOR_FRONTERA = 1.2
ESTILO_FRONTERA = '-'

# COLOR_REGION / GROSOR_REGION / ESTILO_REGION: estilo de los límites internos
# de las regiones de Chile en la planta. Más tenues que las fronteras pero
# visibles, en línea segmentada. Configurable.
COLOR_REGION = '#202020'
GROSOR_REGION = 1.0
ESTILO_REGION = '--'

# COLOR_PERCIBIDO: color de relleno de los eventos percibidos (fuente
# eventquery, campo percibido="S"). Puede ser nombre o código hexadecimal.
COLOR_PERCIBIDO = "#c00000"

# COLOR_NO_PERCIBIDO: color de relleno del resto de los eventos (no
# percibidos o seisan).
COLOR_NO_PERCIBIDO = "#ffff00"

# COLOR_BORDE_SOSPECHOSO: color del borde de los eventos marcados como
# posiblemente mal localizados (campo sospechoso=True de generajson.py).
# El relleno conserva el color por percibido/no percibido; el borde violeta
# marca la sospecha sin tapar esa información.
COLOR_BORDE_SOSPECHOSO = "#7b1196"

# COLOR_RESALTADO: color del anillo que indica el evento seleccionado con un
# clic en el mapa (no se usa para clasificar eventos).
COLOR_RESALTADO = "#000080"

# COLOR_SLAB: color de la línea del slab en el perfil.
COLOR_SLAB = "black"

# COLOR_TOPO: color de la línea de topografía/batimetría en el perfil.
COLOR_TOPO = "black"

# MAX_EVENTOS_ETIQUETA: si el perfil tiene menos/igual cantidad de eventos,
# se muestran las etiquetas (id) junto a cada punto. Por encima del umbral
# se omiten: con muchas etiquetas son ilegibles y adjust_text (cuadrático
# en nº de textos) encarece mucho el ploteo.
# Configurable: subirlo etiqueta perfiles más densos (a costa de velocidad);
# bajarlo da mapas más rápidos y limpios.
MAX_EVENTOS_ETIQUETA = 60

# ITERACIONES_ADJUST_TEXT: iteraciones de adjust_text al acomodar etiquetas.
# Con 1-2 iteraciones el acomodo es casi igual (el coste dominante está en
# el primer pase) y el tiempo baja varios ordenes de magnitud.
# Configurable: rango útil 1-3 (más iteraciones = mejor reparto, más lento).
ITERACIONES_ADJUST_TEXT = 2

# ASPECTO_PLANTA_GRADOS: proporción fija ancho/alto (en grados) de la vista en
# planta, igual a la proporción de la caja del subplot (FIG_SIZE con 2 subplots
# → ~2:1). Con una proporción constante, todos los mapas de planta se renderizan
# con el MISMO tamaño en pantalla, sin deformación geográfica. La caja se
# centra en los eventos del perfil (el slab puede recortarse en extremos sin
# eventos). Configurable.
ASPECTO_PLANTA_GRADOS = 2.0


# =========================================================================
# RUTAS (resueltas respecto a este archivo, no al CWD)
# =========================================================================

# ARCHIVO_TIF_GLOBAL: relieve global (Natural Earth) de respaldo para la
# vista en planta, cuando el perfil queda fuera de la cobertura del recorte
# local de Chile.
ARCHIVO_TIF_GLOBAL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "NE2_LR_LC_SR_W_DR.tif")

# ARCHIVO_TIF_LOCAL: relieve pre-recortado a Chile (alta resolución, mucho
# más liviano y rápido). Se usa como prioridad; si no existe se usa el global.
ARCHIVO_TIF_LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "relieve_chile.tif")

# ARCHIVO_LOCALIDADES: archivo CSV con las localidades (ciudades/pueblos) y
# sus coordenadas, usado para marcar pueblos cercanos en la planta.
ARCHIVO_LOCALIDADES = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "localidades.csv")

# ARCHIVO_SISMICIDAD: catálogo de sismicidad histórica validada (solo
# referencia: fondo contextual en los mapas y estadísticas locales de
# clasificación en sismicidad.py). El catálogo jamás se clasifica.
ARCHIVO_SISMICIDAD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "base_2020_2026.dat")

# Parámetros visuales del fondo de sismicidad histórica (gris tenue uniforme).
HIST_COLOR = "0.55"
HIST_S = 8
HIST_S_PERFIL = 8
HIST_ALPHA = 0.35

# HIST_MAX_PERP_PROF_KM: solo se proyectan al perfil los eventos históricos
# dentro de esta distancia perpendicular (km) a la línea central del perfil,
# para no saturar el gráfico con eventos lejanos de la franja.
HIST_MAX_PERP_PROF_KM = 40.0

# Histórico: etiqueta de leyenda para el fondo de sismicidad histórica.
HIST_LABEL = "Sismicidad histórica 2020-2026"


# Constantes de la proyección local del recorte relieve_chile.tif (igual que
# en mapasOPA/ploteo/capturar.py).
RELIEVE_LOCAL = ((-97.0, -53.0), (-62.0, -4.0))  # (lon_min, lon_max), (lat_min, lat_max)

# Límites geográficos para los tres territorios de eventos sin perfil:
# 1. Territorio Nacional Chileno: margen continental donde se definen los perfiles
TERRITORIO_NACIONAL = ((-77.0, -66.0), (-56.0, -17.5))
# 2. Territorio Insular Chileno: Isla de Pascua y alrededores (Pacifico oriental)
TERRITORIO_INSULAR = ((-110.0, -72.0), (-45.0, -31.0))
# 3. Territorio Antártico Chileno: reclamo antártico chileno (53°W-90°W, 53°S-South Pole)
TERRITORIO_ANTARTICO = ((-76.0, -57.0), (-71.0, -53.0))

# TERRITORIOS: índice por nombre de los límites de cada territorio. Mismo
# formato que las constantes: (lon, lat) = ((lon_min, lon_max), (lat_min, lat_max)).
TERRITORIOS = {
    "Nacional": TERRITORIO_NACIONAL,
    "Insular": TERRITORIO_INSULAR,
    "Antártico": TERRITORIO_ANTARTICO,
}


def _cargar_relieve_planta(lon_min, lon_max, lat_min, lat_max):
    """
    Carga el recorte de relieve para la vista en planta.
    Prioriza el recorte local de Chile; si el área pedida queda fuera de su
    cobertura (o no existe), usa el relieve global NE2 como respaldo.
    Devuelve (img_rgb_resized, proyeccion) o (None, motivo) si falla.
    """
    archivo = None
    proyeccion = None

    local = RELIEVE_LOCAL
    (lon_min_r, lon_max_r), (lat_min_r, lat_max_r) = local
    dentro_local = (lon_min >= lon_min_r and lon_max <= lon_max_r and
                    lat_min >= lat_min_r and lat_max <= lat_max_r)

    if dentro_local and os.path.isfile(ARCHIVO_TIF_LOCAL):
        archivo = ARCHIVO_TIF_LOCAL
        proyeccion = ("local",) + tuple(local[0]) + tuple(local[1])
    elif os.path.isfile(ARCHIVO_TIF_GLOBAL):
        archivo = ARCHIVO_TIF_GLOBAL
        proyeccion = ("global",)

    if archivo is None:
        return None, "No se encontró ningún relieve (.tif) en el proyecto"

    try:
        base = Image.open(archivo)
        w, h = base.size
        if proyeccion[0] == "local":
            _, lon_min_r, lon_max_r, lat_min_r, lat_max_r = proyeccion
            x0 = int((lon_min - lon_min_r) / (lon_max_r - lon_min_r) * w)
            x1 = int((lon_max - lon_min_r) / (lon_max_r - lon_min_r) * w)
            y0 = int((lat_max_r - lat_max) / (lat_max_r - lat_min_r) * h)
            y1 = int((lat_max_r - lat_min) / (lat_max_r - lat_min_r) * h)
        else:
            x0 = int((lon_min + 180.0) / 360.0 * w)
            x1 = int((lon_max + 180.0) / 360.0 * w)
            y0 = int((90.0 - lat_max) / 180.0 * h)
            y1 = int((90.0 - lat_min) / 180.0 * h)
        x0 = max(0, min(w - 1, x0))
        x1 = max(x0 + 1, min(w, x1))
        y0 = max(0, min(h - 1, y0))
        y1 = max(y0 + 1, min(h, y1))
        if x1 <= x0 or y1 <= y0:
            raise ValueError("área fuera de la imagen")
        crop = base.crop((x0, y0, x1, y1))
        alto_deseado = RESOLUCION_RELIEVE_PLANTA
        ancho_deseado = max(1, int(crop.width * alto_deseado / max(crop.height, 1)))
        img = crop.resize((ancho_deseado, alto_deseado), Image.LANCZOS)
        return img.convert("RGB"), proyeccion
    except Exception as e:
        return None, "No se pudo proyectar el relieve .tif: %s" % e


def _color_evento(fuente, evento):
    """
    Color de RELLENO del evento según fuente y percibido. La sospecha (borde
    violeta) se maneja aparte como atributo del marcador.
    """
    if fuente == "eventquery" and evento.get('percibido') == "S":
        return COLOR_PERCIBIDO
    return COLOR_NO_PERCIBIDO


def _bordes_eventos(eventos):
    """Edgecolors y grosores de borde por evento en el mismo orden."""
    bordes = []
    grosores = []
    for ev in eventos:
        sospechoso = bool(ev.get('sospechoso'))
        bordes.append(COLOR_BORDE_SOSPECHOSO if sospechoso else 'black')
        grosores.append(2.2 if sospechoso else 1.2)
    return bordes, grosores


def _handles_eventos(fuente):
    """
    Handles de leyenda con los colores de los sismos según fuente.
    eventquery distingue no percibido/percibido; seisan usa un solo
    color ("Sismo registrado"). Ambos incluyen la sospecha (borde violeta,
    relleno según percibido/no percibido) y el anillo de selección.
    """
    from matplotlib.lines import Line2D
    handle_sospechoso = Line2D([0], [0], marker='o', color='w',
                               markerfacecolor=COLOR_NO_PERCIBIDO,
                               markeredgecolor=COLOR_BORDE_SOSPECHOSO,
                               markeredgewidth=2.2, markersize=8,
                               label="Sospechoso (borde violeta)")
    handle_seleccion = Line2D([0], [0], marker='o', color='w',
                              markerfacecolor='none',
                              markeredgecolor=COLOR_RESALTADO,
                              markeredgewidth=2.2, markersize=8,
                              label="Evento seleccionado")
    if fuente == "eventquery":
        handles = [
            Line2D([0], [0], marker='o', color='w',
                   markerfacecolor=COLOR_NO_PERCIBIDO, markeredgecolor='black',
                   markersize=8, label="Sismo no percibido"),
            Line2D([0], [0], marker='o', color='w',
                   markerfacecolor=COLOR_PERCIBIDO, markeredgecolor='black',
                   markersize=8, label="Sismo percibido"),
            handle_sospechoso,
            handle_seleccion,
        ]
    else:
        handles = [
            Line2D([0], [0], marker='o', color='w',
                   markerfacecolor=COLOR_NO_PERCIBIDO, markeredgecolor='black',
                   markersize=8, label="Sismo registrado"),
            handle_sospechoso,
            handle_seleccion,
        ]
    return handles


# =========================================================================
# FONDO DE SISMICIDAD HISTÓRICA (base_2020_2026.dat, solo referencia)
# =========================================================================

_cache_sismicidad = None
_cache_hist_perfil = {}


def _cargar_sismicidad():
    """
    Lee el catálogo histórico (tab-separado; cols 1=lat, 2=lon, 3=prof, 4=mag)
    y lo guarda en caché de módulo. Devuelve (lats, lons, profs) o None si el
    archivo no existe o no tiene eventos válidos. Es SOLO fondo/referencia:
    estos eventos no se clasifican como sospechosos.
    """
    global _cache_sismicidad
    if _cache_sismicidad is not None:
        return _cache_sismicidad
    if not os.path.isfile(ARCHIVO_SISMICIDAD):
        _cache_sismicidad = None
        return None

    lats, lons, profs = [], [], []
    with open(ARCHIVO_SISMICIDAD, encoding='utf-8') as f:
        for linea in f:
            partes = linea.strip().split('\t')
            if len(partes) < 7:
                continue
            try:
                lats.append(float(partes[1]))
                lons.append(float(partes[2]))
                profs.append(float(partes[3]))
            except ValueError:
                continue

    if not lats:
        _cache_sismicidad = None
        return None
    _cache_sismicidad = (np.array(lats), np.array(lons), np.array(profs))
    return _cache_sismicidad


def _handle_sismicidad():
    """Handle de leyenda para el fondo de sismicidad histórica."""
    from matplotlib.lines import Line2D
    return Line2D([0], [0], marker='o', color='w',
                  markerfacecolor=HIST_COLOR, markeredgecolor='none',
                  markersize=6, label=HIST_LABEL)


def _sismicidad_planta(ax, lon_min, lon_max, lat_min, lat_max):
    """
    Dibuja el fondo de sismicidad histórica en la vista en planta (gris tenue,
    zorder=1), filtrando por la extensión visible.
    """
    datos = _cargar_sismicidad()
    if datos is None:
        return
    lats, lons, profs = datos
    mask = ((lons >= lon_min) & (lons <= lon_max) &
            (lats >= lat_min) & (lats <= lat_max))
    if not np.any(mask):
        return
    ax.scatter(lons[mask], lats[mask], s=HIST_S, color=HIST_COLOR,
               alpha=HIST_ALPHA, linewidths=0, zorder=1, rasterized=True,
               transform=ccrs.PlateCarree())


def _proyectar_hist_perfil(lons, lats, profs, perfil):
    """
    Proyección vectorizada de los eventos históricos a un perfil: posición a
    lo largo (km) y distancia perpendicular (km), replicando la geometría de
    ap.distancia_al_perfil sobre todo el catálogo a la vez (loop por tramo,
    numpy escalar por punto). Devuelve (alongs, profs_neg) con los eventos
    dentro de HIST_MAX_PERP_PROF_KM (listas vacías si el perfil no sirve).
    """
    slab = perfil["slab"]
    lon_c = slab["lon"]
    lat_c = slab["lat"]
    p_c = slab["p"]
    if len(lon_c) < 2:
        return [], []
    lon_c = np.asarray(lon_c, dtype=float)
    lat_c = np.asarray(lat_c, dtype=float)
    p_c = np.asarray(p_c, dtype=float)
    lon_ref = float(np.nanmean(lon_c))
    lat_ref = float(np.nanmean(lat_c))

    x_c, y_c = ap._proyectar_a_plano(lon_c, lat_c, lon_ref, lat_ref)
    x_p, y_p = ap._proyectar_a_plano(np.asarray(lons, dtype=float),
                                     np.asarray(lats, dtype=float),
                                     lon_ref, lat_ref)
    x_p = np.asarray(x_p, dtype=float)
    y_p = np.asarray(y_p, dtype=float)

    dx = np.diff(x_c)
    dy = np.diff(y_c)
    seg_len2 = dx * dx + dy * dy
    n = x_p.shape[0]
    mejor = np.full(n, np.inf)
    mejor_i = np.zeros(n, dtype=np.intp)
    for i in range(dx.shape[0]):
        vx = x_p - x_c[i]
        vy = y_p - y_c[i]
        t = (vx * dx[i] + vy * dy[i]) / np.where(seg_len2[i] > 0,
                                                 seg_len2[i], 1.0)
        t = np.clip(t, 0.0, 1.0)
        fx = x_c[i] + t * dx[i]
        fy = y_c[i] + t * dy[i]
        d2 = (x_p - fx) ** 2 + (y_p - fy) ** 2
        idx = d2 < mejor
        if idx.any():
            mejor[idx] = d2[idx]
            mejor_i[idx] = i

    perp = np.sqrt(mejor)
    mask = perp <= HIST_MAX_PERP_PROF_KM
    if not mask.any():
        return [], []
    i = mejor_i[mask]
    seg_len2_i = np.where(seg_len2[i] > 0, seg_len2[i], 1.0)
    tm = np.clip(((x_p[mask] - x_c[i]) * dx[i] +
                  (y_p[mask] - y_c[i]) * dy[i]) / seg_len2_i, 0.0, 1.0)
    along = p_c[i] + tm * (p_c[i + 1] - p_c[i])
    profs_neg = -np.asarray(profs, dtype=float)[mask]
    return along.tolist(), profs_neg.tolist()


def _sismicidad_perfil(ax_perfil, perfil):
    """
    Dibuja el fondo de sismicidad histórica en el perfil (derecha): proyecta
    el catálogo al perfil (según la perpendicular al slab) y plotea los que
    quedan dentro de HIST_MAX_PERP_PROF_KM. Usa caché por perfil.
    """
    datos = _cargar_sismicidad()
    if datos is None:
        return
    clave = perfil["id"]
    if clave in _cache_hist_perfil:
        alongs, profs_neg = _cache_hist_perfil[clave]
    else:
        lats, lons, profs = datos
        alongs, profs_neg = _proyectar_hist_perfil(lons, lats, profs, perfil)
        _cache_hist_perfil[clave] = (alongs, profs_neg)
    if alongs:
        ax_perfil.scatter(alongs, profs_neg, s=HIST_S_PERFIL, color=HIST_COLOR,
                          alpha=HIST_ALPHA, linewidths=0, zorder=1,
                          rasterized=True)


_cache_regiones = None


def _cargar_regiones_chile():
    """
    Límites internos de las regiones de Chile (Natural Earth 10m
    'admin_1_states_provinces_lines'). Se leen con pyshp porque el lector de
    cartopy falla por un registro con geometría nula. Devuelve una lista de
    shapely geometries, cacheada en memoria. Si no se puede cargar, devuelve
    [] (el mapa queda sin regiones, no rompe).
    """
    global _cache_regiones
    if _cache_regiones is not None:
        return _cache_regiones
    try:
        import shapefile
        from shapely.geometry import shape
        ruta = shpreader.natural_earth(
            resolution='10m', category='cultural',
            name='admin_1_states_provinces_lines')
        r = shapefile.Reader(ruta)
        i_adm = [f[0] for f in r.fields[1:]].index('ADM0_A3')
        geoms = []
        for sr in r.iterShapeRecords():
            if sr.record[i_adm] != 'CHL':
                continue
            if sr.shape.shapeType == 0 or len(sr.shape.points) == 0:
                continue
            g = shape(sr.shape.__geo_interface__)
            if not g.is_empty:
                geoms.append(g)
        _cache_regiones = geoms
    except Exception as e:
        print("[Aviso] No se pudieron cargar las regiones: %s" % e)
        _cache_regiones = []
    return _cache_regiones


def _base_mapa_planta(ax, lon_min, lon_max, lat_min, lat_max):
    """
    Dibuja el fondo de la planta en el axes cartopy: relieve, costas, bordes
    administrativos y grilla con etiquetas.
    """
    ax.set_extent([lon_min, lon_max, lat_min, lat_max], crs=ccrs.PlateCarree())

    img, proyeccion = _cargar_relieve_planta(lon_min, lon_max, lat_min, lat_max)
    if img is not None:
        try:
            img_array = np.asarray(img)
            ax.imshow(img_array, origin='upper',
                      extent=[lon_min, lon_max, lat_min, lat_max],
                      transform=ccrs.PlateCarree())
        except Exception as e:
            print("[Aviso] No se pudo mostrar el relieve: %s" % e)
            ax.patch.set_facecolor("#f7f7f4")
    else:
        ax.patch.set_facecolor("#f7f7f4")

    ax.add_feature(cfeature.COASTLINE.with_scale(NIVEL_GEO),
                   edgecolor='#111111', linewidth=1.1, zorder=2)
    ax.add_feature(cfeature.BORDERS.with_scale(NIVEL_GEO),
                   edgecolor=COLOR_FRONTERA, linestyle=ESTILO_FRONTERA,
                   linewidth=GROSOR_FRONTERA, zorder=2)

    regiones = _cargar_regiones_chile()
    if regiones:
        ax.add_geometries(regiones, crs=ccrs.PlateCarree(),
                          edgecolor=COLOR_REGION, linestyle=ESTILO_REGION,
                          linewidth=GROSOR_REGION, facecolor='none', zorder=2)

    gl = ax.gridlines(draw_labels=True, linestyle='--', alpha=0.5,
                      color='#444444', zorder=4)
    gl.top_labels = False
    gl.right_labels = False
    gl.xlabel_style = {'size': 8.5, 'weight': 'bold'}
    gl.ylabel_style = {'size': 8.5, 'weight': 'bold'}


def _marcadores_planta(ax, eventos, fuente):
    """
    Plotea los eventos (scatter con picker + etiqueta de id) sobre la planta.
    Devuelve (scatter, eventos_plot) para habilitar la selección interactiva.
    """
    eventos_plot = []
    for e in eventos:
        try:
            float(e['longitud'])
            float(e['latitud'])
        except (TypeError, ValueError, KeyError):
            continue
        eventos_plot.append(e)

    if not eventos_plot:
        return None, []

    lons = [float(e['longitud']) for e in eventos_plot]
    lats = [float(e['latitud']) for e in eventos_plot]

    colores = [_color_evento(fuente, e) for e in eventos_plot]
    bordes, grosores = _bordes_eventos(eventos_plot)
    scatter = ax.scatter(lons, lats, s=60, c=colores, alpha=0.95,
                         edgecolors=bordes, linewidths=grosores, zorder=5,
                         transform=ccrs.PlateCarree(), picker=True,
                         pickradius=6)

    textos = []
    # Etiquetas (id) solo si la cantidad de eventos lo permite (umbral
    # configurable MAX_EVENTOS_ETIQUETA). Por encima se omiten: son ilegibles
    # y adjust_text (cuadrático) vuelve lento el ploteo.
    if len(eventos_plot) <= MAX_EVENTOS_ETIQUETA:
        for e in eventos_plot:
            try:
                t = ax.text(float(e['longitud']), float(e['latitud']),
                            str(e.get('id', '')), fontsize=7, zorder=6,
                            transform=ccrs.PlateCarree())
                textos.append(t)
            except (TypeError, ValueError):
                continue
    if textos:
        try:
            # Acomoda las etiquetas evitando solapamientos. Valores
            # configurables: expand (margen de separación, en fracción del
            # tamaño de la etiqueta), min_arrow_len=0 (dibuja la flecha
            # conectora al punto en TODAS las etiquetas; aumentarlo la dibuja
            # solo cuando la etiqueta realmente se movió) e
            # iter_lim=ITERACIONES_ADJUST_TEXT (control de rendimiento).
            adjust_text(textos, ax=ax, expand=(1.2, 1.4), min_arrow_len=0,
                        iter_lim=ITERACIONES_ADJUST_TEXT,
                        arrowprops=dict(arrowstyle="-", color='black',
                                        lw=0.5, alpha=0.6))
        except Exception:
            pass

    return scatter, eventos_plot


def _localidades_planta(ax, lon_min, lon_max, lat_min, lat_max, territorio=None):
    """Marca las localidades que caen dentro del área visible de la planta."""
    if not os.path.isfile(ARCHIVO_LOCALIDADES):
        return
    if territorio is not None:
        return
    try:
        with open(ARCHIVO_LOCALIDADES, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                nombre = row['Nombre']
                try:
                    lon_loc = float(row['Lon'])
                    lat_loc = float(row['Lat'])
                except (TypeError, ValueError):
                    continue
                if (lon_min <= lon_loc <= lon_max and
                        lat_min <= lat_loc <= lat_max):
                    ax.plot(lon_loc, lat_loc, 'o', color='black',
                            markersize=3, transform=ccrs.PlateCarree(),
                            zorder=6)
                    ax.text(lon_loc + 0.08, lat_loc + 0.04, nombre,
                            fontsize=8, fontweight='bold', color='black',
                            transform=ccrs.PlateCarree(), zorder=7,
                            path_effects=None)
    except Exception as e:
        print("[Aviso] No se pudieron cargar las localidades: %s" % e)



def _extent_planta_por_eventos(eventos, perfil=None, territorio=None, margen_adicional=None):
    """
    Calcula el área visible de la vista en planta con proporción fija
    (ASPECTO_PLANTA_GRADOS), centrada en los eventos del perfil.

    Recopila las coordenadas válidas de los eventos (rellenando con el slab
    si el perfil no tiene eventos con coordenadas), expande con el margen de
    planta y ajusta la extensión para que ancho/alto en grados sea exactamente
    ASPECTO_PLANTA_GRADOS. Así todos los mapas se renderizan igual de grandes.

    Si se proporciona 'territorio', también se consideran sus límites por
    defecto para asegurar que el mapa cubra el área del territorio, haciendo
    los márgenes dinámicos para adaptarse a eventos fuera de esos límites.
    Devuelve (lon_min, lon_max, lat_min, lat_max).
    """
    lons = []
    lats = []
    for ev in eventos:
        try:
            lons.append(float(ev['longitud']))
            lats.append(float(ev['latitud']))
        except (TypeError, ValueError, KeyError):
            continue

    if not lons and perfil is not None:
        lon_s = perfil["slab"]["lon"]
        lat_s = perfil["slab"]["lat"]
        lons = [float(x) for x in lon_s if not np.isnan(x)]
        lats = [float(x) for x in lat_s if not np.isnan(x)]

    if not lons:
        if territorio is not None:
            return _extent_territorio(territorio, margen=margen_adicional)
        return None

    margen = MARGEN_PLANTA_GRADOS if margen_adicional is None else margen_adicional
    lon_min_e = min(lons)
    lon_max_e = max(lons)
    lat_min_e = min(lats)
    lat_max_e = max(lats)

    if territorio is not None and territorio in TERRITORIOS:
        ((tlon_min, tlon_max), (tlat_min, tlat_max)) = TERRITORIOS[territorio]
        lon_min = min(lon_min_e, tlon_min)
        lon_max = max(lon_max_e, tlon_max)
        lat_min = min(lat_min_e, tlat_min)
        lat_max = max(lat_max_e, tlat_max)
    else:
        lon_min = lon_min_e
        lon_max = lon_max_e
        lat_min = lat_min_e
        lat_max = lat_max_e

    lon_min = lon_min - margen
    lon_max = lon_max + margen
    lat_min = lat_min - margen
    lat_max = lat_max + margen

    if territorio is not None:
        return (lon_min, lon_max, lat_min, lat_max)

    ancho = lon_max - lon_min
    alto = lat_max - lat_min
    if ancho <= 0 or alto <= 0:
        return None

    # Proporción fija ancho/alto en grados.
    objetivo = ASPECTO_PLANTA_GRADOS
    if ancho / alto < objetivo:
        ancho = alto * objetivo
    else:
        alto = ancho / objetivo

    lon_centro = (lon_min + lon_max) / 2.0
    lat_centro = (lat_min + lat_max) / 2.0
    return (lon_centro - ancho / 2.0, lon_centro + ancho / 2.0,
            lat_centro - alto / 2.0, lat_centro + alto / 2.0)


def _raiz_tk():
    """Devuelve la ventana raíz Tk compartida de matplotlib (TkAgg) o None."""
    try:
        import tkinter
        fm = plt.get_current_fig_manager()
        win = fm.window
        top = win.winfo_toplevel()
        if isinstance(top, tkinter.Tk):
            return top
        raiz = top.master
        while raiz is not None and not isinstance(raiz, tkinter.Tk):
            raiz = raiz.master
        return raiz
    except Exception:
        return None


def _texto_extencion(lon_min, lon_max, lat_min, lat_max):
    """Devuelve un str con la extensión geográfica en grados y km."""
    lat_med = (lat_min + lat_max) / 2.0
    lon_km = (lon_max - lon_min) * 111.0 * max(0.1, math.cos(math.radians(lat_med)))
    lat_km = (lat_max - lat_min) * 111.0
    return ("Lon %.1f° a %.1f° | Lat %.1f° a %.1f° (≈ %d × %d km)"
            % (lon_min, lon_max, lat_min, lat_max, round(lon_km), round(lat_km)))


def _texto_parametros_evento(ev):
    """Texto multilínea con los parámetros del evento para la viñeta."""
    lineas = [
        "id: %s" % ev.get('id', ''),
        "fecha hora: %s" % ev.get('fecha hora', ''),
        "lat: %s   lon: %s" % (ev.get('latitud', ''), ev.get('longitud', '')),
        "prof: %s km" % ev.get('prof', ''),
        "magnitud: %s   tipo: %s" % (ev.get('magnitud', ''), ev.get('tipo', '')),
    ]
    if 'percibido' in ev:
        lineas.append("percibido: %s" % ev['percibido'])
    if ev.get('analista'):
        lineas.append("analista: %s" % ev['analista'])
    if ev.get('perfil') is not None:
        lineas.append("perfil: %s   along: %s km"
                      % (ev.get('perfil'), ev.get('along_km', '')))
    return "\n".join(lineas)

def _distancia_a_rectangulo(lon, lat, limites):
    """Distancia mínima (grados) de un punto (lon, lat) a una caja geográfica."""
    (lon_min, lon_max), (lat_min, lat_max) = limites
    dx = max(lon_min - lon, 0.0, lon - lon_max)
    dy = max(lat_min - lat, 0.0, lat - lat_max)
    return math.sqrt(dx * dx + dy * dy)


def _categorizar_por_territorio(eventos):
    """Categoriza eventos sin perfil en los 3 territorios definidos.

    Los eventos que no caen dentro de los límites por defecto de NINGÚN
    territorio se asignan al territorio cuya caja les queda más cerca, para
    que nunca queden fuera de los mapas; su mapa se expande dinámicamente
    para incluirlos. Se imprime un aviso en consola cuando esto ocurre.
    """
    resultado = {nombre: [] for nombre in TERRITORIOS}
    fuera = []

    for ev in eventos:
        try:
            lon = float(ev['longitud'])
            lat = float(ev['latitud'])
        except (TypeError, ValueError, KeyError):
            continue

        for nombre, limites in TERRITORIOS.items():
            (lon_min, lon_max), (lat_min, lat_max) = limites
            if lon_min <= lon <= lon_max and lat_min <= lat <= lat_max:
                resultado[nombre].append(ev)
                break
        else:
            fuera.append((ev, lon, lat))

    for ev, lon, lat in fuera:
        mejor_nombre = None
        mejor_dist = None
        for nombre, limites in TERRITORIOS.items():
            d = _distancia_a_rectangulo(lon, lat, limites)
            if mejor_dist is None or d < mejor_dist:
                mejor_dist = d
                mejor_nombre = nombre
        resultado[mejor_nombre].append(ev)
        print("[Aviso] Evento %s (%.2f, %.2f) fuera de los límites por defecto; "
              "asignado al territorio '%s' (a ~%d km). El mapa se expandirá."
              % (ev.get('id'), lat, lon, mejor_nombre,
                 round(mejor_dist * 111.0)))

    return resultado["Nacional"], resultado["Insular"], resultado["Antártico"]


def _extent_territorio(nombre, margen=None):
    """
    Devuelve la extensión geográfica completa de un territorio sin forzar
    proporción: (lon_min, lon_max, lat_min, lat_max). 'nombre' debe ser una
    clave de TERRITORIOS. 'margen' en grados alrededor de los límites.
    """
    if nombre not in TERRITORIOS:
        return None
    if margen is None:
        margen = MARGEN_PLANTA_GRADOS
    ((lon_min, lon_max), (lat_min, lat_max)) = TERRITORIOS[nombre]
    return (lon_min - margen, lon_max + margen,
            lat_min - margen, lat_max + margen)


def _limpiar_resaltado(ax):
    """Elimina anillos de selección y viñetas marcados en 'ax'."""
    for coll in list(ax.collections):
        if getattr(coll, '_es_resaltado', False):
            coll.remove()
    for t in list(ax.texts):
        if getattr(t, '_es_anotacion', False):
            t.remove()


def _resaltar_evento(ax, ev, lon=None, lat=None, x_km=None, prof_km=None,
                     anotar=True):
    """
    Dibuja un anillo grande resaltando el evento seleccionado y, si 'anotar',
    una viñeta con sus parámetros cerca del círculo.
    """
    # Elimina resaltados y viñetas previos en el mismo axes
    _limpiar_resaltado(ax)

    contenido = _texto_parametros_evento(ev)

    if lon is not None and lat is not None:
        sc = ax.scatter([lon], [lat], s=220, facecolors='none',
                        edgecolors=COLOR_RESALTADO, linewidths=2.5, zorder=12,
                        transform=ccrs.PlateCarree(), picker=False)
        if anotar:
            anot = ax.annotate(
                contenido, xy=(lon, lat), xytext=(0, 25),
                textcoords='offset points', fontsize=8, color='black',
                bbox=dict(boxstyle='round,pad=0.4', fc='lightyellow',
                          ec='navy', alpha=0.95),
                arrowprops=dict(arrowstyle='-', color='navy', lw=0.8),
                zorder=13, clip_on=False, transform=ccrs.PlateCarree())
    elif x_km is not None and prof_km is not None:
        sc = ax.scatter([x_km], [prof_km], s=220, facecolors='none',
                        edgecolors=COLOR_RESALTADO, linewidths=2.5, zorder=12,
                        picker=False)
        if anotar:
            anot = ax.annotate(
                contenido, xy=(x_km, prof_km), xytext=(0, 25),
                textcoords='offset points', fontsize=8, color='black',
                bbox=dict(boxstyle='round,pad=0.4', fc='lightyellow',
                          ec='navy', alpha=0.95),
                arrowprops=dict(arrowstyle='-', color='navy', lw=0.8),
                zorder=13, clip_on=False)
    else:
        return
    sc._es_resaltado = True
    if anotar:
        anot._es_anotacion = True


def _resaltar_en_axes(ax, ev, anotar=False):
    """Resalta 'ev' en 'ax' (planta cartopy o perfil rectilineo).

    'anotar' controla si además del anillo se dibuja la viñeta con los
    parámetros del evento (solo en el mapa clicado).
    """
    if ax.name.startswith('cartopy'):
        try:
            _resaltar_evento(ax, ev, lon=float(ev['longitud']),
                             lat=float(ev['latitud']), anotar=anotar)
        except (TypeError, ValueError, KeyError):
            pass
    else:
        try:
            _resaltar_evento(ax, ev, x_km=float(ev.get('along_km')),
                             prof_km=float(ev['prof']) * -1,
                             anotar=anotar)
        except (TypeError, ValueError, KeyError):
            pass


def _buscar_mismo_evento(ev, lista):
    """Devuelve el evento equivalente a 'ev' dentro de 'lista', o None."""
    for e in lista:
        if e is ev:
            return e
    ident = ev.get('id')
    if ident is not None:
        for e in lista:
            if e.get('id') == ident:
                return e
    return None


def _conectar_seleccion_eventos(fig, ax, scatter, eventos_plot,
                                contraparte=None):
    """
    Conecta clics sobre un scatter para resaltar un evento y mostrar su
    viñeta de parámetros.

    Usa deteccion propia (scatter.contains) en button_press/button_release,
    independiente del widgetlock del toolbar: la seleccion funciona tambien
    mientras el modo zoom/pan esta activo (matplotlib ignora los clics simples
    de < 5 px en esos modos, asi no hay conflicto). Si 'contraparte' es
    (ax2, eventos2), resalta el mismo evento en el otro mapa con el mismo
    anillo (mismo tamano y color); la viñeta solo aparece en el mapa clicado.
    Un clic en espacio vacio (fuera de cualquier circulo) elimina la viñeta y
    los anillos de ambos mapas.
    """
    presion = {'x': None, 'y': None}

    def on_press(evento):
        if getattr(evento, 'x', None) is None:
            return
        if getattr(evento, 'inaxes', None) is not ax:
            return
        presion['x'] = evento.x
        presion['y'] = evento.y

    def on_release(evento):
        if presion['x'] is None:
            return
        if getattr(evento, 'inaxes', None) is not ax:
            return
        dx = abs(evento.x - presion['x'])
        dy = abs(evento.y - presion['y'])
        presion['x'] = None
        presion['y'] = None
        if dx >= 5 or dy >= 5:
            return  # fue un drag (zoom/pan), no un clic simple
        if getattr(evento, 'button', 1) not in (1, None):
            return
        cont = scatter.contains(evento)
        if not cont[0]:
            _limpiar_resaltado(ax)
            if contraparte is not None:
                ax2, _ = contraparte
                if ax2 is not None:
                    _limpiar_resaltado(ax2)
            fig.canvas.draw_idle()
            return
        ind = cont[1]['ind']
        if not len(ind):
            return
        idx = int(ind[0])
        if idx >= len(eventos_plot):
            return
        ev = eventos_plot[idx]
        _resaltar_en_axes(ax, ev, anotar=True)
        if contraparte is not None:
            ax2, eventos2 = contraparte
            if ax2 is not None:
                ev2 = _buscar_mismo_evento(ev, eventos2)
                if ev2 is not None:
                    _resaltar_en_axes(ax2, ev2)
        fig.canvas.draw_idle()

    fig.canvas.mpl_connect('button_press_event', on_press)
    fig.canvas.mpl_connect('button_release_event', on_release)


def mostrar_json_en_popup(nombre, eventos, fuente, percibidos, total_eventos):
    """
    Muestra el JSON de los eventos de un perfil en una ventana pop-up con scroll,
    restaurando la funcionalidad de la versión Tkinter original.
    """
    try:
        import tkinter as tk
        from tkinter import scrolledtext
    except Exception:
        return
    raiz = _raiz_tk()
    if raiz is None:
        return
    contenido_json = json.dumps(eventos, indent=4, ensure_ascii=False)
    popup = tk.Toplevel(raiz)
    if fuente == "eventquery":
        popup.title("%s ( fuente %s - %d percibidos de %d eventos ploteados)"
                     % (nombre, fuente, percibidos, total_eventos))
    else:
        popup.title("%s ( fuente %s - %d eventos ploteados)"
                     % (nombre, fuente, total_eventos))
    popup.geometry("700x400")
    campo_texto = scrolledtext.ScrolledText(popup, wrap=tk.WORD,
                                            font=("Consolas", 10))
    campo_texto.pack(expand=True, fill="both")
    campo_texto.insert(tk.INSERT, contenido_json)
    campo_texto.config(state=tk.DISABLED)


_detener_despliegue = False
_progreso = ""


def _registrar_progreso(texto):
    """Guarda el avance actual del despliegue para mostrar en el título."""
    global _progreso
    _progreso = texto


def _agregar_boton_detener(fig):
    """Añade un botón pequeño 'Detener' en el extremo derecho inferior de la
    ventana del mapa, fuera del área de la leyenda."""
    try:
        from matplotlib.widgets import Button
    except Exception:
        return
    ax_btn = fig.add_axes([0.905, 0.012, 0.08, 0.04])
    for s in ax_btn.spines.values():
        s.set_visible(False)
    ax_btn.set_xticks([])
    ax_btn.set_yticks([])
    boton = Button(ax_btn, 'Detener', color='#c00000', hovercolor='#ff5050')
    boton.label.set_color('white')
    boton.label.set_fontweight('bold')
    boton.label.set_fontsize(8)
    boton.on_clicked(lambda event: detener())
    # matplotlib registra el callback del widget como weakref; sin una
    # referencia fuerte el Button se recolecta al salir de esta funcion y el
    # clic deja de responder. Se ancla a la figura para que viva con ella.
    fig._boton_detener = boton
    return boton


def detener():
    """Detiene el despliegue cerrando todas las figuras abiertas."""
    global _detener_despliegue
    _detener_despliegue = True
    try:
        plt.close('all')
    except Exception:
        pass


def despliegue_detenido():
    return _detener_despliegue


def _indicador_modo_interaccion(fig):
    """
    Muestra el modo activo del toolbar (ZOOM/PAN) y cambia el cursor.

    El toolbar de matplotlib deja fijo el cursor de cruz (tcross) en modo zoom
    con independencia de que ya se haya completado el zoom, lo que puede
    confundir. Aqui se sustituye por una mano mientras el modo este activo y se
    añade un texto superpuesto que indica el modo y los gestos disponibles.

    El modo solo cambia por tres vias: los botones Zoom/Pan del toolbar (se
    reconfigura su 'command'), la tecla Escape y por eventos de raton (para el
    cursor se usa motion_notify_event, que corre despues del del toolbar).
    No se usa ningun temporizador Tk ('after'): los timers pendientes de una
    figura cerrada provocan 'invalid command name' al dispararse en el
    mainloop, por lo que se evitan a la raiz.
    """
    try:
        from matplotlib.backend_bases import cursors
    except Exception:
        cursors = None
    toolbar = getattr(getattr(fig.canvas, 'manager', None), 'toolbar', None)
    if toolbar is None:
        return
    canvas = fig.canvas
    tk_canvas = None
    try:
        tk_canvas = canvas.get_tk_widget()
    except Exception:
        tk_canvas = None

    indicador = fig.text(
        0.01, 0.985, "", transform=fig.transFigure, ha='left', va='top',
        fontsize=10,
        bbox=dict(boxstyle='round,pad=0.3', fc='lightyellow', ec='navy',
                  alpha=0.9))
    indicador.set_visible(False)

    estado = {'texto': '', 'parado': False,
              'boton_zoom': None, 'boton_pan': None}

    def _texto_modo():
        if toolbar.mode.name == 'ZOOM':
            return ("MODO ZOOM  ·  clic = seleccionar evento  ·  "
                    "arrastre = zoom  ·  Esc = salir")
        if toolbar.mode.name == 'PAN':
            return ("MODO PAN  ·  clic = seleccionar evento  ·  "
                    "arrastre = mover vista  ·  Esc = salir")
        return ''

    def _refrescar_cursor():
        if cursors is None or tk_canvas is None:
            return
        nuevo = (cursors.HAND if toolbar.mode.name in ('ZOOM', 'PAN')
                 else cursors.POINTER)
        try:
            if tk_canvas.cget('cursor') != (
                    'hand2' if nuevo == cursors.HAND else 'arrow'):
                canvas.set_cursor(nuevo)
        except Exception:
            pass

    def _refrescar():
        try:
            if estado['parado']:
                return
            texto = _texto_modo()
            if texto != estado['texto']:
                estado['texto'] = texto
                indicador.set_text(texto)
                indicador.set_visible(bool(texto))
                canvas.draw_idle()
        except Exception:
            pass
        _refrescar_cursor()

    def _alternar(modo):
        def _adelante():
            if estado['parado']:
                return
            try:
                getattr(toolbar, modo)()
            except Exception:
                return
            _refrescar()
        return _adelante

    boton_zoom = toolbar._buttons.get('Zoom') \
        if hasattr(toolbar, '_buttons') else None
    boton_pan = toolbar._buttons.get('Pan') \
        if hasattr(toolbar, '_buttons') else None
    if boton_zoom is not None:
        estado['boton_zoom'] = _alternar('zoom')
        try:
            boton_zoom.configure(command=estado['boton_zoom'])
        except Exception:
            pass
    if boton_pan is not None:
        estado['boton_pan'] = _alternar('pan')
        try:
            boton_pan.configure(command=estado['boton_pan'])
        except Exception:
            pass

    def _on_key(event):
        if event is None or getattr(event, 'key', None) != 'escape':
            return
        if toolbar.mode.name == 'ZOOM':
            toolbar.zoom()
        elif toolbar.mode.name == 'PAN':
            toolbar.pan()
        else:
            return
        _refrescar()

    def _on_move(event):
        _refrescar_cursor()

    fig._modo_interaccion = estado
    canvas.mpl_connect('key_press_event', _on_key)
    canvas.mpl_connect('motion_notify_event', _on_move)
    _refrescar()


def _layout_nacional(fig, ax, ax_txt, lon_min, lon_max, lat_min, lat_max,
                     titulo, subtitulo):
    """
    Recalcula la disposición del mapa del Territorio Nacional según el tamaño
    actual de la figura: el mapa queda a la derecha respetando su aspecto
    geográfico (sin deformar) y el título a la izquierda, envolviéndolo al
    ancho de la columna. Se invoca al crear y en cada redimensionamiento.
    """
    W, H = fig.get_size_inches()
    if W <= 0 or H <= 0:
        return
    # Aspecto geográfico del mapa (grados).
    aspecto = (lon_max - lon_min) / max(1e-9, lat_max - lat_min)
    # Márgenes en fracción de la figura.
    top_frac = 0.03
    bot_frac = 0.10
    der_in = 0.12
    izq_in = 0.02
    # Espacio vertical disponible para el mapa.
    alto_disponible = H * (1.0 - top_frac - bot_frac)
    # Ancho mínimo (pulgadas) para la columna de texto a la izquierda.
    texto_min_in = 2.2
    ancho_disponible = W - der_in
    alto_mapa = alto_disponible
    ancho_mapa = alto_mapa * aspecto
    if ancho_mapa > ancho_disponible - texto_min_in:
        ancho_mapa = ancho_disponible - texto_min_in
        alto_mapa = ancho_mapa / aspecto
    # Posición del mapa (derecha).
    x0_mapa = (W - der_in - ancho_mapa) / W
    y0_mapa = bot_frac
    ax.set_position([x0_mapa, y0_mapa, ancho_mapa / W, alto_mapa / H])
    # Columna de texto a la izquierda del mapa.
    x0_texto = izq_in / W
    ancho_columna = (x0_mapa - izq_in / W)
    ax_txt.set_position([x0_texto, bot_frac, max(0.03, ancho_columna),
                         1.0 - top_frac - bot_frac])
    ax_txt.cla()
    ax_txt.axis('off')
    # Envolver el texto al ancho de la columna (estimación por caracteres).
    fs = 11
    ancho_pulg = max(1.0, ancho_columna * W)
    chars = max(10, int(ancho_pulg / (0.6 * fs / 72.0)))
    partes = [p for p in (titulo, subtitulo) if p]
    texto_izq = "\n".join(textwrap.fill(p, width=chars) for p in partes)
    ax_txt.text(0.0, 0.5, texto_izq, ha='left', va='center',
                fontsize=fs, fontweight='bold')


def plotear_planta(eventos, fuente, perfil=None, n_asignados=None, totales=None,
                   territorio=None):
    """
    Crea una ventana con la vista en planta (relieve + localidades + eventos).
    Si se pasa 'perfil', el área visible se deriva del recorrido del slab;
    si no, y se pasa 'territorio' (clave de TERRITORIOS), se usa la extensión
    completa de ese territorio; si no, la extensión de los propios eventos.
    n_asignados/totales: conteos de generajson.py para mostrar en la ventana.
    Devuelve (percibidos, total_eventos).
    """
    total_eventos = 0
    percibidos = 0
    sospechosos = 0
    for ev in eventos:
        try:
            float(ev['latitud'])
            float(ev['longitud'])
        except (TypeError, ValueError, KeyError):
            continue
        total_eventos += 1
        if fuente == "eventquery" and ev.get('percibido') == "S":
            percibidos += 1
        if ev.get('sospechoso'):
            sospechosos += 1

    if eventos:
        extent = _extent_planta_por_eventos(eventos, perfil, territorio=territorio)
    elif territorio is not None:
        extent = _extent_territorio(territorio)
    else:
        extent = None
    if extent is None:
        return percibidos, 0
    lon_min, lon_max, lat_min, lat_max = extent
    if perfil is not None:
        titulo = "Vista en Planta - Perfil %s" % perfil["id"]
        nombre_popup = "Perfil %s" % perfil["id"]
    elif territorio is not None:
        nombre_popup = "Territorio %s" % territorio
        # Título compacto para los mapas de territorio (sin suptitle ni
        # redundancias). La extensión geográfica la muestran las grillas.
        plural_ev = "evento" if total_eventos == 1 else "eventos"
        plural_sosp = "sospechoso" if sospechosos == 1 else "sospechosos"
        titulo = ("Territorio %s — %d %s · %d %s"
                  % (territorio, total_eventos, plural_ev,
                     sospechosos, plural_sosp))
        if fuente == "eventquery" and percibidos:
            titulo += " · %d percibidos" % percibidos
    else:
        titulo = "Vista en Planta - Eventos sin perfil asignado"
        nombre_popup = "Eventos sin perfil"
    subtitulo = _texto_extencion(lon_min, lon_max, lat_min, lat_max)

    layout_nacional = (territorio == "Nacional")
    if layout_nacional:
        fig = plt.figure(figsize=FIG_SIZE_NACIONAL, dpi=DPI)
        # Abre a lo máximo en vertical: ajusta la altura al alto de pantalla.
        try:
            raiz = _raiz_tk()
            if raiz is not None:
                alto_px = int(raiz.winfo_screenheight())
                if alto_px > 0:
                    alto_pulg = max(6.0, alto_px / DPI - 1.0)
                    aspecto = (lon_max - lon_min) / max(
                        1e-9, lat_max - lat_min)
                    ancho_pulg = (0.02 + 2.4 + 0.2) + (alto_pulg - 0.9) * aspecto
                    ancho_pulg = max(4.0, ancho_pulg)
                    fig.set_size_inches(ancho_pulg, alto_pulg)
        except Exception:
            pass
        ax = fig.add_axes([0.40, 0.10, 0.58, 0.84], projection=ccrs.PlateCarree())
        ax_txt = fig.add_axes([0.02, 0.10, 0.30, 0.84])
        ax_txt.axis('off')
        _layout_nacional(fig, ax, ax_txt, lon_min, lon_max, lat_min, lat_max,
                         titulo, "")
        fig.canvas.mpl_connect(
            'resize_event',
            lambda ev: _layout_nacional(fig, ax, ax_txt,
                                        lon_min, lon_max, lat_min, lat_max,
                                        titulo, ""))
    else:
        fig = plt.figure(figsize=FIG_SIZE, dpi=DPI)
        ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
    _base_mapa_planta(ax, lon_min, lon_max, lat_min, lat_max)
    _localidades_planta(ax, lon_min, lon_max, lat_min, lat_max, territorio=territorio)
    scatter, eventos_plot = _marcadores_planta(ax, eventos, fuente)
    handles_leyenda = _handles_eventos(fuente)
    if scatter is not None:
        _conectar_seleccion_eventos(fig, ax, scatter, eventos_plot)
    if layout_nacional:
        # La disposición y el título izquierdo los gestiona _layout_nacional.
        pass
    else:
        texto_titulo = titulo
        if perfil is not None:
            texto_titulo = "%s\n%s" % (titulo, subtitulo)
        ax.set_title(texto_titulo, fontsize=11, fontweight='bold', pad=10)
    mostrar_json_en_popup(nombre_popup, eventos, fuente, percibidos,
                          total_eventos)
    if territorio is not None:
        # Los mapas de territorio usan un único título compacto (sin suptitle).
        pass
    else:
        if n_asignados is None:
            n_asignados = total_eventos
        sufijo = ""
        if fuente == "eventquery" and percibidos:
            sufijo = " — %d percibidos" % percibidos
        if totales:
            fig.suptitle("%s — %d eventos asignados (de %d totales) — %d sospechosos%s"
                         % (nombre_popup, n_asignados, totales, sospechosos, sufijo),
                         fontsize=12, fontweight='bold', y=0.98)
        elif n_asignados:
            fig.suptitle("%s — %d eventos asignados — %d sospechosos%s"
                         % (nombre_popup, n_asignados, sospechosos, sufijo),
                         fontsize=12, fontweight='bold', y=0.98)
    fig.legend(handles=handles_leyenda, loc='lower center',
               bbox_to_anchor=(0.5, 0.02),
               ncol=(2 if layout_nacional else len(handles_leyenda)),
               fontsize=8, frameon=True)
    if not layout_nacional:
        plt.tight_layout(rect=[0, 0.10, 1, 0.94])
    _agregar_boton_detener(fig)
    _indicador_modo_interaccion(fig)
    plt.show()
    return percibidos, total_eventos


def plotear_perfil(eventos, perfil, fuente, percibidos, n_asignados=None,
                   totales=None):
    """
    Crea una figura con dos subplots: vista en planta (izquierda) y perfil
    de subducción (derecha), con etiquetas de id y selección interactiva.
    n_asignados/totales: conteos de generajson.py para mostrar en la ventana.
    Devuelve (percibidos, total_eventos).
    """
    total_eventos = 0
    percibidos = 0
    sospechosos = 0

    extent = _extent_planta_por_eventos(eventos, perfil)
    if extent is None:
        return percibidos, 0
    lon_min, lon_max, lat_min, lat_max = extent

    fig = plt.figure(figsize=FIG_SIZE, dpi=DPI)

    # --- Planta (izquierda) ---
    ax_planta = fig.add_subplot(1, 2, 1, projection=ccrs.PlateCarree())
    _base_mapa_planta(ax_planta, lon_min, lon_max, lat_min, lat_max)
    _localidades_planta(ax_planta, lon_min, lon_max, lat_min, lat_max)
    scatter, eventos_plot = _marcadores_planta(ax_planta, eventos, fuente)
    handles_leyenda = _handles_eventos(fuente) + [_handle_sismicidad()]
    ax_planta.set_title("Vista en Planta - Perfil %s %s\n%s"
                        % (perfil["id"], "(%s)" % _progreso if _progreso else "",
                           _texto_extencion(lon_min, lon_max, lat_min,
                                            lat_max)),
                        fontsize=11, fontweight='bold', pad=10)

    # --- Perfil (derecha) ---
    ax_perfil = fig.add_subplot(1, 2, 2)

    _sismicidad_perfil(ax_perfil, perfil)

    tp = perfil["topo_p"]
    alt = perfil["topo_alt"]
    if len(tp) > 1:
        ax_perfil.plot(tp, alt / 1000.0, color=COLOR_TOPO, lw=1.2, zorder=3,
                       label="Topografía/Batimetría")

    sp = perfil["slab"]["p"]
    sz = perfil["slab"]["depth"]
    if len(sp) > 0:
        mask = ~np.isnan(sz)
        if np.any(mask):
            ax_perfil.plot(sp[mask], -sz[mask], color=COLOR_SLAB, lw=2.2,
                           zorder=4, label="Contacto Placas")

    n_validos_perfil = 0
    for e in eventos:
        try:
            float(e['prof'])
            float(e.get('along_km'))
        except (TypeError, ValueError, KeyError):
            continue
        n_validos_perfil += 1
    # Mismo umbral que en la planta (MAX_EVENTOS_ETIQUETA): controla si el
    # perfil etiqueta los ids o los omite por densidad.
    etiquetas_perfil = n_validos_perfil <= MAX_EVENTOS_ETIQUETA

    xs = []
    ys = []
    colores = []
    bordes = []
    grosores = []
    eventos_perfil = []
    textos = []
    for evento in eventos:
        try:
            prof_punto = float(evento['prof']) * -1  # negativa hacia abajo
            x_km = float(evento.get('along_km'))
        except (TypeError, ValueError, KeyError):
            continue
        total_eventos += 1
        color = _color_evento(fuente, evento)
        xs.append(x_km)
        ys.append(prof_punto)
        colores.append(color)
        borde, grosor = _bordes_eventos([evento])
        bordes.append(borde[0])
        grosores.append(grosor[0])
        eventos_perfil.append(evento)
        if evento.get('sospechoso'):
            sospechosos += 1

        if evento.get('id') is not None and etiquetas_perfil:
            t = ax_perfil.text(x_km, prof_punto, str(evento.get('id', '')),
                               fontsize=7, zorder=11)
            textos.append(t)

        if fuente == "eventquery" and evento.get('percibido') == "S":
            percibidos += 1
            with open("percibidos.txt", "a") as archivo_perc:
                linea = "{} {} {} {} {} {} {} {}\n".format(
                    evento.get('id'), evento.get('fecha hora'),
                    float(evento['latitud']), float(evento['longitud']),
                    prof_punto, evento.get('magnitud'),
                    evento.get('tipo'), evento.get('percibido'))
                archivo_perc.write(linea)

    scatter_perf = None
    if xs:
        scatter_perf = ax_perfil.scatter(xs, ys, s=60, c=colores, alpha=0.95,
                                         edgecolors=bordes, linewidths=grosores,
                                         zorder=10, picker=True, pickradius=6)
        if textos:
            try:
                adjust_text(textos, ax=ax_perfil,
                            expand=(1.15, 1.7), min_arrow_len=0,
                            iter_lim=ITERACIONES_ADJUST_TEXT,
                            arrowprops=dict(arrowstyle="-", color='black',
                                            lw=0.4, alpha=0.5))
            except Exception:
                pass

    # Seleccion cruzada: al hacer clic en un mapa se resalta el mismo evento
    # (mismo anillo, tamano y color) tambien en el otro mapa.
    if scatter is not None:
        _conectar_seleccion_eventos(
            fig, ax_planta, scatter, eventos_plot,
            contraparte=(ax_perfil, eventos_perfil))
    if scatter_perf is not None:
        _conectar_seleccion_eventos(
            fig, ax_perfil, scatter_perf, eventos_perfil,
            contraparte=(ax_planta, eventos_plot))

    minX = float(sp.min())
    maxX = float(sp.max())
    ax_perfil.set_xlim(minX, maxX)
    ax_perfil.set_ylim(-PROF_MAX_KM, ALT_MAR_KM)
    ax_perfil.set_xlabel("Distancia a lo largo (km)", fontsize=9,
                         fontweight='bold')
    ax_perfil.set_ylabel("Profundidad (km)", fontsize=9, fontweight='bold')
    ax_perfil.tick_params(axis='both', labelsize=8)
    ax_perfil.grid(True, linestyle=':', alpha=0.4, color='gray', zorder=0)
    ax_perfil.set_title("Perfil %s (%.0f-%.0f km | 0-%d km de prof)"
                        % (perfil["id"], minX, maxX, PROF_MAX_KM),
                        fontsize=11, fontweight='bold', pad=10)

    mostrar_json_en_popup("Perfil %s" % perfil["id"], eventos, fuente,
                          percibidos, total_eventos)
    if n_asignados is None:
        n_asignados = total_eventos
    sufijo = ""
    if fuente == "eventquery" and percibidos:
        sufijo = " — %d percibidos" % percibidos
    if totales:
        fig.suptitle("Perfil %s — %d eventos asignados (de %d totales) — %d sospechosos%s"
                     % (perfil["id"], n_asignados, totales, sospechosos, sufijo),
                     fontsize=12, fontweight='bold', y=0.98)
    else:
        fig.suptitle("Perfil %s — %d eventos asignados — %d sospechosos%s"
                     % (perfil["id"], n_asignados, sospechosos, sufijo),
                     fontsize=12, fontweight='bold', y=0.98)
    fig.legend(handles=handles_leyenda, loc='lower center',
               bbox_to_anchor=(0.5, 0.02), ncol=len(handles_leyenda),
               fontsize=8, frameon=True)
    plt.tight_layout(rect=[0, 0.10, 1, 0.94])
    _agregar_boton_detener(fig)
    _indicador_modo_interaccion(fig)
    plt.show()
    return percibidos, total_eventos


def plotear_ventana(eventos, perfil, fuente, percibidos, n_asignados=None,
                    totales=None):
    """
    Abre la ventana de un perfil (planta + perfil). Se mantiene este alias
    para no cambiar el resto del flujo. Devuelve (percibidos, total_eventos).
    """
    return plotear_perfil(eventos, perfil, fuente, percibidos,
                          n_asignados, totales)


def plotear_sin_perfil(eventos, fuente, percibidos, n_asignados=None,
                       totales=None):
    """Plotea los eventos sin perfil solo sobre la planta."""
    return plotear_planta(eventos, fuente, perfil=None,
                          n_asignados=n_asignados, totales=totales)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    archivo = sys.argv[1]
    fuente = sys.argv[2]

    if not os.path.isfile(archivo):
        print("Error: no se encontró el archivo '%s'." % archivo)
        sys.exit(1)

    # abre percibidos.txt SIEMPRE en modo "w" para evitar acumular datos
    # de ejecuciones anteriores (solo relevante para eventquery)
    if fuente == "eventquery":
        with open("percibidos.txt", "w") as f:
            f.write("id fecha hora latitud longitud prof magnitud tipomag percibido\n")

    # Carga el conteo por perfil que generajson.py dejó en
    # conteo_perfiles_<fuente>.json para mostrarlo a medida que se plotea.
    conteo_por_perfil = {}
    conteo_total = None
    conteo_archivo = 'conteo_perfiles_%s.json' % fuente
    if os.path.isfile(conteo_archivo):
        try:
            with open(conteo_archivo) as f:
                datos_conteo = json.load(f)
            conteo_por_perfil = datos_conteo.get('conteo', {})
            conteo_total = datos_conteo.get('total')
        except Exception:
            pass

    with open(archivo) as contenido:
        eventos = json.load(contenido)

    perfiles = ap.detectar_perfiles()
    if not perfiles:
        print("Error: no se detectaron perfiles validos en 'grillas'.")
        sys.exit(1)

    perfiles_por_id = {p["id"]: p for p in perfiles}

    # agrupa en memoria por perfil
    grupos = {}
    sin_perfil = []
    for evento in eventos:
        pid = evento.get('perfil')
        if pid is None:
            sin_perfil.append(evento)
        elif pid in perfiles_por_id:
            grupos.setdefault(pid, []).append(evento)
        else:
            sin_perfil.append(evento)

    percibidos = 0
    total_por_perfil = {}

    for pid in sorted(grupos):
        if despliegue_detenido():
            break
        perfil = perfiles_por_id[pid]
        _registrar_progreso("Perfil %s de %d"
                            % (pid, len(grupos)))
        p, n = plotear_ventana(grupos[pid], perfil, fuente, percibidos,
                               n_asignados=conteo_por_perfil.get(pid),
                               totales=conteo_total)
        percibidos += p
        total_por_perfil[pid] = n

    if sin_perfil and not despliegue_detenido():
        _registrar_progreso("Eventos sin perfil")
        nacional, insular, antartico = _categorizar_por_territorio(sin_perfil)
        
        for nombre, eventos_territorio in [
            ("Nacional", nacional),
            ("Insular", insular),
            ("Antártico", antartico)
        ]:
            if despliegue_detenido():
                break
            if eventos_territorio:
                p, n = plotear_planta(
                    eventos_territorio, fuente, perfil=None,
                    n_asignados=conteo_por_perfil.get(f"({nombre})"),
                    totales=conteo_total, territorio=nombre
                )
                percibidos += p
                total_por_perfil[nombre] = n

    if despliegue_detenido():
        print("Despliegue detenido por el usuario.")

    print("Eventos ploteados:")
    for pid, n in sorted(total_por_perfil.items()):
        print("  %s : %d" % (pid, n))
    if fuente == "eventquery":
        print("Percibidos:", percibidos)


if __name__ == "__main__":
    main()