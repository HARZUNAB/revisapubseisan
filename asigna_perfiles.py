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

El evento se asigna al perfil de menor dist_asoc si dist_asoc <= UMBRAL.
Si todos los perfiles superan el umbral, el evento queda SIN PERFIL (None).
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
        topo_p, topo_alt = _leer_topo(os.path.join(
            grillas_dir, "topoP%03d.tmp" % num))
        perfiles.append({
            "id": "P%03d" % num,
            "num": num,
            "slab": slab,
            "topo_p": topo_p,
            "topo_alt": topo_alt,
        })
    return perfiles


def distancia_al_perfil(lon, lat, perfil):
    """
    Distancia perpendicular (km) del punto (lon,lat) al perfil y su posición
    a lo largo del perfil (km).
    """
    slab = perfil["slab"]
    lon_c = slab["lon"]
    lat_c = slab["lat"]
    p_c = slab["p"]

    if len(lon_c) < 2:
        return None, None

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
    t = np.clip(t, 0.0, 1.0)

    fx = x_c[:-1] + t * dx
    fy = y_c[:-1] + t * dy

    dist2 = (x_p - fx) ** 2 + (y_p - fy) ** 2
    i = int(np.argmin(dist2))
    dist_min = math.sqrt(dist2[i])

    along = p_c[i] + t[i] * (p_c[i + 1] - p_c[i])
    return dist_min, along


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


def asignar_perfil_evento(lon, lat, prof,
                          perfiles,
                          umbral=UMBRAL_DIST_KM,
                          k_peso=K_PESO_PROFUNDIDAD):
    """
    Asigna un evento (lon, lat, prof) al perfil más cercano según la métrica
    combinada. Devuelve un diccionario con:

        perfil      : id del perfil ('P001', ...) o None si no cumple el umbral
        along_km    : posición a lo largo del perfil (km)
        perp_km     : distancia perpendicular epicentro-perfil (km)
        residuo_km  : |prof - slab(along)| en km (None si slab sin cobertura)
        dist_asoc   : índice de asociación (km)
    """
    mejor = None  # (dist_asoc, perfil_id, along, perp, residuo)

    for per in perfiles:
        perp, along = distancia_al_perfil(lon, lat, per)
        if perp is None:
            continue

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

    if mejor is None:
        return {"perfil": None, "along_km": None, "perp_km": None,
                "residuo_km": None, "dist_asoc": None}

    dist_asoc, perfil_id, along, perp, residuo = mejor
    if dist_asoc > umbral:
        return {"perfil": None, "along_km": None, "perp_km": None,
                "residuo_km": None, "dist_asoc": None}

    return {
        "perfil": perfil_id,
        "along_km": round(float(along), 3),
        "perp_km": round(float(perp), 3),
        "residuo_km": round(residuo, 3) if residuo is not None else None,
        "dist_asoc": round(dist_asoc, 3),
    }


def asignar_eventos(eventos, umbral=UMBRAL_DIST_KM, k_peso=K_PESO_PROFUNDIDAD,
                    grillas_dir=GRILLAS_DIR):
    """
    Asigna una lista de eventos (dicts con 'lon', 'lat', 'prof') a sus perfiles.
    Adorna cada dict con los campos: perfil, along_km, perp_km, residuo_km,
    dist_asoc. Devuelve la lista modificada.
    """
    perfiles = detectar_perfiles(grillas_dir)
    if not perfiles:
        print("[asigna_perfiles] Aviso: no se detectaron perfiles en '{}'.".format(
            grillas_dir))

    for ev in eventos:
        try:
            lon = float(ev.get('lon'))
            lat = float(ev.get('lat'))
            prof = ev.get('prof')
            if prof is None:
                prof = None
            else:
                prof = float(prof)
        except (TypeError, ValueError):
            lon = None

        if lon is None:
            ev.update({"perfil": None, "along_km": None, "perp_km": None,
                       "residuo_km": None, "dist_asoc": None})
            continue

        resultado = asignar_perfil_evento(lon, lat, prof, perfiles,
                                          umbral=umbral, k_peso=k_peso)
        ev.update(resultado)

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