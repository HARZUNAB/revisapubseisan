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
  - Obtener y revisar los datos de SeisComp: al arrancar se ofrece exportar la
    ventana del catálogo, o elegir una exportación ya hecha, y la revisión se
    abre en su propia pestaña.
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
import glob
import queue
import threading
import subprocess
from datetime import datetime, timedelta

import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledText
from ttkbootstrap.dialogs import Messagebox

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
]


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

# La exportación de SeisComp es un subproceso aparte del pipeline de análisis,
# así que lleva su propio plan: primero se verifica el entorno (que es barato
# y falla rápido si falta psycopg2 o el global.cfg) y después se exporta. El
# peso chico del primero es reflejo de eso, no de su importancia.
SEISCOMP_PLAN = [
    {"nombre": "Verificando entorno de SeisComp",
     "scripts": ("verifica_entorno.py",), "peso": 0.05},
    {"nombre": "Exportando SeisComp",
     "scripts": ("exporta_ventana_seiscomp.py",), "peso": 0.95},
]

# Formato de fecha que espera exporta_ventana_seiscomp.py por línea de comandos.
FORMATO_SEISCOMP = "%Y%m%d%H%M%S"

# Margen en horas que se suma a la ventana del catálogo al sugerir la
# exportación. El catálogo ya trae su propio margen, pero la sugerencia se
# redondea a minuto entero y no conviene que el borde caiga justo sobre el
# primer o el último evento.
MARGEN_SEISCOMP_HORAS = 1


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
        self.ultima_fuente = None
        self.plan_etapas = None
        self.etapa_base = 0.0
        self.etapa_ancho = 1.0
        self.etapa_nombre = ""

        self._construir()
        self._autodetectar_analisis()
        self.raiz.protocol("WM_DELETE_WINDOW", self._salir_app)
        self.raiz.after(100, self._drenar)
        # El diálogo de SeisComp se ofrece con la ventana ya en pantalla, no
        # durante el __init__: abrir un Toplevel antes de que la raíz esté
        # mapeada lo deja en un estado raro y roba el foco antes de tiempo.
        self.raiz.after(400, self._dialogo_seiscomp)

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
        self.raiz.geometry("980x640")
        self.raiz.minsize(820, 520)

        cab = ttk.Frame(self.raiz, padding=(12, 10, 12, 4))
        cab.pack(side=TOP, fill=X)
        ttk.Label(cab, text="Revisión de eventos sísmicos",
                  font=("", 15, "bold")).pack(side=LEFT)
        ttk.Label(cab, text="entrada: %s" % (self.archivo or "-"),
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
        self._boton(barra, "Datos de Seisan",
                    lambda: self._accion_fuente("seisan"), gated=True)
        self._boton(barra, "Datos de eventquery",
                    lambda: self._accion_fuente("eventquery"), gated=True)
        self._boton(barra, "Datos de SeisComp",
                    lambda: self._accion_fuente("seiscomp"), gated=True)
        self._boton(barra, "No publicados de seisan",
                    lambda: self._accion_fuente("nopub"), gated=True)
        # El cruce contra eventquery ya existe: compara.py lo corre también
        # sobre las soluciones preferred de SeisComp, con el prefijo seiscomp_.
        # Sigue con compuerta porque sin análisis no hay con qué contrastar.
        self._boton(barra, "No publicados de SeisComp",
                    lambda: self._accion_fuente("nopub_seiscomp"), gated=True)

        ttk.Separator(barra, orient=HORIZONTAL).pack(fill=X, pady=10)

        ttk.Label(barra, text="CATÁLOGOS",
                  bootstyle="secondary").pack(anchor=W, pady=(0, 4))
        self._boton(barra, "Catálogo Seisan",
                    lambda: self._abrir_catalogo("salida_collect.csv",
                                                 "seisan"),
                    condicion=(self._hay_salida_seisan,
                               lambda: "Falta ejecutar el análisis: todavía "
                                       "no hay salida_collect.csv."))
        self._boton(barra, "Catálogo Eventquery",
                    lambda: self._abrir_catalogo("todos_eventquery.csv",
                                                 "eventquery"),
                    condicion=(self._hay_ventanas_eventquery,
                               lambda: "Falta ejecutar el análisis: todavía "
                                       "no hay ventanas de eventquery."))

        ttk.Separator(barra, orient=HORIZONTAL).pack(fill=X, pady=10)

        ttk.Label(barra, text="SEISCOMP",
                  bootstyle="secondary").pack(anchor=W, pady=(0, 4))
        # Obtener no depende del análisis: es una consulta a otra base, con su
        # propia ventana, y tiene sentido quererla de entrada. Revisar sí pasa
        # por la compuerta, como las demás fuentes, porque sin análisis no hay
        # con qué contrastar después.
        #
        # Obtener se apaga solo cuando ya hay una exportación que cubre el
        # catálogo: antes el clic no hacía nada y terminaba escribiendo
        # "ya hay una exportación" en el registro, que es el mismo silencio
        # que se corrigió en la atribución.
        self._boton(barra, "Obtener de SeisComp", self._obtener_seiscomp,
                    condicion=(self._falta_seiscomp,
                               lambda: "Ya se obtuvo SeisComp para este "
                                       "catálogo. Para rehacerla, borrá la "
                                       "exportación de datos/."))
        self._boton(barra, "Revisar SeisComp", self._revisar_seiscomp,
                    gated=True)

        ttk.Separator(barra, orient=HORIZONTAL).pack(fill=X, pady=10)
        self._boton(barra, "Salir", self._salir_app, bootstyle="danger")

        # --- Contenido (pestañas) ---
        self.cuaderno = ttk.Notebook(cuerpo)
        self.cuaderno.pack(side=LEFT, fill=BOTH, expand=YES)

        marco_log = ttk.Frame(self.cuaderno)
        self.cuaderno.add(marco_log, text="Registro")
        self.txt = ScrolledText(marco_log, padding=4, autohide=True)
        self.txt.pack(fill=BOTH, expand=YES)
        self.txt.text.configure(state=DISABLED, font=("Consolas", 9))

        marco_panel = ttk.Frame(self.cuaderno)
        self.cuaderno.add(marco_panel, text="Panel de análisis")
        self.panel_frame = ttk.Frame(marco_panel)
        self.panel_frame.pack(fill=BOTH, expand=YES)
        self.etiqueta_panel = ttk.Label(
            self.panel_frame, justify=CENTER,
            text=("Genere una fuente (Seisan / eventquery / SeisComp / No "
                  "publicados) para ver aquí el panel de análisis."))
        self.etiqueta_panel.pack(expand=YES)

        # Va tercera a propósito: _abrir_panel_en_tab selecciona la pestaña
        # por índice, y ese índice tiene que seguir siendo el del panel.
        # El marco de la pestaña ES el contenedor del panel, sin un nivel más
        # en el medio, porque es lo que hay que pasarle a select() después.
        self.seiscomp_frame = ttk.Frame(self.cuaderno)
        self.cuaderno.add(self.seiscomp_frame, text="SeisComp")
        self.etiqueta_seiscomp = ttk.Label(
            self.seiscomp_frame, justify=CENTER,
            text=("No hay datos de SeisComp para mostrar.\n\n"
                  "Use “Obtener de SeisComp” en la barra lateral, o "
                  "“Revisar SeisComp” si ya tiene una exportación."))
        self.etiqueta_seiscomp.pack(expand=YES)

        self.seisan_frame = ttk.Frame(self.cuaderno)
        self.cuaderno.add(self.seisan_frame, text="Seisan")
        self.etiqueta_seisan = ttk.Label(
            self.seisan_frame, justify=CENTER,
            text=("No hay datos de Seisan para mostrar.\n\n"
                  "Pulse «Catálogo Seisan» en la barra lateral."))
        self.etiqueta_seisan.pack(expand=YES)

        self.eventquery_frame = ttk.Frame(self.cuaderno)
        self.cuaderno.add(self.eventquery_frame, text="Eventquery")
        self.etiqueta_eventquery = ttk.Label(
            self.eventquery_frame, justify=CENTER,
            text=("No hay datos de eventquery para mostrar.\n\n"
                  "Pulse «Catálogo Eventquery» en la barra lateral."))
        self.etiqueta_eventquery.pack(expand=YES)

        # --- Barra de progreso (inferior, persistente) ---
        barra_marco = ttk.Frame(self.raiz, padding=(12, 4, 12, 8))
        barra_marco.pack(side=TOP, fill=X)
        self.barra = ttk.Progressbar(barra_marco, maximum=1000, value=0)
        self.barra.pack(side=LEFT, fill=X, expand=YES)
        self.barra_texto = ttk.Label(barra_marco, text="Esperando tarea…",
                                     bootstyle="secondary", width=46)
        self.barra_texto.pack(side=LEFT, padx=(10, 0))
        self.barra_valor = 0

        self._log("Listo. Directorio de trabajo: %s" % self.cwd)

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
            estado_analisis = DISABLED
            estado_fuente = DISABLED
        elif self.analisis_hecho:
            estado_analisis = DISABLED
            estado_fuente = NORMAL
        else:
            estado_analisis = NORMAL
            estado_fuente = DISABLED
        self.boton_analisis.configure(state=estado_analisis)
        for b in self.botones_fuente:
            b.configure(state=estado_fuente)
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
            if os.path.isfile(parametros) and os.path.getsize(parametros) > 0:
                self._log("***** Atribuyendo publicados a SeisComp *****")
                self._popen([_script("compara.py"),
                             os.path.join("datos", "new_2_" + self.base),
                             parametros, "seiscomp_"])
            else:
                self._log("Sin datos de SeisComp: se omite la atribución. Use "
                          "«Obtener de SeisComp» para exportar la ventana.")
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
            self._popen([_script("repetidos.py"),
                         os.path.join("datos", "new_2_" + self.base),
                         os.path.join("datos", "salida_collect.csv")])
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
        else:
            self._log("El análisis no generó datos/salida_collect.csv; "
                      "revise el registro.")
        self._actualizar_estado()
        self._actualizar_gate()

    def _accion_fuente(self, fuente):
        # 'json_fuente' es el nombre base del JSON resultante. 'nopub' reusa el
        # de seisan a propósito, porque son los mismos eventos con otro filtro
        # y plotear los pinta con la etiqueta que le pasa 'etiqueta_fuente'.
        etiquetas = {"seisan": "Seisan", "eventquery": "Eventquery",
                     "seiscomp": "SeisComp", "nopub": "No publicados de seisan",
                     "nopub_seiscomp": "No publicados de SeisComp"}
        # nopub_seiscomp dibuja sobre el JSON de seiscomp: son Preferred
        # Solutions, no eventos de Seisan, y sus magnitudes y profundidades
        # vienen de otra base. Mezclarlos en eventos_seisan.json daría perfiles
        # calculados con la convención de la fuente equivocada.
        if fuente in ("eventquery", "seiscomp", "nopub_seiscomp"):
            json_fuente = "seiscomp" if fuente == "nopub_seiscomp" else fuente
        else:
            json_fuente = "seisan"
        etiqueta_fuente = etiquetas.get(fuente, fuente)

        def tarea():
            if fuente == "seisan":
                self._popen([_script("generajson.py"),
                             os.path.join("datos", "salida_collect.csv"),
                             "seisan"])
            elif fuente == "eventquery":
                self._fijar_etapa(0)
                self._concatenar_eventquery()
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
                              "este catálogo. Use «Obtener de SeisComp».")
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
                self._popen([_script("generajson.py"), archivo, origen])
            else:
                return
            self._log("JSON generado: datos/eventos_%s.json" % json_fuente)

        def al_terminar():
            self._abrir_panel_en_tab(json_fuente, etiqueta_fuente)

        self._iniciar(tarea, on_fin=al_terminar,
                      plan=FUENTE_PLAN.get(fuente))

    def _abrir_catalogo(self, nombre_archivo, etiqueta):
        """Muestra el catálogo crudo de una fuente en su pestaña."""
        rs = self._importar_revisor()
        if rs is None:
            return
        ruta = os.path.join("datos", nombre_archivo)
        marco = (self.seisan_frame if etiqueta == "seisan"
                 else self.eventquery_frame)
        if etiqueta == "eventquery" and not os.path.isfile(ruta):
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
        try:
            ok = rs.abrir_catalogo(marco, ruta, etiqueta, log=self._log,
                                    cwd=self.cwd)
        except Exception as e:
            self._log("[error] catálogo %s: %s" % (etiqueta, e))
            return
        if not ok:
            self._log("No se pudo abrir el catálogo de %s." % etiqueta)
            return
        self.cuaderno.select(marco)
        self._log("Catálogo abierto: %s" % os.path.basename(ruta))

    def _abrir_panel_en_tab(self, json_fuente, etiqueta_fuente=None):
        """Construye el panel de análisis embebido en la pestaña del panel."""
        archivo = os.path.join("datos", "eventos_%s.json" % json_fuente)
        if not os.path.isfile(archivo):
            self._log("No se encontró %s; no se abre el panel." % archivo)
            return
        # Limpia el área del panel anterior.
        for w in list(self.panel_frame.winfo_children()):
            w.destroy()
        try:
            import plotear
            ok = plotear.abrir_panel(self.panel_frame, archivo, json_fuente,
                                     etiqueta_fuente=etiqueta_fuente)
            if ok:
                self.cuaderno.select(self.cuaderno.tabs()[1])
                self._log("Panel de análisis abierto (%s)." % json_fuente)
            else:
                self._log("No se pudo abrir el panel (¿backend interactivo?).")
        except Exception as e:
            self._log("[error] panel: %s" % e)

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

    def _hay_salida_seisan(self):
        return os.path.isfile(os.path.join("datos", "salida_collect.csv"))

    def _hay_ventanas_eventquery(self):
        """
        Si hay con qué armar el catálogo de eventquery.

        No se exige todos_eventquery.csv porque el catálogo se arma al vuelo
        desde cualquier new_2_*.csv (ver _abrir_catalogo): exigir el
        concatenado dejaría el botón apagado justo cuando los datos sí están.
        """
        if os.path.isfile(os.path.join("datos", "todos_eventquery.csv")):
            return True
        return bool(glob.glob(os.path.join("datos", "new_2_*.csv")))

    def _falta_seiscomp(self):
        """
        True si todavía no hay una exportación de SeisComp para este catálogo.

        Sin archivo de entrada no hay ventana con la que comparar, así que el
        botón queda habilitado: es justamente el caso en el que hay que elegir
        la ventana a mano, y apagarlo dejaría al usuario sin salida.

        Con ventana, se reusa el criterio de _dialogo_seiscomp. Si el botón
        queda habilitado cuando el diálogo no tiene nada que preguntar, o al
        revés, los dos caminos se contradicen.
        """
        ventana = self._ventana_del_catalogo()
        if ventana is None:
            return True
        rs = self._importar_revisor()
        if rs is None:
            return True
        return rs._elegir_par(self._pares_seiscomp(), ventana) is None

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

    def _abrir_revisor(self, par):
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
        self.cuaderno.select(self.seiscomp_frame)
        self._log("Revisión de SeisComp abierta (%s)."
                  % os.path.basename(par["eventos"]))
        self._anunciar_cobertura(par)

    # ------------------------------------------------- obtener SeisComp
    def _obtener_seiscomp(self):
        if self.ocupado:
            return
        self._dialogo_seiscomp()

    def _dialogo_seiscomp(self):
        """
        Al arrancar: ofrece exportar la ventana del catálogo, o dar por hecho
        que ya se tiene.

        Si ya hay una exportación completa que cubre el catálogo no se pregunta
        nada: se avisa por el registro y se sigue. Preguntar de más es la forma
        más rápida de que la app se vuelva molesta.
        """
        ventana = self._ventana_del_catalogo()
        if ventana is None:
            self._log("No se pudo leer la ventana del catálogo; use "
                      "«Obtener de SeisComp» para elegirla a mano.")
            return

        rs = self._importar_revisor()
        if rs is None:
            return
        existente = rs._elegir_par(self._pares_seiscomp(), ventana)
        if existente is not None:
            self._log("Ya hay una exportación de SeisComp para este "
                      "catálogo: %s" % os.path.basename(existente["eventos"]))
            self._anunciar_cobertura(existente)
            return

        desde, hasta = ventana
        sug_inicio = (desde - timedelta(hours=MARGEN_SEISCOMP_HORAS))
        sug_fin = (hasta + timedelta(hours=MARGEN_SEISCOMP_HORAS))
        # Se redondea hacia afuera a minuto entero: el exportador filtra con
        # BETWEEN, y un segundo de diferencia alcanza para quedarse sin el
        # primer evento del catálogo.
        sug_inicio = sug_inicio.replace(second=0, microsecond=0)
        sug_fin = (sug_fin.replace(second=0, microsecond=0)
                   + timedelta(minutes=1))

        top = ttk.Toplevel(title="Datos de SeisComp", master=self.raiz)
        top.transient(self.raiz)
        top.grab_set()

        marco = ttk.Frame(top, padding=12)
        marco.pack(fill=BOTH, expand=YES)

        ttk.Label(marco, text="Datos de SeisComp", font=("", 13, "bold"),
                  bootstyle="primary").pack(anchor=W)
        ttk.Label(
            marco, justify=LEFT, wraplength=430,
            text=("El catálogo va del %s al %s.\n\n"
                  "Se puede exportar esa ventana de la base de SeisComp, o "
                  "indicar una exportación que ya tenga."
                  % (desde.strftime("%Y-%m-%d %H:%M"),
                     hasta.strftime("%Y-%m-%d %H:%M")))).pack(
            anchor=W, pady=(6, 10))

        campos = ttk.Frame(marco)
        campos.pack(fill=X)
        ttk.Label(campos, text="Desde (AAAAMMDDHHMMSS)",
                  width=22).grid(row=0, column=0, sticky=W)
        ttk.Label(campos, text="Hasta (AAAAMMDDHHMMSS)",
                  width=22).grid(row=1, column=0, sticky=W)
        ent_desde = ttk.Entry(campos, width=22)
        ent_desde.grid(row=0, column=1, sticky=W, pady=2)
        ent_fin = ttk.Entry(campos, width=22)
        ent_fin.grid(row=1, column=1, sticky=W, pady=2)
        ent_desde.insert(0, sug_inicio.strftime(FORMATO_SEISCOMP))
        ent_fin.insert(0, sug_fin.strftime(FORMATO_SEISCOMP))

        aviso = ttk.Label(marco, text="", bootstyle="danger", wraplength=430)
        aviso.pack(anchor=W, pady=(6, 0))

        botones = ttk.Frame(marco)
        botones.pack(fill=X, pady=(12, 0))

        def exportar():
            try:
                d = datetime.strptime(ent_desde.get().strip(),
                                      FORMATO_SEISCOMP)
                h = datetime.strptime(ent_fin.get().strip(),
                                      FORMATO_SEISCOMP)
            except ValueError:
                aviso.configure(text="Las fechas van como AAAAMMDDHHMMSS.")
                return
            if h <= d:
                aviso.configure(text="El término tiene que ser posterior "
                                     "al inicio.")
                return
            top.grab_release()
            top.destroy()
            self._exportar_seiscomp(d, h)

        def elegir_archivos():
            evento, fases = rs._elegir_archivos(self.cwd, top)
            if not evento:
                return
            top.grab_release()
            top.destroy()
            if not os.path.basename(evento).startswith("seiscomp_"):
                self._log("Ojo: %s no sigue la convención seiscomp_*.csv, así "
                          "que «Datos de SeisComp» no la va a encontrar para "
                          "plotear. Guardala con ese nombre si la vas a "
                          "reusar." % os.path.basename(evento))
            self._abrir_revisor({"eventos": evento, "fases": fases})

        def seguir():
            top.grab_release()
            top.destroy()

        ttk.Button(botones, text="Exportar ahora", bootstyle="primary",
                   command=exportar).pack(side=LEFT)
        ttk.Button(botones, text="Ya lo tengo, elegir archivos",
                   bootstyle="secondary",
                   command=elegir_archivos).pack(side=LEFT, padx=(8, 0))
        ttk.Button(botones, text="Seguir sin SeisComp",
                   bootstyle="secondary-outline",
                   command=seguir).pack(side=RIGHT)

    def _exportar_seiscomp(self, desde, hasta):
        """Exporta la ventana indicada y, si sale bien, abre la revisión."""
        inicio = desde.strftime(FORMATO_SEISCOMP)
        fin = hasta.strftime(FORMATO_SEISCOMP)
        esperado = os.path.join("datos", "seiscomp_%s_%s.csv" % (inicio, fin))

        def tarea():
            self._log("***** Se exportan los datos de SeisComp "
                      "(%s a %s) *****" % (inicio, fin))
            if self._popen([_script("verifica_entorno.py")]):
                self._log("El entorno no está listo (ver el registro). "
                          "No se consulta la base de SeisComp.")
                return
            if self._popen([_script("exporta_ventana_seiscomp.py"),
                            inicio, fin]):
                self._log("La exportación de SeisComp falló (ver el registro).")
                return
            if not os.path.isfile(esperado):
                self._log("La exportación dijo haber terminado, pero no está "
                          "%s" % esperado)
                return
            if not self._exportacion_completa(esperado):
                self._log("Ojo: %s no tiene la marca de exportación completa."
                          % os.path.basename(esperado))
            self._log("Exportación de SeisComp lista: %s" % esperado)

        def al_terminar():
            if not os.path.isfile(esperado):
                return
            if not self._exportacion_completa(esperado):
                # La corrida pudo cortarse después de escribir el CSV de
                # eventos. Abrirlo daría la impresión de que en esa ventana no
                # hubo más eventos de los que hubo, que es justo el problema que
                # la marca existe para evitar.
                self._log("No se abre la revisión de SeisComp: la exportación "
                          "de %s quedó incompleta (sin marca .completo). Se "
                          "puede volver a exportar."
                          % os.path.basename(esperado))
                return
            self._abrir_revisor({
                "eventos": esperado,
                "fases": esperado[:-4] + "_fases.csv",
            })

        self._iniciar(tarea, on_fin=al_terminar, plan=SEISCOMP_PLAN)

    # ------------------------------------------------- revisar SeisComp
    def _revisar_seiscomp(self):
        if self.ocupado:
            return
        par = self._par_seiscomp_para_catalogo()
        if par is not None:
            self._abrir_revisor(par)
            return
        # No hay ninguna que cubra el catálogo. Se ofrece elegir una a mano en
        # vez de negarse: puede que la ventana no coincida y aun así la
        # exportación sirva para otra cosa.
        Messagebox.show_info(
            "No hay exportaciones de SeisComp en datos/ que cubran el "
            "catálogo.\n\nPuede elegir una a mano, o exportar la ventana "
            "con «Obtener de SeisComp».",
            "Revisar SeisComp", parent=self.raiz)
        rs = self._importar_revisor()
        if rs is None:
            return
        evento, fases = rs._elegir_archivos(self.cwd, self.raiz)
        if evento:
            self._abrir_revisor({"eventos": evento, "fases": fases})


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
