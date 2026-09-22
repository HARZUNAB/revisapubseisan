#!/usr/bin/env python3
"""
sismicidad.py
=============
Catálogo de sismicidad histórica: carga, consultas espaciales y clasificación
de los EVENTOS PLOTEADOS como "posible mal localizado" usando criterios
configurables (distancia al slab y sismicidad histórica local).

El catálogo (base_2023_2026.dat) se presume ya validado y se usa SOLO como
referencia (fondo en plotear.py y estadísticas locales en la clasificación).
NUNCA se evalúa un evento del catálogo como sospechoso; es_sospechoso() solo
se aplica a los eventos del lote que se está procesando.

La decisión está centralizada en la función pública es_sospechoso(ev), que
recibe los parámetros del evento (lat/lon/prof más perp_km, residuo_km,
dist_asoc, perfil calculados por asigna_perfiles) y devuelve True/False.
"""

import os
import numpy as np


# =========================================================================
# RUTA DEL CATÁLOGO (resuelta respecto a este archivo, flexible a cualquier
# ubicación de instalación del proyecto).
# =========================================================================
RUTA_CATALOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "base_2020_2026.dat")

# Factores de conversión grados -> km (igual que asigna_perfiles.py).
GRADO_KM_LAT = 111.0

# =========================================================================
# CRITERIOS PARA DETERMINAR UN "POSIBLE MAL LOCALIZADO"
# =========================================================================
# Cada prueba genera un veredicto (True/False). Las pruebas se agrupan por
# origen de la evidencia y la regla de combinación decide el resultado final:
#
#   regla = "ambos_grupos"  -> sospechoso si AL MENOS una prueba del grupo
#                              "slab" Y AL MENOS una del grupo "historica"
#                              se cumplen (cada grupo con su "min_por_grupo").
#                              Corrige los falsos positivos de la regla OR:
#                              un evento cerca del slab o de la sismicidad
#                              histórica no se marca aunque falla una sola
#                              prueba.
#   regla = "cualquier_grupo" -> comportamiento OR: sospechoso si ALGUNA
#                              prueba activa se cumple (para experimentar).
#
# Pruebas disponibles (todas configurables, "activo" para habilitar/deshabilitar):
#   perp_max_km           : distancia perpendicular epicentro->perfil > valor
#   residuo_max_km        : |prof_ev - slab(along)| > valor
#   knn                   : promedio de distancia 3D (lat/lon/prof) a los k
#                           vecinos históricos más cercanos > umbral_km
#   ventana_aislamiento   : pocos históricos en ventana (radio_km horizontal +
#                           banda_prof_km) < min_vecinos
#   desvio_mediana_prof   : |prof_ev - mediana prof_hist en la ventana| >
#                           umbral_km (con conteo >= min_vecinos)
#
# "sin_catalogo": qué hacer cuando no existe base_2023_2026.dat y el grupo
# "historica" no puede evaluarse:
#   "ninguno"   -> no se marca (grupo no corroborado) [recomendado]
#   "solo_slab" -> basta con que falle el grupo "slab"
#
# Prueba interna (siempre activa): evento sin perfil (dist_asoc > umbral de
# asociación) -> sospechoso.
CRITERIOS_SOSPECHOSO = {
    "regla": "ambos_grupos",
    "grupos": {
        "slab": ["perp_max_km", "residuo_max_km"],
        "historica": ["knn", "ventana_aislamiento", "desvio_mediana_prof"],
    },
    "min_por_grupo": {"slab": 1, "historica": 1},
    "sin_catalogo": "ninguno",
    "pruebas": {
        "perp_max_km": {"activo": True, "valor": 60.0},
        "residuo_max_km": {"activo": True, "valor": 60.0},
        "knn": {"activo": True, "k": 5, "umbral_km": 55.0},
        "ventana_aislamiento": {"activo": True, "radio_km": 40.0,
                                "banda_prof_km": 40.0, "min_vecinos": 2},
        "desvio_mediana_prof": {"activo": True, "radio_km": 40.0,
                                "banda_prof_km": 40.0, "min_vecinos": 3,
                                "umbral_km": 35.0},
    },
}

_cache_catalogo = None


