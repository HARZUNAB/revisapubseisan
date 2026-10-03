#!/usr/bin/env python3
"""Exporta a CSV las soluciones preferidas de SeisComp6 de una ventana de tiempo.

Consulta los eventos cuyo origen preferido cae dentro de la ventana indicada y
escribe dos CSV:

  * <salida>.csv          una fila por evento, con la solución preferida.
  * <salida>_fases.csv    una fila por llegada de estación de esa solución
                          preferida: fase y hora, geometría, si fue usada, la
                          magnitud que calculó esa estación, su tipo, el
                          residuo, el control de calidad y los datos de
                          inventario. Se asocia con el evento por id_evento.
                          Si la estación no calculó magnitud para esa fase, la
                          fila sigue apareciendo igual, con la celda vacía y
                          tiene_magnitud en "No". Nunca se escribe 0 en una
                          celda sin dato, porque un cero falso se cuela en los
                          promedios sin avisar.

Los dos archivos terminan en una columna base_datos, que dice de qué base salió
cada fila.

Uso:
    ./exporta_ventana_seiscomp.py
    ./exporta_ventana_seiscomp.py <inicio> <fin> [salida.csv] [--base <nombre>]
    ./exporta_ventana_seiscomp.py --sugerencia <inicio> <fin> [--reusar]
    ./seiscomp.sh <catalogo.csv>

La forma recomendada es el lanzador ./seiscomp.sh, que encadena la exportación
con la revisión. Este script no depende de él: se puede usar solo, y la ventana
que se le pase es la que sea.

La ventana va en formato AAAAMMDDHHMMSS y corresponde a hora UTC. Si no se
pasan los dos argumentos, se preguntan por pantalla con validación. Con
--sugerencia <inicio> <fin> esos valores aparecen ya escritos en la pregunta y
se aceptan con Enter, pero igual se pueden cambiar: la sugerencia no obliga a
exportar ese período ni lo restringe, la ventana sigue siendo libre.

Con --reusar, si los dos archivos de esa ventana ya existen y la exportación
anterior terminó bien, no se consulta la base y se devuelven los archivos que
ya están. Ver REEXPORTAR ABAJO para qué hace falta la marca de fin.

BASES DE DATOS

Es UNA sola base de datos repartida en varias: la base grande tiene el
histórico y una copia reducida se usa para responder rápido en tiempo real.
Consultar una sola deja huecos sin avisar, así que por defecto se combinan
todas las bases de SeisComp que haya en el servidor y se fusiona el resultado.

Cuando un evento está en más de una base, gana la que tiene datos más
recientes, que es la que está recibiendo. No se mezclan fases de dos bases
dentro de un mismo evento: la solución de cada evento sale entera de una base,
porque para la misma llegada las dos difieren en snr, magnitud de estación y
QC, y mezclar eso armaría una solución que no existe en ninguna.

Para consultar una sola base: --base <nombre>. El servidor, el usuario y la
clave salen de la línea "database" del global.cfg de SeisComp; se pueden
pisar con NEWPT_DB_HOST, NEWPT_DB_DATABASE, NEWPT_DB_USER y
NEWPT_DB_PASSWORD. Si no se encuentra ninguna de esas fuentes, el script se
detiene y avisa en vez de conectarse a una base cualquiera. Si la base elegida
no cubre la ventana pedida, lo avisa antes de exportar.

REEXPORTAR

Con --reusar se busca no volver a pegarle a la base cuando la ventana pedida ya
se exportó. Para saber si se puede, no alcanza con que los dos CSV existan: una
exportación que se cortó a mitad de camino deja el archivo de fases a medias y
se vería como una ventana más corta, sin ningún aviso. Por eso, al terminar
bien, se escribe una tercera archivo al lado:

    <salida>.csv.completo

que es la marca de que aquella exportación llegó hasta el final. --reusar solo
reutiliza los CSV si la marca está; si no está, los vuelve a exportar. La marca
se borra al empezar una exportación y se vuelve a escribir al terminarla, así
que un intento fallido nunca deja decir que algo se completó cuando no.

Este script es de SOLO LECTURA: no modifica la base de datos bajo ninguna
circunstancia. Lo único que envía al servidor es "SET TIME ZONE 'UTC'" (un
ajuste de sesión que no altera datos y se descarta al cerrar la conexión) y
las consultas SELECT. No hay INSERT, UPDATE, DELETE ni sentencias DDL, no se
crean índices y no se llama a commit(), por lo que la conexión cierra siempre
en rollback.
"""
import csv
import decimal
import os
import re
import sys
from datetime import datetime

import prog

try:
    # El módulo de mediciones solo existe en el proyecto NewPT; acá es opcional.
    import mediciones as med
except ImportError:
    med = None

FORMATO = "%Y%m%d%H%M%S"
TIMEOUT_CONEXION = 10

# Cuántas filas de fase se traen por vez desde el servidor. Es el tamaño del
# lote de escritura: con esto la memoria no depende del tamaño de la ventana.
TAMANO_LOTE = 5000

# A partir de cuántas filas de fase la exportación avisa que va a tardar. No
# corta nada, solo informa: el que decide es el que la lanzó.
AVISO_DE_LOTES = 200000

# Rango en el que una magnitud de estación es creíble. Medido sobre la base real
# en la ventana de septiembre 2026: el mínimo fue -1.438 y el máximo 10.330, con
# 3 valores bajo -1 y 4 sobre 10 de 169.130. Salirse de acá es un cálculo roto.
RANGO_MAG_ESTACION = (-1.0, 10.0)

# Las mismas 14 columnas, en el mismo orden, que consulta_eventosSC.py, más
# base_datos al final: de qué base salió la fila. Con varias bases en juego no
# hay forma de trazar un valor sospechoso hasta su origen si esto no queda
# escrito en el archivo.
CABECERA = [
    "id_evento", "ot_utc", "magnitud", "tipo_magnitud", "fases", "rms",
    "azgap", "latitud", "longitud", "profundidad_km", "agencia", "operador",
    "region", "estatus", "base_datos",
]

# Anclada al evento y unida a su solución preferida: evento -> origen preferido
# y evento -> magnitud preferida. Los INNER JOIN del origen dejan fuera los
# eventos que todavía no tienen solución preferida confirmada.
#
# Los decimales del SELECT son la convención con la que se tratan estos datos en
# todo el flujo, la misma con la que los traen Seisan y eventquery: coordenadas
# con tres decimales (~111 m) y profundidad y magnitud con uno. Sin redondear, la
# base devuelve la latitud con toda su precisión (valores como
# -26.155641555786133) y ese número es el que después se compara, se copia y se
# dibuja en todas partes.
CONSULTA_SQL = """
SELECT
    TRIM(po_e.m_publicid::text) AS id_evento,
    o.m_time_value AS ot_utc,
    ROUND(m.m_magnitude_value::numeric, 1) AS magnitud,
    m.m_type AS tipo_magnitud,
    o.m_quality_usedphasecount AS fases,
    ROUND(o.m_quality_standarderror::numeric, 2) AS rms,
    ROUND(o.m_quality_azimuthalgap::numeric, 0) AS azgap,
    ROUND(o.m_latitude_value::numeric, 3) AS latitud,
    ROUND(o.m_longitude_value::numeric, 3) AS longitud,
    ROUND(o.m_depth_value::numeric, 1) AS profundidad_km,
    o.m_creationinfo_agencyid AS agencia,
    o.m_creationinfo_author AS operador,
    ed.m_text AS region,
    o.m_evaluationstatus AS estatus
FROM event e
INNER JOIN publicobject po_e ON e._oid = po_e._oid
INNER JOIN publicobject po_o ON po_o.m_publicid = e.m_preferredoriginid
INNER JOIN origin o ON o._oid = po_o._oid
LEFT JOIN publicobject po_m ON po_m.m_publicid = e.m_preferredmagnitudeid
LEFT JOIN magnitude m ON po_m._oid = m._oid
LEFT JOIN eventdescription ed ON ed._parent_oid = e._oid
                             AND ed.m_type = 'region name'
WHERE o.m_time_value >= %s
  AND o.m_time_value <= %s
  AND (%s::text IS NULL OR o.m_evaluationStatus = %s::text)
ORDER BY o.m_time_value;
"""

