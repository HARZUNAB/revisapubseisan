#!/usr/bin/env python3
"""
generajson.py
=============
Lee un archivo .csv de eventos (seisan, seiscomp o eventquery), asigna cada
evento al perfil de subducción más cercano usando asigna_perfiles.py y genera
UN solo archivo JSON por fuente con todos los eventos, cada uno adornado con su
perfil y las coordenadas calculadas para el ploteo.

Uso:
    python3 generajson.py <archivo_csv> <fuente> [--umbral=KM] [--k=K] [--umbral-perp=KM] [--margen-borde=KM] [--salida=NOMBRE]

    archivo_csv : archivo .csv con los eventos (p. ej. salida_collect.csv o
                  new_2_*.csv)
    fuente      : "seisan" | "seiscomp" | "eventquery"
    --salida=NOMBRE : nombre base de los archivos de salida (default: la misma
                  'fuente'). Sirve para que los «no publicados» reusen el parseo
                  de su fuente sin pisar eventos_<fuente>.json.

Las tres fuentes se leen por POSICIÓN, y el archivo tiene que llevar el índice
de la fila como columna 0 (es lo que escribe pandas con to_csv() por defecto),
porque 'id' y 'n_fila_origen' salen de ahí. El resto de las columnas es:

    seisan   : Fecha_Hora, Latitud, Longitud, Prof., Mag., Tipo_mag., Analista
    seiscomp : igual que seisan, con el OPERADOR de la solución preferred de
               SeisComp en la columna del analista (ver seiscomp_a_parametros.py)
    eventquery: Fecha_Hora, Latitud, Longitud, Prof., Mag., Tipo_mag.,
               Referencia, Percep.   <- 'percibido' sale de la última

Ojo: en eventquery la columna 7 es la Referencia (la región), NO un analista.
Las filas sin latitud o longitud parseable se descartan en silencio, así que el
conversor de cada fuente tiene que avisar cuántas descartó.
    --umbral=KM : umbral de dist_asoc (km) para asignar perfil (default
                  UMBRAL_DIST_KM de asigna_perfiles.py)
    --k=K       : peso de la profundidad en la métrica (default
                  K_PESO_PROFUNDIDAD de asigna_perfiles.py)
    --umbral-perp=KM : tope lateral OPCIONAL del respaldo por cobertura (default
                  UMBRAL_PERP_KM de asigna_perfiles.py; None = sin tope)
    --margen-borde=KM : margen (km) admitido más allá de la cobertura natural
                  del set (medio hueco entre perfiles y extremos de sección).
                  Default MARGEN_BORDE_KM de asigna_perfiles.py (0.0).

Salida:
    eventos_<vista>.json    (lista de eventos con sus campos originales más
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
import rutas
import prog


def parsear_extra_args(args):
    """Extrae --umbral=KM, --k=K, --umbral-perp=KM, --margen-borde=KM
    y --salida=NOMBRE."""
    umbral = None
    k_peso = None
    umbral_perp = None
    margen_borde = None
    salida = None
    for arg in args:
        if arg.startswith("--umbral="):
            umbral = float(arg.split("=", 1)[1])
        elif arg.startswith("--k="):
            k_peso = float(arg.split("=", 1)[1])
        elif arg.startswith("--umbral-perp="):
            umbral_perp = float(arg.split("=", 1)[1])
        elif arg.startswith("--margen-borde="):
            margen_borde = float(arg.split("=", 1)[1])
        elif arg.startswith("--salida="):
            salida = arg.split("=", 1)[1]
    return umbral, k_peso, umbral_perp, margen_borde, salida


def _distancia_aprox_km(lat1, lon1, lat2, lon2):
    """Distancia aproximada en km entre dos puntos, para mostrar al lado del
    nombre. Es la fórmula equirectangular, que a esta escala (decenas de km)
    alcanza y no necesita pyproj ni cartopy."""
    try:
        lat1, lon1, lat2, lon2 = (float(x) for x in (lat1, lon1, lat2, lon2))
    except (TypeError, ValueError):
        return None
    import math
    latm = math.radians((lat1 + lat2) / 2.0)
    dx = (lon1 - lon2) * 111.32 * math.cos(latm)
    dy = (lat1 - lat2) * 110.57
    return (dx * dx + dy * dy) ** 0.5


def _cargar_atribucion(nombre_fuente):
    """
    Lee datos/atribucion_<nombre_fuente>.csv y devuelve un índice
    {fecha_hora: [entradas de cruce]}.

    El emparejamiento se hace por la cadena exacta de fecha_hora porque es el
    único campo que se conserva idéntico en los dos lados. NO se usa el índice
    de fila: todos_eventquery.csv concatena varios new_2_*.csv sin renumerar
    la primera columna, así que n_fila_origen se repite entre ventanas y
    emparejaría eventos de ventanas distintas. Por eso, cuando hay más de una
    entrada con la misma hora se descarta la que no coincide en coordenadas.
    """
    ruta = rutas.p_datos('atribucion_%s.csv' % nombre_fuente)
    if not os.path.isfile(ruta):
        return None
    indice = {}
    try:
        with open(ruta, 'r', newline='') as csvfile:
            for fila in csv.DictReader(csvfile):
                indice.setdefault(fila.get('fecha_eventquery', ''), []).append(fila)
    except OSError:
        return None
    if not indice:
        return None
    return indice


def _analistas_para_evento(indice, fecha_hora, latitud, longitud):
    """
    Devuelve la lista de fuentes que aportaron un analista para este evento,
    o None si ninguna. Cada entrada trae los analistas distintos de esa fuente
    y el mejor cruce (menor Δt).
    """
    if not indice:
        return None
    candidatas = indice.get(fecha_hora)
    if not candidatas:
        return None
    # Descarta las entradas de otro evento que happencaer en el mismo segundo.
    if len(candidatas) > 1:
        proche = [c for c in candidatas
                  if _distancia_aprox_km(latitud, longitud,
                                         c.get('lat_eventquery'),
                                         c.get('lon_eventquery')) is not None
                  and _distancia_aprox_km(latitud, longitud,
                                          c.get('lat_eventquery'),
                                          c.get('lon_eventquery')) < 0.5]
        if proche:
            candidatas = proche
    if not candidatas:
        return None

    por_fuente = {}
    for c in candidatas:
        entrada = por_fuente.setdefault(c.get('fuente', 'local'), {
            'fuente': c.get('fuente', 'local'),
            'n_soluciones': 0,
            'dt_seg': None,
            'km': None,
        })
        entrada['n_soluciones'] += 1
        try:
            dt = float(c.get('dt_seg'))
        except (TypeError, ValueError):
            dt = None
        if dt is not None and (entrada['dt_seg'] is None or dt < entrada['dt_seg']):
            km = _distancia_aprox_km(latitud, longitud,
                                     c.get('lat_eventquery'), c.get('lon_eventquery'))
            entrada['dt_seg'] = dt
            entrada['km'] = None if km is None else round(km, 1)
    for entrada in por_fuente.values():
        entrada['analistas'] = sorted({
            (c.get('analista') or '(sin nombre)')
            for c in candidatas if c.get('fuente', 'local') == entrada['fuente']})
    # Primero SeisComp, después Seisan: el orden de inserción ya viene así
    # porque se cargan en ese orden, pero se hace explícito por si cambia.
    return sorted(por_fuente.values(), key=lambda e: 0 if e['fuente'] == 'seiscomp' else 1)


def _texto_posibles_analistas(ev):
    """
    'SeisComp: cris; Seisan: jere' para los eventos de eventquery, que no
    traen responsable. Para seisan y seiscomp devuelve el nombre que ya viene
    en su propio CSV, que en ese caso NO es una inferencia sino un dato.
    """
    entradas = ev.get('analistas')
    if entradas:
        return '; '.join('%s: %s' % (e['fuente'], ', '.join(e['analistas']))
                         for e in entradas)
    return ev.get('analista') or ''


def _texto_calidad_cruce(ev):
    """
    'SeisComp dt 0.2s 3.0km'. El Δt y la distancia van siempre al lado del
    nombre porque el nombre es una inferencia por tolerancia: con 0.2 s y 3 km
    se cree, con 30 s y 30 km hay que verificarlo.
    """
    entradas = ev.get('analistas')
    if not entradas:
        return ''
    partes = []
    for e in entradas:
        if e.get('dt_seg') is None:
            continue
        texto = '%s dt %.1fs' % (e['fuente'], e['dt_seg'])
        if e.get('km') is not None:
            texto += ' %.1fkm' % e['km']
        if e.get('n_soluciones', 1) > 1:
            texto += ' (%d soluciones)' % e['n_soluciones']
        partes.append(texto)
    return '; '.join(partes)


def procesar_csv(archivo_csv, fuente, umbral=None, k_peso=None,
                 umbral_perp=None, margen_borde=None, salida=None):
    """
    Procesa el .csv, asigna perfiles y escribe eventos_<vista>.json.

    'fuente' decide cómo se lee el CSV (seisan / seiscomp / eventquery) y la
    atribución; 'salida' (la "vista") es solo el nombre base en disco. Permite
    que los no publicados usen el parseo de su fuente sin pisar el JSON de la
    fuente principal.
    Devuelve (total_eventos, con_perfil, sin_perfil).
    """
    vista = salida or fuente
    if umbral is None:
        umbral = ap.UMBRAL_DIST_KM
    if k_peso is None:
        k_peso = ap.K_PESO_PROFUNDIDAD
    if umbral_perp is None:
        umbral_perp = ap.UMBRAL_PERP_KM
    if margen_borde is None:
        margen_borde = ap.MARGEN_BORDE_KM

    eventos = []
    archivo_origen = os.path.basename(archivo_csv)

    # Solo eventquery necesita atribución: las otras fuentes ya traen el
    # analista en su propio CSV.
    #
    # Se avisa cuando falta ALGUNA fuente, no solo cuando faltan las dos. Con
    # solo Seisan el panel igual abre y muestra el catálogo entero, así que un
    # aviso único "no hay atribución" es justo el que no se va a ver en el caso
    # más probable: hay una fuente y se cree que es suficiente. Nombrar la que
    # falta es lo que permite notar que la mayoría de los eventos se quedan
    # sin posible analista.
    atribuciones = []
    if fuente == 'eventquery':
        faltantes = []
        for nombre in ('seiscomp', 'seisan'):
            indice = _cargar_atribucion(nombre)
            if indice:
                atribuciones.append(indice)
            else:
                faltantes.append(nombre)
        if faltantes:
            archivos = ', '.join('datos/atribucion_%s.csv' % n
                                 for n in faltantes)
            remedio = ('Use «Datos de SeisComp» para generar el catálogo de '
                       'soluciones preferred y después «Datos de eventquery».'
                       if 'seiscomp' in faltantes else
                       'Use «Ejecutar análisis» para generar '
                       'salida_collect.csv.')
            print('[generajson] Aviso: sin atribución contra %s porque no '
                  'está %s. Los eventos de eventquery se mostrarán sin '
                  'posible analista. %s'
                  % (', '.join(faltantes), archivos, remedio))

    # Progreso monotónico global: lectura 0-10%, asignación de perfiles 10-70%,
    # evaluación de sospechosos 70-100%.
    def _fraccion(ini, fin, sub):
        return ini + (fin - ini) * min(1.0, max(0.0, sub))

    try:
        total_filas = sum(1 for _ in open(archivo_csv, 'r', newline='')) - 1
    except OSError:
        total_filas = 0
    total_filas = max(1, total_filas)

    with open(archivo_csv, 'r', newline='') as csvfile:
        lector_csv = csv.reader(csvfile)
        next(lector_csv, None)  # Omitir encabezado si existe

        for i, fila in enumerate(lector_csv):
            prog.avance(_fraccion(0.0, 0.10, i / total_filas))
            if len(fila) < 5:
                continue
            try:
                latitud = float(fila[2])
                longitud = float(fila[3])
                prof = fila[4]
            except (ValueError, IndexError):
                continue

            # seisan y seiscomp comparten el formato de columnas (la 7 es el
            # analista: el operador de la solución, en el caso de SeisComp), así
            # que se leen igual. Lo que NO se hace es inventar un 'percibido':
            # SeisComp no tiene esa noción, y la rama de eventquery la usa para
            # pintar de otro color.
            if fuente in ("seisan", "seiscomp"):
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
            if atribuciones:
                # Se recorren TODOS los índices, no se corta en el primero:
                # el pedido es mostrar ambas fuentes, y un evento puede tener
                # solución SeisComp y también Seisan. Cada archivo trae una
                # sola fuente, así que concatenar no puede duplicar nombres.
                entradas = []
                for indice in atribuciones:
                    encontradas = _analistas_para_evento(indice, fila[1],
                                                         latitud, longitud)
                    if encontradas:
                        entradas.extend(encontradas)
                if entradas:
                    evento['analistas'] = entradas
                    nombres = []
                    for e in entradas:
                        for n in e['analistas']:
                            if n not in nombres:
                                nombres.append(n)
                    evento['analistas_nombres'] = nombres
                    evento['analista_ambiguo'] = len(nombres) > 1
            eventos.append(evento)

    # Asigna perfil a cada evento (incluye la profundidad en la métrica).
    # Se detectan los perfiles una sola vez para conocer también la cobertura
    # del set y reportarla.
    perfiles = ap.detectar_perfiles()
    eventos = ap.asignar_eventos(eventos, umbral=umbral, k_peso=k_peso,
                                 umbral_perp=umbral_perp,
                                 margen_borde=margen_borde,
                                 perfiles=perfiles,
                                 on_avance=lambda f:
                                     prog.avance(_fraccion(0.10, 0.70, f)))

    # Decide si cada evento ploteado podría estar mal localizado (sospechoso)
    # usando el slab y la sismicidad histórica local. La sismicidad histórica
    # jamás se evalúa; solo se usa como referencia.
    for i, ev in enumerate(eventos):
        prog.avance(_fraccion(0.70, 1.0, (i + 1) / len(eventos)))
        ev['sospechoso'] = sismicidad.es_sospechoso(ev)

    # Elimina claves auxiliares usadas por el asignador
    for ev in eventos:
        ev.pop('lon', None)
        ev.pop('lat', None)

    salida_json = rutas.p_datos('eventos_%s.json' % vista)
    with open(salida_json, 'w') as jsonfile:
        json.dump(eventos, jsonfile, indent=4)

    # Lista de eventos que podrían estar mal localizados (sospechosos).
    # Es un entregable: el JSON de eventos ya trae el campo 'sospechoso' y el
    # panel lo filtra y lo descarga solo, así que este CSV no lo lee nadie. Sin
    # RV_ENTREGABLES ni se escribe ni se arma, porque sismicidad.evaluar() hay que
    # volver a correrlo evento por evento solo para este archivo. El marcado ya
    # quedó hecho antes, más arriba, para el campo 'sospechoso' del JSON, que sí
    # es caché.
    if rutas.ENTREGABLES:
        sospechosos_csv = 'sospechosos_%s.csv' % vista
        with rutas.entregable(sospechosos_csv) as csvfile:
            escritor = csv.writer(csvfile)
            escritor.writerow(['id', 'fecha hora', 'latitud', 'longitud', 'prof',
                               'perfil', 'perp_km', 'residuo_km', 'dist_asoc',
                               'd_knn_km', 'vecinos_ventana', 'criterios',
                               'posibles_analistas', 'analista_ambiguo',
                               'calidad_cruce',
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
                                       _texto_posibles_analistas(ev),
                                       'si' if ev.get('analista_ambiguo') else 'no',
                                       _texto_calidad_cruce(ev),
                                       ev.get('archivo_origen'),
                                       ev.get('n_fila_origen')])
                    # Diagnóstico en consola: por qué se marcó cada sospechoso
                    #print("  [sospechoso] %s"
                    #      % sismicidad.explicar_sospechoso(ev))
    else:
        sospechosos_csv = '(no generado: use RV_ENTREGABLES=1)'
 
    total_eventos = len(eventos)
    with_perfil = sum(1 for ev in eventos if ev.get('perfil') is not None)
    sin_perfil = total_eventos - with_perfil

    # Resumen por perfil
    conteo = {}
    for ev in eventos:
        per = ev.get('perfil')
        conteo[per] = conteo.get(per, 0) + 1

    # Desglose de los sin perfil por motivo (cobertura del set detectado)
    motivos = {}
    for ev in eventos:
        if ev.get('perfil') is None:
            m = ev.get('motivo') or 'sin_perfil'
            motivos[m] = motivos.get(m, 0) + 1
    cobertura = ap.cobertura_set(perfiles)

    print('Total de eventos:', total_eventos)
    print('Eventos con perfil:', with_perfil)
    n_sospechosos = sum(1 for ev in eventos if ev.get('sospechoso'))
    if n_sospechosos:
        print('Eventos posiblemente mal localizados: %d (ver %s)'
              % (n_sospechosos, sospechosos_csv))
    if sin_perfil:
        print('Eventos sin perfil (se plotearán solo en planta):', sin_perfil)
        if cobertura:
            print('  cobertura del set: lat %.2f..%.2f | lon %.2f..%.2f '
                  '(%d perfiles)'
                  % (cobertura['lat_min'], cobertura['lat_max'],
                     cobertura['lon_min'], cobertura['lon_max'],
                     cobertura['n_perfiles']))
        etiquetas = {
            'fuera_cobertura_norte': 'fuera de cobertura (norte del set)',
            'fuera_cobertura_sur': 'fuera de cobertura (sur del set)',
            'fuera_cobertura_extremo': 'fuera del alcance de las secciones',
            'fuera_cobertura': 'fuera de cobertura',
            'fuera_umbral': 'fuera del tope lateral (--umbral-perp)',
            'sin_coordenadas': 'sin coordenadas',
            'sin_perfiles': 'no se detectaron perfiles',
        }
        for m in sorted(motivos):
            print('  %-40s %d' % (etiquetas.get(m, m), motivos[m]))
        if any(k.startswith('fuera_cobertura') for k in motivos):
            print('  [Aviso] El set de grillas no cubre todo el catálogo: use '
                  'un set con mayor cobertura (o ajuste --margen-borde).')
    #print('Distribución por perfil:')
    conteo_labels = {}
    for per in sorted(conteo, key=lambda x: (x is None, '' if x is None else x)):
        label = per if per is not None else '(sin perfil)'
        conteo_labels[label] = conteo[per]
        #print('  %-12s %d' % (label, conteo[per]))

    # Guarda el conteo para que plotear.py lo muestre a medida que plotea
    conteo_json = rutas.p_datos('conteo_perfiles_%s.json' % vista)
    with open(conteo_json, 'w') as f:
        json.dump({'total': total_eventos,
                   'con_perfil': with_perfil,
                   'sin_perfil': sin_perfil,
                   'conteo': conteo_labels,
                   'cobertura_set': cobertura,
                   'sin_perfil_motivos': motivos}, f, indent=4)

    prog.avance(1.0)

    return total_eventos, with_perfil, sin_perfil


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    archivo_csv = sys.argv[1]
    fuente = sys.argv[2]
    umbral_usr, k_usr, umbral_perp_usr, margen_usr, salida_usr = \
        parsear_extra_args(sys.argv[3:])
    vista = salida_usr or fuente

    if not os.path.isfile(archivo_csv):
        print("Error: no se encontró el archivo '%s'." % archivo_csv)
        sys.exit(1)

    procesar_csv(archivo_csv, fuente, umbral=umbral_usr, k_peso=k_usr,
                 umbral_perp=umbral_perp_usr, margen_borde=margen_usr,
                 salida=salida_usr)
    print('Archivo JSON generado:', 'eventos_%s.json' % vista)