#!/bin/bash
# ==============================================================================
# seiscomp.sh
# Lanzador de la extracción desde SeisComp6 y su revisión, en un solo comando.
# Vive al lado de supervisor.sh, pero NO es la aplicación: acá no hay ventana de
# supervisor, solo la exportación de SeisComp y la pantalla que la revisa.
# Sigue siendo útil para trabajar un período suelto sin lanzar todo el análisis;
# desde la app, el mismo trabajo se hace con «Obtener de SeisComp».
#
# Uso:
#   ./seiscomp.sh <catalogo.csv> [--reexportar] [--solo-revision]
#   ./seiscomp.sh --ayuda
#
# QUÉ ES EL CATÁLOGO
#
# Es el mismo archivo que se le pasa a supervisor.sh para extraer, por ejemplo
# sept_2026.csv. Es la referencia contra la que se va a comparar lo que
# devuelva SeisComp, y va PRIMERO en la línea de órdenes.
#
# Va explícito a propósito, y no se busca solo: la carpeta de trabajo tiene
# varios CSV con columna de tiempo, y algunos no son un catálogo de eventos sino
# el fondo de sismicidad que se plotea, o un reporte de sospechosos. Elegirlo por
# fecha de modificación abriría una ventana que no es la que se está revisando,
# sin que nada lo avise. Con el catálogo a la vista, la exportación y la revisión
# quedan atadas al mismo período por construcción.
#
# Sirve tanto el de entrada (columna 'time') como el derivado que deja el
# análisis, datos/new_2_<nombre>.csv (columna 'Fecha_Hora').
#
# QUÉ HACE, EN ORDEN
#
#   1. Prepara el entorno virtual si falta (preparar_venv.sh).
#   2. Verifica intérprete, paquetes, pantalla y acceso a la base con
#      verifica_entorno.py, y corta si falta algo obligatorio. Sin esto, una
#      consulta a la base que va a fallar se descubre veinte minutos después.
#   3. Saca del catálogo la ventana de tiempo y se la pasa al exportador como
#      SUGERENCIA. El exportador igual pregunta el inicio y el término, con su
#      validación: se acepta con Enter o se escribe otra ventana. La ventana es
#      libre, no tiene por qué ser la del catálogo.
#   4. Exporta, salvo que esa ventana ya esté exportada y completa: en ese caso la
#      reusa sin volver a pegarle a la base. --reexportar fuerza a rehacerla.
#   5. Abre la revisión con el MISMO catálogo, para que se abra la exportación que
#      mejor cubre esa ventana y no la última escrita.
#
# Con --solo-revision no se consulta la base: sirve para volver a mirar una
# exportación que ya está, por ejemplo en otra máquina o con el servidor caído.
#
# Los argumentos que este lanzador no reconozca se pasan tal cual a
# exporta_ventana_seiscomp.py, así que --base, --todos y --ayuda del exportador
# también funcionan, siempre después del catálogo.
#
# DÓNDE QUEDAN LOS ARCHIVOS
#
# Este script NO cambia de directorio. Los CSV van a ./datos del directorio desde
# donde se lo llama, que es donde el exportador los escribe (rutas.py) y donde
# la revisión los busca. Es lo mismo que hace supervisor.sh, y es lo que
# conviene para revisar un período en su propia carpeta.
#
# En ./datos quedan, por ventana:
#   seiscomp_<inicio>_<fin>.csv            un renglón por evento
#   seiscomp_<inicio>_<fin>_fases.csv      un renglón por llegada de estación
#   seiscomp_<inicio>_<fin>.csv.completo   marca de que la exportación terminó
# ==============================================================================

set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$DIR/.venv"
REQ="$DIR/requirements.txt"
PY="$VENV/bin/python"
PROG="seiscomp"

# shellcheck source=preparar_venv.sh
. "$DIR/preparar_venv.sh"

ayuda() {
    # Toma el bloque de comentario de arriba, entre las dos líneas de "=".
    # Se busca por delimitadores y no con un rango de números, para que el
    # --ayuda no se quede corto cada vez que se agrega o se saca una línea.
    awk '
        NR == 1 { next }
        /^# ===/ {
            if (vistos) exit
            vistos = 1
            next
        }
        vistos { sub(/^# ?/, ""); print }
    ' "${BASH_SOURCE[0]}"
}

error() {
    echo "[X] $*"
}

pista() {
    echo "    Use './seiscomp.sh --ayuda' para ver el uso."
}

CATALOGO=""
REEXPORTAR=0
SOLO_REVISION=0
AYUDA=0
EXTRA=()

while [ $# -gt 0 ]; do
    case "$1" in
        -h|--ayuda)
            AYUDA=1
            ;;
        --reexportar)
            REEXPORTAR=1
            ;;
        --solo-revision)
            SOLO_REVISION=1
            ;;
        --)
            shift
            EXTRA+=("$@")
            break
            ;;
        -*)
            EXTRA+=("$1")
            ;;
        *)
            if [ -z "$CATALOGO" ]; then
                CATALOGO="$1"
            else
                EXTRA+=("$1")
            fi
            ;;
    esac
    shift