def cargar_catalogo(ruta=RUTA_CATALOGO):
    """
    Lee el catálogo histórico (base_2023_2026.dat, separado por tabs) y lo
    guarda en caché. Devuelve un dict con arrays lat, lon, prof y la
    proyección local x, y (km) usando la latitud de referencia, o None si el
    archivo no existe o no tiene eventos válidos. El catálogo NUNCA se
    clasifica; solo se consulta.
    """
    global _cache_catalogo
    if _cache_catalogo is not None:
        return _cache_catalogo
    if not os.path.isfile(ruta):
        _cache_catalogo = None
        return None

    lats, lons, profs = [], [], []
    with open(ruta, encoding='utf-8') as f:
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
        _cache_catalogo = None
        return None

    cat = {"lat": np.array(lats), "lon": np.array(lons),
           "prof": np.array(profs)}
    cat["lat_ref"] = float(np.mean(cat["lat"]))
    cat["lon_ref"] = float(np.mean(cat["lon"]))
    k_lon = GRADO_KM_LAT * max(0.1, float(np.cos(np.radians(cat["lat_ref"]))))
    cat["x"] = (cat["lon"] - cat["lon_ref"]) * k_lon
    cat["y"] = (cat["lat"] - cat["lat_ref"]) * GRADO_KM_LAT
    _cache_catalogo = cat
    return cat


def _coord_evento_en_km(ev, catalogo):
    """Proyecta el evento al mismo plano local del catálogo -> (x, y, prof)."""
    lat = float(ev['latitud'])
    lon = float(ev['longitud'])
    k_lon = GRADO_KM_LAT * max(0.1, float(np.cos(np.radians(catalogo["lat_ref"]))))
    x = (lon - catalogo["lon_ref"]) * k_lon
    y = (lat - catalogo["lat_ref"]) * GRADO_KM_LAT
    return x, y


def _dist_kkn(ev, catalogo, k):
    """
    Promedio (km) de la distancia 3D (x, y, prof) del evento a los k vecinos
    históricos más cercanos. Devuelve None si no hay datos suficientes.
    """
    try:
        x, y = _coord_evento_en_km(ev, catalogo)
        prof = float(ev['prof'])
    except (TypeError, ValueError, KeyError):
        return None
    dx = catalogo["x"] - x
    dy = catalogo["y"] - y
    dz = catalogo["prof"] - prof
    d2 = dx * dx + dy * dy + dz * dz
    if len(d2) == 0:
        return None
    k_ef = min(k, len(d2))
    idx = np.argpartition(d2, k_ef - 1)[:k_ef]
    return float(np.sqrt(d2[idx].mean()))


def _vecinos_ventana(ev, catalogo, radio_km, banda_prof_km):
    """
    Índices booleanos de los históricos dentro de una ventana cilíndrica
    (radio_km horizontal + banda_prof_km de profundidad) alrededor del
    evento. Devuelve (mask, None) o (None, motivo).
    """
    try:
        x, y = _coord_evento_en_km(ev, catalogo)
        prof = float(ev['prof'])
    except (TypeError, ValueError, KeyError):
        return None, "coordenadas/profundidad no válidas"
    dx = catalogo["x"] - x
    dy = catalogo["y"] - y
    horiz2 = dx * dx + dy * dy
    mask = (horiz2 <= radio_km ** 2) & (np.abs(catalogo["prof"] - prof) <= banda_prof_km)
    return mask, None


def _test_perp(ev, cfg, catalogo):
    """válido solo si el evento tiene perfil y perp_km numérico."""
    perp = ev.get('perp_km')
    if perp is None or ev.get('perfil') is None:
        return False
    try:
        return float(perp) > float(cfg["valor"])
    except (TypeError, ValueError):
        return False


def _test_residuo(ev, cfg, catalogo):
    """válido solo si el evento tiene residuo_km numérico."""
    residuo = ev.get('residuo_km')
    if residuo is None:
        return False
    try:
        return float(residuo) > float(cfg["valor"])
    except (TypeError, ValueError):
        return False


def _test_knn(ev, cfg, catalogo):
    if catalogo is None:
        return False
    d = _dist_kkn(ev, catalogo, int(cfg["k"]))
    if d is None:
        return False
    return d > float(cfg["umbral_km"])


def _test_aislamiento(ev, cfg, catalogo):
    if catalogo is None:
        return False
    mask, motivo = _vecinos_ventana(ev, catalogo, float(cfg["radio_km"]),
                                    float(cfg["banda_prof_km"]))
    if mask is None:
        return False
    return int(mask.sum()) < int(cfg["min_vecinos"])


