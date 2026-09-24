#!/usr/bin/env python3
"""
generajson.py
=============
Lee un archivo .csv de eventos (seisan o eventquery), asigna cada evento al
perfil de subducción más cercano usando asigna_perfiles.py y genera UN solo
archivo JSON por fuente con todos los eventos, cada uno adornado con su
perfil y las coordenadas calculadas para el ploteo.

Uso:
    python3 generajson.py <archivo_csv> <fuente> [--umbral=KM] [--k=K] [--umbral-perp=KM]

    archivo_csv : archivo .csv con los eventos (p. ej. salida_collect.csv o
                  new_2_*.csv)
    fuente      : "seisan" | "eventquery"
    --umbral=KM : umbral de dist_asoc (km) para asignar perfil (default
                  UMBRAL_DIST_KM de asigna_perfiles.py)
    --k=K       : peso de la profundidad en la métrica (default
                  K_PESO_PROFUNDIDAD de asigna_perfiles.py)
    --umbral-perp=KM : umbral de respaldo por distancia perpendicular (km)
                  para asociar eventos cercanos al perfil aunque su
                  profundidad difiera del slab (default UMBRAL_PERP_KM de
                  asigna_perfiles.py)

Salida:
    eventos_<fuente>.json    (lista de eventos con sus campos originales más
    "perfil", "along_km", "perp_km", "residuo_km" y "dist_asoc", y las
    claves de trazabilidad "archivo_origen" y "n_fila_origen")
"""

import csv
import json
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import asigna_perfiles as ap
import sismicidad


def parsear_extra_args(args):
    """Extrae --umbral=KM, --k=K y --umbral-perp=KM de los argumentos."""
    umbral = None
    k_peso = None
    umbral_perp = None
    for arg in args:
        if arg.startswith("--umbral="):
            umbral = float(arg.split("=", 1)[1])
        elif arg.startswith("--k="):
            k_peso = float(arg.split("=", 1)[1])
        elif arg.startswith("--umbral-perp="):
            umbral_perp = float(arg.split("=", 1)[1])
    return umbral, k_peso, umbral_perp


