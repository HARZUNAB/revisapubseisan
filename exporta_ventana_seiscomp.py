#!/usr/bin/env python3
"""Exporta a CSV las soluciones preferidas de SeisComp6 de una ventana de tiempo.

Consulta los eventos cuyo origen preferido cae dentro de la ventana indicada y
escribe tres CSV:

  * <salida>.csv          una fila por evento, con la solución preferida.
  * <salida>_fases.csv    una fila por llegada de estación de esa solución
                          preferida: fase y hora, geometría, si fue usada, la
                          magnitud que calculó esa estación, su tipo, el
                          residuo, el control de calidad, los datos de
                          inventario y la procedencia del pick (manual o
                          automático, con autor, agencia y método). Se asocia
                          con el evento por id_evento. Si la estación no
                          calculó magnitud para esa fase, la fila sigue
                          apareciendo igual, con la celda vacía y
                          tiene_magnitud en "No". Nunca se escribe 0 en una
                          celda sin dato, porque un cero falso se cuela en los
                          promedios sin avisar.
  * <salida>_no_picadas.csv  una fila por estación del inventario que quedó
                          dentro del radio del evento y no fue picada: su
                          distancia al hipocentro, sus datos de inventario y
                          cuántas otras veces picó cerca en el tiempo.

Los dos primeros archivos terminan en una columna base_datos, que dice de qué
base salió cada fila. El de no picadas no la lleva: el inventario no es de una
base en particular.

ESTACIONES NO PICADAS

El tercer archivo responde a la pregunta de por qué una estación cercana no
aparece en la solución. Sale del INVENTARIO y no de las fases, porque una
estación sin arribos asociados no tiene fila de llegada: el INNER JOIN de las
fases descarta justamente lo que acá se busca.

Importante, porque el nombre puede hacer pensar otra cosa: esto NO dice que la
estación no haya grabado. La base de metadatos de SeisComp no registra qué
estaciones tienen formas de onda de cada evento; eso vive en el archivo de
ondas. Lo que el archivo responde es qué estaciones tenían inventario vigente
dentro del radio y no tienen arrivals/picks asociados al ORIGEN PREFERIDO del
evento. Por eso la interfaz las llama "sin arribos" y no "no grabó".

La cadena de inventario se valida entera por evento: red, estación, sensor
location y stream tienen que estar vigentes en la hora del evento. Una estación
sin sensorlocation/stream vigente no se lista, porque no hay forma de sostener
que estuviera operativa. Las columnas loc_ref/cha_ref son el stream de
REFERENCIA (el de época más reciente entre los vigentes) y streams_vigentes
cuenta cuántos había; no son el único stream disponible.

Además se acota a los BINDINGS: solo las estaciones que SeisComp tiene
configurado procesar (tabla configstation, módulos habilitados). Puede haber
dataless cargado sin binding creado, y esas estaciones no se listan porque
SeisComp no las trabaja. El binding es la config ACTUAL y no tiene épocas, así
que para eventos históricos es una aproximación (el inventario sí resuelve la
vigencia de la estación por evento). Si no se encuentran bindings, no se filtra.

La columna actividad_ventana cuenta cuántos otros eventos de la ventana tienen
picks de esa estación dentro de ±ACTIVIDAD_HORAS. Es un indicador indirecto de
operación: en cero la estación puede estar caída, no interesarle el evento o
simplemente nadie la revisó; mayor que cero indica que estaba operando y no
tiene arribos en ESTE evento, que es el caso a revisar. El radio sale de
--radio-km (300 km por defecto) y la ventana de --actividad-h (24 horas por
defecto).

Este radio es SOLO para las estaciones sin arribos de los eventos de SeisComp:
no tiene nada que ver con los catálogos de Seisan ni de eventquery, que no
arman esta lista. El exportador también ofrece estimar_no_picadas(), que
estima cuántas filas y cuántos MB tendría la lista antes de calcularla, para
avisar cuando la ventana es grande.

Los campos waveform_status, availability_source, cobertura_desde y
cobertura_hasta quedan previstos para cuando se consulte disponibilidad real
(SDS, scardac/DataAvailability o FDSN Availability). Hoy waveform_status vale
NO_CONSULTADO y los otros van vacíos: no se afirma nada sobre las formas de
onda.

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

Con --reusar, si los tres archivos de esa ventana ya existen y la exportación
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
se exportó. Para saber si se puede, no alcanza con que los CSV existan: una
exportación que se cortó a mitad de camino deja el archivo de fases a medias y
se vería como una ventana más corta, sin ningún aviso. Por eso, al terminar
bien, se escribe una tercera archivo al lado:

    <salida>.csv.completo

que es la marca de que aquella exportación llegó hasta el final. --reusar solo
reutiliza los CSV si la marca está; si no está, los vuelve a exportar. La marca
se borra al empezar una exportación y se vuelve a escribir al terminarla, así
que un intento fallido nunca deja decir que algo se completó cuando no.

--reusar además exige que estén los TRES CSV. Una ventana exportada antes de que
existiera el de no picadas se vuelve a exportar aunque tenga la marca, porque sin
ese archivo la solapa de estaciones del revisor no tiene qué mostrar.

Este script es de SOLO LECTURA: no modifica la base de datos bajo ninguna
circunstancia. Lo único que envía al servidor es "SET TIME ZONE 'UTC'" (un
ajuste de sesión que no altera datos y se descarta al cerrar la conexión) y
las consultas SELECT. No hay INSERT, UPDATE, DELETE ni sentencias DDL, no se
crean índices y no se llama a commit(), por lo que la conexión cierra siempre
en rollback.
"""
import csv
import decimal
import math
import os
import re
import sys
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta

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

# Radio, en kilómetros, para la búsqueda de estaciones que NO fueron picadas en
# un evento. Es el número que hace acotable el análisis: sin radio salen todas
# las estaciones del inventario, que no es lo que interesa. 300 km cubre de
# sobra la red cercana de un evento chileno, y con --radio-km se cambia sin
# tocar el código. El revisor además puede ampliar el radio por evento contra
# la base sin re-exportar, así que este corte solo acota el tamaño del archivo.
RADIO_ESTACIONES_KM = 300.0

