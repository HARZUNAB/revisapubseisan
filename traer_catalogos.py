#!/usr/bin/env python3
"""
traer_catalogos.py
==================
Capa de red (SSH/SCP) para obtener los catálogos de Seisan y eventquery desde
el servidor remoto. No tiene interfaz gráfica: la ventana de solicitud la
armá solicita_catalogos.py, y acá vive solo lo que habla con el servidor.

Por qué está separado
---------------------
La conexión se prueba y se depura sin levantar la ventana, y la lógica de red
queda en un solo archivo. Si algún día cambia el servidor o el usuario, se toca
solo acá.

Cómo se entrega la contraseña
-----------------------------
No se usa sshpass (no está instalado) ni se pasa la clave por la línea de
comandos, donde quedaría visible en el listado de procesos. Se usa el mecanismo
de OpenSSH: un pequeño ayudante apuntado por SSH_ASKPASS que imprime la clave
que recibe por entorno, forzado con SSH_ASKPASS_REQUIRE=force (OpenSSH 8.4+).
El ayudante se crea en un directorio temporal con permisos 700 y se borra al
terminar.

Sobre `select`
--------------
`select` es palabra reservada de bash (el menú `select ... in ...`). Si se
invocara como `bash -lc 'select select.inp'`, bash intentaría tomarlo como el
menú y daría error de sintaxis. Por eso la ruta se resuelve con `type -P`
(que ignora palabras reservadas y funciones) y se invoca por ruta absoluta.
"""
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from datetime import datetime

USUARIO_REMOTO = "sysopr"
IP_REMOTA = "10.54.217.9"
DIR_TMP = "tmp"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PLANTILLA = os.path.join(SCRIPT_DIR, "plantillas", "select.inp")

FORMATO_14 = "%Y%m%d%H%M%S"
FORMATO_ISO = "%Y-%m-%dT%H:%M:%S"

SELECT_INP = "select.inp"
SALIDA_SELECT = "select.out"
SALIDA_EVENTQUERY = "eventquery.csv"

# accept-new acepta la clave del servidor la primera vez y la deja en
# ~/.ssh/known_hosts; después ya no pregunta. El servidor no estaba en
# known_hosts al escribir esto.
OPCIONES_SSH = [
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=3",
]


def a_iso(marca14):
    """AAAAMMDDHHMMSS -> AAAA-MM-DDTHH:MM:SS (lo que espera eventquery)."""
    return datetime.strptime(marca14, FORMATO_14).strftime(FORMATO_ISO)


def generar_select_inp(inicio14, fin14, destino):
    """
    Copia plantillas/select.inp cambiando SOLO los valores de las líneas
    'Start time' y 'End time'.

    Se trabaja en bytes y con sustitución por línea para no tocar el resto del
    archivo: la plantilla trae 65 bytes NUL en dos líneas de campos fijos, y
    reescribirla de texto los perdería. Se exige exactamente un reemplazo por
    etiqueta: si la plantilla cambia y deja de calzar, mejor fallar que generar
    un .inp a medias.
    """
    with open(PLANTILLA, "rb") as f:
        data = f.read()

    for etiqueta, valor in ((b"Start time", inicio14), (b"End time", fin14)):
        patron = re.compile(
            rb"(" + re.escape(etiqueta) + rb"\s*:\s*)\d{14}")
        data, n = patron.subn(rb"\g<1>" + valor.encode("ascii"), data)
        if n != 1:
            raise RuntimeError(
                "La plantilla %s no tiene una línea '%s' reemplazable "
                "(se encontraron %d)." % (PLANTILLA, etiqueta.decode(), n))

    carpeta = os.path.dirname(os.path.abspath(destino))
    os.makedirs(carpeta, exist_ok=True)
    with open(destino, "wb") as f:
        f.write(data)
    return destino