# ---------------------------------------------------------------------------
# Fases (lecturas de estación) de la misma solución preferida
# ---------------------------------------------------------------------------
# En SeisComp 6.1 la tabla de fases se llama Arrival (antes PhaseReport) y se
# une al origen únicamente por _parent_oid: no tiene columna de origen. Cada
# fila trae la fase, la geometría y la marca m_timeUsed, que es la única señal
# de "usada" que existe (no hay flag de fase preferida en este esquema).
#
# La estación y la hora de llegada vienen del Pick, que Arrival referencia por
# su id público (a.m_pickID), igual que la Amplitud que se le midió.
# Un pick puede tener varias amplitudes: el LATERAL se queda con la más
# reciente para no duplicar la fase.
#
# La magnitud por estación se une por sm.m_amplitudeID, que es la amplitud
# exacta de esa fase. Esto se verificó contra la base real, y importa por tres
# razones. Primero, el padre de stationmagnitude es el ORIGEN, no la magnitud:
# sm._parent_oid = m._oid no trae ni una fila, contra 168.908 de 168.908 para
# sm._parent_oid = o._oid. El campo m_originID, que sería la otra puerta de
# entrada, está vacío en la totalidad de la tabla. Segundo, NO alcanza con
# filtrar por código de estación: hay 36.723 pares origen/estación con 2
# magnitudes, y hasta 6, así que multiplicaría las filas.
#
# Tercero, y esto no se ve hasta que se exporta un mes entero: hay pares
# origen/amplitud que tienen VARIAS stationmagnitude del mismo tipo y distinto
# valor (el mismo origen llegó a tener 6 MLv para una sola amplitud). Con un
# join plano esa fase sale repetida. Por eso la magnitud va en un LATERAL con
# LIMIT 1, que además elige la que aporta a la magnitud preferida. Medido sobre
# septiembre de 2026 completo: 51.278 filas para 51.278 llegadas, una cada una.
#
# Notar que hay 20 picks referenciados por dos llegadas distintas (misma fase,
# azimut distinto). Eso no es una duplicación: son dos llegadas reales, y el
# archivo tiene una fila por llegada.
#
# Como stationmagnitude cuelga del ORIGEN y nosotros filtramos por el origen
# PREFERIDO, lo que entra es justamente la solución que se quiere exportar.
# El residuo sí cuelga de la MAGNITUD: smc._parent_oid = m._oid, con 167.817 de
# 167.817. Son dos padres distintos y hay que mezclarlos con cuidado.
#
# Todos los joins de la magnitud son LEFT JOIN, así que una estación que fue
# picada sigue apareciendo aunque no haya calculado magnitud para esa fase. En
# ese caso la celda va VACÍA, nunca cero: un 0 se cuela en los promedios en
# silencio, mientras que una celda vacía la saltan pandas y Excel por su cuenta.
# La columna tiene_magnitud dice explícitamente Si o No.
#
# El inventario de la estación se resuelve en un LATERAL con LIMIT 1 para que
# una fase nunca pueda multiplicarse. El código de estación no alcanza solo:
# hay que pasar por network y respetar la vigencia (m_start/m_end), porque un
# mismo código puede repetirse en distintas épocas. Si el código no está en el
# inventario, esas columnas quedan vacías y la fase no se pierde.
CABECERA_FASES = [
    # Llaves: permiten asociar la fase con su evento y con su solución
    "id_evento", "id_origen", "id_pick",
    # Estación (en SC6 el id de forma de onda va dentro del Pick)
    "red", "estacion", "loc", "cha",
    # Fase y solución. Ojo: el _ms de SeisComp 6 guarda MICROsegundos (0 a
    # 999999), no milisegundos, así que la columna se llama llegada_us.
    "fase", "llegada_utc", "llegada_us", "correccion_s", "residual_s",
    "azimut", "distancia",
    # Cuáles usó la solución
    "usada", "peso", "polaridad",
    # Características de la medición
    "snr",
    # Magnitud que calculó esa estación para esa fase. Si no la calculó, la
    # celda queda vacía y tiene_magnitud dice "No".
    "mag_estacion", "tipo_mag_estacion", "tiene_magnitud", "mag_est_residuo",
    # Control de calidad: aprobado, rechazado o sin_evaluar. Es texto y no
    # booleano a propósito, para no confundir "rechazó" con "nunca se miró".
    "qc_estacion",
    # Inventario de la estación
    "est_lat", "est_lon", "est_elev", "est_lugar", "est_pais",
    # De qué base salió la fila
    "base_datos",
]

