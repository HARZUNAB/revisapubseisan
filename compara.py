import csv
import sys, os
from os import remove
import time
import shutil
import datetime
from datetime import timedelta
import pandas as pd

import rutas

# parametros de los dos niveles de filtro (amplio y estricto)
MAX_SEG_AMPLIO=6
MAX_LAT_LON_AMPLIO=2.0
MAX_SEG_ESTRICTO=3
MAX_LAT_LON_ESTRICTO=1.0

# cabecera para cada archivo .txt de salida (Para plotear con google earth)
cabecera="fecha hora latitud longitud prof mag tipomag analista percibido\n"

def comparar(listacsv_1, listacsv_2, max_seg, max_lat, max_lon, sufijo):
    # archivos de salida
    archivo=open(rutas.p_informes("no_pub_todos_"+sufijo+".txt"), "w")
    archivo1=open(rutas.p_informes("no_act_"+sufijo+".txt"), "w")
    archivo2=open(rutas.p_informes("no_pub_desde_2_5_"+sufijo+".txt"), "w")

    archivo.write(cabecera)
    archivo1.write(cabecera)
    archivo2.write(cabecera)

    pub=0
    total_eventos=0
    diferencias=0
    total_diferentes=0
    totsobre2_5=0
    avance=0
    listanopub=[]

    # compara fecha_hora de cada evento de seisan para determinar si esta publicado 
    for sismo2 in listacsv_2:
        avance=avance+1
        poravance=(avance*100)/numsis_csv_2
        print('avance proceso: {:.0f}'.format(poravance),'%', end='\r')

        for sismo1 in listacsv_1:
            # con esto tengo dudas de como programe al principio, podria hacer falta sumarle un minuto a las horas 1 y 2
            if sismo1['fecha_hora'][-2:]=='60':
                hora1=sismo1['fecha_hora'][0:18]+'59'
            else:
                hora1=sismo1['fecha_hora']

            if sismo2['fecha_hora'][-2:]=='60':
                hora2=sismo2['fecha_hora'][0:18]+'59'
            else:
                hora2=sismo2['fecha_hora']

            # Convierte string fecha_hora en un dato de tipo datetime
            hora1=datetime.datetime.strptime(hora1, '%Y-%m-%d  %H:%M:%S')         
            hora2=datetime.datetime.strptime(hora2, '%Y-%m-%d  %H:%M:%S')

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
                pub=+1
                # el delta maximo en coordenadas es de 1 grado en latitud y longitud
                if delta_lat <= max_lat and delta_lon <= max_lon:
                    if sismo2['lat'] != sismo1['lat'] or sismo2['lon'] != sismo1['lon'] or sismo2['prof'] != sismo1['prof']:
                        per_noper=sismo1['perc']
                        diferencias=+1

        # Si el valor de la variable pub es 0 el sismo no esta publicado        
        if pub==0:
            # el evento no publicado se escribe en el txt de salida correspondiente
            total_eventos=total_eventos+1
            archivo.write(sismo2['fecha_hora']+' '+sismo2['lat']+' '+sismo2['lon']+' '+sismo2['prof']+' '+sismo2['mag']+' '+sismo2['tipo_mag']+' '+sismo2['analista']+' '+'?'+"\n")
            
            # Si la magnitud es igual o superior a 2.5 el evento tambien es incluido en otro txt adicional
            if float(sismo2['mag'])>=2.5:
                totsobre2_5=totsobre2_5+1
                archivo2.write(sismo2['fecha_hora']+' '+sismo2['lat']+' '+sismo2['lon']+' '+sismo2['prof']+' '+sismo2['mag']+' '+sismo2['tipo_mag']+' '+sismo2['analista']+' '+'?'+"\n")
                listanopub.append(sismo2)

        else:

            # Si el valor de la variable diferencia es distinto a 0 sismo no esta actualizado en la web
            # y se escribe el evento en el txt de salida correspondiente
            if diferencias!=0:
                total_diferentes=total_diferentes+1
                archivo1.write(sismo2['fecha_hora']+' '+sismo2['lat']+' '+sismo2['lon']+' '+sismo2['prof']+' '+sismo2['mag']+' '+sismo2['tipo_mag']+' '+sismo2['analista']+' '+per_noper+"\n")
                diferencias=0
                per_noper=''
        pub=0

    # crea csv para eventos no publicados
    salida=rutas.p_datos("no_pub_desde_2_5_"+sufijo+".csv")
    if listanopub:
        df = pd.DataFrame(listanopub)
        df.columns=['Fecha_Hora', 'Latitud', 'Longitud', 'Prof.', 'Mag.', 'Tipo_mag.', 'Analista']
        df.to_csv(salida)

    archivo.close()
    archivo1.close()
    archivo2.close()
    return total_eventos, total_diferentes, totsobre2_5, salida