def _test_mediana_prof(ev, cfg, catalogo):
    if catalogo is None:
        return False
    mask, motivo = _vecinos_ventana(ev, catalogo, float(cfg["radio_km"]),
                                    float(cfg["banda_prof_km"]))
    if mask is None:
        return False
    if int(mask.sum()) < int(cfg["min_vecinos"]):
        return False
    try:
        prof_ev = float(ev['prof'])
        mediana = float(np.median(catalogo["prof"][mask]))
    except (TypeError, ValueError, KeyError):
        return False
    return abs(prof_ev - mediana) > float(cfg["umbral_km"])


# Mapa nombre de prueba -> función.
_TEST_FUNCIONES = {
    "perp_max_km": _test_perp,
    "residuo_max_km": _test_residuo,
    "knn": _test_knn,
    "ventana_aislamiento": _test_aislamiento,
    "desvio_mediana_prof": _test_mediana_prof,
}


def evaluar(ev, catalogo=None, criterios=None):
    """
    Evalúa un EVENTO PLOTEADO contra todas las pruebas activas y aplica la
    regla de combinación de CRITERIOS_SOSPECHOSO. DEVUELVE un dict con:

        sospechoso   : bool
        sin_perfil   : bool  (prueba interna: sin perfil -> siempre sospechoso)
        regla        : regla utilizada
        pruebas      : {nombre_prueba: veredicto} de las pruebas activas
        grupos       : {grupo: {"disparadas", "min", "cumplido"}}
        metricas     : {perp_km, residuo_km, d_knn_km, vecinos_ventana,
                        desvio_mediana_km} (contexto; None si no aplica)

    El catálogo histórico solo se usa como referencia; si falta el archivo,
    el grupo "historica" no se puede evaluar y se aplica "sin_catalogo"
    ("ninguno" no marca; "solo_slab" marca si falla el grupo slab).
    """
    if catalogo is None:
        catalogo = cargar_catalogo()
    if criterios is None:
        criterios = CRITERIOS_SOSPECHOSO

    metricas = {
        "perp_km": ev.get('perp_km'),
        "residuo_km": ev.get('residuo_km'),
        "d_knn_km": None,
        "vecinos_ventana": None,
        "desvio_mediana_km": None,
    }

    # Prueba interna: sin perfil -> fuera del umbral de asociación.
    if ev.get('perfil') is None:
        return {"sospechoso": True, "sin_perfil": True,
                "regla": criterios.get("regla", "ambos_grupos"),
                "pruebas": {}, "grupos": {}, "metricas": metricas}

    veredictos = {}
    pruebas = criterios.get("pruebas", {})
    for nombre, funcion in _TEST_FUNCIONES.items():
        cfg = pruebas.get(nombre)
        if not cfg or not cfg.get("activo"):
            continue
        veredictos[nombre] = funcion(ev, cfg, catalogo)

    # Métricas de contexto para el diagnóstico (reutiliza las sub-funciones
    # de las pruebas con la configuración activa).
    if catalogo is not None and 'latitud' in ev:
        cfg_knn = pruebas.get("knn")
        if cfg_knn and cfg_knn.get("activo"):
            metricas["d_knn_km"] = _dist_kkn(ev, catalogo,
                                             int(cfg_knn.get("k", 5)))
        cfg_vent = pruebas.get("ventana_aislamiento")
        if cfg_vent and cfg_vent.get("activo"):
            m, _ = _vecinos_ventana(ev, catalogo,
                                    float(cfg_vent.get("radio_km", 40.0)),
                                    float(cfg_vent.get("banda_prof_km", 40.0)))
            if m is not None:
                metricas["vecinos_ventana"] = int(m.sum())
        cfg_desv = pruebas.get("desvio_mediana_prof")
        if cfg_desv and cfg_desv.get("activo"):
            m, _ = _vecinos_ventana(ev, catalogo,
                                    float(cfg_desv.get("radio_km", 40.0)),
                                    float(cfg_desv.get("banda_prof_km", 40.0)))
            if m is not None and int(m.sum()) >= int(cfg_desv.get("min_vecinos", 3)):
                try:
                    prof_ev = float(ev['prof'])
                    mediana = float(np.median(catalogo["prof"][m]))
                    metricas["desvio_mediana_km"] = abs(prof_ev - mediana)
                except (TypeError, ValueError, KeyError):
                    pass

    if not veredictos:
        return {"sospechoso": False, "sin_perfil": False,
                "regla": criterios.get("regla", "ambos_grupos"),
                "pruebas": veredictos, "grupos": {}, "metricas": metricas}

    regla = criterios.get("regla", "ambos_grupos")
    grupos = criterios.get("grupos", {})
    minima = criterios.get("min_por_grupo", {})
    res_grupos = {}

    def _resumen_grupo(nombre_grupo):
        activas = [n for n in grupos.get(nombre_grupo, []) if n in veredictos]
        if not activas:
            # Grupo sin pruebas evaluables (p. ej. "historica" sin catálogo).
            if nombre_grupo == "historica" and \
                    criterios.get("sin_catalogo") == "solo_slab":
                return {"disparadas": 0,
                        "min": int(minima.get(nombre_grupo, 1)),
                        "cumplido": True}
            return {"disparadas": 0,
                    "min": int(minima.get(nombre_grupo, 1)),
                    "cumplido": False}
        disparadas = sum(1 for n in activas if veredictos[n])
        return {"disparadas": disparadas,
                "min": int(minima.get(nombre_grupo, 1)),
                "cumplido": disparadas >= int(minima.get(nombre_grupo, 1))}

    if regla != "ambos_grupos":
        # "cualquier_grupo" (u otro): comportamiento OR para experimentar.
        for nombre_grupo in grupos:
            res_grupos[nombre_grupo] = _resumen_grupo(nombre_grupo)
        return {"sospechoso": any(veredictos.values()), "sin_perfil": False,
                "regla": regla, "pruebas": veredictos, "grupos": res_grupos,
                "metricas": metricas}

    # "ambos_grupos": se exige al menos "min_por_grupo" de cada grupo.
    cumple = True
    for nombre_grupo in grupos:
        info = _resumen_grupo(nombre_grupo)
        res_grupos[nombre_grupo] = info
        if not info["cumplido"]:
            cumple = False
    return {"sospechoso": cumple, "sin_perfil": False, "regla": regla,
            "pruebas": veredictos, "grupos": res_grupos, "metricas": metricas}


