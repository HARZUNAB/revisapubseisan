#!/usr/bin/env python3
"""
verifica_entorno.py
===================
Revisa que el entorno esté listo para que el proyecto funcione, y dice qué
falta. No modifica nada: solo informa. Es una herramienta de NIVEL PROYECTO:
revisa el intérprete, los módulos, la interfaz gráfica y el acceso a la base,
que son las cuatro cosas de las que depende cualquier parte del proyecto. No
revisa datos ni resultados de ninguna funcionalidad en particular.

Está pensado para que un instalador futuro lo reutilice. Por eso la lógica está
separada de la pantalla: cada función devuelve un diccionario, informe() junta
todo, y main() solo imprime. Un instalador puede usar informe() para decidir
qué instalar sin volver a implementar las comprobaciones.

Qué revisa:

  * que se esté usando el entorno virtual, y no el Python del sistema;
  * que los paquetes de requirements.txt estén en la versión que se pide;
  * que tkinter esté disponible, que es lo único que NO se puede resolver con
    pip porque viene del Python instalado;
  * que se pueda llegar a la base de datos, distinguiendo un rechazo de
    permisos de una caída de red.

Uso:
    .venv/bin/python verifica_entorno.py

Devuelve 0 si no falta nada obligatorio, y 1 si falta algo.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
REQUISITOS = os.path.join(RAIZ, "requirements.txt")

# tkinter viene del Python instalado y no se puede instalar con pip. Estos son
# los nombres del paquete según la distribución, para poder sugerirlo.
PAQUETES_TKINTER = {
    "debian": "python3-tk",
    "ubuntu": "python3-tk",
    "rhel": "python3-tkinter",
    "centos": "python3-tkinter",
    "fedora": "python3-tkinter",
    "suse": "python3-tk",
    "arch": "tk",
}


def _distro():
    """Nombre de la distribución, en minúsculas, o una cadena vacía."""
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for linea in f:
                if linea.startswith("ID="):
                    return linea.split("=", 1)[1].strip().strip('"').lower()
    except OSError:
        pass
    return ""


def verificar_venv():
    """Comprueba si el intérprete actual es un entorno virtual."""
    dentro = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    return {
        "ok": dentro,
        "titulo": "Entorno virtual",
        "detalle": ("%s%s" % (sys.prefix, "" if dentro else
                              "  <-- NO es un entorno virtual")),
        "aviso": ("" if dentro else
                  "Instalá los módulos con '%s -m pip install -r requirements.txt'"
                  % os.path.join(sys.prefix, "bin", "python")),
    }


def _version_instalada(nombre):
    """
    Versión de un paquete instalado, o None.

    Se consulta con pkg_resources y no importando el paquete: importar todo
    tardaría y podría tener efectos. Ojo que en Python 3.7 no existe
    importlib.metadata, que es lo que se usaría a partir de 3.8.
    """
    try:
        import pkg_resources
    except ImportError:
        return None
    try:
        return pkg_resources.get_distribution(nombre).version
    except Exception:
        return None


def _pedidos(ruta=REQUISITOS):
    """Lee requirements.txt y devuelve {paquete: version}. None si no hay pin."""
    pedidos = {}
    try:
        with open(ruta, encoding="utf-8") as f:
            for linea in f:
                linea = linea.split("#")[0].strip()
                if not linea:
                    continue
                if "==" in linea:
                    nombre, version = linea.split("==", 1)
                    pedidos[nombre.strip().lower()] = version.strip()
                else:
                    pedidos[linea.split(">=")[0].split("<=")[0].strip().lower()] = None
    except OSError:
        pass
    return pedidos


def verificar_requirements(ruta=REQUISITOS):
    """Compara cada paquete de requirements.txt con lo que hay instalado."""
    pedidos = _pedidos(ruta)
    faltantes, distintas = [], []
    for nombre, version in sorted(pedidos.items()):
        instalada = _version_instalada(nombre)
        if instalada is None:
            faltantes.append(nombre)
        elif version and instalada != version:
            distintas.append("%s (pide %s, hay %s)" % (nombre, version, instalada))
    detalle = "%d paquetes" % len(pedidos)
    if not pedidos:
        detalle = "no se pudo leer %s" % ruta
    return {
        "ok": not faltantes and not distintas,
        "titulo": "Paquetes de Python",
        "detalle": detalle,
        "faltantes": faltantes,
        "distintas": distintas,
        "aviso": ("Faltan: %s" % ", ".join(faltantes) if faltantes else "") +
                  (" | Versiones distintas: %s" % "; ".join(distintas)
                   if distintas else ""),
    }


def verificar_tkinter():
    """
    Comprueba tkinter, que es la dependencia que no viene de pip.

    Si falta, el problema no se arregla en el entorno virtual: hay que instalar
    el paquete del sistema, y eso sí necesita permisos de administrador.
    """
    try:
        import tkinter
        return {
            "ok": True,
            "titulo": "Interfaz gráfica (tkinter)",
            "detalle": "Tcl/Tk %s" % tkinter.TkVersion,
            "aviso": "",
        }
    except ImportError as e:
        paquete = PAQUETES_TKINTER.get(_distro(), "python3-tk")
        return {
            "ok": False,
            "titulo": "Interfaz gráfica (tkinter)",
            "detalle": "no está disponible",
            "aviso": "Falta a nivel de máquina, no se arregla con pip.\n"
                     "        Instalá el paquete '%s' del sistema y volvé a probar."
                     % paquete,
            "error": str(e),
        }


def verificar_base(config=None):
    """
    Comprueba que se pueda conectar a la base, sin escribir nada.

    Se distinguen dos fallos porque se resuelven distinto: si el servidor
    rechaza por permisos (pg_hba) hay que hablar con el administrador de
    SeisComp; si no resuelve el nombre o no hay red, el problema es local.
    """
    if config is None:
        try:
            import exporta_ventana_seiscomp as ev
            config = ev.configuracion()
        except Exception as e:
            return {
                "ok": False, "titulo": "Base de datos",
                "detalle": "no se pudo leer la configuración",
                "aviso": str(e), "error": str(e),
            }
    titulo = "Base de datos %s@%s/%s" % (config["user"], config["host"],
                                         config["database"])
    try:
        import psycopg2
    except ImportError:
        return {
            "ok": False, "titulo": titulo,
            "detalle": "falta el módulo psycopg2",
            "aviso": "Instalalo con pip en el entorno virtual.",
        }
    try:
        conn = psycopg2.connect(host=config["host"], database=config["database"],
                                user=config["user"], password=config["password"],
                                connect_timeout=10)
        conn.close()
    except Exception as e:
        texto = str(e).strip()
        if "pg_hba" in texto:
            aviso = ("El servidor rechaza la conexión por permisos. "
                     "Hay que pedirle al administrador de SeisComp que habilite "
                     "este usuario desde esta máquina.")
        elif "could not translate host name" in texto or "Name or service" in texto:
            aviso = ("No se puede resolver el servidor. Revisá la red o el nombre "
                     "en el global.cfg.")
        elif "does not exist" in texto:
            aviso = "Esa base no existe en el servidor."
        else:
            aviso = "No se pudo conectar: %s" % texto.splitlines()[0]
        return {"ok": False, "titulo": titulo, "detalle": "no se pudo conectar",
                "aviso": aviso, "error": texto}
    return {"ok": True, "titulo": titulo, "detalle": "conexión OK",
            "aviso": ""}


def informe():
    """
    Corre todas las comprobaciones y devuelve los resultados.

    Cada revisión va en su propio try: que una falle no impide que las demás
    informen, que es justo lo que se necesita para ver qué falta.

    Solo se revisa el ENTORNO: el entorno virtual, los módulos, tkinter y la
    conexión a la base. Saber qué archivos hay exportados no es una condición
    del entorno sino un dato de la funcionalidad de SeisComp, y esa búsqueda
    vive con esa funcionalidad, no acá.
    """
    revisiones = [
        ("venv", verificar_venv()),
        ("requisitos", verificar_requirements()),
        ("tkinter", verificar_tkinter()),
        ("base", verificar_base()),
    ]
    obligatorias = {"venv", "requisitos", "base"}
    faltan = [nombre for nombre, r in revisiones if nombre in obligatorias
              and not r["ok"]]
    return {"revisiones": revisiones, "faltan": faltan,
            "ok": not faltan}


def main():
    resultado = informe()
    print("Verificación del entorno")
    print("=" * 68)
    for nombre, r in resultado["revisiones"]:
        marca = "  OK  " if r["ok"] else " FALTA"
        print("[%s] %-28s %s" % (marca, r["titulo"], r["detalle"]))
        if r.get("aviso"):
            for linea in r["aviso"].splitlines():
                print("        -> %s" % linea)
    print("=" * 68)
    if resultado["ok"]:
        print("Todo lo necesario está en su lugar.")
        return 0
    print("Falta resolver: %s" % ", ".join(resultado["faltan"]))
    return 1


if __name__ == "__main__":
    sys.exit(main())
