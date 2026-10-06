#!/usr/bin/env python3
"""
descargas.py
============
Todo lo que la app deja escribir en disco para que uno se lo lleve.

Centraliza las descargas en un solo lugar para que las cuatro vistas con
tabla (los dos listados de no actualizados, los no publicados y los repetidos)
más los paneles no repitan la misma mecánica: preguntar el formato, construir un
nombre que no pise el anterior, escribir con el BOM que necesita Excel y avisar
dónde quedó.

Por qué una carpeta propia y no informes/ o listados/: lo que uno descarga es
suyo, no un resultado del análisis. Informes/ es caché que la app relee para no
repetir trabajo; mezclar ahí los entregables haría imposible saber qué se puede
borrar sin romper la reapertura.

Dos formatos porque los dos se piden:

CSV   separado por comas, para planillas.
TXT   separado por tabulaciones, que es lo que pega directo en las planillas
      que se usan para revisar y distribuyen los resultados.

El CSV va con utf-8-sig: sin el BOM, Excel en Windows abre los acentos mal y las
columnas numéricas como texto. La TXT va con utf-8 pelado, porque un BOM se cuela
en el primer campo y rompe las comparaciones contra el encabezado.

Los informes que ya son texto (los de repetidos) no pasan por el diálogo de
formato: se bajan tal cual, en .txt. Ver exportar_lineas.

Este módulo no toca la caché: solo escribe en descargas/, y una vez escrito el
archivo es del usuario.
"""

import csv
import os
import subprocess
import sys
from datetime import datetime

import rutas

# Marca de fecha para los nombres de archivo, no para leer datos. La misma que
# usa el exportador de SeisComp para las ventanas, para que los nombres se
# vean todos del mismo modo.
FORMATO_FECHA = "%Y%m%d%H%M%S"

EXTENSIONES = {"csv": ".csv", "txt": ".txt"}
SEPARADORES = {"csv": ",", "txt": "\t"}

# La última elección del usuario: uno que exporta a CSV para Excel y después a
# TXT para la planilla no debería tener que volver a decidir en cada descarga.
_ultimo_formato = "csv"


def _etiqueta_secundaria(ttk, marco, texto, **opciones):
    """
    Una Label atenuada, con el estilo de ttkbootstrap si está disponible.

    Este módulo se importa desde scripts que no usan la app, donde ttk es el de
    la biblioteca estándar y no acepta bootstyle. Por eso el estilo va en un
    try: la diferencia es que se vea más claro o más apagado, no que el diálogo
    no abra. Que este diálogo no abriera era justo el bug reportado.
    """
    try:
        return ttk.Label(marco, text=texto, bootstyle="secondary",
                         **opciones)
    except Exception:
        return ttk.Label(marco, text=texto, foreground="#777777", **opciones)


def encima_de(padre, ventana=None, modal=True):
    """
    Pone una ventana delante de la principal y, si es un diálogo, la hace modal.

    Sin esto, un Toplevel con transient() puede abrirse detrás de la ventana
    principal: el diálogo se está mostrando, la app sigue respondiendo y parece
    que no pasó nada. Con grab_set() tampoco se puede mandar a otro lado
    clickeando fuera, que es justo lo que se pierde por no verlo.

    'modal=True' es lo correcto para un diálogo de confirmación: la app no debe
    seguir hasta contestarlo. En cambio, para las ventanas de consulta (el
    detalle del evento, las estaciones), el grab deja la app bloqueada mientras
    están abiertas y hay que cerrarlas para seguir navegando. Ahí va
    'modal=False': se suben y se les da el foco la primera vez, pero sin capturar
    la entrada, así el teclado y el mouse siguen en la lista.

    ventana puede venir None (los messagebox devuelven None al cerrarse): en ese
    caso solo se sube el foco a la ventana principal, que es lo que hace falta
    para que el mensaje que ya se mostró quede a la vista.
    """
    try:
        objetivo = ventana if ventana is not None else padre
        if objetivo is None:
            return
        objetivo.lift()
        if ventana is None or modal:
            # En un diálogo modal el foco tiene que caer adentro. En una ventana
            # de consulta no: robar el foco en cada clic corta la navegación con
            # el teclado sobre la lista.
            objetivo.focus_force()
        if ventana is not None and modal:
            ventana.grab_set()
    except Exception:
        # Si el gestor de ventanas no colabora, el diálogo igual funciona: es
        # mejor un Toplevel detrás que no tener diálogo.
        pass


def _carpeta(base):
    """Carpeta de descargas bajo base, creándola si hace falta."""
    destino = os.path.join(base, rutas.DIR_DESCARGAS)
    os.makedirs(destino, exist_ok=True)
    return destino


def carpeta_descargas(cwd=None):
    """Ruta de la carpeta de descargas del directorio de ejecución."""
    return _carpeta(os.getcwd() if cwd is None else cwd)


