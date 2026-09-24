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
Este script agrupa los eventos en memoria por perfil y abre un PANEL DE
ANÁLISIS: una tabla resumen de todos los perfiles (con su mini-perfil) desde
donde el usuario decide qué ver en detalle —abrir perfiles/mapas en paralelo,
filtrar por sospechosos, ver los mapas de territorio (Nacional/Insular/
Antártico) o restablecer la vista de inicio—. Sin backend interactivo cae al
flujo secuencial: una ventana por perfil (planta a la izquierda, perfil a la
derecha) y los eventos sin perfil solo sobre la planta.
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
import rutas

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

# PROF_MAX_KM: profundidad MÍNIMA (km) mostrada en el eje vertical del perfil
# (piso). El eje va desde -prof_fondo (abajo) hasta ALT_MAR_KM (arriba), donde
# prof_fondo = _prof_fondo_perfil(...) cubre el slab y los eventos del catálogo
# con margen, de modo que los eventos/slab más profundos no queden recortados.
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


def _resumen_perfil(eventos, fuente):
    """
    Resumen de un grupo de eventos (un perfil) para la tabla del panel:
    (total, sospechosos, percibidos, along_min, along_max).
    along_min/along_max son None si ningún evento tiene along_km válido.
    """
    total = 0
    sospechosos = 0
    percibidos = 0
    alongs = []
    for ev in eventos:
        try:
            float(ev['latitud'])
            float(ev['longitud'])
        except (TypeError, ValueError, KeyError):
            continue
        total += 1
        if ev.get('sospechoso'):
            sospechosos += 1
        if fuente == "eventquery" and ev.get('percibido') == "S":
            percibidos += 1
        try:
            alongs.append(float(ev.get('along_km')))
        except (TypeError, ValueError):
            pass
    a_min = min(alongs) if alongs else None
    a_max = max(alongs) if alongs else None
    return total, sospechosos, percibidos, a_min, a_max


def _prof_fondo_perfil(perfil, profundidades_eventos):
    """
    Fondo (km) del eje de profundidad del perfil: cubre el slab y los eventos
    del catálogo, con ~10 % de margen. PROF_MAX_KM actúa como piso, de modo
    que los perfiles someros no cambian. 'profundidades_eventos' son valores
    positivos (km).
    """
    base = 0.0
    for d in profundidades_eventos:
        try:
            d = float(d)
        except (TypeError, ValueError):
            continue
        if d > base:
            base = d
    try:
        sz = np.asarray(perfil["slab"]["depth"], dtype=float)
        if sz.size and np.any(~np.isnan(sz)):
            base = max(base, float(np.nanmax(sz)))
    except (KeyError, TypeError, ValueError):
        pass
    return max(PROF_MAX_KM, base * 1.10)


def _mini_perfil(ax, perfil, eventos, fuente, mostrar_hist=False):
    """
    Miniatura ligera del perfil para el panel de análisis: topografía, slab y
    eventos (con borde violeta en los sospechosos). Por defecto SIN fondo
    histórico ni relieve (para dibujarse en fracciones de segundo a lo largo de
    los ~32 perfiles); si mostrar_hist es True se añade la sismicidad histórica
    (misma caché que el detalle).
    """
    sp = perfil["slab"]["p"]
    sz = perfil["slab"]["depth"]

    if mostrar_hist:
        _sismicidad_perfil(ax, perfil)

    try:
        tp = perfil.get("topo_p")
        alt = perfil.get("topo_alt")
        if tp is not None and len(tp) > 1:
            ax.plot(tp, np.asarray(alt) / 1000.0, color=COLOR_TOPO, lw=0.9,
                    zorder=3, rasterized=True)
    except Exception:
        pass

    if len(sp) > 0:
        mask = ~np.isnan(sz)
        if np.any(mask):
            ax.plot(sp[mask], -sz[mask], color=COLOR_SLAB, lw=1.6, zorder=4,
                    rasterized=True)

    xs = []
    ys = []
    colores = []
    bordes = []
    grosores = []
    total = 0
    sospechosos = 0
    for ev in eventos:
        try:
            prof_punto = float(ev['prof']) * -1
            x_km = float(ev.get('along_km'))
        except (TypeError, ValueError, KeyError):
            continue
        total += 1
        if ev.get('sospechoso'):
            sospechosos += 1
        xs.append(x_km)
        ys.append(prof_punto)
        colores.append(_color_evento(fuente, ev))
        b, g = _bordes_eventos([ev])
        bordes.append(b[0])
        grosores.append(g[0])
    if xs:
        ax.scatter(xs, ys, s=22, c=colores, edgecolors=bordes,
                   linewidths=grosores, zorder=10, alpha=0.95, rasterized=True)

    # Ejes: mismo rango que el detalle para que las miniaturas sean comparables.
    min_x = None
    max_x = None
    if len(sp) > 0:
        validos = sp[~np.isnan(sp)]
        if len(validos):
            min_x = float(validos.min())
            max_x = float(validos.max())
    if min_x is None and xs:
        min_x = min(xs)
        max_x = max(xs)
    if min_x is None:
        return False
    ax.set_xlim(min_x, max_x)
    ax.set_ylim(-_prof_fondo_perfil(perfil, [-y for y in ys]), ALT_MAR_KM)

    ax.grid(True, linestyle=':', alpha=0.35, color='gray', zorder=0)
    for lado in ('top', 'right'):
        ax.spines[lado].set_visible(False)
    ax.tick_params(axis='both', labelsize=6, length=2)

    titulo = perfil["id"]
    if total:
        titulo += "  ·  %d ev" % total
    if sospechosos:
        titulo += "  ·  %d sospechosos" % sospechosos
    ax.set_title(titulo, fontsize=7,
                 fontweight='bold',
                 color=('#8b0000' if sospechosos else 'black'))
    return True