done

if [ "$AYUDA" -eq 1 ]; then
    ayuda
    exit 0
fi

# --- 1. Entorno virtual ------------------------------------------------------
if ! preparar_venv "$VENV" "$REQ" "$PROG"; then
    exit 1
fi

# --- 2. El catálogo es obligatorio -------------------------------------------
# Se valida antes que todo lo demás, incluso antes de tocar la base: exportar una
# ventana para una referencia que no existe es trabajo que después no sirve.
if [ -z "$CATALOGO" ]; then
    error "Falta el catálogo. Es el archivo de entrada del análisis, por ejemplo:"
    echo "       ./seiscomp.sh sept_2026.csv"
    pista
    exit 2
fi
if [ ! -f "$CATALOGO" ]; then
    error "No existe el catálogo: $CATALOGO"
    pista
    exit 2
fi

# --- 3. Ventana del catálogo -------------------------------------------------
# La ventana se la sugiere el exportador, que la muestra en la pregunta: si el
# usuario no escribe nada se usa esta, y si escribe, se usa lo que escribió. La
# ventana es libre y no tiene por qué ser la del catálogo.
#
# Se resuelve acá y no en el exportador porque el catálogo es del flujo de
# revisión, y el exportador no tiene por qué saber de catálogos. Va antes de la
# verificación del entorno a propósito: leer el catálogo es local y tarda nada,
# mientras que la verificación se va a la base, y tener el archivo malo es el
# error más probable.
SUGERENCIA=""
DESDE=""
HASTA=""
if ! SUGERENCIA=$("$PY" -c '
import sys
sys.path.insert(0, sys.argv[2])
import revisa_seiscomp as rs
ventana = rs._ventana_del_catalogo(sys.argv[1])
if ventana is None:
    print("SIN VENTANA")
else:
    print(ventana[0].strftime(rs.FORMATO_FECHA), ventana[1].strftime(rs.FORMATO_FECHA))
' "$CATALOGO" "$DIR" 2>/dev/null); then
    error "No se pudo leer el catálogo $CATALOGO."
    pista
    exit 2
fi
if [ "$SUGERENCIA" = "SIN VENTANA" ]; then
    error "El catálogo $CATALOGO no tiene una columna de tiempo reconocible."
    echo "    Se reconoce 'time' (AAAAMMDDTHHMMSS) o 'Fecha_Hora' (AAAAMMDD HH:MM:SS)."
    echo "    Revise la primera línea del archivo."
    pista
    exit 2
fi
DESDE=$(echo "$SUGERENCIA" | cut -d' ' -f1)
HASTA=$(echo "$SUGERENCIA" | cut -d' ' -f2)
echo " [$PROG] Catálogo    : $CATALOGO"
if [ "$SOLO_REVISION" -eq 0 ]; then
    echo "        Ventana     : $DESDE -> $HASTA  (sugerida; Enter la acepta)"
fi

# --- 4. Verificación del entorno --------------------------------------------
# En --solo-revision no se verifica: no se consulta la base, y exigir que esté
# accesible para mirar un CSV que ya está en disco sería un requisito falso.
if [ "$SOLO_REVISION" -eq 0 ]; then
    echo " [$PROG] Verificando el entorno ..."
    if ! "$PY" "$DIR/verifica_entorno.py"; then
        error "El entorno no está listo; no se exportó nada."
        exit 1
    fi
    echo
fi

# --- 5. Exportar ------------------------------------------------------------
if [ "$SOLO_REVISION" -eq 1 ]; then
    echo " [$PROG] Solo revisión: no se consulta la base."
else
    echo " [$PROG] Exportando desde SeisComp ..."
    # --reusar salvo que se pida lo contrario. La comprobación de si la
    # exportación anterior terminó bien la hace el exportador, que es donde
    # están los nombres de archivo y la marca de fin.
    REUSO=(--reusar)
    if [ "$REEXPORTAR" -eq 1 ]; then
        REUSO=()
        echo "        (--reexportar: se vuelve a consultar la base)"
    fi

    set +e
    "$PY" "$DIR/exporta_ventana_seiscomp.py" \
        --sugerencia "$DESDE" "$HASTA" \
        "${REUSO[@]+"${REUSO[@]}"}" \
        "${EXTRA[@]+"${EXTRA[@]}"}"
    CODIGO=$?
    set -e
    if [ "$CODIGO" -ne 0 ]; then
        error "La exportación no se completó (código $CODIGO); no se abre la revisión."
        exit "$CODIGO"
    fi
fi

# --- 6. Revisar ------------------------------------------------------------
# El mismo catálogo que se usó para decidir la ventana. Acá se elige el par de
# CSV que MEJOR cubre esa ventana, que es lo contrario de abrir la última
# escrita: al revisar varios períodos en la misma carpeta, la más reciente no
# siempre es la que interesa.
echo
echo " [$PROG] Abriendo la revisión ..."
exec "$PY" "$DIR/revisa_seiscomp.py" --catalogo "$CATALOGO" \
    "${EXTRA[@]+"${EXTRA[@]}"}"
