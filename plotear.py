from PIL import Image, ImageTk, ImageDraw, ImageGrab
import tkinter as tk
import json
import time
import sys, os
#from tkinter import messagebox
from tkinter import scrolledtext
import pandas as pd
import csv

# define ruta de mapas utilizados y directorio donde se encuenta el usuario al ejecutar el script plotear
# en este directorio deben estar los archivos .json que se generaron con anterioridad 
#path_perfil="/home/hriquelmez/Revision_Local/harzmapas/perfiles_seisan"
path_perfil="/home/hriquelmez/Desarrollo/harzmapas/perfiles_seisan"
# path mapas planta harz
#path_planta="/home/hriquelmez/Revision_Local/harzmapas/planta_2"
path_planta="/home/hriquelmez/Desarrollo/harzmapas/planta_2"
path_ejecucion=os.getcwd()

def crear_canvas(nuevo_ancho, nuevo_alto):
    # Crear la ventana principal
    ventana = tk.Tk()
    ventana.title("Perfil / Planta")

    # Crear el canvas perfil
    #canvas = tk.Canvas(ventana, width=900, height=800)
    canvas = tk.Canvas(ventana, width=nuevo_ancho, height=nuevo_alto)
    canvas.pack(side=tk.LEFT)

    # Crear el canvas para planta
    #canvas_planta = tk.Canvas(ventana, width=900, height=800)
    canvas_planta = tk.Canvas(ventana, width=nuevo_ancho, height=nuevo_alto)
    canvas_planta.pack(side=tk.RIGHT)
    return ventana, canvas, canvas_planta

def redimensionar_imagen(imagen_path, nuevo_ancho, nuevo_alto):
    imagen = Image.open(imagen_path)
    #imagen_planta = Image.open(imagen_planta_path)
    imagen_redimensionada = imagen.resize((nuevo_ancho, nuevo_alto), Image.LANCZOS)
    return ImageTk.PhotoImage(imagen_redimensionada)

def mostrar_imagen_en_canvas(canvas, imagen_tk):
    canvas.create_image(0, 0, anchor=tk.NW, image=imagen_tk)
    canvas.image = imagen_tk  # Mantener una referencia a la imagen

def geographic_to_canvas_planta(lat, lon, min_lat, max_lat, min_lon, max_lon, canvas_width, canvas_height):
    # Convierte coordenadas geográficas (latitud, longitud) a coordenadas de píxeles en un canvas.
    # Calcula la escala para latitud y longitud
    lat_scale = (canvas_height) / (max_lat - min_lat)
    lon_scale = (canvas_width) / (max_lon - min_lon)

    # Calcula las coordenadas x e y en el canvas
    x = (lon - min_lon) * lon_scale
    y = canvas_height - ((lat - min_lat) * lat_scale)  # Invertir y para la coordenada del canvas
    #veces_planta=veces_planta+1
    #print('veces en geographic_to_canvas_planta:',veces_planta)
    return x, y

def geographic_to_canvas_perfil(x, y, minY, maxY, minX, maxX, canvas_width, canvas_height):
    # Convierte coordenadas geográficas (latitud, profundidad) a coordenadas de píxeles en un canvas.
    # Calcula la escala para longitud y profundidad
    canvasX = ((x - minX) / (maxX - minX)) * canvas_width
    canvasY = canvas_height - ((y - minY) / (maxY - minY)) * canvas_height
    #print('veces en geographic_to_canvas_perfil:',veces_perfil)
    return canvasX, canvasY

