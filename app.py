#!/usr/bin/env python3
"""
app.py
======
Aplicación de escritorio (ttkbootstrap) que unifica el menú del supervisor con
el flujo de análisis y revisión. La ventana principal gira alrededor de un solo
botón, «Procesar catálogos», que con los catálogos ya descargados:

  - Corre el análisis (proc_query -> revisaselect -> revisacollect ->
    compara -> [atribución a SeisComp] -> [revisaexcluidos/repetidosexclu] ->
    repetidos) mostrando el registro (log) en vivo.
  - Genera el JSON de todas las fuentes (Seisan / eventquery / SeisComp / No
    publicados de seisan / No publicados de SeisComp) y arma las pestañas de
    catálogo. Las fuentes que ya están al día se omiten.
  - Deja toda la información disponible para consultar en sus pestañas, sin
    tener que pulsar un botón por salida.

Al abrir, la aplicación reconoce qué hay en el directorio de ejecución y deja
cada pestaña en su estado (con datos, pendiente de procesar o sin datos). Los
paneles pendientes se generan en segundo plano al abrir su pestaña.

La barra lateral se organiza en Procesar / Consultar / Re-exportar. «Consultar»
reúne «Repetidos» y los listados de «No publicados» y «No actualizados»; los
dos últimos abren una ventana con una pestaña por fuente (SeisComp primero).
«Re-exportar» solo habilita el catálogo que falta o que cambió; si la
extracción inicial no pudo con uno, la app lo avisa y deja re-obtenerlo ahí
mismo.

  - Revisar los datos de SeisComp: la exportación de la ventana la deja la
    solicitud de catálogos y la revisión se abre en su pestaña, junto con los
    catálogos de Seisan y eventquery.
  - Atribuir los publicados a SeisComp: la misma comparación, corrida sobre las
    soluciones preferred en vez de las de Seisan, deja en
    informes/no_act_seiscomp_estricto.txt qué publicado quedó desactualizado y
    a qué analista le corresponde. Se saltea sola si no hay exportación.
  - Ver los reportes de eventos repetidos.

Recibe como argumentos el archivo de entrada ($1) y el de salida temporal
($2), igual que el antiguo supervisor.sh. Opcionalmente un tercer argumento
($3) con un JSON de estado que deja solicita_catalogos.py: el período y qué
catálogos no se pudieron obtener. Las salidas se organizan por contenido en el
directorio de ejecución (ver rutas.py).

Uso:
    python3 app.py <archivo_entrada.csv> <archivo_salida.dat> [estado.json]
"""

import csv
import json
import os
import shutil
import sys
import queue
import threading
import subprocess

import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledText
from ttkbootstrap.dialogs import Messagebox

import ajuste
import descargas

import matplotlib
matplotlib.use("TkAgg")  # las figuras de detalle comparten la raíz Tk de la app

from tkinter import BooleanVar, TclError, Toplevel

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

REP_FILES = [
    ("Repetidos publicados (eventquery) (amplio)",
     "informes/rep_publica_amplio.txt"),
    ("Repetidos publicados (eventquery) (estricto)",
     "informes/rep_publica_estricto.txt"),
    ("Repetidos seisan (amplio)", "informes/rep_seisan_amplio.txt"),
    ("Repetidos seisan (estricto)", "informes/rep_seisan_estricto.txt"),
    ("Repetidos excluidos seisan", "informes/rep_seisan_exclu.txt"),
    ("Repetidos SeisComp (amplio)", "informes/rep_seiscomp_amplio.txt"),
    ("Repetidos SeisComp (estricto)", "informes/rep_seiscomp_estricto.txt"),
]

# Tamaño con el que abre la ventana. Es solo el punto de partida: la ventana
# crece sola con lo que pidan las pestañas (ver _ajustar_ventana y ajuste.py),
# sin pasar nunca de lo que admite la pantalla.
TAMANIO_INICIAL = (980, 820)

# De qué archivo se arma cada pestaña de «Catálogo». El de eventquery es el
# concatenado de los new_2_*.csv, que arma _concatenar_eventquery; el de Seisan
# es el collect del análisis; el de SeisComp no entra acá porque lo elige
# _par_seiscomp_para_catalogo por cobertura.
ARCHIVO_CATALOGO = {
    "seisan": "salida_collect.csv",
    "eventquery": "todos_eventquery.csv",
}


def _derivado_al_dia(destino, entradas, carpeta):
    """
    True si 'destino' es más nuevo que todos los archivos de 'entradas'.

    Sirve para los archivos que son un derivado puro de otros (el concatenado
    de los new_2_*.csv, por ejemplo): si la salida es posterior a todas las
    entradas, no hay forma de que esté vieja y se puede saltear el trabajo.

    Ante cualquier duda devuelve False. Preferir rehacer un archivo a mostrar
    datos de la corrida anterior.
    """
    try:
        if not os.path.isfile(destino):
            return False
        marca = os.path.getmtime(destino)
    except OSError:
        return False
    for nombre in entradas:
        try:
            if os.path.getmtime(os.path.join(carpeta, nombre)) > marca:
                return False
        except OSError:
            return False
    return True

# Una vista por panel de análisis. 'clave' es, a la vez, el nombre base en
# disco (eventos_<clave>.json, conteo_perfiles_<clave>.json) y la clave de la
# pestaña. 'fuente' decide cómo se lee el CSV y cómo se comporta el panel;
# 'entrada' es el CSV del que sale el JSON: mientras el JSON sea más nuevo que
# este archivo, la vista ya está procesada y no hace falta rehacerla.
# 'tab' es el texto corto del botón de la pestaña: el grupo al que pertenece
# (GRUPOS_PESTANAS) ya pone el contexto, así que alcanza con la fuente.
VISTAS = [
    {"clave": "seisan", "fuente": "seisan",
     "tab": "Seisan", "etiqueta": "Seisan",
     "entrada": os.path.join("datos", "salida_collect.csv")},
    {"clave": "eventquery", "fuente": "eventquery",
     "tab": "eventquery", "etiqueta": "Eventquery",
     "entrada": os.path.join("datos", "todos_eventquery.csv")},
    {"clave": "seiscomp", "fuente": "seiscomp",
     "tab": "SeisComp", "etiqueta": "SeisComp",
     "entrada": os.path.join("datos", "seiscomp_parametros.csv")},
    {"clave": "seisan_nopub", "fuente": "seisan",
     "tab": "Seisan", "etiqueta": "No publicados de seisan",
     "entrada": os.path.join("datos", "no_pub_desde_2_5_estricto.csv")},
    {"clave": "seiscomp_nopub", "fuente": "seiscomp",
     "tab": "SeisComp",
     "etiqueta": "No publicados de SeisComp",
     "entrada": os.path.join("datos",
                             "no_pub_desde_2_5_seiscomp_estricto.csv")},
]
VISTAS_POR_CLAVE = {v["clave"]: v for v in VISTAS}

# Las pestañas se agrupan en filas: encabezado arriba, fuentes abajo. Se
# agrupa en lugar de ponerlas todas en una sola tira porque nueve pestañas en
# línea piden 947 px de ancho (más los 232 px de la barra lateral) y la
# ventana no llegaba, así que los nombres quedaban cortados. Con los nombres
# cortos que aporta el grupo, la barra entera mide ~256 px.
#
# 'titulo' en None es una fila sin encabezado: la de "Registro", que sola se
# explica con su propio botón. El orden de las páginas dentro de cada grupo es
# el que usa el cuaderno.
#
# Cada pestaña se identifica con un prefijo porque hay dos SeisComp distintos:
# el panel de análisis (panel:seiscomp) y el catálogo crudo (cat:seiscomp). Con
# la clave de la vista sola no se distinguían y el botón del grupo «Panel de
# mapas y perfiles» terminaba apuntando al catálogo.
GRUPOS_PESTANAS = [
    {"titulo": None, "pestanas": ["log"]},
    {"titulo": "Panel de mapas y perfiles",
     "pestanas": ["panel:seisan", "panel:eventquery", "panel:seiscomp"]},
    {"titulo": "No publicados",
     "pestanas": ["panel:seisan_nopub", "panel:seiscomp_nopub"]},
    {"titulo": "No actualizados",
     "pestanas": ["noact:seisan", "noact:seiscomp"]},
    {"titulo": "Catálogo",
     "pestanas": ["cat:seiscomp", "cat:seisan", "cat:eventquery"]},
]

# De "fuente" (lo que se clickea en la barra) a la vista del panel.
FUENTE_A_VISTA = {
    "seisan": "seisan",
    "eventquery": "eventquery",
    "seiscomp": "seiscomp",
    "nopub": "seisan_nopub",
    "nopub_seiscomp": "seiscomp_nopub",
}
VISTA_A_FUENTE = {v: k for k, v in FUENTE_A_VISTA.items()}


def _script(nombre):
    return os.path.join(SCRIPT_DIR, nombre)


MARCA_PROGRESO = "@@PROGRESO@@"

# Plan de etapas por tarea. 'scripts' mapea el subproceso (basename) que
# activa cada etapa; 'peso' reparte la barra (suman 1.0).
ANALISIS_PLAN = [
    {"nombre": "Procesando query",
     "scripts": ("proc_query_harz_2.py",), "peso": 0.10},
    {"nombre": "Revisando select",
     "scripts": ("revisaselect.py",), "peso": 0.15},
    {"nombre": "Revisando collect",
     "scripts": ("revisacollect.py",), "peso": 0.15},
    {"nombre": "Comparando publicados v/s procesados",
     "scripts": ("compara.py",), "peso": 0.20},
    {"nombre": "Atribuyendo publicados a SeisComp",
     "scripts": ("compara.py",), "peso": 0.10,
     "discriminador": "seiscomp_parametros.csv"},
    {"nombre": "Revisando excluidos",
     "scripts": ("revisaexcluidos.py", "repetidosexclu.py"), "peso": 0.10},
    {"nombre": "Revisando repetidos",
     "scripts": ("repetidos.py",), "peso": 0.20},
]

FUENTE_PLAN = {
    "seisan": [
        {"nombre": "Generando JSON (seisan)", "scripts": ("generajson.py",),
         "peso": 1.0},
    ],
    "nopub": [
        {"nombre": "Generando JSON (no publicados)",
         "scripts": ("generajson.py",), "peso": 1.0},
    ],
    "eventquery": [
        {"nombre": "Concatenando eventquery", "scripts": (), "peso": 0.15},
        {"nombre": "Generando JSON (eventquery)", "scripts": ("generajson.py",),
         "peso": 0.85},
    ],
    "seiscomp": [
        {"nombre": "Convirtiendo SeisComp",
         "scripts": ("seiscomp_a_parametros.py",), "peso": 0.35},
        {"nombre": "Generando JSON (seiscomp)", "scripts": ("generajson.py",),
         "peso": 0.65},
    ],
}

# Plan del botón maestro «Procesar catálogos». El análisis va primero (con la
# conversión de SeisComp en el lugar real donde corre: antes de su atribución,
# ver _asegurar_parametros_seiscomp) y después la generación de los paneles.
# Los pesos suman 1.0. Las cinco corridas de generajson.py se distinguen con
# 'discriminador' (su archivo de entrada), porque con el nombre del script solo
# se ganaría siempre la primera.
PROCESAR_PLAN = [
    {"nombre": "Procesando query",
     "scripts": ("proc_query_harz_2.py",), "peso": 0.075},
    {"nombre": "Revisando select",
     "scripts": ("revisaselect.py",), "peso": 0.11},
    {"nombre": "Revisando collect",
     "scripts": ("revisacollect.py",), "peso": 0.11},
    {"nombre": "Comparando publicados v/s procesados",
     "scripts": ("compara.py",), "peso": 0.15},
    {"nombre": "Convirtiendo SeisComp",
     "scripts": ("seiscomp_a_parametros.py",), "peso": 0.04},
    {"nombre": "Atribuyendo publicados a SeisComp",
     "scripts": ("compara.py",), "peso": 0.075,
     "discriminador": "seiscomp_parametros.csv"},
    {"nombre": "Revisando excluidos",
     "scripts": ("revisaexcluidos.py", "repetidosexclu.py"), "peso": 0.075},
    {"nombre": "Revisando repetidos",
     "scripts": ("repetidos.py",), "peso": 0.115},
    {"nombre": "Generando panel de Seisan",
     "scripts": ("generajson.py",), "peso": 0.06,
     "discriminador": "salida_collect.csv"},
    {"nombre": "Generando panel de eventquery",
     "scripts": ("generajson.py",), "peso": 0.06,
     "discriminador": "todos_eventquery.csv"},
    {"nombre": "Generando panel de SeisComp",
     "scripts": ("generajson.py",), "peso": 0.06,
     "discriminador": "seiscomp_parametros.csv"},
    {"nombre": "Generando panel de no publicados",
     "scripts": ("generajson.py",), "peso": 0.035,
     "discriminador": "no_pub_desde_2_5_estricto.csv"},
    {"nombre": "Generando panel de no publicados de SeisComp",
     "scripts": ("generajson.py",), "peso": 0.035,
     "discriminador": "no_pub_desde_2_5_seiscomp_estricto.csv"},
]

# Etiqueta y estilo de cada estado de catálogo, para los chips y el aviso.
# - ok: al día.
# - fallo: la extracción falló (vino en la lista de fallantes).
# - falta: el archivo no está, sin una falla reportada (se borró o similar).
# - cambio: el insumo es más nuevo que el derivado.
ESTADOS_CATALOGO = {
    "ok": ("✓ OK", "success"),
    "fallo": ("✗ falló", "danger"),
    "falta": ("✗ falta", "danger"),
    "cambio": ("⚠ cambió", "warning"),
}


