import numpy as np
import pandas as pd
import datetime
import sys, os
from dataclasses import asdict
import pytz
import csv
import operator
import pandas as pandasForSortingCSV
from os import remove

csv_file = open(sys.argv[1])
#fh = open(sys.argv[2],"w", encoding='utf-8')
fh = open(sys.argv[2],"w")
csvreader = csv.reader(csv_file)

# Asigna datos del csv de origen
#csvData = pandasForSortingCSV.read_csv(csv_file)
csvData = pd.read_csv(csv_file)
                                         
# Ordena datos por fecha
csvData = csvData.sort_values(["time"], ascending=True)

# Crea archivo .csv ordenado
fecha_hoy_csv = datetime.datetime.today().strftime("%Y%m%d%H%M%S")
salidacsv = 'csvData_' + fecha_hoy_csv + '.csv'
csvData.to_csv(salidacsv)


csvData = open(sys.argv[1], encoding='utf-8')
fh = open(sys.argv[2],"w")
csvreader = csv.reader(csvData)

# saltar el encabezado
next(csvreader,None)

# Declara diccionario
listacsv={}

num_datos=0

# Creando diccionario con lista interior con datos extraidos del .csv ordenado
for linea in csvreader:
	num_datos=num_datos+1
	listacsv[linea[0]] = linea	

# Ordena Diccionario por llave (fecha del evento)
sortedDict = sorted(listacsv.items(), key=operator.itemgetter(0))

if num_datos>0:
	# Prepara salida .dat
	listacsv=[]
	listacsv2=[]
	fecha_hoy = datetime.datetime.today().strftime("%Y-%m-%d  %H:%M:%S")
	fh.write("%s %s \n" %('Fuente : ', sys.argv[1]))
	fh.write("%s %s \t \t \t \t \t \t %s %s \n" %('Destino: ', sys.argv[2], 'Impresion: ', fecha_hoy))
	fh.write('-----------------------------------------------------------------------------------------------------------------\n')
	fh.write("%s \t%s \t%s \t%s \t%s \t%s \t%s \t%s \t%s \n" %('Fecha','    Hora',' Lat',' Long','Prof','Mag','T_Mag','Perc','Obs'))
	fh.write('-----------------------------------------------------------------------------------------------------------------\n')
	for sismo in sortedDict:
	#for index,row in csvData.iterrows():
		# sismo[0] es la llave (el tiempo que usaste para ordenar)
    	# sismo[1] es la lista con [time, lat, long, depth, mag, etc...]
    
		datos_sismo = sismo[1]
		
		# Extraemos la fecha de la posición 0 de la lista de datos
		fecha_original = datos_sismo[0]
		fecha = datetime.datetime.strptime(fecha_original.replace('Z', ''), '%Y-%m-%dT%H:%M:%S')
		fecha2 = fecha.strftime("%Y %m %d %H %M %S")
		
		# Extraemos los demás datos por su posición en la lista
		latitud = float(datos_sismo[1])
		longitud = float(datos_sismo[2])
		prof = float(datos_sismo[3])
		mag = float(datos_sismo[4])
		tipo_mag = datos_sismo[5]
		ref = datos_sismo[6]
		perc = "S" if datos_sismo[7] == "t" else "N"
		
		# Escritura en el archivo .dat
		fh.write('-----------------------------------------------------------------------------------------------------------------\n')
				
		sismolista = fecha, latitud, longitud, prof, mag, tipo_mag, ref, perc, "", "", "", "", "", "", "", ""
		sismolista2 = fecha, latitud, longitud, prof, mag, tipo_mag, ref, perc
		listacsv.append(sismolista)
		listacsv2.append(sismolista2)

	df = pd.DataFrame(listacsv)
	df.columns=['Fecha_Hora', 'Latitud', 'Longitud', 'Prof.', 'Mag.', 'Tipo_mag.', 'Referencia', 'Percep', "Est_leidas", "Autor", "Estruc_origen", "Estruc_Final", "Est_add", "Est_eli", "Act. web", "Observaciones"]
	salida='new_'+sys.argv[1]
	df.to_csv(salida)

	df2 = pd.DataFrame(listacsv2)
	df2.columns=['Fecha_Hora', 'Latitud', 'Longitud', 'Prof.', 'Mag.', 'Tipo_mag.', 'Referencia', 'Percep.']
	salida2='new_2_'+sys.argv[1]
	df2.to_csv(salida2)

	print('Nuevos archivos generados...')
	print(salida)
	print(sys.argv[2])
	print(salida2)
	# Sacar comentario si se desea borrar este archivo
	remove(sys.argv[1])
	remove(salidacsv)
	exit()
else:
	remove(sys.argv[2])
	remove(salidacsv)
	#print('no eliminado', salidacsv)
	print('¡¡¡¡¡ No existen datos !!!!!')

