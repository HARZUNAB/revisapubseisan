import csv
import json
import subprocess
import time
import pandas as pd
import sys, os

#print('***** Procesando archvo .csv *****')

#print('archivo a procesar')
#print(sys.argv[1])
#print(sys.argv[2])

#def procesar_csv(archivo_csv, archivo_json):
def procesar_csv(archivo_csv):

    file_a_json='file_a.json'
    file_b1_json='file_b1.json'
    file_b2_json='file_b2.json'
    file_c_json='file_c.json'
    file_d_json='file_d.json'
    file_e_json='file_e.json'
    file_f_json='file_f.json'
    file_g_json='file_g.json'
    file_h_json='file_h.json'
    file_i_json='file_i.json'
    file_j_json='file_j.json'
    file_k_json='file_k.json'

    p18p19=[]
    p20p21=[]
    p22p23p24p25=[]
    p26p27p28p29=[]
    p30p31p32p33=[]
    p34p35p36p37=[]
    p38p39p40p41=[]
    p42p43=[]
    p44p45=[]
    noplotnor=[]
    noplotsur1=[]
    noplotsur2=[]

    p18p19_total=0
    p20p21_total=0
    p22p23p24p25_total=0
    p26p27p28p29_total=0
    p30p31p32p33_total=0
    p34p35p36p37_total=0
    p38p39p40p41_total=0
    p42p43_total=0
    p44p45_total=0
    noplotnor_total=0
    noplotsur1_total=0
    noplotsur2_total=0

    total_eventos=0
    with open(archivo_csv, 'r', newline='') as csvfile:
        lector_csv = csv.reader(csvfile)
        next(lector_csv)  # Omitir encabezado si existe
        for fila in lector_csv:
            # Procesa cada fila
            # Si el archivo procesado proviene de seisan
            if sys.argv[2] == "seisan":
                fila_procesada = {
                    'id': int(fila[0])+1,
                    'fecha hora': fila[1],
                    'latitud': fila[2],
                    'longitud': fila[3],
                    'prof': fila[4],
                    'magnitud': fila[5],
                    'tipo': fila[6],
                    'analista': fila[7],
                }
            else:
                # Si el archivo procesado proviene de eventquery
                fila_procesada = {
                    'id': int(fila[0])+1,
                    'fecha hora': fila[1],
                    'latitud': fila[2],
                    'longitud': fila[3],
                    'prof': fila[4],
                    'magnitud': fila[5],
                    'tipo': fila[6],
                    'percibido':fila[8],
                }
    
            # separa eventos en distintos archivos segun grupo de latitudes

            # para eventos donde no existen perfiles
            if float(fila[2]) > float(-18.000) or float(fila[2]) < float(-45.000):
                if float(fila[2]) > float(-18.000):
                    noplotnor.append(fila_procesada)
                    noplotnor_total=noplotnor_total+1
                else:
                    if float(fila[2]) < float(-55.000):
                        noplotsur2.append(fila_procesada)
                        noplotsur2_total=noplotsur2_total+1
                    else:
                        noplotsur1.append(fila_procesada)
                        noplotsur1_total=noplotsur1_total+1

            # para eventos donde si existen perfiles
            if float(fila[2]) <= float(-18.000) and float(fila[2]) >= float(-19.999):
                p18p19.append(fila_procesada)
                p18p19_total=p18p19_total+1
            if float(fila[2]) <= float(-20.000) and float(fila[2]) >= float(-21.999):
                p20p21.append(fila_procesada)
                p20p21_total=p20p21_total+1
            if float(fila[2]) <= float(-22.000) and float(fila[2]) >= float(-25.999):
                p22p23p24p25.append(fila_procesada)
                p22p23p24p25_total=p22p23p24p25_total+1
            if float(fila[2]) <= float(-26.000) and float(fila[2]) >= float(-29.999):
                p26p27p28p29.append(fila_procesada)
                p26p27p28p29_total=p26p27p28p29_total+1
            if float(fila[2]) <= float(-30.000) and float(fila[2]) >= float(-33.999):
                p30p31p32p33.append(fila_procesada)
                p30p31p32p33_total=p30p31p32p33_total+1
            if float(fila[2]) <= float(-34.000) and float(fila[2]) >= float(-37.999):
                p34p35p36p37.append(fila_procesada)
                p34p35p36p37_total=p34p35p36p37_total+1
            if float(fila[2]) <= float(-38.000) and float(fila[2]) >= float(-41.999):
                p38p39p40p41.append(fila_procesada)
                p38p39p40p41_total=p38p39p40p41_total+1
            if float(fila[2]) <= float(-42.000) and float(fila[2]) >= float(-43.999):
                p42p43.append(fila_procesada)
                p42p43_total=p42p43_total+1
            if float(fila[2]) <= float(-44.000) and float(fila[2]) >= float(-44.999):
                p44p45.append(fila_procesada)
                p44p45_total=p44p45_total+1

    # genera archivos json que podran ser ploteados
    with open(file_a_json, 'w') as jsonfile:
        json.dump(noplotnor, jsonfile, indent=4)
    with open(file_b1_json, 'w') as jsonfile:
        json.dump(p18p19, jsonfile, indent=4)
    with open(file_b2_json, 'w') as jsonfile:
        json.dump(p20p21, jsonfile, indent=4)
    with open(file_c_json, 'w') as jsonfile:
        json.dump(p22p23p24p25, jsonfile, indent=4)
    with open(file_d_json, 'w') as jsonfile:
        json.dump(p26p27p28p29, jsonfile, indent=4)
    with open(file_e_json, 'w') as jsonfile:
        json.dump(p30p31p32p33, jsonfile, indent=4)
    with open(file_f_json, 'w') as jsonfile:
        json.dump(p34p35p36p37, jsonfile, indent=4)
    with open(file_g_json, 'w') as jsonfile:
        json.dump(p38p39p40p41, jsonfile, indent=4)
    with open(file_h_json, 'w') as jsonfile:
        json.dump(p42p43, jsonfile, indent=4)
    with open(file_i_json, 'w') as jsonfile:
        json.dump(p44p45, jsonfile, indent=4)
    with open(file_j_json, 'w') as jsonfile:
        json.dump(noplotsur1, jsonfile, indent=4)
    with open(file_k_json, 'w') as jsonfile:
        json.dump(noplotsur2, jsonfile, indent=4)

    # genera csv con eventos fuera de rango en latitud hacia el norte (-18) y sur (-45)
    if noplotnor:
        df1 = pd.DataFrame(noplotnor)
        if sys.argv[2] == "seisan":
            df1.columns=['Id','Fecha_Hora', 'Latitud', 'Longitud', 'Prof.', 'Mag.', 'Tipo_mag.', 'Analista']
        else:
            df1.columns=['Id','Fecha_Hora', 'Latitud', 'Longitud', 'Prof.', 'Mag.', 'Tipo_mag.', 'Percibido']
        
        salida1='noplotnor.csv'
        df1.to_csv(salida1)

    if noplotsur1:
        df2 = pd.DataFrame(noplotsur1)
        if sys.argv[2] == "seisan":
            df2.columns=['Id','Fecha_Hora', 'Latitud', 'Longitud', 'Prof.', 'Mag.', 'Tipo_mag.', 'Analista']
        else:
            df2.columns=['Id','Fecha_Hora', 'Latitud', 'Longitud', 'Prof.', 'Mag.', 'Tipo_mag.', 'Percibido']

        salida2='noplotsur1.csv'
        df2.to_csv(salida2)
        
    if noplotsur2:
        df3 = pd.DataFrame(noplotsur2)
        if sys.argv[2] == "seisan":
            df3.columns=['Id','Fecha_Hora', 'Latitud', 'Longitud', 'Prof.', 'Mag.', 'Tipo_mag.', 'Analista']
        else:
            df3.columns=['Id','Fecha_Hora', 'Latitud', 'Longitud', 'Prof.', 'Mag.', 'Tipo_mag.', 'Percibido']

        salida3='noplotsur2.csv'
        df3.to_csv(salida3)

    total_eventos=p18p19_total+p20p21_total+p22p23p24p25_total+p26p27p28p29_total+p30p31p32p33_total+p34p35p36p37_total+p38p39p40p41_total+p42p43_total+p44p45_total
    print('Eventos a plotear con perfil:', total_eventos)
    if not noplotnor or not noplotsur1 or not noplotsur2:
        if not noplotnor and (noplotsur1 and noplotsur2):
            print('Eventos sin perfil:', + noplotsur1_total + noplotsur2_total, '(',salida2,'/',salida3,')')
        if not noplotsur1 and (noplotnor and noplotsur2):
            print('Eventos sin perfil:', + noplotnor_total + noplotsur2_total, '(',salida1,'/',salida3,')')
        if not noplotsur2 and (noplotnor and noplotsur1):
            print('Eventos sin perfil:', + noplotnor_total + noplotsur1_total, '(',salida1,'/',salida2,')')

    else:
        print('Eventos sin perfil:', noplotnor_total + noplotsur1_total + noplotsur2_total, '(',salida1,'/',salida2,'/',salida3,')')

    return total_eventos, noplotsur1_total+noplotsur2_total+noplotnor_total

