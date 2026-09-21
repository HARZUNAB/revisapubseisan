import csv
import sys, os
from os import remove
import time
import shutil
import datetime
from datetime import timedelta

# cabeceras para cada archivo .txt de salida (Para plotear con google earth)
cabecera_publica="fecha hora latitud longitud prof mag tipomag referencia percibido\n"
cabecera_seisan="fecha hora latitud longitud prof mag tipomag analista\n"

# campos de cada fuente utilizados en los archivos de salida
campos_publica=['fecha_hora', 'lat', 'lon', 'prof', 'mag', 'tipo_mag', 'ref', 'perc']
campos_seisan=['fecha_hora', 'lat', 'lon', 'prof', 'mag', 'tipo_mag', 'analista']

# parametros de los dos niveles de filtro (amplio y estricto)
MAX_SEG_AMPLIO=6
MAX_LAT_LON_AMPLIO=2.0
MAX_SEG_ESTRICTO=3
MAX_LAT_LON_ESTRICTO=1.0

def detecta_repetidos(lista_sismos, max_seg, max_lat, max_lon, nombre_archivo, cabecera, campos):
    # revisa cada sismo contra toda la lista y cuenta las coincidencias dentro de la ventana de tiempo y coordenadas
    total_repetidos=0
    avance=0
    archivo=open(nombre_archivo, "w")
    archivo.write(cabecera)
    for sismo in lista_sismos:
        repeticiones=0
        avance=avance+1
        poravance=(avance*100)/len(lista_sismos)
        print('avance proceso: {:.0f}'.format(poravance),'%', end='\r')
        hora_1=sismo['fecha_hora']
        hora_1=datetime.datetime.strptime(hora_1, '%Y-%m-%d  %H:%M:%S')

        for sismo_aux in lista_sismos:
            hora_2=sismo_aux['fecha_hora']
            hora_2=datetime.datetime.strptime(hora_2, '%Y-%m-%d  %H:%M:%S')

            deltatiempo1=hora_2-hora_1
            deltatiempo2=hora_1-hora_2

            deltadias1=deltatiempo1.days
            deltasegundos1=deltatiempo1.total_seconds()

            deltadias2=deltatiempo2.days
            deltasegundos2=deltatiempo2.total_seconds()

            # ventana de tiempo para filtrar posibles eventos repetidos
            if (deltadias1 == 0 or deltadias2 == 0) and ((deltasegundos1 >=0 and deltasegundos1 <=max_seg) or (deltasegundos2 >= 0 and deltasegundos2 <= max_seg)):
                lat_sismo=float(sismo['lat'])
                lat_aux=float(sismo_aux['lat'])
                lon_sismo=float(sismo['lon'])
                lon_aux=float(sismo_aux['lon'])
                delta_lat=round((lat_sismo*(-1))-(lat_aux*(-1)),3)
                delta_lon=round((lon_sismo*(-1))-(lon_aux*(-1)),3)

                if delta_lat<0:
                    delta_lat=delta_lat*(-1)

                if delta_lon<0:
                    delta_lon=delta_lon*(-1)

                # ventana de coordenadas para filtrar posibles eventos repetidos
                if (delta_lat >= 0 and delta_lat <= max_lat) and (delta_lon >= 0 and delta_lon <= max_lon):
                    repeticiones=repeticiones+1

        # si encuentra mas de un evento con similitudes en la busqueda lo define como posible repetido
        # esto es por que la busqueda se hace tomando un elemento de la lista y lo busca en la misma lista hasta llegar al final de esta
        if repeticiones > 1:
            total_repetidos=total_repetidos+1
            linea=' '.join(sismo[campo] for campo in campos)
            archivo.write(linea+"\n")

    archivo.close()
    return total_repetidos

csv_file_1 = open(sys.argv[1])
csv_file_2 = open(sys.argv[2])

csvreader_1 = csv.reader(csv_file_1)
csvreader_2 = csv.reader(csv_file_2)

# saltar el encabezado
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

print("Revisando datos de publica...")
rep_publica_amplio=detecta_repetidos(listacsv_1, MAX_SEG_AMPLIO, MAX_LAT_LON_AMPLIO, MAX_LAT_LON_AMPLIO, "rep_publica_amplio.txt", cabecera_publica, campos_publica)
rep_publica_estricto=detecta_repetidos(listacsv_1, MAX_SEG_ESTRICTO, MAX_LAT_LON_ESTRICTO, MAX_LAT_LON_ESTRICTO, "rep_publica_estricto.txt", cabecera_publica, campos_publica)

print("\nFinalizado")

print("Revisando datos de seisan...")
rep_seisan_amplio=detecta_repetidos(listacsv_2, MAX_SEG_AMPLIO, MAX_LAT_LON_AMPLIO, MAX_LAT_LON_AMPLIO, "rep_seisan_amplio.txt", cabecera_seisan, campos_seisan)
rep_seisan_estricto=detecta_repetidos(listacsv_2, MAX_SEG_ESTRICTO, MAX_LAT_LON_ESTRICTO, MAX_LAT_LON_ESTRICTO, "rep_seisan_estricto.txt", cabecera_seisan, campos_seisan)

print("\nFinalizado")
print("----------------------------------- Salida -----------------------------------")
print('Posibles repetidos en publica (amplio, {}s/{}°): {}'.format(MAX_SEG_AMPLIO, MAX_LAT_LON_AMPLIO, rep_publica_amplio))
print('Posibles repetidos en publica (estricto, {}s/{}°): {}'.format(MAX_SEG_ESTRICTO, MAX_LAT_LON_ESTRICTO, rep_publica_estricto))
print('Posibles repetidos en seisan (amplio, {}s/{}°): {}'.format(MAX_SEG_AMPLIO, MAX_LAT_LON_AMPLIO, rep_seisan_amplio))
print('Posibles repetidos en seisan (estricto, {}s/{}°): {}'.format(MAX_SEG_ESTRICTO, MAX_LAT_LON_ESTRICTO, rep_seisan_estricto))
print('Archivos generados...')
print('rep_publica_amplio.txt')
print('rep_publica_estricto.txt')
print('rep_seisan_amplio.txt')
print('rep_seisan_estricto.txt')