class Conexion:
    """Sesión con el servidor remoto. Se usa como context manager."""

    def __init__(self, contrasena, log=None):
        self.contrasena = contrasena
        self.log = log or (lambda _t: None)
        self._dir = None
        self._askpass = None

    def __enter__(self):
        self._preparar()
        return self

    def __exit__(self, *_):
        self.cerrar()

    # ------------------------------------------------------------- ayudante
    def _preparar(self):
        self._dir = tempfile.mkdtemp(prefix="rv_askpass_")
        os.chmod(self._dir, 0o700)
        self._askpass = os.path.join(self._dir, "askpass.sh")
        with open(self._askpass, "w") as f:
            f.write("#!/bin/sh\nprintf '%s' \"$RV_SSH_PASS\"\n")
        os.chmod(self._askpass, 0o700)

    def cerrar(self):
        if self._dir and os.path.isdir(self._dir):
            shutil.rmtree(self._dir, ignore_errors=True)
        self._dir = None
        self._askpass = None

    def _entorno(self):
        env = dict(os.environ)
        env["RV_SSH_PASS"] = self.contrasena
        env["SSH_ASKPASS"] = self._askpass
        env["SSH_ASKPASS_REQUIRE"] = "force"
        return env

    # ------------------------------------------------------------- procesos
    def _correr(self, args):
        self.log("$ " + " ".join(shlex.quote(a) for a in args))
        try:
            p = subprocess.Popen(
                args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, universal_newlines=True,
                bufsize=1, env=self._entorno())
        except OSError as e:
            raise RuntimeError("No se pudo ejecutar %s: %s" % (args[0], e))
        for linea in p.stdout:
            self.log(linea.rstrip("\n"))
        p.wait()
        return p.returncode

    def _capturar(self, args):
        try:
            p = subprocess.run(
                args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, universal_newlines=True,
                env=self._entorno())
        except OSError as e:
            raise RuntimeError("No se pudo ejecutar %s: %s" % (args[0], e))
        return p.returncode, p.stdout

    def _remoto(self):
        return "%s@%s" % (USUARIO_REMOTO, IP_REMOTA)

    def _ssh(self, comando):
        args = ["ssh"] + OPCIONES_SSH + [self._remoto(), comando]
        if self._correr(args) != 0:
            raise RuntimeError("La conexión SSH falló. Revise el registro.")

    def ssh_login(self, comando):
        """
        Corre `comando` en un shell de login del remoto.

        El shell de login es lo que carga el PATH donde viven Seisan y
        eventquery: `ssh host comando` a secas no lee los archivos de perfil.
        """
        self._ssh("bash -lc %s" % shlex.quote(comando))

    def resolver(self, nombre):
        """Ruta absoluta de un ejecutable en el PATH del login del remoto."""
        cmd = "type -P %s" % shlex.quote(nombre)
        args = ["ssh"] + OPCIONES_SSH + [
            self._remoto(), "bash -lc %s" % shlex.quote(cmd)]
        codigo, salida = self._capturar(args)
        rutas = [l.strip() for l in salida.splitlines() if l.strip()]
        if codigo != 0 or not rutas:
            raise RuntimeError(
                "No se encontró '%s' en el PATH de %s@%s. Revise que el shell "
                "de login cargue el entorno (Seisan/eventquery)."
                % (nombre, USUARIO_REMOTO, IP_REMOTA))
        return rutas[-1]

    def subir(self, local, remoto):
        destino = "%s:%s" % (self._remoto(), remoto)
        args = ["scp"] + OPCIONES_SSH + [local, destino]
        if self._correr(args) != 0:
            raise RuntimeError("Falló la subida de %s al servidor." % local)

    def bajar(self, remoto, local):
        origen = "%s:%s" % (self._remoto(), remoto)
        args = ["scp"] + OPCIONES_SSH + [origen, local]
        if self._correr(args) != 0:
            raise RuntimeError(
                "Falló la bajada de %s desde el servidor." % remoto)


def _ruta_tmp(nombre):
    return "%s/%s" % (DIR_TMP, nombre)


def _emitir(progreso, fraccion):
    """Informa la fracción [0,1] de una etapa, si hay interesado."""
    if progreso is not None:
        progreso(max(0.0, min(1.0, fraccion)))