# Qué tan lejos en el tiempo se busca que una estación haya picado otro evento
# para considerarla "activa". No es lo mismo que estar en el inventario: una
# estación puede tener su época vigente y no haber grabado nunca. La señal de
# que hubo datos fluyendo es que haya picado algo cerca en el tiempo. Con 24 h
# una estación que operó ese día cuenta, y una que solo trabajó a principios de
# mes no aparece como disponible para un evento del 28.
ACTIVIDAD_HORAS = 24.0

# Las mismas 14 columnas, en el mismo orden, que consulta_eventosSC.py, más
# base_datos al final: de qué base salió la fila. Con varias bases en juego no
# hay forma de trazar un valor sospechoso hasta su origen si esto no queda
# escrito en el archivo.
CABECERA = [
    "id_evento", "id_origen", "ot_utc", "magnitud", "tipo_magnitud", "fases",
    "rms", "azgap", "latitud", "longitud", "profundidad_km", "agencia",
    "operador", "region", "estatus", "base_datos",
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
    TRIM(po_o.m_publicid::text) AS id_origen,
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
    # Procedencia del pick: manual/automatic, autor, agencia y método. Permite
    # saber si la llegada que entró a la solución la picó un analista o un
    # autopicker, y con qué método.
    "modo_pick", "pick_autor", "pick_agencia", "pick_metodo",
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
    -- Procedencia del pick: si lo hizo un analista (manual) o un autopicker
    -- (automatic), quién/agencia y con qué método. En la base, un pick manual
    -- trae el nombre del analista en m_creationinfo_author y el método vacío;
    -- uno automático trae el daemon (scautopic...) y el método (p. ej. AIC).
    p.m_evaluationmode                   AS modo_pick,
    p.m_creationinfo_author              AS pick_autor,
    p.m_creationinfo_agencyid            AS pick_agencia,
    p.m_methodid                         AS pick_metodo,
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
# Estaciones SIN ARRIBOS asociados
# ---------------------------------------------------------------------------
# Esta es la consulta al revés: en vez de las estaciones que tienen arribos, las
# que estaban en el inventario y no los tienen. Sale del inventario, no de las
# fases, porque una estación sin arribos no aparece en la tabla de llegadas: el
# INNER JOIN de CONSULTA_FASES_SQL descarta justo lo que se busca acá.
#
# OJO, y es lo que hay que tener claro al leer el archivo: el inventario dice
# que la estación estaba CONFIGURADA, no que grabara este evento. La base de
# metadatos de SeisComp no registra qué estaciones tienen formas de onda de un
# evento; eso vive en el archivo de ondas. Por eso el archivo no dice "no grabó"
# sino "sin arribos": la diferencia entre una estación caída y una que el
# analista no revisó la resuelve quien mira la señal.
#
# La vigencia se trae entera (m_start/m_end) y se resuelve por evento en Python,
# no en el SELECT: una estación puede tener varias épocas y cuál corresponde
# depende de la hora de cada evento, así que el filtro va por evento y no por
# ventana. Por eso el WHERE solo acota la ventana de forma gruesa, con el epoch
# de estación que se solapa con ella.
#
# La cadena se valida completa: red, estación, sensor location y stream. Los
# INNER JOIN sobre sensorlocation y stream son a propósito: una estación sin
# stream definido no se puede validar como operativa y no se lista. Un mismo
# código de estación puede tener varias sensor locations y cada una varios
# streams, así que la consulta devuelve una fila por stream y el agrupamiento
# por estación se hace en Python.
#
# Sin coordenadas no hay distancia, así que una estación sin latitud o sin
# longitud no sirve para este archivo y se descarta abajo. Sigue apareciendo en
# el de fases, porque ahí el inventario solo enriquece.
CONSULTA_INVENTARIO_SQL = """
SELECT
    net.m_code       AS red,
    st.m_code        AS estacion,
    st.m_start       AS epoca_inicio,
    st.m_end         AS epoca_fin,
    st.m_latitude    AS latitud,
    st.m_longitude   AS longitud,
    st.m_elevation   AS elevacion,
    st.m_place       AS lugar,
    st.m_country     AS pais,
    net.m_start      AS red_inicio,
    net.m_end        AS red_fin,
    loc.m_code       AS loc,
    loc.m_start      AS loc_inicio,
    loc.m_end        AS loc_fin,
    str.m_code       AS cha,
    str.m_start      AS cha_inicio,
    str.m_end        AS cha_fin
FROM network net
INNER JOIN station st ON st._parent_oid = net._oid
INNER JOIN sensorlocation loc ON loc._parent_oid = st._oid
INNER JOIN stream str ON str._parent_oid = loc._oid
WHERE st.m_latitude IS NOT NULL
  AND st.m_longitude IS NOT NULL
  AND st.m_start <= %s
  AND (st.m_end IS NULL OR st.m_end >= %s)
ORDER BY net.m_code, st.m_code, st.m_start, loc.m_start, str.m_start
"""

# Bindings habilitados: las estaciones que SeisComp está CONFIGURADO a
# procesar (los "trunk" que mencionan los etc/init/*.py son el proxy de config;
# por eso no se fija el nombre del módulo). Es un subconjunto del inventario:
# puede haber dataless cargado sin binding creado. Lo usa el listado de "sin
# arribos" para no listar estaciones que SeisComp no trabaja.
CONSULTA_BINDINGS_SQL = """
SELECT DISTINCT
    TRIM(c.m_networkcode) AS red,
    TRIM(c.m_stationcode) AS estacion
FROM configstation c
INNER JOIN configmodule m ON m._oid = c._parent_oid
WHERE c.m_enabled
  AND m.m_enabled
"""

# Actividad de una estación alrededor de un instante: los eventos (orígenes
# preferidos) que picó dentro de ±horas. Misma cadena que las fases (evento ->
# origen preferido -> arrival -> pick), pero acotada al tramo temporal y sin
# columnas de más. DISTINCT porque una estación puede tener varias llegadas en
# el mismo origen y lo que se cuenta son eventos, no llegadas. La usa el
# revisor cuando amplía el radio de un evento contra la base sin re-exportar.
CONSULTA_ACTIVIDAD_SQL = """
SELECT DISTINCT
    p.m_waveformID_networkCode           AS red,
    p.m_waveformID_stationCode           AS estacion,
    o.m_time_value                       AS instante
FROM event e
INNER JOIN publicobject po_e ON po_e._oid = e._oid
INNER JOIN publicobject po_o ON po_o.m_publicid = e.m_preferredoriginid
INNER JOIN origin o ON o._oid = po_o._oid
INNER JOIN arrival a ON a._parent_oid = o._oid
INNER JOIN publicobject po_p ON po_p.m_publicid = a.m_pickID
INNER JOIN pick p ON p._oid = po_p._oid
WHERE o.m_time_value >= %s
  AND o.m_time_value <= %s
  AND (%s::text IS NULL OR o.m_evaluationstatus = %s::text)
ORDER BY red, estacion, instante
"""

# Valor por defecto de waveform_status mientras no se consulte una fuente de
# disponibilidad. Es una cadena explícita y no una celda vacía a propósito:
# vacío se lee como "no se sabe", y acá lo correcto es "no se consultó".
ESTADO_SIN_CONSULTAR = "NO_CONSULTADO"

CABECERA_NO_PICADAS = [
    # Con qué evento se asocia la fila, igual que en el archivo de fases: así
    # el revisor puede leer solo el tramo de este evento del archivo entero.
    "id_evento",
    # Origen preferido con el que se clasificaron los arribos y las estaciones.
    # Es la referencia contra la que se mide "sin arribos".
    "id_origen",
    # Qué estación es
    "red", "estacion",
    # Stream de REFERENCIA: el de época más reciente entre los vigentes. No es
    # el único stream disponible; para eso está streams_vigentes.
    "loc_ref", "cha_ref", "streams_vigentes",
    # Distancia al hipocentro en kilómetros. Es la columna por la que se ordena
    # la solapa de la interfaz: lo interesante es lo que quedó cerca.
    "distancia_km",
    # Inventario de esa estación en la época del evento
    "est_lat", "est_lon", "est_elev", "est_lugar", "est_pais",
    # Con qué radio se generó esta lista
    "radio_km",
    # Cuántos OTROS eventos de la ventana tienen picks de esta estación dentro
    # de ±ACTIVIDAD_HORAS. Es un indicador INDIRECTO de operación: si está en
    # cero, la estación puede estar caída, no interesarle el evento, o
    # simplemente nadie la revisó. Si es mayor que cero, estaba operando y no
    # tiene arribos en ESTE evento, que es exactamente el caso a revisar. No
    # demuestra que haya grabado.
    "actividad_ventana",
    # Disponibilidad de formas de onda. Hoy no se consulta ninguna fuente: va
    # NO_CONSULTADO y los demás vacíos, para que el archivo ya tenga el lugar
    # cuando se integren SDS, scardac/DataAvailability o FDSN Availability.
    "waveform_status", "availability_source", "cobertura_desde",
    "cobertura_hasta",
]



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


def _ruta_no_picadas(salida_eventos):
    """Deriva el nombre del CSV de estaciones no picadas desde el de eventos."""
    base, extension = os.path.splitext(salida_eventos)
    return "%s_no_picadas%s" % (base, extension or ".csv")


def _ruta_completo(salida_eventos):
    """
    Nombre de la marca que dice que aquella exportación terminó.

    Va pegada al nombre del CSV de eventos y no al del de fases, porque es la
    salida que define a la exportación: es la que se le pasa al revisor, y la
    que el lanzador usa para decidir si hay algo que reusar.
    """
    return "%s.completo" % salida_eventos


def _escribir_marca(ruta, inicio, fin, eventos, fases, no_picadas, radio_km,
                    bases, descartadas=0):
    """
    Deja escrito que la exportación de esa ventana llegó hasta el final.

    Va con la cantidad de filas y con las bases consultadas porque, cuando más
    adelante alguien mire la carpeta, el archivo solo no dice si esos datos
    corresponden a lo que el catálogo pedía o a otra ventana.

    La cantidad de no picadas también queda escrita, junto con el radio con el
    que se calcularon: sin eso, dos archivos con el mismo nombre no se pueden
    comparar y no se sabe con qué criterio se armó la lista de estaciones. Las
    descartadas por falta de sensorlocation/stream se anotan aparte porque son
    justamente las que no llegaron al archivo y sin ese número no se sabe si
    faltan por criterio o por inventario incompleto.
    """
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("ventana %s %s | eventos %d | fases %d | no_picadas %d"
                " (radio %.0f km) | descartadas_sin_stream %d | bases %s | %s"
                " UTC\n"
                % (inicio.strftime(FORMATO), fin.strftime(FORMATO),
                   eventos, fases, no_picadas, radio_km, descartadas,
                   ",".join(bases),
                   datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")))


def _radio_de_la_marca(ruta):
    """
    El radio con el que se exportó, leído de la marca. None si no se puede.

    Hace falta para el reuso: si el usuario pide un radio distinto del que tiene
    la exportación en disco, no se puede reusar, porque el corte de estaciones
    estaría calculado con el otro radio.
    """
    try:
        with open(ruta, encoding="utf-8") as f:
            texto = f.read()
    except OSError:
        return None
    coincidencia = re.search(r"radio\s+(\d+(?:\.\d+)?)\s*km", texto)
    if coincidencia is None:
        return None
    try:
        return float(coincidencia.group(1))
    except ValueError:
        return None


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

# Cantidad de eventos confirmados de la ventana. Es liviana (no trae las filas)
# y se usa para escalar la estimación muestreada de no picadas.
CONSULTA_EVENTOS_VENTANA_SQL = """
SELECT count(*) AS total
FROM event e
INNER JOIN publicobject po ON po.m_publicid = e.m_preferredoriginid
INNER JOIN origin o ON o._oid = po._oid
WHERE o.m_time_value >= %s
  AND o.m_time_value <= %s
  AND (%s::text IS NULL OR o.m_evaluationstatus = %s::text)
"""

# Estimación de cuántas filas tendría el CSV de no picadas, sin calcularlo:
# cuenta los pares (evento, estación) dentro del radio sobre una MUESTRA de
# eventos y después se escala por el total. Medido: la muestra de 200 tarda
# centésimas y estima con error de pocos puntos, mientras el conteo exacto de
# una ventana histórica tarda decenas de segundos. El LIMIT va en la muestra.
CONSULTA_ESTIMACION_NO_PICADAS_SQL = """
WITH ev AS (
    SELECT o.m_latitude_value  AS lat,
           o.m_longitude_value AS lon
    FROM event e
    INNER JOIN publicobject po ON po.m_publicid = e.m_preferredoriginid
    INNER JOIN origin o ON o._oid = po._oid
    WHERE o.m_time_value >= %s
      AND o.m_time_value <= %s
      AND (%s::text IS NULL OR o.m_evaluationstatus = %s::text)
    LIMIT %s
),
st AS (
    SELECT s.m_latitude  AS lat,
           s.m_longitude AS lon
    FROM network net
    INNER JOIN station s ON s._parent_oid = net._oid
    WHERE s.m_latitude IS NOT NULL
      AND s.m_longitude IS NOT NULL
)
SELECT (SELECT count(*) FROM ev) AS muestra,
       count(*)                   AS pares
FROM ev, st
WHERE 6371.0 * 2 * asin(sqrt(
        power(sin(radians(st.lat - ev.lat) / 2), 2)
        + cos(radians(ev.lat)) * cos(radians(st.lat))
          * power(sin(radians(st.lon - ev.lon) / 2), 2))) <= %s
"""

# Tamaño aproximado de una fila del CSV de no picadas, medido. Traduce la
# estimación de filas a megabytes para el aviso previo.
NO_PICADAS_BYTES_FILA = 154
# A partir de esta estimación (en MB) la interfaz pide confirmación antes de
# exportar. Un mes de datos a 300 km ronda los 20 MB, así que 200 avisa recién
# en ventanas grandes (varios meses).
AVISO_NO_PICADAS_MB = 200.0


# ---------------------------------------------------------------------------
# Estaciones no picadas: la lógica, sin base de datos
# ---------------------------------------------------------------------------
# Todo lo de esta sección es puro: recibe datos y devuelve filas, sin conexión
# ni pantalla. Es lo que hace que se pueda probar el radio, la vigencia y la
# cuenta de actividad sin tener una base a mano.
RADIO_TIERRA_KM = 110.574   # Un grado de latitud, medido, no aproximado a 111
RADIO_TIERRA_LON_KM = 111.320  # Un grado de longitud en el ecuador

# Lado de las celdas del índice de estaciones, en grados. Con radio de 300 km se
# repasa un radio de 3x3 a 7x7 celdas, así que se entra a menos celdas de las
# que hay, y queda holgura de sobra para no perder ninguna por redondeo.
GRADO_CELDA = 1.0


def _distancia_km(lat1, lon1, lat2, lon2):
    """
    Distancia entre dos puntos de la Tierra en kilómetros.

    Es la fórmula de haversine sobre una esfera de radio 6371.0088 km. A escala
    de un radio de unos cientos de kilómetros el error contra el elipsoide es
    de metro y medio, muy por debajo del redondeo a un decimal con el que se
    escribe la columna, así que no vale la pena usar la fórmula de Vincenty: es
    mucho más código para un resultado que no se distingue en el archivo.

    Se usa 'latitud' para el Este/Oeste. Es aproximada (el radio de la Tierra
    crece con la latitud), y se elige esa a propósito porque en un radio de
    300 km el error también es de metro y medio. Importa que la dirección sea
    la misma para todos los puntos, que es lo que acá se cumple.
    """
    radio = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2.0) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2)
    return 2.0 * radio * math.asin(min(1.0, math.sqrt(a)))


def _celda_grado(latitud, longitud):
    """
    La celda del índice en la que cae un punto.

    No se llama _celda como la otra de este módulo, que convierte un valor de la
    base para escribirlo en el CSV: son cosas distintas y el mismo nombre haría
    pensar que una usa a la otra.
    """
    return (int(math.floor(latitud / GRADO_CELDA)),
            int(math.floor(longitud / GRADO_CELDA)))


def _indice_por_celda(filas_inventario, bindings=None):
    """
    Agrupa el inventario por celda para no medir contra todas las estaciones.

    Sin esto, con 70.000 eventos y 1.500 estaciones hay 100 millones de
    distancias, y la exportación de un año se pasa la vida ahí. Con el índice
    se mide solo contra las estaciones de las celdas que tocan el radio.

    Cada fila del inventario es un STREAM, no una estación: la consulta valida
    la cadena entera (red, estación, sensor location, stream) y una estación
    puede tener varios. Por eso se guardan todas las épocas de cada nivel y el
    par loc/cha, y el agrupamiento por estación se hace después.

    'bindings', si viene, es el conjunto de (red, estación) que SeisComp tiene
    configurado a procesar; las demás filas del inventario se descartan. Es lo
    que hace que el listado sea "estaciones que SeisComp trabaja", no todo el
    dataless cargado.

    La deduplicación va en un conjunto aparte y no sobre el diccionario: el
    diccionario está indexado por celda, así que preguntar ahí si un stream ya
    estaba nunca va a dar True, porque una celda es un par de coordenadas y no
    tiene nada que ver con un stream. Con varias bases el inventario viene
    repetido y cada copia de más contaría como un stream más.
    """
    indice = {}
    vistas = set()
    for fila in filas_inventario:
        red = fila.get("red")
        estacion = fila.get("estacion")
        if not red or not estacion:
            continue
        if bindings is not None and (red, estacion) not in bindings:
            continue
        clave = (red, estacion, fila.get("loc"), fila.get("cha"),
                 fila.get("epoca_inicio"), fila.get("loc_inicio"),
                 fila.get("cha_inicio"))
        if clave in vistas:
            continue
        vistas.add(clave)
        try:
            latitud = float(fila.get("latitud"))
            longitud = float(fila.get("longitud"))
        except (TypeError, ValueError):
            continue
        if not _coordenada_valida(latitud, longitud):
            continue
        celda = _celda_grado(latitud, longitud)
        indice.setdefault(celda, []).append({
            "red": red,
            "estacion": estacion,
            "epoca_inicio": fila.get("epoca_inicio"),
            "epoca_fin": fila.get("epoca_fin"),
            "red_inicio": fila.get("red_inicio"),
            "red_fin": fila.get("red_fin"),
            "loc": fila.get("loc"),
            "loc_inicio": fila.get("loc_inicio"),
            "loc_fin": fila.get("loc_fin"),
            "cha": fila.get("cha"),
            "cha_inicio": fila.get("cha_inicio"),
            "cha_fin": fila.get("cha_fin"),
            "latitud": latitud,
            "longitud": longitud,
            "elevacion": fila.get("elevacion"),
            "lugar": fila.get("lugar"),
            "pais": fila.get("pais"),
        })
    return indice


def _coordenada_valida(latitud, longitud):
    """
    Si el par sirve para medir una distancia en el globo.

    También descarta None: el 0,0 es el valor con el que la base representa un
    NULL en un campo de coordenadas, y una comparación con None levanta
    TypeError, así que la comprobación tiene que ir antes que la aritmética.
    """
    if latitud is None or longitud is None:
        return False
    if not (-90.0 <= latitud <= 90.0) or not (-180.0 <= longitud <= 180.0):
        return False
    return not (latitud == 0.0 and longitud == 0.0)


def _estaciones_en_el_radio(indice, latitud, longitud, radio_km):
    """
    Las estaciones del inventario que podrían estar dentro del radio.

    Devuelve candidatos por celda, sin medir: el filtro por distancia exacta,
    vigencia y picadas lo hace _no_picadas_de_evento. Acá solo se agranda el
    radio una celda a cada lado para no perder ninguna por el redondeo del
    índice.

    Con radio_km=None ("sin límite") devuelve TODOS los registros del índice,
    sin acotar por celdas: es el caso de la opción «Todo» del revisor.
    """
    if radio_km is None:
        todos = []
        for celda in indice.values():
            todos.extend(celda)
        return todos
    desde_lat = latitud - radio_km / RADIO_TIERRA_KM - GRADO_CELDA
    hasta_lat = latitud + radio_km / RADIO_TIERRA_KM + GRADO_CELDA
    coseno = max(0.05, math.cos(math.radians(latitud)))
    medio_lon = radio_km / (RADIO_TIERRA_LON_KM * coseno) + GRADO_CELDA
    desde_lon = longitud - medio_lon
    hasta_lon = longitud + medio_lon
    candidatas = []
    celdas = [_celda_grado(desde_lat, desde_lon),
              _celda_grado(hasta_lat, hasta_lon)]
    for i in range(celdas[0][0], celdas[1][0] + 1):
        for j in range(celdas[0][1], celdas[1][1] + 1):
            candidatas.extend(indice.get((i, j), ()))
    return candidatas


def _vigente(inicio, fin, instante):
    """
    Si una época cubre el instante.

    Inicio o fin en None significan "sin límite" en ese extremo: en el
    inventario de SeisComp una época abierta deja el fin en NULL.
    """
    if inicio is not None and inicio > instante:
        return False
    if fin is not None and fin < instante:
        return False
    return True


def _stream_valido(registros, instante):
    """
    El stream de referencia vigente para una estación, y cuántos hay.

    La cadena se valida completa: red, estación, sensor location y stream. Una
    estación con inventario de estación vigente pero sin ningún sensor
    location/stream vigente no es una candidata: no hay forma de sostener que
    estuviera operativa. Si no hay ningún stream válido devuelve None.

    Devuelve (registro, cantidad) donde 'registro' es el de época de estación
    más reciente entre los vigentes (desempate por sensor location y stream),
    que es el que se usa como referencia. 'cantidad' cuenta TODOS los streams
    vigentes: es lo que deja claro que el de referencia no es el único.
    """
    vigentes = [r for r in registros
                if _vigente(r["red_inicio"], r["red_fin"], instante)
                and _vigente(r["epoca_inicio"], r["epoca_fin"], instante)
                and _vigente(r["loc_inicio"], r["loc_fin"], instante)
                and _vigente(r["cha_inicio"], r["cha_fin"], instante)]
    if not vigentes:
        return None, 0
    minimo = datetime.min
    vigentes.sort(key=lambda r: (r["epoca_inicio"] or minimo,
                                 r["loc_inicio"] or minimo,
                                 r["cha_inicio"] or minimo))
    return vigentes[-1], len(vigentes)


def _no_picadas_de_evento(instante, id_evento, id_origen, latitud, longitud,
                          indice, picadas, actividad,
                          radio_km=RADIO_ESTACIONES_KM,
                          actividad_horas=ACTIVIDAD_HORAS):
    """
    Las estaciones con inventario vigente que no tienen arribos asociados.

    'picadas' son las claves (red, estación) con al menos una llegada en este
    evento, e 'id_origen' es el origen preferido usado como referencia.
    'actividad' mapea cada estación a las horas de los otros eventos que la
    picaron. Devuelve (filas, descartadas): las filas listas para el CSV,
    ordenadas por distancia, y cuántas estaciones quedaron afuera por no tener
    sensorlocation/stream vigente.

    Lo que NO hace, y hay que decirlo claro porque el nombre invita a
    entenderlo: no comprueba que la estación haya grabado. La base de metadatos
    no tiene esa información; sale del inventario y de la actividad. Por eso la
    columna de actividad va en la fila: es un indicador indirecto, no una prueba.

    Con radio_km=None no hay corte de distancia: entran todas las estaciones del
    inventario con la cadena de épocas vigente a la hora del evento (la opción
    «Todo (sin límite)» del revisor). La fila queda con radio_km=None.
    """
    if not _coordenada_valida(latitud, longitud) or (
            radio_km is not None and radio_km <= 0):
        return [], 0
    tolerancia = timedelta(hours=actividad_horas)
    filas = []
    descartadas = 0
    # Las candidatas traen varias filas por estación (una por stream y época);
    # se resuelven por evento, así que primero se agrupan por código.
    por_codigo = {}
    for estacion in _estaciones_en_el_radio(indice, latitud, longitud, radio_km):
        por_codigo.setdefault((estacion["red"], estacion["estacion"]),
                              []).append(estacion)
    for codigo, registros in por_codigo.items():
        if codigo in picadas:
            continue
        vigente, cantidad = _stream_valido(registros, instante)
        if vigente is None:
            descartadas += 1
            continue
        distancia = _distancia_km(latitud, longitud,
                                  vigente["latitud"], vigente["longitud"])
        if radio_km is not None and distancia > radio_km:
            continue
        horas = actividad.get(codigo)
        if not horas:
            cercana = 0
        else:
            # La lista de horas está ordenada, así que lo que cae dentro de la
            # tolerancia es un tramo y sale de dos búsquedas.
            desde = bisect_left(horas, instante - tolerancia)
            hasta = bisect_right(horas, instante + tolerancia)
            cercana = hasta - desde
        filas.append({
            "id_evento": id_evento,
            "id_origen": id_origen,
            "red": vigente["red"],
            "estacion": vigente["estacion"],
            "loc_ref": vigente["loc"],
            "cha_ref": vigente["cha"],
            "streams_vigentes": cantidad,
            "distancia_km": round(distancia, 1),
            "est_lat": vigente["latitud"],
            "est_lon": vigente["longitud"],
            "est_elev": vigente["elevacion"],
            "est_lugar": vigente["lugar"],
            "est_pais": vigente["pais"],
            "radio_km": radio_km,
            "actividad_ventana": cercana,
            "waveform_status": ESTADO_SIN_CONSULTAR,
            "availability_source": "",
            "cobertura_desde": "",
            "cobertura_hasta": "",
        })
    filas.sort(key=lambda f: (f["distancia_km"], f["red"], f["estacion"]))
    return filas, descartadas


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


def _consultar_inventario_de_base(base, inicio, fin):
    """
    Trae las estaciones del inventario cuya época se solapa con la ventana.

    No filtra por la hora de cada evento: eso lo hace _stream_valido, porque
    depende del evento y no de la ventana. Acá solo se traen las que podrían
    llegar a estar vigentes en algún momento del período, que son muy pocas
    comparadas con la tabla completa.

    Si la base falla al leer el inventario se avisa y se sigue con lo que haya:
    las estaciones no picadas son un dato derivado y su ausencia no invalida los
    eventos ni las fases, que son la exportación en sí.
    """
    config = configuracion(base)
    conn = conectar(config)
    try:
        cursor = crear_cursor(conn)
        cursor.execute("SET TIME ZONE 'UTC'")
        cursor.execute(CONSULTA_INVENTARIO_SQL, (fin, inicio))
        filas = cursor.fetchall()
        _medir("inventario_fin", "base=%s" % base)
    finally:
        conn.close()
    return filas


def _consultar_bindings_de_base(base):
    """
    Estaciones con binding habilitado: las que SeisComp está configurado a
    procesar (subconjunto del inventario: dataless cargado sin binding no
    cuenta).

    Devuelve un conjunto de (red, estación). Si la base no tiene config o falla
    la consulta, devuelve un conjunto vacío y el que llama decide (no filtrar).
    """
    config = configuracion(base)
    conn = conectar(config)
    try:
        cursor = crear_cursor(conn)
        cursor.execute("SET TIME ZONE 'UTC'")
        cursor.execute(CONSULTA_BINDINGS_SQL)
        filas = cursor.fetchall()
        _medir("bindings_fin", "base=%s" % base)
    finally:
        conn.close()
    return {(f.get("red"), f.get("estacion"))
            for f in filas if f.get("red") and f.get("estacion")}


def _consultar_actividad_de_base(base, instante, horas, solo_confirmados=True):
    """
    Eventos que cada estación picó dentro de ±horas del instante, en una base.

    Devuelve {codigo: [instantes ordenados]}, el mismo mapa que arma la
    exportación a partir del resumen de fases. La usa el revisor cuando amplía
    el radio de un evento: así recalcula la actividad de las estaciones nuevas
    sin recorrer el archivo de fases entero, y solo consulta el tramo temporal
    del evento.
    """
    desde = instante - timedelta(hours=horas)
    hasta = instante + timedelta(hours=horas)
    config = configuracion(base)
    conn = conectar(config)
    try:
        cursor = crear_cursor(conn)
        cursor.execute("SET TIME ZONE 'UTC'")
        cursor.execute(CONSULTA_ACTIVIDAD_SQL,
                       (desde, hasta) + _parametros_estatus(solo_confirmados))
        filas = cursor.fetchall()
    finally:
        conn.close()
    actividad = {}
    for fila in filas:
        # Un origen sin hora no aporta actividad; se saltea para no romper el
        # orden (en la base un origen válido siempre tiene m_time_value).
        instante_fila = fila.get("instante")
        if instante_fila is None:
            continue
        codigo = (fila.get("red"), fila.get("estacion"))
        actividad.setdefault(codigo, []).append(instante_fila)
    for horas_estacion in actividad.values():
        horas_estacion.sort()
    return actividad


def no_picadas_de_evento_desde_base(base, instante, id_evento, id_origen,
                                    latitud, longitud, picadas,
                                    radio_km=RADIO_ESTACIONES_KM,
                                    actividad_horas=ACTIVIDAD_HORAS,
                                    solo_confirmados=True):
    """
    Recalcula las estaciones sin arribos de UN evento contra la base.

    Es lo que usa el revisor cuando el usuario amplía el radio más allá del
    corte exportado: consulta el inventario vigente a la hora del evento y la
    actividad de las estaciones alrededor, y devuelve las filas listas para
    mostrar y descargar. No toca los CSV de la exportación.

    'base' es la del evento (columna base_datos del CSV de eventos). 'picadas'
    son las claves (red, estación) que tienen al menos una llegada en el evento.
    Devuelve (filas, descartadas) igual que _no_picadas_de_evento.
    """
    bindings = None
    try:
        bindings = _consultar_bindings_de_base(base) or None
    except Exception:
        bindings = None
    inventario = _consultar_inventario_de_base(base, instante, instante)
    indice = _indice_por_celda(inventario, bindings=bindings)
    actividad = _consultar_actividad_de_base(base, instante, actividad_horas,
                                             solo_confirmados)
    return _no_picadas_de_evento(instante, id_evento, id_origen, latitud,
                                 longitud, indice, picadas, actividad,
                                 radio_km=radio_km,
                                 actividad_horas=actividad_horas)


def estimar_no_picadas(bases, inicio, fin, radio_km,
                       solo_confirmados=True, muestra=200):
    """
    Estima (filas, MB) del CSV de no picadas de una ventana, sin exportarlo.

    La usan la ventana de solicitud y el re-export para avisar ANTES de correr
    una exportación que puede quedar enorme: el archivo crece con los eventos y
    con el radio, y en el histórico completo pasa de un gigabyte. Cuenta una
    muestra de eventos y la escala por el total, así que es barata incluso para
    ventanas grandes.

    Si una base no responde se la saltea: el aviso es un extra, no un requisito.
    Devuelve filas y megabytes redondeados; (0, 0.0) si no se pudo estimar.
    """
    if radio_km is None or radio_km <= 0:
        return 0, 0.0
    parametros = (inicio, fin) + _parametros_estatus(solo_confirmados)
    filas_estimadas = 0.0
    for base in bases:
        try:
            conn = conectar(configuracion(base))
        except Exception:
            continue
        try:
            cursor = crear_cursor(conn)
            cursor.execute("SET TIME ZONE 'UTC'")
            cursor.execute(CONSULTA_EVENTOS_VENTANA_SQL, parametros)
            total = cursor.fetchone().get("total") or 0
            if not total:
                continue
            cursor.execute(CONSULTA_ESTIMACION_NO_PICADAS_SQL,
                           parametros + (muestra, radio_km))
            fila = cursor.fetchone()
            n_muestra = fila.get("muestra") or 0
            n_pares = fila.get("pares") or 0
        finally:
            conn.close()
        if n_muestra:
            filas_estimadas += n_pares * (float(total) / n_muestra)
    filas = int(round(filas_estimadas))
    return filas, filas * NO_PICADAS_BYTES_FILA / 1000000.0


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
                     solo_confirmados=True, reusar=False,
                     radio_km=RADIO_ESTACIONES_KM,
                     actividad_horas=ACTIVIDAD_HORAS):
    """
    Consulta los eventos de la ventana y sus fases, y escribe los tres CSV.
    Devuelve un diccionario con las rutas y las cantidades de filas.

    Por defecto sale solo lo que un analista revisó (estado "confirmed"). Con
    solo_confirmados=False entran también las soluciones automáticas, que son
    muchas más pero no son eventos publicados.

    El tercer CSV, _no_picadas.csv, son las estaciones del inventario que
    quedaron dentro de radio_km del evento y no fueron picadas. 'radio_km' fija
    ese radio y 'actividad_horas' qué tan cerca en el tiempo tiene que haber
    picado una estación para que se la considere activa.

    Con reusar=True, si esa ventana ya está exportada y completa, devuelve sus
    archivos sin consultar la base. El resultado trae "reusado": True y las
    cantidades en None, porque las filas no se contaron otra vez. Para que el
    reuso siga siendo correcto ahora hacen falta los tres CSV: una exportación
    vieja sin el de no picadas se vuelve a exportar.
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
    salida_no_picadas = _ruta_no_picadas(salida)
    marca = _ruta_completo(salida)

    # El reuso exige que el radio coincida: si se pide uno distinto del que
    # tiene la exportación en disco, el corte de estaciones estaría mal y hay
    # que re-exportar. Se compara redondeado, porque la marca guarda enteros.
    radio_marca = None
    if reusar and os.path.isfile(marca):
        radio_marca = _radio_de_la_marca(marca)
    if reusar and os.path.isfile(salida) and os.path.isfile(salida_fases) \
            and os.path.isfile(salida_no_picadas) and os.path.isfile(marca) \
            and radio_marca is not None \
            and abs(radio_marca - round(radio_km)) < 0.5:
        print("   Ventana       : %s  ->  %s  (UTC)"
              % (inicio.strftime(FORMATO), fin.strftime(FORMATO)))
        print("   [Aviso] Se reusa la exportación existente; no se consulta"
              " la base.")
        prog.avance(1.0)
        return {
            "ruta": os.path.abspath(salida),
            "ruta_fases": os.path.abspath(salida_fases),
            "ruta_no_picadas": os.path.abspath(salida_no_picadas),
            "eventos": None,
            "fases": None,
            "no_picadas": None,
            "reusado": True,
        }
    if reusar and os.path.isfile(marca) and radio_marca is not None \
            and abs(radio_marca - round(radio_km)) >= 0.5:
        print("   [Aviso] La exportación en disco usó radio %.0f km y se pide"
              " %.0f km; se vuelve a exportar." % (radio_marca, radio_km))

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

    # --- Estaciones no picadas ---
    # Va después de las fases porque necesita dos cosas que solo están listas
    # ahora: qué estaciones picaron cada evento (sale del resumen) y la hora de
    # cada evento (está en las filas de eventos, que ya están en memoria).
    print("   Calculando estaciones no picadas (radio %.0f km)..." % radio_km)
    try:
        estimadas, mb = estimar_no_picadas(bases, inicio, fin, radio_km,
                                           solo_confirmados)
    except Exception:
        estimadas, mb = 0, 0.0
    if estimadas:
        print("      Estimado      : ~%s estaciones (~%.1f MB)."
              % ("{:,}".format(estimadas).replace(",", "."), mb))
        if mb >= AVISO_NO_PICADAS_MB:
            print("      [Aviso] Es un archivo grande; considerá bajar el radio"
                  " o partir la ventana.")
    inventario = []
    for nombre in bases:
        try:
            inventario.extend(_consultar_inventario_de_base(nombre, inicio, fin))
        except Exception as e:
            print("   [Aviso] No se pudo leer el inventario de %s (%s); se"
                  " sigue sin las estaciones de esa base."
                  % (nombre, str(e).strip().splitlines()[0]))

    # Bindings: las estaciones que SeisComp tiene configurado procesar. Se
    # acumulan entre bases y, si no hay ninguno, NO se filtra: una base sin
    # config dejaría la lista vacía sin motivo.
    bindings = set()
    for nombre in bases:
        try:
            bindings |= _consultar_bindings_de_base(nombre)
        except Exception as e:
            print("   [Aviso] No se pudieron leer los bindings de %s (%s); se"
                  " sigue sin filtrar por bindings."
                  % (nombre, str(e).strip().splitlines()[0]))
    if not bindings:
        print("   [Aviso] No se encontraron bindings; se usa todo el inventario"
              " (puede incluir dataless sin binding).")
        bindings = None
    indice = _indice_por_celda(inventario, bindings=bindings)

    tiempos = {}
    for fila in filas:
        instante = fila.get("ot_utc")
        if isinstance(instante, datetime):
            tiempos[fila.get("id_evento")] = instante

    # Actividad por estación: las horas de los eventos que picó. Es lo que
    # separa "estaba en el inventario" de "estaba grabando".
    actividad = {}
    for id_evento, resumen_evento in resumen_por_evento.items():
        instante = tiempos.get(id_evento)
        if instante is None:
            continue
        for codigo in resumen_evento["estaciones"]:
            actividad.setdefault(codigo, []).append(instante)
    for horas in actividad.values():
        horas.sort()

    total_no_picadas = 0
    total_descartadas = 0
    _escribir_csv(salida_no_picadas, [], CABECERA_NO_PICADAS)
    for fila in filas:
        instante = tiempos.get(fila.get("id_evento"))
        if instante is None:
            continue
        try:
            latitud = float(fila.get("latitud"))
            longitud = float(fila.get("longitud"))
        except (TypeError, ValueError):
            continue
        no_picadas, descartadas = _no_picadas_de_evento(
            instante, fila.get("id_evento"), fila.get("id_origen"),
            latitud, longitud, indice,
            resumen_por_evento.get(fila.get("id_evento"), {}).get("estaciones",
                                                                  set()),
            actividad, radio_km=radio_km, actividad_horas=actividad_horas)
        total_descartadas += descartadas
        if no_picadas:
            _escribir_csv(salida_no_picadas, no_picadas,
                          CABECERA_NO_PICADAS, append=True)
            total_no_picadas += len(no_picadas)
    print("      %d estaciones sin arribos de %d streams de inventario (%s)."
          % (total_no_picadas,
             sum(len(celda) for celda in indice.values()),
             "con bindings" if bindings else "sin bindings"))
    if total_descartadas:
        print("      [Aviso] %d estaciones quedaron afuera por no tener"
              " sensorlocation/stream vigente en la hora del evento."
              % total_descartadas)
    _medir("no_picadas_fin")

    # La marca va al final, después de escribir los tres CSV: es lo último que
    # se hace, y es lo que dice que no quedó nada a medias.
    _escribir_marca(marca, inicio, fin, len(filas), total_fases,
                    total_no_picadas, radio_km, bases, total_descartadas)
    prog.avance(1.0)

    return {
        "ruta": os.path.abspath(salida),
        "eventos": len(filas),
        "ruta_fases": os.path.abspath(salida_fases),
        "fases": total_fases,
        "ruta_no_picadas": os.path.abspath(salida_no_picadas),
        "no_picadas": total_no_picadas,
        "descartadas_sin_stream": total_descartadas,
        "radio_km": radio_km,
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
    radio_km = RADIO_ESTACIONES_KM
    actividad_horas = ACTIVIDAD_HORAS
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
        if argumentos[i] == "--radio-km":
            # El radio de la búsqueda de estaciones sin arribos. Se acepta con o
            # sin la unidad, porque "300" y "300km" son lo mismo y no vale la
            # pena hacer fallar el comando por eso.
            if i + 1 >= len(argumentos):
                print("[X] --radio-km necesita un valor en kilómetros.")
                return 2
            try:
                radio_km = float(argumentos[i + 1].rstrip("kKmM"))
            except ValueError:
                print("[X] --radio-km debe ser un número de kilómetros"
                      " (por ejemplo 300 o 300km).")
                return 2
            if radio_km <= 0:
                print("[X] --radio-km tiene que ser mayor que cero.")
                return 2
            i += 2
            continue
        if argumentos[i] == "--actividad-h":
            # Qué tan cerca en el tiempo tiene que haber picado una estación
            # para contar como actividad inferida.
            if i + 1 >= len(argumentos):
                print("[X] --actividad-h necesita un valor en horas.")
                return 2
            try:
                actividad_horas = float(argumentos[i + 1].rstrip("hH"))
            except ValueError:
                print("[X] --actividad-h debe ser un número de horas"
                      " (por ejemplo 24 o 24h).")
                return 2
            if actividad_horas < 0:
                print("[X] --actividad-h no puede ser negativo.")
                return 2
            i += 2
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
              " [--radio-km <km>] [--actividad-h <horas>]"
              % os.path.basename(__file__))
        return 2
    else:
        inicio, fin = _preguntar_ventana(sugerencia)

    print()
    try:
        resultado = exportar_ventana(inicio, fin, salida, base,
                                    solo_confirmados, reusar,
                                    radio_km=radio_km,
                                    actividad_horas=actividad_horas)
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
        print("     Archivo: %s" % resultado["ruta_no_picadas"])
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

    total_no_picadas = resultado.get("no_picadas") or 0
    print()
    if total_no_picadas:
        print("[OK] %d estaciones sin arribos asociados dentro de %.0f km"
              " (actividad inferida a ±%.0f h)."
              % (total_no_picadas, resultado["radio_km"], actividad_horas))
    else:
        print("[Aviso] Ninguna estación del inventario quedó sin arribos"
              " asociados dentro de %.0f km." % resultado["radio_km"])
    descartadas = resultado.get("descartadas_sin_stream") or 0
    if descartadas:
        print("[Aviso] %d estaciones quedaron afuera por no tener"
              " sensorlocation/stream vigente en la hora del evento."
              % descartadas)
    print("     Archivo: %s" % resultado["ruta_no_picadas"])
    print("     Ojo: 'sin arribos' es que no tienen arrivals/picks asociados al"
          " origen preferido, no que no hayan grabado. Para eso hay que mirar"
          " la señal (SDS/DataAvailability).")

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