csv_file_1 = open(sys.argv[1])
csv_file_2 = open(sys.argv[2])

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
for linea1 in csvreader_1:
    # Completa con ceros la latitud
    if len(linea1[2])<=6:
        largo_lat=len(linea1[2])
        if largo_lat==3:
            linea1[2]=linea1[2]+".000"
        if largo_lat==4:
            linea1[2]=linea1[2]+"000"
        if largo_lat==5:
            linea1[2]=linea1[2]+"00"
        if largo_lat==6:
            linea1[2]=linea1[2]+"0"

    # Completa con ceros la longitud
    if len(linea1[3])<=6:
        largo_lon=len(linea1[3])
        if largo_lon==3:
            linea1[3]=linea1[3]+".000"
        if largo_lon==4:
            linea1[3]=linea1[3]+"000"
        if largo_lon==5:
            linea1[3]=linea1[3]+"00"
        if largo_lon==6:
            linea1[3]=linea1[3]+"0"

    diccsv_1={
        "fecha_hora":linea1[1],
        "lat":linea1[2],
        "lon":linea1[3],
        "prof":linea1[4],
        "mag":linea1[5],
        "tipo_mag":linea1[6],
        "ref":linea1[7],
        "perc":linea1[8]
    }
    listacsv_1.append(diccsv_1)

# Creando diccionario que contiene lista con datos extraidos del .csv ordenado (seisan)
for linea2 in csvreader_2:
    # Completa con ceros la latitud
    if len(linea2[2])<=6:
        largo_lat=len(linea2[2])
        if largo_lat==3:
            linea2[2]=linea2[2]+".000"
        if largo_lat==4:
            linea2[2]=linea2[2]+"000"
        if largo_lat==5:
            linea2[2]=linea2[2]+"00"
        if largo_lat==6:
            linea2[2]=linea2[2]+"0"

    # Completa con ceros la longitud
    if len(linea2[3])<=6:
        largo_lon=len(linea2[3])
        if largo_lon==3:
            linea2[3]=linea2[3]+".000"
        if largo_lon==4:
            linea2[3]=linea2[3]+"000"
        if largo_lon==5:
            linea2[3]=linea2[3]+"00"
        if largo_lon==6:
            linea2[3]=linea2[3]+"0"

    diccsv_2={
        "fecha_hora":linea2[1],
		"lat":linea2[2],
		"lon":linea2[3],
		"prof":linea2[4],
		"mag":linea2[5],
		"tipo_mag":linea2[6],
		"analista":linea2[7],
    }
    listacsv_2.append(diccsv_2)

for sismo in listacsv_1:
    numsis_csv_1+=1
print('total eventos',sys.argv[1], numsis_csv_1, "( fuente eventquery )")

for sismo in listacsv_2:
    numsis_csv_2+=1
print('total eventos', sys.argv[2], numsis_csv_2, "( fuente select de seisan )")

print("Comparando con filtro amplio ({}s/{}°/{}°)...".format(MAX_SEG_AMPLIO, MAX_LAT_LON_AMPLIO, MAX_LAT_LON_AMPLIO))
total_eventos_amplio, total_diferentes_amplio, totsobre2_5_amplio, salida_amplio = comparar(listacsv_1, listacsv_2, MAX_SEG_AMPLIO, MAX_LAT_LON_AMPLIO, MAX_LAT_LON_AMPLIO, "amplio")

print("\nComparando con filtro estricto ({}s/{}°/{}°)...".format(MAX_SEG_ESTRICTO, MAX_LAT_LON_ESTRICTO, MAX_LAT_LON_ESTRICTO))
total_eventos_estricto, total_diferentes_estricto, totsobre2_5_estricto, salida_estricto = comparar(listacsv_1, listacsv_2, MAX_SEG_ESTRICTO, MAX_LAT_LON_ESTRICTO, MAX_LAT_LON_ESTRICTO, "estricto")

print("\n--------------------------------------- Salida ---------------------------------------")
print('Filtro amplio ({}s/{}°)'.format(MAX_SEG_AMPLIO, MAX_LAT_LON_AMPLIO))
print('  total eventos no publicados: {}'.format(total_eventos_amplio))
print('  eventos no publicados >= a mag. 2.5: {}'.format(totsobre2_5_amplio))
print('  total eventos no actualizados: {}'.format(total_diferentes_amplio))
print('Filtro estricto ({}s/{}°)'.format(MAX_SEG_ESTRICTO, MAX_LAT_LON_ESTRICTO))
print('  total eventos no publicados: {}'.format(total_eventos_estricto))
print('  eventos no publicados >= a mag. 2.5: {}'.format(totsobre2_5_estricto))
print('  total eventos no actualizados: {}'.format(total_diferentes_estricto))
print('Archivos generados...')
print('no_pub_todos_amplio.txt / no_act_amplio.txt / no_pub_desde_2_5_amplio.txt')
print('no_pub_todos_estricto.txt / no_act_estricto.txt / no_pub_desde_2_5_estricto.txt')
print('no_pub_desde_2_5_amplio.csv')
print('no_pub_desde_2_5_estricto.csv')



