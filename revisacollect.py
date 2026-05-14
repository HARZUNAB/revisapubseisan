
import datetime
import time
import csv
import pandas as pd
import sys, os
from os import remove
import operator
import pandas as pandasForSortingCSV
from thefuzz import process, fuzz
import Levenshtein

sismos={}
lista=[]
newlista=[]
nuevalista=[]
sismolista=[]
linealista=''

# genera txt agregando un cero a dias menores a 10 y separa el dia del mes
archivo=open("newcollect.txt")
archivo1=open("newcollect_1.txt", "w")
for linea in archivo:
	sismo=linea.split()
	largolista=len(sismo)
	for elemento in range(largolista):
		if elemento==1:
			if len(sismo[elemento])==1:
				linealista=linealista+'0'+sismo[elemento]+" "
			if len(sismo[elemento])==2:
				linealista=linealista+sismo[elemento]+" "
			if len(sismo[elemento])==3:
				linealista=linealista+'0'+sismo[elemento][0]+' '+sismo[elemento][-2:]+" "
			if len(sismo[elemento])==4:
					linealista=linealista+sismo[elemento][0:2]+' '+sismo[elemento][-2:]+" "	
		else:
			linealista=linealista+sismo[elemento]+' '
	linealista_aux=linealista.split()
	#print('linealista_aux:', linealista_aux)
	#print('largo indice 2', len(linealista_aux[2]))
	if len(linealista_aux[2])==1:
		linealista_aux[2]='0'+linealista_aux[2]
		nuevalinea=''
		for caracter in linealista_aux:
			nuevalinea=nuevalinea+caracter+' '
		linealista=nuevalinea
	linealista=linealista[:-1]
	archivo1.write(linealista+"\n")
	linealista=''

# Archvos .txt de entrada y salida
archivo1=open("newcollect_1.txt")
archivo2=open('newcollect_2.txt', "w")
archivo4=open('constation0.txt', "w")
archivo5=open('sinestructura.txt', "w")

sinestruc=0
concero=0

linealista=''
for linea in archivo1:
	sismo=linea.split()
	largolista=len(sismo)	
	if sismo[4].find('L')==-1 and sismo[4].find('R')==-1 and sismo[4].find('D')==-1:
		# evento sin estructura. Se le asigna Station0 por defecto
		# escribe evento en txt de eventos originalmente sin estructura
		sinestruc=sinestruc+1
		archivo5.write(linea)
		if len(sismo)<= 13:
			linealista=sismo[0]+" "+sismo[1]+" "+sismo[2]+" "+sismo[3]+" "+sismo[4]+"0"+sismo[5]+" "+sismo[6]+" "+sismo[7]+" "+sismo[8]+" "+sismo[9]+" "+sismo[10]+" "+sismo[11]+" "+sismo[12]+" "+sismo[len(sismo)-1]+"\n"
		else:
			if len(sismo)==14:
				linealista=sismo[0]+" "+sismo[1]+" "+sismo[2]+" "+sismo[3]+" "+sismo[4]+"0"+sismo[5]+" "+sismo[6]+" "+sismo[7]+" "+sismo[8]+" "+sismo[9]+" "+sismo[10]+" "+sismo[11]+" "+sismo[12]+" "+sismo[len(sismo)-1]+"\n"
			else:
				linealista=sismo[0]+" "+sismo[1]+" "+sismo[2]+" "+sismo[3]+" "+sismo[4]+"0"+sismo[5]+" "+sismo[6]+" "+sismo[7]+" "+sismo[8]+" "+sismo[9]+" "+sismo[10]+" "+sismo[11]+" "+sismo[12]+" "+sismo[13]+" "+sismo[len(sismo)-1]+"\n"
	else:
		linealista=linea
		linealistaaux=linealista.split()
		# si la estructura utilizada originalmente es el station0, escribe el evento en un txt de eventos con station0
		if linealistaaux[4][-2]=='0':
			concero=concero+1
			archivo4.write(linealista)	
	
	archivo2.write(linealista)
	linealista=''

