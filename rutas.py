#!/usr/bin/env python3
"""
rutas.py
========
Fuente única de verdad para la organización de los archivos que genera el
flujo de revisión. Todo se crea dentro del directorio desde donde se ejecuta
la aplicación (CWD), agrupado por contenido/etapa:

    datos/      CSV y JSON de datos/resultados
    informes/   reportes .txt
    analistas/  CSV de eventos por analista
    ploteo/     percibidos.txt y resumen_*.log
    trabajo/    archivos intermedios (se borran solos)

Las funciones p_* crean la carpeta si hace falta y devuelven la ruta completa.
Las entradas (origen/, origen_<arg>.csv, select.out, grillas/, *.tif,
base_2020_2026.dat, localidades.csv) NO se tocan.
"""

import os

DIR_DATOS = "datos"
DIR_INFORMES = "informes"
DIR_ANALISTAS = "analistas"
DIR_PLOTEO = "ploteo"
DIR_TRABAJO = "trabajo"

DIRS = (DIR_DATOS, DIR_INFORMES, DIR_ANALISTAS, DIR_PLOTEO, DIR_TRABAJO)


def asegurar_dirs():
    """Crea todas las carpetas de salida en el CWD si no existen."""
    for d in DIRS:
        os.makedirs(d, exist_ok=True)


def _p(carpeta, nombre):
    os.makedirs(carpeta, exist_ok=True)
    return os.path.join(carpeta, nombre)


def p_datos(nombre):
    return _p(DIR_DATOS, nombre)


def p_informes(nombre):
    return _p(DIR_INFORMES, nombre)


def p_analistas(nombre):
    return _p(DIR_ANALISTAS, nombre)


def p_ploteo(nombre):
    return _p(DIR_PLOTEO, nombre)


def p_trabajo(nombre):
    return _p(DIR_TRABAJO, nombre)
