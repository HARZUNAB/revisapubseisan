import datetime
import sys
import pytz
import csv 

if len(sys.argv) < 3:
    print("Uso: python3 proc_query.py archivo_entrada.csv archivo_salida.dat")
    sys.exit(1)

# LEE Y ORDENAR EN MEMORIA (Usando Python nativo para no alterar strings)
datos_ordenados = []
with open(sys.argv[1], 'r') as csv_file:
    csvreader = csv.reader(csv_file)
    encabezado = next(csvreader, None) # Guardamos el encabezado
    
    # Cargamos todas las filas en una lista
    filas = list(csvreader)
    
    # Ordena la lista basándonos en la primera columna (fecha)
    # Usa datetime.fromisoformat para que el orden sea cronológico real
    try:
        filas.sort(key=lambda x: datetime.datetime.fromisoformat(x[0].replace('Z', '+00:00')))
        datos_ordenados = filas
    except Exception as e:
        print(f"⚠️ No se pudo ordenar cronológicamente, se usará orden original. Error: {e}")
        datos_ordenados = filas

# PROCESAMIENTO ORIGINAL (Sin cambios en la lógica de escritura)
with open(sys.argv[2], 'w') as fh:
    for row in datos_ordenados:
        try:
            # Esta parte es EXACTAMENTE igual a tu versión original
            fecha_str = row[0].replace('Z', '+00:00')
            fecha = datetime.datetime.fromisoformat(fecha_str)

            fecha_fmt = fecha.astimezone(pytz.UTC).strftime("%Y-%m-%d  %H:%M:%S") 
            
            latitud = float(row[1])
            longitud = float(row[2])
            prof = float(row[3])
            mag = float(row[4])
            tipo_mag = row[5]
            ref = row[6]
            perc = "S" if row[7] == "t" else "N"
            
            fh.write("%s\t%.3f\t%.3f\t%.1f\t%.1f\t%s\t%s\t%s\n" % (
                fecha_fmt, longitud, latitud, prof, mag, tipo_mag, perc, ref 
            ))
        except (ValueError, IndexError) as e:
            print(f"Error procesando fila: {row}. Error: {e}")
            continue