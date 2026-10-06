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
    ploteo/     perceptidos.txt y resumen_*.log
    trabajo/    archivos intermedios (se borran solos)
    descargas/  entregables que uno se lleva (lo que elige descargar)

Las funciones p_* crean la carpeta si hace falta y devuelven la ruta completa.
Las entradas (origen/, origen_<arg>.csv, select.out, grillas/, *.tif,
base_2020_2026.dat, localidades.csv) NO se tocan.

Sobre lo que se genera: el flujo escribe dos cosas de naturaleza distinta. La
caché (datos/, informes/, ploteo/) son resultados que la app vuelve a leer al
reabrir, así que siempre se generan. Los entregables (los .txt y CSV de listado
que uno usa para entregar o consultar fuera) se piden explícitamente desde la
app, o de forma automática con RV_ENTREGABLES=1. La idea es que el análisis no
deje un reguero de archivos que nadie pidió: lo que se lleva, se descarga.
"""

import os

DIR_DATOS = "datos"
DIR_INFORMES = "informes"
DIR_PLOTEO = "ploteo"
DIR_TRABAJO = "trabajo"
DIR_DESCARGAS = "descargas"

DIRS = (DIR_DATOS, DIR_INFORMES, DIR_PLOTEO, DIR_TRABAJO, DIR_DESCARGAS)

# Entregables automáticos: sin esto, el pipeline no escribe los .txt/CSV de
# salida que se usan para entregar o consultar por fuera. Se activan con
# RV_ENTREGABLES=1 y la app ofrece la alternativa de descargarlos a mano.
ENTREGABLES = os.environ.get("RV_ENTREGABLES") == "1"


def con_entregables():
    """True si hay que escribir además los entregables automáticos."""
    return ENTREGABLES


class TextoDescartado:
    """
    Un archivo que acepta escrituras y no guarda nada.

    Para los entregables opcionales: el script escribe siempre y, cuando no se
    pidieron, las llamadas caen acá. Evita llenar el código de if alrededor de
    cada escritura y deja el flujo del script sin cortarse a mitad.
    """

    # Los scripts imprimen el nombre del archivo que abrieron, así que el
    # descarte tiene que contestarlo como sea.
    name = "(entregables desactivados)"

    def write(self, texto):
        return len(texto) if texto else 0

    def flush(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def entregable(nombre):
    """
    Abre un entregable en descargas/ si se pidieron, o un descarte si no.

    El nombre va en descargas/ y no en informes/ a propósito: lo que uno pidió
    explícitamente es suyo y no lo relee nadie; informes/ es caché que la app
    necesita para no repetir el análisis.
    """
    if not ENTREGABLES:
        return TextoDescartado()
    return open(p_descargas(nombre), "w", newline="")


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


def p_ploteo(nombre):
    return _p(DIR_PLOTEO, nombre)


def p_trabajo(nombre):
    return _p(DIR_TRABAJO, nombre)


def p_descargas(nombre):
    return _p(DIR_DESCARGAS, nombre)
