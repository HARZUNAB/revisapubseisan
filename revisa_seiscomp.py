#!/usr/bin/env python3
"""
revisa_seiscomp.py
==================
Interfaz para revisar los eventos exportados de SeisComp: a la izquierda la
lista de eventos, y al elegir uno, sus datos y sus llegadas de estación.

Lee los tres CSV que produce exporta_ventana_seiscomp.py:
  <salida>.csv               una fila por evento
  <salida>_fases.csv         una fila por llegada de estación
  <salida>_no_picadas.csv    una fila por estación sin arribos asociados

No consulta la base de datos. Eso es a propósito: la interfaz necesita
ttkbootstrap y el acceso a la base necesita psycopg2. En el proyecto NewPT de
donde viene, cada uno vivía en un intérprete distinto; acá los dos están en el
.venv, así que este script y el exportador conviven sin problema, y el lanzador
seiscomp.sh los encadena. Aun así sigue sin tocar la base: leer los archivos es
lo que permite que la revisión funcione aunque el servidor no esté disponible.

Las llegadas van agrupadas por estación y plegables, porque un evento puede
llegar a tener 180 llegadas de 94 estaciones: en una tabla plana hay que hacer
scroll para ver nada, y agrupado se lee de un vistazo qué estación aportó qué.

Uso:
    .venv/bin/python revisa_seiscomp.py [<eventos.csv> [<fases.csv>]] [--catalogo <csv>]
    ./seiscomp.sh <catalogo.csv>

Sin argumentos se abre en ./datos, la carpeta del directorio desde donde se
ejecuta el script, que es donde escribe el exportador.

El catálogo de referencia se pasa con --catalogo, y con el lanzador viene
siempre. Va explícito y no se busca solo a propósito: en la carpeta de trabajo
hay varios CSV con columna de tiempo, y no todos son un catálogo de eventos:
algunos son el fondo de sismicidad que se plotea, o un reporte de sospechosos.
Elegirlo por fecha de modificación abriría una ventana que no es la que se está
revisando, sin avisar. Con --catalogo se abre el par de exportaciones que mejor
cubre la ventana de ese catálogo, que es lo contrario de abrir la última
escrita.

Sin --catalogo se usa el de la carpeta de trabajo, y si hay más de uno gana el
modificado más recientemente. Ese camino es el que queda solo cuando se llama
este script a mano; el lanzador siempre pasa el catálogo.

Todos los archivos del flujo de revisión viven en el directorio de ejecución,
según rutas.py. Los archivos del proyecto (requirements.txt, los módulos) van
junto a los scripts, y no se mueven con el directorio de ejecución.
"""
import csv
import os
import sys
from datetime import datetime

import comparacion
import descargas
import rutas

# Con el histórico completo son casi 70.000 eventos y el árbol se vuelve lento
# para llenarlo. Se muestran estos y se avisa, pero el filtro busca sobre todos.
MAX_FILAS = 20000

# Lo que se muestra cuando la celda viene vacía. Nunca 0: un cero falso entra
# en los promedios en silencio, y acá lo que falta es que la estación no calculó
# esa magnitud, no que valga cero.
VACIO = "—"

# Formato de fecha para NOMBRES DE ARCHIVO, no para leer datos: la marca de
# ventana del exportador (seiscomp_<inicio>_<fin>.csv) y el sufijo de los CSV
# exportados. Los datos de los CSV nunca vienen en este formato, por eso el
# parseo vive aparte, en _partir_fecha_hora, que es el único que se usa.
FORMATO_FECHA = "%Y%m%d%H%M%S"

# Qué columna del evento guarda cada columna numérica del árbol. Hace falta
# para ordenar: si se ordenara por el texto ya formateado, "10.0" quedaría antes
# que "3.5" y el guion de "sin dato" se mezclaría con los números.
COLUMNA_NUMERICA = {
    "mag": "magnitud",
    "prof": "profundidad_km",
    "fases": "fases",
    "latitud": "latitud",
    "longitud": "longitud",
}

# Decimales con los que se muestran las coordenadas. Son tres, la convención con
# que se tratan en todo el flujo (Seisan, eventquery y SeisComp los dan así), y
# no uno o dos porque a -25.96 y -26.04, que a un decimal se ven -26.0 y -26.0,
# se los tiene que poder distinguir. El filtro usa la misma constante, para que
# la columna y la banda no puedan terminar mostrando una cosa y filtrando otra.
DECIMALES_COORD = 3

# Columnas del árbol de eventos: (clave, título, ancho).
COLUMNAS_EVENTO = [
    ("fecha", "Fecha", 90),
    ("hora", "Hora", 80),
    ("id", "Id evento", 190),
    ("mag", "Mag", 55),
    ("tipo", "Tipo", 55),
    ("prof", "Prof (km)", 80),
    ("latitud", "Lat", 80),
    ("longitud", "Lon", 80),
    ("region", "Región", 240),
    ("fases", "Fases", 55),
    ("operador", "Operador", 90),
    ("estatus", "Estatus", 90),
    ("base", "Base", 90),
]

# Columnas de las pestañas de catálogo (Seisan / eventquery). A diferencia de
# COLUMNAS_EVENTO, ésta NO es la de SeisComp: estas dos son listas simples, sin
# detalle de llegadas ni paneles. Tupla: (clave, título, ancho, ¿numérica?).
COLUMNAS_CATALOGO_SEISAN = [
    ("fecha", "Fecha", 95, False),
    ("hora", "Hora", 85, False),
    ("latitud", "Lat", 80, True),
    ("longitud", "Lon", 80, True),
    ("prof", "Prof (km)", 80, True),
    ("mag", "Mag", 60, True),
    ("tipo", "Tipo", 60, False),
    ("analista", "Analista", 110, False),
]
COLUMNAS_CATALOGO_EVENTQUERY = [
    ("fecha", "Fecha", 95, False),
    ("hora", "Hora", 85, False),
    ("latitud", "Lat", 80, True),
    ("longitud", "Lon", 80, True),
    ("prof", "Prof (km)", 80, True),
    ("mag", "Mag", 60, True),
    ("tipo", "Tipo", 60, False),
    ("referencia", "Referencia", 280, False),
    ("percibido", "Percib.", 70, False),
    ("analista", "Analista probable", 170, False),
]

# Columnas del árbol de llegadas: (clave, título, ancho).
COLUMNAS_FASE = [
    ("fase", "Fase", 50),
    ("llegada", "Llegada", 165),
    ("loc", "Loc", 40),
    ("cha", "Cha", 55),
    ("residual", "Resid (s)", 90),
    ("azimut", "Azimut", 80),
    ("distancia", "Dist (°)", 90),
    ("usada", "Usada", 60),
    ("modo", "Modo", 70),
    ("pick_autor", "Autor pick", 150),
    ("pick_metodo", "Método", 70),
    ("pick_agencia", "Agencia", 70),
    ("peso", "Peso", 70),
    ("amplitud", "Amplitud", 90),
    ("snr", "SNR", 70),
    ("mag", "Mag", 70),
    ("tipo", "Tipo", 55),
    ("residuo", "Residuo", 85),
    ("qc", "QC", 95),
    ("lugar", "Lugar", 200),
    ("elev", "Elev (m)", 85),
]

# Columnas de las estaciones SIN ARRIBOS asociados: (clave, título, ancho). Es
# la solapa complementaria de la de llegadas, y va ordenada por distancia porque
# lo que se busca es lo que quedó cerca. loc_ref/cha_ref son el stream de
# REFERENCIA (no el único) y streams_vigentes dice cuántos había.
COLUMNAS_NO_PICADA = [
    ("distancia_km", "Dist (km)", 90),
    ("red", "Red", 70),
    ("estacion", "Estación", 100),
    ("loc_ref", "Loc ref.", 65),
    ("cha_ref", "Canal ref.", 75),
    ("streams_vigentes", "Streams vig.", 80),
    ("actividad_ventana", "Actividad ±24 h", 130),
    ("est_elev", "Elev (m)", 85),
    ("est_lugar", "Lugar", 210),
    ("est_pais", "País", 110),
]

# Distancia a la que una estación sin arribos se considera "cerca" y se resalta.
# Es un segundo umbral, más chico que el radio con el que se exportó, y no
# pisa ese radio: el archivo trae todo lo que entró en el radio y esto solo
# decide qué se ve de entrada. Con el radio en 300 km y esto en 50, la lista
# completa queda a un clic y los casos que más importan quedan arriba.
UMBRAL_CERCANO_KM = 50.0

# Si una ampliación trae más filas que esto, se pide confirmación antes de
# mostrarla. La red local tiene ~486 estaciones (~446 con stream), así que
# «Todo» por evento ronda las 400-450: 2000 no molesta en el uso normal y marca
# algo anómalo (otra red, un inventario que cambió, un error).
UMBRAL_AVISO_AMPLIADO = 2000

# Textos de ayuda de la solapa "Sin arribos". Van fijos arriba de la tabla
# además del tooltip, para que el mensaje no dependa de pasar el mouse.
AYUDA_SIN_ARRIBOS = (
    "Sin arribos: no hay arrivals/picks asociados al origen preferido del"
    " evento, entre las estaciones con binding (la config actual de SeisComp)."
    " No demuestra ausencia de formas de onda; para eso hay que"
    " consultar SDS/DataAvailability.")
# Se muestra como línea fija arriba de la tabla Y como tooltip. Es lo más
# explícito posible a propósito: la ventana de ±24 h (24 h antes y 24 h después
# del origen) es lo que más se presta a confusión.
AYUDA_ACTIVIDAD = (
    "Actividad inferida: cuenta otros eventos con picks de esa estación dentro"
    " de ±24 h del origen, es decir 24 h antes y 24 h después. Es un indicador"
    " indirecto; 0 no implica inactividad ni ausencia de formas de onda.")


def _ayuda_emergente(widget, texto):
    """
    Muestra un texto de ayuda al pasar el mouse por encima de un widget.

    Tkinter no trae tooltips y en el proyecto no había ninguno, así que va uno
    mínimo: un Toplevel sin bordes que aparece en <Enter> y se destruye en
    <Leave>. La referencia se guarda en el propio widget para que no se la lleve
    el recolector antes de tiempo.
    """
    import tkinter as tk

    def _mostrar(_evento=None):
        try:
            x = widget.winfo_rootx() + 20
            y = widget.winfo_rooty() + widget.winfo_height() + 4
        except Exception:
            return
        try:
            emergente = tk.Toplevel(widget)
            emergente.wm_overrideredirect(True)
            emergente.wm_geometry("+%d+%d" % (x, y))
            tk.Label(emergente, text=texto, justify="left",
                     background="#ffffe1", relief="solid", borderwidth=1,
                     padx=6, pady=3, wraplength=380).pack()
        except Exception:
            return
        widget._ayuda = emergente

    def _ocultar(_evento=None):
        emergente = getattr(widget, "_ayuda", None)
        if emergente is not None:
            try:
                emergente.destroy()
            except Exception:
                pass
            widget._ayuda = None

    widget.bind("<Enter>", _mostrar, add="+")
    widget.bind("<Leave>", _ocultar, add="+")

# Grupos del panel de detalle: (título, [columnas del evento]).
DETALLE_GRUPOS = [
    ("Identificación", ["id_evento", "id_origen", "base_datos"]),
    ("Ubicación", ["latitud", "longitud", "profundidad_km", "region"]),
    ("Solución", ["ot_utc", "magnitud", "tipo_magnitud", "fases", "rms",
                  "azgap"]),
    ("Control", ["agencia", "operador", "estatus"]),
]


