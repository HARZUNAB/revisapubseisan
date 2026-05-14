import csv
import sys, os
from os import remove
import time
import shutil
import datetime
from datetime import timedelta

# archivos de salida
archivo1=open("rep_publica.txt", "w")
archivo2=open("rep_seisan.txt", "w")

# cabeceras para cada archivo .txt de salida (Para plotear con google earth)
archivo1.write("fecha hora latitud longitud prof mag tipomag referencia percibido\n")
archivo2.write("fecha hora latitud longitud prof mag tipomag analista\n")

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

rep_publica=0
rep_publica_total=0
rep_seisan=0
rep_seisan_total=0
avance=0
fecha_inicio = datetime.datetime.today().strftime("%Y-%m-%d %H:%M:%S")

# revisando datos extraidos de publica (eventos publicados y extraidos con eventquery)
# Revisa .csv con los datos que tienen como fuente el select de seisan y el posterior newcollect generado en los pasos anteriores (en revisacollect.py)
print("Revisando datos de publica...")
for sismo1 in listacsv_1:
    rep_publica=0
    avance=avance+1
    poravance=(avance*100)/numsis_csv_1
    print('avance proceso: {:.0f}'.format(poravance),'%', end='\r')
    hora_1=sismo1['fecha_hora']
    hora_1=datetime.datetime.strptime(hora_1, '%Y-%m-%d  %H:%M:%S')
    
    for sismo_1_1 in listacsv_1:
        hora_2=sismo_1_1['fecha_hora']
        hora_2=datetime.datetime.strptime(hora_2, '%Y-%m-%d  %H:%M:%S')

        deltatiempo1=hora_2-hora_1
        deltatiempo2=hora_1-hora_2

        deltadias1=deltatiempo1.days
        deltaminutos1=deltatiempo1.min
        deltasegundos1=deltatiempo1.total_seconds()

        deltadias2=deltatiempo2.days
        deltaminutos2=deltatiempo2.min
        deltasegundos2=deltatiempo2.total_seconds()

        """
        h2_menos_h1=hora_2-hora_1
        h1_menos_h2=hora_1-hora_2
        delta_dia=float(h2_menos_h1.days)
        delta_dia_aux=float(h1_menos_h2.days)
        delta_segundos=float(h2_menos_h1.seconds)
        delta_segundos_aux=float(h1_menos_h2.seconds)
        """

        # Ventana de 3 segundos para filtrar posibles eventos repetidos
        #if (delta_dia == 0 or delta_dia_aux == 0) and (delta_segundos <= 3 or delta_segundos_aux <= 3):   
        if (deltadias1 == 0 or deltadias2 == 0) and ((deltasegundos1 >=0 and deltasegundos1 <=3) or (deltasegundos2 >= 0 and deltasegundos2 <= 3)):
            lat1=float(sismo1['lat'])
            lat1_1=float(sismo_1_1['lat'])
            lon1=float(sismo1['lon'])
            lon1_1=float(sismo_1_1['lon'])
            delta_lat=round((lat1*(-1))-(lat1_1*(-1)),3)
            delta_lon=round((lon1*(-1))-(lon1_1*(-1)),3)

            if delta_lat<0:
                delta_lat=delta_lat*(-1)
            
            if delta_lon<0:
                delta_lon=delta_lon*(-1)

            # Delta de 0.200 en coordenadas de latitud y longitud
            #if (delta_dia == 0.0 or delta_dia_aux == 0.0) and (delta_lat >= 0 and delta_lat <= 0.200) and (delta_lon >= 0 and delta_lon <= 0.200):
            if (deltadias1 == 0 or deltadias2 == 0) and (delta_lat >= 0 and delta_lat <= 0.200) and (delta_lon >= 0 and delta_lon <= 0.200):
                rep_publica=rep_publica+1


        
    # Si encuentra mas de un evento con similitudes en la busqueda lo define como posible repetido
    # esto es por que la busqueda se hace tomando un elemento de la lista y lo busca en la misma lista hasta llegar al final de esta
    if rep_publica > 1:
        rep_publica_total=rep_publica_total+1
        archivo1.write(sismo1['fecha_hora']+' '+sismo1['lat']+' '+sismo1['lon']+' '+sismo1['prof']+' '+sismo1['mag']+' '+sismo1['tipo_mag']+' '+sismo1['ref']+' '+sismo1['perc']+"\n")
        #time.sleep(10)

    rep_publica=0
  