def verificar_conexion(conexion, log=None, progreso=None):
    log = log or (lambda _t: None)
    log("[+] Conectando a %s@%s ..." % (USUARIO_REMOTO, IP_REMOTA))
    _emitir(progreso, 0.1)
    conexion.ssh_login("echo OK")
    log("[+] Conexión establecida con el servidor.")
    _emitir(progreso, 1.0)


def traer_seisan(inicio14, fin14, conexion, cwd=".", log=None, progreso=None,
                 forzar=False):
    """
    Baja el select de Seisan para la ventana pedida.

    Reuso: si ya está el archivo local de esa ventana, no se vuelve a consultar
    el servidor. El archivo lleva las fechas en el nombre justamente para poder
    reusarlo sin ambigüedad. Con 'forzar' se rebaja aunque exista (re-exportar).
    """
    log = log or (lambda _t: None)
    nombre_salida = "select_%s_%s.out" % (inicio14, fin14)
    destino = os.path.join(cwd, nombre_salida)
    if not forzar and os.path.isfile(destino) and os.path.getsize(destino) > 0:
        log("[reuso] Seisan ya estaba en disco: %s" % nombre_salida)
        _emitir(progreso, 1.0)
        return destino

    select_inp_local = os.path.join(cwd, "trabajo", SELECT_INP)
    generar_select_inp(inicio14, fin14, select_inp_local)
    _emitir(progreso, 0.1)

    ruta_select = conexion.resolver("select")
    log("[+] select remoto: %s" % ruta_select)
    _emitir(progreso, 0.25)

    conexion.ssh_login("mkdir -p %s" % shlex.quote(DIR_TMP))
    conexion.subir(select_inp_local, _ruta_tmp(SELECT_INP))
    _emitir(progreso, 0.4)

    comando = "cd %s && %s %s && mv -f %s %s" % (
        shlex.quote(DIR_TMP), shlex.quote(ruta_select),
        shlex.quote(SELECT_INP), shlex.quote(SALIDA_SELECT),
        shlex.quote(nombre_salida))
    _emitir(progreso, 0.45)
    conexion.ssh_login(comando)
    _emitir(progreso, 0.85)
    conexion.bajar(_ruta_tmp(nombre_salida), destino)
    log("[OK] Seisan: %s" % nombre_salida)
    _emitir(progreso, 1.0)
    return destino


def traer_eventquery(inicio14, fin14, conexion, cwd=".", log=None,
                     progreso=None, forzar=False):
    """Baja el catálogo de eventquery para la ventana pedida (con reuso).

    Con 'forzar' se rebaja aunque el archivo exista (re-exportar).
    """
    log = log or (lambda _t: None)
    nombre_salida = "eventquery_%s_%s.csv" % (inicio14, fin14)
    destino = os.path.join(cwd, nombre_salida)
    if not forzar and os.path.isfile(destino) and os.path.getsize(destino) > 0:
        log("[reuso] eventquery ya estaba en disco: %s" % nombre_salida)
        _emitir(progreso, 1.0)
        return destino

    ruta_eventquery = conexion.resolver("eventquery")
    log("[+] eventquery remoto: %s" % ruta_eventquery)
    _emitir(progreso, 0.15)

    conexion.ssh_login("mkdir -p %s" % shlex.quote(DIR_TMP))
    _emitir(progreso, 0.2)
    comando = "cd %s && %s --start-time %s --end-time %s %s" % (
        shlex.quote(DIR_TMP), shlex.quote(ruta_eventquery),
        shlex.quote(a_iso(inicio14)), shlex.quote(a_iso(fin14)),
        shlex.quote(nombre_salida))
    _emitir(progreso, 0.25)
    conexion.ssh_login(comando)
    _emitir(progreso, 0.85)
    conexion.bajar(_ruta_tmp(nombre_salida), destino)
    log("[OK] eventquery: %s" % nombre_salida)
    _emitir(progreso, 1.0)
    return destino
