import csv
import sys, os
from os import remove
import time
import shutil
import datetime
from datetime import timedelta
import pandas as pd

import rutas
import prog
import comparacion

# parametros de los dos niveles de filtro (amplio y estricto)
# Ojo con las tolerancias: 2.0 grados de latitud son unos 220 km, holgado
# para fusionar dos eventos cercanos distintos. Como un cruce erroneo le
# atribuye el evento al analista equivocado, para notificar hay que guiarse
# por el informe ESTRICTO; el amplio sirve para estimar cobertura.
#
# Medición real (septiembre 2026: 901 publicados contra 2167 soluciones
# preferred de SeisComp) que respalda dejarlas como están:
#   - La mediana de Δt entre vecinos más cercanos es 0.00 s, así que no hay
#     desfase de reloj entre las dos fuentes y la ventana no se puede
#     "centrar" para ganar alcance.
#   - Estricto y amplio encuentran los MISMOS 907 cruces reales. Ampliar de 3 a
#     6 s no gana ninguno y mete 1 cruce erróneo (5 s y 54 km de distancia,
#     magnitudes 4.2 vs 4.8). El estricto es estrictamente mejor.
#   - Ningún evento de SeisComp tiene más de un publicado dentro de 6 s, así
#     que la ambigüedad no se materializa.
#   - Abrir a 30 s recupera 1 cruce real más (29.5 km, Δt exacto de 30.0 s,
#     operadora mary) a cambio de 22 pares que son otros eventos. No conviene.
# Si alguna vez se cambian estas tolerancias, repetir esa medición antes.
MAX_SEG_AMPLIO=6
MAX_LAT_LON_AMPLIO=2.0
MAX_SEG_ESTRICTO=3
MAX_LAT_LON_ESTRICTO=1.0

# Dentro de esa ventana, un evento se considera actualizado si sus parámetros
# coinciden con la solución local a la precisión con la que se manejan:
# coordenadas a 3 decimales, profundidad y magnitud a 1 (ver comparacion.py).
# Antes se comparaban los textos tal cual, y el mismo valor escrito con
# distinta cantidad de decimales (-31.64 contra -31.639999...) se marcaba como
# no actualizado. La comparación numérica incluye ahora también la magnitud.

# cabecera para cada archivo .txt de salida (Para plotear con google earth)
cabecera="fecha hora latitud longitud prof mag tipomag analista percibido\n"

# formato de fecha_hora en los .csv (dos espacios entre fecha y hora)
_FORMATO='%Y-%m-%d  %H:%M:%S'

def _parsear_fecha_hora(texto):
    # normaliza el segundo 60 -> 59 (eventquery llega con segundos inválidos)
    # Se toca solo el último par y no una posición fija: entre la fecha y la
    # hora hay uno o dos espacios según la fuente, y con el "[0:18]+'59'" de
    # antes una fecha de un solo espacio quedaba corrupta ("...:659") y
    # strptime fallaba. seiscomp_a_parametros.py escribe con un espacio.
    if texto[-2:]=='60':
        texto=texto[:-2]+'59'
    return datetime.datetime.strptime(texto, _FORMATO)

def _magnitud(texto):
    # Magnitud como float, o None si no hay dato o no se puede leer.
    # Las soluciones preferred de SeisComp admiten eventos sin magnitud, y
    # float('') revienta: sin esto el script muere a mitad de la comparación
    # y se pierden los informes de los eventos que ya venía comparando.
    texto = (texto or "").strip()
    if not texto:
        return None
    try:
        return float(texto)
    except ValueError:
        return None

def _borrar(ruta):
    # Borra un CSV de salida que esta corrida dejó vacío, para que no quede el
    # de una corrida anterior y la pestaña muestre datos viejos.
    try:
        os.remove(ruta)
    except OSError:
        pass