def ploteando(archivo_plot, perfil_plot, planta_plot, fuente, percibidos):

    if (fuente == "eventquery"):
        if not os.path.exists("percibidos.txt"):
            # archivos de salida
            archivo_perc=open("percibidos.txt", "w")

            # cabeceras para cada archivo .txt de salida (Para plotear con google earth)
            archivo_perc.write("id fecha hora latitud longitud prof mag tipomag percibido\n")
        # podria ser necesario un else y borrar si existe el archivo txt
        #else:
        #    archivo_perc=open("percibidos.txt", "a")
    
    listaperci=[]
    #muestra por pantalla la fuente de datos a plotear (seisan/eventquery)
    #print('fuente datos:', fuente)

    # Define las coordenadas del mapa base

    # Para mapas perfiles (parametros del perfil a plotear)
    # Asigna valores para parametros del cuadrante base para canvas para mapa perfil
    minY = perfiles_seisan[perfil_plot]["minY"]
    maxY = perfiles_seisan[perfil_plot]["maxY"]
    minX = perfiles_seisan[perfil_plot]["minX"]
    maxX = perfiles_seisan[perfil_plot]["maxX"]

    # Para mapas planta (parametros del mapa planta a plotear)
    # Asigna valores para parametros del cuadrante base para canvas para mapa planta
    min_lat = plantas[planta_plot]["minY"]
    max_lat = plantas[planta_plot]["maxY"]
    min_lon = plantas[planta_plot]["minX"]
    max_lon = plantas[planta_plot]["maxX"]

    # Archvo que se va a plotear. Esto esta definido con anterioridad en el diccionario plotear
    nombre_del_archivo = path_ejecucion+"/"+archivo_plot
    #print("ploteado", nombre_del_archivo)

    percibidos=0
    total_eventos=0
    evento_percibido=[]

    with open(nombre_del_archivo) as contenido:
            eventos = json.load(contenido)
            for evento in eventos:

                #print('evento')
                #print(evento)

                #  Definir colores al plotear
                color="yellow"
                color2="red"
                
                # Coordenadas geográficas de un evento a plotear
                id = evento.get('id')
                fecha_hora = evento.get('fecha hora')
                lat_punto = float(evento.get('latitud'))
                lon_punto = float(evento.get('longitud'))
                if evento.get('prof')=='GUC':
                    print(evento)
                prof_punto = float(evento.get('prof'))*-1

                # Se invocaran a las funciones que transforman coordenadas geográficas a coordenadas del canvas para cada mapa
                
                # para perfil
                x, y = geographic_to_canvas_perfil(lon_punto, prof_punto, minY, maxY, minX, maxX, nuevo_ancho, nuevo_alto)
                
                # Si los datos a plotear no tienen mapa de perfil no plotea datos
                if perfil_plot[:10] != "sin_perfil":
                    #print(evento.get('percibido'))
                    if fuente=="eventquery" and evento.get('percibido')=="S":
                        color=color2
                        #print('id ',id,' Percibido')
                    else:
                        color=color
                                        
                    # Dibuja un círculo en el canvas (perfil) en las coordenadas calculadas
                    canvas.create_oval(x-5, y-5, x+5, y+5, fill=color, outline="black")
                    # Añade texto al mapa (opcional)
                    canvas.create_text(x, y - 10, text=id, fill="black")
                    #canvas.create_text(x, y - 10, text=f"({lat_punto:.2f}, {lon_punto:.2f})", fill="black")
                
                total_eventos=total_eventos+1
                
                if fuente=="eventquery" and evento.get('percibido')=="S":
                    color=color2
                    percibidos=percibidos+1
                    #print('id ',id,' Percibido')
                    #time.sleep(1)
                    # genera csv con eventos percibidos
                    evento_procesado = {
                        'id': id,
                        'fecha hora': fecha_hora,
                        'latitud': lat_punto,
                        'longitud': lon_punto,
                        'prof': prof_punto,
                        'magnitud': evento.get('magnitud'),
                        'tipo': evento.get('tipo'),
                        #'referencia': evento.get('referencia'),
                        'percibido': evento.get('percibido'),
                    }
                    #print(evento_procesado)
                    evento_percibido.append(evento_procesado)

                    # Abrir un archivo en modo de escritura ('w')
                    with open("percibidos.txt", "a") as archivo_perc:
                        # Concatenar los valores del diccionario con espacios y un salto de línea
                        linea_a_escribir = str(evento_procesado['id']) + ' ' + \
                                        str(evento_procesado['fecha hora']) + ' ' + \
                                        str(evento_procesado['latitud']) + ' ' + \
                                        str(evento_procesado['longitud']) + ' ' + \
                                        str(evento_procesado['prof']) + ' ' + \
                                        str(evento_procesado['magnitud']) + ' ' + \
                                        str(evento_procesado['tipo']) + ' ' + \
                                        str(evento_procesado['percibido']) + "\n"

                        # Escribir la línea en el archivo
                        archivo_perc.write(linea_a_escribir)

                    color=color

                # para planta
                x, y = geographic_to_canvas_planta(lat_punto, lon_punto, min_lat, max_lat, min_lon, max_lon, nuevo_ancho, nuevo_alto)
                # Dibuja un círculo en el canvas en las coordenadas calculadas
                canvas_planta.create_oval(x-5, y-5, x+5, y+5, fill=color, outline="black")
 
                # Añade texto al mapa (opcional)
                canvas_planta.create_text(x, y - 10, text=id, fill="black")
                #canvas.create_text(x, y - 10, text=f"({lat_punto:.2f}, {lon_punto:.2f})", fill="black")

            """
            # dibujar punto volcan
            if archivo_elegido=="file_b.json":
                lat_volcan=float("-19.16")
                lon_volcan=float("-68.82")
                x, y = geographic_to_canvas_planta(lat_volcan, lon_volcan, min_lat, max_lat, min_lon, max_lon, nuevo_ancho, nuevo_alto) 
                canvas_planta.create_oval(x-4, y-4, x+4, y+4, fill="blue", outline="black")
                print("ploteo volcan")
                print("en latitud ", lat_volcan)
                print("en longitud ", lon_volcan)
                #time.sleep(20)
            """

    return canvas, canvas_planta, percibidos, total_eventos