def recorrer_json(nombre_archivo):
    #Recorre un archivo JSON y muestra sus elementos.
    try:
        with open(nombre_archivo, 'r') as archivo:
            datos = json.load(archivo)

            if isinstance(datos, dict):
                for clave, valor in datos.items():
                    print(f"Clave: {clave}, Valor: {valor}")
                    #time.sleep(2)
            elif isinstance(datos, list):
                for elemento in datos:
                    print(elemento)
                    #time.sleep(2)
            else:
                print("El archivo JSON no contiene un diccionario ni una lista.")

    except FileNotFoundError:
        print(f"Error: El archivo '{nombre_archivo}' no fue encontrado.")
    except json.JSONDecodeError:
        print(f"Error: El archivo '{nombre_archivo}' no contiene un JSON válido.")
    except Exception as e:
        print(f"Ocurrió un error: {e}")

def accede_datos_json(nombre_archivo):
    with open(nombre_archivo) as contenido:
        eventos = json.load(contenido)
        for evento in eventos:
            print(evento.get('id'))

#total_eventos_proc, noploteados=procesar_csv('salida_collect.csv')
total_eventos_proc, noploteados=procesar_csv(sys.argv[1])

#nombre_del_archivo = 'salida_collect.json'
#recorrer_json(nombre_del_archivo)

#accede_datos_json(nombre_del_archivo)

print('Total eventos :', total_eventos_proc+noploteados)
print('Archivos .json generados...')



