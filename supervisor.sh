#!/usr/bin/bash
# ==============================================================================
# supervisor.sh
# Lanzador de la aplicación de revisión.
#   - Si no existe el entorno virtual (.venv), lo crea e instala las
#     dependencias de requirements.txt (Python 3.7+, requiere python3-venv).
#   - Luego ejecuta app.py con el entorno activado.
#
# Uso:
#   ./supervisor.sh
#
# Sin parámetros abre la ventana de solicitud de catálogos (Seisan y
# eventquery desde el servidor remoto, más la ventana de SeisComp) y, al
# terminar, la ventana principal de revisión. Luego se pulsa «Procesar
# catálogos» cuando se quiera procesar.
#
# El modo antiguo sigue disponible para trabajos puntuales:
#   ./supervisor.sh <archivo_entrada.csv> <archivo_salida.dat>
#
# Las salidas se organizan por contenido en el directorio de ejecución
# (datos/ informes/ analistas/ ploteo/ trabajo/ — ver rutas.py).
# ==============================================================================

set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$DIR/.venv"
REQ="$DIR/requirements.txt"

if [ ! -d "$VENV" ]; then
    echo "[supervisor] No existe el entorno virtual; creándolo en $VENV ..."
    if ! python3 -m venv "$VENV"; then
        echo "[supervisor] ERROR: no se pudo crear el entorno virtual."
        echo "             Verifique que 'python3-venv' esté instalado y que"
        echo "             la máquina tenga Python 3.7 o superior."
        exit 1
    fi
    echo "[supervisor] Instalando dependencias (requirements.txt) ..."
    # Nota: Shapely se compila desde fuente (--no-binary shapely) para que use
    # el GEOS del sistema; el wheel empaqueta su propio GEOS y provoca un
    # segfault al usarlo junto con cartopy (que enlaza el GEOS del sistema).
    # Esto requiere libgeos-dev y un compilador C en la máquina.
    if ! "$VENV/bin/pip" install --no-binary shapely -r "$REQ"; then
        echo "[supervisor] ERROR: falló la instalación de dependencias."
        echo "             Si falla al compilar Shapely, instale 'libgeos-dev'"
        echo "             (y un compilador C) y vuelva a intentarlo."
        exit 1
    fi
fi

# Con argumentos se conserva el modo antiguo (catálogo explícito); sin
# argumentos se pide la ventana y se bajan los tres catálogos.
if [ "$#" -gt 0 ]; then
    exec "$VENV/bin/python" "$DIR/app.py" "$@"
fi
exec "$VENV/bin/python" "$DIR/solicita_catalogos.py"
