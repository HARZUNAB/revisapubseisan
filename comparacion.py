#!/usr/bin/env python3
"""
comparacion.py
==============
Comparación numérica de los parámetros de un evento (latitud, longitud,
profundidad y magnitud) a la precisión con la que se manejan en todo el flujo:

    latitud / longitud  -> 3 decimales (~111 m)
    profundidad         -> 1 decimal
    magnitud            -> 1 decimal

La usan compara.py (para decidir qué evento quedó "no actualizado" y escribir
los informes) y revisa_seiscomp.py (para filtrar datos/atribucion_*.csv y armar
la tabla). Vive en un módulo propio para que las dos no se separen: antes cada
archivo tenía su copia y había que cambiarlas a mano, con el riesgo de que un
día dijeran cosas distintas.

Comparar por texto, como se hacía antes, marcaba como distinto el mismo valor
escrito con distinta cantidad de decimales (-31.64 contra -31.639999...), que
es justo el falso positivo que este módulo evita: acá se comparan los números
redondeados a la precisión de cada campo.
"""

DECIMALES_COORDENADA = 3
DECIMALES_PROFUNDIDAD = 1
DECIMALES_MAGNITUD = 1


def a_numero(texto):
    """El texto como float, o None si no hay dato o no se puede leer."""
    if texto is None:
        return None
    limpio = str(texto).strip()
    if not limpio:
        return None
    try:
        return float(limpio)
    except ValueError:
        return None


def mismo_numero(a, b, decimales, ignorar_signo=False):
    """
    True si a y b son el mismo número a la cantidad de decimales pedida.

    - Si falta uno de los dos, son distintos (no hay con qué comparar), salvo
      que falten los dos, que se consideran iguales.
    - Si alguno no se puede leer como número, se comparan los textos tal cual:
      no se puede afirmar que sean iguales a partir de un dato corrupto.
    - 'ignorar_signo' es para la profundidad, donde una diferencia de
      convención (positiva/negativa) marcaría el informe entero.
    """
    a, b = ("" if a is None else str(a).strip(),
            "" if b is None else str(b).strip())
    if not a or not b:
        return a == b
    na, nb = a_numero(a), a_numero(b)
    if na is None or nb is None:
        return a == b
    if ignorar_signo:
        na, nb = abs(na), abs(nb)
    return round(na, decimales) == round(nb, decimales)


def mismo_coordenada(a, b):
    """Latitud o longitud igual a 3 decimales."""
    return mismo_numero(a, b, DECIMALES_COORDENADA)


def misma_profundidad(a, b):
    """Profundidad igual a 1 decimal, ignorando el signo."""
    return mismo_numero(a, b, DECIMALES_PROFUNDIDAD, ignorar_signo=True)


def mismo_magnitud(a, b):
    """Magnitud igual a 1 decimal."""
    return mismo_numero(a, b, DECIMALES_MAGNITUD)


def _formato(texto, decimales):
    """El número con esa cantidad de decimales, o el texto crudo si no se lee."""
    if texto is None:
        return ""
    limpio = str(texto).strip()
    if not limpio:
        return ""
    try:
        return "%.*f" % (decimales, float(limpio))
    except ValueError:
        return limpio


def formato_coordenada(texto):
    """Latitud o longitud con 3 decimales (reemplaza el relleno de ceros)."""
    return _formato(texto, DECIMALES_COORDENADA)


def formato_profundidad(texto):
    """Profundidad con 1 decimal."""
    return _formato(texto, DECIMALES_PROFUNDIDAD)


def formato_magnitud(texto):
    """Magnitud con 1 decimal."""
    return _formato(texto, DECIMALES_MAGNITUD)


def parametros_discrepantes(lat_a, lon_a, prof_a, mag_a,
                            lat_b, lon_b, prof_b, mag_b):
    """
    Nombres de los parámetros que no coinciden entre dos eventos.

    Devuelve una lista (vacía si coinciden) para que quien la use decida el
    orden y el formato. La comparación es simétrica, así que el orden de los
    dos eventos no cambia el resultado.
    """
    campos = []
    if not mismo_coordenada(lat_a, lat_b):
        campos.append("lat")
    if not mismo_coordenada(lon_a, lon_b):
        campos.append("lon")
    if not misma_profundidad(prof_a, prof_b):
        campos.append("prof")
    if not mismo_magnitud(mag_a, mag_b):
        campos.append("mag")
    return campos