# Separa la longitud de la profundidad en los casos que esta sea mayor a 99 km (que tenga 3 o mas digitos)
archivo2=open("newcollect_2.txt")
archivo3=open("newcollect_final.txt", "w")
for linea2 in archivo2:
	sismo=linea2.split()
	largolista=len(sismo)
	if len(sismo[6])<=7:
		archivo3.write(linea2)
	else:
		for elemento in range(largolista):
			if elemento==6 and len(sismo[elemento])>7:
				# Si la profundidad esta fija o iterada elimina el caracter correspondiente antes de escribir el evento en el txt
				if sismo[elemento][-1:]=='F' or sismo[elemento][-1:]=='S':
					linealista=linealista+sismo[elemento][0:7]+' '+sismo[elemento][-6:]+" "
				else:
					linealista=linealista+sismo[elemento][0:7]+' '+sismo[elemento][-5:]+" "
			else:
				linealista=linealista+sismo[elemento]+' '
		linealista=linealista[:-1]
		archivo3.write(linealista+"\n")
		linealista=''

# Borra archivos txt temporales		
remove("newcollect_1.txt")
remove("newcollect_2.txt")

# crea archivo salida salida_collect.csv
archivo3=open("newcollect_final.txt")
listacsv=[]
numeventofinal=0
for linea in archivo3:
	numeventofinal+=1
	sismo=linea.split()
	pospunto=sismo[4].find('.')
	dato=sismo[4][0:pospunto]
	if len(sismo[1])<2:
		sismo[1]="0"+sismo[1]
	if len(sismo[2])<2:
		sismo[2]="0"+sismo[2]
	if int(sismo[4][0:pospunto])<10:
		segundos="0"+sismo[4][0:1]
	else:
		segundos=sismo[4][0:2]
	fecha_hora=sismo[0]+"-"+sismo[1]+"-"+sismo[2]+"  "+sismo[3][0:2]+":"+sismo[3][-2:]+":"+segundos
	lat=sismo[5]
	lon=sismo[6]
	if sismo[7][-1]=='F' or sismo[7][-1]=='S':
		largoprof=len(sismo[7])-1
		sismo[7]=sismo[7][0:largoprof]
	prof=sismo[7]
	mag=sismo[11][0:3]
	tipomag="M"+sismo[11][3:4]
	analista=sismo[len(sismo)-1]
	sismolista=fecha_hora, lat, lon, prof, mag, tipomag, analista
	listacsv.append(sismolista)

df = pd.DataFrame(listacsv)
df.columns=['Fecha_Hora', 'Latitud', 'Longitud', 'Prof.', 'Mag.', 'Tipo_mag.', 'Analista']
salida='salida_collect_tmp.csv'
df.to_csv(salida)

# Asigna datos del csv de origen
salida = pandasForSortingCSV.read_csv(salida)

#print(salida)

# Ordena datos por fecha
salida.sort_values(["Fecha_Hora"], 
                    axis=0,
                    ascending=[True], 
                    inplace=True)
  
# Crea archivo .csv ordenado
salida_csv = 'salida_collect_sort.csv'
salida.to_csv(salida_csv)

# borra .csv temporal
remove('salida_collect_tmp.csv')

csvData = open(salida_csv, encoding='utf-8')
csvreader = csv.reader(csvData)

# saltar el encabezado
next(csvreader,None)

# Creando lista con datos extraidos del .csv ordenado
listacsv=[]
for linea in csvreader:
	#print(linea)
	# verifica si hora queda con segundo 60
	if linea[2][-2:]=='60':
		linea[2]=linea[2][0:18]+'00'
		# se le suma 1 minuto a la hora
		hora=datetime.datetime.strptime(linea[2], '%Y-%m-%d  %H:%M:%S')
		hora=hora+datetime.timedelta(minutes=1)
		fecha_hora_str=datetime.datetime.strftime(hora, '%Y-%m-%d  %H:%M:%S')
		linea[2]=fecha_hora_str
		#print(linea[2])
		#time.sleep(20)
	
	linea_aux=(linea[2], linea[3], linea[4], linea[5], linea[6], linea[7], linea[8])
	listacsv.append(linea_aux)

#print(listacsv)
#time.sleep(20)

# crea .csv final de salida
df_final = pd.DataFrame(listacsv)
df_final.columns=['Fecha_Hora', 'Latitud', 'Longitud', 'Prof.', 'Mag.', 'Tipo_mag.', 'Analista']
salida='salida_collect.csv'
df_final.to_csv(salida)

