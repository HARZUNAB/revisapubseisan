#!/usr/bin/env python3
"""
app.py
======
Aplicación de escritorio (ttkbootstrap) que unifica el menú del supervisor con
el flujo de análisis y revisión. En esta FASE 1 la ventana principal permite:

  - Ejecutar el análisis (proc_query -> revisaselect -> revisacollect ->
    compara -> [atribución a SeisComp] -> [revisaexcluidos/repetidosexclu] ->
    repetidos) mostrando el registro (log) en vivo.
  - Generar el JSON por fuente (Seisan / eventquery / SeisComp / No publicados
    de seisan / No publicados de SeisComp) y abrir el ploteo.
  - Revisar los datos de SeisComp: la exportación de la ventana la deja la
    solicitud de catálogos y la revisión se abre en su pestaña al terminar el
    análisis, junto con los catálogos de Seisan y eventquery.
  - Atribuir los publicados a SeisComp: la misma comparación, corrida sobre las
    soluciones preferred en vez de las de Seisan, deja en
    informes/no_act_seiscomp_estricto.txt qué publicado quedó desactualizado y
    a qué analista le corresponde. Se saltea sola si no hay exportación.
  - Ver los reportes de eventos repetidos.

Recibe como argumentos el archivo de entrada ($1) y el de salida temporal
($2), igual que el antiguo supervisor.sh. Las salidas se organizan por
contenido en el directorio de ejecución (ver rutas.py).

Uso:
    python3 app.py <archivo_entrada.csv> <archivo_salida.dat>
"""

import os
import sys
import queue
import threading
import subprocess

import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledText
from ttkbootstrap.dialogs import Messagebox

import ajuste

import matplotlib
matplotlib.use("TkAgg")  # las figuras de detalle comparten la raíz Tk de la app

from tkinter import TclError, Toplevel

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

