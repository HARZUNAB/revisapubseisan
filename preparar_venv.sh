#!/bin/bash
# ==============================================================================
# preparar_venv.sh
# Dejar el entorno virtual del proyecto listo para usar, o decir por qué no se
# pudo. No se ejecuta solo: se sourcea desde un lanzador, que es quien decide
# qué hacer con el resultado.
#
#   . preparar_venv.sh
#   preparar_venv "$DIR/.venv" "$DIR/requirements.txt" "seiscomp"
#
# El tercer argumento es solo la etiqueta que aparece en los mensajes, para que
# cada lanzador se anuncie con su propio nombre.
#
# Por qué existe: el bloque de creación e instalación estaba escrito dentro de
# supervisor.sh. Con un segundo lanzador habría que copiarlo, y las dos copias
# se van a ir solapando con el tiempo. supervisor.sh sigue con su bloque propio
# y funciona igual; este archivo es para los lanzadores nuevos.
#
# La instalación usa --no-binary shapely a propósito: el wheel de Shapely
# empaqueta su propio GEOS y provoca un segfault al usarlo junto con cartopy,
# que enlaza el GEOS del sistema. Eso exige libgeos-dev y un compilador C.
# ==============================================================================

preparar_venv() {
    local venv="$1"
    local req="$2"
    local etiqueta="${3:-proyecto}"

    if [ -d "$venv" ]; then
        return 0
    fi

    echo "[$etiqueta] No existe el entorno virtual; creándolo en $venv ..."
    if ! python3 -m venv "$venv"; then
        echo "[$etiqueta] ERROR: no se pudo crear el entorno virtual."
        echo "              Verifique que 'python3-venv' esté instalado y que"
        echo "              la máquina tenga Python 3.7 o superior."
        return 1
    fi

    echo "[$etiqueta] Instalando dependencias (requirements.txt) ..."
    if ! "$venv/bin/pip" install --no-binary shapely -r "$req"; then
        echo "[$etiqueta] ERROR: falló la instalación de dependencias."
        echo "              Si falla al compilar Shapely, instale 'libgeos-dev'"
        echo "              (y un compilador C) y vuelva a intentarlo."
        return 1
    fi
    return 0
}