def _mini_mapa_territorio(ax, nombre, eventos, fuente):
    """
    Mini-mapa simplificado de un territorio para el sub-panel de eventos sin
    perfil: fondo claro, costas/fronteras y eventos. SIN relieve, grilla,
    localidades ni adjust_text (barato: ~decenas de ms tras la primera carga
    de las features de cartopy). Devuelve True si dibujó.
    """
    extent = _extent_planta_por_eventos(eventos, perfil=None, territorio=nombre)
    if extent is None:
        extent = _extent_territorio(nombre)
    if extent is None:
        return False
    lon_min, lon_max, lat_min, lat_max = extent
    ax.set_extent([lon_min, lon_max, lat_min, lat_max], crs=ccrs.PlateCarree())
    ax.set_facecolor("#eef3f7")

    ax.add_feature(cfeature.COASTLINE.with_scale(NIVEL_GEO),
                   edgecolor='#111111', linewidth=0.7, zorder=2)
    ax.add_feature(cfeature.BORDERS.with_scale(NIVEL_GEO),
                   edgecolor=COLOR_FRONTERA, linestyle=ESTILO_FRONTERA,
                   linewidth=0.6, zorder=2)

    eventos_plot = []
    for e in eventos:
        try:
            float(e['longitud'])
            float(e['latitud'])
        except (TypeError, ValueError, KeyError):
            continue
        eventos_plot.append(e)
    if eventos_plot:
        lons = [float(e['longitud']) for e in eventos_plot]
        lats = [float(e['latitud']) for e in eventos_plot]
        colores = [_color_evento(fuente, e) for e in eventos_plot]
        bordes, grosores = _bordes_eventos(eventos_plot)
        ax.scatter(lons, lats, s=28, c=colores, alpha=0.95,
                   edgecolors=bordes, linewidths=grosores, zorder=5,
                   transform=ccrs.PlateCarree())

    total = len(eventos_plot)
    sosp = sum(1 for e in eventos_plot if e.get('sospechoso'))
    ax.set_title("%s  ·  %d ev · %d sospechosos" % (nombre, total, sosp),
                 fontsize=9, fontweight='bold')
    return True


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
    """Devuelve la ventana raíz Tk compartida de matplotlib (TkAgg) o None.

    Solo devuelve la raíz si existe al menos una figura real: con cero
    figuras, plt.get_current_fig_manager() puede devolver un manager residual
    cuya ventana es una raíz Tk vacía ("Figure 1" sin contenido), y usarla
    impediría crear el ancla oculta de la sesión.
    """
    try:
        import tkinter
        if not plt.get_fignums():
            return None
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


