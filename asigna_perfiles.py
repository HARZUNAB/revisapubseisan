#!/usr/bin/env python3
"""
asigna_perfiles.py
==================
Asigna cada evento (sismo) al perfil de subducción más cercano, considerando
tanto la posición horizontal (epicentro) como la profundidad (residuo al slab).

Los perfiles se detectan de forma DINÁMICA desde la carpeta "grillas":
basta agregar o reemplazar los pares de archivos  slabP###.tmp / topoP###.tmp
(la topografía es opcional, solo se usa para dibujar el fondo del perfil).
No depende de la cantidad de perfiles ni de su numeración.

Para cada evento y cada perfil se calcula:
    dist_horiz_km : distancia perpendicular del epicentro a la línea central
                    del perfil (km, con corrección cos(lat)).
    along_km      : posición del evento a lo largo del perfil (km).
    residuo_km    : |profundidad_evento - profundidad_del_slab(al along_km)|.
                    Si el slab no tiene cobertura en esa posición, se omite
                    el término de profundidad (residuo_km = None -> se usa 0).
    dist_asoc²    = dist_horiz_km² + (K_PESO_PROFUNDIDAD * residuo_km)²

PRECONDICIÓN: LA PROFUNDIDAD DEL EVENTO TIENE QUE LLEGAR POSITIVA
----------------------------------------------------------------
El slab se guarda en profundidad ABSOLUTA (abs(z), ver _cargar_grilla), así
que residuo_km = |prof - slab| solo significa "distancia al slab" si la
profundidad del evento llega como magnitud positiva, en km y hacia abajo.

Hoy todas las fuentes cumplen:
  * SeisComp   -> m_depth_value viene positiva, en km.
  * Seisan y eventquery -> positivas también, verificado sobre las 901 filas
    de new_2_sep_2026_1_29.csv (todas entre 5.0 y 307.6 km, ninguna negativa).

Si alguna vez una fuente entregara profundidad negativa, la resta se volvería
suma (|-39.3 - 100| = 139.3 en vez de 60.7), dist_asoc se inflaría y tanto el
umbral de asociación como los criterios de sismicidad se romperían sin que
nada fallara visiblemente: el módulo seguiría devolviendo números, solo que
todos sospechosos. Por eso asignar_eventos() cuenta las profundidades
negativas y avisa por el log. Si aparece ese aviso, el problema está en el
origen de los datos, no acá, y conviene no mirar los conteos hasta
corregirlo.

El evento se asigna al perfil de menor dist_asoc si dist_asoc <= UMBRAL.
Si ningún perfil cumple ese umbral, se aplica un respaldo por COBERTURA del
set de perfiles, de modo que el comportamiento no dependa de constantes
pensadas para un set particular:

  * Lateral: un evento que cae entre dos perfiles adyacentes (dentro de la
    celda de Voronoi del perfil más cercano) se asigna a ese perfil, aunque
    su distancia perpendicular supere el umbral fijo. Así no quedan "cuñas"
    sin perfil entre perfiles separados.
  * Borde: el primer y el último perfil (por latitud media) delimitan el set.
    Un evento del lado EXTERIOR de un perfil de borde solo se asigna si su
    distancia es <= MARGEN_BORDE_KM; si no, queda SIN PERFIL con motivo
    "fuera_cobertura_norte" / "fuera_cobertura_sur".
  * Longitudinal: si la proyección cae más allá de los extremos de la sección
    en más de MARGEN_BORDE_KM, el evento queda SIN PERFIL con motivo
    "fuera_cobertura_extremo" (p. ej. eventos oceánicos lejanos).

El campo "motivo" del resultado queda en None cuando el evento fue asignado.
UMBRAL_PERP_KM (opcional, None por defecto) actúa como tope lateral explícito
para quien quiera limitar el respaldo; con None no hay tope.
"""

import os
import re
import math
import numpy as np