def guarda_canvas_png(canvas, nombre_archivo_imagen):
    """
    Guarda el contenido de un canvas de Tkinter como un archivo PNG.
    """
    try:
        # Crea un archivo Postscript (vectorial) a partir del canvas
        canvas.postscript(file=nombre_archivo_imagen + '.ps', colormode='color')
        
        # Abre el archivo Postscript con Pillow
        img = Image.open(nombre_archivo_imagen + '.ps')
        
        # Guarda la imagen en formato PNG
        img.save(nombre_archivo_imagen)
        
        # Opcional: elimina el archivo Postscript temporal
        import os
        os.remove(nombre_archivo_imagen + '.ps')
        
        print(f"Canvas guardado con éxito como {nombre_archivo_imagen}")
    except Exception as e:
        print(f"Ocurrió un error: {e}")
    return    

def mostrar_json_en_popup(ruta_archivo, nombre, percibidos, total_eventos, fuente):
    """
    Lee un archivo JSON y muestra su contenido en una ventana pop-up con scroll.
    """
    try:
        with open(ruta_archivo, 'r', encoding='utf-8') as archivo:
            # Carga el contenido del archivo JSON
            contenido_json = json.load(archivo)
            # Formatea el JSON para una mejor visualización (indentación)
            texto_formateado = json.dumps(contenido_json, indent=4)
    except FileNotFoundError:
        tk.messagebox.showerror("Error", f"El archivo '{ruta_archivo}' no se encontró.")
        return
    except json.JSONDecodeError:
        tk.messagebox.showerror("Error", "El archivo no es un JSON válido.")
        return
    except Exception as e:
        tk.messagebox.showerror("Error", f"Ocurrió un error: {e}")
        return

    # Crea una ventana de nivel superior (el pop-up) que muestra el contenido del archivo que se esta ploteando
    archivo_popup = tk.Toplevel()
    if fuente == "eventquery":
        archivo_popup.title(nombre + ' ( fuente ' + fuente + ' - ' + str(percibidos) + ' percibidos de ' + str(total_eventos) + ' eventos ploteados)')
    else:
        archivo_popup.title(nombre + ' ( fuente ' + fuente + ' - ' + str(total_eventos) + ' eventos ploteados)')
        
    archivo_popup.geometry("700x400") # Puedes ajustar el tamaño inicial de la ventana

    # Crea un widget ScrolledText (combina un widget Text y una Scrollbar)
    campo_texto = scrolledtext.ScrolledText(archivo_popup, wrap=tk.WORD, font=("Consolas", 10))
    campo_texto.pack(expand=True, fill="both")

    # Inserta el texto formateado en el widget
    campo_texto.insert(tk.INSERT, texto_formateado)
    campo_texto.config(state=tk.DISABLED) # Evita que el usuario edite el texto
    return