def _ubicacion_vineta(ax, x, y):
    """
    Elige el lado en que se abre la viñeta para que no se salga de la figura:
    hacia la izquierda si el evento cae en la mitad derecha de los ejes, y
    hacia abajo si está cerca del borde superior. Devuelve
    (xytext, ha, va) para ax.annotate.
    """
    try:
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
    except Exception:
        x0, x1, y0, y1 = 0.0, 1.0, 0.0, 1.0
    fx = (x - x0) / (x1 - x0) if x1 > x0 else 0.5
    fy = (y - y0) / (y1 - y0) if y1 > y0 else 0.5
    if fx > 0.5:
        dx, ha = -6, 'right'
    else:
        dx, ha = 6, 'left'
    if fy > 0.75:
        dy, va = -6, 'top'
    else:
        dy, va = 25, 'bottom'
    return (dx, dy), ha, va


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
            xytext, ha, va = _ubicacion_vineta(ax, lon, lat)
            anot = ax.annotate(
                contenido, xy=(lon, lat), xytext=xytext,
                textcoords='offset points', ha=ha, va=va, fontsize=8,
                color='black',
                bbox=dict(boxstyle='round,pad=0.4', fc='lightyellow',
                          ec='navy', alpha=0.95),
                arrowprops=dict(arrowstyle='-', color='navy', lw=0.8),
                zorder=13, clip_on=False, transform=ccrs.PlateCarree())
    elif x_km is not None and prof_km is not None:
        sc = ax.scatter([x_km], [prof_km], s=220, facecolors='none',
                        edgecolors=COLOR_RESALTADO, linewidths=2.5, zorder=12,
                        picker=False)
        if anotar:
            xytext, ha, va = _ubicacion_vineta(ax, x_km, prof_km)
            anot = ax.annotate(
                contenido, xy=(x_km, prof_km), xytext=xytext,
                textcoords='offset points', ha=ha, va=va, fontsize=8,
                color='black',
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
    """Detiene el despliegue cerrando las figuras abiertas de detalle."""
    global _detener_despliegue
    _detener_despliegue = True
    try:
        if _panel_activo and _fig_ancla is not None:
            # En el modo panel se cierran solo las ventanas de detalle; la
            # figura ancla (y con ella la raíz Tk del panel) sigue viva.
            for num in list(plt.get_fignums()):
                if num != _fig_ancla.number:
                    plt.close(num)
        else:
            plt.close('all')
    except Exception:
        pass


def despliegue_detenido():
    return _detener_despliegue


# Estado del panel de análisis. _panel_activo indica que el usuario navega
# desde el panel (ya hay un mainloop Tk corriendo), por lo que el modo
# "bloqueante" debe esperar el cierre bombeando eventos en vez de anidar un
# segundo mainloop. _fig_ancla mantiene viva la raíz Tk de la sesión.
_panel_activo = False
_fig_ancla = None
# Ids de percibidos ya escritos en percibidos.txt (evita duplicados cuando el
# usuario abre el mismo perfil más de una vez desde el panel).
_percibidos_escritos = set()


def _registrar_percibido(evento):
    """
    Registra el evento como percibido VISTO en esta sesión: lo escribe en
    percibidos.txt la primera vez (dedup por id) y lo suma al contador de
    vistos (_percibidos_escritos). Devuelve True si quedó registrado aquí.
    """
    if evento.get('percibido') != "S":
        return False
    key = evento.get('id')
    if key in _percibidos_escritos:
        return False
    try:
        prof_punto = -float(evento['prof'])
        linea = "{} {} {} {} {} {} {} {}\n".format(
            key, evento.get('fecha hora'),
            float(evento['latitud']), float(evento['longitud']),
            prof_punto, evento.get('magnitud'),
            evento.get('tipo'), evento.get('percibido'))
        with open(rutas.p_ploteo("percibidos.txt"), "a") as archivo_perc:
            archivo_perc.write(linea)
    except (TypeError, ValueError, KeyError, OSError):
        return False
    _percibidos_escritos.add(key)
    return True


def _asegurar_raiz():
    """
    Devuelve la raíz Tk compartida de TkAgg, creándola si aún no existe ninguna
    figura (el panel de análisis es la primera ventana de la sesión). Se usa
    una figura 'ancla' oculta que mantiene viva la raíz hasta el cierre.
    Devuelve None si el backend no es interactivo (fallback al flujo
    secuencial).
    """
    global _fig_ancla
    raiz = _raiz_tk()
    if raiz is not None:
        return raiz
    try:
        fig_ancla = plt.figure(figsize=(0.1, 0.1), dpi=1)
        mgr = fig_ancla.canvas.manager
        if mgr is not None:
            # La figura 'ancla' se crea SIN mostrarse (no se llama a show()):
            # solo se oculta su ventana para que la raíz Tk exista y sirva de
            # maestro para el panel y las figuras de detalle, sin que nunca
            # llegue a verse el cuadro vacío "Figure 1".
            try:
                mgr.window.withdraw()
            except Exception:
                pass
        raiz = _raiz_tk()
        if raiz is not None:
            _fig_ancla = fig_ancla  # se conserva para no cerrar la raíz
            return raiz
    except Exception:
        pass
    return None


def _mostrar_figura(bloquear):
    """
    Muestra la figura actual respetando el modo de interacción:
      - bloquear=False -> no bloquea (abre ventanas en paralelo). Se muestra
        SOLO la figura actual con el manager, sin pasar por plt.show() (que
        recorrería y re-mapearía el ancla oculta de la raíz Tk).
      - bloquear=True  -> bloquea hasta cerrar la ventana (modo secuencial,
        fuera del panel) con plt.show() normal.
    """
    mgr = getattr(plt.gcf().canvas, 'manager', None)
    if bloquear:
        plt.show(block=True)
    elif mgr is not None:
        mgr.show()
    else:
        plt.show(block=False)


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
                   territorio=None, bloquear=True, mostrar_json=True,
                   con_boton_detener=True):
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
            _registrar_percibido(ev)
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
    if mostrar_json:
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
    if con_boton_detener:
        _agregar_boton_detener(fig)
    _indicador_modo_interaccion(fig)
    _mostrar_figura(bloquear)
    return percibidos, total_eventos