# =========================================================================
# PARÁMETROS CONFIGURABLES (EDITAR SEGÚN SEA NECESARIO)
# Estos valores pueden ajustarse manualmente aquí o sobrescribirse por
# argumento al ejecutar generajson.py (--umbral y --k).
# =========================================================================

# GRILLAS_DIR: carpeta que contiene los perfiles dinámicos (slabP###.tmp y
# topoP###.tmp). Se detectan automáticamente todos los perfiles presentes,
# sin importar su número ni la cantidad. Por defecto apunta a la carpeta
# "grillas" del proyecto (se resuelve respecto a este archivo), de modo que
# los scripts puedan ejecutarse desde cualquier directorio. También se puede
# pasar una ruta relativa al CWD o una ruta absoluta.
GRILLAS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "grillas")

# UMBRAL_DIST_KM: distancia máxima en km del índice de asociación (dist_asoc)
# para asignar un evento a un perfil. Si el mejor perfil supera este umbral,
# el evento queda SIN PERFIL (campo "perfil": None) y solo se plotea sobre
# la planta. Default 110 km (criterio similar a mapasOPA/perfiles.py).
UMBRAL_DIST_KM = 110.0

# UMBRAL_PERP_KM: tope lateral OPCIONAL (km) para el respaldo por cobertura.
# Con None (default) no hay tope: un evento entre dos perfiles adyacentes se
# asigna al más cercano sin importar la distancia perpendicular, y los bordes
# del set se controlan con MARGEN_BORDE_KM. Si se fija un valor, el respaldo
# lateral solo actúa cuando la distancia perpendicular es <= ese valor.
UMBRAL_PERP_KM = None

# MARGEN_BORDE_KM: margen (km) admitido más allá del borde del set de
# perfiles (primer/último perfil y extremos de cada sección). Con 0.0, un
# evento al norte del perfil más septentrional, al sur del más meridional, o
# más allá del extremo de una sección, queda SIN PERFIL y se reporta como
# "fuera de cobertura" para que se use un set con mayor cobertura. Un valor
# mayor permite asignarlo al perfil de borde hasta esa distancia.
MARGEN_BORDE_KM = 0.0

# _TOL_KM: tolerancia geométrica (km) para no rechazar un evento por un
# sobrepaso ínfimo del extremo o del borde (ruido de proyección).
_TOL_KM = 1.0

# K_PESO_PROFUNDIDAD: peso de la profundidad frente a la distancia horizontal
# en la métrica  dist_asoc² = dist_horiz² + (K * residuo_slab)².
#   K = 1.0 -> mismo peso para distancia y profundidad
#   K > 1.0 -> la profundidad (residuo al slab) gana importancia
#   K = 0.0 -> se ignora la profundidad (solo distancia horizontal)
# Configurable; default 1.0.
K_PESO_PROFUNDIDAD = 1.0

# GRADO_KM_LAT / GRADO_KM_LON: factores de conversión de grados a km.
GRADO_KM_LAT = 111.0
GRADO_KM_LON = 111.0

# ANCHO_BIN_KM: ancho del bineo de la coordenada "a lo largo" (p) para
# construir la línea central de cada perfil a partir de la franja q del .tmp.
ANCHO_BIN_KM = 1.0


def _km_por_deg_lon(lat_ref):
    """Km por grado de longitud a la latitud de referencia (corrección cos)."""
    lat_ref = float(lat_ref)
    return GRADO_KM_LON * max(0.1, math.cos(math.radians(lat_ref)))


def _proyectar_a_plano(lon, lat, lon_ref, lat_ref):
    """Convierte (lon,lat) a coordenadas planas locales en km."""
    k_lon = _km_por_deg_lon(lat_ref)
    x = (np.asarray(lon) - lon_ref) * k_lon
    y = (np.asarray(lat) - lat_ref) * GRADO_KM_LAT
    return x, y


