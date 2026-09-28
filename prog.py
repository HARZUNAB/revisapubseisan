"""
prog.py
=======
Protocolo de progreso entre los scripts del pipeline y la interfaz (app.py).

La app ejecuta los scripts con la variable de entorno RV_PROG=1; en ese modo,
este módulo emite líneas de marcador por stdout con el formato:

    @@PROGRESO@@ <fraccion>

donde <fraccion> es un número en [0, 1]. app.py detecta esas líneas y las
convierte en avance de la barra de progreso. Sin RV_PROG=1 los scripts corren
en modo CLI/standalone sin emitir marcadores (consola limpia).

Se difumina la emisión al 0.1% (1000 pasos) para no saturar el pipe.
"""

import os

_INICIO = "@@PROGRESO@@"


def avance(fraccion):
    """Emite el marcador de progreso si RV_PROG=1 está definido."""
    if not os.environ.get("RV_PROG"):
        return
    paso = int(round(max(0.0, min(1.0, fraccion)) * 1000))
    if paso != getattr(avance, "ultimo", None):
        avance.ultimo = paso
        print("%s %.4f" % (_INICIO, paso / 1000.0), flush=True)


def avance_reset():
    """Reinicia el umbral del último paso (por si se reutilizan los bucles)."""
    avance.ultimo = None