def plotear_perfil(eventos, perfil, fuente, percibidos, n_asignados=None,
                   totales=None, bloquear=True, mostrar_json=True,
                   con_boton_detener=True):
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
            _registrar_percibido(evento)

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
    prof_fondo = _prof_fondo_perfil(perfil, [-y for y in ys])
    ax_perfil.set_xlim(minX, maxX)
    ax_perfil.set_ylim(-prof_fondo, ALT_MAR_KM)
    ax_perfil.set_xlabel("Distancia a lo largo (km)", fontsize=9,
                         fontweight='bold')
    ax_perfil.set_ylabel("Profundidad (km)", fontsize=9, fontweight='bold')
    ax_perfil.tick_params(axis='both', labelsize=8)
    ax_perfil.grid(True, linestyle=':', alpha=0.4, color='gray', zorder=0)
    ax_perfil.set_title("Perfil %s (%.0f-%.0f km | 0-%.0f km de prof)"
                        % (perfil["id"], minX, maxX, prof_fondo),
                        fontsize=11, fontweight='bold', pad=10)

    if mostrar_json:
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
    if con_boton_detener:
        _agregar_boton_detener(fig)
    _indicador_modo_interaccion(fig)
    _mostrar_figura(bloquear)
    return percibidos, total_eventos


def plotear_ventana(eventos, perfil, fuente, percibidos, n_asignados=None,
                    totales=None, bloquear=True, mostrar_json=True,
                    con_boton_detener=True):
    """
    Abre la ventana de un perfil (planta + perfil). Se mantiene este alias
    para no cambiar el resto del flujo. Devuelve (percibidos, total_eventos).
    """
    return plotear_perfil(eventos, perfil, fuente, percibidos,
                          n_asignados, totales, bloquear=bloquear,
                          mostrar_json=mostrar_json,
                          con_boton_detener=con_boton_detener)


def plotear_sin_perfil(eventos, fuente, percibidos, n_asignados=None,
                       totales=None, bloquear=True, mostrar_json=True,
                       con_boton_detener=True):
    """Plotea los eventos sin perfil solo sobre la planta."""
    return plotear_planta(eventos, fuente, perfil=None,
                          n_asignados=n_asignados, totales=totales,
                          bloquear=bloquear, mostrar_json=mostrar_json,
                          con_boton_detener=con_boton_detener)


