#!/usr/bin/env python3
"""
app.py
======
Aplicación de escritorio (ttkbootstrap) que unifica el menú del supervisor con
el flujo de análisis y revisión. En esta FASE 1 la ventana principal permite:

  - Ejecutar el análisis (proc_query -> revisaselect -> revisacollect ->
    compara -> [revisaexcluidos/repetidosexclu] -> repetidos) mostrando el
    registro (log) en vivo.
  - Generar el JSON por fuente (Seisan / eventquery / No publicados de seisan)
    y abrir, por ahora en ventana aparte, el ploteo.
  - Ver los reportes de eventos repetidos.
  - Opciones de SeisComp deshabilitadas (a futuro).

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

import matplotlib
matplotlib.use("TkAgg")  # las figuras de detalle comparten la raíz Tk de la app

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
     "scripts": ("comparar.py",), "peso": 0.25},
    {"nombre": "Revisando excluidos",
     "scripts": ("revisaexcluidos.py", "repetidosexclu.py"), "peso": 0.10},
    {"nombre": "Revisando repetidos",
     "scripts": ("repetidos.py",), "peso": 0.25},
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
        self.ultima_fuente = None
        self.plan_etapas = None
        self.etapa_base = 0.0
        self.etapa_ancho = 1.0
        self.etapa_nombre = ""

        self._construir()
        self._autodetectar_analisis()
        self.raiz.protocol("WM_DELETE_WINDOW", self._salir_app)
        self.raiz.after(100, self._drenar)

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
        self._boton(barra, "No publicados de seisan",
                    lambda: self._accion_fuente("nopub"), gated=True)
        self._boton(barra, "Datos de SeisComp", None, disabled=True)
        self._boton(barra, "No publicados de SeisComp", None, disabled=True)

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
            text=("Genere una fuente (Seisan / eventquery / No publicados) "
                  "para ver aquí el panel de análisis."))
        self.etiqueta_panel.pack(expand=YES)

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
               gated=False):
        b = ttk.Button(marco, text=texto, command=fn, bootstyle=bootstyle,
                       width=26)
        b.pack(fill=X, pady=2)
        if disabled:
            b.configure(state=DISABLED)
        elif gated:
            self.botones_fuente.append(b)
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

    def _preparar_etapa_script(self, nombre_script):
        try:
            nombre_script = os.path.basename(nombre_script)
        except TypeError:
            return
        for i, e in enumerate(self.plan_etapas or ()):
            if nombre_script in e.get("scripts", ()):
                self._fijar_etapa(i)
                return

    # ------------------------------------------------------------ procesos
    def _popen(self, args):
        args = list(args)
        if args and args[0].endswith(".py"):
            args = [PY] + args
        self._log("$ " + " ".join(args))
        self._preparar_etapa_script(args[0])
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
        # 'json_fuente' es el nombre base del JSON resultante (nopub usa seisan).
        etiquetas = {"seisan": "Seisan", "eventquery": "Eventquery",
                     "nopub": "No publicados de seisan"}
        if fuente == "eventquery":
            json_fuente = "eventquery"
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
                self._popen([_script("generajson.py"),
                             os.path.join("datos", "todos_eventquery.csv"),
                             "eventquery"])
                self._rm(os.path.join("datos", "todos_eventquery.csv"))
            elif fuente == "nopub":
                archivo = os.path.join("datos", "no_pub_desde_2_5_estricto.csv")
                if not os.path.isfile(archivo):
                    self._log("No se encontró %s (corra el análisis primero)."
                              % archivo)
                    return
                self._popen([_script("generajson.py"), archivo, "seisan"])
            else:
                return
            self._log("JSON generado: datos/eventos_%s.json" % json_fuente)

        def al_terminar():
            self._abrir_panel_en_tab(json_fuente, etiqueta_fuente)

        self._iniciar(tarea, on_fin=al_terminar,
                      plan=FUENTE_PLAN.get(fuente))

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

        def al_seleccionar(evento=None):
            sel = arbol.selection()
            if not sel:
                return
            ruta = rutas[sel[0]]
            contenido.text.configure(state=NORMAL)
            contenido.text.delete("1.0", END)
            if os.path.isfile(ruta):
                with open(ruta) as f:
                    contenido.text.insert(END, f.read())
            else:
                contenido.text.insert(END, "(no generado)")
            contenido.text.configure(state=DISABLED)

        arbol.bind("<<TreeviewSelect>>", al_seleccionar)
        hijos = arbol.get_children()
        if hijos:
            arbol.selection_set(hijos[0])
            al_seleccionar()


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