def nombre_descarga(etiqueta, extension, cwd=None):
    """
    Nombre único en descargas/ para una descarga.

    La hora está porque lo mismo se descarga más de una vez (distinto filtro,
    distinta fecha de corrida) y sin ella cada una pisaría a la anterior. Si el
    nombre ya existe, le agrega un correlativo: una descarga no debería fallar
    nunca porque alguien-exportó-hace-un-minuto.
    """
    base = os.getcwd() if cwd is None else cwd
    fuente = "".join(c for c in (etiqueta or "descarga").lower()
                     if c.isalnum() or c in "-_") or "descarga"
    extension = extension if extension in EXTENSIONES else "csv"
    sufijo = EXTENSIONES[extension]
    marca = datetime.now().strftime(FORMATO_FECHA)
    nombre = "%s_%s%s" % (fuente, marca, sufijo)
    carpeta = _carpeta(base)
    ruta = os.path.join(carpeta, nombre)
    n = 2
    while os.path.exists(ruta):
        nombre = "%s_%s_%d%s" % (fuente, marca, n, sufijo)
        ruta = os.path.join(carpeta, nombre)
        n += 1
    return ruta


def escribir_filas(ruta, encabezados, filas, formato="csv"):
    """
    Escribe una tabla de encabezados y filas en ruta.

    filas es una lista de listas ya formateadas a texto: entra exactamente lo
    que se ve en pantalla, con el guion de "sin dato" y los números ya
    redondeados. Lo de formatear es del caller, que es quien sabe de qué tipo
    es cada campo; acá solo se elige el separador.

    Para CSV usa csv.writer porque entrecomilla los campos que bringan coma o
    salto, que en coordenadas y comentarios pasa siempre. Para TXT se hace a
    mano: el tabulador no necesita escapes y csv.writer lo transformaría en
    comillas que en la planilla quedan como caracteres de más.
    """
    # El BOM va solo en el CSV. Excel en Windows necesita utf-8-sig para no
    # romper los acentos, pero en la TXT un BOM parte el nombre de la primera
    # columna: se cuela en el primer campo y delata comparisons con cut -f1 o
    # con el encabezado de un read_csv de pandas.
    separador = SEPARADORES.get(formato, ",")
    if formato == "csv":
        with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
            escritor = csv.writer(f)
            escritor.writerow(list(encabezados))
            for fila in filas:
                escritor.writerow(list(fila))
        return ruta

    with open(ruta, "w", encoding="utf-8", newline="") as f:
        f.write(separador.join(str(h) for h in encabezados) + "\r\n")
        for fila in filas:
            f.write(separador.join(str(v) for v in fila) + "\r\n")
    return ruta


def exportar_tabla(encabezados, filas, etiqueta, cwd=None, formato="csv"):
    """
    Escribe una tabla ya formateada y devuelve la ruta, o None si no hay filas.

    None en vez de un archivo vacío a propósito: un CSV con solo encabezados
    parece un listado que no encontró nada, y es peor que no haber descargado.
    """
    if not filas:
        return None
    base = os.getcwd() if cwd is None else cwd
    ruta = nombre_descarga(etiqueta, formato, cwd=base)
    escribir_filas(ruta, encabezados, filas, formato)
    return ruta


def exportar_lineas(lineas, etiqueta, cwd=None):
    """
    Vuelca un archivo de texto tal cual (informes de repetidos, etc.).

    A diferencia de exportar_tabla no formatea nada: lo que se descarga es el
    informe completo, no lo que entra en pantalla. Los listados se muestran
    recortados para que la ventana siga siendo usable; acá va todo, porque un
    informe que se corta a la primera fila no sirve para nada.

    Siempre .txt y siempre sin BOM. Estos informes vienen separados por espacios
    con las columnas alineadas a lo ancho (ver repetidos.py), no son tablas: no
    hay un CSV que corresponda sin inventar columnas que no están. Por eso
    preguntar el formato acá no tenía sentido.
    """
    if not lineas:
        return None
    base = os.getcwd() if cwd is None else cwd
    ruta = nombre_descarga(etiqueta, "txt", cwd=base)
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        for linea in lineas:
            f.write(linea if linea.endswith("\n") else linea + "\n")
    return ruta


def leer_lineas(ruta):
    """Contenido de un archivo de texto como lista de líneas, o [] si no está."""
    if not os.path.isfile(ruta):
        return []
    with open(ruta, encoding="utf-8-sig", errors="replace") as f:
        return f.readlines()