def comparar(listacsv_1, listacsv_2, max_seg, max_lat, max_lon, sufijo,
             prefijo=""):
    # El prefijo distingue la fuente local para que una corrida no pise los
    # informes de la otra. Viene vacío para Seisan, así sus nombres quedan
    # exactamente como siempre (no_pub_desde_2_5_estricto.csv lo usa app.py).
    # archivos de salida
    # Los tres informes de texto se parecen pero no son lo mismo:
    #   no_pub_todos_*      y no_pub_desde_2_5_*  son entregables: nadie los
    #                                         relee, van a descargas/ y solo
    #                                         con RV_ENTREGABLES=1.
    #   no_act_*            NO es entregable: app.py lo abre para distinguir
    #                                         "el análisis nunca corrió" de
    #                                         "corrió y no encontró cruces". Se
    #                                         escribe siempre en informes/.
    archivo=rutas.entregable("no_pub_todos_"+prefijo+sufijo+".txt")
    archivo1=open(rutas.p_informes("no_act_"+prefijo+sufijo+".txt"), "w")
    archivo2=rutas.entregable("no_pub_desde_2_5_"+prefijo+sufijo+".txt")

    archivo.write(cabecera)
    archivo1.write(cabecera)
    archivo2.write(cabecera)

    pub=0
    total_eventos=0
    diferencias=0
    total_diferentes=0
    totsobre2_5=0
    nopub_sin_magnitud=0
    avance=0
    listanopub=[]

    # Cada coincidencia real (tiempo Y espacio) se guarda acá para poder decir
    # de quién es cada evento publicado. Se registran TODAS, no solo la última:
    # el bucle de abajo no corta en el primer cruce, así que cuando dos
    # soluciones locales caen dentro de la tolerancia del mismo evento
    # publicado hay más de una fila acá y eso es justamente el caso ambiguo
    # que hay que poder mostrar en vez de tapar. No altera los txt/.csv de
    # siempre: acá solo se agrega information que antes se perdía.
    cruces=[]

    # Un archivo local sin eventos (solo encabezado) haría 0/0 acá. Con la
    # fuente SeisComp eso es esperable: la ventana puede no tener eventos.
    total_a_comparar = max(1, numsis_csv_2)

    # compara fecha_hora de cada evento de seisan para determinar si esta publicado 
    for sismo2 in listacsv_2:
        avance=avance+1
        prog.avance(avance / total_a_comparar)

        # el estado (publicado/sin actualizar) se reinicia por cada evento de seisan
        diferencias=0
        per_noper=''

        for sismo1 in listacsv_1:
            # con esto tengo dudas de como programe al principio, podria hacer falta sumarle un minuto a las horas 1 y 2
            hora1=sismo1['dt']
            hora2=sismo2['dt']

            # determinando el delta en dias y segundos
            h2_menos_h1=hora2-hora1
            h1_menos_h2=hora1-hora2
            delta_dia=float(h2_menos_h1.days)
            delta_dia_aux=float(h1_menos_h2.days)
            delta_1=hora1-hora2
            delta_2=hora2-hora1
            delta_seg=float(delta_1.seconds)
            delta_seg_aux=float(delta_2.seconds)

            # determinando el delta en latitud y longitud
            lat2=float(sismo2['lat'])
            lat1=float(sismo1['lat'])
            lon2=float(sismo2['lon'])
            lon1=float(sismo1['lon'])
            delta_lat=round((lat2*(-1))-(lat1*(-1)),3)
            delta_lon=round((lon2*(-1))-(lon1*(-1)),3)

            # si los deltas son negativos los convierte a un numero positivo
            if delta_lat<0:
                delta_lat=delta_lat*(-1)
            
            if delta_lon<0:
                delta_lon=delta_lon*(-1)

            # el delta dia evita que sismos de distinto dia y con horas similares (horas dentro de la ventana de segundos)
            # sean considerados como no actualizados al ser comparados entre el evento que esta en los datos del evenquery
            # con los eventos extraidos con seisan
            # solo entraran a este if eventos comparados que sean del mismo dia en una ventana de segundos como maximo
            if (delta_dia == 0 or delta_dia_aux== 0) and (delta_seg <= max_seg or delta_seg_aux <= max_seg):
                pub=1
                # el delta maximo en coordenadas es de 1 grado en latitud y longitud
                if delta_lat <= max_lat and delta_lon <= max_lon:
                    # Coincidencia real: se anota la pareja completa para poder
                    # atribuir el evento publicado a un analista. El Δt y las
                    # distancias se guardan sin signo para que el consumidor
                    # pueda judgear la calidad del cruce sin recalcular nada.
                    cruces.append({
                        "n_fila_eventquery": sismo1['n_fila'],
                        "fecha_eventquery": sismo1['fecha_hora'],
                        "lat_eventquery": sismo1['lat'],
                        "lon_eventquery": sismo1['lon'],
                        "prof_eventquery": sismo1['prof'],
                        "mag_eventquery": sismo1['mag'],
                        "percibido": sismo1['perc'],
                        "fecha_local": sismo2['fecha_hora'],
                        "lat_local": sismo2['lat'],
                        "lon_local": sismo2['lon'],
                        "prof_local": sismo2['prof'],
                        "mag_local": sismo2['mag'],
                        "analista": sismo2['analista'],
                        "dt_seg": round(min(delta_seg, delta_seg_aux), 3),
                        "dlat": round(delta_lat, 4),
                        "dlon": round(delta_lon, 4),
                    })
                    if comparacion.parametros_discrepantes(
                            sismo1['lat'], sismo1['lon'],
                            sismo1['prof'], sismo1['mag'],
                            sismo2['lat'], sismo2['lon'],
                            sismo2['prof'], sismo2['mag']):
                        per_noper=sismo1['perc']
                        diferencias=1

        # Si el valor de la variable pub es 0 el sismo no esta publicado        
        if pub==0:
            # el evento no publicado se escribe en el txt de salida correspondiente
            total_eventos=total_eventos+1
            archivo.write(sismo2['fecha_hora']+' '+sismo2['lat']+' '+sismo2['lon']+' '+sismo2['prof']+' '+sismo2['mag']+' '+sismo2['tipo_mag']+' '+sismo2['analista']+' '+'?'+"\n")
            
            # Si la magnitud es igual o superior a 2.5 el evento tambien es incluido en otro txt adicional.
            # Un evento sin magnitud no entra al CSV: sin dato no se puede decir
            # que sea "menor que 2.5". Se cuenta aparte y se informa, porque si
            # no el total de no publicados y el del CSV no cierran y parece que
            # el evento se publicó.
            magnitud = _magnitud(sismo2['mag'])
            if magnitud is None:
                nopub_sin_magnitud = nopub_sin_magnitud + 1
            elif magnitud >= 2.5:
                totsobre2_5=totsobre2_5+1
                archivo2.write(sismo2['fecha_hora']+' '+sismo2['lat']+' '+sismo2['lon']+' '+sismo2['prof']+' '+sismo2['mag']+' '+sismo2['tipo_mag']+' '+sismo2['analista']+' '+'?'+"\n")
                # copia sin la clave temporal 'dt' para el .csv final
                listanopub.append({k: v for k, v in sismo2.items()
                                   if k != 'dt'})

        else:

            # Si el valor de la variable diferencia es distinto a 0 sismo no esta actualizado en la web
            # y se escribe el evento en el txt de salida correspondiente
            if diferencias!=0:
                total_diferentes=total_diferentes+1
                archivo1.write(sismo2['fecha_hora']+' '+sismo2['lat']+' '+sismo2['lon']+' '+sismo2['prof']+' '+sismo2['mag']+' '+sismo2['tipo_mag']+' '+sismo2['analista']+' '+per_noper+"\n")
                diferencias=0
                per_noper=''
        pub=0

    # Crea el csv de eventos no publicados. El del filtro estricto es caché: lo
    # leen app.py y generajson para armar el listado de no publicados, así que
    # se escribe siempre en datos/. El del amplio no lo lee nadie, va como
    # entregable y sin RV_ENTREGABLES ni se crea ni se borra el de antes.
    nombre_csv = "no_pub_desde_2_5_"+prefijo+sufijo+".csv"
    if sufijo == "estricto":
        salida = rutas.p_datos(nombre_csv)
    elif rutas.ENTREGABLES:
        salida = rutas.p_descargas(nombre_csv)
    else:
        salida = None
    if salida is not None:
        if listanopub:
            df = pd.DataFrame(listanopub)
            df.columns=['Fecha_Hora', 'Latitud', 'Longitud', 'Prof.', 'Mag.', 'Tipo_mag.', 'Analista']
            df.to_csv(salida)
        else:
            # Sin no publicados, se borra el CSV: si no, quedaría el de la corrida
            # anterior y app.py lo leería como si fuera de esta.
            _borrar(salida)

    # Atribución: de qué analista es cada evento publicado. Solo se toca con el
    # filtro estricto, que es el que sirve para atribuir (con el amplio se cuela
    # un cruce erróneo sin ganar ninguno, ver la nota de tolerancias). Sin
    # cruces se borra el archivo: "no existe" significa "no hay nada que
    # atribuir", que es distinto de un archivo vacío, y así no queda el de una
    # corrida anterior.
    if sufijo == "estricto":
        fuente = prefijo.rstrip("_") or "seisan"
        destino = rutas.p_datos("atribucion_%s.csv" % fuente)
        if cruces:
            candidatos = {}
            for c in cruces:
                clave = c["n_fila_eventquery"]
                candidatos[clave] = candidatos.get(clave, 0) + 1
            columnas = ["n_fila_eventquery", "fecha_eventquery",
                        "lat_eventquery", "lon_eventquery", "prof_eventquery",
                        "mag_eventquery", "percibido", "fecha_local",
                        "lat_local", "lon_local", "prof_local", "mag_local",
                        "analista", "dt_seg", "dlat", "dlon", "n_candidatos",
                        "fuente"]
            with open(destino, "w", newline="") as salida_atr:
                escritor = csv.writer(salida_atr)
                escritor.writerow(columnas)
                for c in cruces:
                    fila = [c[col] for col in columnas[:-2]]
                    fila.extend([candidatos[c["n_fila_eventquery"]], fuente])
                    escritor.writerow(fila)
            print('atribución de %s: %d cruces sobre %d eventos publicados'
                  % (fuente, len(cruces), len(candidatos)))
        else:
            _borrar(destino)

    archivo.close()
    archivo1.close()
    archivo2.close()
    return total_eventos, total_diferentes, totsobre2_5, salida, nopub_sin_magnitud