def _panel_analisis(grupos, perfiles_por_id, sin_perfil, fuente,
                    conteo_por_perfil, conteo_total, total_eventos,
                    n_sospechosos, total_percibidos=None):
    """
    Ventana inicial de análisis: tabla resumen de todos los perfiles con su
    mini-perfil, y acciones para abrir cada uno en detalle (en paralelo),
    abrir los mapas de territorio, filtrar por sospechosos, añadir la
    sismicidad histórica al mini-perfil y restablecer la vista de inicio. Al
    cerrar (Salir), los callbacks pendientes quedan desactivados para no tocar
    widgets ya destruidos.

    Se apoya en la raíz Tk compartida (_asegurar_raiz). Devuelve True si el
    panel quedó operativo (el programa debe mantener vivo el mainloop). Si no
    hay backend interactivo devuelve False (quien llama cae al flujo
    secuencial).
    """
    global _panel_activo
    import tkinter as tk
    from tkinter import ttk
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

    raiz = _asegurar_raiz()
    if raiz is None:
        return False
    _panel_activo = True

    estado = {'percibidos': 0, 'filtro_sospechosos': False, 'activo': True,
              'mostrar_hist': False}
    # Referencia al sub-panel de territorios (para poder cerrarlo desde Salir).
    terr_state = {'panel': None, 'cerrar': None}
    con_perfil = sum(len(v) for v in grupos.values())

    panel = tk.Toplevel(raiz)
    panel.title("Panel de análisis · %s — %d eventos (%d con perfil, %s)"
                % (fuente, total_eventos, con_perfil,
                   ("%d sospechosos" % n_sospechosos) if n_sospechosos else
                   "sin sospechosos"))
    panel.geometry("980x600")
    panel.minsize(860, 480)

    def _salir():
        global _panel_activo
        # Marca la sesión como inactiva ANTES de destruir widgets: así los
        # callbacks Tk que queden en cola se convierten en no-op y no tocan
        # widgets ya destruidos (evita "invalid command name").
        estado['activo'] = False
        _panel_activo = False
        # Cierra el sub-panel de territorios si estuviera abierto.
        cerrar_terr = terr_state.get('cerrar')
        if cerrar_terr is not None:
            try:
                cerrar_terr()
            except Exception:
                pass
        # Cierra solo las figuras de detalle: el ancla sostiene la raíz Tk.
        try:
            for num in list(plt.get_fignums()):
                if _fig_ancla is None or num != _fig_ancla.number:
                    plt.close(num)
        except Exception:
            pass
        try:
            fig_mini.clear()
        except Exception:
            pass
        try:
            panel.destroy()
        except Exception:
            pass
        try:
            raiz.quit()
        except Exception:
            pass

    panel.protocol("WM_DELETE_WINDOW", _salir)

    # --- Cabecera con resumen e indicaciones ---
    marco_cab = tk.Frame(panel)
    marco_cab.pack(fill='x', padx=8, pady=(8, 2))
    etiqueta_resumen = None

    def _actualizar_resumen():
        if not estado['activo'] or etiqueta_resumen is None or not total_percibidos:
            return
        try:
            if not etiqueta_resumen.winfo_exists():
                return
        except Exception:
            return
        etiqueta_resumen.config(
            text="Percibidos vistos: %d de %d en el catálogo."
                 % (len(_percibidos_escritos), total_percibidos))

    if total_eventos:
        tk.Label(marco_cab, justify='left', text=(
            "%d eventos · %d con perfil · %d sospechosos · doble clic en una "
            "fila para abrir el detalle" % (total_eventos, con_perfil,
                                            n_sospechosos)),
                 font=('', 10, 'bold')).pack(anchor='w')
        if fuente == "eventquery" and total_percibidos:
            etiqueta_resumen = tk.Label(marco_cab, justify='left', text="",
                                        font=('', 9))
            etiqueta_resumen.pack(anchor='w')
            _actualizar_resumen()
    else:
        tk.Label(marco_cab, text="No hay eventos para analizar.",
                 font=('', 10, 'bold')).pack(anchor='w')

    # --- Zona principal: tabla (izquierda) + mini-perfil (derecha) ---
    marco_principal = tk.Frame(panel)
    marco_principal.pack(fill='both', expand=True, padx=8, pady=4)

    marco_tabla = tk.Frame(marco_principal)
    marco_tabla.pack(side='left', fill='both', expand=True)
    columnas = ('n', 'perfil', 'eventos', 'sosp', 'perc', 'along')
    arbol = ttk.Treeview(marco_tabla, columns=columnas, show='headings',
                         height=20)
    encabezados = [('n', '#', 38), ('perfil', 'Perfil', 60),
                   ('eventos', 'Ev', 55), ('sosp', 'Sospechosos', 90),
                   ('perc', 'Percibidos', 80), ('along', 'Along (km)', 120)]
    for clave, texto, ancho in encabezados:
        arbol.heading(clave, text=texto)
        arbol.column(clave, width=ancho, minwidth=40, stretch=False)
    barra = ttk.Scrollbar(marco_tabla, orient='vertical', command=arbol.yview)
    arbol.configure(yscrollcommand=barra.set)
    arbol.pack(side='left', fill='both', expand=True)
    barra.pack(side='left', fill='y')

    # --- Mini-perfil insertado en el panel ---
    fig_mini = plt.Figure(figsize=(5.2, 3.4), dpi=82)
    lienzo_mini = FigureCanvasTkAgg(fig_mini, master=marco_principal)
    lienzo_mini.get_tk_widget().pack(side='left', fill='both', expand=True,
                                     padx=(10, 0))
    ax_mini = fig_mini.add_subplot(111)

    # --- Lista de ids mostrados (índice de fila en el árbol) ---
    filas = []

    def _poblar_arbol():
        if not estado['activo']:
            return
        arbol.delete(*arbol.get_children())
        del filas[:]
        for pid in sorted(grupos):
            total, sosp, perc, a_min, a_max = _resumen_perfil(grupos[pid],
                                                              fuente)
            if estado['filtro_sospechosos'] and not sosp:
                continue
            if a_min is not None:
                along = "%.0f-%.0f" % (a_min, a_max)
            else:
                along = "-"
            iid = arbol.insert(
                '', 'end',
                values=(len(filas) + 1, pid, total, sosp, perc, along))
            if sosp:
                arbol.item(iid, tags=('sosp',))
            filas.append(pid)
        arbol.tag_configure('sosp', foreground='#8b0000',
                            font=('', 10, 'bold'))

    def _actualizar_mini():
        if not estado['activo']:
            return
        sel = arbol.selection()
        if not sel:
            return
        idx = arbol.index(sel[0])
        if idx >= len(filas):
            return
        pid = filas[idx]
        fig_mini.clear()
        ax_nuevo = fig_mini.add_subplot(111)
        _mini_perfil(ax_nuevo, perfiles_por_id[pid], grupos[pid], fuente,
                     mostrar_hist=estado['mostrar_hist'])
        fig_mini.canvas.draw_idle()

    def _abrir_perfil_actual():
        if not estado['activo']:
            return
        sel = arbol.selection()
        if not sel:
            return
        idx = arbol.index(sel[0])
        if idx >= len(filas):
            return
        pid = filas[idx]
        perfil = perfiles_por_id[pid]
        _registrar_progreso("Perfil %s" % pid)
        p_, _ = plotear_ventana(grupos[pid], perfil, fuente,
                                estado['percibidos'],
                                n_asignados=conteo_por_perfil.get(pid),
                                totales=conteo_total,
                                bloquear=False,
                                mostrar_json=False,
                                con_boton_detener=False)
        estado['percibidos'] += p_
        _actualizar_resumen()

    def _abrir_territorios():
        if not estado['activo']:
            return
        if not sin_perfil:
            print("No hay eventos sin perfil.")
            return
        nacional, insular, antartico = _categorizar_por_territorio(sin_perfil)
        items = [(nombre, evs) for nombre, evs in [
            ("Nacional", nacional), ("Insular", insular),
            ("Antártico", antartico)] if evs]
        if not items:
            print("No hay eventos sin perfil.")
            return
        # Si ya está abierto, se trae al frente en vez de duplicarlo.
        if terr_state.get('panel') is not None:
            try:
                terr_state['panel'].lift()
                return
            except Exception:
                terr_state['panel'] = None

        top = tk.Toplevel(raiz)
        top.title("Mapas sin perfil · %s — %d eventos sin perfil"
                  % (fuente, len(sin_perfil)))
        top.geometry("780x520")
        terr_activo = {'activo': True}

        marco = tk.Frame(top)
        marco.pack(fill='both', expand=True, padx=8, pady=8)
        marco_tabla = tk.Frame(marco)
        marco_tabla.pack(side='left', fill='y')
        cols = ('terr', 'eventos', 'sosp', 'perc')
        arbol_t = ttk.Treeview(marco_tabla, columns=cols, show='headings',
                               height=8)
        for clave, texto, ancho in [('terr', 'Territorio', 110),
                                    ('eventos', 'Eventos', 70),
                                    ('sosp', 'Sospechosos', 95),
                                    ('perc', 'Percibidos', 85)]:
            arbol_t.heading(clave, text=texto)
            arbol_t.column(clave, width=ancho, minwidth=50, stretch=False)
        arbol_t.pack(side='left', fill='y')

        fig_mapa = plt.Figure(figsize=(4.6, 3.4), dpi=82)
        lienzo = FigureCanvasTkAgg(fig_mapa, master=marco)
        lienzo.get_tk_widget().pack(side='left', fill='both', expand=True,
                                    padx=(10, 0))

        datos = {}
        for nombre, evs in items:
            tot = len(evs)
            sosp = sum(1 for e in evs if e.get('sospechoso'))
            perc = sum(1 for e in evs if e.get('percibido') == 'S')
            iid = arbol_t.insert('', 'end', values=(nombre, tot, sosp, perc))
            datos[iid] = (nombre, evs)

        def _redibujar_mini():
            if not terr_activo['activo']:
                return
            sel = arbol_t.selection()
            if not sel:
                return
            nombre, evs = datos[sel[0]]
            fig_mapa.clear()
            ax = fig_mapa.add_subplot(111, projection=ccrs.PlateCarree())
            try:
                _mini_mapa_territorio(ax, nombre, evs, fuente)
            except Exception as e:
                ax.set_title("No se pudo dibujar %s" % nombre, fontsize=9)
                print("[Aviso] mini territorio %s: %s" % (nombre, e))
            fig_mapa.canvas.draw_idle()

        def _abrir_detalle_terr():
            if not terr_activo['activo']:
                return
            sel = arbol_t.selection()
            if not sel:
                return
            nombre, evs = datos[sel[0]]
            _registrar_progreso("Territorio %s" % nombre)
            p_, _ = plotear_planta(
                evs, fuente, perfil=None,
                n_asignados=conteo_por_perfil.get("(%s)" % nombre),
                totales=conteo_total, territorio=nombre,
                bloquear=False, mostrar_json=False,
                con_boton_detener=False)
            estado['percibidos'] += p_
            _actualizar_resumen()

        def _cerrar_territorios():
            if not terr_activo['activo']:
                return
            terr_activo['activo'] = False
            terr_state['panel'] = None
            terr_state['cerrar'] = None
            try:
                fig_mapa.clear()
            except Exception:
                pass
            try:
                top.destroy()
            except Exception:
                pass

        arbol_t.bind('<<TreeviewSelect>>', lambda e: _redibujar_mini())
        arbol_t.bind('<Double-1>', lambda e: _abrir_detalle_terr())
        top.protocol("WM_DELETE_WINDOW", _cerrar_territorios)

        marco_bot = tk.Frame(top)
        marco_bot.pack(fill='x', padx=8, pady=(0, 8))
        tk.Button(marco_bot, text="Abrir detalle",
                  command=_abrir_detalle_terr, padx=10, pady=6).pack(
                      side='left', padx=4)
        tk.Button(marco_bot, text="Cerrar", command=_cerrar_territorios,
                  padx=10, pady=6).pack(side='left', padx=4)

        terr_state['panel'] = top
        terr_state['cerrar'] = _cerrar_territorios
        # Enganches para pruebas.
        top._arbol = arbol_t
        top._fig_mapa = fig_mapa
        top._redibujar_mini = _redibujar_mini
        top._abrir_detalle = _abrir_detalle_terr
        top._cerrar = _cerrar_territorios

        arbol_t.selection_set(arbol_t.get_children()[0])
        _redibujar_mini()

    def _alternar_filtro():
        if not estado['activo']:
            return
        estado['filtro_sospechosos'] = not estado['filtro_sospechosos']
        btn_filtro.config(
            text=("Todos los perfiles" if estado['filtro_sospechosos']
                  else "Solo sospechosos"))
        _poblar_arbol()
        if arbol.get_children():
            arbol.selection_set(arbol.get_children()[0])
        _actualizar_mini()

    def _ir_inicio():
        # Restaura el estado inicial: filtro a todos, tabla repoblada y
        # primera fila seleccionada con su mini-perfil.
        if not estado['activo']:
            return
        if estado['filtro_sospechosos']:
            _alternar_filtro()
        else:
            _poblar_arbol()
        if arbol.get_children():
            arbol.selection_set(arbol.get_children()[0])
        _actualizar_mini()

    arbol.bind('<<TreeviewSelect>>', lambda e: _actualizar_mini())
    arbol.bind('<Double-1>', lambda e: _abrir_perfil_actual())

    # --- Botones ---
    marco_botones = tk.Frame(panel)
    marco_botones.pack(fill='x', padx=8, pady=(2, 8))
    estilo_btn = {'padx': 10, 'pady': 6}

    def _boton(marco, texto, fn):
        tk.Button(marco, text=texto, command=fn, **estilo_btn).pack(
            side='left', padx=4)

    var_hist = tk.BooleanVar(value=False)

    def _alternar_hist():
        if not estado['activo']:
            return
        estado['mostrar_hist'] = bool(var_hist.get())
        _actualizar_mini()

    _boton(marco_botones, "Abrir detalle", _abrir_perfil_actual)
    _boton(marco_botones, "Mapas sin perfil", _abrir_territorios)
    btn_filtro = tk.Button(marco_botones, text="Solo sospechosos",
                           command=_alternar_filtro, **estilo_btn)
    btn_filtro.pack(side='left', padx=4)
    _boton(marco_botones, "Inicio", _ir_inicio)
    chk_hist = tk.Checkbutton(marco_botones, text="Sismicidad histórica",
                              variable=var_hist, command=_alternar_hist,
                              **estilo_btn)
    chk_hist.pack(side='left', padx=4)
    _boton(marco_botones, "Salir", _salir)

    _poblar_arbol()
    if arbol.get_children():
        arbol.selection_set(arbol.get_children()[0])
        _actualizar_mini()

    # Enganches para depuración/pruebas (sin efecto en la operación normal).
    panel._arbol = arbol
    panel._fig_mini = fig_mini
    panel._etiqueta_resumen = etiqueta_resumen
    panel._actualizar_mini = _actualizar_mini
    panel._actualizar_resumen = _actualizar_resumen
    panel._btn_filtro = btn_filtro
    panel._chk_hist = chk_hist
    panel._var_hist = var_hist
    panel._abrir_perfil_actual = _abrir_perfil_actual
    panel._abrir_territorios = _abrir_territorios
    panel._alternar_filtro = _alternar_filtro
    panel._alternar_hist = _alternar_hist
    panel._ir_inicio = _ir_inicio
    panel._poblar_arbol = _poblar_arbol
    panel._salir = _salir
    return True