CONSULTA_FASES_SQL = """
SELECT
    TRIM(po_e.m_publicid::text)          AS id_evento,
    TRIM(po_o.m_publicid::text)          AS id_origen,
    TRIM(a.m_pickID::text)               AS id_pick,
    p.m_waveformID_networkCode           AS red,
    p.m_waveformID_stationCode           AS estacion,
    p.m_waveformID_locationCode          AS loc,
    p.m_waveformID_channelCode           AS cha,
    a.m_phase_code                       AS fase,
    p.m_time_value                       AS llegada_utc,
    p.m_time_value_ms                    AS llegada_us,
    a.m_timeCorrection                   AS correccion_s,
    a.m_timeResidual                     AS residual_s,
    a.m_azimuth                          AS azimut,
    a.m_distance                         AS distancia,
    a.m_timeUsed                         AS usada,
    a.m_weight                           AS peso,
    p.m_polarity                         AS polaridad,
    amp.m_snr                            AS snr,
    sm.m_magnitude_value                 AS mag_estacion,
    sm.m_type                            AS tipo_mag_estacion,
    CASE WHEN sm.smid IS NULL THEN 'No' ELSE 'Si' END             AS tiene_magnitud,
    smc.m_residual                                            AS mag_est_residuo,
    CASE WHEN sm.smid IS NULL THEN 'sin_evaluar'
         WHEN sm.m_passedQC THEN 'aprobado'
         ELSE 'rechazado' END                                 AS qc_estacion,
    inv.m_latitude                       AS est_lat,
    inv.m_longitude                      AS est_lon,
    inv.m_elevation                      AS est_elev,
    inv.m_place                          AS est_lugar,
    inv.m_country                        AS est_pais
FROM event e
INNER JOIN publicobject po_e ON e._oid = po_e._oid
INNER JOIN publicobject po_o ON po_o.m_publicid = e.m_preferredoriginid
INNER JOIN origin o ON o._oid = po_o._oid
LEFT JOIN publicobject po_m ON po_m.m_publicid = e.m_preferredmagnitudeid
LEFT JOIN magnitude m ON po_m._oid = m._oid
INNER JOIN arrival a ON a._parent_oid = o._oid
INNER JOIN publicobject po_p ON po_p.m_publicid = a.m_pickID
INNER JOIN pick p ON p._oid = po_p._oid
LEFT JOIN LATERAL (
    -- Sin alias propio a propósito: la verificación de aliases mira todo el
    -- SQL, y acá las columnas ya se llaman como las espera el SELECT exterior.
    -- Se trae también el id público de la amplitud porque es lo que permite
    -- colgarle la magnitud de esa fase en particular (sm.m_amplitudeID).
    SELECT
        a2.m_snr,
        po_a.m_publicid
    FROM amplitude a2
    INNER JOIN publicobject po_a ON a2._oid = po_a._oid
    WHERE a2.m_pickID = a.m_pickID
    ORDER BY a2.m_creationInfo_creationTime DESC NULLS LAST, a2._oid DESC
    LIMIT 1
) amp ON TRUE
LEFT JOIN LATERAL (
    -- Inventario de la estación que picked. El LIMIT 1 es lo que impide que
    -- una fase se repita por varias escrituras de inventario; la vigencia
    -- temporal es lo que impide que se confunda una época con otra.
    SELECT
        st.m_latitude,
        st.m_longitude,
        st.m_elevation,
        st.m_place,
        st.m_country
    FROM network net
    INNER JOIN station st ON st._parent_oid = net._oid
    WHERE net.m_code = p.m_waveformID_networkCode
      AND st.m_code = p.m_waveformID_stationCode
      AND st.m_start <= p.m_time_value
      AND (st.m_end IS NULL OR st.m_end >= p.m_time_value)
    LIMIT 1
) inv ON TRUE
LEFT JOIN LATERAL (
    -- Magnitud de ESA fase. El LIMIT 1 no es un detalle: hay pares
    -- origen/amplitud con hasta 6 stationmagnitude del mismo tipo y distinto
    -- valor, y con un join plano esa fase salía repetida. Cuando hay varias,
    -- gana la que efectivamente aportó a la magnitud preferida (tiene fila en
    -- stationmagnitudecontribution), y si ninguna aportó, la más reciente.
    -- El id público sale acá porque es lo que necesita el join del residuo.
    SELECT
        po_v.m_publicid AS smid,
        smv.m_magnitude_value,
        smv.m_type,
        smv.m_passedQC
    FROM stationmagnitude smv
    INNER JOIN publicobject po_v ON smv._oid = po_v._oid
    LEFT JOIN stationmagnitudecontribution smc_v
           ON smc_v._parent_oid = m._oid
          AND smc_v.m_stationMagnitudeID = po_v.m_publicid
    WHERE smv._parent_oid = o._oid
      AND smv.m_waveformID_networkCode = p.m_waveformID_networkCode
      AND smv.m_waveformID_stationCode = p.m_waveformID_stationCode
      AND smv.m_amplitudeID = amp.m_publicid
    ORDER BY (smc_v.m_stationMagnitudeID IS NOT NULL) DESC,
             smv.m_creationInfo_creationTime DESC NULLS LAST,
             smv._oid DESC
    LIMIT 1
) sm ON TRUE
LEFT JOIN stationmagnitudecontribution smc
       ON smc._parent_oid = m._oid
      AND smc.m_stationMagnitudeID = sm.smid
WHERE o.m_time_value >= %s
  AND o.m_time_value <= %s
  AND (%s::text IS NULL OR o.m_evaluationStatus = %s::text)
ORDER BY o.m_time_value, p.m_waveformID_stationCode, a.m_azimuth NULLS LAST;
"""



# ---------------------------------------------------------------------------
# Configuración y conexión
# ---------------------------------------------------------------------------
def ruta_datos(nombre="prueba.csv"):
    """
    Resuelve dónde se escribe un archivo de salida.

    Todo cae dentro del directorio desde donde se ejecuta el script, usando el
    módulo rutas.py, que es la fuente única de verdad del proyecto para organizar
    lo que genera el flujo de revisión: los datos van a ./datos/, que se crea
    sola si no está.

    NEWPT_DATA_DIR gana sobre todo, por si algún día corre desde un cron o desde
    otro proyecto que fije el destino. Y si rutas no se puede importar, porque
    este script se copió solo a otra carpeta, se avisa y se sigue escribiendo en
    el directorio del propio script, que es lo que se hacía antes.
    """
    env = os.environ.get("NEWPT_DATA_DIR")
    if env:
        return os.path.join(env, nombre)

    try:
        import rutas
        return rutas.p_datos(nombre)
    except ImportError:
        print("   [Aviso] No se encontró rutas.py; los archivos van junto a este"
              " script en vez de ./datos/.")
        if getattr(sys, "frozen", False):
            return os.path.join(os.path.dirname(sys.executable), nombre)
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), nombre)


class FaltanParametros(Exception):
    """No se pudo determinar con qué base de datos conectarse."""


def _ruta_global_cfg():
    """Ubica el global.cfg de SeisComp, que es quien define la base de datos."""
    candidatos = []
    raiz = os.environ.get("SEISCOMP_ROOT")
    if raiz:
        candidatos.append(os.path.join(raiz, "etc", "global.cfg"))
    candidatos.append(os.path.expanduser("~/seiscomp/etc/global.cfg"))
    for ruta in candidatos:
        if os.path.isfile(ruta):
            return ruta
    return None


def _leer_global_cfg():
    """
    Saca los parámetros de conexión de la línea `database` del global.cfg.

    El archivo no tiene secciones, es un clave = valor plano con comentarios, así
    que va con un barrido de líneas. Devuelve None si no está o no se puede leer.
    """
    ruta = _ruta_global_cfg()
    if ruta is None:
        return None
    try:
        with open(ruta, encoding="utf-8", errors="replace") as f:
            lineas = f.readlines()
    except OSError:
        return None

    for linea in lineas:
        limpia = linea.split("#", 1)[0].strip()
        if not limpia.lower().startswith("database"):
            continue
        _, _, valor = limpia.partition("=")
        valor = valor.strip()
        if not valor:
            continue
        # postgresql://usuario:clave@host/base
        cuerpo = valor.split("://", 1)[-1]
        credenciales, _, host_y_base = cuerpo.rpartition("@")
        if not host_y_base:
            continue
        host, _, base = host_y_base.partition("/")
        usuario, _, clave = credenciales.partition(":")
        if not base:
            continue
        return {
            "host": host,
            "database": base,
            "user": usuario or None,
            "password": clave or None,
        }
    return None