print("\nFinalizado")

# revisando datos extraidos de seisan extraidos inicialmente con select (posteriormente se ejecutan scripts revisaslect.py y revisacollect.py en ese orden)
avance=0
print("Revisando datos de seisan...")
for sismo2 in listacsv_2:
    rep_seisan=0
    delta_dia=0
    delta_segundos=0
    avance=avance+1
    poravance=(avance*100)/numsis_csv_2
    print('avance proceso: {:.0f}'.format(poravance),'%', end='\r')
    hora_1=sismo2['fecha_hora']
    hora_1=datetime.datetime.strptime(hora_1, '%Y-%m-%d  %H:%M:%S')
    for sismo_2_2 in listacsv_2:
        hora_2=sismo_2_2['fecha_hora']
        hora_2=datetime.datetime.strptime(hora_2, '%Y-%m-%d  %H:%M:%S')

        deltatiempo1=hora_2-hora_1
        deltatiempo2=hora_1-hora_2

        deltadias1=deltatiempo1.days
        deltaminutos1=deltatiempo1.min
        deltasegundos1=deltatiempo1.total_seconds()

        deltadias2=deltatiempo2.days
        deltaminutos2=deltatiempo2.min
        deltasegundos2=deltatiempo2.total_seconds()

        """
        h2_menos_h1=hora_2-hora_1
        h1_menos_h2=hora_1-hora_2
        delta_dia=float(h2_menos_h1.days)
        delta_dia_aux=float(h1_menos_h2.days)
        delta_segundos=float(h2_menos_h1.seconds)
        delta_segundos_aux=float(h1_menos_h2.seconds)
        """
        
        # Ventana de 3 segundos para filtrar posibles eventos repetidos
        #if (delta_dia == 0 or delta_dia_aux == 0) and (delta_segundos <= 3 or delta_segundos_aux <= 3):
        if (deltadias1 == 0 or deltadias2 == 0) and ((deltasegundos1 >=0 and deltasegundos1 <=3) or (deltasegundos2 >= 0 and deltasegundos2 <= 3)):
            lat2=float(sismo2['lat'])
            lat2_2=float(sismo_2_2['lat'])
            lon2=float(sismo2['lon'])
            lon2_2=float(sismo_2_2['lon'])
            delta_lat=round((lat2*(-1))-(lat2_2*(-1)),3)
            delta_lon=round((lon2*(-1))-(lon2_2*(-1)),3)

            if delta_lat<0:
                delta_lat=delta_lat*(-1)
            
            if delta_lon<0:
                delta_lon=delta_lon*(-1)
            
            # Delta de 0.200 en coordenadas de latitud y longitud
            #if (delta_dia == 0.0 or delta_dia_aux == 0.0) and (delta_lat >= 0 and delta_lat <= 0.200) and (delta_lon >= 0 and delta_lon <= 0.200):
            if (deltadias1 == 0 or deltadias2 == 0) and (delta_lat >= 0 and delta_lat <= 0.200) and (delta_lon >= 0 and delta_lon <= 0.200):
                rep_seisan=rep_seisan+1
    
    # Si encuentra mas de un evento con similitudes en la busqueda lo define como posible repetido
    # esto es por que la busqueda se hace tomando un elemento de la lista y lo busca en la misma lista hasta llegar al final de esta
    if rep_seisan > 1:
        rep_seisan_total=rep_seisan_total+1
        archivo2.write(sismo2['fecha_hora']+' '+sismo2['lat']+' '+sismo2['lon']+' '+sismo2['prof']+' '+sismo2['mag']+' '+sismo2['tipo_mag']+' '+sismo2['analista']+"\n")

    rep_seisan=0
  
print("\nFinalizado")
#time.sleep(5)
# fin revision seisan

fecha_termino = datetime.datetime.today().strftime("%Y-%m-%d %H:%M:%S")
fecha_inicio = datetime.datetime.strptime(fecha_inicio, '%Y-%m-%d  %H:%M:%S')
fecha_termino = datetime.datetime.strptime(fecha_termino, '%Y-%m-%d  %H:%M:%S')
tiempo_proc=fecha_termino-fecha_inicio

#print("----------------------------------- Salida -----------------------------------")
#print('tiempo proceso:', tiempo_proc) 
print('Posibles repetidos en publica:',rep_publica_total)
print('Posibles repetidos en seisan:',rep_seisan_total)
print('Archivos generados...')
print(archivo1.name)
print(archivo2.name)