def _centrolinea_perfil(archivo_slab):
    """
    Lee un archivo slabP###.tmp y devuelve la línea central del perfil.
    El .tmp tiene columnas GMT: p (km a lo largo), q (km perpendicular),
    r (lon), s (lat), x, y, z (profundidad del slab, km, NEGATIVA si es dato).

    Salida: diccionario con arrays ordenados por p:
        p      : distancia a lo largo del perfil en km (bins de ANCHO_BIN_KM)
        lon    : lon promedio de cada bin  (línea central)
        lat    : lat promedio de cada bin
        depth  : profundidad del slab en km (abs(z)), NaN si no hay dato
    """
    filas = []
    with open(archivo_slab, 'r') as f:
        for linea in f:
            if linea.startswith('#') or not linea.strip():
                continue
            partes = linea.strip().split()
            if len(partes) < 7:
                continue
            try:
                p = float(partes[0])
                lon = float(partes[2])
                lat = float(partes[3])
                z = float(partes[6])
            except ValueError:
                continue
            filas.append((p, lon, lat, z))

    if not filas:
        return None

    filas.sort(key=lambda t: t[0])  # orden por distancia a lo largo

    p_bin = ANCHO_BIN_KM * np.round(np.array([t[0] for t in filas]) / ANCHO_BIN_KM)

    uniq = np.unique(p_bin)
    lon_cen = np.full(len(uniq), np.nan)
    lat_cen = np.full(len(uniq), np.nan)
    depth_cen = np.full(len(uniq), np.nan)

    for i, pu in enumerate(uniq):
        mask = np.abs(p_bin - pu) < 1e-9
        idx = np.where(mask)[0]
        lon_cen[i] = np.mean([filas[j][1] for j in idx])
        lat_cen[i] = np.mean([filas[j][2] for j in idx])
        zs = [filas[j][3] for j in idx]
        valid = [z for z in zs if not math.isnan(z)]
        if valid:
            depth_cen[i] = np.mean([abs(z) for z in valid])

    return {
        "p": uniq,
        "lon": lon_cen,
        "lat": lat_cen,
        "depth": depth_cen,
    }


def _leer_topo(archivo_topo):
    """
    Lee un archivo topoP###.tmp y devuelve las columnas (p, altitud_m).
    El .tmp tiene columnas GMT: p, q, r (lon), s (lat), x, y, z (altitud en m).
    """
    p_list = []
    alt_list = []
    if not os.path.isfile(archivo_topo):
        return np.array(p_list), np.array(alt_list)
    with open(archivo_topo, 'r') as f:
        for linea in f:
            if linea.startswith('#') or not linea.strip():
                continue
            partes = linea.strip().split()
            if len(partes) < 7:
                continue
            try:
                p_list.append(float(partes[0]))
                alt_list.append(float(partes[6]))
            except ValueError:
                continue
    return np.array(p_list), np.array(alt_list)