def es_sospechoso(ev, catalogo=None, criterios=None):
    """
    Determina si un EVENTO PLOTEADO podría estar mal localizado.
    Aplica todas las pruebas activas de CRITERIOS_SOSPECHOSO agrupándolas:

      "ambos_grupos"    -> debe fallar al menos "min_por_grupo" pruebas del
                           grupo "slab" Y al menos "min_por_grupo" del grupo
                           "historica" (un evento cerca del slab o de la
                           sismicidad histórica no se marca).
      "cualquier_grupo" -> comportamiento OR (cualquier prueba basta).

    El catálogo histórico solo se usa como referencia; si falta el archivo,
    el grupo "historica" no se puede evaluar y se aplica "sin_catalogo"
    ("ninguno" no marca; "solo_slab" marca si falla el grupo slab). Un evento
    sin perfil asignado siempre es sospechoso.
    """
    return evaluar(ev, catalogo, criterios)["sospechoso"]


def explicar_sospechoso(ev, catalogo=None, criterios=None):
    """
    Resumen legible para diagnóstico de por qué un evento se marcó (o no)
    como sospechoso. Devuelve una cadena con las métricas de contexto y los
    criterios disparados por grupo, p. ej.:

        id 4 -> SOSPECHOSO | perp=10.9 residuo=47.8 d_knn=38.2 vecinos=1 |
        grupos: slab:residuo_max_km; historica:knn
    """
    r = evaluar(ev, catalogo, criterios)
    id_ev = ev.get('id', '?')
    estado = "SOSPECHOSO" if r["sospechoso"] else "no marcado"

    m = r["metricas"]
    def _fmt(v):
        return "-" if v is None else ("%.1f" % float(v))

    if r["sin_perfil"]:
        return ("id %s -> %s | sin perfil asignado (dist_asoc > umbral)"
                % (id_ev, estado))

    grupo_de = {}
    for g, nombres in (criterios or CRITERIOS_SOSPECHOSO).get("grupos", {}).items():
        for n in nombres:
            grupo_de[n] = g
    piezas = []
    for g, info in r["grupos"].items():
        dis = [n for n, v in r["pruebas"].items() if v and grupo_de.get(n) == g]
        piezas.append("%s:%s" % (g, ",".join(dis) if dis else "-"))

    return ("id %s -> %s | perp=%s residuo=%s d_knn=%s vecinos=%s | grupos: %s"
            % (id_ev, estado, _fmt(m["perp_km"]), _fmt(m["residuo_km"]),
               _fmt(m["d_knn_km"]), m["vecinos_ventana"], "; ".join(piezas)))


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding='utf-8') as f:
            for ev in json.load(f):
                print("%s -> sospechoso: %s"
                      % (ev.get('id'), es_sospechoso(ev)))
    else:
        print("Uso: python3 sismicidad.py <eventos_<fuente>.json>")