#!/usr/bin/env python3
"""
solicita_catalogos.py
=====================
Ventana de solicitud de catálogos. Se abre cuando se ejecuta supervisor.sh sin
parámetros. Pide inicio, fin y la contraseña del servidor; baja los catálogos
de Seisan (`select.out`) y eventquery (`eventquery_<ini>_<fin>.csv`) por
SSH/SCP y exporta la ventana de SeisComp (reusando si ya está). Al terminar
lanza la ventana principal de revisión (app.py) con el catálogo de eventquery
descargado.

Los tres catálogos se pueden reusar: si el archivo de esa ventana ya está en
disco, no se vuelve a consultar el servidor.

El avance se muestra por etapas con pesos (conectar, bajar Seisan, bajar
eventquery, preparar select.out, verificar entorno y exportar SeisComp) y un
cronómetro: el porcentaje es orientativo, porque los pasos remotos no tienen un
total conocido de antemano. Bajo la barra hay una línea discreta con lo que se
está obteniendo en ese momento ("Obteniendo catálogos…", "Obteniendo
SeisComp…"), que es la que avisa que el proceso sigue vivo cuando el porcentaje
se congela en una consulta remota o contra la base. La exportación de SeisComp,
que es la etapa más larga, además informa su avance fino a través del protocolo
prog.py.

Hay dos caminos: «Solicitar y descargar» baja lo que falte del servidor, y «Ya
los tengo (seguir)» exige que los catálogos de esa ventana (select y eventquery)
ya estén en la carpeta de ejecución; si faltan, los lista y no continúa. Debajo
de los campos hay un indicador en vivo de qué archivos hay para la ventana
escrita.

Si algo falla se avisa por la salida de errores (la consola desde donde se
lanzó supervisor.sh) y no se abre la ventana principal.
"""
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime

import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledText

import rutas
import traer_catalogos as tc

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
FORMATO_14 = "%Y%m%d%H%M%S"
MARCA_PROGRESO = "@@PROGRESO@@"

# Etapas del avance. 'peso' reparte la barra (0..1) y 'texto' es el verbo corto
# que muestra la línea de actividad; los scripts y las funciones de red
# informan su fracción dentro de la etapa. El porcentaje es orientativo: los
# pasos remotos no tienen un total conocido de antemano, así que lo que importa
# es la etapa en curso y que el cronómetro y los puntos sigan corriendo.
PLAN_DESCARGAR = [
    {"nombre": "Conectando con el servidor", "peso": 0.05,
     "texto": "Conectando con el servidor"},
    {"nombre": "Descargando Seisan (select)", "peso": 0.27,
     "texto": "Obteniendo catálogos"},
    {"nombre": "Descargando eventquery", "peso": 0.30,
     "texto": "Obteniendo catálogos"},
    {"nombre": "Preparando select.out", "peso": 0.03,
     "texto": "Preparando catálogos"},
    {"nombre": "Verificando entorno de SeisComp", "peso": 0.05,
     "texto": "Verificando SeisComp"},
    {"nombre": "Exportando ventana de SeisComp", "peso": 0.30,
     "texto": "Obteniendo SeisComp"},
]

PLAN_USAR = [
    {"nombre": "Preparando catálogos locales", "peso": 0.05,
     "texto": "Preparando catálogos"},
    {"nombre": "Verificando entorno de SeisComp", "peso": 0.05,
     "texto": "Verificando SeisComp"},
    {"nombre": "Exportando ventana de SeisComp", "peso": 0.90,
     "texto": "Obteniendo SeisComp"},
]


def _validar(texto):
    """Devuelve (datetime, marca14) o None si el texto no es AAAAMMDDHHMMSS."""
    texto = (texto or "").strip()
    if len(texto) != 14 or not texto.isdigit():
        return None
    try:
        return datetime.strptime(texto, FORMATO_14), texto
    except ValueError:
        return None


def _hay_archivo(ruta):
    """True si el archivo existe y no está vacío.

    El tamaño importa: una bajada interrumpida deja un archivo de cero bytes que
    se leería como válido y después rompería el análisis sin avisar.
    """
    return os.path.isfile(ruta) and os.path.getsize(ruta) > 0