# Uso: compara.py <eventquery.csv> <soluciones_locales.csv> [prefijo]
# El prefijo es opcional y solo distingue la fuente local en los nombres de
# salida ("seiscomp_" para seiscomp_a_parametros.py). Sin él, la corrida es la
# de siempre y escribe los mismos nombres de siempre.
csv_file_1 = open(sys.argv[1])
csv_file_2 = open(sys.argv[2])

PREFIJO = sys.argv[3] if len(sys.argv) > 3 else ""

csvreader_1 = csv.reader(csv_file_1)
csvreader_2 = csv.reader(csv_file_2)

# saltar el encabezado de cada archivo .csv
next(csvreader_1,None)
next(csvreader_2,None)

# Declara diccionario
diccsv_1={}
diccsv_2={}

# Declara listas
listacsv_1=[]
listacsv_2=[]

numsis_csv_1=0
numsis_csv_2=0

# Creando diccionario que contiene lista con datos extraidos del .csv ordenado (eventquery)
# Las columnas numéricas se normalizan al formato fijo del flujo (coordenadas
# 3 decimales, profundidad y magnitud 1) con comparacion.py, que reemplaza al
# viejo relleno de ceros. Así las salidas quedan consistentes y la comparación
# numérica no depende de cuántos decimales traiga cada fuente.
for linea1 in csvreader_1:
    diccsv_1={
        "n_fila":linea1[0],
        "fecha_hora":linea1[1],
        "dt":_parsear_fecha_hora(linea1[1]),
        "lat":comparacion.formato_coordenada(linea1[2]),
        "lon":comparacion.formato_coordenada(linea1[3]),
        "prof":comparacion.formato_profundidad(linea1[4]),
        "mag":comparacion.formato_magnitud(linea1[5]),
        "tipo_mag":linea1[6],
        "ref":linea1[7],
        "perc":linea1[8]
    }
    listacsv_1.append(diccsv_1)

