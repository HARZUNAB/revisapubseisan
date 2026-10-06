import pandas as pd
import datetime
import sys, os
import csv
import operator
from os import remove

import rutas
import prog


def _parsear_tiempo(texto):
    """
    Interpreta el instante de un evento de eventquery.

    Acepta el export viejo ('2026-08-01T01:36:26Z') y el actual
    ('2026-09-04 23:58:48.654902-04:00', con espacio, microsegundos y offset).
    Devuelve UTC naive y sin microsegundos: es la semántica del 'Z' viejo, que
    es la que cruza con las horas UTC de select.out.
    """
    limpio = (texto or "").strip().replace("Z", "+00:00")
    try:
        fecha = datetime.datetime.fromisoformat(limpio)
    except ValueError:
        fecha = None
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d %H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S%z",
                    "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                fecha = datetime.datetime.strptime(limpio, fmt)
                break
            except ValueError:
                continue
        if fecha is None:
            raise ValueError("No se reconoce la fecha: %r" % texto)
    if fecha.tzinfo is not None:
        fecha = fecha.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return fecha.replace(microsecond=0)


csv_file = open(sys.argv[1])
#fh = open(sys.argv[2],"w", encoding='utf-8')
fh = open(sys.argv[2],"w")
csvreader = csv.reader(csv_file)

# El total de eventos se cuenta leyendo solo la primera columna, en vez de
# pd.read_csv completo. Ese read servía para el sort y para el
# csvData_<fecha>.csv ordenado, que se escribía y se borraba sin que nadie lo
# leyera: el script vuelve a abrir el original más abajo y arma el diccionario
# desde ahí, ordenando por llave al final. Medido sobre un CSV de 25 MB, el sort
# más la copia que se escribían acá costaban 2.2 s, y el read entero 0.24 s
# contra 0.16 s de leer una sola columna.
#
# No se cuenta con len(lineas) porque un salto de línea dentro de un campo
# entrecomillado (un comentario, por ejemplo) no es una fila nueva: el conteo
# físico contiguousía de más y la barra de progreso se passes de 1.
num_total = len(pd.read_csv(sys.argv[1], usecols=[0]))

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
	if num_total > 0:
		prog.avance(num_datos / num_total)	

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
	num_escritos=0
	for sismo in sortedDict:
	#for index,row in csvData.iterrows():
		# sismo[0] es la llave (el tiempo que usaste para ordenar)
    	# sismo[1] es la lista con [time, lat, long, depth, mag, etc...]
    
		num_escritos = num_escritos + 1
		prog.avance(num_escritos / num_total if num_total > 0 else 1.0)
		datos_sismo = sismo[1]
		
		# Extraemos la fecha de la posición 0 de la lista de datos
		fecha_original = datos_sismo[0]
		fecha = _parsear_tiempo(fecha_original)
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
	salida=rutas.p_datos('new_'+os.path.basename(sys.argv[1]))
	df.to_csv(salida)

	df2 = pd.DataFrame(listacsv2)
	df2.columns=['Fecha_Hora', 'Latitud', 'Longitud', 'Prof.', 'Mag.', 'Tipo_mag.', 'Referencia', 'Percep.']
	salida2=rutas.p_datos('new_2_'+os.path.basename(sys.argv[1]))
	df2.to_csv(salida2)

	print('Nuevos archivos generados...')
	print(salida)
	print(sys.argv[2])
	print(salida2)
	exit()
else:
	remove(sys.argv[2])
	print('¡¡¡¡¡ No existen datos !!!!!')