def configuracion(base=None):
    """
    Parámetros de conexión.

    El orden de precedencia es: lo que se pase por línea de comandos, después
    las variables NEWPT_DB_* del entorno, y por último la línea `database` del
    global.cfg, que es la que usa SeisComp. No hay ningún valor fijo a propósito:
    si ninguna de esas fuentes está, se avisa y se corta, porque adivinar una
    base sería exportar datos de la base equivocada sin dar ningún aviso.
    """
    desde_cfg = _leer_global_cfg() or {}
    origen = "global.cfg"

    def elegir(clave_entorno, clave_cfg):
        valor = os.environ.get(clave_entorno)
        if valor:
            return valor, "entorno"
        valor = desde_cfg.get(clave_cfg)
        return valor, origen if valor else None

    host, _ = elegir("NEWPT_DB_HOST", "host")
    base_efectiva, origen_base = elegir("NEWPT_DB_DATABASE", "database")
    usuario, _ = elegir("NEWPT_DB_USER", "user")
    clave, _ = elegir("NEWPT_DB_PASSWORD", "password")

    if base is not None:
        # Solo se pisa el nombre: el servidor y las credenciales siguen viniendo
        # de la configuración, para no tener que repetirlos.
        base_efectiva = base
        origen_base = "línea de comandos"

    if not base_efectiva:
        raise FaltanParametros(
            "No se pudo determinar la base de datos.\n"
            "    Probá una de estas opciones:\n"
            "      * indicarla explícitamente:  --base <nombre>\n"
            "      * definirla en el entorno:    export NEWPT_DB_DATABASE=<nombre>\n"
            "      * revisá la línea 'database' del global.cfg de SeisComp\n"
            "        (%s)"
            % (_ruta_global_cfg() or "no se encontró ningún global.cfg")
        )

    if not host:
        raise FaltanParametros(
            "Se indicó la base (%s) pero no hay ningún servidor de dónde sacarlo.\n"
            "    El host se lee del global.cfg, así que revisá que tenga la línea\n"
            "    'database' con el formato servicio://usuario:clave@host/base,\n"
            "    o definí NEWPT_DB_HOST en el entorno.\n"
            "    (%s)"
            % (base_efectiva,
               _ruta_global_cfg() or "no se encontró ningún global.cfg")
        )

    config = {
        "host": host,
        "database": base_efectiva,
        "user": usuario,
        "password": clave,
        "connect_timeout": TIMEOUT_CONEXION,
    }
    # psycopg2 no acepta None en estos campos: se completan con lo de siempre.
    config["user"] = config["user"] or "sysop"
    config["password"] = config["password"] or "sysop"
    config["_origen"] = origen_base
    return config


def conectar(config=None):
    """Abre la conexión a la base de SeisComp (import perezoso de psycopg2)."""
    import psycopg2
    if config is None:
        config = configuracion()
    return psycopg2.connect(
        host=config["host"], database=config["database"],
        user=config["user"], password=config["password"],
        connect_timeout=config["connect_timeout"],
    )


def crear_cursor(conn):
    from psycopg2.extras import RealDictCursor
    return conn.cursor(cursor_factory=RealDictCursor)


def _medir(etapa, extra=None):
    """Punto de medida, si el módulo de mediciones está disponible."""
    if med is None:
        return
    if extra is None:
        med.hito("consulta", etapa)
    else:
        med.hito("consulta", etapa, extra=extra)


# ---------------------------------------------------------------------------
# Interfaz de usuario
# ---------------------------------------------------------------------------
def _pedir(mensaje, ejemplo, defecto=None):
    """
    Pide un instante en formato AAAAMMDDHHMMSS, repreguntando si no es válido.

    Con 'defecto' no, un valor propuesto: si la respuesta viene vacía se
    devuelve ese en vez de dar el error de "no puede estar vacío", y el mensaje
    lo muestra al lado de la pregunta. El defecto es solo una sugerencia de
    atajo, no una validación más floja: lo que se escriba se revisa igual.
    """
    pista = ""
    if defecto is not None:
        pista = "  ·  Enter = %s" % defecto.strftime(FORMATO)
    while True:
        try:
            texto = input(mensaje.format(ejemplo=ejemplo, defecto=pista)).strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\n[-] Operación cancelada por el usuario.")
            sys.exit(1)

        if not texto:
            if defecto is not None:
                return defecto
            print("   Error: El valor no puede estar vacío.")
            continue
        if not re.match(r"^\d{14}$", texto):
            print("   Error: Use el formato AAAAMMDDHHMMSS (14 dígitos).")
            continue
        try:
            return datetime.strptime(texto, FORMATO)
        except ValueError:
            print("   Error: Fecha o hora inválida (ej. mes 13 o día 32).")


def _preguntar_ventana(sugerencia=None):
    """
    Pide inicio y término, y repregunta si el término no es posterior.

    'sugerencia' es una tupla (inicio, fin) que aparece escrita en las
    preguntas: se acepta con Enter y se puede cambiar. Cuando no hay sugerencia
    se pregunta igual, porque la ventana que se exporta es libre y no tiene por
    qué ser la de ningún otro archivo.
    """
    inicio_defecto, fin_defecto = sugerencia if sugerencia else (None, None)
    print("\n" + "=" * 70)
    print("           VENTANA DE TIEMPO A EXPORTAR DESDE SEISCOMP6")
    print("=" * 70)
    print("Formato: AAAAMMDDHHMMSS, en hora UTC. Ventana con extremos incluidos.\n")
    while True:
        inicio = _pedir("   Fecha y hora de INICIO   (Ej: {ejemplo}){defecto}: ",
                        "20260901000000", inicio_defecto)
        fin = _pedir("   Fecha y hora de TÉRMINO  (Ej: {ejemplo}){defecto}: ",
                     "20260930235959", fin_defecto)
        if fin > inicio:
            return inicio, fin
        print("\n   [X] El TÉRMINO debe ser posterior al INICIO.")
        print("       Por favor, ingrese la ventana nuevamente.\n")


# ---------------------------------------------------------------------------
# Exportación
# ---------------------------------------------------------------------------
def _celda(valor):
    """Normaliza un valor de la base para escribirlo en el CSV."""
    if valor is None:
        return ""
    if isinstance(valor, datetime):
        return valor.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(valor, decimal.Decimal):
        return float(valor)
    return valor


def _verificar_columnas(filas, cabecera=None, etiqueta="El SELECT"):
    """
    Compara los alias que devolvió el SELECT con la cabecera del CSV.
    Es la red de seguridad ante un cambio de esquema en la base.
    """
    if cabecera is None:
        cabecera = CABECERA
    if not filas:
        return
    recibidas = set(filas[0].keys())
    esperadas = set(cabecera)
    if recibidas == esperadas:
        return
    print("   [Aviso] %s no coincide exactamente con la cabecera del CSV:" % etiqueta)
    if esperadas - recibidas:
        print("           sin dato: %s" % ", ".join(sorted(esperadas - recibidas)))
    if recibidas - esperadas:
        print("           no declaradas: %s" % ", ".join(sorted(recibidas - esperadas)))


