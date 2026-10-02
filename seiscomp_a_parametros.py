#!/usr/bin/env python3
"""
seiscomp_a_parametros.py
========================
Convierte una exportación de SeisComp (datos/seiscomp_<inicio>_<fin>.csv) al
formato de columnas que generajson.py ya sabe leer, para que SeisComp entre al
mismo panel de análisis que Seisan y eventquery, con su perfil de subducción,
sus sospechosos y el responsable de cada solución.

Por qué hace falta un conversor
------------------------------
generajson.py lee los CSV por POSICIÓN, y la columna 0 tiene que ser el índice
de la fila: de ahí salen 'id' y 'n_fila_origen', que es el enlace de
trazabilidad de vuelta al archivo crudo. El archivo de Seisan que produce
revisacollect.py tiene 8 columnas, con el índice como columna 0 porque pandas
escribe el índice por defecto. Este script reproduce ese mismo formato, con el
OPERADOR de la solución preferred de SeisComp en la columna del analista.

Lo que NO se copia
------------------
La exportación cruda tiene 15 columnas, y varias no se copian: el panel de
análisis no las usa y el CSV crudo queda intacto al lado, para el análisis de
estaciones y fases. En particular no se copia 'region', porque la columna del
analista ya la ocupa el operador, y la región se ve igual en el panel de
revisión de SeisComp.

    columnas crudas -> columnas del conversor
    ot_utc          -> Fecha_Hora
    latitud         -> Latitud
    longitud        -> Longitud
    profundidad_km  -> Prof.        (positiva en km, tal como la guarda SeisComp)
    magnitud        -> Mag.
    tipo_magnitud   -> Tipo_mag.
    operador        -> Analista

Profundidad
-----------
Se copia tal cual, en kilómetros y con signo positivo hacia abajo, que es como
SeisComp la guarda (m_depth_value). Es la convención del catálogo histórico
base_2020_2026.csv, contra el que sismicidad.py calcula el knn y la mediana de
profundidad, y la que plotear.py invierte al dibujar la sección.

Filas que no se pueden convertir
--------------------------------
Solo se descarta un evento si su latitud o su longitud no se pueden leer como
número, porque sin eso no hay a qué perfil asignarlo ni dónde dibujarlo. Un
evento SIN magnitud sí se convierte: la magnitud es texto en el JSON y nada la
convierte a float, así que un origen sin magnitud preferida se dibuja igual y
simplemente no se le rotula el número.

generajson.py descarta esas mismas filas en silencio (un 'except: continue' sin
contar), así que este script cuenta y avisa cuántas dejó afuera. Sin ese aviso
el total ploteado no se puede reconciliar con el total de la exportación.

Uso:
    python3 seiscomp_a_parametros.py <exportacion.csv> [salida.csv]
"""

import csv
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import rutas
import prog

# Columnas de la exportación que hacen falta para convertir. Si el esquema de
# la base cambiara y el SELECT dejara de devolver alguna, el nombre nuevo
# aparecería acá y el error lo diría, en vez de escribir una columna de vacío.
COLUMNAS_DE_LA_EXPORTACION = (
    "ot_utc", "latitud", "longitud", "profundidad_km", "magnitud",
    "tipo_magnitud", "operador",
)

# Encabezado de la salida. El primer campo va vacío a propósito: es la columna
# del índice, y así lo escribe pandas en los CSV del resto del flujo.
ENCABEZADO = ("", "Fecha_Hora", "Latitud", "Longitud", "Prof.", "Mag.",
              "Tipo_mag.", "Analista")


def _numero(texto):
    """Devuelve el texto como float, o None si no es un número."""
    if texto is None:
        return None
    limpio = str(texto).strip()
    if not limpio:
        return None
    try:
        return float(limpio)
    except ValueError:
        return None