class App:
    def __init__(self, raiz, archivo, salida, estado=None):
        self.raiz = raiz
        self.archivo = archivo
        self.salida = salida
        self.base = os.path.basename(archivo) if archivo else ""
        self.cwd = os.getcwd()
        # Estado que dejó solicita_catalogos.py: período y catálogos que no se
        # pudieron obtener. Puede venir vacío (modo antiguo o arranque directo).
        estado = estado or {}
        self.periodo = (estado.get("inicio"), estado.get("fin"))
        self.catalogos_faltantes = set(estado.get("faltantes", []))
        self.detalles_faltantes = estado.get("detalles", {}) or {}
        self.cola = queue.Queue()
        self.ocupado = False
        self.analisis_hecho = False
        self.analisis_en_curso = False
        self.botones = []
        self.botones_fuente = []
        # Botones con una condición propia: (widget, ¿se puede?, motivo).
        # La compuerta general solo sabe de análisis hecho/no hecho, así que
        # para lo que depende de un archivo puntual hace falta esto.
        self.condiciones = []
        # Con «Forzar actualización» los botones de re-exportar se habilitan
        # aunque el catálogo figure al día, para poder rebajarlo y reprocesar.
        self.forzar_actualizacion = BooleanVar(value=False)
        # Tamaño que se sabe que tiene la ventana. Tk contesta 200x200 a todo
        # antes de que esté mapeada (ver ajuste.py), así que el "solo crecer"
        # se apoya en este valor y no en preguntarle a la ventana.
        self._tamanio = TAMANIO_INICIAL
        # Panel de cada vista: {"frame", "placeholder", "construido"}.
        self.paneles = {}
        self.ultima_fuente = None
        self.plan_etapas = None
        self.etapa_base = 0.0
        self.etapa_ancho = 1.0
        self.etapa_nombre = ""

        # Ids de los after pendientes, para cancelarlos al salir y que Tk no
        # intente ejecutarlos con la raíz ya destruida (bgerror en la consola).
        self._after_drenar = None
        self._after_msg = None
        self._construir()
        self._autodetectar_estado()
        self.raiz.protocol("WM_DELETE_WINDOW", self._salir_app)
        self._after_drenar = self.raiz.after(100, self._drenar)
        # La exportación de SeisComp la deja la solicitud de catálogos antes
        # de llegar acá, y su pestaña se llena al procesar los catálogos,
        # igual que las de Seisan y eventquery.

    def _salir_app(self):
        """Cierra las figuras de matplotlib y luego la ventana principal."""
        # Cancelar los after pendientes ANTES de destruir la raíz: si no, Tk
        # intenta ejecutarlos cuando el intérprete ya no existe y ensucia la
        # consola con un bgerror ("invalid command name ..._drenar").
        for ident in (self._after_drenar, self._after_msg):
            if ident is not None:
                try:
                    self.raiz.after_cancel(ident)
                except Exception:
                    pass
        self._after_drenar = None
        self._after_msg = None
        try:
            import matplotlib.pyplot as plt
            plt.close("all")
        except Exception:
            pass
        try:
            self.raiz.destroy()
        except Exception:
            pass

    # ------------------------------------------------------------------ UI
    def _construir(self):
        self.raiz.title("Revisión de eventos · supervisor")
        self.raiz.geometry("%dx%d" % TAMANIO_INICIAL)
        self.raiz.minsize(860, 600)

        cab = ttk.Frame(self.raiz, padding=(12, 10, 12, 4))
        cab.pack(side=TOP, fill=X)
        ttk.Label(cab, text="Revisión de eventos sísmicos",
                  font=("", 15, "bold")).pack(side=LEFT)

        # La carpeta de ejecución va en su propia fila, a la derecha. Antes la
        # entrada compartía línea con el título y, al ser la ruta completa, los
        # dos textos se pisaban: la cabecera pedía 1001 px en una ventana de
        # 980. El archivo de entrada no se pierde: queda en el Registro cuando
        # se ejecuta el análisis, porque _popen registra la línea de comando.
        carpeta = ttk.Frame(self.raiz, padding=(12, 0, 12, 4))
        carpeta.pack(side=TOP, fill=X)
        ttk.Label(carpeta, text="Carpeta: %s" % self.cwd,
                  bootstyle="secondary").pack(side=RIGHT)

        cuerpo = ttk.Frame(self.raiz, padding=(12, 4, 12, 12))
        cuerpo.pack(side=TOP, fill=BOTH, expand=YES)

        # --- Barra lateral ---
        barra = ttk.Frame(cuerpo)
        barra.pack(side=LEFT, fill=Y, padx=(0, 12))

        self._encabezado(barra, "PROCESAR")
        self.boton_analisis = self._boton(barra, "Procesar catálogos",
                                          self._accion_procesar,
                                          bootstyle="primary")
        self.botones.remove(self.boton_analisis)
        self.etiqueta_estado = ttk.Label(barra, text="",
                                         bootstyle="warning")
        self.etiqueta_estado.pack(anchor=W, pady=(2, 2))
        # Aviso del estado de los catálogos (se refresca en
        # _actualizar_estado_catalogos): dice cuáles están OK, cuáles fallaron,
        # cuáles faltan y cuáles cambiaron.
        self.aviso_catalogos = ttk.Label(barra, text="", bootstyle="secondary",
                                         wraplength=230, justify=LEFT)
        self.aviso_catalogos.pack(anchor=W, pady=(0, 6))

        self._separador(barra)
        self._encabezado(barra, "CONSULTAR")
        # Repetidos, no publicados y no actualizados son listados de
        # texto/tabla, no los mapas de las pestañas. Los dos últimos abren una
        # ventana con una pestaña por fuente (SeisComp primero); acá va una
        # sola opción por listado.
        self._boton(barra, "Repetidos", self._ver_repetidos, gated=True)
        self._boton(barra, "No publicados", self._ver_no_publicados, gated=True)
        self._boton(barra, "No actualizados", self._ver_no_actualizados,
                    gated=True)

        self._separador(barra)
        self._encabezado(barra, "DESCARGAS")
        # Abre la carpeta donde caen los archivos que uno se lleva. Sin 'gated'
        # a propósito: no depende del análisis, la carpeta existe siempre y
        # sirve incluso antes de correr.
        self._boton(barra, "Abrir carpeta", self._abrir_descargas)

        self._separador(barra)
        self._encabezado(barra, "RE-EXPORTAR")
        # Con el tilde puesto, los botones de abajo se habilitan aunque el
        # catálogo figure al día: re-importar fuerza el análisis (los datos
        # cruzan entre catálogos).
        self.chk_forzar = ttk.Checkbutton(
            barra, text="Forzar actualización",
            variable=self.forzar_actualizacion, command=self._actualizar_gate,
            bootstyle="round-toggle")
        self.chk_forzar.pack(fill=X, pady=(2, 4))
        # Cada fila: el botón del catálogo y, a la derecha, un chip con su
        # estado. Solo se habilita el botón del catálogo que falló, falta o
        # cambió; el chip explica el estado de los tres.
        self.botones_reexportar = {}
        self.chips_catalogo = {}
        for catalogo in ("Seisan", "eventquery", "SeisComp"):
            fila = ttk.Frame(barra)
            fila.pack(fill=X)
            chip = ttk.Label(fila, text="", width=9, anchor=E)
            chip.pack(side=RIGHT)
            b = self._boton(
                fila, catalogo,
                lambda c=catalogo: self._re_exportar(c),
                condicion=(lambda c=catalogo: self._puede_re_exportar(c),
                           lambda c=catalogo: self._motivo_re_exportar(c)))
            self.botones_reexportar[catalogo] = b
            self.chips_catalogo[catalogo] = chip

        self._separador(barra)
        self._boton(barra, "Salir", self._salir_app, bootstyle="danger")

        # --- Contenido (pestañas) ---
        # La barra lateral va a la izquierda; a su derecha, un frame con la
        # barra de pestañas agrupadas arriba y el cuaderno abajo.
        derecha = ttk.Frame(cuerpo)
        derecha.pack(side=LEFT, fill=BOTH, expand=YES)

        self._boton_pestana = {}
        self.cuaderno = ttk.Notebook(derecha)

        marco_log = ttk.Frame(self.cuaderno)
        self.marco_log = marco_log
        self.cuaderno.add(marco_log, text="Registro")
        self.txt = ScrolledText(marco_log, padding=4, autohide=True)
        self.txt.pack(fill=BOTH, expand=YES)
        self.txt.text.configure(state=DISABLED, font=("Consolas", 9))

        # Un panel por vista. El marco de la pestaña ES el contenedor del
        # panel, sin un nivel más en el medio, porque es lo que hay que
        # pasarle a select() después.
        for vista in VISTAS:
            marco = ttk.Frame(self.cuaderno)
            self.cuaderno.add(marco, text=vista["tab"])
            etiqueta = ttk.Label(
                marco, justify=CENTER,
                text="No hay datos de esta fuente para mostrar.\n\nPulse "
                     "«Procesar catálogos» para generarlos.")
            etiqueta.pack(expand=YES)
            self.paneles[vista["clave"]] = {
                "frame": marco,
                "etiqueta": etiqueta,
                "construido": False,
            }

        # Catálogos crudos (sin análisis de perfiles): una pestaña por fuente.
        # El orden es el que usa GRUPOS_PESTANAS. Cada uno lleva su placeholder
        # y se arma solo al abrir la pestaña: antes los llenaba solo
        # _poblar_catalogos, que corre al terminar un análisis, así que al
        # reabrir la aplicación sobre una carpeta ya analizada las tres
        # pestañas quedaban vacías pidiendo repetir el análisis.
        self.catalogos = {}
        for clave, titulo in (("seiscomp", "SeisComp"), ("seisan", "Seisan"),
                              ("eventquery", "eventquery")):
            marco = ttk.Frame(self.cuaderno)
            self.cuaderno.add(marco, text=titulo)
            etiqueta = ttk.Label(
                marco, justify=CENTER,
                text=("No hay datos de %s para mostrar.\n\n"
                      "Pulse «Procesar catálogos» para generarlos."
                      % titulo))
            etiqueta.pack(expand=YES)
            self.catalogos[clave] = {"frame": marco, "titulo": titulo,
                                     "construido": False, "firma": None}
        # Atajos que ya usaban _marco_de y _abrir_revisor.
        self.seiscomp_frame = self.catalogos["seiscomp"]["frame"]
        self.seisan_frame = self.catalogos["seisan"]["frame"]
        self.eventquery_frame = self.catalogos["eventquery"]["frame"]

        # Listado de los eventos que sí están publicados pero cuyos parámetros
        # no coinciden con la solución local. Lo arma la corrida del análisis
        # (compara.py) y acá solo se muestra; se construye al abrir la pestaña.
        self.noact = {}
        for fuente, etiqueta in (("seisan", "Seisan"),
                                 ("seiscomp", "SeisComp")):
            marco = ttk.Frame(self.cuaderno)
            self.cuaderno.add(marco, text=etiqueta)
            etiqueta_noact = ttk.Label(
                marco, justify=CENTER,
                text=("Todavía no hay nada para mostrar.\n\n"
                      "Pulse «Procesar catálogos» para generarlo."))
            etiqueta_noact.pack(expand=YES)
            self.noact[fuente] = {"frame": marco, "etiqueta": etiqueta_noact,
                                  "construido": False}

        # Ahora que ya existen todas las páginas, se arma la barra de pestañas
        # agrupadas y recién después se empaqueta el cuaderno: la barra va
        # primero (side=TOP) para quedar arriba, y el cuaderno ocupa el resto.
        self._construir_barra_pestanas(derecha)
        self.cuaderno.pack(side=LEFT, fill=BOTH, expand=YES)

        # Se anula el layout de la pestaña nativa del cuaderno PRINCIPAL para que
        # no se vea la tira que dibuja el cuaderno: las pestañas se eligen desde
        # la barra de grupos de arriba. Se hace sobre un estilo propio
        # ("Principal.TNotebook") y NO sobre "TNotebook.Tab": anular ese era un
        # cambio GLOBAL al proceso y dejaba sin pestañas a otros cuadernos, como
        # el de la ventana de Estaciones, que sí necesita mostrar las suyas.
        self.raiz.style.layout("Principal.TNotebook.Tab", [])
        self.cuaderno.configure(style="Principal.TNotebook")

        # --- Barra de progreso (inferior, persistente) ---
        barra_marco = ttk.Frame(self.raiz, padding=(12, 4, 12, 8))
        barra_marco.pack(side=TOP, fill=X)
        self.barra = ttk.Progressbar(barra_marco, maximum=1000, value=0)
        self.barra.pack(side=LEFT, fill=X, expand=YES)
        self.barra_texto = ttk.Label(barra_marco, text="Esperando tarea…",
                                     bootstyle="secondary", width=46)
        self.barra_texto.pack(side=LEFT, padx=(10, 0))
        self.barra_valor = 0

        # Al abrir una pestaña de panel se construye/reusa el panel de esa
        # vista (ver _al_cambiar_pestana).
        self.cuaderno.bind("<<NotebookTabChanged>>", self._al_cambiar_pestana)

        self._log("Listo. Directorio de trabajo: %s" % self.cwd)
        # La primera pestaña se ve al arrancar: se marca desde el inicio para
        # que no quede ningún botón de la barra sin resaltar.
        self._marcar_pestana_activa()
        # Y se baja la barra para que «Registro» quede a la altura de
        # «Procesar catálogos». Se mide al mapear la ventana (ver _alinear).
        self.raiz.bind("<Map>", self._alinear_pestanas, add="+")
        # Con el contenido del registro el tamaño inicial alcanza y la ventana
        # no se toca; el ajuste importa cuando aparece algo más ancho, como el
        # panel de análisis o un catálogo.
        self._ajustar_ventana()

    def _ajustar_ventana(self):
        """
        Agranda la ventana si el contenido no entra, y solo lo necesario.

        El tamaño que ya tiene se pasa como piso, que es lo que hace que la
        ventana **solo crezca**: preguntar el tamaño actual a Tk no sirve
        porque antes de estar mapeada contesta 200x200 (ver ajuste.py), y con
        ese dato la ventana se encogería al abrir en vez de crecer.

        El tope lo pone ajuste.py: nunca se pasa de la pantalla ni de 1920x1080.
        """
        nuevo = ajuste.ajustar(self.raiz, minimo=self._tamanio)
        if tuple(nuevo) == tuple(self._tamanio):
            return
        self._tamanio = tuple(nuevo)
        self._log("Ventana ajustada a %dx%d px." % nuevo)

    def _alinear_pestanas(self, _evento=None):
        """Baja la barra de pestañas hasta la altura del botón de procesar.

        «Registro» arrancaba en el tope del área de contenido, arriba de donde
        arranca la barra lateral, y quedaba desfasado respecto de «Procesar
        catálogos». Se mide el desfasaje real en vez de escribir un número fijo
        para que siga valiendo si cambia el tema o la fuente; el cálculo es
        idempotente, así que un re-mapeo de la ventana no lo descoloca.
        """
        desfasaje = (self.boton_analisis.winfo_rooty()
                     - self.marco_pestanas.winfo_rooty())
        if desfasaje > 0:
            self.marco_pestanas.pack_configure(pady=(desfasaje, 0))

    def _construir_barra_pestanas(self, padre):
        """Dibuja la barra de pestañas agrupadas en filas.

        Va arriba del cuaderno, que muestra su propia tira oculta (ver
        _construir). Cada grupo es un encabezado con la fila de fuentes debajo.
        Los botones se indexan por FRAME y no por texto: "SeisComp" aparece en
        tres grupos distintos y el nombre no los distingue.
        """
        self.marco_pestanas = ttk.Frame(padre)
        self.marco_pestanas.pack(side=TOP, fill=X)

        for grupo in GRUPOS_PESTANAS:
            marco_grupo = ttk.Frame(self.marco_pestanas)
            marco_grupo.pack(fill=X, pady=(0, 4))
            titulo = grupo.get("titulo")
            if titulo:
                ttk.Label(marco_grupo, text=titulo, bootstyle="secondary",
                          font=("", 9, "bold")).pack(anchor=W)
            fila = ttk.Frame(marco_grupo)
            fila.pack(anchor=W)
            for clave in grupo["pestanas"]:
                marco = self._marco_de(clave)
                texto = self._texto_de(clave)
                boton = ttk.Button(
                    fila, text=texto,
                    command=lambda m=marco: self._ir_a_pestana(m),
                    bootstyle="secondary-outline")
                boton.pack(side=LEFT, padx=(0, 4))
                self._boton_pestana[marco] = boton

    def _marco_de(self, clave):
        """El frame del cuaderno que corresponde a una clave de pestaña."""
        if clave == "log":
            return self.marco_log
        tipo, _, nombre = clave.partition(":")
        if tipo == "cat":
            return {"seiscomp": self.seiscomp_frame,
                    "seisan": self.seisan_frame,
                    "eventquery": self.eventquery_frame}[nombre]
        if tipo == "noact":
            return self.noact[nombre]["frame"]
        panel = self.paneles.get(nombre)
        return panel["frame"] if panel else None

    def _texto_de(self, clave):
        """El texto corto del botón de esa pestaña."""
        if clave == "log":
            return "Registro"
        tipo, _, nombre = clave.partition(":")
        if tipo in ("cat", "noact"):
            return {"seiscomp": "SeisComp", "seisan": "Seisan",
                    "eventquery": "eventquery"}[nombre]
        vista = VISTAS_POR_CLAVE.get(nombre)
        return vista["tab"] if vista else nombre

    def _ir_a_pestana(self, marco):
        # Se marca el botón al toque y no solo por el evento del cuaderno: el
        # <<NotebookTabChanged>> se entrega encolado, y con el evento solo el
        # resaltado llegaba un paso tarde (visible al hacer clic rápido).
        self.cuaderno.select(marco)
        self._marcar_pestana_activa()

    def _marcar_pestana_activa(self):
        """Pinta cuál es la pestaña activa en la barra de grupos.

        Se apoya en el evento <<NotebookTabChanged>>, así que los select()
        programáticos (abrir panel, abrir catálogo) actualizan el resaltado
        solos y no hay que acordarse de llamarlo en cada uno.
        """
        actual = self.cuaderno.select()
        for marco, boton in self._boton_pestana.items():
            activo = str(marco) == actual
            boton.configure(bootstyle="primary" if activo
                            else "secondary-outline")

    def _encabezado(self, marco, texto):
        """Rótulo de un bloque de la barra lateral."""
        ttk.Label(marco, text=texto, bootstyle="secondary").pack(
            anchor=W, pady=(0, 4))

    def _separador(self, marco):
        ttk.Separator(marco, orient=HORIZONTAL).pack(fill=X, pady=10)

    def _boton(self, marco, texto, fn, bootstyle=DEFAULT, disabled=False,
               gated=False, condicion=None):
        b = ttk.Button(marco, text=texto, command=fn, bootstyle=bootstyle,
                       width=26)
        b.pack(fill=X, pady=2)
        if disabled:
            b.configure(state=DISABLED)
        elif gated:
            self.botones_fuente.append(b)
        elif condicion is not None:
            self.condiciones.append((b,) + tuple(condicion))
            self._tooltip(b, condicion[1])
        else:
            self.botones.append(b)
        return b

    # ------------------------------------------------------------- logging
    def _log(self, texto):
        self.cola.put(("log", texto))

    def _drenar(self):
        try:
            while True:
                tipo, dato = self.cola.get_nowait()
                if tipo == "log":
                    self.txt.text.configure(state=NORMAL)
                    self.txt.text.insert(END, dato + "\n")
                    self.txt.text.see(END)
                    self.txt.text.configure(state=DISABLED)
                elif tipo == "fin":
                    self._set_ocupado(False)
                    if callable(dato):
                        try:
                            dato()
                        except Exception as e:
                            self._log("[error] %s" % e)
                    self._aplicar_progreso(1.0, "Listo")
                elif tipo == "prog":
                    self._aplicar_progreso(dato[0], dato[1])
                elif tipo == "msg":
                    Messagebox.show_info(dato, "Información",
                                         parent=self.raiz)
        except queue.Empty:
            pass
        self._after_drenar = self.raiz.after(100, self._drenar)

    def _set_ocupado(self, valor):
        self.ocupado = valor
        estado = DISABLED if valor else NORMAL
        for b in self.botones:
            b.configure(state=estado)
        self._actualizar_gate()

    def _actualizar_gate(self):
        if self.ocupado:
            estado_fuente = DISABLED
        else:
            estado_fuente = NORMAL if self.analisis_hecho else DISABLED
        # «Procesar catálogos» solo se habilita si están los insumos mínimos
        # (el CSV de eventquery y select.out). Si falta alguno, se avisa en la
        # barra y se re-exporta.
        self.boton_analisis.configure(
            state=DISABLED if (self.ocupado or not self._puede_procesar())
            else NORMAL)
        for b in self.botones_fuente:
            b.configure(state=estado_fuente)
        for b, puede, _ in self.condiciones:
            b.configure(state=(NORMAL if puede() and not self.ocupado
                               else DISABLED))
        self._actualizar_estado_catalogos()

    # ----------------------------------------------------------- catálogos
    def _puede_procesar(self):
        """Si están los insumos mínimos para correr el análisis."""
        if not self.archivo or not os.path.isfile(self.archivo):
            return False
        return os.path.isfile(os.path.join("select.out"))

    def _analisis_obsoleto(self):
        """
        True si el análisis quedó viejo respecto de sus catálogos de entrada.

        Se re-exportó el select (o el CSV de eventquery) después del último
        análisis: los paneles no deben mostrar los datos viejos como si fueran
        actuales.
        """
        salida = os.path.join("datos", "salida_collect.csv")
        if not os.path.isfile(salida):
            return False
        try:
            mtime = os.path.getmtime(salida)
        except OSError:
            return False
        select = os.path.join("select.out")
        if os.path.isfile(select) and os.path.getmtime(select) > mtime:
            return True
        new2 = os.path.join("datos", "new_2_" + self.base)
        if (self.archivo and os.path.isfile(self.archivo)
                and os.path.isfile(new2)
                and os.path.getmtime(self.archivo) > os.path.getmtime(new2)):
            return True
        return False

    def _periodo(self):
        """(inicio, fin) en 14 dígitos, del estado o inferido de los nombres."""
        inicio, fin = self.periodo
        if inicio and fin:
            return inicio, fin
        import glob
        import re
        for patron in ("select_*_*.out", "eventquery_*_*.csv"):
            for ruta in sorted(glob.glob(patron)):
                m = re.match(r".*_(\d{14})_(\d{14})\.[^.]+$",
                             os.path.basename(ruta))
                if m:
                    return m.group(1), m.group(2)
        return None, None

    def _estado_catalogo(self, catalogo):
        """'ok', 'fallo', 'falta' o 'cambio' para el catálogo pedido."""
        if catalogo == "Seisan":
            insumo = "select.out"
            derivado = os.path.join("datos", "salida_collect.csv")
        elif catalogo == "eventquery":
            insumo = self.archivo
            derivado = os.path.join("datos", "new_2_" + self.base)
        elif catalogo == "SeisComp":
            par = self._par_seiscomp_para_catalogo(silencioso=True)
            insumo = par["eventos"] if par is not None else None
            derivado = os.path.join("datos", "seiscomp_parametros.csv")
        else:
            return "ok"
        if not insumo or not os.path.isfile(insumo):
            # No está: si la extracción de esta sesión lo reportó como fallante,
            # fue un fallo; si no, simplemente no está (se borró o similar).
            return "fallo" if catalogo in self.catalogos_faltantes else "falta"
        # Sin derivado todavía, el análisis no corrió: el catálogo está, no hay
        # nada que re-exportar. Solo es "cambio" si el insumo es más nuevo que
        # un derivado que ya existía.
        if not os.path.isfile(derivado):
            return "ok"
        try:
            return ("cambio" if os.path.getmtime(insumo)
                    > os.path.getmtime(derivado) else "ok")
        except OSError:
            return "ok"

    def _puede_re_exportar(self, catalogo):
        # Con «Forzar actualización» se habilita aunque el catálogo esté al día.
        if self.forzar_actualizacion.get():
            return True
        return self._estado_catalogo(catalogo) != "ok"

    def _motivo_re_exportar(self, catalogo):
        estado = self._estado_catalogo(catalogo)
        if estado == "fallo":
            return ("La extracción de %s falló. Use este botón para volver a "
                    "intentarlo." % catalogo)
        if estado == "falta":
            return ("El catálogo de %s no está (¿se borró?). Use este botón "
                    "para volver a obtenerlo." % catalogo)
        if estado == "cambio":
            return ("%s cambió desde el último procesamiento. Re-expórtelo y "
                    "vuelva a procesar." % catalogo)
        return ("El catálogo de %s está al día; no hace falta re-exportarlo."
                % catalogo)

    def _actualizar_estado_catalogos(self):
        """Refresca los chips por catálogo y el aviso resumen."""
        for catalogo, chip in self.chips_catalogo.items():
            texto, estilo = ESTADOS_CATALOGO[self._estado_catalogo(catalogo)]
            chip.configure(text=texto, bootstyle=estilo)
        partes = []
        for catalogo in ("Seisan", "eventquery", "SeisComp"):
            estado = self._estado_catalogo(catalogo)
            if estado == "ok":
                continue
            texto, _ = ESTADOS_CATALOGO[estado]
            partes.append("%s: %s" % (texto, catalogo))
        if not partes:
            self.aviso_catalogos.configure(text="✓ Catálogos OK.",
                                           bootstyle="success")
            return
        estilo = "danger" if any("✗" in p for p in partes) else "warning"
        self.aviso_catalogos.configure(text=" · ".join(partes),
                                       bootstyle=estilo)

    def _re_exportar(self, catalogo):
        """Re-importa un catálogo y, siempre, vuelve a correr el análisis.

        Re-importar uno solo ya obliga a reprocesar, porque los datos cruzan
        entre catálogos (comparación, atribución a SeisComp, repetidos, No
        publicados, mapas y perfiles). Por eso el aviso previo lo dice y, al
        terminar la descarga, el análisis corre solo.
        """
        if self.ocupado:
            return
        if not self._confirmar_reimportar(catalogo):
            self._log("Re-exportación cancelada.")
            return
        if catalogo == "SeisComp":
            radio = self._pedir_radio(self._radio_seiscomp_actual())
            if radio is None:
                self._log("Re-exportación cancelada.")
                return
            inicio, fin = self._periodo()
            if inicio and fin and not self._confirmar_tamano_seiscomp(
                    radio, inicio, fin):
                self._log("Re-exportación cancelada por el tamaño estimado.")
                return

            def tarea():
                self._tarea_re_exportar_seiscomp(radio)
                # Refresca el panel con la exportación recién escrita.
                self._procesar_fuente("seiscomp")
        else:
            contrasena = self._pedir_contrasena()
            if not contrasena:
                self._log("Re-exportación cancelada.")
                return
            tarea = (lambda c=catalogo, p=contrasena:
                     self._tarea_re_exportar_red(c, p))

        def al_terminar():
            self.catalogos_faltantes.discard(catalogo)
            self._actualizar_gate()
            # El popup previo ya avisó que se reprocesa: se hace sin preguntar
            # de nuevo.
            self._accion_procesar(confirmar=False)

        self._iniciar(tarea, on_fin=al_terminar, plan=None)

    def _confirmar_reimportar(self, catalogo):
        """
        Aviso previo a re-importar: al hacerlo se fuerza el análisis.

        No es solo un cambio de archivo: lo que entrega la app cruza datos
        entre catálogos, así que re-importar uno obliga a reprocesar todo.
        """
        texto = (
            "Vas a re-importar el catálogo de %s.\n\n"
            "La información que entrega la app cruza datos entre los catálogos "
            "(comparación publicados vs procesados, atribución a SeisComp, "
            "revisión de repetidos, No publicados, mapas y perfiles), así que "
            "al re-importarlo se forzará el análisis y se reprocesarán los "
            "catálogos actuales (Seisan, Eventquery y SeisComp).\n\n"
            "Puede tardar unos minutos. ¿Continuar?" % catalogo)
        return Messagebox.show_question(
            texto, "Re-importar y reprocesar", parent=self.raiz,
            buttons=["Forzar y reprocesar:primary",
                     "Cancelar"]) == "Forzar y reprocesar"

    def _tarea_re_exportar_seiscomp(self, radio):
        inicio, fin = self._periodo()
        if not (inicio and fin):
            self._log("No se pudo determinar el período a exportar.")
            return
        self._log("***** Re-exportando SeisComp (%s - %s, radio %.0f km) *****"
                  % (inicio, fin, radio))
        if self._popen([_script("verifica_entorno.py")]):
            self._log("El entorno no está listo; no se exportó SeisComp.")
            return
        exportador = _script("exporta_ventana_seiscomp.py")
        # Sin --reusar: re-exportar es forzar, así que se reconsulta la base.
        if self._popen([exportador, "--radio-km", "%g" % radio,
                        inicio, fin]):
            self._log("La exportación de SeisComp falló (ver el registro).")
            return
        self._log("SeisComp re-exportado.")

    def _tarea_re_exportar_red(self, catalogo, contrasena):
        import traer_catalogos as tc
        inicio, fin = self._periodo()
        if not (inicio and fin):
            self._log("No se pudo determinar el período a re-exportar.")
            return
        self._log("***** Re-exportando %s (%s - %s) *****"
                  % (catalogo, inicio, fin))
        with tc.Conexion(contrasena, log=self._log) as conexion:
            tc.verificar_conexion(conexion, log=self._log,
                                  progreso=self._progreso_local)
            if catalogo == "Seisan":
                ruta = tc.traer_seisan(inicio, fin, conexion, cwd=self.cwd,
                                       log=self._log,
                                       progreso=self._progreso_local,
                                       forzar=True)
                # copy2 preserva la fecha del select recién bajado; copyfile
                # la pondría en "ahora" y select.out parecería más nuevo.
                shutil.copy2(ruta, os.path.join(self.cwd, "select.out"))
                self._log("select.out actualizado desde %s"
                          % os.path.basename(ruta))
            else:
                tc.traer_eventquery(inicio, fin, conexion, cwd=self.cwd,
                                    log=self._log,
                                    progreso=self._progreso_local,
                                    forzar=True)
        self._log("%s re-exportado." % catalogo)

    def _pedir_contrasena(self):
        """Diálogo simple para la contraseña del servidor remoto."""
        top = Toplevel(self.raiz)
        top.title("Contraseña del servidor")
        top.transient(self.raiz)
        top.grab_set()
        marco = ttk.Frame(top, padding=12)
        marco.pack(fill=BOTH, expand=YES)
        ttk.Label(marco, text="Contraseña del servidor remoto:").pack(anchor=W)
        entrada = ttk.Entry(marco, show="*", width=28)
        entrada.pack(fill=X, pady=(4, 10))
        entrada.focus_set()
        resultado = {"valor": None}

        def aceptar(_evento=None):
            resultado["valor"] = entrada.get()
            top.destroy()

        def cancelar(_evento=None):
            top.destroy()

        botones = ttk.Frame(marco)
        botones.pack(fill=X)
        ttk.Button(botones, text="Aceptar", command=aceptar,
                   bootstyle="primary").pack(side=RIGHT)
        ttk.Button(botones, text="Cancelar", command=cancelar,
                   bootstyle="secondary").pack(side=RIGHT, padx=(0, 6))
        entrada.bind("<Return>", aceptar)
        top.bind("<Escape>", cancelar)
        self.raiz.wait_window(top)
        return resultado["valor"]

    def _pedir_radio(self, defecto):
        """Diálogo para el radio (km) de estaciones sin arribos de SeisComp."""
        top = Toplevel(self.raiz)
        top.title("Radio de estaciones SeisComp")
        top.transient(self.raiz)
        top.grab_set()
        marco = ttk.Frame(top, padding=12)
        marco.pack(fill=BOTH, expand=YES)
        ttk.Label(marco, text="Radio de búsqueda de estaciones sin arribos"
                             " (km, solo SeisComp):").pack(anchor=W)
        entrada = ttk.Entry(marco, width=12)
        entrada.insert(0, "%g" % defecto)
        entrada.pack(anchor=W, pady=(4, 10))
        entrada.focus_set()
        entrada.selection_range(0, END)
        resultado = {"valor": None}

        def aceptar(_evento=None):
            try:
                valor = float(entrada.get().strip().rstrip("kKmM"))
            except ValueError:
                return
            if valor <= 0:
                return
            resultado["valor"] = valor
            top.destroy()

        def cancelar(_evento=None):
            top.destroy()

        botones = ttk.Frame(marco)
        botones.pack(fill=X)
        ttk.Button(botones, text="Aceptar", command=aceptar,
                   bootstyle="primary").pack(side=RIGHT)
        ttk.Button(botones, text="Cancelar", command=cancelar,
                   bootstyle="secondary").pack(side=RIGHT, padx=(0, 6))
        entrada.bind("<Return>", aceptar)
        top.bind("<Escape>", cancelar)
        self.raiz.wait_window(top)
        return resultado["valor"]

    def _radio_seiscomp_actual(self):
        """El radio de la exportación vigente, o el valor por defecto.

        Se lee de la marca de fin, que anota con qué radio se calculó la lista
        de estaciones. Si no hay exportación o no se puede leer, cae al valor
        por defecto del exportador.
        """
        try:
            import exporta_ventana_seiscomp as ev
            defecto = ev.RADIO_ESTACIONES_KM
        except Exception:
            ev = None
            defecto = 400.0
        inicio, fin = self._periodo()
        if ev is not None and inicio and fin:
            marca = os.path.join("datos", "seiscomp_%s_%s.csv.completo"
                                 % (inicio, fin))
            radio = ev._radio_de_la_marca(marca)
            if radio is not None:
                return radio
        return defecto

    def _confirmar_tamano_seiscomp(self, radio, inicio, fin):
        """Pide confirmación si la exportación de SeisComp quedaría enorme.

        El archivo de no picadas crece con los eventos y con el radio, y en el
        histórico pasa de un gigabyte. Si la exportación se va a reutilizar (el
        radio coincide con la marca) no hay nada que estimar. Ante cualquier
        error se sigue sin preguntar: es un aviso, no un requisito.
        """
        try:
            from datetime import datetime
            import exporta_ventana_seiscomp as ev
        except Exception:
            return True
        marca = os.path.join("datos", "seiscomp_%s_%s.csv.completo"
                             % (inicio, fin))
        radio_marca = ev._radio_de_la_marca(marca)
        if radio_marca is not None and abs(radio_marca - round(radio)) < 0.5:
            return True
        try:
            ini_dt = datetime.strptime(inicio, "%Y%m%d%H%M%S")
            fin_dt = datetime.strptime(fin, "%Y%m%d%H%M%S")
            bases = ev._bases_a_consultar(None)
            _filas, mb = ev.estimar_no_picadas(bases, ini_dt, fin_dt, radio)
        except Exception:
            return True
        if mb < ev.AVISO_NO_PICADAS_MB:
            return True
        texto = ("Con radio %.0f km esta ventana generaría alrededor de %.0f MB"
                 " de estaciones sin arribos. El revisor lo escanea al abrir y"
                 " puede tardar.\n\n¿Continuar?" % (radio, mb))
        return Messagebox.show_question(
            texto, "Exportación grande", parent=self.raiz,
            buttons=["Continuar:primary", "Cancelar"]) == "Continuar"

    def _tooltip(self, widget, motivo):
        """
        Tooltip mínimo que sale solo con el botón apagado.

        ttkbootstrap.tooltip no se puede usar acá: usa typing.Literal, que
        existe desde Python 3.8, y la app corre en 3.7. Por eso son veinte
        líneas de Toplevel en vez de un import.

        El motivo se evalúa al entrar, no al crear el widget: depende del
        estado de los archivos y cambia con el correr del tiempo. Se acepta
        tanto una función como un texto fijo, para que un motivo constante (o
        vacío) no se intente llamar como función.
        """
        if not callable(motivo):
            fijo = motivo
            motivo = lambda: fijo

        def entrar(_evento=None):
            if widget.instate(["disabled"]):
                texto = motivo()
                if texto:
                    self._mostrar_ayuda(widget, texto)

        def salir(_evento=None):
            self._ocultar_ayuda(widget)

        widget.bind("<Enter>", entrar, add="+")
        widget.bind("<Leave>", salir, add="+")

    def _mostrar_ayuda(self, widget, texto):
        self._ocultar_ayuda()
        # Toplevel de tkinter y NO de ttkbootstrap: el de ttkbootstrap, en x11,
        # entra en wait_visibility() dentro de su __init__ (porque alpha viene
        # en 1.0 por defecto), que es un event loop anidado y bloqueante. Pasa
        # antes de que se pueda poner overrideredirect, así que el window
        # manager decide dónde queda la ventana: appeared en cualquier lado, y
        # además el anidamiento reentra al loop de la app justo en un evento de
        # mouse. Con tkinter la posición pedida se respeta.
        top = Toplevel(widget)
        top.overrideredirect(True)
        ttk.Label(top, text=texto, justify=LEFT, wraplength=240,
                  padding=6, background="#fff8dc").pack()
        top.update_idletasks()
        # Abajo del botón, y no encima: si el tooltip se superpone al widget,
        # el mouse "sale" de él, se borra el tooltip, vuelve a entrar y el
        # ciclo se repite en parpadeo.
        top.geometry("+%d+%d" % (widget.winfo_rootx(),
                                 widget.winfo_rooty() + widget.winfo_height()))
        self._ayuda = (widget, top)

    def _ocultar_ayuda(self, widget=None):
        """
        Cierra el tooltip.

        El widget se chequea porque al pasar de un botón a otro Tk no garantiza
        el orden de <Leave> y <Enter>: si entra en el nuevo antes de salir del
        anterior, el <Leave> del viejo borraría el tooltip del nuevo.
        """
        ayuda = getattr(self, "_ayuda", None)
        if ayuda is None:
            return
        duenio, top = ayuda
        if widget is not None and duenio is not widget:
            return
        try:
            top.destroy()
        except TclError:
            pass
        self._ayuda = None

    def _actualizar_estado(self):
        if self.analisis_en_curso:
            self.etiqueta_estado.configure(
                text="Catálogos: procesando…", bootstyle="warning")
        elif self.analisis_hecho:
            self.etiqueta_estado.configure(
                text="Catálogos: procesados", bootstyle="success")
        else:
            self.etiqueta_estado.configure(
                text="Catálogos: sin procesar", bootstyle="secondary")

    def _autodetectar_estado(self):
        """
        Reconoce en el directorio de ejecución qué pestañas pueden mostrarse.

        No genera nada: deja cada panel en su placeholder correcto (con datos,
        pendiente de procesar o sin datos) y registra el resumen. La generación
        de los pendientes es perezosa, al abrir su pestaña (ver
        _abrir_panel_si_puede).
        """
        obsoleto = self._analisis_obsoleto()
        self.analisis_hecho = (
            os.path.isfile(os.path.join("datos", "salida_collect.csv"))
            and not obsoleto)
        listas, pendientes = [], []
        for clave, vista in VISTAS_POR_CLAVE.items():
            if obsoleto:
                self._placeholder_panel(
                    clave, "Los catálogos cambiaron desde el último "
                           "análisis.\n\nPulse «Procesar catálogos» para "
                           "regenerar el panel de %s." % vista["etiqueta"])
            elif self._vista_procesada(clave):
                listas.append(clave)
                self._placeholder_panel(
                    clave, "Hay datos procesados de %s.\n\nAbra la pestaña "
                           "para verlos." % vista["etiqueta"])
            elif os.path.isfile(vista["entrada"]):
                pendientes.append(clave)
                self._placeholder_panel(
                    clave, "Hay datos sin procesar de %s.\n\nAl abrir esta "
                           "pestaña se genera el panel."
                           % vista["etiqueta"])
            else:
                self._placeholder_panel(
                    clave, "No hay datos de %s para mostrar.\n\nPulse "
                           "«Procesar catálogos» para generarlos."
                           % vista["etiqueta"])
        if obsoleto:
            self._log("El análisis quedó obsoleto (los catálogos son más "
                      "nuevos); vuelva a «Procesar catálogos».")
        if listas:
            self._log("Paneles ya procesados: %s." % ", ".join(listas))
        if pendientes:
            self._log("Paneles pendientes (se generan al abrir su pestaña): "
                      "%s." % ", ".join(pendientes))
        if self.analisis_hecho:
            self._log("Se detectaron resultados del análisis; fuentes "
                      "habilitadas.")
        if self.catalogos_faltantes:
            faltan = ", ".join(sorted(self.catalogos_faltantes))
            self._log("***** Faltan catálogos: %s. Use «Re-exportar». *****"
                      % faltan)
            self._after_msg = self.raiz.after(300, lambda: Messagebox.show_warning(
                "No se pudieron obtener: %s.\n\nUse «Re-exportar» para "
                "volver a intentarlo." % faltan,
                "Catálogos faltantes", parent=self.raiz))
        self._actualizar_estado()
        self._actualizar_gate()

    def _placeholder_panel(self, clave, texto):
        """Deja el placeholder de un panel con el texto dado."""
        panel = self.paneles.get(clave)
        if panel is None:
            return
        for w in list(panel["frame"].winfo_children()):
            w.destroy()
        etiqueta = ttk.Label(panel["frame"], justify=CENTER, text=texto)
        etiqueta.pack(expand=YES)
        panel["etiqueta"] = etiqueta
        panel["construido"] = False

    def _vista_procesada(self, clave):
        """
        True si el JSON de la vista es más nuevo que su CSV de entrada.

        Es lo que decide si el botón de la fuente queda apagado: mientras el
        JSON siga siendo el resultado del CSV actual, reprocesar daría el mismo
        panel. Cuando el análisis reescribe el CSV, el botón se enciende solo.
        """
        if self._analisis_obsoleto():
            return False
        vista = VISTAS_POR_CLAVE.get(clave)
        if vista is None:
            return False
        json_path = os.path.join("datos", "eventos_%s.json" % clave)
        if not os.path.isfile(json_path):
            return False
        if clave == "eventquery":
            # El CSV derivado (todos_eventquery.csv) no lo refresca el análisis,
            # lo arma _concatenar_eventquery. La frescura hay que medirla contra
            # los new_2_*.csv, que sí cambian con cada análisis: si no, un JSON
            # viejo parecería al día y el panel quedaría con datos de menos.
            entradas = self._partes_eventquery()
            if not entradas:
                return False
            mas_nuevo = max(os.path.getmtime(r) for r in entradas)
            return os.path.getmtime(json_path) >= mas_nuevo
        entrada = vista["entrada"]
        if not os.path.isfile(entrada):
            return False
        return os.path.getmtime(json_path) >= os.path.getmtime(entrada)

    @staticmethod
    def _partes_eventquery(carpeta="datos"):
        """Rutas de los new_2_*.csv, ordenadas, o [] si no hay."""
        try:
            nombres = sorted(n for n in os.listdir(carpeta)
                             if n.startswith("new_2_") and n.endswith(".csv"))
        except OSError:
            return []
        return [os.path.join(carpeta, n) for n in nombres]

    # ------------------------------------------------------------- progreso
    def _aplicar_progreso(self, fraccion, texto):
        """Actualiza la barra (monótona) y la etiqueta con % + etapa."""
        frac = max(0.0, min(1.0, fraccion))
        val = int(round(frac * 1000))
        if val > self.barra_valor:
            self.barra_valor = val
            self.barra.configure(value=val)
        self.barra_texto.configure(
            text="%d %% · %s" % (round(frac * 100), texto))

    def _fijar_etapa(self, indice):
        """Posiciona la etapa actual según el plan y muestra su inicio."""
        if not self.plan_etapas:
            return
        indice = max(0, min(indice, len(self.plan_etapas) - 1))
        etapa = self.plan_etapas[indice]
        self.etapa_base = sum(p["peso"] for p in self.plan_etapas[:indice])
        self.etapa_ancho = etapa["peso"]
        self.etapa_nombre = etapa["nombre"]
        self.cola.put(("prog", (self.etapa_base, self.etapa_nombre)))

    def _progreso_local(self, fraccion):
        """Mapea la fracción [0,1] del script dentro del peso de la etapa."""
        frac = max(0.0, min(1.0, fraccion))
        global_v = self.etapa_base + self.etapa_ancho * frac
        self.cola.put(("prog", (global_v, self.etapa_nombre)))

    def _preparar_etapa_script(self, nombre_script, argumentos=()):
        try:
            nombre_script = os.path.basename(nombre_script)
        except TypeError:
            return
        etapas = self.plan_etapas or ()
        # Una etapa puede pedir un discriminador. Hace falta porque el mismo
        # script corre más de una vez en el plan con entradas distintas
        # (compara.py compara Seisan y después SeisComp) y con el nombre solo
        # no se sabe cuál de las dos es: se ganaría siempre la primera.
        for i, e in enumerate(etapas):
            marca = e.get("discriminador")
            # El script también tiene que coincidir: si no, un discriminator
            # como "salida_collect.csv" lo ganaría cualquier etapa cuyo script
            # reciba ese archivo (p. ej. compara.py), no solo la buscada.
            if (marca is not None
                    and nombre_script in e.get("scripts", ())
                    # any(...) y no `marca in argumentos`: los argumentos llegan
                    # como rutas completas ("datos/seiscomp_parametros.csv"),
                    # así que tiene que ser coincidencia parcial y no igualdad
                    # de elemento.
                    and any(marca in str(a) for a in argumentos)):
                self._fijar_etapa(i)
                return
        for i, e in enumerate(etapas):
            if nombre_script in e.get("scripts", ()):
                self._fijar_etapa(i)
                return

    # ------------------------------------------------------------ procesos
    def _popen(self, args):
        args = list(args)
        script = args[0] if args and args[0].endswith(".py") else None
        if script:
            args = [PY] + args
        self._log("$ " + " ".join(args))
        if script:
            self._preparar_etapa_script(script, args)
        env = dict(os.environ)
        env["RV_PROG"] = "1"
        try:
            p = subprocess.Popen(args, cwd=self.cwd,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT,
                                 universal_newlines=True, bufsize=1,
                                 env=env)
        except Exception as e:
            self._log("[error] no se pudo ejecutar: %s" % e)
            return 1
        for linea in p.stdout:
            linea = linea.rstrip("\n")
            if linea.startswith(MARCA_PROGRESO):
                partes = linea.split(None, 1)
                try:
                    self._progreso_local(float(partes[1]))
                except (IndexError, ValueError):
                    pass
                continue
            self._log(linea)
        p.wait()
        if p.returncode:
            self._log("[código de salida %d]" % p.returncode)
        return p.returncode

    def _iniciar(self, tarea, on_fin=None, plan=None):
        if self.ocupado:
            return
        self.plan_etapas = plan
        self.barra_valor = 0
        self.barra.configure(value=0)
        self.barra_texto.configure(text="0 % · Iniciando…")
        self._set_ocupado(True)

        def envolver():
            try:
                tarea()
            except Exception as e:
                self._log("[error] %s" % e)
            finally:
                self.cola.put(("fin", on_fin))

        threading.Thread(target=envolver, daemon=True).start()

    # ------------------------------------------------------------ acciones
    def _procesar_analisis(self):
        """
        Pipeline pesado de análisis. Síncrono: corre dentro de una tarea.

        No pregunta nada ni toca el estado de la app; de eso se encargan los
        envoltorios (_accion_procesar y _accion_fuente).
        """
        self._log("***** Se comienza el análisis de los datos *****")
        self._popen([_script("proc_query_harz_2.py"),
                     self.archivo, self.salida])
        self._popen([_script("revisaselect.py")])
        self._popen([_script("revisacollect.py")])
        self._log("***** Comparando publicados v/s procesados *****")
        self._popen([_script("compara.py"),
                     os.path.join("datos", "new_2_" + self.base),
                     os.path.join("datos", "salida_collect.csv")])
        # La atribución a SeisComp es la misma comparación con las soluciones
        # preferred en vez de las de Seisan: deja en no_act_seiscomp_*.txt qué
        # publicado quedó desactualizado y a quién le corresponde. Se saltea si
        # no hay exportación, porque la ventana del catálogo puede no haberse
        # descargado nunca.
        parametros = os.path.join("datos", "seiscomp_parametros.csv")
        self._asegurar_parametros_seiscomp()
        if os.path.isfile(parametros) and os.path.getsize(parametros) > 0:
            self._log("***** Atribuyendo publicados a SeisComp *****")
            self._popen([_script("compara.py"),
                         os.path.join("datos", "new_2_" + self.base),
                         parametros, "seiscomp_"])
        else:
            self._log("Sin datos de SeisComp: se omite la atribución.")
        excl = os.path.join("informes", "excluidos.txt")
        if os.path.isfile(excl) and os.path.getsize(excl) > 0:
            self._log("***** Revisando excluidos *****")
            self._popen([_script("revisaexcluidos.py")])
            self._popen([_script("repetidosexclu.py"),
                         os.path.join("datos", "excluidos.csv"),
                         os.path.join("datos", "salida_collect.csv")])
        else:
            for f in (excl, os.path.join("trabajo", "excluidostmp1.txt")):
                try:
                    os.remove(f)
                except OSError:
                    pass
            self._log("No se excluyeron eventos del select.out")
        self._log("***** Se revisan repetidos *****")
        args_repetidos = [_script("repetidos.py"),
                          os.path.join("datos", "new_2_" + self.base),
                          os.path.join("datos", "salida_collect.csv")]
        # El catálogo de SeisComp se revisa con el mismo script: mismo layout de
        # 8 columnas, así que solo hay que pasarle el CSV.
        if os.path.isfile(parametros) and os.path.getsize(parametros) > 0:
            args_repetidos.append(parametros)
        self._popen(args_repetidos)
        try:
            os.remove(self.salida)
        except OSError:
            pass
        self._log("***** Análisis terminado *****")

    def _accion_procesar(self, confirmar=True):
        """
        Botón maestro «Procesar catálogos».

        Corre el análisis y, con los mismos catálogos ya en disco, genera el
        JSON de todas las pestañas de panel y arma las de catálogo. Una sola
        pulsación deja toda la información disponible para consultar; las
        fuentes que ya estaban al día se omiten, así que volver a pulsarlo
        rehace solo lo vencido.

        Con 'confirmar=False' no pregunta: lo usa la re-exportación, que ya
        avisó en su popup previo que al re-importar se reprocesa.
        """
        if not self.archivo:
            self._log("No se especificó archivo de entrada.")
            return
        # Volver a ejecutarlo es una acción legítima pero son minutos de
        # trabajo, así que se pregunta antes. El botón queda habilitado
        # siempre, con la compuerta aprobando que se vuelva a pulsar. Si el
        # análisis quedó obsoleto (se re-exportó un catálogo), no se pregunta:
        # reprocesar es justamente lo que hay que hacer.
        if confirmar and self.analisis_hecho and not self._analisis_obsoleto():
            texto = ("Volver a procesar los catálogos va a regenerar los "
                     "datos de %s.\n\nLo que ya estaba procesado vuelve a "
                     "quedar para rehacer, porque su CSV de entrada "
                     "cambió.\n\n¿Continuar?"
                     % os.path.basename(self.archivo))
            if Messagebox.show_question(texto, "Volver a procesar catálogos",
                                        parent=self.raiz,
                                        buttons=["Procesar:primary",
                                                 "Cancelar"]) != "Procesar":
                self._log("Procesamiento cancelado.")
                return

        def tarea():
            self._procesar_analisis()
            # SeisComp primero: deja seiscomp_parametros.csv, que la atribución
            # de eventquery necesita. Si no hay exportación, _procesar_fuente lo
            # avisa y sigue.
            for fuente in ("seiscomp", "seisan", "eventquery", "nopub",
                           "nopub_seiscomp"):
                vista_clave = FUENTE_A_VISTA.get(fuente)
                if vista_clave and self._vista_procesada(vista_clave):
                    self._log("La fuente %s ya estaba procesada; se omite."
                              % vista_clave)
                    continue
                self._procesar_fuente(fuente)
            self._poblar_catalogos()
            self._log("***** Procesamiento terminado *****")

        self.analisis_en_curso = True
        self._actualizar_estado()
        self._iniciar(tarea, on_fin=self._al_terminar_procesar,
                      plan=PROCESAR_PLAN)

    def _al_terminar_procesar(self):
        self.analisis_en_curso = False
        self.analisis_hecho = os.path.isfile(
            os.path.join("datos", "salida_collect.csv"))
        if self.analisis_hecho:
            self._log("Procesamiento completado: las pestañas ya tienen sus "
                      "datos.")
        else:
            self._log("El procesamiento no generó datos/salida_collect.csv; "
                      "revise el registro.")
        self._actualizar_estado()
        self._actualizar_gate()

    def _poblar_catalogos(self):
        """
        Llena las pestañas de catálogo al terminar «Procesar catálogos».

        Las tres salen del análisis: Seisan de salida_collect.csv, eventquery
        del concatenado de los new_2_*.csv y SeisComp de la exportación que
        dejó la solicitud de catálogos. No se cambia de pestaña para no sacar
        al usuario de donde está mirando.

        Va por _construir_catalogo, el mismo camino que usa la pestaña al
        abrirse, para que no haya dos formas de llenarla y se puedan
        desincronizar.
        """
        # El concatenado se rehace siempre que el análisis acaba de correr:
        # «Procesar catálogos» regenera los new_2_*.csv, así que el derivado
        # tiene que volver a armarse. forzar=True porque es el único punto
        # donde se garantiza que lo demás ya está en disco.
        self._concatenar_eventquery(forzar=True)
        for clave in ("seisan", "eventquery", "seiscomp"):
            self._construir_catalogo(clave, seleccionar=False)

    def _procesar_fuente(self, fuente):
        """
        Genera el JSON/panel de una fuente. Síncrono, sin envoltorio de tarea.

        Devuelve True si dejó el JSON en disco. Lo comparten el botón maestro
        («Procesar catálogos»), la re-exportación de SeisComp y la generación
        perezosa al abrir una pestaña, para que no haya dos caminos que puedan
        desincronizarse.
        """
        # Cada fuente escribe su propio eventos_<vista>.json: los no publicados
        # comparten parseo con su fuente, pero no archivo de salida, así que
        # procesarlos no pisa el panel de la fuente principal.
        vista_clave = FUENTE_A_VISTA.get(fuente)
        if vista_clave not in VISTAS_POR_CLAVE:
            return False
        if fuente == "seisan":
            self._popen([_script("generajson.py"),
                         os.path.join("datos", "salida_collect.csv"),
                         "seisan"])
        elif fuente == "eventquery":
            self._concatenar_eventquery()
            self._asegurar_parametros_seiscomp()
            self._atribuir_para_eventquery()
            self._popen([_script("generajson.py"),
                         os.path.join("datos", "todos_eventquery.csv"),
                         "eventquery"])
            # No se borra: es lo que lee la pestaña de catálogo de eventquery, y
            # regenerarlo cuesta una pasada más. Es un derivado de los new_2_*,
            # así que no puede quedar desactualizado sin que también lo estén
            # ellos.
        elif fuente == "seiscomp":
            par = self._par_seiscomp_para_catalogo()
            if par is None:
                self._log("No hay una exportación de SeisComp que cubra "
                          "este catálogo.")
                return False
            self._log("Usando %s" % os.path.basename(par["eventos"]))
            # Idempotente: si el análisis ya dejó seiscomp_parametros.csv al
            # día, no vuelve a convertir.
            self._asegurar_parametros_seiscomp()
            parametros = os.path.join("datos", "seiscomp_parametros.csv")
            if not (os.path.isfile(parametros)
                    and os.path.getsize(parametros) > 0):
                self._log("La conversión falló; no se genera el JSON.")
                return False
            self._popen([_script("generajson.py"), parametros, "seiscomp"])
        elif fuente in ("nopub", "nopub_seiscomp"):
            # Los dos "no publicados" salen del mismo compara.py, cada uno con
            # su prefijo, así que no se pisan entre ellos.
            if fuente == "nopub_seiscomp":
                archivo = os.path.join(
                    "datos", "no_pub_desde_2_5_seiscomp_estricto.csv")
                origen = "seiscomp"
            else:
                archivo = os.path.join("datos",
                                       "no_pub_desde_2_5_estricto.csv")
                origen = "seisan"
            if not os.path.isfile(archivo):
                self._log("No se encontró %s (procese los catálogos primero)."
                          % archivo)
                return False
            # --salida evita que el JSON de los no publicados pise el de la
            # fuente principal: comparten parseo, no archivo de salida.
            self._popen([_script("generajson.py"), archivo, origen,
                         "--salida=%s" % vista_clave])
        else:
            return False
        json_path = os.path.join("datos", "eventos_%s.json" % vista_clave)
        if os.path.isfile(json_path):
            self._log("JSON generado: %s" % json_path)
            return True
        self._log("No se generó %s." % json_path)
        return False

    def _accion_fuente(self, fuente):
        """Genera una fuente puntual en segundo plano (generación perezosa)."""
        vista_clave = FUENTE_A_VISTA.get(fuente)
        if vista_clave not in VISTAS_POR_CLAVE:
            return

        def tarea():
            if fuente == "eventquery":
                # La concatenación no tiene script que marque la etapa, así que
                # se fija a mano (es la primera de FUENTE_PLAN).
                self._fijar_etapa(0)
            self._procesar_fuente(fuente)

        def al_terminar():
            self._abrir_panel_en_tab(vista_clave)
            self._actualizar_gate()

        self._iniciar(tarea, on_fin=al_terminar,
                      plan=FUENTE_PLAN.get(fuente))

    def _firma_catalogo(self, clave):
        """
        Qué archivos definen el contenido de esa pestaña de catálogo.

        Devuelve una tupla de (ruta, mtime, tamaño) con la que se compara la
        firma guardada para saber si hay que volver a construir, o None si no
        hay datos con que construirla.

        Para eventquery se usan los new_2_*.csv y no el todos_eventquery.csv
        derivado, por dos razones: el derivado puede no existir todavía (lo
        arma _concatenar_eventquery al construir, así que antes de construir no
        hay nada que mirar), y si entra un new_2 nuevo hay que rehacer el
        catálogo aunque el derivado todavía sea el de la corrida anterior.
        """
        if clave == "seiscomp":
            par = self._par_seiscomp_para_catalogo()
            if par is None:
                return None
            rutas = (par["eventos"], par["fases"])
        elif clave == "eventquery":
            rutas = self._partes_eventquery()
            if not rutas:
                return None
        else:
            ruta = os.path.join("datos", "salida_collect.csv")
            if not os.path.isfile(ruta):
                return None
            rutas = [ruta]
        firma = []
        for ruta in rutas:
            if not os.path.isfile(ruta):
                return None
            try:
                st = os.stat(ruta)
            except OSError:
                return None
            firma.append((ruta, st.st_mtime, st.st_size))
        return tuple(firma)

    def _construir_catalogo(self, clave, seleccionar=False):
        """
        Construye (o reusa) el catálogo de una pestaña.

        La firma evita rehacer la tabla en cada visita, que con catálogos grandes
        se nota; y si cambió algún archivo de entrada se rehace sola, que es lo
        que pasa después de un análisis nuevo.
        """
        panel = self.catalogos.get(clave)
        if panel is None:
            return
        firma = self._firma_catalogo(clave)
        if firma is None:
            # No hay datos: se deja el placeholder, que explica qué hacer.
            return
        if (panel["construido"] and panel.get("firma") == firma
                and panel["frame"].winfo_children()):
            return
        if clave == "seiscomp":
            par = self._par_seiscomp_para_catalogo()
            if par is None:
                return
            self._abrir_revisor(par, seleccionar=seleccionar)
        else:
            self._abrir_catalogo(ARCHIVO_CATALOGO[clave], clave,
                                 seleccionar=seleccionar)
        if panel["frame"].winfo_children():
            panel["construido"] = True
            panel["firma"] = firma
        else:
            # _abrir_revisor borra los hijos antes de construir y no los repone
            # si algo falla, así que la pestaña quedaría en blanco. El mensaje
            # va siempre, haya estado construida antes o no.
            panel["construido"] = False
            ttk.Label(panel["frame"], justify=CENTER,
                      text=("No se pudo abrir el catálogo de %s."
                            % panel["titulo"])).pack(expand=YES)

    def _abrir_catalogo(self, nombre_archivo, etiqueta, seleccionar=True):
        """Muestra el catálogo crudo de una fuente en su pestaña."""
        rs = self._importar_revisor()
        if rs is None:
            return
        ruta = os.path.join("datos", nombre_archivo)
        marco = (self.seisan_frame if etiqueta == "seisan"
                 else self.eventquery_frame)
        if etiqueta == "eventquery" and (not os.path.isfile(ruta)
                                         or os.path.getsize(ruta) == 0):
            # El catálogo publicado es la unión de los new_2_*.csv, que arma
            # _concatenar_eventquery. Sin esto, consultar el catálogo por acá
            # exigiría antes haber corrido «Datos de eventquery», que es un paso
            # extra que no tiene nada que ver con consultar: se arma acá y se
            # abre en un solo paso, como el de Seisan.
            self._concatenar_eventquery()
        if not os.path.isfile(ruta):
            self._log("No se encontró %s. Pulse «Procesar catálogos» primero."
                      % ruta)
            return
        for w in list(marco.winfo_children()):
            w.destroy()
        atribuciones = (self._mapa_analistas_eventquery()
                        if etiqueta == "eventquery" else None)
        try:
            ok = rs.abrir_catalogo(marco, ruta, etiqueta, log=self._log,
                                    cwd=self.cwd, atribuciones=atribuciones)
        except Exception as e:
            self._log("[error] catálogo %s: %s" % (etiqueta, e))
            return
        if not ok:
            self._log("No se pudo abrir el catálogo de %s." % etiqueta)
            return
        if seleccionar:
            self.cuaderno.select(marco)
        self._ajustar_ventana()
        self._log("Catálogo abierto: %s" % os.path.basename(ruta))

    def _al_cambiar_pestana(self, _evento=None):
        """
        Construye (o reusa) el panel de la vista al abrir su pestaña.

        Hace falta porque el botón de una fuente ya procesada queda apagado, así
        que la pestaña es la única vía para volver a ver el panel (por ejemplo,
        al reabrir la aplicación sobre una carpeta ya analizada). Si el CSV de
        entrada existe pero el JSON no (o quedó viejo), se genera acá en
        segundo plano.
        """
        self._marcar_pestana_activa()
        actual = self.cuaderno.select()
        for clave, panel in self.catalogos.items():
            if str(panel["frame"]) != actual:
                continue
            self._construir_catalogo(clave)
            break
        for fuente, panel in self.noact.items():
            if str(panel["frame"]) != actual:
                continue
            self._abrir_no_actualizados(fuente)
            break
        for clave, panel in self.paneles.items():
            if str(panel["frame"]) != actual:
                continue
            self._abrir_panel_si_puede(clave)
            break

    def _abrir_panel_si_puede(self, clave):
        """
        Abre el panel de una vista, generándolo si hace falta.

        Si el JSON está al día, se muestra; si el CSV de entrada existe pero el
        JSON falta o quedó viejo, se procesa la fuente en segundo plano y el
        panel se abre al terminar. Si no hay entrada, se deja el placeholder.
        """
        if self._analisis_obsoleto():
            # Los catálogos son más nuevos que el análisis: no se muestra un
            # panel viejo como si fuera actual.
            self._placeholder_panel(
                clave, "Los catálogos cambiaron desde el último análisis.\n\n"
                       "Pulse «Procesar catálogos» para regenerar el panel.")
            return
        if self._vista_procesada(clave):
            self._abrir_panel_en_tab(clave)
            return
        vista = VISTAS_POR_CLAVE.get(clave)
        if vista is None or not os.path.isfile(vista["entrada"]):
            return
        # Sin esto, abrir la pestaña mientras corre otra tarea arrancaría un
        # segundo procesamiento que _iniciar descartaría sin dejar rastro.
        if self.ocupado:
            return
        self._placeholder_panel(
            clave, "Procesando esta fuente…\n\nSe genera el panel a partir de "
                   "%s." % os.path.basename(vista["entrada"]))
        self._accion_fuente(VISTA_A_FUENTE[clave])

    def _abrir_panel_en_tab(self, clave):
        """Construye (una sola vez) el panel de la vista y la selecciona."""
        vista = VISTAS_POR_CLAVE.get(clave)
        panel = self.paneles.get(clave)
        if vista is None or panel is None:
            return
        # Sin CSV de entrada vigente no se abre el panel, aunque el JSON exista:
        # podría ser el de una corrida anterior cuyo CSV se borró por quedar
        # vacío (ver _procesar_fuente y _borrar en compara.py). _vista_procesada
        # exige que el JSON sea igual o más nuevo que su entrada.
        if not self._vista_procesada(clave):
            self._log("No hay datos vigentes de %s; no se abre el panel."
                      % vista["etiqueta"])
            self._placeholder_panel(
                clave, "No hay datos de %s para mostrar.\n\nPulse «Procesar "
                       "catálogos» para generarlos." % vista["etiqueta"])
            return
        archivo = os.path.join("datos", "eventos_%s.json" % clave)
        mtime = os.path.getmtime(archivo)
        # Un panel ya construido con el mismo JSON se reusa tal cual: cambiar
        # de pestaña no debe rehacer perfiles ni redibujar. El frame tiene que
        # seguir teniendo algo dentro: si algún camino lo dejó vacío, el caché
        # lo daba por bueno y la pestaña quedaba muda, sin forma de recuperarla
        # con el botón de esa fuente ya deshabilitado por «ya procesada».
        if (panel["construido"] and panel.get("mtime") == mtime
                and panel["frame"].winfo_children()):
            self.cuaderno.select(panel["frame"])
            return
        for w in list(panel["frame"].winfo_children()):
            w.destroy()
        panel["construido"] = False
        try:
            import plotear
            ok = plotear.abrir_panel(panel["frame"], archivo, vista["fuente"],
                                     etiqueta_fuente=vista["etiqueta"],
                                     vista=clave)
        except Exception as e:
            ok = False
            self._log("[error] panel %s: %s" % (clave, e))
        if not ok:
            self._log("No se pudo abrir el panel de %s "
                      "(¿backend interactivo?)." % vista["etiqueta"])
            ttk.Label(panel["frame"], justify=CENTER,
                      text="No se pudo dibujar el panel.").pack(expand=YES)
            return
        panel["construido"] = True
        panel["mtime"] = mtime
        self.cuaderno.select(panel["frame"])
        # El panel es lo más ancho de la app: sin esto la figura y parte de la
        # tabla quedan fuera de la ventana.
        self._ajustar_ventana()
        self._log("Panel abierto (%s)." % clave)

    def _abrir_no_actualizados(self, fuente, contenedor=None):
        """
        Muestra el listado de eventos no actualizados de una fuente.

        No calcula nada: los datos salen de datos/atribucion_<fuente>.csv, que
        escribe la corrida del análisis. Como el botón de la fuente queda
        apagado cuando ya está procesada, la pestaña es la única forma de ver
        el listado al reabrir la aplicación sobre una carpeta ya analizada.

        Distingue los tres estados posibles, porque un mismo "no se puede
        mostrar" significa cosas distintas: que el análisis nunca corrió, que
        corrió sin encontrar cruces, o que hay datos. Si se pasa 'contenedor'
        se llena ese marco (ventana de consulta); si no, la pestaña del
        cuaderno principal, con su caché por mtime.
        """
        panel = self.noact.get(fuente)
        if contenedor is None:
            if panel is None:
                return
            contenedor = panel["frame"]
        etiqueta = {"seisan": "Seisan", "seiscomp": "SeisComp"}[fuente]
        csv_noact = os.path.join("datos", "atribucion_%s.csv" % fuente)
        # El informe .txt se escribe siempre que corre la comparación (aunque
        # quede sin filas), así que dice si el análisis llegó a hacer el cruce.
        informe = os.path.join(
            "informes", "no_act_%sestricto.txt"
            % ("" if fuente == "seisan" else "seiscomp_"))

        if not os.path.isfile(csv_noact):
            for w in list(contenedor.winfo_children()):
                w.destroy()
            if panel is not None:
                panel["construido"] = False
            texto = ("Todavía no hay nada para mostrar.\n\nPulse "
                     "«Procesar catálogos» para generarlo."
                     if not os.path.isfile(informe) else
                     "La comparación se ejecutó, pero no encontró ningún "
                     "cruce entre %s y lo publicado.\n\nNo hay eventos "
                     "no actualizados." % etiqueta)
            ttk.Label(contenedor, justify=CENTER, text=texto).pack(
                expand=YES)
            return

        mtime = os.path.getmtime(csv_noact)
        if (panel is not None and panel["construido"]
                and panel.get("mtime") == mtime
                and contenedor.winfo_children()):
            return
        for w in list(contenedor.winfo_children()):
            w.destroy()
        if panel is not None:
            panel["construido"] = False
        rs = self._importar_revisor()
        if rs is None:
            return
        try:
            ok = rs.abrir_no_actualizados(contenedor, fuente,
                                          log=self._log, cwd=self.cwd)
        except Exception as e:
            ok = False
            self._log("[error] no actualizados %s: %s" % (fuente, e))
        if not ok:
            ttk.Label(contenedor, justify=CENTER,
                      text="No se pudo leer el listado de %s." % etiqueta
                      ).pack(expand=YES)
            return
        if panel is not None:
            panel["construido"] = True
            panel["mtime"] = mtime
        self._ajustar_ventana()

    def _ver_no_actualizados(self):
        """
        Ventana con el listado de no actualizados, una pestaña por fuente.

        SeisComp va primero y por defecto; Seisan después. Cada pestaña se
        arma recién al seleccionarla, reutilizando _abrir_no_actualizados
        sobre el marco de esa pestaña.
        """
        top = ttk.Toplevel(title="No actualizados", master=self.raiz)
        top.geometry("1000x560")
        cuaderno = ttk.Notebook(top)
        cuaderno.pack(fill=BOTH, expand=YES)
        fuentes = (("seiscomp", "SeisComp"), ("seisan", "Seisan"))
        marcos, construido = {}, {}
        for clave, etiqueta in fuentes:
            marco = ttk.Frame(cuaderno)
            cuaderno.add(marco, text=etiqueta)
            marcos[clave] = marco
            construido[clave] = False

        def _construir(clave):
            if construido[clave]:
                return
            construido[clave] = True
            self._abrir_no_actualizados(clave, contenedor=marcos[clave])

        def _al_cambiar(_evento=None):
            actual = cuaderno.select()
            for clave, marco in marcos.items():
                if str(marco) == actual:
                    _construir(clave)
                    break

        cuaderno.bind("<<NotebookTabChanged>>", _al_cambiar)
        _construir("seiscomp")

    def _concatenar_eventquery(self, forzar=False):
        """
        Arma datos/todos_eventquery.csv con todos los new_2_*.csv.

        Es un derivado puro de esos archivos, así que se saltea si la salida es
        más nueva que todas las entradas: no hay forma de que esté desactualizada
        y el trabajo es una pasada completa sobre el archivo. Antes se rehacía
        siempre y por eso reabrir la app costaba una concatización entera.

        forzar=True lo usa «Procesar catálogos», que acaba de regenerar todo y
        quiere dejar el concatenado rehecho aunque las fechas den por bien.
        """
        carpeta = "datos"
        salida = os.path.join(carpeta, "todos_eventquery.csv")
        try:
            partes = sorted(n for n in os.listdir(carpeta)
                            if n.startswith("new_2_") and n.endswith(".csv"))
        except OSError:
            partes = []
        if (not forzar and partes
                and _derivado_al_dia(salida, partes, carpeta)):
            self._log("Reutilizado %s (ya estaba al día con %d new_2_*.csv)."
                      % (salida, len(partes)))
            return
        self._log("Concatenando %s/new_2_*.csv -> %s" % (carpeta, salida))
        primera = True
        with open(salida, "w") as destino:
            for nombre in partes:
                ruta = os.path.join(carpeta, nombre)
                with open(ruta) as origen:
                    for i, linea in enumerate(origen):
                        if i == 0 and not primera:
                            continue
                        destino.write(linea)
                primera = False

    def _asegurar_parametros_seiscomp(self):
        """
        Deja datos/seiscomp_parametros.csv al día desde la exportación.

        Ese archivo es el que permite atribuir los eventos de eventquery a un
        responsable de SeisComp (el operador de la solución preferred). Antes
        solo se generaba al pulsar «Datos de SeisComp»: si la exportación la
        había descargado la solicitud de catálogos, el cruce de eventquery
        quedaba solo contra Seisan y casi ningún evento mostraba responsable.

        Es idempotente: si el archivo es más nuevo que la exportación no hace
        nada. No necesita la base de SeisComp, solo el CSV exportado.
        """
        par = self._par_seiscomp_para_catalogo()
        if par is None:
            return
        destino = os.path.join("datos", "seiscomp_parametros.csv")
        try:
            if (os.path.isfile(destino)
                    and os.path.getmtime(destino)
                    >= os.path.getmtime(par["eventos"])):
                return
        except OSError:
            pass
        self._log("Generando la atribución de SeisComp desde %s..."
                  % os.path.basename(par["eventos"]))
        self._popen([_script("seiscomp_a_parametros.py"), par["eventos"]])

    def _mapa_analistas_eventquery(self):
        """
        {fecha_hora: "Seisan: Jere; SeisComp: mdur"} para la columna del
        catálogo de eventquery.

        eventquery no informa el responsable; el nombre se deduce cruzando cada
        evento publicado con las soluciones locales de Seisan y SeisComp. Se
        reusa la misma lógica del panel (generajson) para que la columna y la
        viñeta no puedan decir cosas distintas.
        """
        try:
            import generajson as gj
        except Exception as e:
            self._log("[aviso] no se pudo deducir el analista probable: %s" % e)
            return {}
        indices = []
        for nombre in ("seiscomp", "seisan"):
            indice = gj._cargar_atribucion(nombre)
            if indice:
                indices.append(indice)
        if not indices:
            return {}
        rs = self._importar_revisor()
        if rs is None:
            return {}
        ruta = os.path.join("datos", "todos_eventquery.csv")
        if not os.path.isfile(ruta):
            return {}
        etiqueta = {"seiscomp": "SeisComp", "seisan": "Seisan"}
        mapa = {}
        for fila in rs._leer_catalogo(ruta):
            fecha_hora = str(fila.get("Fecha_Hora", "")).strip()
            if not fecha_hora:
                continue
            try:
                lat = float(fila.get("Latitud"))
                lon = float(fila.get("Longitud"))
            except (TypeError, ValueError):
                continue
            partes = []
            for indice in indices:
                encontradas = gj._analistas_para_evento(indice, fecha_hora,
                                                        lat, lon)
                for e in encontradas or ():
                    nombres = ", ".join(e.get("analistas") or [])
                    partes.append("%s: %s"
                                  % (etiqueta.get(e.get("fuente"),
                                                  e.get("fuente")), nombres))
            if partes:
                mapa[fecha_hora] = "; ".join(partes)
        return mapa

    def _atribuir_para_eventquery(self):
        """
        Corre la atribución de Solutiones locales al catálogo publicado si hace
        falta, antes de generar el JSON de eventquery.

        Sin esto habría que repetir el análisis completo después de exportar
        SeisComp, porque la atribución vive dentro del plan principal y ahí se
        saltea si seiscomp_parametros.csv todavía no existe. Comparar
        mtime contra el archivo de salida es lo que hace que el flujo se
        autorrepare: si la exportación es más nueva que la atribución, esta
        está vieja y hay que rehacerla.

        Atribuir es un extra y no bloquea el panel, así que si falta una fuente
        se sigue igual. Lo que no se hace es seguir en silencio: queda escrito
        contra qué fuentes se atribuyó y contra cuáles no, con el motivo. Sin
        eso, un panel con la atribución casi vacía se ve igual que uno
        completo, y no hay forma de notar que falta el dato.
        """
        base = os.path.join("datos", "new_2_" + self.base)
        if not os.path.isfile(base):
            return
        try:
            mtime_base = os.path.getmtime(base)
        except OSError:
            return
        candidatos = (
            (os.path.join("datos", "seiscomp_parametros.csv"), "seiscomp"),
            (os.path.join("datos", "salida_collect.csv"), "seisan"),
        )
        usadas = []
        omitidas = []
        for entrada, etiqueta in candidatos:
            if not os.path.isfile(entrada) or os.path.getsize(entrada) == 0:
                omitidas.append((etiqueta, "no está %s" % entrada))
                continue
            # Está vencida si el catálogo o las soluciones locales son más
            # recientes que ella: si se reexporta SeisComp, el archivo local
            # cambia y el cruce hay que rehacerlo aunque el catálogo no se haya
            # tocado.
            mas_reciente = max(mtime_base, os.path.getmtime(entrada))
            salida = os.path.join("datos", "atribucion_%s.csv" % etiqueta)
            if (os.path.isfile(salida)
                    and os.path.getmtime(salida) >= mas_reciente):
                usadas.append(etiqueta)
                continue
            self._log("Actualizando la atribución a %s..." % etiqueta)
            comando = [_script("compara.py"), base, entrada]
            if etiqueta != "seisan":
                comando.append(etiqueta + "_")
            self._popen(comando)
            if os.path.isfile(salida):
                usadas.append(etiqueta)
        # Atribuir es un extra y no bloquea el panel, así que una fuente que
        # falta no es un error: pero SÍ tiene que quedar a la vista. El silencio
        # es lo peligroso acá, porque el panel igual abre con todos los eventos
        # y parece completo, solo que casi ninguno muestra responsable.
        if usadas:
            self._log("Atribución de eventquery: %s."
                      % " y ".join(usadas))
        for etiqueta, motivo in omitidas:
            self._log("Sin atribución contra %s (%s). "
                      "Pulse «Procesar catálogos» si la quiere."
                      % (etiqueta, motivo))

    def _rm(self, ruta):
        try:
            os.remove(ruta)
        except OSError:
            pass

    # --------------------------------------------------- ver repetidos
    def _abrir_descargas(self):
        """Abre la carpeta de descargas del directorio de trabajo."""
        carpeta = descargas.carpeta_descargas(self.cwd)
        if descargas.abrir_carpeta(carpeta):
            self._log("Descargas: %s" % carpeta)
        else:
            self._log("No se pudo abrir el explorador de archivos; la carpeta "
                      "de descargas es %s" % carpeta)

    def _ver_repetidos(self):
        top = ttk.Toplevel(title="Eventos repetidos", master=self.raiz)
        top.geometry("760x480")

        marco = ttk.Frame(top, padding=10)
        marco.pack(fill=BOTH, expand=YES)

        cols = ("archivo", "eventos")
        arbol = ttk.Treeview(marco, columns=cols, show="headings", height=6)
        arbol.heading("archivo", text="Archivo")
        arbol.heading("eventos", text="Eventos")
        arbol.column("archivo", width=320, anchor=W)
        arbol.column("eventos", width=80, anchor=CENTER)
        arbol.pack(fill=X)

        contenido = ScrolledText(marco, padding=4, autohide=True, height=14)
        contenido.pack(fill=BOTH, expand=YES, pady=(8, 0))
        contenido.text.configure(state=DISABLED, font=("Consolas", 9))

        rutas = {}
        totales = {}
        for titulo, ruta in REP_FILES:
            if os.path.isfile(ruta):
                with open(ruta) as f:
                    n = sum(1 for _ in f)
                n = n - 1 if n > 0 else 0
                etiqueta = "%s  (%s)" % (titulo, os.path.basename(ruta))
            else:
                n = 0
                etiqueta = "%s  (no generado)" % titulo
            iid = arbol.insert("", END, values=(etiqueta, n))
            rutas[iid] = ruta
            totales[iid] = n

        MAX_VISIBLES = 2000

        def al_seleccionar(evento=None):
            sel = arbol.selection()
            if not sel:
                return
            iid = sel[0]
            ruta = rutas[iid]
            contenido.text.configure(state=NORMAL)
            contenido.text.delete("1.0", END)
            if os.path.isfile(ruta):
                lineas = []
                with open(ruta) as f:
                    for _ in range(MAX_VISIBLES):
                        linea = f.readline()
                        if not linea:
                            break
                        lineas.append(linea)
                contenido.text.insert(END, "".join(lineas))
                n_total = totales[iid]
                if n_total > MAX_VISIBLES:
                    leftovers = n_total - (len(lineas) - 1)
                    contenido.text.insert(
                        END, "\n... (%d líneas más, de %d en total)"
                        % (leftovers, n_total))
            else:
                contenido.text.insert(END, "(no generado)")
            contenido.text.configure(state=DISABLED)
            # El botón se enciende con el informe elegido y se apaga cuando no
            # hay archivo o no tiene nada adentro.
            boton_descargar.configure(
                state="normal" if totales.get(iid) else "disabled")

        def al_descargar():
            sel = arbol.selection()
            if not sel:
                return
            iid = sel[0]
            ruta = rutas[iid]
            # Se baja el informe entero, no lo que entra en pantalla: la
            # ventana muestra las primeras MAX_VISIBLES solo para que siga
            # siendo usable, y un informe recortado no sirve para nada.
            lineas = descargas.leer_lineas(ruta)
            if not lineas:
                return
            nombre = os.path.splitext(os.path.basename(ruta))[0]
            escrito = descargas.descargar_texto(top, lineas, nombre)
            if escrito:
                self._log("Descargado el informe de repetidos %s a %s"
                          % (nombre, escrito))

        marco_botones = ttk.Frame(marco)
        marco_botones.pack(fill=X, pady=(8, 0))
        boton_descargar = ttk.Button(marco_botones, text="Descargar informe",
                                     command=al_descargar, state="disabled",
                                     bootstyle="primary-outline")
        boton_descargar.pack(side=RIGHT)
        ttk.Label(marco_botones,
                  text="Se descarga el informe completo del archivo "
                       "seleccionado.").pack(side=LEFT)

        arbol.bind("<<TreeviewSelect>>", al_seleccionar)
        hijos = arbol.get_children()
        if hijos:
            arbol.selection_set(hijos[0])
            al_seleccionar()

    def _ver_no_publicados(self, fuente=None):
        """
        Ventana con el listado de no publicados, una pestaña por fuente.

        SeisComp va primero y por defecto; Seisan después. Cada pestaña se
        arma recién al seleccionarla, para no construir las dos de golpe (el
        listado de Seisan se pide a demanda). Si se pasa 'fuente' se abre
        directo en esa pestaña, para no romper al generador de capturas.
        """
        top = ttk.Toplevel(title="No publicados", master=self.raiz)
        top.geometry("900x560")
        cuaderno = ttk.Notebook(top)
        cuaderno.pack(fill=BOTH, expand=YES)
        fuentes = (("seiscomp", "SeisComp"), ("seisan", "Seisan"))
        marcos, construido = {}, {}
        for clave, etiqueta in fuentes:
            marco = ttk.Frame(cuaderno)
            cuaderno.add(marco, text=etiqueta)
            marcos[clave] = marco
            construido[clave] = False

        def _construir(clave):
            if construido[clave]:
                return
            construido[clave] = True
            self._construir_tabla_no_publicados(marcos[clave], clave)

        def _al_cambiar(_evento=None):
            actual = cuaderno.select()
            for clave, marco in marcos.items():
                if str(marco) == actual:
                    _construir(clave)
                    break

        cuaderno.bind("<<NotebookTabChanged>>", _al_cambiar)
        inicial = fuente if fuente in marcos else "seiscomp"
        if inicial != "seiscomp":
            cuaderno.select(marcos[inicial])
        _construir(inicial)

    def _construir_tabla_no_publicados(self, contenedor, fuente):
        """
        Listado de los eventos no publicados (mag >= 2.5) de una fuente.

        Complementa al panel/mapa: acá se ve el conjunto completo en una tabla,
        sin tener que ir evento por evento en el ploteo.

        Se ordena con clic en el encabezado y se filtra por texto. La descarga
        arma el archivo con el filtro y el orden puestos; «Descargar todo» lo
        escribe entero, que es lo que se reparte cuando el listado va completo.
        """
        ruta = os.path.join(
            "datos", "no_pub_desde_2_5_%sestricto.csv"
            % ("" if fuente == "seisan" else "seiscomp_"))
        marco = ttk.Frame(contenedor, padding=10)
        marco.pack(fill=BOTH, expand=YES)

        filas = []
        if os.path.isfile(ruta):
            try:
                with open(ruta, encoding="utf-8-sig", newline="") as f:
                    filas = list(csv.DictReader(f))
            except OSError as e:
                self._log("[error] no publicados %s: %s" % (fuente, e))

        columnas = [("Fecha_Hora", "Fecha y hora", 150),
                    ("Latitud", "Latitud", 90),
                    ("Longitud", "Longitud", 90),
                    ("Prof.", "Prof. km", 80),
                    ("Mag.", "Mag.", 70),
                    ("Tipo_mag.", "Tipo mag.", 80),
                    ("Analista", "Analista", 120)]
        claves = [c for c, _, _ in columnas]
        # Profundidad, magnitud y coordenadas se ordenan como número: por texto
        # un 9.0 quedaría después de un 10.0, que es justo lo que uno no quiere
        # al revisar un listado por magnitud.
        ordenables = {"Latitud", "Longitud", "Prof.", "Mag."}
        estado = {"orden": None, "desc": False, "elegidas": list(filas)}

        marco_controles = ttk.Frame(marco)
        marco_controles.pack(fill=X, pady=(0, 6))
        ttk.Label(marco_controles, text="Filtrar:").pack(side=LEFT)
        caja_filtro = ttk.Entry(marco_controles, width=24)
        caja_filtro.pack(side=LEFT, padx=(4, 10))
        etiqueta_estado = ttk.Label(marco_controles, text="",
                                    bootstyle="secondary")
        etiqueta_estado.pack(side=LEFT)

        def _valores(fila):
            return [str(fila.get(c, "") or "") for c in claves]

        def _ver_mapa(_evento=None):
            """Abre planta+perfil del evento elegido (ploteo de un evento suelto)."""
            seleccion = arbol.selection()
            if not seleccion:
                return
            try:
                fila = estado["elegidas"][int(seleccion[0])]
            except (ValueError, IndexError):
                return

            def _num(clave):
                try:
                    return float(str(fila.get(clave, "")).strip())
                except (TypeError, ValueError):
                    return None

            if _num("Latitud") is None or _num("Longitud") is None:
                etiqueta_estado.config(text="El evento no tiene coordenadas.")
                return
            evento = {
                "fecha hora": fila.get("Fecha_Hora", ""),
                "latitud": _num("Latitud"), "longitud": _num("Longitud"),
                "prof": _num("Prof."), "magnitud": fila.get("Mag.", ""),
                "tipo": fila.get("Tipo_mag.", ""),
                "analista": fila.get("Analista", ""),
            }
            try:
                import plotear
                plotear.abrir_evento(evento, fuente)
            except Exception as e:
                self._log("[error] no se pudo plotear: %s" % e)
                etiqueta_estado.config(text="No se pudo plotear el evento.")

        def _al_descargar(todas=False):
            elegidas = filas if todas else estado["elegidas"]
            if not elegidas:
                return
            escrito = descargas.descargar_tabla(
                contenedor, [t for _, t, _ in columnas],
                [_valores(f) for f in elegidas],
                "no publicados %s" % fuente, aviso=False)
            if not escrito:
                return
            aviso = "%d evento%s descargados a %s" % (
                len(elegidas), "" if len(elegidas) == 1 else "s",
                os.path.basename(escrito))
            etiqueta_estado.config(text=aviso)
            self._log(aviso)

        boton_descargar = ttk.Button(marco_controles, text="Descargar",
                                     command=_al_descargar, state="disabled",
                                     bootstyle="primary-outline")
        boton_descargar.pack(side=RIGHT)
        ttk.Button(marco_controles, text="Descargar todo",
                   command=lambda: _al_descargar(todas=True),
                   bootstyle="primary-outline").pack(side=RIGHT, padx=(6, 0))
        # Aviso corto: el detalle se abre con doble clic, no hay botón.
        ttk.Label(marco_controles, text="Doble clic plotea",
                  bootstyle="secondary").pack(side=RIGHT, padx=(10, 0))

        marco_tabla = ttk.Frame(marco)
        marco_tabla.pack(fill=BOTH, expand=YES)
        arbol = ttk.Treeview(marco_tabla, columns=claves, show="headings",
                             selectmode="browse")
        for clave, tit, ancho in columnas:
            arbol.heading(clave, text=tit,
                          command=lambda c=clave: _al_ordenar(c))
            arbol.column(clave, width=ancho, minwidth=50, stretch=False)
        barra_v = ttk.Scrollbar(marco_tabla, orient="vertical",
                                command=arbol.yview)
        arbol.configure(yscrollcommand=barra_v.set)
        barra_h = ttk.Scrollbar(marco_tabla, orient="horizontal",
                                command=arbol.xview)
        arbol.configure(xscrollcommand=barra_h.set)
        arbol.pack(side="left", fill="both", expand=True)
        barra_v.pack(side="right", fill="y")
        barra_h.pack(side="bottom", fill="x")

        # Doble clic (o Enter con la fila elegida) abre planta+perfil del evento.
        arbol.bind("<Double-1>", _ver_mapa)
        arbol.bind("<Return>", _ver_mapa)

        def _clave_orden(fila, columna):
            if columna in ordenables:
                try:
                    return (0, float(str(fila.get(columna, "")).strip()), "")
                except (TypeError, ValueError):
                    pass
            return (1, 0.0, str(fila.get(columna, "")).strip().lower())

        def _ordenar(evs, columna, desc=False):
            if columna is None:
                return list(evs)
            con = [f for f in evs if str(f.get(columna, "")).strip() != ""]
            sin = [f for f in evs if str(f.get(columna, "")).strip() == ""]
            con.sort(key=lambda f: _clave_orden(f, columna), reverse=desc)
            return con + sin

        def _al_ordenar(columna):
            if estado["orden"] == columna:
                estado["desc"] = not estado["desc"]
            else:
                estado["orden"] = columna
                estado["desc"] = False
            _llenar()

        def _llenar(_evento=None):
            texto = caja_filtro.get().strip().lower()
            if texto:
                elegidas = [f for f in filas
                            if texto in " ".join(
                                str(v).lower() for v in f.values())]
            else:
                elegidas = list(filas)
            elegidas = _ordenar(elegidas, estado["orden"], estado["desc"])
            estado["elegidas"] = elegidas
            for item in arbol.get_children():
                arbol.delete(item)
            for i, fila in enumerate(elegidas):
                arbol.insert("", "end", iid=str(i), values=_valores(fila))
            etiqueta_estado.config(
                text="%d de %d eventos" % (len(elegidas), len(filas))
                if len(elegidas) != len(filas)
                else "%d evento%s" % (len(filas),
                                      "" if len(filas) == 1 else "s"))
            boton_descargar.configure(
                state="normal" if elegidas else "disabled")

        caja_filtro.bind("<KeyRelease>", _llenar)
        _llenar()
        self._log("No publicados de %s: %d eventos." % (fuente, len(filas)))

    # ----------------------------------------------------------- SeisComp
    # Todo lo de SeisComp se apoya en revisa_seiscomp.py, que ya sabe qué es
    # una exportación, cómo se lee la ventana del catálogo y cómo se dibuja la
    # revisión. Acá solo se orquesta: qué se le pregunta al usuario, cuándo se
    # exporta y en qué pestaña se muestra.

    def _importar_revisor(self):
        """Carga revisa_seiscomp.py, o avisa por qué no pudo."""
        try:
            import revisa_seiscomp
            return revisa_seiscomp
        except Exception as e:
            self._log("[error] no se pudo cargar revisa_seiscomp.py: %s" % e)
            return None

    def _ventana_del_catalogo(self):
        """
        (desde, hasta) con las fechas del catálogo de entrada, o None.

        Se le pregunta al revisor y no se recalcula acá: el formato del
        catálogo tiene variantes (con 'T' y 'Z', con espacio) y duplicar esa
        lógica haría que un día los dos caminos dejaran de coincidir.
        """
        if not self.archivo or not os.path.isfile(self.archivo):
            return None
        rs = self._importar_revisor()
        if rs is None:
            return None
        return rs._ventana_del_catalogo(self.archivo)

    def _pares_seiscomp(self):
        """
        Las exportaciones de SeisComp de datos/ que terminaron de escribirse.

        Se filtran por la marca '.completo' porque una exportación cortada a
        mitad deja el CSV de eventos a medias, y plotearla daría la impresión
        de que en esa ventana no hubo más eventos de los que hubo.
        """
        rs = self._importar_revisor()
        if rs is None:
            return []
        return [p for p in rs._pares_disponibles(self.cwd)
                if self._exportacion_completa(p["eventos"])
                and os.path.isfile(p["fases"] or "")]

    @staticmethod
    def _ruta_de_marca(ruta_eventos):
        """
        Ruta del archivo que marca que aquella exportación terminó.

        Esto devuelve una RUTA, no un sí/no. Por eso el predicado está aparte,
        en _exportacion_completa: usar esta ruta directamente como condición
        nunca avisó nada, porque una ruta no vacía siempre es verdadera y la
        marca dejó de filtrar exportaciones cortadas sin que se notara.
        """
        base, extension = os.path.splitext(ruta_eventos)
        return "%s%s.completo" % (base, extension or ".csv")

    @classmethod
    def _exportacion_completa(cls, ruta_eventos):
        """Si la exportación de esa ventana tiene la marca de que terminó."""
        return os.path.isfile(cls._ruta_de_marca(ruta_eventos))

    def _par_seiscomp_para_catalogo(self, silencioso=False):
        """
        El par exportado que mejor cubre la ventana del catálogo, o None.

        Va por cobertura y no por fecha de modificación a propósito: cuando se
        revisan varios períodos en la misma carpeta, la última exportación no
        es la que corresponde al catálogo que se está mirando ahora.

        Con 'silencioso' no avisa cuando hay exportaciones pero ninguna cubre la
        ventana. Lo necesita la compuerta del botón, que consulta esto en cada
        cambio de estado y llenaría el registro de ese mismo aviso.
        """
        rs = self._importar_revisor()
        if rs is None:
            return None
        pares = self._pares_seiscomp()
        if not pares:
            return None
        par = rs._elegir_par(pares, self._ventana_del_catalogo())
        if par is None and pares and not silencioso:
            # Sin cobertura no se elige el más reciente a ciegas: se avisa y
            # deja que el usuario elija, que es lo seguro.
            self._log("Hay exportaciones de SeisComp en datos/, pero ninguna "
                      "se superpone con la ventana de este catálogo.")
        return par

    def _anunciar_cobertura(self, par):
        """Deja en el registro cuánto de la ventana del catálogo se cubrió."""
        rs = self._importar_revisor()
        if rs is None:
            return
        ventana = self._ventana_del_catalogo()
        if ventana is None:
            return
        propia = rs._ventana_del_nombre(os.path.basename(par["eventos"]))
        inicio, fin, fraccion = rs._cobertura(propia, ventana)
        if fraccion <= 0:
            return
        if fraccion < 0.999:
            self._log("La exportación cubre el %.0f%% de la ventana del "
                      "catálogo (%s a %s)."
                      % (fraccion * 100,
                         inicio.strftime("%Y-%m-%d %H:%M"),
                         fin.strftime("%Y-%m-%d %H:%M")))

    def _abrir_revisor(self, par, seleccionar=True):
        """Muestra la revisión de SeisComp en su pestaña."""
        rs = self._importar_revisor()
        if rs is None:
            return
        for w in list(self.seiscomp_frame.winfo_children()):
            w.destroy()
        try:
            ok = rs.abrir_panel(self.seiscomp_frame, par["eventos"],
                                par["fases"], par.get("no_picadas"),
                                log=self._log, cwd=self.cwd)
        except Exception as e:
            self._log("[error] revisión de SeisComp: %s" % e)
            return
        if not ok:
            self._log("No se pudo abrir la revisión de SeisComp "
                      "(faltan archivos o no hay interfaz).")
            return
        if seleccionar:
            self.cuaderno.select(self.seiscomp_frame)
        # La lista de eventos de SeisComp pide ~1340 px de ancho, más que el
        # tamaño inicial; sin esto las últimas columnas quedan fuera y hay que
        # agrandar la ventana a mano. El detalle vive en su propia ventana, así
        # que lo que se mide acá es solo la lista.
        self._ajustar_ventana()
        self._log("Revisión de SeisComp abierta (%s)."
                  % os.path.basename(par["eventos"]))
        self._anunciar_cobertura(par)


def main():
    if len(sys.argv) < 3:
        print("Uso: python3 app.py <archivo_entrada.csv> <archivo_salida.dat>"
              " [estado.json]")
        sys.exit(1)
    archivo = sys.argv[1]
    salida = sys.argv[2]
    estado = None
    if len(sys.argv) >= 4:
        try:
            estado = json.loads(sys.argv[3])
        except (TypeError, ValueError):
            estado = None
    raiz = ttk.Window(themename="flatly")
    App(raiz, archivo, salida, estado=estado)
    raiz.mainloop()


if __name__ == "__main__":
    main()
