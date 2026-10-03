"""
ajuste.py
=========
Agranda una ventana hasta que su contenido entre entero, acotado por la
pantalla y sin achicarla nunca.

Por qué hace falta
-----------------
Tk ya sabe cuánto mide cada contenido: ``winfo_reqwidth()`` y
``winfo_reqheight()`` devuelven lo que la ventana tendría que medir para que
nada quede recortado. Acá se usa eso en vez de un tamaño fijo, porque el de
la ventana principal no daba abasto para el panel de análisis: esa vista pide
1182x953 y con la ventana en 980x820 el gráfico y parte de la tabla quedaban
fuera de pantalla sin avisar.

Por qué el tope es 1920x1080
-----------------------------
Es una pantalla Full HD de referencia: más ancho deja de ayudar, y más alto
que 1080 no entra en un monitor normal.

El tope real es el menor entre ese valor y lo que admite el gestor de
ventanas (``wm_maxsize()``), que ya descuenta el marco: pedir 1080 exactos en
una pantalla de 1080 dejaría el borde de abajo bajo la barra de tareas.
Cuando el contenido pide más que el tope, gana la pantalla: lo que no entra se
desplaza con sus barras horizontales.

Una trampa que conviene no olvidar
----------------------------------
Antes de que la ventana esté mapeada, Tk contesta **200x200** a
``winfo_width()`` y a ``geometry()``, y también a ``winfo_reqwidth()`` y
``winfo_reqheight()``: es el valor por defecto, no el tamaño real. Por eso el
que llama lleva el tamaño que ya sabe que tiene la ventana y lo pasa como
``minimo``, en vez de preguntarle a Tk. Y :func:`medir` llama
``update_idletasks()`` antes de preguntar, que es lo que hace que las medidas
dejen de ser 200x200.
"""

# Tope de referencia: una pantalla Full HD.
TOPE_MAXIMO = (1920, 1080)

# Margen que se deja contra el borde de la pantalla al colocar la ventana, para
# que no quede pegada ni con el borde justo en el límite.
MARGEN = 40


def techo(ventana):
    """El tamaño máximo que se le permite a esta ventana.

    Es el menor entre :data:`TOPE_MAXIMO` y lo que admite el gestor de
    ventanas. Si el gestor no está disponible, manda el valor de referencia.
    """
    ancho, alto = TOPE_MAXIMO
    try:
        maximo = ventana.wm_maxsize()
    except Exception:
        # Sin gestor de ventanas no hay nada que consultar. Queda el tope de
        # referencia, que para eso está.
        return (ancho, alto)
    return (min(ancho, maximo[0]), min(alto, maximo[1]))


def medir(ventana, minimo=(0, 0), holgura=0):
    """(ancho, alto) que debería tener la ventana para que entre su contenido.

    ``minimo`` es el piso, y es lo que hace que la ventana **solo crezca**: si
    ya está más grande de lo que el contenido pide, devuelve ese tamaño y no
    propone nada. ``holgura`` suma pixeles de margen.
    """
    ventana.update_idletasks()
    ancho = max(int(minimo[0]), int(ventana.winfo_reqwidth()) + holgura)
    alto = max(int(minimo[1]), int(ventana.winfo_reqheight()) + holgura)
    return acotar(ventana, ancho, alto)


def aplicar(ventana, ancho, alto):
    """Fija el tamaño de la ventana y la deja dentro de la pantalla.

    Al agrandarla conservando la esquina superior izquierda, el borde derecho o
    el de abajo pueden quedar fuera; se la mueve lo justo para que entre.
    """
    ancho = max(1, int(ancho))
    alto = max(1, int(alto))
    ventana.geometry("%dx%d" % (ancho, alto))
    _acotar_posicion(ventana, ancho, alto)
    return (ancho, alto)


def ajustar(ventana, minimo=(0, 0), holgura=0):
    """Mide y aplica. Devuelve el tamaño (ancho, alto) al que quedó."""
    ancho, alto = medir(ventana, minimo=minimo, holgura=holgura)
    return aplicar(ventana, ancho, alto)


def acotar(ventana, ancho, alto):
    """Baja un tamaño al tope que admite esta ventana."""
    maximo = techo(ventana)
    return (max(1, min(int(ancho), maximo[0])),
            max(1, min(int(alto), maximo[1])))


def _acotar_posicion(ventana, ancho, alto):
    """Mueve la ventana lo justo para que no se salga de la pantalla."""
    try:
        x, y = ventana.winfo_x(), ventana.winfo_y()
        max_x = max(0, ventana.winfo_screenwidth() - ancho - MARGEN)
        max_y = max(0, ventana.winfo_screenheight() - alto - MARGEN)
        if x > max_x or y > max_y:
            ventana.geometry("+%d+%d" % (min(x, max_x), min(y, max_y)))
    except Exception:
        # Sin posición conocida no hay nada que corregir; el tamaño ya está.
        pass