def procesar_csv(archivo_csv, fuente, umbral=None, k_peso=None,
                 umbral_perp=None):
    """
    Procesa el .csv, asigna perfiles y escribe eventos_<fuente>.json.
    Devuelve (total_eventos, con_perfil, sin_perfil).
    """
    if umbral is None:
        umbral = ap.UMBRAL_DIST_KM
    if k_peso is None:
        k_peso = ap.K_PESO_PROFUNDIDAD
    if umbral_perp is None:
        umbral_perp = ap.UMBRAL_PERP_KM

    eventos = []
    archivo_origen = os.path.basename(archivo_csv)

    with open(archivo_csv, 'r', newline='') as csvfile:
        lector_csv = csv.reader(csvfile)
        next(lector_csv, None)  # Omitir encabezado si existe

        for fila in lector_csv:
            if len(fila) < 5:
                continue
            try:
                latitud = float(fila[2])
                longitud = float(fila[3])
                prof = fila[4]
                prof_num = float(prof) if prof else None
            except (ValueError, IndexError):
                continue

            if fuente == "seisan":
                evento = {
                    'id': int(fila[0]) + 1,
                    'fecha hora': fila[1],
                    'latitud': latitud,
                    'longitud': longitud,
                    'prof': prof,
                    'magnitud': fila[5],
                    'tipo': fila[6],
                    'analista': fila[7] if len(fila) > 7 else "",
                }
            else:
                evento = {
                    'id': int(fila[0]) + 1,
                    'fecha hora': fila[1],
                    'latitud': latitud,
                    'longitud': longitud,
                    'prof': prof,
                    'magnitud': fila[5],
                    'tipo': fila[6],
                    'percibido': fila[8] if len(fila) > 8 else "",
                }

            evento['archivo_origen'] = archivo_origen
            evento['n_fila_origen'] = int(fila[0])
            evento['lon'] = longitud
            evento['lat'] = latitud
            eventos.append(evento)

    # Asigna perfil a cada evento (incluye la profundidad en la métrica)
    eventos = ap.asignar_eventos(eventos, umbral=umbral, k_peso=k_peso,
                                 umbral_perp=umbral_perp)

    # Decide si cada evento ploteado podría estar mal localizado (sospechoso)
    # usando el slab y la sismicidad histórica local. La sismicidad histórica
    # jamás se evalúa; solo se usa como referencia.
    for ev in eventos:
        ev['sospechoso'] = sismicidad.es_sospechoso(ev)

    # Elimina claves auxiliares usadas por el asignador
    for ev in eventos:
        ev.pop('lon', None)
        ev.pop('lat', None)

    salida_json = 'eventos_%s.json' % fuente
    with open(salida_json, 'w') as jsonfile:
        json.dump(eventos, jsonfile, indent=4)

    # Lista de eventos que podrían estar mal localizados (sospechosos)
    sospechosos_csv = 'sospechosos_%s.csv' % fuente
    with open(sospechosos_csv, 'w', newline='') as csvfile:
        escritor = csv.writer(csvfile)
        escritor.writerow(['id', 'fecha hora', 'latitud', 'longitud', 'prof',
                           'perfil', 'perp_km', 'residuo_km', 'dist_asoc',
                           'd_knn_km', 'vecinos_ventana', 'criterios',
                           'archivo_origen', 'n_fila_origen'])
        for ev in eventos:
            if ev.get('sospechoso'):
                eva = sismicidad.evaluar(ev)
                m = eva.get('metricas', {})
                # Criterios disparados (para diagnóstico)
                grupo_de = {}
                for g, nombres in sismicidad.CRITERIOS_SOSPECHOSO.get(
                        "grupos", {}).items():
                    for n in nombres:
                        grupo_de[n] = g
                criterios = "; ".join(
                    "%s:%s" % (g, ",".join(n for n, v in eva['pruebas'].items()
                                           if v and grupo_de.get(n) == g))
                    for g in eva.get('grupos', {})
                    if eva['grupos'][g]['cumplido'])
                escritor.writerow([ev.get('id'), ev.get('fecha hora'),
                                   ev.get('latitud'), ev.get('longitud'),
                                   ev.get('prof'), ev.get('perfil'),
                                   ev.get('perp_km'), ev.get('residuo_km'),
                                   ev.get('dist_asoc'),
                                   m.get('d_knn_km'), m.get('vecinos_ventana'),
                                   criterios,
                                   ev.get('archivo_origen'),
                                   ev.get('n_fila_origen')])
                # Diagnóstico en consola: por qué se marcó cada sospechoso
                print("  [sospechoso] %s"
                      % sismicidad.explicar_sospechoso(ev))

    total_eventos = len(eventos)
    with_perfil = sum(1 for ev in eventos if ev.get('perfil') is not None)
    sin_perfil = total_eventos - with_perfil

    # Resumen por perfil
    conteo = {}
    for ev in eventos:
        per = ev.get('perfil')
        conteo[per] = conteo.get(per, 0) + 1

    print('Total de eventos:', total_eventos)
    print('Eventos con perfil:', with_perfil)
    n_sospechosos = sum(1 for ev in eventos if ev.get('sospechoso'))
    if n_sospechosos:
        print('Eventos posiblemente mal localizados: %d (ver %s)'
              % (n_sospechosos, sospechosos_csv))
    if sin_perfil:
        print('Eventos sin perfil (se plotearán solo en planta):', sin_perfil)
    print('Distribución por perfil:')
    conteo_labels = {}
    for per in sorted(conteo, key=lambda x: (x is None, '' if x is None else x)):
        label = per if per is not None else '(sin perfil)'
        conteo_labels[label] = conteo[per]
        print('  %-12s %d' % (label, conteo[per]))

    # Guarda el conteo para que plotear.py lo muestre a medida que plotea
    conteo_json = 'conteo_perfiles_%s.json' % fuente
    with open(conteo_json, 'w') as f:
        json.dump({'total': total_eventos,
                   'con_perfil': with_perfil,
                   'sin_perfil': sin_perfil,
                   'conteo': conteo_labels}, f, indent=4)

    return total_eventos, with_perfil, sin_perfil


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    archivo_csv = sys.argv[1]
    fuente = sys.argv[2]
    umbral_usr, k_usr, umbral_perp_usr = parsear_extra_args(sys.argv[3:])

    if not os.path.isfile(archivo_csv):
        print("Error: no se encontró el archivo '%s'." % archivo_csv)
        sys.exit(1)

    procesar_csv(archivo_csv, fuente, umbral=umbral_usr, k_peso=k_usr,
                 umbral_perp=umbral_perp_usr)
    print('Archivo JSON generado:', 'eventos_%s.json' % fuente)