# Diccionario con perfiles de seisan
# min y max en X corresponden a longitudes
# min y  max en Y corresponden a profundidades
perfiles_seisan = {
    "Perf_18.5_-74.280000_-66.500000_250_sm.png" : {
        "minX" : -74.280000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_19.0_-73.700000_-66.500000_250_sm.png" : {
        "minX" : -73.700000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_20.0_-73.120000_-66.500000_250_sm.png" : {
        "minX" : -73.120000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_21.0_-73.920000_-66.500000_250_sm.png" : {
        "minX" : -73.920000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_22.0_-72.960000_-66.500000_250_sm.png" : {
        "minX" : -72.960000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_23.0_-73.060000_-66.500000_250_sm.png" : {
        "minX" : -73.060000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_24.0_-73.120000_-66.500000_250_sm.png" : {
        "minX" : -73.120000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_25.0_-73.140000_-66.500000_250_sm.png" : {
        "minX" : -73.140000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_26.0_-73.260000_-66.500000_250_sm.png" : {
        "minX" : -73.260000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_27.0_-73.420000_-66.500000_250_sm.png" : {
        "minX" : -73.420000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_28.0_-73.640000_-66.500000_250_sm.png" : {
        "minX" : -73.640000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_29.0_-73.900000_-66.500000_250_sm.png" : {
        "minX" : -73.900000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_30.0_-74.100000_-66.500000_250_sm.png" : {
        "minX" : -74.100000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_31.0_-74.240000_-66.500000_250_sm.png" : {
        "minX" : -74.240000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_32.0_-74.420000_-66.500000_250_sm.png" : {
        "minX" : -74.420000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_33.0_-74.640000_-66.500000_250_sm.png" : {
        "minX" : -74.640000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_34.0_-75.000000_-66.500000_250_sm.png" : {
        "minX" : -75.000000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_35.0_-75.440000_-66.500000_250_sm.png" : {
        "minX" : -75.440000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_36.0_-75.900000_-66.500000_250_sm.png" : {
        "minX" : -75.900000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_37.0_-76.200000_-66.500000_250_sm.png" : {
        "minX" : -76.200000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_38.0_-76.420000_-66.500000_250_sm.png" : {
        "minX" : -76.420000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_39.0_-76.660000_-66.500000_250_sm.png" : {
        "minX" : -76.660000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_40.0_-76.840000_-66.500000_250_sm.png" : {
        "minX" : -76.840000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_41.0_-77.020000_-66.500000_250_sm.png" : {
        "minX" : -77.020000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_42.0_-77.240000_-66.500000_250_sm.png" : {
        "minX" : -77.240000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_43.0_-77.300000_-66.500000_250_sm.png" : {
        "minX" : -77.300000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_44.0_-77.380000_-66.500000_250_sm.png" : {
        "minX" : -77.380000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "Perf_45.0_-77.380000_-66.500000_250_sm.png" : {
        "minX" : -77.380000,
        "maxX" : -66.500000,
        "minY" : -250,
        "maxY" : 15
    },
    "sin_perfil_norte.jpg" : {
        "minX" : -75.0,#da lo mismo los valores ya que no se plotearan (-75.0_-66.0_-22.0_-14.0 planta)
        "maxX" : -66.0,
        "minY" : -250,
        "maxY" : 15
    },
    "sin_perfil_sur1.jpg" : {
        "minX" : -80.0,#da lo mismo los valores ya que no se plotearan (-80.0_-57.0_-56.0_-44.0.png planta)
        "maxX" : -57.0,
        "minY" : -250,
        "maxY" : 15
    },
    "sin_perfil_sur2.jpg" : {
        "minX" : -79.0,#da lo mismo los valores ya que no se plotearan (-79.0_-53.0_-65.0_-55.0.png planta)
        "maxX" : -53.0,
        "minY" : -250,
        "maxY" : 15
    },
}

# Diccionario con mapas planta perfiles segun nombre de archivo .png de harz
# min y max en X corresponden a longitudes
# min y max en Y corresponden a latitudes
plantas = {
    "-74.0_-65.0_-24.0_-16.0.png" : {
        "minX" : -74.0,
        "maxX" : -65.0,
        "minY" : -24.0,
        "maxY" : -16.0
    },
    "-74.0_-65.0_-28.0_-20.0.png" : {
        "minX" : -74.0,
        "maxX" : -65.0,
        "minY" : -28.0,
        "maxY" : -20.0
    },
    "-76.0_-67.0_-31.0_-24.0.png" : {
        "minX" : -76.0,
        "maxX" : -67.0,
        "minY" : -31.0,
        "maxY" : -24.0
    },
    "-76.0_-67.0_-36.0_-28.0.png" : {
        "minX" : -76.0,
        "maxX" : -67.0,
        "minY" : -36.0,
        "maxY" : -28.0
    },
    "-77.0_-68.0_-40.0_-32.0.png" : {
        "minX" : -77.0,
        "maxX" : -68.0,
        "minY" : -40.0,
        "maxY" : -32.0
    },
    "-80.0_-68.0_-44.0_-36.0.png" : {
        "minX" : -80.0,
        "maxX" : -68.0,
        "minY" : -44.0,
        "maxY" : -36.0
    },
    "-80.0_-68.0_-47.0_-39.0.png" : {
        "minX" : -80.0,
        "maxX" : -68.0,
        "minY" : -47.0,
        "maxY" : -39.0
    },
    "-80.0_-68.0_-48.0_-41.0.png" : {
        "minX" : -80.0,
        "maxX" : -68.0,
        "minY" : -48.0,
        "maxY" : -41.0
    },
    "-80.0_-68.0_-51.0_-45.0.png" : {
        "minX" : -80.0,
        "maxX" : -68.0,
        "minY" : -51.0,
        "maxY" : -45.0
    },
    "-79.0_-63.0_-55.0_-49.0.png" : {
        "minX" : -79.0,
        "maxX" : -63.0,
        "minY" : -55.0,
        "maxY" : -49.0
    },
    "-78.0_-63.0_-60.0_-54.0.png" : {
        "minX" : -78.0,
        "maxX" : -63.0,
        "minY" : -60.0,
        "maxY" : -54.0
    },
    "-75.0_-66.0_-22.0_-14.0.png" : {
        "minX" : -75.0,
        "maxX" : -66.0,
        "minY" : -22.0,
        "maxY" : -14.0
    },
    "-80.0_-57.0_-56.0_-44.0.png" : {
        "minX" : -80.0,
        "maxX" : -57.0,
        "minY" : -56.0,
        "maxY" : -44.0
    },
    "-79.0_-53.0_-65.0_-55.0.png" : {
        "minX" : -79.0,
        "maxX" : -53.0,
        "minY" : -65.0,
        "maxY" : -55.0
    },
}

# Diccionario que define con que plotear segun el archivo de datos .json con los mapas de planta de harz
plotear = {
    "file_a.json" : {
        "archivo" : "sin_perfil_norte",
        "perfil"  : "sin_perfil_norte.jpg",
        "planta"  : "-75.0_-66.0_-22.0_-14.0.png"
    },
    "file_b1.json" : {
        "archivo" : "Perfil18",
        "perfil"  : "Perf_18.5_-74.280000_-66.500000_250_sm.png",
        "planta"  : "-74.0_-65.0_-24.0_-16.0.png"
    },
    "file_b2.json" : {
        "archivo" : "Perfil20",
        "perfil"  : "Perf_20.0_-73.120000_-66.500000_250_sm.png",
        "planta"  : "-74.0_-65.0_-24.0_-16.0.png"
    },
    "file_c.json" : {
        "archivo" : "Perfil25",
        "perfil"  : "Perf_25.0_-73.140000_-66.500000_250_sm.png",
        "planta"  : "-74.0_-65.0_-28.0_-20.0.png"
    },
    "file_d.json" : {
        "archivo" : "Perfil28",
        "perfil"  : "Perf_28.0_-73.640000_-66.500000_250_sm.png",
        "planta"  : "-76.0_-67.0_-31.0_-24.0.png"
    },
    "file_e.json" : {
        "archivo" : "Perfil33",
        "perfil"  : "Perf_33.0_-74.640000_-66.500000_250_sm.png",
        "planta"  : "-76.0_-67.0_-36.0_-28.0.png"
    },
    "file_f.json" : {
        "archivo" : "Perfil37",
        "perfil"  : "Perf_37.0_-76.200000_-66.500000_250_sm.png",
        "planta"  : "-77.0_-68.0_-40.0_-32.0.png"
    },
    "file_g.json" : {
        "archivo" : "Perfil41",
        "perfil"  : "Perf_41.0_-77.020000_-66.500000_250_sm.png",
        "planta"  : "-80.0_-68.0_-44.0_-36.0.png"
    },
    "file_h.json" : {
        "archivo" : "Perfil43",
        "perfil"  : "Perf_43.0_-77.300000_-66.500000_250_sm.png",
        "planta"  : "-80.0_-68.0_-47.0_-39.0.png"
    },
    "file_i.json" : {
        "archivo" : "Perfil45",
        "perfil"  : "Perf_45.0_-77.380000_-66.500000_250_sm.png",
        "planta"  : "-80.0_-68.0_-48.0_-41.0.png"
    },
    "file_j.json" : {
        "archivo" : "sin_perfil_sur1",
        "perfil"  : "sin_perfil_sur1.jpg",
        "planta"  : "-80.0_-57.0_-56.0_-44.0.png"
    },
    "file_k.json" : {
        "archivo" : "sin_perfil_sur2",
        "perfil"  : "sin_perfil_sur2.jpg",
        "planta"  : "-79.0_-53.0_-65.0_-55.0.png"
    },
}

"""
# Diccionario que define con que plotear segun el archivo de datos .json con los mapas de planta de tati
plotear = {
    "archivo1.json" : {
        "archivo" : "Perfil18",
        "perfil"  : "Perf_18.5_-74.280000_-66.500000_250_sm.png",
        "planta"  : "-74.0_-65.5_-24.5_-16.0.png"
    },
    "archivo2.json" : {
        "archivo" : "Perfil25",
        "perfil"  : "Perf_25.0_-73.140000_-66.500000_250_sm.png",
        "planta"  : "-74.0_-65.5_-24.5_-16.0.png"
    },
    "archivo3.json" : {
        "archivo" : "Perfil28",
        "perfil"  : "Perf_28.0_-73.640000_-66.500000_250_sm.png",
        "planta"  : "-76.0_-67.5_-32.5_-24.0.png"
    },
    "archivo4.json" : {
        "archivo" : "Perfil33",
        "perfil"  : "Perf_33.0_-74.640000_-66.500000_250_sm.png",
        "planta"  : "-76.0_-67.5_-32.5_-24.0.png"
    },
    "archivo5.json" : {
        "archivo" : "Perfil37",
        "perfil"  : "Perf_37.0_-76.200000_-66.500000_250_sm.png",
        "planta"  : "-77.0_-69.0_-40.5_-32.0.png"
    },
    "archivo6.json" : {
        "archivo" : "Perfil41",
        "perfil"  : "Perf_41.0_-77.020000_-66.500000_250_sm.png",
        "planta"  : "-79.5_-70.0_-49.0_-39.5.png"
    },
    "archivo7.json" : {
        "archivo" : "Perfil43",
        "perfil"  : "Perf_43.0_-77.300000_-66.500000_250_sm.png",
        "planta"  : "-79.5_-70.0_-49.0_-39.5.png"
    },
    "archivo8.json" : {
        "archivo" : "Perfil45",
        "perfil"  : "Perf_45.0_-77.380000_-66.500000_250_sm.png",
        "planta"  : "-79.5_-70.0_-49.0_-39.5.png"
    },
}
"""

"""
# Cargar en una lista los nombres de los archivos json que se generan en la carpeta donde se ejecuta el script
lista = [file for file in os.listdir() if file[-4:] == "json"]
listajson=sorted(lista)
largo=len(listajson)
print('lista archivos json')
print(listajson)
#print('largo lista:',largo)
"""
# argumento enviado al ejecutar el script para plotear (archivo .json)
archivo=sys.argv[1]
fuente=sys.argv[2]
percibidos=0

# resolucion para cada imagen y para el canvas
nuevo_ancho = 800
nuevo_alto = 800
ventana, canvas, canvas_planta=crear_canvas(nuevo_ancho, nuevo_alto)

perfil_elegido=plotear[archivo]["perfil"]
planta_elegido=plotear[archivo]["planta"]
archivo_elegido=archivo

# muestra por pantalla perfil y planta ploteados
#print('ploteado perfil', perfil_elegido)
#print('ploteado planta', planta_elegido)
#print('ploteado archvo', archivo_elegido)

try:
    
    # Mapas perfiles (ruta al mapa del perfil a utilizar)
    imagen_perfil_path = path_perfil+"/sin_margen/"+perfil_elegido # ruta a la imagen
    
    # Mapas planta (ruta al mapa de planta a utilizar)
    imagen_planta_path = path_planta+"/"+planta_elegido  # ruta a la imagen

except FileNotFoundError:
    print("Error: No se encontró la imagen.")
    exit()
except Exception as e:
    print(f"Error al cargar la imagen: {e}")
    exit()

# Redimensionar la imagen y obtener la versión compatible con Tkinter
imagen_tk = redimensionar_imagen(imagen_perfil_path, nuevo_ancho, nuevo_alto)
imagen_tk_planta = redimensionar_imagen(imagen_planta_path, nuevo_ancho, nuevo_alto)

# Mostrar la imagen en el canvas
mostrar_imagen_en_canvas(canvas, imagen_tk)
canvas.create_text(250, nuevo_alto-50, text=perfil_elegido[:-4], fill="black", font=("Arial", 16))
canvas.create_text(100, 20, text='Ploteando '+ archivo_elegido, fill="blue", font=("Arial", 12))
mostrar_imagen_en_canvas(canvas_planta, imagen_tk_planta)
canvas_planta.create_text(165, nuevo_alto-50, text=planta_elegido[:-4], fill="black", font=("Arial", 16))

#canvas.create_text(250, 150, text=archivo_elegido, fill="black", font=("Arial", 12))
canvas, canvas_planta, percibidos, total_eventos = ploteando(archivo_elegido, perfil_elegido, planta_elegido, fuente, percibidos)
#if fuente=="eventquery":
#    print('Percibidos:', percibidos)

#guarda_canvas_png(canvas, archivo_elegido[:8]+"_perfil")
#guarda_canvas_png(canvas_planta, archivo_elegido[:8]+"planta")

#guarda_canvas_png(canvas)
#guarda_canvas_png(canvas_planta)

mostrar_json_en_popup(path_ejecucion+'/'+archivo_elegido, archivo_elegido, percibidos, total_eventos, fuente)

# Iniciar el bucle principal de Tkinter
#time.sleep(5)
ventana.mainloop()

#valor_a_devolver = mostrar_json_en_popup(ruta_archivo, nombre, percibidos, total_eventos)
#sys.exit(valor_a_devolver)