def _escribir_csv(ruta, filas, cabecera=None, append=False):
    """
    Escribe las filas en un CSV.

    Con append=True agrega al final y NO repite la cabecera. Es lo que permite
    volcar las fases por lotes: la cabecera se escribe una vez con el primer
    lote y el resto se van pegando.
    """
    if cabecera is None:
        cabecera = CABECERA
    modo = "a" if append else "w"
    with open(ruta, modo, encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        if not append:
            escritor.writerow(cabecera)
        for fila in filas:
            escritor.writerow([_celda(fila.get(columna)) for columna in cabecera])


def _ruta_fases(salida_eventos):
    """Deriva el nombre del CSV de fases a partir del de eventos."""
    base, extension = os.path.splitext(salida_eventos)
    return "%s_fases%s" % (base, extension or ".csv")


def _ruta_completo(salida_eventos):
    """
    Nombre de la marca que dice que aquella exportación terminó.

    Va pegada al nombre del CSV de eventos y no al del de fases, porque es la
    salida que define a la exportación: es la que se le pasa al revisor, y la
    que el lanzador usa para decidir si hay algo que reusar.
    """
    return "%s.completo" % salida_eventos


def _escribir_marca(ruta, inicio, fin, eventos, fases, bases):
    """
    Deja escrito que la exportación de esa ventana llegó hasta el final.

    Va con la cantidad de filas y con las bases consultadas porque, cuando más
    adelante alguien mire la carpeta, el archivo solo no dice si esos datos
    corresponden a lo que el catálogo pedía o a otra ventana.
    """
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("ventana %s %s | eventos %d | fases %d | bases %s | %s UTC\n"
                % (inicio.strftime(FORMATO), fin.strftime(FORMATO),
                   eventos, fases, ",".join(bases),
                   datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")))


def _resumen_fases(filas_fases):
    """
    Cuenta las fases con y sin magnitud de estación, y las que están fuera del
    rango creíble. No filtra nada: el objetivo es que quede registrado sin
    perder el dato crudo.
    """
    con_magnitud = 0
    fuera_de_rango = 0
    negativas = 0
    con_residuo = 0
    for fila in filas_fases:
        if fila.get("tiene_magnitud") != "Si":
            continue
        con_magnitud += 1
        if fila.get("mag_est_residuo") is not None:
            con_residuo += 1
        valor = fila.get("mag_estacion")
        if valor is None:
            continue
        valor = float(valor)
        if valor < 0:
            negativas += 1
        if not RANGO_MAG_ESTACION[0] <= valor <= RANGO_MAG_ESTACION[1]:
            fuera_de_rango += 1
    return {
        "con_magnitud": con_magnitud,
        "sin_magnitud": len(filas_fases) - con_magnitud,
        "con_residuo": con_residuo,
        "negativas": negativas,
        "fuera_de_rango": fuera_de_rango,
    }


def _acumular_por_evento(mapa, filas):
    """
    Va juntando los conteos de las fases, agrupados por evento.

    Hace falta porque las fases ya no se guardan todas en memoria: se escriben
    por lotes. Lo único que se retiene es un resumen chico por evento, decenas
    de miles de entradas mínimas, en vez de un millón de filas completas.
    """
    for f in filas:
        clave = f.get("id_evento")
        evento = mapa.get(clave)
        if evento is None:
            evento = {"fases": 0, "usadas": 0, "con_magnitud": 0,
                      "con_residuo": 0, "negativas": 0, "fuera_de_rango": 0,
                      "estaciones": set(), "magnitudes": [], "con_suma": 0.0}
            mapa[clave] = evento
        evento["fases"] += 1
        if str(f.get("usada", "")).strip().lower() == "true":
            evento["usadas"] += 1
        evento["estaciones"].add((f.get("red", ""), f.get("estacion", "")))
        if str(f.get("tiene_magnitud", "")).strip() != "Si":
            continue
        evento["con_magnitud"] += 1
        # Ojo con esto: str(None) es "None", no una cadena vacía, así que hay
        # que mirar el valor antes de convertirlo o se contarían como presentes
        # los residuos que la base tiene en NULL.
        if f.get("mag_est_residuo") not in (None, ""):
            evento["con_residuo"] += 1
        valor = f.get("mag_estacion")
        if valor in (None, ""):
            continue
        try:
            valor = float(valor)
        except (TypeError, ValueError):
            continue
        evento["magnitudes"].append(valor)
        evento["con_suma"] += valor
        if valor < 0:
            evento["negativas"] += 1
        if not RANGO_MAG_ESTACION[0] <= valor <= RANGO_MAG_ESTACION[1]:
            evento["fuera_de_rango"] += 1


def _resumen_desde_mapa(mapa):
    """Junta los conteos por evento en el resumen que se muestra al final."""
    total = {"con_magnitud": 0, "con_residuo": 0, "negativas": 0,
             "fuera_de_rango": 0, "usadas": 0, "fases": 0, "estaciones": 0,
             "con_suma": 0.0, "cuantas_magnitudes": 0, "eventos": len(mapa)}
    for evento in mapa.values():
        total["fases"] += evento["fases"]
        total["usadas"] += evento["usadas"]
        total["con_magnitud"] += evento["con_magnitud"]
        total["con_residuo"] += evento["con_residuo"]
        total["negativas"] += evento["negativas"]
        total["fuera_de_rango"] += evento["fuera_de_rango"]
        total["estaciones"] += len(evento["estaciones"])
        total["con_suma"] += evento["con_suma"]
        total["cuantas_magnitudes"] += len(evento["magnitudes"])
    total["sin_magnitud"] = total["fases"] - total["con_magnitud"]
    total["no_usadas"] = total["fases"] - total["usadas"]
    total["mag_promedio"] = (total["con_suma"] / total["cuantas_magnitudes"]
                             if total["cuantas_magnitudes"] else None)
    return total


CONSULTA_COBERTURA_SQL = """
SELECT min(o.m_time_value) AS desde, max(o.m_time_value) AS hasta
FROM event e
INNER JOIN publicobject po ON po.m_publicid = e.m_preferredoriginid
INNER JOIN origin o ON o._oid = po._oid
"""

# Cuenta rápida de lo que la ventana va a producir, para avisar antes de
# exportar y no dejar esperando veinte minutos sin saber a qué atenerse.
# Cuenta llegadas de TODOS los orígenes de la ventana, no solo de los que son
# origen preferido de algún evento, así que es un piso y no un exacto: sale
# barata porque no necesita pasar por event ni por publicobject.
CONSULTA_TAMANO_SQL = """
SELECT count(*) AS llegadas, count(DISTINCT o._oid) AS origenes
FROM origin o
INNER JOIN arrival a ON a._parent_oid = o._oid
WHERE o.m_time_value >= %s
  AND o.m_time_value <= %s
  AND (%s::text IS NULL OR o.m_evaluationStatus = %s::text)
"""


def _bases_a_consultar(base):
    """
    Decide contra qué bases se consulta.

    `base` es None, un nombre puntual o la palabra "todas". Con "todas" se usan
    todas las bases de SeisComp que el servidor declare, con el servidor y las
    credenciales que ya provienen de la configuración.
    """
    if base is not None and base.lower() != "todas":
        return [base]

    nombres = _bases_seiscomp()
    if not nombres:
        # No se pudo listar: se cae a la de la configuración, que siempre existe
        # o ya habría fallado antes.
        return [configuracion(None)["database"]]
    return nombres


def _bases_seiscomp():
    """
    Lista las bases de datos visibles para este usuario en el servidor.

    Se consulta pg_database desde una conexión a SeisComp y no a 'postgres',
    porque en este servidor el acceso a la base postgres está bloqueado por
    pg_hba para el usuario sysop y la conexión sería rechazada.
    """
    config = configuracion(None)
    try:
        import psycopg2
        conn = psycopg2.connect(host=config["host"], database=config["database"],
                                user=config["user"], password=config["password"],
                                connect_timeout=TIMEOUT_CONEXION)
    except Exception as e:
        print("   [Aviso] No se pudieron listar las bases del servidor (%s)."
              % str(e).strip().splitlines()[0])
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT datname FROM pg_database "
                       "WHERE datistemplate = false AND datallowconn "
                       "AND datname NOT IN ('postgres', 'template0', 'template1') "
                       "ORDER BY datname")
        nombres = [r[0] for r in cursor.fetchall()]
        return nombres or [config["database"]]
    except Exception as e:
        print("   [Aviso] No se pudieron listar las bases del servidor (%s)."
              % str(e).strip().splitlines()[0])
        return [config["database"]]
    finally:
        conn.close()


def _parametros_estatus(solo_confirmados):
    """
    Los dos valores del filtro de estatus, para las consultas.

    Se pasa el estado dos veces porque el filtro está escrito como
    "(%s::text IS NULL OR columna = %s::text)": con NULL no se filtra nada, y
    con 'confirmed' quedan solo los revisados por un analista. Medido en la base
    real, los eventos automáticos de la ventana tenían el estado vacío, así que
    este filtro solo ya saca las soluciones automáticas.
    """
    estado = "confirmed" if solo_confirmados else None
    return (estado, estado)


def _consultar_eventos_de_base(base, inicio, fin, solo_confirmados):
    """
    Trae los eventos de una base. Son pocos (decenas de miles como máximo), así
    que acá no hace falta ir por lotes.
    """
    config = configuracion(base)
    conn = conectar(config)
    try:
        _medir("conexion_fin", "host=%s base=%s" % (config["host"], base))
        cursor = crear_cursor(conn)
        cursor.execute("SET TIME ZONE 'UTC'")
        cursor.execute(CONSULTA_COBERTURA_SQL)
        cobertura = cursor.fetchone()
        cursor.execute(CONSULTA_SQL,
                       (inicio, fin) + _parametros_estatus(solo_confirmados))
        filas = cursor.fetchall()
        _medir("query_fin", "base=%s" % base)
        # La estimación sale en la misma conexión para no abrir otra.
        cursor.execute(CONSULTA_TAMANO_SQL,
                       (inicio, fin) + _parametros_estatus(solo_confirmados))
        estimadas = (cursor.fetchone() or {}).get("llegadas", 0)
    finally:
        conn.close()
    return filas, cobertura, estimadas


def _escribir_fases_de_base(base, inicio, fin, solo_confirmados, dueno,
                            ruta_fases, resumen_por_evento, esperado=None,
                            progreso=None):
    """
    Escribe las fases de UNA base, y solo de los eventos que le tocan, yendo por
    lotes con un cursor de servidor.

    Esto es lo que mantiene acotada la memoria: con fetchall, una ventana
    grande necesita tener todas las filas vivas antes de escribir nada, y se
    midió que el histórico completo ocupaba 5,6 GB. Con un cursor de servidor
    el resultado se va trayendo de a porciones y la memoria queda plana.

    'dueno' dice qué base manda en cada evento, según la más reciente. Así cada
    evento escribe sus fases una sola vez y de una sola base, sin necesidad de
    tener los resultados de las dos bases en memoria al mismo tiempo.

    El archivo ya viene con su encabezado escrito: esta función solo agrega.

    'esperado' es la cantidad estimada de llegadas y 'progreso' un callback
    opcional que recibe (escritas, esperado) tras cada lote, para el avance de la
    interfaz. Sin callback no se informa nada.
    """
    config = configuracion(base)
    total = 0
    from psycopg2.extras import RealDictCursor
    conn = conectar(config)
    try:
        cursor = crear_cursor(conn)
        cursor.execute("SET TIME ZONE 'UTC'")
        # itersize no alcanza con un cursor normal: libpq igual trae el
        # resultado entero. El cursor con nombre lo deja en el servidor.
        cursor = conn.cursor(name="fases", cursor_factory=RealDictCursor,
                             withhold=False)
        cursor.itersize = TAMANO_LOTE
        cursor.execute(CONSULTA_FASES_SQL,
                       (inicio, fin) + _parametros_estatus(solo_confirmados))
        while True:
            lote = cursor.fetchmany(TAMANO_LOTE)
            if not lote:
                break
            filas = []
            for fila in lote:
                if dueno.get(fila.get("id_evento")) != base:
                    continue
                fila = dict(fila)
                fila["base_datos"] = base
                filas.append(fila)
            if filas:
                _escribir_csv(ruta_fases, filas, CABECERA_FASES, append=True)
                total += len(filas)
                # El resumen se acumula por evento, así que no hace falta
                # guardar las filas: al final solo quedan los conteos.
                _acumular_por_evento(resumen_por_evento, filas)
                if progreso is not None:
                    progreso(total, esperado)
        cursor.close()
        _medir("fases_fin", "base=%s" % base)
    finally:
        conn.close()
    return total


def _prioridad_por_base(coberturas):
    """
    Ordena las bases de más antigua a más reciente, según hasta dónde llega cada
    una. La más reciente es la que recibe datos, así que es la que gana cuando
    un evento está en más de una.

    Se usa la fecha real y no el nombre: decidir por alfabeto sería confiar en
    que la base nueva se llama con un número mayor, que es suposición.
    """
    ordenables = []
    for base, cobertura in coberturas.items():
        hasta = (cobertura or {}).get("hasta") or datetime.min
        ordenables.append((base, hasta))
    ordenables.sort(key=lambda x: x[1])
    return {base: i for i, (base, _) in enumerate(ordenables)}


def _base_ganadora_por_evento(filas_por_base, prioridad):
    """
    Decide de qué base sale la solución de cada evento: la de mayor prioridad
    entre las que lo tienen.

    No se mezclan fases de dos bases dentro de un mismo evento. Medido contra la
    base real: para la misma fase, seiscomp y seiscomp2 difieren en snr,
    magnitud de estación y QC, o sea que la base viva reprocesó. Armar una
    solución con filas de las dos sería construir algo que no existe en ninguna.
    """
    ganadora = {}
    for base, filas in filas_por_base.items():
        for fila in filas:
            evento = fila["id_evento"]
            actual = ganadora.get(evento)
            if actual is None or prioridad.get(base, 0) > prioridad.get(actual, 0):
                ganadora[evento] = base
    return ganadora


def _fusionar_eventos(filas_por_base, prioridad):
    """Une los eventos, dejando uno solo por evento y anotando su base."""
    ganadora = _base_ganadora_por_evento(filas_por_base, prioridad)
    orden = sorted(filas_por_base, key=lambda b: prioridad.get(b, 0))
    fusionados = []
    for base in orden:
        for fila in filas_por_base.get(base, []):
            if ganadora.get(fila["id_evento"]) != base:
                continue
            fila = dict(fila)
            fila["base_datos"] = base
            fusionados.append(fila)
    return fusionados


def _fusionar_fases(filas_por_base, prioridad):
    """
    Une las fases, dejando la solución de cada evento entera en una sola base.

    La clave de deduplicación incluye el azimut a propósito: hay 20 llegadas
    que comparten pick, fase y hora de llegada y solo se distinguen por el
    azimut, así que una clave sin él se comería una llegada real.
    """
    ganadora = _base_ganadora_por_evento(filas_por_base, prioridad)
    orden = sorted(filas_por_base, key=lambda b: prioridad.get(b, 0))
    vistas = set()
    fusionadas = []
    for base in orden:
        for fila in filas_por_base.get(base, []):
            if ganadora.get(fila["id_evento"]) != base:
                continue
            clave = (fila["id_evento"], fila["id_pick"], fila["fase"],
                     fila["llegada_us"], fila["azimut"])
            if clave in vistas:
                continue
            vistas.add(clave)
            fila = dict(fila)
            fila["base_datos"] = base
            fusionadas.append(fila)
    return fusionadas


def _aviso_cobertura(nombre, inicio, fin, cobertura):
    """
    Avisa si la ventana pedida no entra entera en lo que la base tiene.
    Exportar una parte sin decir nada es peor que no exportar.
    """
    if cobertura is None:
        return
    primero, ultimo = cobertura.get("desde"), cobertura.get("hasta")
    if primero is None or ultimo is None:
        return
    if primero > fin or ultimo < inicio:
        print("   [Aviso] La base %s tiene datos del %s al %s: la ventana"
              " pedida queda COMPLETAMENTE fuera."
              % (nombre, primero.date(), ultimo.date()))
    elif primero > inicio or ultimo < fin:
        print("   [Aviso] La base %s cubre del %s al %s, así que la ventana"
              " pedida sale incompleta."
              % (nombre, primero.date(), ultimo.date()))


def exportar_ventana(inicio, fin, salida=None, base=None,
                     solo_confirmados=True, reusar=False):
    """
    Consulta los eventos de la ventana y sus fases, y escribe los dos CSV.
    Devuelve un diccionario con las rutas y las cantidades de filas.

    Por defecto sale solo lo que un analista revisó (estado "confirmed"). Con
    solo_confirmados=False entran también las soluciones automáticas, que son
    muchas más pero no son eventos publicados.

    Con reusar=True, si esa ventana ya está exportada y completa, devuelve sus
    archivos sin consultar la base. El resultado trae "reusado": True y las
    cantidades en None, porque las filas no se contaron otra vez.
    """
    if med is not None:
        # Se arranca el cronómetro acá para incluir el import de psycopg2.
        med.arranque("consulta")

    # Cada exportación informa su propio avance; si el proceso se reusa (no es
    # el caso normal, el CLI siempre arranca de cero) se reinicia el umbral.
    prog.avance_reset()

    if salida is None:
        salida = ruta_datos("seiscomp_%s_%s.csv"
                            % (inicio.strftime(FORMATO), fin.strftime(FORMATO)))
    salida_fases = _ruta_fases(salida)
    marca = _ruta_completo(salida)

    if reusar and os.path.isfile(salida) and os.path.isfile(salida_fases) \
            and os.path.isfile(marca):
        print("   Ventana       : %s  ->  %s  (UTC)"
              % (inicio.strftime(FORMATO), fin.strftime(FORMATO)))
        print("   [Aviso] Se reusa la exportación existente; no se consulta"
              " la base.")
        prog.avance(1.0)
        return {
            "ruta": os.path.abspath(salida),
            "ruta_fases": os.path.abspath(salida_fases),
            "eventos": None,
            "fases": None,
            "reusado": True,
        }

    # Se borra la marca ANTES de exportar. Si esta corrida se corta, el archivo
    # puede quedar a medias y lo que no puede pasar es que la marca siga
    # diciendo que está completo: --reusar se llevaría la exportación
    # truncada como si fuera entera.
    try:
        os.remove(marca)
    except OSError:
        pass

    bases = _bases_a_consultar(base)
    n = max(1, len(bases))

    print("   Ventana       : %s  ->  %s  (UTC)"
          % (inicio.strftime(FORMATO), fin.strftime(FORMATO)))
    if len(bases) > 1:
        print("   Bases         : %s (se combinan)" % ", ".join(bases))
    else:
        config = configuracion(bases[0] if bases else None)
        print("   Base de datos : %s@%s/%s"
              % (config["user"], config["host"], config["database"]))
        print("   Definida en   : %s" % config["_origen"])

    eventos_por_base = {}
    coberturas = {}
    estimacion = {}
    for i, nombre in enumerate(bases):
        print("   Consultando %s..." % nombre)
        filas, cobertura, estimadas = _consultar_eventos_de_base(
            nombre, inicio, fin, solo_confirmados)
        _aviso_cobertura(nombre, inicio, fin, cobertura)
        eventos_por_base[nombre] = filas
        coberturas[nombre] = cobertura
        estimacion[nombre] = estimadas
        print("      %d eventos." % len(filas))
        # La consulta de eventos ocupa el primer 40 % del avance.
        prog.avance(0.40 * (i + 1) / n)

    # La base que llega más lejos en el tiempo es la que recibe datos, y es la
    # que gana cuando un evento está en más de una.
    prioridad = _prioridad_por_base(coberturas)
    if len(bases) > 1:
        ganadora = max(bases, key=lambda b: prioridad.get(b, 0))
        print("   Ante un evento presente en varias, manda: %s" % ganadora)

     # Quién se queda con cada evento. Con esto cada base escribe después solo
    # las fases de los eventos que le tocan, sin tener que guardar los
    # resultados de las dos al mismo tiempo.
    dueno = {}
    for nombre in sorted(bases, key=lambda b: prioridad.get(b, 0)):
        for fila in eventos_por_base[nombre]:
            dueno[fila["id_evento"]] = nombre

    # Estimación previa: más vale saberlo antes de esperar que después.
    estimado = sum(estimacion.values())
    print("   A exportar    : ~%s llegadas de estación%s"
          % ("{:,}".format(estimado).replace(",", "."),
             "" if solo_confirmados else " (sin filtrar por estado)"))
    if estimado > AVISO_DE_LOTES:
        print("   [Aviso] Es una ventana grande: puede tardar. Se escribe por"
              " lotes, así que la memoria se mantiene acotada.")

    filas = _fusionar_eventos(eventos_por_base, prioridad)
    for fila in filas:
        fila.setdefault("base_datos", "")
    _verificar_columnas(filas)
    _escribir_csv(salida, filas)
    prog.avance(0.50)

    # Las fases van por lotes. Lo único que se retiene es el resumen por evento.
    # El archivo se crea acá, con su encabezado, y después todas las bases
    # agregan. Si se esperara al primer lote para escribirlo, y la primera base
    # no trajera nada, el archivo quedaría con lo de una corrida anterior.
    _escribir_csv(salida_fases, [], CABECERA_FASES)
    resumen_por_evento = {}
    total_fases = 0
    for i, nombre in enumerate(bases):
        print("   Escribiendo fases de %s..." % nombre)
        esperado = estimacion.get(nombre)

        def _avance_fases(escritas, esperado=esperado, i=i):
            # Dentro de la base se avanza según la estimación; si no hay
            # estimación (o es 0) se deja el sub-bloque a media asta y se
            # completa recién al terminar la base.
            frac = min(1.0, escritas / esperado) if esperado else 0.5
            prog.avance(0.50 + 0.50 * ((i + frac) / n))

        total = _escribir_fases_de_base(
            nombre, inicio, fin, solo_confirmados, dueno, salida_fases,
            resumen_por_evento, esperado=esperado, progreso=_avance_fases)
        print("      %d llegadas." % total)
        total_fases += total
        # Pase lo que pase con la estimación, la base cerrada avanza su bloque.
        prog.avance(0.50 + 0.50 * ((i + 1) / n))
    _medir("escritura_fin")

    resumen = _resumen_desde_mapa(resumen_por_evento)

    # La marca va al final, después de escribir las fases: es lo último que se
    # hace, y es lo que dice que no quedó nada a medias.
    _escribir_marca(marca, inicio, fin, len(filas), total_fases, bases)
    prog.avance(1.0)

    return {
        "ruta": os.path.abspath(salida),
        "eventos": len(filas),
        "ruta_fases": os.path.abspath(salida_fases),
        "fases": total_fases,
        "resumen_fases": resumen,
        "bases": bases,
        "eventos_por_base": {b: len(eventos_por_base.get(b, [])) for b in bases},
        "estimado": estimado,
        "reusado": False,
    }



# ---------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------
def main():
    argumentos = sys.argv[1:]

    if argumentos and argumentos[0] in ("-h", "--help", "--ayuda"):
        print(__doc__)
        return 0

    # --base va aparte porque no es parte de la ventana ni del archivo de salida.
    # Por defecto se combinan todas las bases de SeisComp del servidor: la base
    # grande tiene el histórico y la chica el tiempo real, y usar una sola deja
    # huecos en silencio.
    base = "todas"
    solo_confirmados = True
    sugerencia = None
    reusar = False
    resto = []
    i = 0
    while i < len(argumentos):
        if argumentos[i] == "--base":
            if i + 1 >= len(argumentos):
                print("[X] --base necesita el nombre de la base, o 'todas'.")
                return 2
            base = argumentos[i + 1]
            i += 2
            continue
        if argumentos[i] == "--todos":
            # Saca también las soluciones automáticas, que no son eventos
            # revisados por un analista. Son muchas más filas.
            solo_confirmados = False
            i += 1
            continue
        if argumentos[i] == "--sugerencia":
            # Un período cualquiera para dejar escrito en la pregunta. No obliga
            # a exportar esa ventana: la pregunta sigue abierta y se puede
            # escribir otra.
            if i + 2 >= len(argumentos):
                print("[X] --sugerencia necesita inicio y término"
                      " (AAAAMMDDHHMMSS).")
                return 2
            try:
                desde = datetime.strptime(argumentos[i + 1], FORMATO)
                hasta = datetime.strptime(argumentos[i + 2], FORMATO)
            except ValueError:
                print("[X] La sugerencia debe ir en formato AAAAMMDDHHMMSS.")
                return 2
            if hasta <= desde:
                print("[X] El término de la sugerencia debe ser posterior"
                      " al inicio.")
                return 2
            sugerencia = (desde, hasta)
            i += 3
            continue
        if argumentos[i] == "--reusar":
            reusar = True
            i += 1
            continue
        resto.append(argumentos[i])
        i += 1
    argumentos = resto

    salida = None
    if len(argumentos) >= 2:
        try:
            inicio = datetime.strptime(argumentos[0], FORMATO)
            fin = datetime.strptime(argumentos[1], FORMATO)
        except ValueError:
            print("[X] Inicio y término deben ir en formato AAAAMMDDHHMMSS.")
            return 2
        if fin <= inicio:
            print("[X] El término debe ser posterior al inicio.")
            return 2
        if len(argumentos) > 2:
            salida = argumentos[2]
        if sugerencia:
            # Ganó la ventana escrita: es la que se exporta. Se dice, para que
            # no parezca que la sugerencia se aplicó igual.
            print("[Aviso] Hay ventana escrita y sugerencia; se usa la"
                  " escrita (%s - %s)." % (inicio.strftime(FORMATO),
                                          fin.strftime(FORMATO)))
    elif argumentos:
        print("[X] Indique inicio y término, o ninguno para que se los pregunte.")
        print("    Uso: %s [<inicio> <fin> [salida.csv]] [--base <nombre>]"
              " [--sugerencia <inicio> <fin>] [--reusar]"
              % os.path.basename(__file__))
        return 2
    else:
        inicio, fin = _preguntar_ventana(sugerencia)

    print()
    try:
        resultado = exportar_ventana(inicio, fin, salida, base,
                                    solo_confirmados, reusar)
    except FaltanParametros as e:
        print("[X] %s" % e)
        return 2
    except Exception as e:
        print("[X] Error al exportar los eventos: %s" % e)
        return 1

    if resultado.get("reusado"):
        print("[OK] Exportación existente reutilizada.")
        print("     Archivo: %s" % resultado["ruta"])
        print("     Archivo: %s" % resultado["ruta_fases"])
        return 0

    total = resultado["eventos"]
    total_fases = resultado["fases"]
    print()
    if total:
        print("[OK] %d eventos exportados." % total)
    else:
        print("[OK] Exportación finalizada, pero ningún evento cae en la ventana.")
    print("     Archivo: %s" % resultado["ruta"])

    if total_fases:
        print("[OK] %d fases de estación exportadas." % total_fases)
    else:
        print("[Aviso] No se encontraron lecturas de estación en la ventana.")
    print("     Archivo: %s" % resultado["ruta_fases"])

    por_base = resultado.get("eventos_por_base") or {}
    if len(por_base) > 1:
        print()
        print("     Eventos por base (antes de fusionar):")
        for nombre, n in sorted(por_base.items()):
            print("       %-12s %6d" % (nombre, n))
        print("     Total sin fusionar: %d -> %d en el archivo."
              % (sum(por_base.values()), total))

    r = resultado["resumen_fases"]
    print()
    print("     Con magnitud de estación: %d de %d (%.0f%%)"
          % (r["con_magnitud"], total_fases,
             100.0 * r["con_magnitud"] / total_fases if total_fases else 0))
    print("     De las que la tienen, con residuo: %d" % r["con_residuo"])

    if r["fuera_de_rango"] or r["negativas"]:
        print()
        if r["fuera_de_rango"]:
            print("[Aviso] %d magnitudes están fuera del rango creíble (%.1f a %.1f)."
                  % (r["fuera_de_rango"], RANGO_MAG_ESTACION[0],
                     RANGO_MAG_ESTACION[1]))
        if r["negativas"]:
            print("[Aviso] %d magnitudes de estación son negativas." % r["negativas"])
        print("        Están en el CSV sin filtrar; conviene revisarlas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