# Creando diccionario que contiene lista con datos extraidos del .csv ordenado (seisan)
for linea2 in csvreader_2:
    diccsv_2={
        "fecha_hora":linea2[1],
		"dt":_parsear_fecha_hora(linea2[1]),
		"lat":comparacion.formato_coordenada(linea2[2]),
		"lon":comparacion.formato_coordenada(linea2[3]),
		"prof":comparacion.formato_profundidad(linea2[4]),
		"mag":comparacion.formato_magnitud(linea2[5]),
		"tipo_mag":linea2[6],
		"analista":linea2[7],
    }
    listacsv_2.append(diccsv_2)

for sismo in listacsv_1:
    numsis_csv_1+=1
print('total eventos',sys.argv[1], numsis_csv_1, "( fuente eventquery )")

for sismo in listacsv_2:
    numsis_csv_2+=1
print('total eventos', sys.argv[2], numsis_csv_2,
      "( fuente select de seisan )" if not PREFIJO
      else "( fuente local %s )" % PREFIJO.rstrip("_"))

print("Comparando con filtro amplio ({}s/{}°/{}°)...".format(MAX_SEG_AMPLIO, MAX_LAT_LON_AMPLIO, MAX_LAT_LON_AMPLIO))
total_eventos_amplio, total_diferentes_amplio, totsobre2_5_amplio, salida_amplio, sinmag_amplio = comparar(listacsv_1, listacsv_2, MAX_SEG_AMPLIO, MAX_LAT_LON_AMPLIO, MAX_LAT_LON_AMPLIO, "amplio", PREFIJO)