class App:
    def __init__(self):
        self.raiz = ttk.Window(themename="flatly")
        self.raiz.title("Solicitud de catálogos")
        self._dimensionar()
        self.cola = queue.Queue()
        self.trabajando = False
        self.botones = []
        self._inicio = None
        self._fin = None
        self._pass = ""

        self.plan_etapas = None
        self.etapa_base = 0.0
        self.etapa_ancho = 0.0
        self.etapa_nombre = ""
        self.etapa_texto = ""
        self.barra_valor = 0
        self._texto_estado = "En espera."
        self._t0 = 0.0

        self._construir()
        self.raiz.protocol("WM_DELETE_WINDOW", self._cancelar)
        self.raiz.after(100, self._drenar)

    # ------------------------------------------------------------------ UI
    def _dimensionar(self):
        """Ajusta el tamaño y la posición a la pantalla.

        La ventana se dimensiona en vez de fijar un tamaño: el contenido pide
        más alto del que tenía la ventana chica anterior y los botones de abajo
        quedaban fuera de pantalla, obligando a agrandarla a mano. Se toma un
        alto acotado por la pantalla real y se centra.
        """
        sw = self.raiz.winfo_screenwidth()
        sh = self.raiz.winfo_screenheight()
        ancho = max(560, min(760, sw - 80))
        alto = max(520, min(860, sh - 80))
        self.raiz.minsize(560, 480)
        self.raiz.geometry("%dx%d" % (ancho, alto))
        x = max(0, (sw - ancho) // 2)
        y = max(0, (sh - alto) // 2)
        self.raiz.geometry("+%d+%d" % (x, y))

    def _construir(self):
        marco = ttk.Frame(self.raiz, padding=14)
        marco.pack(fill=BOTH, expand=YES)

        # La barra de botones se empaqueta primero y anclada abajo: así se
        # reserva su alto natural desde el borde inferior y queda siempre
        # visible, aunque el aviso de error o el registro crezcan. El registro
        # (el único con expand=YES) es lo que cede espacio.
        botones = ttk.Frame(marco)
        botones.pack(side=BOTTOM, fill=X)
        self._boton(botones, "Solicitar y descargar", self._solicitar,
                    bootstyle="primary").pack(side=LEFT)
        self._boton(botones, "Ya los tengo (seguir)", self._ya_los_tengo,
                    bootstyle="secondary").pack(side=LEFT, padx=(8, 0))
        self._boton(botones, "Salir", self._cancelar,
                    bootstyle="danger-outline").pack(side=RIGHT)

        ttk.Label(marco, text="Solicitud de catálogos", font=("", 15, "bold"),
                  bootstyle="primary").pack(anchor=W)
        ttk.Label(
            marco, justify=LEFT, wraplength=600,
            text="Indique el período y la contraseña del servidor."
        ).pack(anchor=W, pady=(6, 10))

        campos = ttk.Frame(marco)
        campos.pack(fill=X)
        ttk.Label(campos, text="Inicio (AAAAMMDDHHMMSS)",
                  width=26).grid(row=0, column=0, sticky=W)
        ttk.Label(campos, text="Fin (AAAAMMDDHHMMSS)",
                  width=26).grid(row=1, column=0, sticky=W)
        ttk.Label(campos, text="Contraseña %s@%s"
                  % (tc.USUARIO_REMOTO, tc.IP_REMOTA),
                  width=26).grid(row=2, column=0, sticky=W)
        self.ent_ini = ttk.Entry(campos, width=22)
        self.ent_ini.grid(row=0, column=1, sticky=W, pady=2)
        self.ent_fin = ttk.Entry(campos, width=22)
        self.ent_fin.grid(row=1, column=1, sticky=W, pady=2)
        self.ent_pass = ttk.Entry(campos, width=22, show="*")
        self.ent_pass.grid(row=2, column=1, sticky=W, pady=2)

        # Indicador en vivo de qué hay en disco para la ventana escrita.
        self.estado_archivos = ttk.Label(marco, text="En disco —",
                                         bootstyle="secondary",
                                         wraplength=600)
        self.estado_archivos.pack(anchor=W, pady=(8, 0))
        for entrada in (self.ent_ini, self.ent_fin):
            entrada.bind("<KeyRelease>", self._al_editar_fecha)

        self.aviso = ttk.Label(marco, text="", bootstyle="danger",
                               wraplength=600)
        self.aviso.pack(anchor=W, pady=(6, 0))

        ttk.Label(marco, text="Avance", bootstyle="secondary").pack(
            anchor=W, pady=(10, 2))
        self.barra = ttk.Progressbar(marco, maximum=1000, value=0,
                                     bootstyle="primary")
        self.barra.pack(fill=X)
        self.estado = ttk.Label(marco, text="En espera.",
                                bootstyle="secondary", wraplength=600)
        self.estado.pack(anchor=W, pady=(4, 0))
        # Una sola línea discreta con lo que se está obteniendo en este
        # momento. Antes era una segunda barra en movimiento, pero convive mal
        # con la de arriba: una dice cuántos por ciento y la otra que no sabe,
        # y hay tramos (consulta remota, consulta a la base) en los que la de
        # arriba se congela. El texto con puntos cubre ese hueco sin fingir un
        # avance cuantificable.
        self.actividad = ttk.Label(marco, text="", bootstyle="secondary",
                                   wraplength=600)
        self.actividad.pack(anchor=W, pady=(0, 6))

        ttk.Label(marco, text="Actividad", bootstyle="secondary").pack(
            anchor=W, pady=(4, 2))
        self.txt = ScrolledText(marco, padding=4, autohide=True, height=10)
        self.txt.pack(fill=BOTH, expand=YES)
        self.txt.text.configure(state=DISABLED, font=("Consolas", 9))

    def _boton(self, marco, texto, fn, bootstyle=DEFAULT):
        b = ttk.Button(marco, text=texto, command=fn, bootstyle=bootstyle)
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
                elif tipo == "prog":
                    self._pintar_progreso(*dato)
                elif tipo == "fin":
                    self._terminar_ok(dato)
                    return
                elif tipo == "error":
                    self._terminar_error(dato)
                    return
        except queue.Empty:
            pass
        if self.trabajando:
            self._refrescar_estado()
        self.raiz.after(100, self._drenar)

    # ------------------------------------------------------------- avance
    def _pintar_progreso(self, fraccion, texto):
        """Aplica el avance (monótono) y la etiqueta de etapa en el hilo de UI."""
        frac = max(0.0, min(1.0, fraccion))
        val = int(round(frac * 1000))
        if val > self.barra_valor:
            self.barra_valor = val
            self.barra.configure(value=val)
        self._texto_estado = "%s  ·  %d %%" % (texto, round(frac * 100))
        self._refrescar_estado()

    def _refrescar_estado(self):
        if not self.trabajando:
            return
        seg = int(time.time() - self._t0)
        self.estado.configure(
            text="%s  ·  %d:%02d" % (self._texto_estado, seg // 60, seg % 60))
        # Los puntos cambian dos veces por segundo. No hace falta un
        # temporizador aparte: _drenar ya llama a esto cada 100 ms.
        self.actividad.configure(
            text="%s%s" % (self.etapa_texto,
                           "." * (int(time.time() * 2) % 4)))

    def _fijar_etapa(self, indice):
        """Posiciona la etapa actual y avisa a la interfaz (se llama del hilo
        de trabajo, así que solo encola)."""
        if not self.plan_etapas:
            return
        indice = max(0, min(indice, len(self.plan_etapas) - 1))
        etapa = self.plan_etapas[indice]
        self.etapa_base = sum(p["peso"] for p in self.plan_etapas[:indice])
        self.etapa_ancho = etapa["peso"]
        self.etapa_nombre = etapa["nombre"]
        self.etapa_texto = etapa.get("texto", etapa["nombre"])
        self.cola.put(("prog", (self.etapa_base, self.etapa_nombre)))

    def _progreso_local(self, fraccion):
        """Mapea la fracción [0,1] de la etapa en curso sobre su peso."""
        frac = max(0.0, min(1.0, fraccion))
        self.cola.put(("prog", (self.etapa_base + self.etapa_ancho * frac,
                                self.etapa_nombre)))

    # --------------------------------------------------------- archivos
    def _archivos_ventana(self, inicio14, fin14):
        """Los catálogos de esa ventana y si están utilizables en disco."""
        cwd = os.getcwd()
        nombre_select = "select_%s_%s.out" % (inicio14, fin14)
        nombre_evento = "eventquery_%s_%s.csv" % (inicio14, fin14)
        return (
            ("Seisan", nombre_select,
             _hay_archivo(os.path.join(cwd, nombre_select))),
            ("eventquery", nombre_evento,
             _hay_archivo(os.path.join(cwd, nombre_evento))),
        )

    def _revisar_locales(self, inicio14, fin14):
        """Nombres de los catálogos de esa ventana que no están en disco."""
        return [nombre for _etiqueta, nombre, ok
                in self._archivos_ventana(inicio14, fin14) if not ok]

    def _seiscomp_reusa(self, inicio14, fin14):
        """Si la exportación de SeisComp de esa ventana ya está completa.

        Reusa el mismo criterio que exporta_ventana_seiscomp.py --reusar: los
        dos CSV y la marca de fin. Sirve para avisar que la etapa larga no va
        a tocar la base.
        """
        base = os.path.join("datos", "seiscomp_%s_%s.csv" % (inicio14, fin14))
        fases = os.path.join("datos",
                             "seiscomp_%s_%s_fases.csv" % (inicio14, fin14))
        marca = base + ".completo"
        return all(_hay_archivo(r) for r in (base, fases, marca))

    def _refrescar_estado_archivos(self):
        """Pinta el indicador en vivo de lo que hay para la ventana escrita.

        Siempre en estilo neutro: antes de descargar que falten los catálogos
        es el estado esperado, no un error, y en rojo se leía como que algo
        estaba mal. El error de verdad aparece recién al pulsar «Ya los tengo»,
        en el aviso de arriba.
        """
        if self.trabajando:
            return
        ini = _validar(self.ent_ini.get())
        fin = _validar(self.ent_fin.get())
        if ini is None or fin is None or fin[0] <= ini[0]:
            self.estado_archivos.configure(text="En disco —",
                                           bootstyle="secondary")
            return
        partes = []
        for etiqueta, _nombre, ok in self._archivos_ventana(ini[1], fin[1]):
            partes.append("%s: %s" % (etiqueta, "sí" if ok else "no"))
        partes.append("SeisComp %s"
                      % ("se reusará" if self._seiscomp_reusa(ini[1], fin[1])
                         else "se consultará"))
        self.estado_archivos.configure(
            text="En disco — " + " · ".join(partes),
            bootstyle="secondary")

    def _al_editar_fecha(self, _evento=None):
        """Reactualiza el indicador y se lleva el aviso de error viejo.

        Si el usuario pulsa «Ya los tengo», ve en rojo lo que falta, corrige las
        fechas y el error se va con la corrección. Durante una tarea en curso no
        se toca el aviso, que ahí son mensajes del proceso.
        """
        if self.trabajando:
            return
        if self.aviso.cget("text"):
            self.aviso.configure(text="")
        self._refrescar_estado_archivos()

    # ------------------------------------------------------------- acciones
    def _validar_campos(self, pedir_pass):
        self.aviso.configure(text="")
        ini = _validar(self.ent_ini.get())
        if ini is None:
            self.aviso.configure(
                text="El inicio debe ser AAAAMMDDHHMMSS (14 dígitos).")
            return False
        fin = _validar(self.ent_fin.get())
        if fin is None:
            self.aviso.configure(
                text="El fin debe ser AAAAMMDDHHMMSS (14 dígitos).")
            return False
        if fin[0] <= ini[0]:
            self.aviso.configure(text="El fin debe ser posterior al inicio.")
            return False
        if pedir_pass and not self.ent_pass.get():
            self.aviso.configure(
                text="Falta la contraseña del servidor %s." % tc.IP_REMOTA)
            return False
        self._inicio = ini[1]
        self._fin = fin[1]
        self._pass = self.ent_pass.get()
        return True

    def _solicitar(self):
        self._iniciar("descargar")

    def _ya_los_tengo(self):
        # «Ya los tengo» no es un atajo: exige que los catálogos de esa
        # ventana estén en la carpeta de ejecución. Antes se avisaba en el
        # registro y se seguía, y el fallo aparecía más tarde, en el análisis.
        if not self._validar_campos(pedir_pass=False):
            return
        faltan = self._revisar_locales(self._inicio, self._fin)
        if faltan:
            self.aviso.configure(
                text="Faltan catálogos de la ventana %s - %s en %s:\n%s\n"
                     "Vuelva a «Solicitar y descargar» o ajuste las fechas."
                     % (self._inicio, self._fin, os.getcwd(),
                        "".join("  - %s\n" % n for n in faltan)))
            return
        self._iniciar("usar")

    def _iniciar(self, modo):
        if self.trabajando:
            return
        if not self._validar_campos(pedir_pass=(modo == "descargar")):
            return
        self._set_trabajando(True)
        threading.Thread(target=self._tarea, args=(modo,),
                         daemon=True).start()

    def _set_trabajando(self, valor):
        self.trabajando = valor
        estado = DISABLED if valor else NORMAL
        for b in self.botones:
            b.configure(state=estado)
        if valor:
            self.barra_valor = 0
            self.barra.configure(value=0)
            self._texto_estado = "Iniciando…"
            self._t0 = time.time()
            self.estado.configure(text=self._texto_estado)
            self._refrescar_estado()
        else:
            self.actividad.configure(text="")

    # ------------------------------------------------------------- tarea
    def _tarea(self, modo):
        try:
            cwd = os.getcwd()
            rutas.asegurar_dirs()
            inicio14, fin14 = self._inicio, self._fin

            self.plan_etapas = (PLAN_DESCARGAR if modo == "descargar"
                                else PLAN_USAR)

            nombre_select = "select_%s_%s.out" % (inicio14, fin14)
            ruta_select = os.path.join(cwd, nombre_select)
            ruta_evento = os.path.join(
                cwd, "eventquery_%s_%s.csv" % (inicio14, fin14))

            if modo == "descargar":
                self._fijar_etapa(0)
                with tc.Conexion(self._pass, log=self._log) as conexion:
                    tc.verificar_conexion(conexion, log=self._log,
                                          progreso=self._progreso_local)
                    self._fijar_etapa(1)
                    tc.traer_seisan(inicio14, fin14, conexion, cwd=cwd,
                                    log=self._log,
                                    progreso=self._progreso_local)
                    self._fijar_etapa(2)
                    tc.traer_eventquery(inicio14, fin14, conexion, cwd=cwd,
                                        log=self._log,
                                        progreso=self._progreso_local)

            # revisaselect.py abre literalmente "select.out": el archivo con
            # fechas es el de reuso y este es el que consume el análisis.
            # Ahora que ambos caminos/start guarantee el archivo (descarga o
            # verificación previa), si falta es un error, no un aviso.
            self._fijar_etapa(3 if modo == "descargar" else 0)
            if not _hay_archivo(ruta_select):
                raise RuntimeError(
                    "No se obtuvo %s. Vuelva a «Solicitar y descargar»."
                    % nombre_select)
            shutil.copyfile(ruta_select, os.path.join(cwd, "select.out"))
            self._log("select.out actualizado desde %s" % nombre_select)

            if not _hay_archivo(ruta_evento):
                raise RuntimeError(
                    "No se obtuvo %s. Vuelva a «Solicitar y descargar»."
                    % os.path.basename(ruta_evento))

            self._exportar_seiscomp(
                inicio14, fin14,
                4 if modo == "descargar" else 1,
                5 if modo == "descargar" else 2)

            self._log("Listo. Se abre la revisión con %s."
                      % os.path.basename(ruta_evento))
            self.cola.put(("fin", ruta_evento))
        except Exception as e:
            self.cola.put(("error", str(e)))

    def _exportar_seiscomp(self, inicio14, fin14, i_verifica, i_exporta):
        self._fijar_etapa(i_verifica)
        self._log("***** Verificando el entorno de SeisComp *****")
        if self._popen([os.path.join(SCRIPT_DIR, "verifica_entorno.py")]) != 0:
            raise RuntimeError(
                "El entorno no está listo; no se exportó SeisComp (ver el "
                "registro).")
        self._fijar_etapa(i_exporta)
        self._log("***** Exportando SeisComp (%s - %s) *****"
                  % (inicio14, fin14))
        exportador = os.path.join(SCRIPT_DIR, "exporta_ventana_seiscomp.py")
        if self._popen([exportador, "--reusar", inicio14, fin14]) != 0:
            raise RuntimeError("La exportación de SeisComp falló (ver el "
                               "registro).")

    def _popen(self, args):
        args = [PY] + args
        self._log("$ " + " ".join(args))
        env = dict(os.environ)
        # Los scripts que hablan el protocolo de prog.py emiten marcadores
        # @@PROGRESO@@ <fracción> por stdout; acá se traducen a la etapa en
        # curso y no se muestran en el registro.
        env["RV_PROG"] = "1"
        try:
            p = subprocess.Popen(args, cwd=os.getcwd(),
                                 stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT,
                                 universal_newlines=True, bufsize=1,
                                 env=env)
        except OSError as e:
            raise RuntimeError("No se pudo ejecutar %s: %s" % (args[0], e))
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
        return p.returncode

    # ------------------------------------------------------------- cierre
    def _terminar_ok(self, ruta_evento):
        salida = os.path.join("trabajo", "salida.dat")
        try:
            self.raiz.destroy()
        except Exception:
            pass
        os.execv(PY, [PY, os.path.join(SCRIPT_DIR, "app.py"),
                      ruta_evento, salida])

    def _terminar_error(self, mensaje):
        print("[solicitud] %s" % mensaje, file=sys.stderr)
        try:
            self.raiz.destroy()
        except Exception:
            pass
        sys.exit(1)

    def _cancelar(self):
        print("[solicitud] Cancelado por el usuario.", file=sys.stderr)
        try:
            self.raiz.destroy()
        except Exception:
            pass
        sys.exit(1)


def main():
    App().raiz.mainloop()


if __name__ == "__main__":
    main()