def preguntar_formato(padre, titulo="Formato de descarga"):
    """
    Pregunta CSV o TXT y devuelve 'csv', 'txt' o None si se cancela.

    None cancela, no cae a un formato por defecto: si alguien no elige, lo
    razonable es no escribir nada antes que adivinar mal.
    """
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        return None
    if padre is None:
        return None

    eleccion = {"formato": None}
    top = tk.Toplevel(padre)
    top.title(titulo)
    top.transient(padre)
    top.resizable(False, False)
    marco = ttk.Frame(top, padding=12)
    marco.pack(fill="both", expand=True)
    ttk.Label(marco, text="¿En qué formato querés el archivo?").pack(anchor="w")

    opciones = [("csv", "CSV  (.csv)   para planillas"),
                ("txt", "TXT  (.txt)   separado por tabulaciones")]
    marco_op = ttk.Frame(marco)
    marco_op.pack(anchor="w", fill="x", pady=(8, 4))
    # Una sola variable para las dos opciones: eso es lo que hace que sean un
    # grupo. Con una variable por opción cada radiobutton va por su cuenta, al
    # marcar TXT el de CSV sigue apareciendo marcado y no hay forma de
    # desmarcar ninguno de los dos.
    var = tk.StringVar(value=_ultimo_formato)
    for clave, texto in opciones:
        ttk.Radiobutton(marco_op, text=texto, value=clave,
                        variable=var).pack(anchor="w")

    nota = "Se guarda en descargas/ dentro de la carpeta del análisis."
    _etiqueta_secundaria(ttk, marco, nota)

    def aceptar(_evento=None):
        global _ultimo_formato
        elegido = var.get()
        if elegido not in EXTENSIONES:
            elegido = "csv"
        _ultimo_formato = elegido
        eleccion["formato"] = elegido
        top.destroy()

    def cancelar(_evento=None):
        top.destroy()

    botones = ttk.Frame(marco)
    botones.pack(anchor="e", pady=(10, 0))
    # Los botones también son de ttkbootstrap en la app y de ttk estándar fuera
    # de ella: mismo try que en _etiqueta_secundaria.
    try:
        ttk.Button(botones, text="Cancelar", command=cancelar,
                   bootstyle="secondary").pack(side="right")
        ttk.Button(botones, text="Descargar", command=aceptar,
                   bootstyle="primary").pack(side="right", padx=(0, 6))
    except Exception:
        ttk.Button(botones, text="Cancelar", command=cancelar).pack(side="right")
        ttk.Button(botones, text="Descargar", command=aceptar).pack(
            side="right", padx=(0, 6))
    top.bind("<Return>", aceptar)
    top.bind("<Escape>", cancelar)
    top.protocol("WM_DELETE_WINDOW", cancelar)
    encima_de(padre, top)
    padre.wait_window(top)
    return eleccion["formato"]


def _avisar_error(padre, mensaje):
    """Mostrar un error de escritura sin que se caiga la app."""
    try:
        from tkinter import messagebox
        # Primero se sube el foco a la ventana principal y después se abre el
        # mensaje: messagebox es bloqueante, así que pasarlo como argumento de
        # encima_de solo lo enfocaría al cerrarse, cuando ya no sirve de nada.
        encima_de(padre)
        messagebox.showerror("No se pudo descargar", mensaje, parent=padre)
    except Exception:
        print("[descargas] %s" % mensaje)


def _avisar_exito(padre, ruta):
    """Confirmar dónde quedó el archivo y ofrecer abrir la carpeta."""
    try:
        from tkinter import messagebox
        encima_de(padre)
        messagebox.showinfo(
            "Listo",
            "Se guardó:\n%s\n\n%s" % (os.path.basename(ruta),
                                       os.path.dirname(ruta)),
            parent=padre)
    except Exception:
        print("[descargas] escrito: %s" % ruta)


def abrir_carpeta(ruta=None):
    """
    Abre la carpeta en el explorador de archivos.

    Devuelve True si se pudo, False si no. No es un error si no se puede: en un
    servidor sin escritorio no hay explorador que abrir y el archivo ya está
    escrito, así que solo se avisa por pantalla.
    """
    destino = ruta if ruta is not None else _carpeta(os.getcwd())
    if not os.path.isdir(destino):
        return False
    try:
        if sys.platform.startswith("darwin"):
            subprocess.Popen(["open", destino])
        elif os.name == "nt":
            os.startfile(destino)  # noqa: S606  (API propia de Windows)
        else:
            subprocess.Popen(["xdg-open", destino])
        return True
    except Exception as exc:
        print("[descargas] no se pudo abrir %s: %s" % (destino, exc))
        return False


def descargar_tabla(padre, encabezados, filas, etiqueta, cwd=None, aviso=True):
    """
    Ruta común de las descargas con tabla: preguntar, escribir, avisar.

    Devuelve la ruta escrita, o None si se canceló o no había filas. Centraliza
    el manejo de errores para que ninguna vista tenga que escribir el mismo
    try/except OSError alrededor de la llamada.
    """
    if not filas:
        return None
    formato = preguntar_formato(padre)
    if formato is None:
        return None
    try:
        ruta = exportar_tabla(encabezados, filas, etiqueta, cwd=cwd,
                              formato=formato)
    except OSError as exc:
        _avisar_error(padre, "No se pudo escribir el archivo: %s" % exc)
        return None
    if ruta is None:
        return None
    if aviso:
        _avisar_exito(padre, ruta)
    return ruta


def descargar_texto(padre, lineas, etiqueta, cwd=None):
    """
    Igual que descargar_tabla, pero para el contenido de un informe.

    No pregunta el formato: el archivo va como TXT, que es el formato del
    informe. Ver exportar_lineas.
    """
    if not lineas:
        return None
    try:
        ruta = exportar_lineas(lineas, etiqueta, cwd=cwd)
    except OSError as exc:
        _avisar_error(padre, "No se pudo escribir el archivo: %s" % exc)
        return None
    if ruta is not None:
        _avisar_exito(padre, ruta)
    return ruta