# ---------------------------------------------------------------------------
# Lógica pura: se puede probar sin pantalla
# ---------------------------------------------------------------------------
def _leer_csv(ruta):
    """Lee un CSV y devuelve la lista de filas como diccionarios."""
    with open(ruta, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _leer_catalogo(ruta):
    """
    Lee un catálogo crudo: el de Seisan, el select, o el publicado de eventquery.

    utf-8-sig porque estos archivos vienen de exportaciones que pueden llevar
    BOM, y sin eso la primera columna del encabezado queda con un carácter
    invisible pegado y deja de coincidir con nada.
    """
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _partir_fecha_hora(texto):
    """
    Parte el instante de un CSV en (fecha, hora).

    Es el ÚNICO parser de fecha del módulo, y el panel de SeisComp usa el mismo
    que las pestañas de catálogo. Antes había dos: el panel tenía el suyo, que
    esperaba AAAAMMDDHHMMSS, un formato compacto que no usa ninguno de los tres
    CSV. Por eso la columna Hora salía vacía en las 2082 filas del export.

    Acepta 'YYYY-MM-DD HH:MM:SS' y 'YYYY-MM-DDTHH:MM:SS', que es como lo
    escriben Seisan, eventquery y SeisComp (con espacio) y el catálogo de
    referencia (con T).

    Usa split() y no posiciones fijas a propósito: el select de Seisan separa
    fecha y hora con doble espacio ("2026-09-04  06:48:08"), y con índices fijos
    la hora salía corrida. split() no le hace caso a la cantidad de espacios.
    """
    limpio = str(texto or "").strip().replace("T", " ")
    if not limpio:
        return VACIO, VACIO
    partes = limpio.split()
    if len(partes) >= 2:
        return partes[0], partes[1][:8]
    return limpio, VACIO


def _campo_tiempo(fila):
    """
    Devuelve el instante del evento, sea cual sea el nombre de su columna.

    El export crudo de SeisComp lo llama 'ot_utc' porque sus nombres siguen el
    esquema de consulta_eventosSC.py; los catálogos lo llaman 'Fecha_Hora' y el
    de referencia 'time'. Buscar el nombre en vez de fijarlo permite que el
    panel abra cualquiera de los tres, y que estandarizar el export mañana no
    obligue a venir a tocar el panel.
    """
    for clave in COLUMNAS_DE_TIEMPO:
        valor = fila.get(clave)
        if valor is not None and str(valor).strip() != "":
            return valor
    return ""


def _instante_de_evento(fila):
    """El instante del evento como datetime, o None si no se puede leer.

    Lo usa la ampliación contra la base: la consulta del inventario y la
    actividad necesitan la hora del evento como tal, no como texto.
    """
    fecha, hora = _partir_fecha_hora(_campo_tiempo(fila))
    if fecha == VACIO:
        return None
    try:
        return datetime.strptime("%s %s" % (fecha, hora), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _normalizar_catalogo(fila):
    """
    Traduce una fila de catálogo crudo a las claves que usan las pestañas.

    Los catálogos traen el encabezado con nombres propios (Fecha_Hora, Prof.,
    Mag., Tipo_mag.) y además cambian las columnas finales según de dónde
    vengan: Referencia/Percep. en el publicado, Analista en los locales. Se
    dejan todas a mano para que un cambio de encabezado en la exportación no
    rompa la lista entera: si una falta, la columna muestra el guion de vacío y
    el resto sigue ahí.
    """
    limpia = {}
    for clave, valor in fila.items():
        limpia[(clave or "").strip().lstrip("\ufeff")] = valor
    limpia["fecha"], limpia["hora"] = _partir_fecha_hora(
        limpia.get("Fecha_Hora", ""))
    limpia["latitud"] = limpia.get("Latitud", "")
    limpia["longitud"] = limpia.get("Longitud", "")
    limpia["prof"] = limpia.get("Prof.", "")
    limpia["mag"] = limpia.get("Mag.", "")
    limpia["tipo"] = limpia.get("Tipo_mag.", "")
    limpia["analista"] = limpia.get("Analista", "")
    limpia["referencia"] = limpia.get("Referencia", "")
    limpia["percibido"] = limpia.get("Percep.", "")
    return limpia


def _id_de_primera_columna(linea):
    """
    Saca el id_evento de una línea cruda del CSV de fases.

    Se lee la línea como bytes porque el índice se construye así, y el id es la
    primera columna: en un CSV solo hace falta mirar hasta la primera coma, sin
    parsear el resto. Si estuviera entre comillas se las saca, para no guardar
    un id que después no se encuentra en el archivo de eventos.
    """
    if linea.startswith(b'"'):
        fin = linea.find(b'"', 1)
        if fin > 0:
            return linea[1:fin].decode("utf-8", "replace")
    return linea.split(b",", 1)[0].decode("utf-8", "replace")


def _indexar_fases(ruta):
    """
    Recorre el CSV de fases UNA vez y anotan en qué byte empieza y termina cada
    evento, sin parsear las líneas.

    Devuelve (indice, cabecera, total). El índice es un diccionario de
    id_evento a una lista de tramos (inicio, largo) en bytes.

    Esto es lo que evita cargar el archivo entero en memoria. Con el histórico
    completo son más de 680.000 llegadas, y parsearlas todas como diccionarios
    ocuparía varios gigabytes; acá solo se retienen unos miles de entradas
    mínimas, y al elegir un evento se lee únicamente su tramo.
    """
    indice = {}
    with open(ruta, "rb") as f:
        cabecera = f.readline().decode("utf-8", "replace").rstrip("\r\n")
        campos = next(csv.reader([cabecera]), [])
        actual = None
        inicio = 0
        total = 0
        while True:
            posicion = f.tell()
            linea = f.readline()
            if not linea:
                if actual is not None:
                    indice.setdefault(actual, []).append((inicio, posicion - inicio))
                break
            total += 1
            evento = _id_de_primera_columna(linea)
            if evento != actual:
                if actual is not None:
                    indice.setdefault(actual, []).append((inicio, posicion - inicio))
                actual = evento
                inicio = posicion
    return indice, campos, total


def _leer_fases_de_evento(ruta, indice, campos, id_evento):
    """Trae solo las llegadas de un evento, leyendo su tramo del archivo."""
    tramos = indice.get(id_evento)
    if not tramos:
        return []
    filas = []
    with open(ruta, "rb") as f:
        for inicio, largo in tramos:
            f.seek(inicio)
            texto = f.read(largo).decode("utf-8", "replace")
            filas.extend(csv.DictReader(texto.splitlines(), fieldnames=campos))
    return filas


def _texto(valor):
    """Devuelve el valor limpio, o VACIO si no hay nada."""
    if valor is None:
        return VACIO
    valor = str(valor).strip()
    return valor or VACIO


def _numero(valor, decimales=None):
    """
    Formatea un número, o VACIO si no se puede.

    No se fuerza un 0 nunca: una celda sin dato tiene que seguir siendo
    reconocible como tal.
    """
    if valor is None or str(valor).strip() == "":
        return VACIO
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return _texto(valor)
    if decimales is None:
        return ("%g" % numero)
    return ("%.*f" % (decimales, numero))


def _texto_modo(valor):
    """
    Traduce el modo del pick de SeisComp a algo legible.

    En la base es 'manual' o 'automatic'; el CSV guarda ese valor crudo y acá
    se muestra en castellano. Cualquier otra cosa (incluido el vacío de una
    exportación vieja) cae en _texto, que devuelve el guion de vacío.
    """
    modo = str(valor or "").strip().lower()
    if modo == "manual":
        return "manual"
    if modo == "automatic":
        return "automática"
    return _texto(valor)


def _n_manual(n):
    """«1 manual» o «2 manuales»."""
    return "%d manual%s" % (n, "" if n == 1 else "es")


def _n_auto(n):
    """«1 automática» o «2 automáticas»."""
    return "%d automática%s" % (n, "" if n == 1 else "s")


def _conteo_modo(filas):
    """Cuenta (manuales, automáticas) en una lista de llegadas."""
    manual = sum(1 for f in filas
                 if str(f.get("modo_pick", "")).strip().lower() == "manual")
    auto = sum(1 for f in filas
               if str(f.get("modo_pick", "")).strip().lower() == "automatic")
    return manual, auto


def _desglose_uso(resumen):
    """
    Texto del resumen de usadas/sin usar, desglosado por modo si hay dato.

    Sin la columna modo (exportaciones viejas) cae al texto clásico, para no
    mostrar «0 manuales, 0 automáticas», que sería falso.
    """
    if not resumen.get("con_modo"):
        return "%d usadas, %d sin usar" % (resumen["usadas"],
                                           resumen["no_usadas"])
    partes = ["%d usadas (%s, %s)"
              % (resumen["usadas"], _n_manual(resumen["usadas_manual"]),
                 _n_auto(resumen["usadas_auto"]))]
    if resumen["no_usadas"]:
        partes.append("%d sin usar (%s, %s)"
                      % (resumen["no_usadas"],
                         _n_manual(resumen["sin_usar_manual"]),
                         _n_auto(resumen["sin_usar_auto"])))
    return ", ".join(partes)


def _agrupar_por_estacion(filas_fases):
    """
    Agrupa las llegadas por estación, ordenando lo que se muestra.

    Devuelve una lista de (clave, etiqueta, filas). La clave identifica a la
    estación y la etiqueta es lo que se escribe como fila plegable. Las
    estaciones van por red y nombre, y las llegadas dentro de cada una por
    azimut, que es como se lee una solución.
    """
    grupos = {}
    for fila in filas_fases:
        clave = (fila.get("red", ""), fila.get("estacion", ""))
        grupos.setdefault(clave, []).append(fila)

    ordenados = []
    for clave in sorted(grupos):
        filas = sorted(grupos[clave], key=lambda f: _a_float(f.get("azimut")))
        red, estacion = clave
        nombre = "%s %s" % (red, estacion) if red else estacion
        ordenados.append((clave, nombre, filas))
    return ordenados


def _a_float(valor):
    """Float o un número muy grande, para que el orden nunca se rompa."""
    try:
        return float(valor)
    except (TypeError, ValueError):
        return float("inf")


def _ruta_no_picadas(ruta_eventos):
    """Deriva el nombre del CSV de estaciones sin arribos desde el de eventos."""
    base, extension = os.path.splitext(ruta_eventos)
    return "%s_no_picadas%s" % (base, extension or ".csv")


def _valores_no_picada(fila):
    """Las columnas de una estación sin arribos asociados, ya formateadas."""
    valores = []
    for clave, _, _ in COLUMNAS_NO_PICADA:
        if clave in ("distancia_km",):
            valores.append(_numero(fila.get(clave), 1))
        elif clave in ("est_elev", "streams_vigentes"):
            valores.append(_numero(fila.get(clave), 0))
        else:
            valores.append(_texto(fila.get(clave)))
    return valores


def _etiqueta_no_picada(fila):
    """
    La etiqueta de color de una estación sin arribos asociados.

    Son cuatro, y el orden importa: lo que tiene actividad inferida Y está
    cerca va arriba porque es el caso que vale la pena mirar. La actividad es
    un indicador INDIRECTO de operación, no una prueba de que la estación
    grabara: una estación con actividad y cerca se ve distinto de una que solo
    está cerca.

    No se agrega una quinta categoría para "sin actividad": en cero la estación
    puede estar caída, no interesarle el evento o simplemente nadie la revisó,
    y ese es el caso más común; no tiene por qué verse distinto del resto.
    """
    actividad = _a_float(fila.get("actividad_ventana"))
    if actividad == float("inf"):
        actividad = 0.0
    distancia = _a_float(fila.get("distancia_km"))
    cerca = distancia != float("inf") and distancia <= UMBRAL_CERCANO_KM
    activa = actividad > 0
    if cerca and activa:
        return "destacada"
    if activa:
        return "activa"
    if cerca:
        return "cercana"
    return "normal"


def _resumen_fases(filas_fases):
    """Cuentos de las llegadas de un evento, para la cabecera del detalle."""
    usadas = sum(1 for f in filas_fases
                 if str(f.get("usada", "")).strip().lower() == "true")
    con_magnitud = sum(1 for f in filas_fases
                       if str(f.get("tiene_magnitud", "")).strip() == "Si")
    con_residuo = sum(1 for f in filas_fases
                      if str(f.get("mag_est_residuo", "")).strip() != "")
    estaciones = len({(f.get("red", ""), f.get("estacion", ""))
                      for f in filas_fases})
    magnitudes = [_a_float(f.get("mag_estacion")) for f in filas_fases
                  if str(f.get("tiene_magnitud", "")).strip() == "Si"]
    magnitudes = [m for m in magnitudes if m != float("inf")]
    # Procedencia del pick, separando las que entraron a la solución de las que
    # no. 'con_modo' dice si el archivo trae el dato: en una exportación vieja
    # la columna no existe y no hay que inventar un desglose.
    usadas_filas = [f for f in filas_fases
                    if str(f.get("usada", "")).strip().lower() == "true"]
    sin_usar_filas = [f for f in filas_fases
                      if str(f.get("usada", "")).strip().lower() != "true"]
    usadas_manual, usadas_auto = _conteo_modo(usadas_filas)
    sin_usar_manual, sin_usar_auto = _conteo_modo(sin_usar_filas)
    con_modo = sum(1 for f in filas_fases
                   if str(f.get("modo_pick", "")).strip() != "")
    return {
        "fases": len(filas_fases),
        "estaciones": estaciones,
        "usadas": usadas,
        "no_usadas": len(filas_fases) - usadas,
        "usadas_manual": usadas_manual,
        "usadas_auto": usadas_auto,
        "sin_usar_manual": sin_usar_manual,
        "sin_usar_auto": sin_usar_auto,
        "con_modo": con_modo,
        "con_magnitud": con_magnitud,
        "sin_magnitud": len(filas_fases) - con_magnitud,
        "con_residuo": con_residuo,
        "mag_promedio": (sum(magnitudes) / len(magnitudes)
                         if magnitudes else None),
    }


def _encabezado_estacion(nombre, filas):
    """Texto de la fila plegable de una estación, con su resumen."""
    usadas = sum(1 for f in filas
                 if str(f.get("usada", "")).strip().lower() == "true")
    magnitud = _texto(next((f.get("mag_estacion") for f in filas
                            if str(f.get("tiene_magnitud", "")).strip() == "Si"),
                           ""))
    tipo = _texto(next((f.get("tipo_mag_estacion") for f in filas
                        if str(f.get("tiene_magnitud", "")).strip() == "Si"), ""))
    partes = ["%d llegada%s" % (len(filas), "" if len(filas) == 1 else "s")]
    con_modo = any(str(f.get("modo_pick", "")).strip() for f in filas)
    if con_modo:
        # Desglose completo de usadas y sin usar por modo; es lo que permite ver
        # de un vistazo si la solución de esta estación se apoyó en un pick
        # manual. Se muestra solo si hay dato de modo (si no, es exportación
        # vieja y va el texto clásico).
        usadas_filas = [f for f in filas
                        if str(f.get("usada", "")).strip().lower() == "true"]
        sin_usar = len(filas) - usadas
        manual_u, auto_u = _conteo_modo(usadas_filas)
        manual_s, auto_s = _conteo_modo([f for f in filas
                                         if str(f.get("usada", "")
                                                ).strip().lower() != "true"])
        partes.append("usadas %d (%s, %s)" % (usadas, _n_manual(manual_u),
                                              _n_auto(auto_u)))
        if sin_usar:
            partes.append("sin usar %d (%s, %s)"
                          % (sin_usar, _n_manual(manual_s), _n_auto(auto_s)))
    elif len(filas) > usadas:
        partes.append("%d sin usar" % (len(filas) - usadas))
    if magnitud != VACIO:
        partes.append(("mag %s %s" % (_numero(magnitud, 1), tipo)).strip())
    return "%s   (%s)" % (nombre, ", ".join(partes))


def _valores_fase(fila):
    """Los valores de una llegada, en el orden de COLUMNAS_FASE."""
    llegada = _texto(fila.get("llegada_utc"))
    micro = str(fila.get("llegada_us", "")).strip()
    # Los microsegundos van en su propia columna del CSV, y el arrival_utc no
    # trae decimales, así que hay que pegarlos a mano.
    if micro and "." not in llegada:
        llegada = "%s.%s" % (llegada, micro)
    return [
        _texto(fila.get("fase")),
        llegada,
        _texto(fila.get("loc")),
        _texto(fila.get("cha")),
        _numero(fila.get("residual_s"), 3),
        _numero(fila.get("azimut"), 1),
        _numero(fila.get("distancia"), 2),
        "sí" if str(fila.get("usada", "")).strip().lower() == "true" else "no",
        _texto_modo(fila.get("modo_pick")),
        _texto(fila.get("pick_autor")),
        _texto(fila.get("pick_metodo")),
        _texto(fila.get("pick_agencia")),
        _numero(fila.get("peso"), 2),
        _numero(fila.get("amplitud"), 5),
        _numero(fila.get("snr"), 1),
        _numero(fila.get("mag_estacion"), 1),
        _texto(fila.get("tipo_mag_estacion")),
        _numero(fila.get("mag_est_residuo"), 3),
        _texto(fila.get("qc_estacion")),
        _texto(fila.get("est_lugar")),
        _numero(fila.get("est_elev"), 0),
    ]


def _valores_fase_con_estacion(fila):
    """
    Una llegada con su estación al frente, para la descarga.

    El árbol de llegadas agrupa por estación y la muestra en la columna de
    texto; en un archivo plano esa estación hay que llevarla como columna, o
    las llegadas quedan sueltas sin ninguna referencia de dónde son.
    """
    red = str(fila.get("red", "")).strip()
    estacion = str(fila.get("estacion", "")).strip()
    nombre = "%s %s" % (red, estacion) if red else estacion
    return [nombre or VACIO] + _valores_fase(fila)


def _valores_evento(fila):
    """Los valores de un evento, en el orden de COLUMNAS_EVENTO."""
    fecha, hora = _partir_fecha_hora(_campo_tiempo(fila))
    return [
        fecha,
        hora,
        _texto(fila.get("id_evento")),
        _numero(fila.get("magnitud"), 1),
        _texto(fila.get("tipo_magnitud")),
        _numero(fila.get("profundidad_km"), 1),
        _numero(fila.get("latitud"), DECIMALES_COORD),
        _numero(fila.get("longitud"), DECIMALES_COORD),
        _texto(fila.get("region")),
        _texto(fila.get("fases")),
        _texto(fila.get("operador")),
        _texto(fila.get("estatus")),
        _texto(fila.get("base_datos")),
    ]


def _tiene_dato(fila, columna):
    """Si la columna tiene un valor usable en esa fila."""
    if columna in COLUMNA_NUMERICA:
        return str(fila.get(COLUMNA_NUMERICA[columna], "")).strip() != ""
    if columna in ("fecha", "hora"):
        return str(_campo_tiempo(fila)).strip() != ""
    return str(fila.get(columna, "")).strip() != ""


def _ordenar_eventos(eventos, columna, descendente=False):
    """
    Ordena por una columna del árbol, dejando lo que no tiene dato al final.

    Va en dos grupos a propósito: si se ordenara con un solo key, al invertir el
    sentido los eventos sin magnitud quedarían PRIMERO, que es lo contrario de
    lo que uno espera al pedir el orden inverso.
    """
    if columna is None:
        return list(eventos)
    con_dato = [f for f in eventos if _tiene_dato(f, columna)]
    sin_dato = [f for f in eventos if not _tiene_dato(f, columna)]
    con_dato.sort(key=lambda f: _clave_orden(f, columna), reverse=descendente)
    return con_dato + sin_dato


def _clave_orden(fila, columna):
    """
    Clave para ordenar un evento por una columna del árbol.

    Las columnas numéricas ordenan por número, no por el texto que se muestra:
    ordenar "10.0" antes que "3.5" porque se comparan como cadenas sería un
    error que se ve enseguida con un solo evento de magnitud 10. Lo que no tiene
    dato va siempre al final, en cualquier sentido de orden.

    Devuelve una tupla (grupo, valor) para que todos los tipos sean comparables
    entre sí dentro de la misma columna.
    """
    if columna in COLUMNA_NUMERICA:
        try:
            return (0, float(fila.get(COLUMNA_NUMERICA[columna], "")))
        except (TypeError, ValueError):
            return (1, 0.0)
    if columna in ("fecha", "hora"):
        # El instante viene en un solo campo, en ISO ('AAAA-MM-DD HH:MM:SS'), y
        # ordenando por el texto se ordena cronológicamente igual que con un
        # datetime, porque el formato tiene los campos en orden de magnitud.
        return (0, str(_campo_tiempo(fila)))
    return (0, str(fila.get(columna, "")).strip().lower())


def _texto_filtrable(valores):
    """
    Junta los valores mostrados de una fila en una sola cadena buscable.

    Se arma con lo que se ve en pantalla, no con las claves del diccionario, por
    dos razones. Primero, porque las claves de la fila no coinciden con las de
    las columnas: "Id evento" es id_evento en el CSV, "fecha" y "hora" salen de
    ot_utc, "mag" es magnitud. Segundo, y más importante, porque así el filtro
    no puede dejar de buscar en una columna que está a la vista: si el filtro
    busca exactamente lo que se muestra, agregar una columna al árbol la agrega
    al filtro sin tocar el filtro.

    VACIO se descarta: si no, escribir el guion de "sin dato" devolvería todos
    los eventos a los que les falta ese campo.
    """
    partes = []
    for valor in valores:
        texto = str(valor).strip()
        if texto and texto != VACIO:
            partes.append(texto)
    return " ".join(partes).lower()


# Campos que la caja de texto busca aunque no se vean en el árbol. Selstos se
# agregan a los valores mostrados: son datos que el operador tiene a mano al
# revisar y que salen del mismo CSV, así que dejarlo fuera del buscador sería
# esconder información.VACIO se descarta igual que en el texto mostrado.
CAMPOS_BUSQUEDA_EVENTO = (
    "latitud", "longitud", "rms", "azgap", "agencia", "profundidad_km",
    "id_evento", "tipo_magnitud", "base_datos", "magnitud",
)


def _banda_numero(valor_crudo, token):
    """
    ¿Este valor cae en la banda que pide el token?

    Sin decimales el token es un GRADO: -26 trae todo lo que va de -26.000 a
    -26.999. Se trunca hacia cero y no se usa floor a propósito, porque las
    latitudes no tienen ceros fijos: floor(-25.74) es -26 y metería en la banda
    de -26 un evento que en realidad es de -25. int() va hacia cero, así que
    -25.74 da -25 y queda afuera, y -26.999 da -26 y entra.

    Con decimales el token es un PUNTO: -26.156 trae solo lo que está en -26.156.

    En los dos casos se compara al redondeo con el que se muestra el valor, no
    contra el crudo. El CSV guarda la coordenada con toda su precisión
    (-26.155641555786133) pero en pantalla se ve -26.156, y lo que el operador
    escribe es lo que ve. Comparar el float crudo contra el float escrito daría
    cero resultados para todos los puntos con decimales.
    """
    try:
        objetivo = float(str(token).strip())
        valor = float(str(valor_crudo).strip())
    except (TypeError, ValueError):
        return False
    limpio = str(token).strip()
    if "." in limpio or "e" in limpio.lower():
        # Con decimales el token es un PUNTO. Se compara al redondeo que se
        # muestra, no con igualdad exacta de float: el CSV guarda la coordenada
        # con toda su precisión (-26.155641555786133) pero en pantalla y en el
        # CSV exportado se ve -26.156, así que escribir -26.156 tiene que
        # encontrarlo. Comparar float contra float daría 0 resultados.
        if "e" in limpio.lower():
            return valor == objetivo
        decimales = len(limpio.split(".")[1])
        return round(valor, decimales) == objetivo
    # Sin decimales, el token es un GRADO. Se redondea al mismo paso que se
    # muestra antes de truncar, para que la banda y la columna no se
    # contradigan: un -25.9996 se ve -26.000 y tiene que entrar en la banda
    # de -26.
    return int(round(valor, DECIMALES_COORD)) == int(objetivo)


def _filtrar_listado(filas, valores, texto="", mag_min=None, clave_mag="mag",
                     lat=None, lon=None, clave_lat="latitud",
                     clave_lon="longitud", extra=()):
    """
    Filtra la lista de eventos por lo que se está mostrando.

    `valores` es la función que arma cada fila del árbol (_valores_evento en el
    panel, _valores en los catálogos), así que el texto busca en todas las
    columnas visibles, no en una lista escrita a mano. Eso es lo que antes
    dejaba pestañas distintas: SeisComp solo buscaba en id, región y operador,
    de modo que escribir una fecha vaciaba la lista, y los catálogos pedían
    id_evento y region, dos claves que no existen en su diccionario y por lo
    tanto no filtraban nada.

    `extra` suma claves crudas que no son columnas del árbol (rms, azgap,
    agencia), para que escribir "1.2" encuentre también el azgap de 1.2 y no
    solo el rms. Van aparte de `valores` porque no son columnas: si se metieran
    dentro, aparecerían en el árbol y en el CSV.

    La caja de texto es texto puro: no intenta interpretar números. Las
    coordenadas y la magnitud tienen campos propios (lat, lon, mag_min), y dejar
    que un "3" en la caja significara "magnitud 3.x" hacía que no encontrara un
    id o una referencia que tuviera un 3 adentro.

    El mínimo de magnitud sí usa la clave cruda: comparar números sobre el
    texto ya formateado no es fiabile, y '—' no es un número. El valor por
    defecto es 'mag' (los catálogos) y el panel pasa 'magnitud'. Se mantiene la
    regla de descartar los eventos sin magnitud: un evento al que la estación no
    le calculó magnitud no es 'menor que 2', es otra cosa, y mezclar las dos
    comparaciones da resultados raros.
    """
    texto = (texto or "").strip().lower()
    lat = (lat or "").strip()
    lon = (lon or "").strip()
    elegidos = []
    for fila in filas:
        if mag_min is not None:
            valor = str(fila.get(clave_mag, "")).strip()
            if not valor:
                continue
            try:
                if float(valor) < float(mag_min):
                    continue
            except ValueError:
                continue
        if lat and not _banda_numero(fila.get(clave_lat, ""), lat):
            continue
        if lon and not _banda_numero(fila.get(clave_lon, ""), lon):
            continue
        if texto:
            heno = _texto_filtrable(valores(fila))
            if texto not in heno:
                for clave in extra:
                    valor = str(fila.get(clave, "")).strip()
                    if valor and valor != VACIO and texto in valor.lower():
                        break
                else:
                    continue
        elegidos.append(fila)
    return elegidos


# ---------------------------------------------------------------------------
# Interfaz
# ---------------------------------------------------------------------------
# Los listados que se descargan van a descargas/, no a listados/. La carpeta se
# llama así porque lo que sale por acá lo elige el usuario y no se relee nunca:
# el análisis no lo usa para nada, así que se puede vaciar sin romper la
# reapertura de la app.
CARPETA_LISTADOS = rutas.DIR_DESCARGAS


def _exportar_listado(filas, valores, columnas, cwd, etiqueta,
                      padre=None, formato=None):
    """
    Descarga a descargas/ las filas que se están mostrando, con o sin filtro.

    Va lo que se ve, con los valores ya formateados: el guion de "sin dato", las
    coordenadas con tres decimales y la profundidad y las magnitudes con uno. Es
    lo que se pidió y lo que uno espera al abrir el archivo: el mismo contenido
    de la pantalla.

    El formato (CSV o TXT tabulado) lo pregunta descargas.py. Se puede forzar
    pasando 'formato', que es lo que usan los caminos sin interfaz.

    Devuelve la ruta escrita, o None si no había filas o si se canceló la
    pregunta de formato. No escribe un archivo vacío: un CSV con solo
    encabezados parece un catálogo que no tiene eventos.
    """
    if not filas:
        return None
    if formato is None:
        formato = descargas.preguntar_formato(padre)
        if formato is None:
            return None
    titulos = [titulo for _, titulo, *_ in columnas]
    return descargas.exportar_tabla(titulos, [valores(fila) for fila in filas],
                                    etiqueta, cwd=cwd, formato=formato)


def _construir_detalle(ttk, marco, evento, filas_fases, etiqueta_fuente,
                       sin_fases=False, al_estaciones=None):
    """
    Arma el panel de datos del evento y el resumen de sus llegadas.

    Esto se muestra en la ventana emergente que abre _ventana_detalle al hacer
    clic en una fila, no embebido en el panel: ahí compartía el ancho con la
    lista de eventos y abajo se cortaba, justo donde va el botón «Estaciones».
    El árbol de llegadas tampoco va acá: vive en su propia ventana, a la que se
    entra con ese botón.

    'al_estaciones' es el callback del botón. Va como parámetro y no se arma
    siempre porque el mismo panel se usa para fuentes sin llegadas, donde el
    botón no tiene sentido.
    """
    import ttkbootstrap as _t
    for hijo in marco.winfo_children():
        hijo.destroy()

    titulo = _t.Frame(marco)
    titulo.pack(fill="x", pady=(0, 6))
    _t.Label(titulo, text=_texto(evento.get("id_evento")),
             font=("", 12, "bold")).pack(side="left")
    if al_estaciones is not None:
        _t.Button(titulo, text="Estaciones", bootstyle="primary-outline",
                  command=al_estaciones).pack(side="left", padx=(10, 0))
    if etiqueta_fuente:
        _t.Label(titulo, text=etiqueta_fuente, bootstyle="secondary"
                 ).pack(side="right")

    if sin_fases:
        # Decir "0 llegadas de 0 estaciones" sería falso: la fuente no trae
        # llegadas, no es que el evento no tenga. Se aclara para que nadie
        # interprete el vacío como un problema del evento.
        _t.Label(marco, text="Esta fuente no trae detalle de llegadas.",
                 bootstyle="secondary").pack(anchor="w", pady=(0, 8))
    else:
        resumen = _resumen_fases(filas_fases)
        partes = ["%d llegadas de %d estaciones" % (resumen["fases"],
                                                    resumen["estaciones"])]
        partes.append(_desglose_uso(resumen))
        partes.append("%d con magnitud de estación" % resumen["con_magnitud"])
        if resumen["mag_promedio"] is not None:
            partes.append("magnitud media de estación %.1f"
                          % resumen["mag_promedio"])
        _t.Label(marco, text="  |  ".join(partes)).pack(anchor="w",
                                                        pady=(0, 8))

    # Datos del evento, agrupados por tema.
    cajas = _t.Frame(marco)
    cajas.pack(fill="x")
    for indice, (titulo_grupo, claves) in enumerate(DETALLE_GRUPOS):
        caja = _t.Labelframe(cajas, text=titulo_grupo, padding=(6, 4))
        caja.grid(row=indice // 2, column=indice % 2, sticky="nsew", padx=4,
                  pady=4)
        for fila, clave in enumerate(claves):
            _t.Label(caja, text=clave.replace("_", " ") + ":",
                     bootstyle="secondary").grid(row=fila, column=0,
                                                 sticky="w")
            valor = evento.get(clave, "")
            if clave in ("ot_utc",):
                fecha, hora = _partir_fecha_hora(_campo_tiempo(evento))
                valor = "%s %s" % (fecha, hora) if fecha != VACIO else VACIO
            elif clave in ("latitud", "longitud"):
                valor = _numero(valor, DECIMALES_COORD)
            elif clave in ("profundidad_km", "rms", "azgap", "fases",
                           "magnitud"):
                valor = _numero(valor, 1) if clave != "fases" else _numero(valor)
            else:
                valor = _texto(valor)
            _t.Label(caja, text=valor).grid(row=fila, column=1, sticky="w",
                                            padx=(6, 0))
    cajas.columnconfigure(0, weight=1)
    cajas.columnconfigure(1, weight=1)


def _construir_arbol_fases(ttk, marco, filas_fases, padre=None, cwd=None,
                           etiqueta=None, log=None):
    """
    Arma el árbol de llegadas, agrupado y plegable por estación.

    Con padre/cwd/etiqueta agrega abajo el botón de descarga: el árbol se ve
    siempre en crudo, y revisar llegadas es justamente el trabajo para el que
    uno necesita la tabla completa afuera.
    """
    import ttkbootstrap as _t
    for hijo in marco.winfo_children():
        hijo.destroy()

    if not filas_fases:
        _t.Label(marco, text="Este evento no tiene llegadas registradas.",
                 font=("", 10, "bold")).pack(anchor="w", padx=6, pady=10)
        return None

    claves = [c for c, _, _ in COLUMNAS_FASE]
    titulos = ["Estación / llegada"] + [t for _, t, _ in COLUMNAS_FASE]
    anchos = [230] + [a for _, _, a in COLUMNAS_FASE]
    marco_tabla = _t.Frame(marco)
    marco_tabla.pack(fill="both", expand=True)

    arbol = _t.Treeview(marco_tabla, columns=claves, show="tree headings",
                        selectmode="browse")
    arbol.heading("#0", text=titulos[0])
    arbol.column("#0", width=anchos[0], minwidth=150, stretch=False)
    for indice, clave in enumerate(claves):
        arbol.heading(clave, text=titulos[indice + 1])
        arbol.column(clave, width=anchos[indice + 1], minwidth=45,
                     stretch=False)
    barra = _t.Scrollbar(marco_tabla, orient="vertical", command=arbol.yview)
    arbol.configure(yscrollcommand=barra.set)
    arbol.pack(side="left", fill="both", expand=True)
    barra.pack(side="right", fill="y")
    # La tabla de llegadas tiene 15 columnas y es más ancha que el detalle, así
    # que también necesita poder desplazarse de lado.
    barra_h = _t.Scrollbar(marco_tabla, orient="horizontal", command=arbol.xview)
    arbol.configure(xscrollcommand=barra_h.set)
    barra_h.pack(side="bottom", fill="x")

    # Resaltado de los picks manuales: el que entró a la solución va fuerte,
    # el que quedó afuera va suave. Los colores salen del tema para que no
    # queden texto claro sobre fondo claro con un tema oscuro.
    try:
        from ttkbootstrap.style import Style
        oscuro = bool(Style.get_instance().colors.dark)
    except Exception:
        oscuro = False
    arbol.tag_configure("manual_usada",
                        foreground="#c0392b" if not oscuro else "#ff8a80",
                        font=("", 9, "bold"))
    arbol.tag_configure("manual_sin_usar",
                        foreground="#b9770e" if not oscuro else "#f0c674")

    for clave, nombre, filas in _agrupar_por_estacion(filas_fases):
        nodo = arbol.insert("", "end", text=_encabezado_estacion(nombre, filas),
                            open=False, tags=("estacion",))
        for fila in filas:
            valores = _valores_fase(fila)
            etiquetas = ["fase"]
            if str(fila.get("modo_pick", "")).strip().lower() == "manual":
                usada = str(fila.get("usada", "")).strip().lower() == "true"
                etiquetas.append("manual_usada" if usada
                                 else "manual_sin_usar")
            arbol.insert(nodo, "end", values=valores,
                         text="   %s %s %s" % (fila.get("fase", ""),
                                               fila.get("loc", ""),
                                               fila.get("cha", "")),
                         tags=tuple(etiquetas))

    if padre is not None and cwd is not None:
        # El botón se arma aparte, no dentro del bloque de la tabla, para que
        # quede debajo del árbol y no compita con el ancho de las 15 columnas.
        def _al_descargar_fases():
            # Se usan las filas completas del evento, no las que se ven: el
            # árbol se arma plegado por estación, así que "lo que se ve" serían
            # solo los encabezados de las estaciones cerradas.
            ruta = _exportar_listado(
                filas_fases, _valores_fase_con_estacion,
                [("estacion", "Estación", 160)] + list(COLUMNAS_FASE),
                cwd, "llegadas_%s" % (etiqueta or "seiscomp"), padre=padre)
            if ruta is None:
                return
            aviso = "Descargadas %d llegadas a %s" % (len(filas_fases),
                                                       os.path.basename(ruta))
            if log:
                log(aviso)
            etiqueta_estado.config(text=aviso)

        marco_botones = _t.Frame(marco)
        marco_botones.pack(anchor="w", padx=4, pady=(4, 0))
        etiqueta_estado = _t.Label(marco_botones, text="%d llegadas."
                                   % len(filas_fases))
        etiqueta_estado.pack(side="left", padx=(0, 8))
        _t.Button(marco_botones, text="Descargar llegadas",
                  bootstyle="secondary-outline",
                  command=_al_descargar_fases).pack(side="right")
    return arbol


def _tabla_sin_arribos(ttk, marco, filas, padre=None, cwd=None, etiqueta=None,
                       log=None):
    """
    Dibuja la tabla de estaciones sin arribos (y su descarga) para una lista.

    Está separada de _construir_arbol_no_picadas para poder repintarla al
    filtrar por radio o al mostrar el resultado ampliado contra la base: la
    tabla, la descarga y los resaltados son siempre los mismos; lo único que
    cambia es la lista de filas.
    """
    import ttkbootstrap as _t
    for hijo in marco.winfo_children():
        hijo.destroy()

    # Colores de la paleta de ttkbootstrap (no fijos) para que con otro tema no
    # queden texto claro sobre fondo claro. La paleta es una clase con atributos
    # (colors.bg, no colors["bg"]) y .dark dice si el tema es oscuro.
    try:
        from ttkbootstrap.style import Style
        paleta = Style.get_instance().colors
        oscuro = bool(paleta.dark)
    except Exception:
        oscuro = False
    fondo = "#1f2b34" if oscuro else "#fff4d6"
    texto_color = "#f2f2f2" if oscuro else "#7a4b00"
    color_activa = "#5fd08a" if oscuro else "#1a7f37"

    if not filas:
        _t.Label(marco, text="Ninguna estación dentro del radio elegido.",
                 font=("", 10, "bold")).pack(anchor="w", padx=8, pady=10)
        return None, None

    # Leyenda de 2 líneas: la primera explica qué mide la actividad; la segunda,
    # los colores de las filas, con los mismos que usa tag_configure más abajo.
    _t.Label(marco, text=AYUDA_ACTIVIDAD, bootstyle="secondary",
             justify="left", wraplength=900).pack(anchor="w", padx=8,
                                                  pady=(4, 2))
    leyenda = _t.Frame(marco)
    leyenda.pack(anchor="w", padx=8, pady=(0, 4))
    _t.Label(leyenda, text="Colores:", bootstyle="secondary").pack(side="left")
    _t.Label(leyenda, text=" Activa y ≤ %g km " % UMBRAL_CERCANO_KM,
             background=fondo, foreground=texto_color,
             font=("", 9, "bold")).pack(side="left", padx=(6, 4))
    _t.Label(leyenda, text=" Activa (picks ±24 h) ", foreground=color_activa,
             font=("", 9)).pack(side="left", padx=4)
    _t.Label(leyenda, text=" ≤ %g km " % UMBRAL_CERCANO_KM,
             font=("", 9, "bold")).pack(side="left", padx=4)
    _t.Label(leyenda, text=" Resto ", font=("", 9)).pack(side="left", padx=4)

    claves = [c for c, _, _ in COLUMNAS_NO_PICADA]
    titulos = [titulo for _, titulo, _ in COLUMNAS_NO_PICADA]
    anchos = [ancho for _, _, ancho in COLUMNAS_NO_PICADA]
    marco_tabla = _t.Frame(marco)
    marco_tabla.pack(fill="both", expand=True)

    arbol = _t.Treeview(marco_tabla, columns=claves, show="headings",
                        selectmode="browse")
    for indice, clave in enumerate(claves):
        arbol.heading(clave, text=titulos[indice])
        arbol.column(clave, width=anchos[indice], minwidth=60, stretch=False)
    barra = _t.Scrollbar(marco_tabla, orient="vertical", command=arbol.yview)
    arbol.configure(yscrollcommand=barra.set)
    arbol.pack(side="left", fill="both", expand=True)
    barra.pack(side="right", fill="y")
    barra_h = _t.Scrollbar(marco_tabla, orient="horizontal",
                           command=arbol.xview)
    arbol.configure(xscrollcommand=barra_h.set)
    barra_h.pack(side="bottom", fill="x")
    _ayuda_emergente(arbol, AYUDA_ACTIVIDAD)

    # Los colores ya se calcularon arriba (leyenda); acá se aplican los tags.
    arbol.tag_configure("destacada", background=fondo, foreground=texto_color,
                        font=("", 9, "bold"))
    arbol.tag_configure("activa", foreground=color_activa)
    arbol.tag_configure("cercana", font=("", 9, "bold"))

    for fila in sorted(filas,
                       key=lambda f: (_a_float(f.get("distancia_km")),
                                      f.get("red", ""), f.get("estacion", ""))):
        arbol.insert("", "end", values=_valores_no_picada(fila),
                     tags=(_etiqueta_no_picada(fila),))

    etiqueta_estado = None
    if padre is not None and cwd is not None:
        def _al_descargar_no_picadas():
            ruta = _exportar_listado(
                filas, _valores_no_picada, COLUMNAS_NO_PICADA, cwd,
                "no_picadas_%s" % (etiqueta or "seiscomp"), padre=padre)
            if ruta is None:
                return
            aviso = "Descargadas %d estaciones a %s" % (
                len(filas), os.path.basename(ruta))
            if log:
                log(aviso)
            if etiqueta_estado is not None:
                etiqueta_estado.config(text=aviso)

        marco_botones = _t.Frame(marco)
        marco_botones.pack(anchor="w", padx=4, pady=(4, 0))
        activas = sum(1 for f in filas
                      if _etiqueta_no_picada(f) in ("activa", "destacada"))
        etiqueta_estado = _t.Label(
            marco_botones,
            text="%d estaciones, %d con actividad inferida."
            % (len(filas), activas))
        etiqueta_estado.pack(side="left", padx=(0, 8))
        _t.Button(marco_botones, text="Descargar sin arribos",
                  bootstyle="secondary-outline",
                  command=_al_descargar_no_picadas).pack(side="right")
    return arbol, etiqueta_estado


def _radio_exportado(filas):
    """El radio con el que se exportó la lista, leído de las filas."""
    for fila in filas:
        valor = _a_float(fila.get("radio_km"))
        if valor != float("inf"):
            return valor
    return None


def _construir_arbol_no_picadas(ttk, marco, filas_no_picadas, padre=None,
                                cwd=None, etiqueta=None, log=None,
                                hay_archivo=True):
    """
    Arma el contenido de la solapa de estaciones sin arribos: ayuda y tabla.

    Devuelve el contenedor donde quedó la tabla (o None si no hay tabla), para
    que el encabezado de la ventana pueda repintarla al filtrar por radio. El
    control de radio y el botón «Ampliar» NO van acá: viven en el encabezado de
    la ventana, siempre visibles, porque esta solapa no es la que abre por
    defecto.

    Con 'hay_archivo=False' no es que no haya estaciones: es que el CSV no está,
    que es lo que pasa con una exportación vieja. El texto lo dice, porque un
    árbol vacío ahí se lee como "no había ninguna estación cerca" y sería falso.
    """
    import ttkbootstrap as _t
    for hijo in marco.winfo_children():
        hijo.destroy()

    if not hay_archivo:
        _t.Label(marco, text="Esta exportación no tiene el archivo de"
                 " estaciones sin arribos asociados.\nVolvé a exportar la"
                 " ventana: el archivo se llama igual que los otros, con"
                 " _no_picadas antes del .csv.",
                 bootstyle="secondary", justify="left").pack(anchor="w",
                                                             padx=8, pady=10)
        return None

    # Ayuda fija, siempre visible: el tooltip es cómodo pero no puede ser la
    # única forma de enterarse de que "sin arribos" no significa "no grabó".
    _t.Label(marco, text=AYUDA_SIN_ARRIBOS, bootstyle="secondary",
             justify="left", wraplength=900).pack(anchor="w", padx=8,
                                                  pady=(4, 0))
    contenedor = _t.Frame(marco)
    contenedor.pack(fill="both", expand=True)
    _tabla_sin_arribos(_t, contenedor, filas_no_picadas, padre=padre, cwd=cwd,
                       etiqueta=etiqueta, log=log)
    return contenedor


def _centrar_en_pantalla(ventana, ancho, alto):
    """
    Ubica la ventana centrada en la pantalla, acotada al área visible.

    Tk deja un Toplevel nuevo donde quiera el gestor de ventanas, y en pantallas
    anchas eso puede terminar fuera del área visible: la ventana existe, captura
    o tapa, pero no se ve. Centrarla y recortarla a la pantalla evita el caso.
    """
    try:
        pantalla_ancho = ventana.winfo_screenwidth()
        pantalla_alto = ventana.winfo_screenheight()
    except Exception:
        ventana.geometry("%dx%d" % (ancho, alto))
        return
    ancho = min(ancho, pantalla_ancho)
    alto = min(alto, pantalla_alto)
    x = max(0, (pantalla_ancho - ancho) // 2)
    y = max(0, (pantalla_alto - alto) // 2)
    ventana.geometry("%dx%d+%d+%d" % (ancho, alto, x, y))


def _ventana_detalle(padre, evento, filas_fases, etiqueta_fuente=None,
                     sin_fases=False, al_estaciones=None, ventana_previa=None):
    """
    Abre (o reusa) la ventana con los parámetros del evento.

    El detalle ya no vive embebido en el panel: compartía el ancho con la lista
    y abajo se cortaba justo donde está el botón «Estaciones». Acá entra
    completo y el panel queda solo para la lista, a todo el ancho.

    Es una ventana de consulta, no un diálogo: va sin grab, para que se pueda
    seguir navegando la lista de eventos con la ventana abierta.

    Se reusa la ventana que ya está abierta al cambiar de evento, igual que
    _ventana_estaciones, para no llenar la pantalla de ventanas iguales.

    'ventana_previa' es la ventana que había, o None. Se la devuelve
    actualizada para que el panel la guarde.
    """
    import ttkbootstrap as _t
    if ventana_previa is not None and ventana_previa.winfo_exists():
        ventana = ventana_previa
    else:
        ventana = _t.Toplevel(padre)
    descargas.encima_de(padre, ventana, modal=False)

    ventana.title("Parámetros del evento %s"
                  % (_texto(evento.get("id_evento")) or ""))
    for hijo in ventana.winfo_children():
        hijo.destroy()

    _construir_detalle(_t, ventana, evento, filas_fases, etiqueta_fuente,
                       sin_fases=sin_fases, al_estaciones=al_estaciones)

    # El tamaño lo pide el contenido; se recorta a la pantalla para que en un
    # monitor chico no quede parte fuera de la vista.
    ventana.update_idletasks()
    ancho = max(560, ventana.winfo_reqwidth())
    alto = ventana.winfo_reqheight()
    try:
        maximo = ventana.wm_maxsize()
        if maximo and maximo[0] > 0:
            ancho = min(ancho, maximo[0] - 40)
            alto = min(alto, maximo[1] - 40)
    except Exception:
        pass
    _centrar_en_pantalla(ventana, ancho, alto)
    return ventana


def _ventana_estaciones(padre, evento, filas_fases, filas_no_picadas, cwd,
                        etiqueta_fuente=None, log=None, hay_no_picadas=True,
                        ventana_previa=None, al_ampliar=None):
    """
    Abre (o reusa) la ventana "Estaciones del evento", con dos solapas.

    La de "Con arribos" es el árbol de llegadas de siempre, agrupado por
    estación. La de "Sin arribos" son las estaciones con binding (config actual
    de SeisComp) que quedaron dentro del radio y no tienen arrivals/picks
    asociados al origen preferido. Juntas contestan la pregunta completa: qué
    estaciones tienen arribos según el analista, y cuáles SeisComp trabaja y no
    los tienen.

    "Sin arribos" no es "no grabó": la base de metadatos no sabe qué estaciones
    tienen formas de onda de cada evento. Por eso el encabezado y la ayuda lo
    dicen, y la actividad es un indicador indirecto.

    Se reusa la ventana que ya está abierta en vez de acumular una por evento:
    son miles de pixeles de tabla y abrirlas en cada selección llena la
    pantalla de ventanas iguales.

    'ventana_previa' es la ventana que había, o None. Se la devuelve actualizada
    para que el panel la guarde.
    """
    import ttkbootstrap as _t
    resumen = _resumen_fases(filas_fases)
    partes = ["%d picadas de %d estaciones" % (resumen["fases"],
                                               resumen["estaciones"])]
    partes.append(_desglose_uso(resumen))
    id_origen = _texto(evento.get("id_origen"))
    if id_origen:
        partes.append("origen %s" % id_origen)
    if hay_no_picadas:
        partes.append("%d sin arribos" % len(filas_no_picadas))
    else:
        partes.append("sin arribos: sin archivo")

    if ventana_previa is not None and ventana_previa.winfo_exists():
        ventana = ventana_previa
    else:
        ventana = _t.Toplevel(padre)
    # Ventana de consulta, no diálogo: sin grab, para poder seguir navegando.
    descargas.encima_de(padre, ventana, modal=False)

    ventana.title("Estaciones del evento %s"
                  % (_texto(evento.get("id_evento")) or ""))
    for hijo in ventana.winfo_children():
        hijo.destroy()

    arriba = _t.Frame(ventana)
    arriba.pack(fill="x", padx=6, pady=(6, 0))
    _t.Label(arriba, text="  |  ".join(partes),
             bootstyle="secondary").pack(side="left")
    if etiqueta_fuente:
        _t.Label(arriba, text=etiqueta_fuente,
                 bootstyle="secondary").pack(side="right")

    # Control de radio y ampliación, en el ENCABEZADO y siempre visible: antes
    # vivía dentro de la solapa "Sin arribos", que no es la que abre por defecto,
    # así que no se encontraba.
    radio_exportado = _radio_exportado(filas_no_picadas)
    control = _t.Frame(ventana)
    control.pack(fill="x", padx=8, pady=(4, 0))
    _t.Label(control, text="Radio SeisComp (km):").pack(side="left")
    ent_radio = _t.Entry(control, width=8)
    if radio_exportado is not None:
        ent_radio.insert(0, "%g" % radio_exportado)
    ent_radio.pack(side="left", padx=(4, 6))

    if not hay_no_picadas:
        _t.Label(ventana, text="Aviso: esta exportación no trae el archivo de"
                 " estaciones sin arribos asociados. Volvé a exportar la"
                 " ventana para tenerlo. La solapa de arribos funciona igual.",
                 bootstyle="warning").pack(anchor="w", padx=8, pady=(4, 0))

    cuaderno = _t.Notebook(ventana)
    cuaderno.pack(fill="both", expand=True, padx=6, pady=6)
    marco_picadas = _t.Frame(cuaderno)
    marco_no_picadas = _t.Frame(cuaderno)
    cuaderno.add(marco_picadas, text="Con arribos")
    cuaderno.add(marco_no_picadas, text="Sin arribos")

    _construir_arbol_fases(_t, marco_picadas, filas_fases, padre=ventana,
                           cwd=cwd, etiqueta=etiqueta_fuente, log=log)
    contenedor_no_picadas = _construir_arbol_no_picadas(
        _t, marco_no_picadas, filas_no_picadas, padre=ventana, cwd=cwd,
        etiqueta=etiqueta_fuente, log=log, hay_archivo=hay_no_picadas)

    estado_control = _t.Label(control, text="", bootstyle="secondary")

    def _leer_radio():
        try:
            valor = float(ent_radio.get().strip().rstrip("kKmM"))
        except ValueError:
            return None
        return valor if valor > 0 else None

    def _aplicar():
        radio = _leer_radio()
        if radio is None:
            estado_control.config(text="Radio inválido.")
            return
        filas = [f for f in filas_no_picadas
                 if _a_float(f.get("distancia_km")) <= radio]
        if contenedor_no_picadas is not None:
            _tabla_sin_arribos(_t, contenedor_no_picadas, filas, padre=ventana,
                               cwd=cwd, etiqueta=etiqueta_fuente, log=log)
        estado_control.config(text="%d de %d dentro de %g km."
                              % (len(filas), len(filas_no_picadas), radio))

    def _ampliar(todo=False):
        if al_ampliar is None:
            return
        if todo:
            radio = None
        else:
            radio = _leer_radio()
            if radio is None:
                estado_control.config(text="Radio inválido.")
                return
        estado_control.config(text="Consultando la base…")
        ventana.update_idletasks()
        boton_ampliar.configure(state="disabled")
        boton_todo.configure(state="disabled")
        try:
            cantidad = al_ampliar(radio)
            if cantidad is None:
                estado_control.config(text="Ampliación cancelada.")
            elif radio is None:
                estado_control.config(
                    text="Ampliado sin límite: %d estaciones." % cantidad)
            else:
                estado_control.config(text="Ampliado a %g km: %d estaciones."
                                      % (radio, cantidad))
        except Exception as exc:
            estado_control.config(text="No se pudo ampliar: %s" % exc)
        finally:
            boton_ampliar.configure(state="normal")
            boton_todo.configure(state="normal")

    _t.Button(control, text="Filtrar", bootstyle="secondary-outline",
              command=_aplicar).pack(side="left")
    boton_ampliar = _t.Button(control, text="Ampliar (consulta a la base)",
                              bootstyle="primary-outline",
                              command=lambda: _ampliar())
    boton_ampliar.pack(side="left", padx=(6, 0))
    boton_todo = _t.Button(control, text="Todo (sin límite)",
                           bootstyle="primary-outline",
                           command=lambda: _ampliar(todo=True))
    boton_todo.pack(side="left", padx=(6, 0))
    if al_ampliar is None:
        boton_ampliar.configure(state="disabled")
        boton_todo.configure(state="disabled")
    estado_control.pack(side="left", padx=(8, 0))
    if radio_exportado is not None:
        estado_control.config(text="Corte exportado: %g km." % radio_exportado)
    ent_radio.bind("<Return>", lambda _e: _aplicar())

    # El ancho se pide para la tabla más ancha de las dos, que es la de
    # llegadas. Se recorta al máximo de la pantalla: pedir 1700 px en un monitor
    # chico hace que las columnas queden fuera y haya que arrastrar la barra.
    ancho = 230 + sum(a for _, _, a in COLUMNAS_FASE) + 60
    otro = sum(a for _, _, a in COLUMNAS_NO_PICADA) + 60
    ancho = max(ancho, otro, 900)
    alto = min(760, max(420, ventana.winfo_screenheight() - 160))
    try:
        maximo = ventana.wm_maxsize()
        # Con Some/None el par no es comparable; se descarta.
        if maximo and maximo[0] > 0:
            ancho = min(ancho, maximo[0] - 40)
            alto = min(alto, maximo[1] - 40)
    except Exception:
        pass
    _centrar_en_pantalla(ventana, ancho, alto)
    return ventana


def _ventana_sin_arribos_ampliada(padre, evento, filas, radio, base, cwd,
                                  etiqueta_fuente=None, log=None,
                                  ventana_previa=None):
    """
    Muestra, en una ventana aparte, la lista sin arribos ampliada contra la base.

    Es una consulta para UN evento: se recalcula el inventario vigente a la hora
    del evento y la actividad de las estaciones, y se muestran las que quedan
    dentro del radio pedido. Va aparte de la ventana de estaciones para no pisar
    el corte exportado: así se comparan los dos y lo que se baja es exactamente
    lo que se ve.
    """
    import ttkbootstrap as _t
    if ventana_previa is not None and ventana_previa.winfo_exists():
        ventana = ventana_previa
    else:
        ventana = _t.Toplevel(padre)
    descargas.encima_de(padre, ventana, modal=False)

    ventana.title("Sin arribos ampliado — %s"
                  % (_texto(evento.get("id_evento")) or ""))
    for hijo in ventana.winfo_children():
        hijo.destroy()

    arriba = _t.Frame(ventana)
    arriba.pack(fill="x", padx=8, pady=(8, 0))
    radio_texto = "sin límite" if radio is None else ("radio %.0f km" % radio)
    _t.Label(arriba, text="Consulta a la base %s — %s — %d estaciones"
             % (base, radio_texto, len(filas)),
             font=("", 11, "bold")).pack(side="left")
    if etiqueta_fuente:
        _t.Label(arriba, text=etiqueta_fuente,
                 bootstyle="secondary").pack(side="right")
    _t.Label(ventana, text="Recalculado contra el inventario vigente a la hora"
             " del evento; no reemplaza el corte exportado.",
             bootstyle="secondary", justify="left",
             wraplength=900).pack(anchor="w", padx=8, pady=(2, 4))

    marco_tabla = _t.Frame(ventana)
    marco_tabla.pack(fill="both", expand=True, padx=8, pady=(0, 8))
    _tabla_sin_arribos(_t, marco_tabla, filas, padre=ventana, cwd=cwd,
                       etiqueta="ampliado_%s" % (etiqueta_fuente or "seiscomp"),
                       log=log)

    ancho = 230 + sum(a for _, _, a in COLUMNAS_NO_PICADA) + 60
    ancho = max(ancho, 900)
    alto = min(760, max(420, ventana.winfo_screenheight() - 160))
    try:
        maximo = ventana.wm_maxsize()
        if maximo and maximo[0] > 0:
            ancho = min(ancho, maximo[0] - 40)
            alto = min(alto, maximo[1] - 40)
    except Exception:
        pass
    _centrar_en_pantalla(ventana, ancho, alto)
    return ventana


def abrir_panel(contenedor, ruta_eventos, ruta_fases=None,
                ruta_no_picadas=None, etiqueta_fuente=None,
                permitir_sin_fases=False, log=None, cwd=None):
    """
    Muestra el panel de revisión EMBEBIDO en 'contenedor' (un widget ttk).

    Es la misma forma que usa plotear.abrir_panel, para que app.py la enganche
    con una línea. Devuelve True si el panel quedó operativo y False si faltan
    los archivos, que es lo que permite al supervisor avisar sin que se caiga.

    'ruta_no_picadas' es el CSV con las estaciones del inventario que quedaron
    dentro del radio del evento y no tienen arribos asociados. Si no se pasa, se
    deriva del nombre del de eventos. Su falta NO hace fallar el panel: es una
    exportación anterior a ese archivo, y la ventana de estaciones avisa y
    muestra solo los arribos. Lo que sí sigue siendo fatal es que falten los
    eventos o las fases, porque de eso vive la revisión.

    'permitir_sin_fases' es para las fuentes que no tienen llegadas, como el
    catálogo publicado de eventquery o el select de Seisan: sin este permiso,
    la falta del CSV de fases se toma como señal de exportación incompleta y se
    devuelve False, que es lo que protege a SeisComp de abrir un panel a medias
    cuando la exportación se cortó. Por eso el valor por defecto es False y
    SeisComp no lo cambia: la protección se mantiene intacta.
    """
    if not ruta_eventos or not os.path.isfile(ruta_eventos):
        return False
    sin_fases = False
    if not ruta_fases:
        ruta_fases = ruta_eventos[:-4] + "_fases.csv"
    if not os.path.isfile(ruta_fases):
        if not permitir_sin_fases:
            return False
        sin_fases = True
        ruta_fases = None
    if not ruta_no_picadas:
        ruta_no_picadas = _ruta_no_picadas(ruta_eventos)
    if contenedor is None:
        # El supervisor puede llamar antes de tener la pantalla lista; se
        # devuelve False como con un archivo faltante y él avisa, en vez de
        # reventar con un AttributeError.
        return False

    # El import va acá y no arriba del todo a propósito: las funciones de
    # lógica son puras y se prueban sin pantalla, y esto evita que importar el
    # módulo para probarlas exija tener tkinter y un display.
    try:
        import ttkbootstrap as ttk
    except ImportError:
        return False

    eventos = _leer_csv(ruta_eventos)
    if not eventos:
        return False

    # La carpeta del listado exportado es la de trabajo, no la del script.
    if cwd is None:
        cwd = os.getcwd()

    # Las fases NO se cargan todas: se indexa dónde está cada evento y se lee
    # solo el tramo del que se elija. Con el histórico completo son cientos de
    # miles de llegadas y cargarlas todas ocuparía gigabytes.
    if sin_fases:
        # Un índice vacío hace que _leer_fases_de_evento devuelva [] sin abrir
        # nada, así que la lista de eventos y el resto del panel funcionan
        # igual; solo queda vacío el detalle de llegadas.
        indice_fases, campos_fases, total_fases = {}, [], 0
    else:
        indice_fases, campos_fases, total_fases = _indexar_fases(ruta_fases)

    # Las estaciones sin arribos se indexan igual que las fases, por el mismo
    # motivo: el archivo es una fila por evento y estación, y con el histórico
    # son cientos de miles. Su ausencia NO es un error: es una exportación
    # vieja, y la ventana de estaciones avisa y ofrece solo la solapa de
    # llegadas.
    if ruta_no_picadas and os.path.isfile(ruta_no_picadas):
        indice_no_picadas, campos_no_picadas, total_no_picadas = \
            _indexar_fases(ruta_no_picadas)
        hay_no_picadas = True
    else:
        indice_no_picadas, campos_no_picadas, total_no_picadas = {}, [], 0
        hay_no_picadas = False

    if log is not None:
        # Los dos totales no se usan para nada más, pero dicen algo que de
        # otro modo no se sabe: cuántos eventos traen llegadas y cuántos traen
        # estaciones sin arribos. Si un archivo vino a medias, el número es la
        # primera pista.
        log("SeisComp: %d llegadas de estación indexadas, %d estaciones sin"
            " arribos%s."
            % (total_fases, total_no_picadas,
               "" if hay_no_picadas else " (sin archivo)"))

    for hijo in contenedor.winfo_children():
        hijo.destroy()

    # --- Barra superior: archivos, filtro y mínimo de magnitud ---
    barra = ttk.Frame(contenedor)
    barra.pack(fill="x", pady=(0, 6))
    ttk.Label(barra, text="Mostrando", bootstyle="secondary").pack(side="left")
    caja_filtro = ttk.Entry(barra, width=24)
    caja_filtro.pack(side="left", padx=(4, 10))
    ttk.Label(barra, text="magnitud mínima", bootstyle="secondary").pack(side="left")
    caja_mag = ttk.Entry(barra, width=6)
    caja_mag.pack(side="left", padx=4)
    # Lat y Lon van en campos separados y no en la caja de texto: un -26 tiene
    # que ser latitud y un -71 longitud, pero en la caja de texto un número no
    # sabe a qué columna pertenece y además -26 aparece dentro de la fecha
    # 2026-09-26. Como campos separados no hay ambigüedad, y un entero es el
    # grado (banda de un grado) y un número con decimales es el punto exacto.
    ttk.Label(barra, text="Lat", bootstyle="secondary").pack(side="left",
                                                                padx=(10, 0))
    caja_lat = ttk.Entry(barra, width=7)
    caja_lat.pack(side="left", padx=(4, 0))
    ttk.Label(barra, text="Lon", bootstyle="secondary").pack(side="left",
                                                               padx=(8, 0))
    caja_lon = ttk.Entry(barra, width=7)
    caja_lon.pack(side="left", padx=(4, 4))
    boton_exportar = ttk.Button(barra, text="Exportar lista",
                                bootstyle="secondary-outline", width=17,
                                state="disabled")
    boton_exportar.pack(side="right", padx=(8, 8))
    etiqueta_estado = ttk.Label(barra, text="", bootstyle="secondary")
    etiqueta_estado.pack(side="right")

    # --- Lista de eventos (a todo el ancho) ---
    # El detalle del evento ya no va al lado: abre en su propia ventana al
    # hacer clic en una fila (_ventana_detalle). Compartir el ancho lo dejaba
    # cortado abajo, justo donde está el botón «Estaciones».
    cuerpo = ttk.Frame(contenedor)
    cuerpo.pack(fill="both", expand=True)
    marco_lista = ttk.Frame(cuerpo)
    marco_lista.pack(side="left", fill="both", expand=True)

    claves_ev = [c for c, _, _ in COLUMNAS_EVENTO]
    arbol_ev = ttk.Treeview(marco_lista, columns=claves_ev,
                            show="headings", selectmode="browse")
    for clave, titulo, ancho in COLUMNAS_EVENTO:
        arbol_ev.heading(clave, text=titulo)
        arbol_ev.column(clave, width=ancho, minwidth=45, stretch=False)
    barra_ev = ttk.Scrollbar(marco_lista, orient="vertical",
                             command=arbol_ev.yview)
    arbol_ev.configure(yscrollcommand=barra_ev.set)
    arbol_ev.pack(side="left", fill="both", expand=True)
    barra_ev.pack(side="right", fill="y")
    # Las columnas del panel suman 1275 px. Con la ventana que trae abrir_panel
    # entran, pero en una achicada las últimas se van de la vista y no había
    # forma de llegar: la barra horizontal evita perder columnas.
    barra_h = ttk.Scrollbar(marco_lista, orient="horizontal",
                            command=arbol_ev.xview)
    arbol_ev.configure(xscrollcommand=barra_h.set)
    barra_h.pack(side="bottom", fill="x")

    # Orden por columna: se guarda el sentido y se reordena al hacer clic.
    orden = {"columna": None, "descendente": False}

    def _aplicar_orden(columna):
        """Marca la columna de orden y reordena. Un clic más invierte el sentido."""
        if orden["columna"] == columna:
            orden["descendente"] = not orden["descendente"]
        else:
            orden["columna"] = columna
            orden["descendente"] = False
        _llenar_eventos()

    # La columna se cierra por defecto en el lambda y no se lee del evento a
    # propósito: Tk invoca el comando de un encabezado con una cadena, no con
    # un objeto de evento, así que uno que espere evento.widget revienta en el
    # primer clic.
    for clave, _, _ in COLUMNAS_EVENTO:
        arbol_ev.heading(clave,
                         command=lambda _e=None, c=clave: _aplicar_orden(c))

    estado = {"filas": [], "evento": None}

    def _elegidos():
        """
        Filas que pasan el filtro, ordenadas y SIN recortar.

        El corte de MAX_FILAS es solo de la pantalla: el export usa esta misma
        función y por eso trae todo lo que cumple el filtro. Si compartieran el
        recorte, un CSV de más de 20000 eventos saldría incompleto sin
        ningún aviso en el archivo.
        """
        mag_min = caja_mag.get().strip()
        try:
            mag_min = float(mag_min) if mag_min else None
        except ValueError:
            mag_min = None
        elegidos = _filtrar_listado(eventos, _valores_evento,
                                    caja_filtro.get(), mag_min,
                                    clave_mag="magnitud",
                                    lat=caja_lat.get(), lon=caja_lon.get(),
                                    extra=CAMPOS_BUSQUEDA_EVENTO)
        return _ordenar_eventos(elegidos, orden["columna"],
                                orden["descendente"]), mag_min

    def _llenar_eventos():
        for item in arbol_ev.get_children():
            arbol_ev.delete(item)
        elegido_orden, _ = _elegidos()
        total = len(elegido_orden)
        if total > MAX_FILAS:
            elegido_orden = elegido_orden[:MAX_FILAS]
            etiqueta_estado.config(
                text="Se muestran los primeros %d de %d eventos que cumplen"
                     " el filtro. Aflojá el filtro para ver el resto."
                     % (MAX_FILAS, total))
        else:
            etiqueta_estado.config(text="%d de %d eventos"
                                   % (len(elegido_orden), len(eventos)))
        # Sin filas no hay nada que volcar, y un botón prendido que no hace
        # nada es peor que uno apagado.
        boton_exportar.configure(state="normal" if total else "disabled")
        estado["filas"] = elegido_orden
        for fila in elegido_orden:
            arbol_ev.insert("", "end", iid=str(id(fila)),
                            values=_valores_evento(fila))

    def _al_exportar():
        """
        Exporta lo que se ve, con o sin filtro, a descargas/.

        Vuelve a filtrar desde los eventos completos en vez de usar
        estado["filas"], que a esta altura ya viene recortado a MAX_FILAS: si
        usara esa lista, el CSV de una consulta grande saldría truncado sin
        dejar rastro.
        """
        elegido_orden, _ = _elegidos()
        etiqueta = etiqueta_fuente or "seiscomp"
        try:
            ruta = _exportar_listado(elegido_orden, _valores_evento,
                                     COLUMNAS_EVENTO, cwd, etiqueta,
                                     padre=contenedor)
        except OSError as exc:
            aviso = "No se pudo escribir el listado: %s" % exc
            etiqueta_estado.config(text=aviso)
            if log:
                log(aviso)
            return
        if ruta is None:
            aviso = "No hay eventos que cumplan el filtro; no se escribió nada."
            etiqueta_estado.config(text=aviso)
            if log:
                log(aviso)
            return
        aviso = "Exportados %d eventos a %s" % (len(elegido_orden), ruta)
        etiqueta_estado.config(text="Exportados %d eventos a %s"
                               % (len(elegido_orden), os.path.basename(ruta)))
        if log:
            log(aviso)
            if len(elegido_orden) > MAX_FILAS:
                log("El listado trae las %d filas que cumplen el filtro, más "
                    "de las %d que muestra la pantalla."
                    % (len(elegido_orden), MAX_FILAS))

    def _abrir_estaciones():
        """
        Abre la ventana de estaciones del evento que está seleccionado.

        Las llegadas y las estaciones sin arribos se leen acá, no en
        _al_seleccionar: leerlas de cada evento que se selecciona sería
        recorrer dos veces el archivo, y el costo no está en el disco sino en
        el trabajo de armar el índice. Se leen solo del evento que se va a
        mostrar.
        """
        evento = estado.get("evento")
        if evento is None:
            return
        id_evento = evento.get("id_evento", "")
        fases = [] if sin_fases else _leer_fases_de_evento(
            ruta_fases, indice_fases, campos_fases, id_evento)
        no_picadas = [] if not hay_no_picadas else _leer_fases_de_evento(
            ruta_no_picadas, indice_no_picadas, campos_no_picadas, id_evento)

        def _ampliar_contra_base(radio):
            """
            Recalcula las estaciones sin arribos de este evento contra la base.

            Se llama desde el botón «Ampliar» de la solapa «Sin arribos» cuando
            el radio pedido supera el corte exportado. Consulta el inventario
            vigente a la hora del evento y la actividad de las estaciones, y
            muestra el resultado en una ventana aparte, descargable. Devuelve
            cuántas estaciones quedaron (o None si el usuario cancela por el
            aviso de cordura), para que el encabezado lo muestre.
            """
            base_datos = _texto(evento.get("base_datos"))
            if base_datos == VACIO:
                raise RuntimeError("el evento no trae la columna base_datos;"
                                   " re-exportá la ventana")
            instante = _instante_de_evento(evento)
            if instante is None:
                raise RuntimeError("el evento no tiene una hora válida")
            latitud = _a_float(evento.get("latitud"))
            longitud = _a_float(evento.get("longitud"))
            if latitud == float("inf") or longitud == float("inf"):
                raise RuntimeError("el evento no tiene coordenadas")
            # Import perezoso: la ventana de revisión no toca la base salvo que
            # el usuario pida ampliar.
            import exporta_ventana_seiscomp as ex
            picadas = {(f.get("red", ""), f.get("estacion", ""))
                       for f in fases}
            filas, _descartadas = ex.no_picadas_de_evento_desde_base(
                base_datos, instante, id_evento, evento.get("id_origen"),
                latitud, longitud, picadas, radio_km=radio)
            if len(filas) > UMBRAL_AVISO_AMPLIADO:
                from ttkbootstrap.dialogs import Messagebox
                texto = ("La ampliación trajo %d estaciones%s.\n\n¿Mostrar la"
                         " lista?" % (len(filas),
                                      "" if radio is not None else " (sin"
                                                                   " límite)"))
                if Messagebox.show_question(
                        texto, "Ampliación grande", parent=contenedor,
                        buttons=["Mostrar:primary", "Cancelar"]) != "Mostrar":
                    return None
            ventana_ampliada["ventana"] = _ventana_sin_arribos_ampliada(
                contenedor, evento, filas, radio, base_datos, cwd,
                etiqueta_fuente=etiqueta_fuente, log=log,
                ventana_previa=ventana_ampliada.get("ventana"))
            return len(filas)

        try:
            ventana_estaciones["ventana"] = _ventana_estaciones(
                contenedor, evento, fases, no_picadas, cwd,
                etiqueta_fuente=etiqueta_fuente, log=log,
                hay_no_picadas=hay_no_picadas,
                ventana_previa=ventana_estaciones.get("ventana"),
                al_ampliar=_ampliar_contra_base)
        except Exception as exc:
            # La ventana es un extra: si falla, el detalle que ya se está
            # viendo tiene que seguir siendo utilizable. Se avisa en la
            # etiqueta y en el registro en vez de voltear toda la pantalla.
            aviso = "No se pudo abrir la ventana de estaciones: %s" % exc
            etiqueta_estado.config(text=aviso)
            if log:
                log("[error] %s" % aviso)

    ventana_estaciones = {"ventana": None}
    ventana_ampliada = {"ventana": None}
    ventana_detalle = {"ventana": None}
    # _ventana_detalle llama a update_idletasks, que puede procesar un
    # <<TreeviewSelect>> que haya quedado encolado y reentrar acá antes de que
    # se guarde la ventana; sin esta guarda se abrirían dos ventanas iguales.
    seleccionando = {"activo": False}

    def _al_seleccionar(_evento=None):
        if seleccionando["activo"]:
            return
        seleccionando["activo"] = True
        try:
            seleccion = arbol_ev.selection()
            if not seleccion:
                return
            identificador = seleccion[0]
            if identificador == "arb0":      # cabecera
                return
            fila = next((f for f in estado["filas"]
                         if str(id(f)) == identificador), None)
            if fila is None:
                return
            estado["evento"] = fila
            # Se leen solo las llegadas de este evento, y se sueltan al pasar al
            # siguiente: la variable es reemplazada, no acumulada.
            fases = _leer_fases_de_evento(ruta_fases, indice_fases,
                                          campos_fases,
                                          fila.get("id_evento", ""))
            # El botón va aunque la fuente no traiga llegadas: en ese caso la
            # ventana solo puede mostrar la solapa de sin arribos, que es
            # justamente para qué sirve un catálogo sin llegadas.
            ventana_detalle["ventana"] = _ventana_detalle(
                contenedor, fila, fases, etiqueta_fuente=etiqueta_fuente,
                sin_fases=sin_fases, al_estaciones=_abrir_estaciones,
                ventana_previa=ventana_detalle.get("ventana"))
        finally:
            seleccionando["activo"] = False

    def _al_filtrar(_evento=None):
        # Solo repuebla la lista. No selecciona ni abre el detalle: si lo
        # hiciera, cada tecla del filtro abriría una ventana de parámetros.
        _llenar_eventos()

    boton_exportar.configure(command=_al_exportar)

    caja_filtro.bind("<KeyRelease>", _al_filtrar)
    caja_mag.bind("<KeyRelease>", _al_filtrar)
    caja_filtro.bind("<Return>", _al_filtrar)
    caja_mag.bind("<Return>", _al_filtrar)
    for caja in (caja_lat, caja_lon):
        caja.bind("<KeyRelease>", _al_filtrar)
        caja.bind("<Return>", _al_filtrar)
        caja.bind("<<Modified>>", _al_filtrar)
    # <<Modified>> cubre el pegado con el mouse, que no pasa por KeyRelease.
    caja_filtro.bind("<<Modified>>", _al_filtrar)
    caja_mag.bind("<<Modified>>", _al_filtrar)
    arbol_ev.bind("<<TreeviewSelect>>", _al_seleccionar)

    # El botón se crea acá, con _al_filtrar ya definido. No es adorno: un camino
    # que dependa solo de un binding de teclado es fácil que se pierda, y el
    # filtrado es la función principal de esta pantalla.
    ttk.Button(barra, text="Aplicar", bootstyle="secondary",
               command=_al_filtrar).pack(side="left", padx=(8, 0))

    _llenar_eventos()
    return True


def abrir_catalogo(contenedor, ruta_csv, etiqueta_fuente=None, log=None,
                    cwd=None, atribuciones=None):
    """
    Abre un catálogo crudo en la pestaña: listado simple, sin llegadas.

    Reutiliza la misma barra de filtro, el árbol y la lógica de orden, pero
    no carga fases ni muestra el detalle con llegadas. Las columnas son las del
    catálogo (no SeisComp).
    """
    if not ruta_csv or not os.path.isfile(ruta_csv):
        return False
    if contenedor is None:
        return False
    try:
        import ttkbootstrap as ttk
    except ImportError:
        return False
    filas_crudas = _leer_catalogo(ruta_csv)
    if not filas_crudas:
        return False
    eventos = [_normalizar_catalogo(f) for f in filas_crudas]

    # eventquery no trae responsable: si la app dedujo uno cruzando con Seisan
    # y SeisComp, se escribe en la columna «Analista probable». El catálogo de
    # Seisan no lo necesita porque su propio CSV ya trae el analista.
    if etiqueta_fuente == "eventquery" and atribuciones:
        for ev in eventos:
            texto = atribuciones.get("%s %s" % (ev.get("fecha", ""),
                                                ev.get("hora", "")))
            if texto:
                ev["analista"] = texto

    # La carpeta del listado exportado es la de trabajo, no la del script.
    if cwd is None:
        cwd = os.getcwd()

    for hijo in contenedor.winfo_children():
        hijo.destroy()

    barra = ttk.Frame(contenedor)
    barra.pack(fill="x", pady=(0, 6))
    ttk.Label(barra, text="Mostrando", bootstyle="secondary").pack(side="left")
    caja_filtro = ttk.Entry(barra, width=24)
    caja_filtro.pack(side="left", padx=(4, 10))
    ttk.Label(barra, text="magnitud mínima", bootstyle="secondary").pack(side="left")
    caja_mag = ttk.Entry(barra, width=6)
    caja_mag.pack(side="left", padx=4)
    ttk.Label(barra, text="Lat", bootstyle="secondary").pack(side="left",
                                                                padx=(10, 0))
    caja_lat = ttk.Entry(barra, width=7)
    caja_lat.pack(side="left", padx=(4, 0))
    ttk.Label(barra, text="Lon", bootstyle="secondary").pack(side="left",
                                                               padx=(8, 0))
    caja_lon = ttk.Entry(barra, width=7)
    caja_lon.pack(side="left", padx=(4, 4))
    boton_exportar = ttk.Button(barra, text="Exportar lista",
                                bootstyle="secondary-outline", width=17,
                                state="disabled")
    boton_exportar.pack(side="right", padx=(8, 8))
    etiqueta_estado = ttk.Label(barra, text="", bootstyle="secondary")
    etiqueta_estado.pack(side="right")

    cuerpo = ttk.Frame(contenedor)
    cuerpo.pack(fill="both", expand=True)

    columnas = (COLUMNAS_CATALOGO_EVENTQUERY if etiqueta_fuente == "eventquery"
                else COLUMNAS_CATALOGO_SEISAN)
    claves_ev = [c for c, _, _, _ in columnas]
    arbol_ev = ttk.Treeview(cuerpo, columns=claves_ev,
                            show="headings", selectmode="browse")
    for clave, titulo, ancho, es_num in columnas:
        arbol_ev.heading(clave, text=titulo)
        arbol_ev.column(clave, width=ancho, minwidth=45, stretch=False)

    barra_ev = ttk.Scrollbar(cuerpo, orient="vertical",
                             command=arbol_ev.yview)
    arbol_ev.configure(yscrollcommand=barra_ev.set)
    arbol_ev.pack(side="left", fill="both", expand=True)
    barra_ev.pack(side="right", fill="y")
    # El catálogo de eventquery suma 890 px contra los 980 de la ventana
    # principal: al achicarla ya se perdían columnas, y con Lat/Lon en el panel
    # de SeisComp la suma llega a 1275.
    barra_h = ttk.Scrollbar(cuerpo, orient="horizontal",
                            command=arbol_ev.xview)
    arbol_ev.configure(xscrollcommand=barra_h.set)
    barra_h.pack(side="bottom", fill="x")

    orden = {"columna": None, "descendente": False}

    def _aplicar_orden(columna):
        if orden["columna"] == columna:
            orden["descendente"] = not orden["descendente"]
        else:
            orden["columna"] = columna
            orden["descendente"] = False
        _llenar_eventos()

    for clave, _, _, _ in columnas:
        arbol_ev.heading(clave,
                         command=lambda _e=None, c=clave: _aplicar_orden(c))

    estado = {"filas": eventos}

    def _es_num(columna):
        for c, _, _, n in columnas:
            if c == columna:
                return n
        return False

    def _valores(fila):
        out = []
        for c, _, _, _ in columnas:
            v = fila.get(c, "")
            if _es_num(c) and c in ("mag", "prof"):
                out.append(_numero(v, 1))
            elif c in ("latitud", "longitud"):
                # Mismo redondeo que el panel de SeisComp: si el catálogo
                # mostrara -26.156 y el panel -26.16, el mismo evento se vería
                # distinto según la pestaña.
                out.append(_numero(v, DECIMALES_COORD))
            else:
                out.append(_texto(v))
        return out

    def _clave_ord(fila, columna):
        for c, _, _, n in columnas:
            if c == columna and n:
                try:
                    return (0, float(str(fila.get(c, "")).strip() or "inf"))
                except Exception:
                    return (1, float("inf"))
        if columna == "fecha":
            return (0, str(fila.get("fecha", "")).strip())
        if columna == "hora":
            return (0, str(fila.get("hora", "")).strip())
        return (0, str(fila.get(columna, "")).strip().lower())

    def _ordenar(evs, columna, desc=False):
        if columna is None:
            return list(evs)
        con = [f for f in evs if str(f.get(columna, "")).strip() != ""]
        sin = [f for f in evs if str(f.get(columna, "")).strip() == ""]
        con.sort(key=lambda x: _clave_ord(x, columna), reverse=desc)
        return con + sin

    def _elegidos():
        """
        Filas que pasan el filtro, ordenadas.

        No hay tope acá, pero el export usa esta misma función para no tener dos
        caminos distintos que puedan discrepar sobre qué se está mostrando.
        """
        mag_min = caja_mag.get().strip()
        try:
            mag_min = float(mag_min) if mag_min else None
        except ValueError:
            mag_min = None
        elegidos = _filtrar_listado(eventos, _valores, caja_filtro.get(),
                                    mag_min, clave_mag="mag",
                                    lat=caja_lat.get(), lon=caja_lon.get())
        return _ordenar(elegidos, orden["columna"], orden["descendente"])

    def _llenar_eventos():
        for item in arbol_ev.get_children():
            arbol_ev.delete(item)
        elegidos = _elegidos()
        etiqueta_estado.config(text="%d eventos" % len(elegidos))
        # Sin filas no hay nada que volcar, y un botón prendido que no hace
        # nada es peor que uno apagado.
        boton_exportar.configure(state="normal" if elegidos else "disabled")
        estado["filas"] = elegidos
        for fila in elegidos:
            arbol_ev.insert("", "end", iid=str(id(fila)), values=_valores(fila))

    def _al_exportar():
        """Exporta lo que se ve, con o sin filtro, a descargas/."""
        elegidos = _elegidos()
        try:
            ruta = _exportar_listado(elegidos, _valores, columnas, cwd,
                                     etiqueta_fuente, padre=contenedor)
        except OSError as exc:
            aviso = "No se pudo escribir el listado: %s" % exc
            etiqueta_estado.config(text=aviso)
            if log:
                log(aviso)
            return
        if ruta is None:
            # None es "no había filas" o "se canceló la pregunta de formato".
            # Cancelar no es un error: no se avisa nada.
            if not elegidos:
                aviso = ("No hay eventos que cumplan el filtro; no se "
                         "escribió nada.")
                etiqueta_estado.config(text=aviso)
                if log:
                    log(aviso)
            return
        if log:
            log("Exportados %d eventos a %s" % (len(elegidos), ruta))
        etiqueta_estado.config(text="Exportados %d eventos a %s"
                               % (len(elegidos), os.path.basename(ruta)))

    boton_exportar.configure(command=_al_exportar)

    caja_filtro.bind("<KeyRelease>", lambda _e: _llenar_eventos())
    caja_mag.bind("<KeyRelease>", lambda _e: _llenar_eventos())
    caja_filtro.bind("<Return>", lambda _e: _llenar_eventos())
    caja_mag.bind("<Return>", lambda _e: _llenar_eventos())
    caja_filtro.bind("<<Modified>>", lambda _e: _llenar_eventos())
    caja_mag.bind("<<Modified>>", lambda _e: _llenar_eventos())
    for caja in (caja_lat, caja_lon):
        caja.bind("<KeyRelease>", lambda _e: _llenar_eventos())
        caja.bind("<Return>", lambda _e: _llenar_eventos())
        caja.bind("<<Modified>>", lambda _e: _llenar_eventos())

    ttk.Button(barra, text="Aplicar", bootstyle="secondary",
               command=_llenar_eventos).pack(side="left", padx=(8, 0))

    _llenar_eventos()
    return True


# Eventos que sí están publicados pero cuyos parámetros no coinciden con los de
# la solución local. Los deltas son distancias (compara.py las toma positivas
# antes de guardarlas), no desplazamientos con signo: 0.018 es que hay 18 m de
# diferencia, no hacia dónde.
#
# Van juntos el valor local y el publicado de cada parámetro, y al final la
# columna que dice cuál de ellos discrepó: sin el lado publicado a la vista, la
# diferencia quedaba invisible (los deltas redondeados a 4 podían dar 0).
COLUMNAS_NO_ACTUALIZADO = [
    ("fecha_local", "Fecha y hora (local)", 150),
    ("lat_local", "Lat. local", 90),
    ("lat_eventquery", "Lat. publicada", 90),
    ("lon_local", "Lon. local", 90),
    ("lon_eventquery", "Lon. publicada", 90),
    ("prof_local", "Prof. local", 80),
    ("prof_eventquery", "Prof. publicada", 80),
    ("mag_local", "Mag. local", 80),
    ("mag_eventquery", "Mag. publicada", 95),
    ("analista", "Analista", 90),
    ("dt_seg", "Δt (s)", 70),
    ("dlat", "Δlat (°)", 80),
    ("dlon", "Δlon (°)", 80),
    ("discrepancias", "Parámetros que difieren", 170),
]

# Nombre legible de cada parámetro para la columna de discrepancias.
ETIQUETAS_DISCREPANCIA = {
    "lat": "lat",
    "lon": "lon",
    "prof": "prof",
    "mag": "mag",
}

# Columnas de 'no actualizado' que se muestran con el número redondeado.
# Las coordenadas y los deltas NO van aquí a propósito: _numero usa %g y
# perdería decimales que sí están en el dato.
_COLUMNAS_REDONDEADAS = frozenset((
    "prof_local", "prof_eventquery", "mag_local", "mag_eventquery", "dt_seg",
))

# Las que se ordenan numéricamente al hacer clic en el encabezado. Ordenar
# estas por el texto pondría "10.0" antes que "9.0", que es justo el error que
# hace LOOK mal usado.
_COLUMNAS_ORDENABLES = frozenset((
    "lat_local", "lon_local", "lat_eventquery", "lon_eventquery",
    "prof_local", "prof_eventquery", "mag_local", "mag_eventquery",
    "dt_seg", "dlat", "dlon",
))


def _valores_no_actualizado(fila):
    """Una fila de no actualizado, en el orden de COLUMNAS_NO_ACTUALIZADO."""
    valores = []
    for clave, _titulo, _ancho in COLUMNAS_NO_ACTUALIZADO:
        bruto = fila.get(clave, "")
        if clave in _COLUMNAS_REDONDEADAS:
            valores.append(_numero(bruto))
        else:
            valores.append(_texto(bruto))
    # Un "-0.0" en los deltas viene de la resta antes de tomar el valor
    # absoluto; se muestra como 0 para que no parezca algo raro.
    return ["0" if v == "-0.0" else v for v in valores]


def _no_actualizados(fuente, cwd=None):
    """
    Filas de 'no actualizado' de una fuente, una por evento local.

    Se parte de datos/atribucion_<fuente>.csv, que compara.py escribe con un
    registro por CRUCE. Un mismo evento local puede aparecer en más de una fila
    si cayó dentro de la tolerancia de dos eventos publicados: el informe .txt
    escribe una fila por evento local, y el CSV una por cruce, así que hay que
    agrupar para no mostrar el mismo evento repetido. De cada grupo se queda el
    mejor cruce (menor Δt), que es la misma idea de _analistas_para_evento.
    """
    if cwd is None:
        cwd = os.getcwd()
    ruta = os.path.join(cwd, "datos", "atribucion_%s.csv" % fuente)
    if not os.path.isfile(ruta):
        return None
    try:
        filas = _leer_csv(ruta)
    except OSError:
        return None
    mejores = {}
    for fila in filas:
        if not _no_actualizado(fila):
            continue
        clave = (fila.get("fecha_local", ""), fila.get("lat_local", ""),
                 fila.get("lon_local", ""))
        actual = mejores.get(clave)
        if actual is None or _a_float(fila.get("dt_seg")) < _a_float(
                actual.get("dt_seg")):
            mejores[clave] = fila
    # Se anota qué parámetros discreparon, con el mismo helper que usa
    # compara.py para decidir el flag: la columna no puede contradecir al
    # informe.
    for fila in mejores.values():
        fila["discrepancias"] = ", ".join(
            ETIQUETAS_DISCREPANCIA.get(c, c)
            for c in _discrepancias(fila)) or VACIO
    return list(mejores.values())


def _discrepancias(fila):
    """Lista de parámetros ('lat', 'lon', 'prof', 'mag') que no coinciden."""
    return comparacion.parametros_discrepantes(
        fila.get("lat_eventquery", ""), fila.get("lon_eventquery", ""),
        fila.get("prof_eventquery", ""), fila.get("mag_eventquery", ""),
        fila.get("lat_local", ""), fila.get("lon_local", ""),
        fila.get("prof_local", ""), fila.get("mag_local", ""))


def _no_actualizado(fila):
    """Si este cruce marca el evento como no actualizado.

    Mismo criterio que usa comparar() en compara.py, vía comparacion.py:
    difieren la latitud, la longitud, la profundidad o la magnitud, comparadas
    numéricamente a la precisión con la que se manejan (coordenadas a 3
    decimales; profundidad y magnitud a 1).
    """
    return bool(_discrepancias(fila))


def abrir_no_actualizados(contenedor, fuente, log=None, cwd=None):
    """
    Lista los eventos publicados que no coinciden con la solución local.

    Los datos salen de datos/atribucion_<fuente>.csv, que escribe la corrida
    del análisis: no consulta nada ni recalcula el cruce, solo lo muestra. La
    fuente es 'seisan' o 'seiscomp'.

    Se ordena haciendo clic en cualquier encabezado (el clic repetido invierte
    el sentido) y se filtra por texto en cualquier columna. Las dos descargas
    van a descargas/: la normal arma el archivo con el filtro y el orden puestos,
    y «Descargar todo» lo escribe sin filtrar, que es lo que uno quiere para
    repartir el listado completo.
    """
    log = log or (lambda _t: None)
    if contenedor is None:
        return False
    if cwd is None:
        cwd = os.getcwd()
    filas = _no_actualizados(fuente, cwd)
    if filas is None:
        return False

    try:
        import ttkbootstrap as ttk
    except ImportError:
        return False

    for hijo in contenedor.winfo_children():
        hijo.destroy()

    estado = {"orden": None, "desc": False, "elegidas": list(filas)}

    marco = ttk.Frame(contenedor)
    marco.pack(fill="both", expand=True, padx=8, pady=6)

    # --- Controles: filtro, estado y descargas ---
    marco_controles = ttk.Frame(marco)
    marco_controles.pack(fill="x", pady=(0, 4))
    ttk.Label(marco_controles, text="Filtrar:").pack(side="left")
    caja_filtro = ttk.Entry(marco_controles, width=24)
    caja_filtro.pack(side="left", padx=(4, 10))
    etiqueta_estado = ttk.Label(marco_controles, text="",
                               bootstyle="secondary")
    etiqueta_estado.pack(side="left")

    def _al_descargar(todas=False):
        elegidas = filas if todas else estado["elegidas"]
        if not elegidas:
            return
        ruta = _exportar_listado(elegidas, _valores_no_actualizado,
                                 COLUMNAS_NO_ACTUALIZADO, cwd,
                                 "no actualizados %s" % fuente,
                                 padre=contenedor)
        if ruta is None:
            return
        aviso = "Descargados %d eventos a %s" % (len(elegidas),
                                                  os.path.basename(ruta))
        etiqueta_estado.config(text=aviso)
        log(aviso)

    boton_descargar = ttk.Button(marco_controles, text="Descargar",
                                 bootstyle="primary-outline",
                                 command=_al_descargar)
    boton_descargar.pack(side="right")
    ttk.Button(marco_controles, text="Descargar todo",
               bootstyle="secondary-outline",
               command=lambda: _al_descargar(todas=True)).pack(
                   side="right", padx=(6, 0))

    # --- Tabla ---
    marco_tabla = ttk.Frame(marco)
    marco_tabla.pack(fill="both", expand=True)
    claves = [c for c, _, _ in COLUMNAS_NO_ACTUALIZADO]
    arbol = ttk.Treeview(marco_tabla, columns=claves, show="headings",
                         selectmode="browse")
    for clave, titulo, ancho in COLUMNAS_NO_ACTUALIZADO:
        arbol.heading(clave, text=titulo,
                      command=lambda c=clave: _al_ordenar(c))
        arbol.column(clave, width=ancho, minwidth=45, stretch=False)
    barra_v = ttk.Scrollbar(marco_tabla, orient="vertical",
                            command=arbol.yview)
    arbol.configure(yscrollcommand=barra_v.set)
    barra_h = ttk.Scrollbar(marco_tabla, orient="horizontal",
                            command=arbol.xview)
    arbol.configure(xscrollcommand=barra_h.set)
    arbol.pack(side="left", fill="both", expand=True)
    barra_v.pack(side="right", fill="y")
    barra_h.pack(side="bottom", fill="x")

    def _clave_orden(fila, columna):
        """Clave de orden de una fila. Las numéricas no salen de la columna."""
        if columna in _COLUMNAS_ORDENABLES:
            try:
                return (0, float(str(fila.get(columna, "")).strip()), "")
            except (TypeError, ValueError):
                pass
        return (1, 0.0, str(fila.get(columna, "")).strip().lower())

    def _ordenar(evs, columna, desc=False):
        if columna is None:
            return list(evs)
        con = [f for f in evs if str(f.get(columna, "")).strip() != ""]
        sin = [f for f in evs if str(f.get(columna, "")).strip() == ""]
        con.sort(key=lambda f: _clave_orden(f, columna), reverse=desc)
        return con + sin

    def _coincide(fila, texto):
        """True si el texto buscado aparece en alguna celda de la fila."""
        if not texto:
            return True
        return texto in " ".join(str(v).lower() for v in fila.values())

    def _al_ordenar(columna):
        if estado["orden"] == columna:
            estado["desc"] = not estado["desc"]
        else:
            estado["orden"] = columna
            estado["desc"] = False
        _llenar()

    def _elegidas():
        texto = caja_filtro.get().strip().lower()
        return _ordenar([f for f in filas if _coincide(f, texto)],
                        estado["orden"], estado["desc"])

    def _llenar(_evento=None):
        for item in arbol.get_children():
            arbol.delete(item)
        elegidas = _elegidas()
        estado["elegidas"] = elegidas
        if len(elegidas) == len(filas):
            etiqueta_estado.config(text="%d evento%s"
                                    % (len(filas),
                                       "" if len(filas) == 1 else "s"))
        else:
            etiqueta_estado.config(text="%d de %d eventos"
                                    % (len(elegidas), len(filas)))
        # Sin filas el botón queda apagado: un botón prendido que no hace nada
        # es peor que uno apagado.
        boton_descargar.configure(state="normal" if elegidas else "disabled")
        for indice, fila in enumerate(elegidas):
            arbol.insert("", "end", iid=str(indice),
                         values=_valores_no_actualizado(fila))

    caja_filtro.bind("<KeyRelease>", _llenar)
    _llenar()

    log("No actualizados de %s: %d eventos."
        % (fuente, len(filas)))
    return True


# Nombres de columna con la fecha, según el archivo: el catálogo de referencia
# usa 'time' con formato ISO, y los derivados del flujo usan 'Fecha_Hora'.
COLUMNAS_DE_TIEMPO = ("time", "Fecha_Hora", "fecha hora", "ot_utc")

# Formatos de fecha que aparecen en esos archivos: con 'T' y 'Z' al final en el
# catálogo, y con un espacio en los del flujo.
FORMATOS_DE_FECHA = ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S")


def _parsear_instante(texto):
    """Interpreta una fecha de cualquiera de esos formatos, o devuelve None."""
    if texto is None:
        return None
    limpio = str(texto).strip()
    if not limpio:
        return None
    for patron in FORMATOS_DE_FECHA:
        try:
            return datetime.strptime(limpio[:19], patron)
        except ValueError:
            continue
    return None


def _ventana_del_catalogo(ruta):
    """
    Devuelve (desde, hasta) con las fechas del archivo, o None si no tiene una
    columna de tiempo reconocible.

    Sirve para abrir la exportación que corresponde al catálogo con el que se
    está revisando, y no la última que se escribió: cuando se revisan varios
    períodos en la misma carpeta, la última no siempre es la que interesa.
    """
    try:
        with open(ruta, encoding="utf-8-sig", newline="") as f:
            lector = csv.DictReader(f)
            nombres = lector.fieldnames or []
            columna = next((c for c in COLUMNAS_DE_TIEMPO if c in nombres), None)
            if columna is None:
                return None
            primero = ultimo = None
            for fila in lector:
                instante = _parsear_instante(fila.get(columna, ""))
                if instante is None:
                    continue
                if primero is None or instante < primero:
                    primero = instante
                if ultimo is None or instante > ultimo:
                    ultimo = instante
    except OSError:
        return None
    return (primero, ultimo) if primero else None


def _ventana_del_nombre(nombre):
    """
    Saca la ventana de un nombre tipo seiscomp_20260901000000_20260930235959.csv.

    Son los dos últimos tramos separados por guion bajo, en AAAAMMDDHHMMSS. Se
    toma del final y no por posición, así que el nombre puede traer un prefijo
    más largo sin romper.
    """
    if str(nombre).endswith(".csv"):
        nombre = str(nombre)[:-4]
    partes = str(nombre).split("_")
    if len(partes) < 3:
        return None
    try:
        return (datetime.strptime(partes[-2], "%Y%m%d%H%M%S"),
                datetime.strptime(partes[-1], "%Y%m%d%H%M%S"))
    except ValueError:
        return None


def _catalogo_disponible(raiz):
    """
    Busca un catálogo de referencia en la carpeta de trabajo.

    Son los CSV de la raíz que tienen columna de tiempo. Los de la subcarpeta
    datos/ se ignoran, y también los seiscomp_*, que son nuestras propias
    exportaciones. Si hay más de uno, gana el modificado más recientemente.
    """
    if not os.path.isdir(raiz):
        return None
    candidatos = []
    for nombre in os.listdir(raiz):
        if not nombre.endswith(".csv") or nombre.startswith("seiscomp_"):
            continue
        ruta = os.path.join(raiz, nombre)
        if not os.path.isfile(ruta):
            continue
        if _ventana_del_catalogo(ruta) is None:
            continue
        candidatos.append(ruta)
    if not candidatos:
        return None
    return max(candidatos, key=os.path.getmtime)


def _elegir_par(pares, ventana):
    """
    De los pares exportados, elige el que mejor cubre la ventana del catálogo.

    Se mide cuánto se superponen las dos ventanas, no si una contiene a la
    otra: el catálogo se arma con un margen y casi nunca coincide exacto con la
    consulta, así que un containment estricto dejaría sin elegir nada.

    Si ningún par se superpone, devuelve None y deja que main() lo diga. Antes
    caía al más reciente, pero eso es peligroso: si el único archivo que hay es
    de otro mes, se abría igual y parecía el correcto, con una fracción de los
    eventos del catálogo y sin ningún aviso.
    """
    if not pares:
        return None
    if ventana is None:
        return pares[0]
    desde, hasta = ventana
    mejor, mejor_puntaje = None, None
    for par in pares:
        propia = _ventana_del_nombre(os.path.basename(par["eventos"]))
        if propia is None:
            continue
        comunes = (min(hasta, propia[1]) - max(desde, propia[0])).total_seconds()
        if comunes <= 0:
            continue
        if mejor_puntaje is None or comunes > mejor_puntaje:
            mejor, mejor_puntaje = par, comunes
    return mejor


def _cobertura(ventana_par, ventana_cat):
    """
    Cuánta parte de la ventana del catálogo cubre un par, como (inicio, fin,
    fraccion). Devuelve (0, 0, 0.0) si no se pueden comparar.
    """
    if ventana_par is None or ventana_cat is None:
        return None, None, 0.0
    desde, hasta = ventana_cat
    inicio = max(desde, ventana_par[0])
    fin = min(hasta, ventana_par[1])
    if fin <= inicio:
        return inicio, fin, 0.0
    fraccion = (fin - inicio).total_seconds() / (hasta - desde).total_seconds()
    return inicio, fin, fraccion


def _directorio_datos():
    """
    Devuelve la carpeta de datos de trabajo: ./datos del directorio desde donde
    se ejecuta el script.

    Ojo con el criterio, que en este proyecto hay dos y se confunden:

      * los DATOS van al directorio de ejecución. Es lo que hace rutas.py, con
        el que escribe el exportador, y lo que usa el resto del flujo de
        revisión. Correr el exportador desde la carpeta de un mes deja los CSV
        en esa carpeta, no en la del proyecto.
      * los ARCHIVOS DEL PROYECTO (requirements.txt, los módulos) quedan junto
        a los scripts, y no se mueven con el directorio de ejecución.

    Por eso acá va os.getcwd() y no la carpeta del script: si se usara esta
    última, al ejecutar desde la carpeta de trabajo buscaría los datos en la del
    proyecto, que es justo donde no están.
    """
    return os.path.join(os.getcwd(), "datos")


def _elegir_archivos(raiz, ventana):
    """
    Pregunta por el CSV de eventos y completa con el de fases.

    El diálogo es el de tkinter y no uno de ttkbootstrap porque esta versión del
    paquete (1.12.2) no trae ningún selector de archivos: solo Messagebox.
    Igual queda bien, porque es el diálogo nativo del sistema.
    """
    from tkinter import filedialog
    directorio = os.path.join(raiz, "datos")
    if not os.path.isdir(directorio):
        directorio = raiz
    tipos = [("CSV", "*.csv"), ("Todos", "*")]

    evento = filedialog.askopenfilename(
        parent=ventana, title="Elegir el CSV de eventos",
        initialdir=directorio, filetypes=tipos)
    if not evento:
        return None, None

    # El de fases tiene el mismo nombre con el sufijo, que es como lo escribe el
    # exportador. Si no está, se pregunta, en vez de asumir que existe.
    fases = evento[:-4] + "_fases.csv"
    if not os.path.isfile(fases):
        fases = filedialog.askopenfilename(
            parent=ventana, title="Elegir el CSV de fases",
            initialdir=os.path.dirname(evento), filetypes=tipos)
    return evento, fases


def main():
    """Abre la interfaz en su propia ventana."""
    import ttkbootstrap as ttk

    raiz = os.getcwd()
    argumentos = sys.argv[1:]

    # --catalogo va aparte porque es una referencia, ni la ventana ni la salida.
    catalogo = None
    resto = []
    i = 0
    while i < len(argumentos):
        if argumentos[i] == "--catalogo":
            if i + 1 >= len(argumentos):
                print("[X] --catalogo necesita la ruta del archivo.")
                return 2
            catalogo = argumentos[i + 1]
            i += 2
            continue
        resto.append(argumentos[i])
        i += 1
    argumentos = resto

    if argumentos and argumentos[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    if len(argumentos) >= 1:
        ruta_eventos = argumentos[0]
    else:
        # Se busca la exportación que corresponde al catálogo con el que se está
        # revisando, y no la última escrita: al revisar varios períodos en la
        # misma carpeta, la más reciente no siempre es la que interesa.
        if catalogo is None:
            catalogo = _catalogo_disponible(raiz)
        ventana_cat = None
        if catalogo and os.path.isfile(catalogo):
            ventana_cat = _ventana_del_catalogo(catalogo)
            if ventana_cat:
                print("Catálogo     : %s" % os.path.basename(catalogo))
                print("              del %s al %s"
                      % (ventana_cat[0].strftime("%Y-%m-%d %H:%M"),
                         ventana_cat[1].strftime("%Y-%m-%d %H:%M")))
        elif catalogo:
            print("[Aviso] No existe el catálogo %s; se toma la exportación"
                  " más reciente." % catalogo)
            ventana_cat = None

        pares = _pares_disponibles(raiz)
        if not pares:
            print("No hay CSV de SeisComp en %s." % _directorio_datos())
            print("    Los datos se buscan en el directorio desde donde se"
                  " ejecuta este script.")
            print("    Lance el exportador desde esta misma carpeta, o pase"
                  " los archivos a mano.")
            ruta_eventos = None
        else:
            par = _elegir_par(pares, ventana_cat)
            if par is None and ventana_cat is not None:
                # Ninguna exportación cubre el catálogo. Es mejor decirlo que
                # abrir un mes cualquiera en silencio: se vería una lista corta
                # y parecería que el catálogo tiene pocos eventos.
                print("Ninguna exportación cubre la ventana del catálogo.")
                print("    Hay %d en %s, pero ninguna va del %s al %s."
                      % (len(pares), _directorio_datos(),
                         ventana_cat[0].strftime("%Y%m%d%H%M%S"),
                         ventana_cat[1].strftime("%Y%m%d%H%M%S")))
                print("    Exporte esa ventana primero:")
                print("      exporta_ventana_seiscomp.py %s %s"
                      % (ventana_cat[0].strftime("%Y%m%d%H%M%S"),
                         ventana_cat[1].strftime("%Y%m%d%H%M%S")))
                print("    Mientras tanto se abre la más reciente:")
                ruta_eventos = pares[0]["eventos"]
            else:
                ruta_eventos = par["eventos"]

            print("Mostrando    : %s" % os.path.basename(ruta_eventos))
            if ventana_cat is not None:
                inicio, fin, fraccion = _cobertura(
                    _ventana_del_nombre(os.path.basename(ruta_eventos)),
                    ventana_cat)
                if fraccion < 0.999:
                    print("              cubre solo el %.0f%% del catálogo"
                          " (del %s al %s de %s)"
                          % (100.0 * fraccion,
                             inicio.strftime("%Y-%m-%d") if inicio else "?",
                             fin.strftime("%Y-%m-%d") if fin else "?",
                             ventana_cat[1].strftime("%Y-%m-%d")))
            elif par is not pares[0]:
                print("              (no es la más reciente: se eligió la que"
                      " mejor cubre la ventana)")
    if not ruta_eventos:
        return 1
    ruta_fases = argumentos[1] if len(argumentos) > 1 else None

    ventana = ttk.Window(themename="flatly")
    ventana.title("Revisión de eventos de SeisComp")
    ventana.geometry("1500x800")
    marco = ttk.Frame(ventana, padding=8)
    marco.pack(fill="both", expand=True)

    if not abrir_panel(marco, ruta_eventos, ruta_fases):
        print("No se pudo abrir el panel. Revisá que existan los dos archivos:")
        print("   %s" % ruta_eventos)
        if ruta_fases:
            print("   %s" % ruta_fases)
        return 1

    barra = ttk.Frame(ventana, padding=(8, 0, 8, 8))
    barra.pack(fill="x")
    ttk.Button(barra, text="Elegir otros archivos…", bootstyle="secondary",
               command=lambda: _cambiar(ventana, marco)).pack(side="left")
    ventana.mainloop()
    return 0


def _cambiar(ventana, marco):
    evento, fases = _elegir_archivos(os.getcwd(), ventana)
    if evento and abrir_panel(marco, evento, fases):
        print("Ahora mostrando: %s" % evento)


def _pares_disponibles(raiz):
    """
    Los pares de CSV de SeisComp de ./datos, del más reciente al más viejo.

    Esta búsqueda vive acá y no en el verificador de entorno a propósito: saber
    cómo se llaman los archivos de esta funcionalidad es parte de la
    funcionalidad, no del entorno. Así el verificador no conoce a SeisComp y
    esta interfaz no depende de nada de nivel proyecto.
    """
    directorio = os.path.join(raiz, "datos")
    pares = []
    if not os.path.isdir(directorio):
        return pares
    for nombre in os.listdir(directorio):
        # Solo los de SeisComp, porque en esa carpeta el flujo de revisión deja
        # además sus propios JSON y CSV.
        if not nombre.startswith("seiscomp_") or not nombre.endswith(".csv"):
            continue
        # Los derivados no son una exportación por sí mismos: se derivan del
        # nombre del de eventos. Si no se excluyeran, cada ventana aparecería
        # dos veces, y el _ventana_del_nombre del _fases ni siquiera podría
        # parsear el nombre, así que además de mostrar de más rompería el
        # emparejamiento con el catálogo.
        if nombre.endswith("_fases.csv") or nombre.endswith("_no_picadas.csv"):
            continue
        completo = os.path.join(directorio, nombre)
        if not os.path.isfile(completo):
            continue
        fases = completo[:-4] + "_fases.csv"
        no_picadas = completo[:-4] + "_no_picadas.csv"
        pares.append({
            "eventos": completo,
            "fases": fases if os.path.isfile(fases) else None,
            "no_picadas": no_picadas if os.path.isfile(no_picadas) else None,
            "mtime": os.path.getmtime(completo),
        })
    pares.sort(key=lambda p: p["mtime"], reverse=True)
    return pares


if __name__ == "__main__":
    sys.exit(main())