def detectar_perfiles(grillas_dir=GRILLAS_DIR):
    """
    Escanea la carpeta de grillas y devuelve la lista de perfiles disponibles.
    Se reconocen sólo archivos con el patrón '^slabP(\d+)\.tmp$' (igual que en
    mapasOPA). Para cada uno se carga su par de topografía si existe.

    Salida: lista (ordenada por número) de diccionarios con:
        id    : 'P001', 'P002', ... (nombre derivado del archivo)
        num   : número entero del perfil
        archivo : nombre exacto del archivo slab (p. ej. 'slabP001.tmp')
        lat_media : latitud media de la sección (para ubicar los bordes)
        slab  : diccionario de _centrolinea_perfil
        topo_p : array con distancia a lo largo de la topografía (km)
        topo_alt : array con altitud en metros
    """
    perfiles = []
    if not os.path.isdir(grillas_dir):
        return perfiles

    nombres = []
    for nombre in os.listdir(grillas_dir):
        m = re.match(r'^slabP(\d+)\.tmp$', nombre)
        if m:
            nombres.append((int(m.group(1)), nombre))
    nombres.sort(key=lambda x: x[0])

    for num, nombre in nombres:
        slab = _centrolinea_perfil(os.path.join(grillas_dir, nombre))
        if slab is None:
            continue
        # La topografía usa el mismo ancho de dígitos que el slab (P###).
        # Si no existe con ese ancho, se intenta la numeración de 3 dígitos.
        num_txt = nombre[len("slabP"):-len(".tmp")]
        ruta_topo = os.path.join(grillas_dir, "topoP%s.tmp" % num_txt)
        if not os.path.isfile(ruta_topo):
            ruta_topo = os.path.join(grillas_dir, "topoP%03d.tmp" % num)
        topo_p, topo_alt = _leer_topo(ruta_topo)
        lat_media = float(np.nanmean(slab["lat"])) if len(slab["lat"]) else None
        perfiles.append({
            "id": "P%03d" % num,
            "num": num,
            "archivo": nombre,
            "lat_media": lat_media,
            "slab": slab,
            "topo_p": topo_p,
            "topo_alt": topo_alt,
        })

    # Aviso si dos archivos producen el mismo id (p. ej. slabP01.tmp y
    # slabP001.tmp): significarían secciones distintas bajo la misma etiqueta
    # y perfiles_por_id se quedaría con una sola en silencio.
    por_id = {}
    for per in perfiles:
        por_id.setdefault(per["id"], []).append(per["archivo"])
    for pid, archivos in sorted(por_id.items()):
        if len(archivos) > 1:
            print("[asigna_perfiles] Aviso: el id '%s' lo producen varios "
                  "archivos (%s). Normalice la nomenclatura de 'grillas' para "
                  "evitar que se confundan secciones distintas."
                  % (pid, ", ".join(archivos)))

    return perfiles


def _detalle_perfil(lon, lat, perfil):
    """
    Geometría del punto (lon,lat) respecto de la línea central del perfil.

    Devuelve una tupla (perp, along, lat_proj, exceso) o None si el perfil no
    tiene geometría suficiente:
        perp     : distancia perpendicular (km) al tramo más cercano.
        along    : posición a lo largo del perfil (km), recortada a los
                   extremos de la sección.
        lat_proj : latitud del punto más cercano de la sección (para saber de
                   qué lado queda el evento).
        exceso   : distancia (km) que la proyección cae más allá del extremo
                   de la sección (0 si proyecta dentro de la sección).
    """
    slab = perfil["slab"]
    lon_c = slab["lon"]
    lat_c = slab["lat"]
    p_c = slab["p"]

    if len(lon_c) < 2:
        return None

    lon_ref = float(np.nanmean(lon_c))
    lat_ref = float(np.nanmean(lat_c))

    # coordenadas planas de la línea central
    x_c, y_c = _proyectar_a_plano(lon_c, lat_c, lon_ref, lat_ref)
    x_p, y_p = _proyectar_a_plano(lon, lat, lon_ref, lat_ref)

    x_p = float(x_p)
    y_p = float(y_p)

    # proyección punto-segmento sobre cada tramo de la polilínea
    dx = np.diff(x_c)
    dy = np.diff(y_c)
    seg_len2 = dx * dx + dy * dy

    vx = x_p - x_c[:-1]
    vy = y_p - y_c[:-1]

    t = (vx * dx + vy * dy) / np.where(seg_len2 > 0, seg_len2, 1.0)
    tc = np.clip(t, 0.0, 1.0)

    fx = x_c[:-1] + tc * dx
    fy = y_c[:-1] + tc * dy

    dist2 = (x_p - fx) ** 2 + (y_p - fy) ** 2
    i = int(np.argmin(dist2))
    dist_min = math.sqrt(dist2[i])

    along = p_c[i] + tc[i] * (p_c[i + 1] - p_c[i])
    lat_proj = lat_c[i] + tc[i] * (lat_c[i + 1] - lat_c[i])

    seg = math.sqrt(seg_len2[i]) if seg_len2[i] > 0 else 0.0
    exceso = abs(float(t[i]) - float(tc[i])) * seg

    return dist_min, along, float(lat_proj), exceso