# borra .csv temporal
remove('salida_collect_sort.csv')
remove('newcollect.txt')
os.rename('newcollect_final.txt', 'newcollect.txt')

# Carga dataframe df_final para crear .csv por analista en una nueva carpeta llamada analistas
# configura que si hay 1 letra de diferencia (o menos), se unen
DISTANCIA_MAXIMA = 1

df_final['Analista_Clean'] = df_final['Analista'].astype(str).str.strip().str.lower()
nombres_unicos = sorted(df_final['Analista_Clean'].unique(), key=len, reverse=True)

mapeo_unificado = {}
ya_asignados = set()

# distancia absoluta
for i, nombre in enumerate(nombres_unicos):
    if nombre in ya_asignados:
        continue
    
    # El primer nombre que encuentra de este grupo será el "nombre maestro"
    mapeo_unificado[nombre] = nombre
    ya_asignados.add(nombre)
    
    # Compara con el resto de nombres
    for j in range(i + 1, len(nombres_unicos)):
        otro_nombre = nombres_unicos[j]
        if otro_nombre in ya_asignados:
            continue
            
        # Calcula cuántos cambios hay entre un nombre y otro
        distancia = Levenshtein.distance(nombre, otro_nombre)
        
        if distancia <= DISTANCIA_MAXIMA:
            mapeo_unificado[otro_nombre] = nombre
            ya_asignados.add(otro_nombre)
            #print(f"Unificando: '{otro_nombre}' -> '{nombre}' (Caracteres diferentes: {distancia})")

# Aplica el mapeo al DataFrame
df_final['Analista_Final'] = df_final['Analista_Clean'].map(mapeo_unificado)

# Guarda archivos .csv por analistas en carpeta analistas
carpeta_destino = 'eventos'
if not os.path.exists(carpeta_destino):
    os.makedirs(carpeta_destino)
	
creados=0

for nombre_maestro, datos in df_final.groupby('Analista_Final'):
	nombre_archivo = f"{nombre_maestro.replace(' ', '_')}.csv"
	ruta_completa = os.path.join(carpeta_destino, nombre_archivo)

	# Guarda sin las columnas de proceso
	columnas_a_guardar = [c for c in datos.columns if c not in ['Analista_Clean', 'Analista_Final']]
	datos[columnas_a_guardar].to_csv(ruta_completa, index=False, encoding='utf-8-sig')

	creados+=1

if creados > 0:
	print(f"✅ archivos .csv de sismos por analista creados en carpeta", carpeta_destino)

"""
# solo crea .csv para cada analista o nombre distinto
carpeta_destino = 'analistas'
if not os.path.exists(carpeta_destino):
    os.makedirs(carpeta_destino)

# agregar columnas si se requiere a todos por igual
#df_final['Percibido'] = ''
#df_final['Est_leidas'] = ''
#df_final['Estruc_origen'] = ''
#df_final['Estruc_final'] = ''
#df_final['Est_agregadas'] = ''
#df_final['Actualizado web'] = ''
#df_final['Observaciones'] = ''
#df_final['Percibido'] = ''

# trata el atributo analista como minuscula siempre
for analista_orig, datos in df_final.groupby(df['Analista'].str.lower().str.strip()):
    
    # nombre_limpio será todo en minúsculas para el nombre del archivo
    nombre_limpio = analista_orig.replace(" ", "_")
    nombre_archivo = f'{nombre_limpio}.csv'
    
    ruta_completa = os.path.join(carpeta_destino, nombre_archivo)
    
    # guarda los datos
    datos.to_csv(ruta_completa, index=False, encoding='utf-8')
    #print(f"Creado {nombre_archivo} ({len(datos)} eventos)")
"""

#time.sleep(5)

#print("----------------------------------- Salida -----------------------------------")
#print("\nAnalizando datos...")  
#print('Total eventos:',numeventofinal)
print('eventos sin estructura:', sinestruc)
print('eventos con station0:', concero)
print('Archivos generados...')
print(archivo3.name)
print(archivo4.name)
print(archivo5.name)
print(salida)






