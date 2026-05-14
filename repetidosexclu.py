import csv
import sys, os
from os import remove
import time
import shutil
import datetime
from datetime import timedelta

# archivos de salida
archivo2=open("rep_seisan_exclu.txt", "w")

# cabeceras para cada archivo .txt de salida (Para plotear con google earth)
archivo2.write("fecha hora analista\n")

csv_file_2 = open(sys.argv[1])
csvreader_2 = csv.reader(csv_file_2)

csv_file_3 = open(sys.argv[2])
csvreader_3 = csv.reader(csv_file_3)

# saltar el encabezado
next(csvreader_2,None)
next(csvreader_3,None)

# Declara diccionario
diccsv_2={}
diccsv_3={}

# Declara listas
listacsv_2=[]
listacsv_3=[]

numsis_csv_2=0
numsis_csv_3=0

# Creando diccionario que contiene lista con datos extraidos del .csv ordenado ("extraidos" desde select.out)
for linea2 in csvreader_2:
    diccsv_2={
        "fecha_hora":linea2[1],
		"analista":linea2[2],
    }
    listacsv_2.append(diccsv_2)

for sismo in listacsv_2:
    numsis_csv_2+=1

print('total de eventos a revisar', numsis_csv_2, "( fuente archivo excluidos del selec.out )")

# Creando diccionario que contiene lista con datos extraidos del .csv ordenado (desde select.out)
for linea3 in csvreader_3:
    diccsv_3={
        "fecha_hora":linea3[1],
		"analista":linea3[7],
    }
    listacsv_3.append(diccsv_3)

for sismo3 in listacsv_3:
    numsis_csv_3+=1

print('total de eventos desde select.out', numsis_csv_3, "( fuente archivo select.out )")

#codigo nuevo
rep_seisan_exclu=0
rep_seisan_exclu_total=0
avance=0
fecha_inicio = datetime.datetime.today().strftime("%Y-%m-%d %H:%M:%S")
avance=0
for sismo2 in listacsv_2:
    rep_seisan=0
    delta_dia=0
    delta_segundos=0
    avance=avance+1
    poravance=(avance*100)/numsis_csv_2
    print('avance proceso: {:.0f}'.format(poravance),'%', end='\r')
    hora_1=sismo2['fecha_hora']
    hora_1=datetime.datetime.strptime(hora_1, '%Y-%m-%d  %H:%M:%S')
    for sismo3 in listacsv_3:
        hora_2=sismo3['fecha_hora']
        hora_2=datetime.datetime.strptime(hora_2, '%Y-%m-%d  %H:%M:%S')
        
        deltatiempo1=hora_2-hora_1
        deltatiempo2=hora_1-hora_2

        deltadias1=deltatiempo1.days
        deltaminutos1=deltatiempo1.min
        deltasegundos1=deltatiempo1.total_seconds()

        deltadias2=deltatiempo2.days
        deltaminutos2=deltatiempo2.min
        deltasegundos2=deltatiempo2.total_seconds()

        # Ventana de 3 segundos para filtrar posibles eventos repetidos
        if (deltadias1 == 0 or deltadias2 == 0) and ((deltasegundos1 >=0 and deltasegundos1 <=6) or (deltasegundos2 >= 0 and deltasegundos2 <= 6)):
            archivo2.write(sismo2['fecha_hora']+' '+sismo2['analista']+"\n")
            rep_seisan_exclu=rep_seisan_exclu+1
            rep_seisan_exclu_total=rep_seisan_exclu_total+1 #funciona
    
    # Si encuentra mas de un evento con similitudes en la busqueda lo define como posible repetido
    # esto es por que la busqueda se hace tomando un elemento de la lista y lo busca en la misma lista hasta llegar al final de esta
    #if rep_seisan_exclu > 0:
    #    print(rep_seisan_exclu)
        #rep_seisan_exclu_total=rep_seisan_exclu_total+1
        #archivo2.write(sismo2['fecha_hora']+' '+sismo2['analista']+"\n")

    rep_seisan_exclu=0

print("\nFinalizado")
#time.sleep(5)

fecha_termino = datetime.datetime.today().strftime("%Y-%m-%d %H:%M:%S")
fecha_inicio = datetime.datetime.strptime(fecha_inicio, '%Y-%m-%d  %H:%M:%S')
fecha_termino = datetime.datetime.strptime(fecha_termino, '%Y-%m-%d  %H:%M:%S')
tiempo_proc=fecha_termino-fecha_inicio

#print("----------------------------------- Salida -----------------------------------")
#print('tiempo proceso:', tiempo_proc) 
print('Posibles repetidos excluidos en seisan:',rep_seisan_exclu_total)
print('Archivos generados...')
print(archivo2.name)