def distancia_al_perfil(lon, lat, perfil):
    """
    Distancia perpendicular (km) del punto (lon,lat) al perfil y su posición
    a lo largo del perfil (km). Envoltorio de _detalle_perfil.
    """
    det = _detalle_perfil(lon, lat, perfil)
    if det is None:
        return None, None
    perp, along, _lat_proj, _exceso = det
    return perp, along


def profundidad_slab_en(perfil, along_km):
    """
    Profundidad del slab (km, positiva) del perfil en la posición along_km.
    Devuelve NaN si no hay cobertura del slab en esa posición.
    """
    slab = perfil["slab"]
    p = slab["p"]
    depth = slab["depth"]
    if len(p) < 1:
        return np.nan
    if along_km is None:
        return np.nan
    # np.interp exige p creciente (ya está ordenado)
    return float(np.interp(float(along_km), p, depth, left=np.nan, right=np.nan))


def cobertura_set(perfiles):
    """Extensión geográfica (lat/lon min-máx) del set de perfiles detectado."""
    lats, lons = [], []
    for p in perfiles:
        for v in p["slab"]["lat"]:
            if not math.isnan(v):
                lats.append(float(v))
        for v in p["slab"]["lon"]:
            if not math.isnan(v):
                lons.append(float(v))
    if not lats or not lons:
        return None
    return {"n_perfiles": len(perfiles),
            "lat_min": min(lats), "lat_max": max(lats),
            "lon_min": min(lons), "lon_max": max(lons)}


def _espaciado_mediano(perfiles):
    """Separación mediana (km) entre perfiles consecutivos por latitud media."""
    lats = sorted(p["lat_media"] for p in perfiles
                  if p.get("lat_media") is not None)
    if len(lats) < 2:
        return None
    difs = [abs(lats[i + 1] - lats[i]) for i in range(len(lats) - 1)]
    return float(np.median(difs)) * GRADO_KM_LAT