def _despliegue_secuencial(grupos, perfiles_por_id, sin_perfil, fuente,
                           conteo_por_perfil, conteo_total, bloquear=True):
    """
    Fallback para cuando no hay backend interactivo (headless): un perfil por
    ventana y luego los mapas de territorio de los eventos sin perfil.
    En modo interactivo el análisis se hace desde el panel, así que solo se
    llega aquí si el panel no pudo abrirse.
    Devuelve (percibidos, total_por_perfil).
    """
    global _detener_despliegue
    _detener_despliegue = False

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
                               totales=conteo_total, bloquear=bloquear)
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
                    n_asignados=conteo_por_perfil.get("(%s)" % nombre),
                    totales=conteo_total, territorio=nombre,
                    bloquear=bloquear
                )
                percibidos += p
                total_por_perfil[nombre] = n

    if despliegue_detenido():
        print("Despliegue detenido por el usuario.")

    return percibidos, total_por_perfil


def _escribir_log_sesion(fuente, total_eventos, n_sospechosos,
                         total_percibidos=None, vistos=None):
    """
    Guarda el resumen de la sesión en dos archivos del directorio de trabajo:
      - resumen_historico.log: acumulativo. Si no existe se crea con
        encabezado (puede haberse borrado); luego se añade una línea por
        ejecución.
      - resumen_sesion.log: solo la sesión actual (se pisa en cada ejecución).
    Devuelve la línea escrita.
    """
    import datetime
    ahora = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    t_perc = total_percibidos if total_percibidos is not None else "-"
    v = vistos if vistos is not None else "-"
    linea = ("%s | %s | %d | %d | %s | %s"
             % (ahora, fuente, total_eventos, n_sospechosos, t_perc, v))
    encabezado = ("fecha hora | fuente | eventos | sospechosos | "
                  "percibidos catalogo | percibidos vistos")
    ruta_hist = rutas.p_ploteo("resumen_historico.log")
    ruta_sesion = rutas.p_ploteo("resumen_sesion.log")
    if not os.path.isfile(ruta_hist):
        with open(ruta_hist, "w") as f:
            f.write(encabezado + "\n")
    with open(ruta_hist, "a") as f:
        f.write(linea + "\n")
    with open(ruta_sesion, "w") as f:
        f.write(encabezado + "\n")
        f.write(linea + "\n")
    return linea


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
        _percibidos_escritos.clear()
        with open(rutas.p_ploteo("percibidos.txt"), "w") as f:
            f.write("id fecha hora latitud longitud prof magnitud tipomag percibido\n")

    # Carga el conteo por perfil que generajson.py dejó en
    # datos/conteo_perfiles_<fuente>.json para mostrarlo a medida que se plotea.
    conteo_por_perfil = {}
    conteo_total = None
    conteo_archivo = rutas.p_datos('conteo_perfiles_%s.json' % fuente)
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

    n_eventos = len(eventos)
    n_sospechosos = sum(1 for ev in eventos if ev.get('sospechoso'))
    # Total de percibidos del catálogo extraído (denominador del resumen
    # "vistos de totales").
    total_percibidos = sum(
        1 for ev in eventos if ev.get('percibido') == "S")

    # Nueva interacción: panel de análisis con vista general y detalle a
    # demanda. Si no hay backend interactivo (o falla) se cae al flujo
    # secuencial histórico.
    if _panel_analisis(grupos, perfiles_por_id, sin_perfil, fuente,
                       conteo_por_perfil, conteo_total, n_eventos,
                       n_sospechosos, total_percibidos):
        # Mantiene viva la raíz Tk: procesa eventos del panel y de las
        # figuras de detalle hasta que el usuario cierra la sesión. Se usa
        # el mainloop de la raíz (y no plt.show()) para que el ancla oculta
        # nunca vuelva a mapearse como cuadro vacío.
        raiz = _raiz_tk()
        if raiz is not None:
            raiz.mainloop()
    else:
        _despliegue_secuencial(grupos, perfiles_por_id, sin_perfil, fuente,
                               conteo_por_perfil, conteo_total,
                               bloquear=True)

    if fuente == "eventquery":
        vistos = len(_percibidos_escritos)
        _escribir_log_sesion(fuente, n_eventos, n_sospechosos,
                             total_percibidos, vistos)
        print("De %d percibidos en el catalogo, %d eventos percibidos "
              "vistos en esta sesion." % (total_percibidos, vistos))
    else:
        _escribir_log_sesion(fuente, n_eventos, n_sospechosos)


if __name__ == "__main__":
    main()