import datetime
import time
import csv
import pandas as pd
import sys, os
from os import remove
import operator
import pandas as pandasForSortingCSV

sismos={}
lista=[]
newlista=[]
nuevalista=[]
sismolista=[]
linealista=''

#time.sleep(50)

# genera txt agregando un cero a dias menores a 10 y separa el dia del mes
archivo=open("excluidos.txt")
archivo1=open("excluidos_tmp_1.txt", "w")
revisar=open("revisar.txt", "w")

for linea in archivo:
	sismo=linea.split()
	largolista=len(sismo)

	#print(sismo)
	

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

	#agrega un cero antes si el elemento es menor a 10
	if len(linealista_aux[2])==1:
		linealista_aux[2]='0'+linealista_aux[2]
		nuevalinea=''
		for caracter in linealista_aux:
			nuevalinea=nuevalinea+caracter+' '
		linealista=nuevalinea
	if len(linealista_aux[3])==1:
		linealista_aux[3]='0'+linealista_aux[3]
		nuevalinea=''
		for caracter in linealista_aux:
			nuevalinea=nuevalinea+caracter+' '
		linealista=nuevalinea
	if len(linealista_aux[4])==1:
		linealista_aux[4]='0'+linealista_aux[4]
		i=0
		nuevalinea=''
		for caracter in linealista_aux:
			if i==3:
				nuevalinea=nuevalinea+caracter
			else:
				nuevalinea=nuevalinea+caracter+' '
			i=i+1
		linealista=nuevalinea

	sismoaux=linea.split()
	#print(sismoaux)

	# guarda en revisar.txt sfile con horas erroneas y no los guarda en excluidos
	horamala=''
	#print(sismoaux[2][:2])
	if int(sismoaux[2][:2]) > 23:
		horamala='s'
	else:
		horamala='n'
	#time.sleep(1)
	if horamala=='n':
		linealista=linealista[:-1]
		archivo1.write(linealista+"\n")
		linealista=''
	else:
		revisar.write(linealista+"\n")

# crea archivo salida excluidos_collect.csv
archivo1=open("excluidos_tmp_1.txt")

listacsv=[]
numeventofinal=0

for linea in archivo1:

	# revisa si le faltan los segundos a linea de solucion
	# si es asi agrega estos segundos y concatena el resto de la linea
	if linea[16].isalpha() or linea[17].isalpha():
		#print(linea)
		#print(linea[16],' / ', linea[17])
		revisar.write(linea+"\n")
		lineaaux=linea[:15]+" 00 "+linea[16:len(linea)]
		#print(lineaaux)
		linea=lineaaux
		#print(linea)

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
	analista=sismo[len(sismo)-1]
	
	if horamala=='n':
		sismolista=fecha_hora, analista
		listacsv.append(sismolista)

df = pd.DataFrame(listacsv)
df.columns=['Fecha_Hora', 'Analista']
salida='excluidos_tmp.csv'
df.to_csv(salida)

# Asigna datos del csv de origen
salida = pandasForSortingCSV.read_csv(salida)

# Ordena datos por fecha
salida.sort_values(["Fecha_Hora"], 
                    axis=0,
                    ascending=[True], 
                    inplace=True)
  
# Crea archivo .csv ordenado
salida_csv = 'excluidos_tmp_sort.csv'
salida.to_csv(salida_csv)

# borra .txt y .csv temporales
remove('excluidos.txt')
remove('excluidostmp1.txt')
os.rename('excluidos_tmp_1.txt', 'excluidos.txt')
remove('excluidos_tmp.csv')

csvData = open(salida_csv, encoding='utf-8')
csvreader = csv.reader(csvData)

# saltar el encabezado
next(csvreader,None)

# Creando lista con datos extraidos del .csv ordenado
listacsv=[]
for linea in csvreader:
	# verifica si hora queda con segundo 60
	if linea[2][-2:]=='60':
		linea[2]=linea[2][0:18]+'00'
		# se le suma 1 minuto a la hora
		hora=datetime.datetime.strptime(linea[2], '%Y-%m-%d  %H:%M:%S')
		hora=hora+datetime.timedelta(minutes=1)
		fecha_hora_str=datetime.datetime.strftime(hora, '%Y-%m-%d  %H:%M:%S')
		linea[2]=fecha_hora_str
	
	linea_aux=(linea[2], linea[3])
	listacsv.append(linea_aux)

# crea .csv final de salida
df = pd.DataFrame(listacsv)
df.columns=['Fecha_Hora', 'Analista']
salida='excluidos.csv'
df.to_csv(salida)

# borra .csv temporal
remove('excluidos_tmp_sort.csv')