print("\nComparando con filtro estricto ({}s/{}°/{}°)...".format(MAX_SEG_ESTRICTO, MAX_LAT_LON_ESTRICTO, MAX_LAT_LON_ESTRICTO))
total_eventos_estricto, total_diferentes_estricto, totsobre2_5_estricto, salida_estricto, sinmag_estricto = comparar(listacsv_1, listacsv_2, MAX_SEG_ESTRICTO, MAX_LAT_LON_ESTRICTO, MAX_LAT_LON_ESTRICTO, "estricto", PREFIJO)

print("\n--------------------------------------- Salida ---------------------------------------")
print('Filtro amplio ({}s/{}°)'.format(MAX_SEG_AMPLIO, MAX_LAT_LON_AMPLIO))
print('  total eventos no publicados: {}'.format(total_eventos_amplio))
print('  eventos no publicados >= a mag. 2.5: {}'.format(totsobre2_5_amplio))
print('  total eventos no actualizados: {}'.format(total_diferentes_amplio))
print('  no publicados sin magnitud (no entran al CSV): {}'.format(sinmag_amplio))
print('Filtro estricto ({}s/{}°)'.format(MAX_SEG_ESTRICTO, MAX_LAT_LON_ESTRICTO))
print('  total eventos no publicados: {}'.format(total_eventos_estricto))
print('  eventos no publicados >= a mag. 2.5: {}'.format(totsobre2_5_estricto))
print('  total eventos no actualizados: {}'.format(total_diferentes_estricto))
print('  no publicados sin magnitud (no entran al CSV): {}'.format(sinmag_estricto))
print('Archivos generados...')
print('no_act_%samplio.txt / no_act_%sestricto.txt' % (PREFIJO, PREFIJO))
print('no_pub_desde_2_5_%sestricto.csv' % PREFIJO)
if rutas.ENTREGABLES:
    print('En descargas/: no_pub_todos_*.txt / no_pub_desde_2_5_*.txt / '
          'no_pub_desde_2_5_*amplio.csv')
else:
    print('Entregables no generados (use RV_ENTREGABLES=1 si los necesita).')