def asignar_perfil_evento(lon, lat, prof,
                          perfiles,
                          umbral=UMBRAL_DIST_KM,
                          k_peso=K_PESO_PROFUNDIDAD,
                          umbral_perp=UMBRAL_PERP_KM,
                          margen_borde=MARGEN_BORDE_KM,
                          espaciado=None):
    """
    Asigna un evento (lon, lat, prof) al perfil más cercano según la métrica
    combinada. Devuelve un diccionario con:

        perfil      : id del perfil ('P001', ...) o None si queda fuera
        along_km    : posición a lo largo del perfil (km)
        perp_km     : distancia perpendicular epicentro-perfil (km)
        residuo_km  : |prof - slab(along)| en km (None si slab sin cobertura)
        dist_asoc   : índice de asociación (km)
        motivo      : None si fue asignado; si no, por qué quedó fuera:
                      'fuera_cobertura_norte' / '_sur' / '_extremo' /
                      'fuera_umbral' / 'sin_perfiles'.

    Cobertura del set: primero se determina si el evento cae dentro. Un evento
    entre dos perfiles (celda de Voronoi del más cercano) siempre está dentro.
    En los bordes (primer/último perfil por latitud media) se admite hasta
    MEDIO HUECO entre perfiles (cobertura natural del set) más MARGEN_BORDE_KM.
    Más allá de los extremos de la sección (longitudinal) se admite el mismo
    margen. Si queda dentro, se asigna al perfil de menor dist_asoc cuando
    dist_asoc <= umbral; si no, al perfil más cercano. Si queda fuera, queda
    sin perfil con su motivo.

    La determinación de "sospechoso" (posible mal localizado) no se hace aquí;
    vive en sismicidad.es_sospechoso(), que recibe estos parámetros y aplica
    los criterios configurables (slab + sismicidad histórica).
    """
    # Bordes del set por latitud media de cada sección.
    con_lat = [p for p in perfiles if p.get("lat_media") is not None]
    id_norte = max(con_lat, key=lambda p: p["lat_media"])["id"] if con_lat else None
    id_sur = min(con_lat, key=lambda p: p["lat_media"])["id"] if con_lat else None

    if espaciado is None:
        espaciado = _espaciado_mediano(perfiles)
    medio_hueco = (0.5 * espaciado) if espaciado else 0.0

    mejor = None        # (dist_asoc, id, along, perp, residuo)
    mejor_perp = None   # (perp, id, along, residuo, dist_asoc, lat_proj, exceso)

    for per in perfiles:
        det = _detalle_perfil(lon, lat, per)
        if det is None:
            continue
        perp, along, lat_proj, exceso = det

        slab_prof = profundidad_slab_en(per, along)
        if math.isnan(slab_prof):
            residuo = None
            residuo_uso = 0.0
        else:
            residuo = abs(float(prof) - slab_prof) if prof is not None else None
            residuo_uso = residuo if residuo is not None else 0.0

        dist_asoc = math.sqrt(perp * perp + (k_peso * residuo_uso) ** 2)

        if mejor is None or dist_asoc < mejor[0]:
            mejor = (dist_asoc, per["id"], along, perp, residuo)
        if mejor_perp is None or perp < mejor_perp[0]:
            mejor_perp = (perp, per["id"], along, residuo, dist_asoc,
                          lat_proj, exceso)

    if mejor is None:
        return {"perfil": None, "along_km": None, "perp_km": None,
                "residuo_km": None, "dist_asoc": None,
                "motivo": "sin_perfiles"}

    (perp_p, perfil_id_p, along_p, residuo_p, dist_asoc_p,
     lat_proj_p, exceso_p) = mejor_perp

    # Cobertura: interior siempre dentro; borde hasta medio hueco + margen;
    # longitudinal hasta el margen.
    if math.isnan(lat_proj_p):
        lat_proj_p = lat
    al_norte = lat > lat_proj_p
    hacia_afuera = ((perfil_id_p == id_norte and al_norte) or
                    (perfil_id_p == id_sur and not al_norte))
    borde_ok = ((not hacia_afuera) or
                (perp_p <= medio_hueco + margen_borde + _TOL_KM))
    exceso_ok = exceso_p <= margen_borde + _TOL_KM
    cap_ok = (umbral_perp is None) or (perp_p <= umbral_perp + _TOL_KM)

    if exceso_ok and borde_ok and cap_ok:
        # Dentro de cobertura: métrica primaria o, si no, el más cercano.
        dist_asoc, perfil_id, along, perp, residuo = mejor
        if dist_asoc <= umbral:
            return {
                "perfil": perfil_id,
                "along_km": round(float(along), 3),
                "perp_km": round(float(perp), 3),
                "residuo_km": round(residuo, 3) if residuo is not None else None,
                "dist_asoc": round(dist_asoc, 3),
                "motivo": None,
            }
        return {
            "perfil": perfil_id_p,
            "along_km": round(float(along_p), 3),
            "perp_km": round(float(perp_p), 3),
            "residuo_km": round(residuo_p, 3) if residuo_p is not None else None,
            "dist_asoc": round(dist_asoc_p, 3),
            "motivo": None,
        }

    # Fuera de cobertura: clasificar el motivo.
    if not exceso_ok:
        motivo = "fuera_cobertura_extremo"
    elif not cap_ok:
        motivo = "fuera_umbral"
    elif perfil_id_p == id_norte and al_norte:
        motivo = "fuera_cobertura_norte"
    elif perfil_id_p == id_sur and not al_norte:
        motivo = "fuera_cobertura_sur"
    else:
        motivo = "fuera_cobertura"
    return {"perfil": None, "along_km": None,
            "perp_km": round(float(perp_p), 3),
            "residuo_km": round(residuo_p, 3) if residuo_p is not None else None,
            "dist_asoc": round(dist_asoc_p, 3),
            "motivo": motivo}