def convertir(ruta_origen, ruta_destino=None):
    """
    Convierte la exportación y escribe el archivo de 8 columnas.

    Devuelve un dict con el resumen: leidas, convertidas, descartadas, sin
    latitud/longitud, sin magnitud, con profundidad, por operador y las
    ventanas de la exportación.
    """
    if ruta_destino is None:
        ruta_destino = rutas.p_datos("seiscomp_parametros.csv")

    if not os.path.isfile(ruta_origen):
        raise IOError("No se encontró la exportación '%s'." % ruta_origen)

    prog.avance_reset()

    with open(ruta_origen, encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f)
        nombres = set(lector.fieldnames or [])
        faltantes = [c for c in COLUMNAS_DE_LA_EXPORTACION if c not in nombres]
        if faltantes:
            raise ValueError(
                "La exportación '%s' no tiene las columnas %s.\n"
                "    Tiene: %s\n"
                "    Si el esquema de la base cambió, hay que revisar el "
                "SELECT de exporta_ventana_seiscomp.py."
                % (os.path.basename(ruta_origen), ", ".join(faltantes),
                   ", ".join(sorted(nombres))))

        filas = list(lector)

    total = max(1, len(filas))
    resumen = {
        "leidas": len(filas),
        "convertidas": 0,
        "descartadas": 0,
        "sin_coordenadas": 0,
        "sin_magnitud": 0,
        "sin_profundidad": 0,
        "con_profundidad": 0,
        "por_operador": {},
        "ventana": (None, None),
    }

    with open(ruta_destino, "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(ENCABEZADO)
        for i, fila in enumerate(filas):
            prog.avance((i + 1) / total)

            latitud = _numero(fila.get("latitud"))
            longitud = _numero(fila.get("longitud"))
            if latitud is None or longitud is None:
                # Sin coordenadas no hay perfil ni posición: no se convierte.
                resumen["descartadas"] += 1
                resumen["sin_coordenadas"] += 1
                continue

            profundidad = (fila.get("profundidad_km") or "").strip()
            magnitud = (fila.get("magnitud") or "").strip()
            operador = (fila.get("operador") or "").strip()

            if profundidad:
                resumen["con_profundidad"] += 1
            else:
                resumen["sin_profundidad"] += 1
            if not magnitud:
                resumen["sin_magnitud"] += 1

            # La primera columna es el número de fila EN LA EXPORTACIÓN, no un
            # contador de filas convertidas. Si se renumerara al saltar una
            # fila, 'n_fila_origen' apuntaría a otro evento del CSV crudo y la
            # trazabilidad del panel de análisis mentiría.
            fecha = (fila.get("ot_utc") or "").strip()
            escritor.writerow([i, fecha,
                               (fila.get("latitud") or "").strip(),
                               (fila.get("longitud") or "").strip(),
                               profundidad, magnitud,
                               (fila.get("tipo_magnitud") or "").strip(),
                               operador])
            resumen["convertidas"] += 1
            if operador:
                resumen["por_operador"][operador] = \
                    resumen["por_operador"].get(operador, 0) + 1
            if fecha:
                # La exportación NO viene ordenada por tiempo: al fusionar las
                # bases, un evento de seiscomp puede quedar antes que uno de
                # seiscomp2 aunque sea posterior. Por eso la ventana se toma
                # con mínimo y máximo y no con la primera y la última fila.
                inicio, fin = resumen["ventana"]
                if inicio is None or fecha < inicio:
                    inicio = fecha
                if fin is None or fecha > fin:
                    fin = fecha
                resumen["ventana"] = (inicio, fin)

    prog.avance(1.0)
    return resumen


def _ruta_completo(ruta_eventos):
    """
    Nombre de la marca que dice que la exportación terminó.

    Es la misma regla que usa exporta_ventana_seiscomp.py: la marca va pegada
    al nombre del CSV de eventos. Se replica acá en vez de importarse para que
    este script no dependa del exportador, que necesita psycopg2.
    """
    base, extension = os.path.splitext(ruta_eventos)
    return "%s%s.completo" % (base, extension or ".csv")


def _avisar_sin_marca(ruta_origen):
    """Avisa si la exportación no tiene la marca de que terminó."""
    marca = _ruta_completo(ruta_origen)
    if not os.path.isfile(marca):
        print("   [Aviso] No está la marca de exportación completa (%s)."
              % os.path.basename(marca))
        print("           Si la exportación se cortó a mitad de camino, este"
              " archivo puede estar incompleto.")


def informe(resumen, ruta_origen, ruta_destino):
    """Imprime el resumen de la conversión."""
    print("   Origen        : %s" % os.path.basename(ruta_origen))
    inicio, fin = resumen["ventana"]
    if inicio or fin:
        print("   Ventana       : %s  ->  %s" % (inicio, fin))
    print("   Eventos leídos: %d" % resumen["leidas"])
    print("   Convertidos   : %d" % resumen["convertidas"])
    if resumen["descartadas"]:
        print("   [Aviso] %d evento(s) quedaron afuera por no tener latitud o"
              " longitud:" % resumen["descartadas"])
        print("           %d convertidas + %d descartadas = %d leídas"
              % (resumen["convertidas"], resumen["descartadas"],
                 resumen["leidas"]))
    if resumen["sin_magnitud"]:
        print("   [Aviso] %d evento(s) sin magnitud preferida: se dibujan sin"
              " rótulo de magnitud." % resumen["sin_magnitud"])
    if resumen["sin_profundidad"]:
        print("   [Aviso] %d evento(s) sin profundidad: no se les pueden"
              " aplicar los criterios de profundidad." % resumen["sin_profundidad"])
    else:
        print("   Con profundidad: %d" % resumen["con_profundidad"])
    if resumen["por_operador"]:
        print("   Por operador (a quién notificar):")
        for operador in sorted(resumen["por_operador"],
                               key=lambda o: -resumen["por_operador"][o]):
            print("     %-28s %d" % (operador, resumen["por_operador"][operador]))
    print("   Archivo       : %s" % ruta_destino)


def main():
    argumentos = sys.argv[1:]
    if argumentos and argumentos[0] in ("-h", "--help", "--ayuda"):
        print(__doc__)
        return 0
    if not argumentos:
        print(__doc__)
        print("[X] Indique la exportación a convertir.")
        return 2
    if len(argumentos) > 2:
        print(__doc__)
        print("[X] Uso: seiscomp_a_parametros.py <exportacion.csv>"
              " [salida.csv]")
        return 2

    ruta_origen = argumentos[0]
    ruta_destino = argumentos[1] if len(argumentos) > 1 else None
    try:
        resumen = convertir(ruta_origen, ruta_destino)
    except (IOError, OSError, ValueError) as e:
        print("[X] %s" % e)
        return 1
    if not resumen["convertidas"]:
        print("[X] No se convirtió ningún evento; no se escribe el archivo.")
        return 1
    _avisar_sin_marca(ruta_origen)
    informe(resumen, ruta_origen,
            ruta_destino or rutas.p_datos("seiscomp_parametros.csv"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