REP_FILES = [
    ("Repetidos públicos (amplio)", "informes/rep_publica_amplio.txt"),
    ("Repetidos públicos (estricto)", "informes/rep_publica_estricto.txt"),
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
# la clave de la vista sola no se distinguían y el botón del grupo Panel
# terminaba apuntando al catálogo.
GRUPOS_PESTANAS = [
    {"titulo": None, "pestanas": ["log"]},
    {"titulo": "Panel",
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

class App:
    def __init__(self, raiz, archivo, salida):
        self.raiz = raiz
        self.archivo = archivo
        self.salida = salida
        self.base = os.path.basename(archivo) if archivo else ""
        self.cwd = os.getcwd()
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
        # Tamaño que se sabe que tiene la ventana. Tk contesta 200x200 a todo
        # antes de que esté mapeada (ver ajuste.py), así que el "solo crecer"
        # se apoya en este valor y no en preguntarle a la ventana.
        self._tamanio = TAMANIO_INICIAL
        # Panel de cada vista: {"frame", "placeholder", "construido"}.
        self.paneles = {}
        # Botón de «Procesar fuente» por vista, para apagarlo si ya está hecha.
        self.botones_fuente_por_clave = {}
        self.ultima_fuente = None
        self.plan_etapas = None
        self.etapa_base = 0.0
        self.etapa_ancho = 1.0
        self.etapa_nombre = ""

        self._construir()
        self._autodetectar_analisis()
        self.raiz.protocol("WM_DELETE_WINDOW", self._salir_app)
        self.raiz.after(100, self._drenar)
        # La exportación de SeisComp la deja la solicitud de catálogos antes
        # de llegar acá, y su pestaña se llena recién al terminar «Ejecutar
        # análisis», igual que las de Seisan y eventquery.

    def _salir_app(self):
        """Cierra las figuras de matplotlib y luego la ventana principal."""
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

        ttk.Label(barra, text="ACCIONES",
                  bootstyle="secondary").pack(anchor=W, pady=(0, 4))
        self.boton_analisis = self._boton(barra, "Ejecutar análisis",
                                          self._accion_analisis,
                                          bootstyle="primary")
        self.botones.remove(self.boton_analisis)
        self.etiqueta_estado = ttk.Label(barra, text="",
                                         bootstyle="warning")
        self.etiqueta_estado.pack(anchor=W, pady=(2, 6))
        self._boton(barra, "Ver repetidos", self._ver_repetidos, gated=True)

        ttk.Separator(barra, orient=HORIZONTAL).pack(fill=X, pady=10)
        ttk.Label(barra, text="PROCESAR FUENTE",
                  bootstyle="secondary").pack(anchor=W, pady=(0, 4))
        fuentes_botones = (
            ("Datos de Seisan", "seisan"),
            ("Datos de eventquery", "eventquery"),
            ("Datos de SeisComp", "seiscomp"),
            ("No publicados de seisan", "nopub"),
            # El cruce contra eventquery ya existe: compara.py lo corre también
            # sobre las soluciones preferred de SeisComp, con el prefijo
            # seiscomp_. Sigue con compuerta porque sin análisis no hay con qué
            # contrastar.
            ("No publicados de SeisComp", "nopub_seiscomp"),
        )
        for texto, clave in fuentes_botones:
            b = self._boton(barra, texto,
                            lambda c=clave: self._accion_fuente(c), gated=True)
            vista_clave = FUENTE_A_VISTA[clave]
            self.botones_fuente_por_clave[vista_clave] = b
            self._tooltip(b, lambda v=vista_clave: self._motivo_fuente_lista(v))

        ttk.Separator(barra, orient=HORIZONTAL).pack(fill=X, pady=10)
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
                text="Genere esta fuente para ver aquí el panel de análisis.")
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
                      "Ejecute «Ejecutar análisis» para generarlos."
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
                      "Ejecute «Ejecutar análisis» para generarlo."))
            etiqueta_noact.pack(expand=YES)
            self.noact[fuente] = {"frame": marco, "etiqueta": etiqueta_noact,
                                  "construido": False}

        # Ahora que ya existen todas las páginas, se arma la barra de pestañas
        # agrupadas y recién después se empaqueta el cuaderno: la barra va
        # primero (side=TOP) para quedar arriba, y el cuaderno ocupa el resto.
        self._construir_barra_pestanas(derecha)
        self.cuaderno.pack(side=LEFT, fill=BOTH, expand=YES)

        # Se anula el layout de la pestaña nativa para que no se vea la tira que
        # dibuja el cuaderno: las pestañas se eligen desde la barra de grupos de
        # arriba. Medido: con las nueve pestañas la tira suma ~45 px de ancho y
        # ~28 de alto, y el cuaderno queda pidiendo lo que ocupan sus páginas.
        # Ojo: es un cambio de estilo GLOBAL al proceso, no del widget; acá no
        # molesta porque solo hay un cuaderno.
        self.raiz.style.layout("TNotebook.Tab", [])

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
        # «Ejecutar análisis». Se mide al mapear la ventana (ver _alinear).
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
        """Baja la barra de pestañas hasta la altura del botón de análisis.

        «Registro» arrancaba en el tope del área de contenido, arriba de donde
        arranca la barra lateral, y quedaba desfasado respecto de «Ejecutar
        análisis». Se mide el desfasaje real en vez de escribir un número fijo
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
        self.raiz.after(100, self._drenar)

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
        # El análisis se puede volver a ejecutar siempre que la app esté libre,
        # incluso si ya se hizo: es lo que hace falta para rehacer una fuente
        # que quedó procesada, y lo que el tooltip de esas fuentes indica. Antes
        # se apagaba en cuanto había análisis hecho y las dos cosas se
        # contradecían: el botón apagado y el texto que mandaba a pulsarlo.
        self.boton_analisis.configure(
            state=DISABLED if self.ocupado else NORMAL)
        for b in self.botones_fuente:
            b.configure(state=estado_fuente)
        # Una fuente ya procesada se apaga aunque haya análisis: su JSON es más
        # nuevo que el CSV del que sale, así que rehacerla daría el mismo panel.
        # Al cambiar el CSV (nuevo análisis) vuelve sola a NORMAL.
        for clave, b in self.botones_fuente_por_clave.items():
            if self._vista_procesada(clave):
                b.configure(state=DISABLED)
        for b, puede, _ in self.condiciones:
            b.configure(state=(NORMAL if puede() and not self.ocupado
                               else DISABLED))

    def _tooltip(self, widget, motivo):
        """
        Tooltip mínimo que sale solo con el botón apagado.

        ttkbootstrap.tooltip no se puede usar acá: usa typing.Literal, que
        existe desde Python 3.8, y la app corre en 3.7. Por eso son veinte
        líneas de Toplevel en vez de un import.

        El motivo se evalúa al entrar, no al crear el widget: depende del
        estado de los archivos y cambia con el correr del tiempo.
        """
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
                text="Análisis: en curso…", bootstyle="warning")
        elif self.analisis_hecho:
            self.etiqueta_estado.configure(
                text="Análisis: realizado", bootstyle="success")
        else:
            self.etiqueta_estado.configure(
                text="Análisis: pendiente", bootstyle="secondary")

    def _autodetectar_analisis(self):
        self.analisis_hecho = os.path.isfile(
            os.path.join("datos", "salida_collect.csv"))
        if self.analisis_hecho:
            self._log("Se detectaron resultados del análisis; "
                      "fuentes habilitadas.")
        self._actualizar_estado()
        self._actualizar_gate()

    def _vista_procesada(self, clave):
        """
        True si el JSON de la vista es más nuevo que su CSV de entrada.

        Es lo que decide si el botón de la fuente queda apagado: mientras el
        JSON siga siendo el resultado del CSV actual, reprocesar daría el mismo
        panel. Cuando el análisis reescribe el CSV, el botón se enciende solo.
        """
        vista = VISTAS_POR_CLAVE.get(clave)
        if vista is None:
            return False
        json_path = os.path.join("datos", "eventos_%s.json" % clave)
        entrada = vista["entrada"]
        if not (os.path.isfile(json_path) and os.path.isfile(entrada)):
            return False
        return os.path.getmtime(json_path) >= os.path.getmtime(entrada)

    def _motivo_fuente_lista(self, clave):
        if not self._vista_procesada(clave):
            return ""
        vista = VISTAS_POR_CLAVE[clave]
        # El texto dice el estado y las dos cosas que se pueden hacer con él,
        # sin dar por hecho en qué estado esté el otro botón: ver el panel en su
        # pestaña, o rehacer la fuente volviendo a ejecutar el análisis.
        return ("Ya se procesó esta fuente: eventos_%s.json es más nuevo que "
                "%s.\n\nSu panel está en la pestaña «%s». Para rehacerla, "
                "vuelva a ejecutar el análisis."
                % (clave, os.path.basename(vista["entrada"]),
                   self._ruta_de_pestana(clave)))

    def _ruta_de_pestana(self, clave):
        """«Grupo · Botón» de la pestaña de una vista.

        Hace falta porque el botón del panel de Seisan y el de los no
        publicados de Seisan se llaman los dos «Seisan»: sin el grupo, el
        tooltip apuntaría a la pestaña equivocada.
        """
        etiqueta = VISTAS_POR_CLAVE.get(clave, {}).get("tab", clave)
        for grupo in GRUPOS_PESTANAS:
            if "panel:%s" % clave in grupo.get("pestanas", ()):
                titulo = grupo.get("titulo")
                return "%s · %s" % (titulo, etiqueta) if titulo else etiqueta
        return etiqueta

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
            # any(...) y no `marca in argumentos`: los argumentos llegan como
            # rutas completas ("datos/seiscomp_parametros.csv"), así que tiene
            # que ser coincidencia parcial y no igualdad de elemento.
            if marca is not None and any(marca in str(a) for a in argumentos):
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
    def _accion_analisis(self):
        if not self.archivo:
            self._log("No se especificó archivo de entrada.")
            return
        # Volver a ejecutarlo es una acción legítima (es lo que hace falta para
        # rehacer una fuente ya procesada) pero son minutos de trabajo, así que
        # se pregunta antes. El botón queda habilitado siempre, con la
        # compuerta aprovando que se vuelva a pulsar.
        if self.analisis_hecho:
            texto = ("Volver a ejecutar el análisis va a regenerar los datos "
                     "de %s.\n\nLas fuentes que ya estaban procesadas "
                     "vuelven a quedar para rehacer, porque su CSV de "
                     "entrada cambió.\n\n¿Continuar?"
                     % os.path.basename(self.archivo))
            if Messagebox.show_question(texto, "Volver a ejecutar el análisis",
                                        parent=self.raiz,
                                        buttons=["Ejecutar:primary",
                                                 "Cancelar"]) != "Ejecutar":
                self._log("Análisis cancelado.")
                return

        def tarea():
            self._log("***** Se comienza el análisis de los datos *****")
            self._popen([_script("proc_query_harz_2.py"),
                         self.archivo, self.salida])
            self._popen([_script("revisaselect.py")])
            self._popen([_script("revisacollect.py")])
            self._log("***** Comparando publicados v/s procesados *****")
            self._popen([_script("compara.py"),
                         os.path.join("datos", "new_2_" + self.base),
                         os.path.join("datos", "salida_collect.csv")])
            # La atribución a SeisComp es la misma comparación con las
            # soluciones preferred en vez de las de Seisan: deja en
            # no_act_seiscomp_*.txt qué publicado quedó desactualizado y a quién
            # le corresponde. Se saltea si no hay exportación, porque la
            # ventana del catálogo puede no haberse descargado nunca.
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
            # El catálogo de SeisComp se revisa con el mismo script: mismo
            # layout de 8 columnas, así que solo hay que pasarle el CSV.
            if os.path.isfile(parametros) and os.path.getsize(parametros) > 0:
                args_repetidos.append(parametros)
            self._popen(args_repetidos)
            try:
                os.remove(self.salida)
            except OSError:
                pass
            self._log("***** Análisis terminado *****")

        self.analisis_en_curso = True
        self._actualizar_estado()
        self._iniciar(tarea, on_fin=self._al_terminar_analisis,
                      plan=ANALISIS_PLAN)

    def _al_terminar_analisis(self):
        self.analisis_en_curso = False
        self.analisis_hecho = os.path.isfile(
            os.path.join("datos", "salida_collect.csv"))
        if self.analisis_hecho:
            self._log("Análisis completado: ya puede procesar fuentes.")
            self._poblar_catalogos()
        else:
            self._log("El análisis no generó datos/salida_collect.csv; "
                      "revise el registro.")
        self._actualizar_estado()
        self._actualizar_gate()

    def _poblar_catalogos(self):
        """
        Llena las pestañas de catálogo cuando termina el análisis.

        Las tres salen del análisis: Seisan de salida_collect.csv, eventquery
        del concatenado de los new_2_*.csv y SeisComp de la exportación que
        dejó la solicitud de catálogos. No se cambia de pestaña para no sacar
        al usuario de donde está mirando.

        Va por _construir_catalogo, el mismo camino que usa la pestaña al
        abrirse, para que no haya dos formas de llenarla y se puedan
        desincronizar.
        """
        # El concatenado se rehace siempre: los new_2_*.csv pueden haber
        # cambiado con este análisis y un todos_eventquery.csv viejo (o vacío
        # de una corrida anterior) dejaría la pestaña con datos de menos.
        self._concatenar_eventquery()
        for clave in ("seisan", "eventquery", "seiscomp"):
            self._construir_catalogo(clave, seleccionar=False)

    def _accion_fuente(self, fuente):
        # Cada fuente escribe su propio eventos_<vista>.json: los no publicados
        # comparten parseo con su fuente, pero no archivo de salida, así que
        # procesarlos no pisa el panel de la fuente principal.
        vista_clave = FUENTE_A_VISTA.get(fuente)
        if vista_clave not in VISTAS_POR_CLAVE:
            return

        def tarea():
            if fuente == "seisan":
                self._popen([_script("generajson.py"),
                             os.path.join("datos", "salida_collect.csv"),
                             "seisan"])
            elif fuente == "eventquery":
                self._fijar_etapa(0)
                self._concatenar_eventquery()
                self._asegurar_parametros_seiscomp()
                self._atribuir_para_eventquery()
                self._popen([_script("generajson.py"),
                             os.path.join("datos", "todos_eventquery.csv"),
                             "eventquery"])
                # No se borra: es lo que lee la pestaña de catálogo de
                # eventquery, y regenerarlo cuesta una pasada más. Es un
                # derivado de los new_2_*, así que no puede quedar
                # desactualizado sin que también lo estén ellos.
            elif fuente == "seiscomp":
                par = self._par_seiscomp_para_catalogo()
                if par is None:
                    self._log("No hay una exportación de SeisComp que cubra "
                              "este catálogo.")
                    return
                self._log("Usando %s" % os.path.basename(par["eventos"]))
                if self._popen([_script("seiscomp_a_parametros.py"),
                                par["eventos"]]):
                    self._log("La conversión falló; no se genera el JSON.")
                    return
                self._popen([_script("generajson.py"),
                             os.path.join("datos", "seiscomp_parametros.csv"),
                             "seiscomp"])
            elif fuente in ("nopub", "nopub_seiscomp"):
                # Los dos "no publicados" salen del mismo compara.py, cada uno
                # con su prefijo, así que no se pisan entre ellos.
                if fuente == "nopub_seiscomp":
                    archivo = os.path.join(
                        "datos", "no_pub_desde_2_5_seiscomp_estricto.csv")
                    origen = "seiscomp"
                else:
                    archivo = os.path.join("datos",
                                           "no_pub_desde_2_5_estricto.csv")
                    origen = "seisan"
                if not os.path.isfile(archivo):
                    self._log("No se encontró %s (corra el análisis primero)."
                              % archivo)
                    return
                # --salida evita que el JSON de los no publicados pise el de la
                # fuente principal: comparten parseo, no archivo de salida.
                self._popen([_script("generajson.py"), archivo, origen,
                             "--salida=%s" % vista_clave])
            else:
                return
            self._log("JSON generado: datos/eventos_%s.json" % vista_clave)

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
            carpeta = os.path.join("datos")
            try:
                nombres = sorted(n for n in os.listdir(carpeta)
                                 if n.startswith("new_2_") and n.endswith(".csv"))
            except OSError:
                return None
            if not nombres:
                return None
            rutas = [os.path.join(carpeta, n) for n in nombres]
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
            self._log("No se encontró %s. Ejecute «Datos de %s» primero."
                      % (ruta, "Seisan" if etiqueta == "seisan" else "eventquery"))
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
        al reabrir la aplicación sobre una carpeta ya analizada).
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
            if os.path.isfile(os.path.join("datos",
                                           "eventos_%s.json" % clave)):
                self._abrir_panel_en_tab(clave)
            break

    def _abrir_panel_en_tab(self, clave):
        """Construye (una sola vez) el panel de la vista y la selecciona."""
        vista = VISTAS_POR_CLAVE.get(clave)
        panel = self.paneles.get(clave)
        if vista is None or panel is None:
            return
        archivo = os.path.join("datos", "eventos_%s.json" % clave)
        if not os.path.isfile(archivo):
            self._log("No se encontró %s; no se abre el panel." % archivo)
            return
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

    def _abrir_no_actualizados(self, fuente):
        """
        Muestra el listado de eventos no actualizados de una fuente.

        No calcula nada: los datos salen de datos/atribucion_<fuente>.csv, que
        escribe la corrida del análisis. Como el botón de la fuente queda
        apagado cuando ya está procesada, la pestaña es la única forma de ver
        el listado al reabrir la aplicación sobre una carpeta ya analizada.

        Distingue los tres estados posibles, porque un mismo "no se puede
        mostrar" significa cosas distintas: que el análisis nunca corrió, que
        corrió sin encontrar cruces, o que hay datos.
        """
        panel = self.noact.get(fuente)
        if panel is None:
            return
        etiqueta = {"seisan": "Seisan", "seiscomp": "SeisComp"}[fuente]
        csv_noact = os.path.join("datos", "atribucion_%s.csv" % fuente)
        # El informe .txt se escribe siempre que corre la comparación (aunque
        # quede sin filas), así que dice si el análisis llegó a hacer el cruce.
        informe = os.path.join(
            "informes", "no_act_%sestricto.txt"
            % ("" if fuente == "seisan" else "seiscomp_"))

        if not os.path.isfile(csv_noact):
            for w in list(panel["frame"].winfo_children()):
                w.destroy()
            panel["construido"] = False
            texto = ("Todavía no hay nada para mostrar.\n\nEjecute "
                     "«Ejecutar análisis» para generarlo."
                     if not os.path.isfile(informe) else
                     "La comparación se ejecutó, pero no encontró ningún "
                     "cruce entre %s y lo publicado.\n\nNo hay eventos "
                     "no actualizados." % etiqueta)
            ttk.Label(panel["frame"], justify=CENTER, text=texto).pack(
                expand=YES)
            return

        mtime = os.path.getmtime(csv_noact)
        if (panel["construido"] and panel.get("mtime") == mtime
                and panel["frame"].winfo_children()):
            return
        for w in list(panel["frame"].winfo_children()):
            w.destroy()
        panel["construido"] = False
        rs = self._importar_revisor()
        if rs is None:
            return
        try:
            ok = rs.abrir_no_actualizados(panel["frame"], fuente,
                                          log=self._log, cwd=self.cwd)
        except Exception as e:
            ok = False
            self._log("[error] no actualizados %s: %s" % (fuente, e))
        if not ok:
            ttk.Label(panel["frame"], justify=CENTER,
                      text="No se pudo leer el listado de %s." % etiqueta
                      ).pack(expand=YES)
            return
        panel["construido"] = True
        panel["mtime"] = mtime
        self._ajustar_ventana()

    def _concatenar_eventquery(self):
        carpeta = "datos"
        salida = os.path.join(carpeta, "todos_eventquery.csv")
        self._log("Concatenando %s/new_2_*.csv -> %s" % (carpeta, salida))
        try:
            partes = sorted(n for n in os.listdir(carpeta)
                            if n.startswith("new_2_") and n.endswith(".csv"))
        except OSError:
            partes = []
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
            boton = ("Datos de SeisComp" if etiqueta == "seiscomp"
                     else "Ejecutar análisis")
            self._log("Sin atribución contra %s (%s). "
                      "Use «%s» si la quiere." % (etiqueta, motivo, boton))

    def _rm(self, ruta):
        try:
            os.remove(ruta)
        except OSError:
            pass

    # --------------------------------------------------- ver repetidos
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

        arbol.bind("<<TreeviewSelect>>", al_seleccionar)
        hijos = arbol.get_children()
        if hijos:
            arbol.selection_set(hijos[0])
            al_seleccionar()

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

    def _par_seiscomp_para_catalogo(self):
        """
        El par exportado que mejor cubre la ventana del catálogo, o None.

        Va por cobertura y no por fecha de modificación a propósito: cuando se
        revisan varios períodos en la misma carpeta, la última exportación no
        es la que corresponde al catálogo que se está mirando ahora.
        """
        rs = self._importar_revisor()
        if rs is None:
            return None
        pares = self._pares_seiscomp()
        if not pares:
            return None
        par = rs._elegir_par(pares, self._ventana_del_catalogo())
        if par is None and pares:
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
                                par["fases"], log=self._log, cwd=self.cwd)
        except Exception as e:
            self._log("[error] revisión de SeisComp: %s" % e)
            return
        if not ok:
            self._log("No se pudo abrir la revisión de SeisComp "
                      "(faltan archivos o no hay interfaz).")
            return
        if seleccionar:
            self.cuaderno.select(self.seiscomp_frame)
        # El árbol de llegadas suma 1450 px de columnas: sin esto la revisión
        # se abre en una ventana de 980 y hay que arrastrar la barra horizontal.
        self._ajustar_ventana()
        self._log("Revisión de SeisComp abierta (%s)."
                  % os.path.basename(par["eventos"]))
        self._anunciar_cobertura(par)


def main():
    if len(sys.argv) < 3:
        print("Uso: python3 app.py <archivo_entrada.csv> <archivo_salida.dat>")
        sys.exit(1)
    archivo = sys.argv[1]
    salida = sys.argv[2]
    raiz = ttk.Window(themename="flatly")
    App(raiz, archivo, salida)
    raiz.mainloop()


if __name__ == "__main__":
    main()