def asignar_eventos(eventos, umbral=UMBRAL_DIST_KM, k_peso=K_PESO_PROFUNDIDAD,
                    umbral_perp=UMBRAL_PERP_KM, margen_borde=MARGEN_BORDE_KM,
                    grillas_dir=GRILLAS_DIR, perfiles=None, on_avance=None):
    """
    Asigna una lista de eventos (dicts con 'lon', 'lat', 'prof') a sus perfiles.
    Adorna cada dict con los campos: perfil, along_km, perp_km, residuo_km,
    dist_asoc, motivo. Devuelve la lista modificada.

    perfiles: lista ya detectada (para reutilizarla y conocer la cobertura del
              set); si es None se detecta desde grillas_dir.
    on_avance: callback opcional recibido la fracción [0,1] por cada evento
    procesado (lo usa generajson.py para reportar avance a la interfaz).
    """
    if perfiles is None:
        perfiles = detectar_perfiles(grillas_dir)
    if not perfiles:
        print("[asigna_perfiles] Aviso: no se detectaron perfiles en '{}'.".format(
            grillas_dir))
    espaciado = _espaciado_mediano(perfiles)

    # Cuenta profundidades negativas para avisar al final. Ver la nota de
    # PRECONDICIÓN en el docstring: con profundidad negativa el residuo se
    # convierte en suma y todos los eventos terminan pareciendo sospechosos,
    # sin que nada falle. Acumular acá y avisar una vez evita inundar el log
    # cuando el problema es de origen y afecta a todo el lote.
    prof_negativos = 0
    primero_negativo = None

    total_ev = len(eventos)
    for i, ev in enumerate(eventos):
        if on_avance:
            on_avance((i + 1) / total_ev if total_ev else 1.0)
        try:
            lon = float(ev.get('lon'))
            lat = float(ev.get('lat'))
            prof = ev.get('prof')
            if prof is None:
                prof = None
            else:
                prof = float(prof)
                if prof < 0:
                    prof_negativos += 1
                    if primero_negativo is None:
                        primero_negativo = i
        except (TypeError, ValueError):
            lon = None

        if lon is None:
            ev.update({"perfil": None, "along_km": None, "perp_km": None,
                       "residuo_km": None, "dist_asoc": None,
                       "motivo": "sin_coordenadas"})
            continue

        resultado = asignar_perfil_evento(lon, lat, prof, perfiles,
                                          umbral=umbral, k_peso=k_peso,
                                          umbral_perp=umbral_perp,
                                          margen_borde=margen_borde,
                                          espaciado=espaciado)
        ev.update(resultado)

    if prof_negativos:
        print("[asigna_perfiles] Aviso: {} de {} eventos llegaron con "
              "profundidad negativa (el primero en el índice {}). El residuo "
                "se calcula como suma y no como diferencia contra el slab, así "
                "que dist_asoc queda inflado y el umbral de asociación puede "
                "dejar de ser correcto. Revisá el origen de los datos "
                "antes de confiar en los perfiles ni en los conteos de "
                "sismicidad.".format(prof_negativos, total_ev, primero_negativo))

    return eventos


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--listar":
        perfiles = detectar_perfiles()
        print("Perfiles detectados ({}):".format(len(perfiles)))
        for per in perfiles:
            slab = per["slab"]
            print("  {}  p: {:.0f}-{:.0f} km | lon {:.2f}-{:.2f} | "
                  "lat {:.2f}-{:.2f} | topo {}".format(
                      per["id"],
                      slab["p"].min(), slab["p"].max(),
                      np.nanmin(slab["lon"]), np.nanmax(slab["lon"]),
                      np.nanmin(slab["lat"]), np.nanmax(slab["lat"]),
                      "S" if len(per["topo_p"]) else "N"))
        sys.exit(0)

    # Prueba rápida: python3 asigna_perfiles.py <lon> <lat> <prof>
    if len(sys.argv) >= 4:
        lon = float(sys.argv[1])
        lat = float(sys.argv[2])
        prof = float(sys.argv[3])
        perfiles = detectar_perfiles()
        print(asignar_perfil_evento(lon, lat, prof, perfiles))