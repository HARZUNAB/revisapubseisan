#!/usr/bin/bash
# ==============================================================================
# supervisor.sh
# Lanzador/supervisor del flujo de revisión:
#   1) Análisis: proc_query -> revisaselect -> revisacollect -> compara ->
#      (revisaexcluidos / repetidosexclu) -> repetidos.
#   2) Menú (con bucle) para generar el JSON de la fuente elegida y plotear,
#      ver los repetidos, etc.
# Las salidas quedan organizadas por contenido en el directorio de ejecución:
#   datos/ informes/ analistas/ ploteo/ trabajo/  (ver rutas.py)
# ==============================================================================

SCRIPTS="/home/hriquelmez/Desarrollo"
PROYECTO="revisapubseisan"
base=$(basename "$1")
nombre_archivo=""

cp $1 origen_$1

# --- Rutas de salida organizadas ---
ARCHIVO_EXCLUIDOS="informes/excluidos.txt"
ARCHIVO_EXCLUIDOSTMP="trabajo/excluidostmp1.txt"

# --- Utilidades del menú -----------------------------------------------------
correr_plotear() {
    read -p "¿Desea plotear resultados? S/N : " -n1 r
    echo
    if [ "$r" = "S" -o "$r" = "s" ]
    then
        echo -e "\n***** Se mostrarán mapas de perfil y planta *****"
        python3 $SCRIPTS/$PROYECTO/plotear.py "datos/eventos_${fuente}.json" "$fuente"
        if [ "$fuente" = "eventquery" ]
        then
            percibidos=0
            while IFS= read -r linea
            do
                ((percibidos++))
            done < <(tail -n +2 "ploteo/percibidos.txt")
            echo -e "Eventos ploteados, de los cuales $percibidos fueron reportados como percibidos"
        else
            echo -e "Se plotearon eventos"
        fi
    fi
}

generar_eventquery() {
    fuente="eventquery"
    # concatena todos los datos/new_2_*.csv en uno solo (conservando el
    # encabezado) para generar un único JSON por fuente
    primera=1
    : > datos/todos_eventquery.csv
    for linea in datos/new_2_*.csv
    do
        [ -f "$linea" ] || continue
        if [ $primera = "1" ]
        then
            cat "$linea" > datos/todos_eventquery.csv
            primera=0
        else
            tail -n +2 "$linea" >> datos/todos_eventquery.csv
        fi
    done
    python3 $SCRIPTS/$PROYECTO/generajson.py "datos/todos_eventquery.csv" $fuente
    rm -f datos/todos_eventquery.csv
}

ver_repetidos() {
    local archivos=(informes/rep_publica_amplio.txt
                    informes/rep_publica_estricto.txt
                    informes/rep_seisan_amplio.txt
                    informes/rep_seisan_estricto.txt
                    informes/rep_seisan_exclu.txt)
    while true
    do
        echo -e "\n***** Eventos repetidos *****"
        local i=1
        for f in "${archivos[@]}"
        do
            if [ -f "$f" ]
            then
                n=$(wc -l < "$f")
                if [ "$n" -gt 0 ]; then n=$((n - 1)); fi
                printf "  %d) %-28s %6d eventos\n" "$i" "$(basename "$f")" "$n"
            else
                printf "  %d) %-28s   (no generado)\n" "$i" "$(basename "$f")"
            fi
            i=$((i + 1))
        done
        echo "  0) Volver al menú"
        read -p "Elija archivo a mostrar : " -n1 sel
        echo
        case "$sel" in
            0|"")
                break
                ;;
            [1-5])
                f="${archivos[$((sel - 1))]}"
                echo -e "\n----- $(basename "$f") -----"
                if [ -s "$f" ]
                then
                    cat "$f"
                else
                    echo "(sin contenido / no generado)"
                fi
                echo "----- fin -----"
                ;;
            *)
                echo -e "\n¡¡¡ Opción inválida !!!"
                ;;
        esac
    done
}

# ==============================================================================
# FASE 1: ANÁLISIS
# ==============================================================================
read -p "¿Desea analizar información? S/N : " -n1 respuesta
echo
if [ $respuesta = "S" -o $respuesta = "s" ]
then
    echo -e "\n***** Se comienza el análisis de los datos *****"
    python3 $SCRIPTS/$PROYECTO/proc_query_harz_2.py $1 $2
    python3 $SCRIPTS/$PROYECTO/revisaselect.py
    python3 $SCRIPTS/$PROYECTO/revisacollect.py
    echo -e "\n***** Se comparan publicados v/s procesados en seisan *****"
    python3 $SCRIPTS/$PROYECTO/compara.py "datos/new_2_${base}" "datos/salida_collect.csv"
    # Verifica si el archivo de excluidos NO está vacío
    if [ -s "$ARCHIVO_EXCLUIDOS" ]
    then
        echo -e "\n***** Revisando excluidos *****"
        python3 $SCRIPTS/$PROYECTO/revisaexcluidos.py
        nombre_archivo="$ARCHIVO_EXCLUIDOS"
        python3 $SCRIPTS/$PROYECTO/repetidosexclu.py "datos/excluidos.csv" "datos/salida_collect.csv"
        echo "$ARCHIVO_EXCLUIDOS"
    else
        rm -f "$ARCHIVO_EXCLUIDOS"
        rm -f "$ARCHIVO_EXCLUIDOSTMP"
        echo -e "\n¡¡¡ No se excluyeron eventos del select.out !!!"
    fi
    echo -e "\n***** Se revisan repetidos *****"
    python3 $SCRIPTS/$PROYECTO/repetidos.py "datos/new_2_${base}" "datos/salida_collect.csv"
    rm -f "$2"

    # ==========================================================================
    # FASE 2: MENÚ (con bucle)
    # ==========================================================================
    while true
    do
        echo -e "\n¿Qué desea hacer?"
        echo -e "  1 - Datos de Seisan"
        echo -e "  2 - Datos de eventquery"
        echo -e "  3 - Datos de SeisComp           (no disponible)"
        echo -e "  4 - No publicados de seisan"
        echo -e "  5 - No publicados de SeisComp   (no disponible)"
        echo -e "  6 - Ver repetidos"
        echo -e "  7 - Salir"
        read -p "Ingrese opción : " -n1 opcion
        echo
        case "$opcion" in
            1)
                echo -e "\n***** Procesando datos extraidos desde seisan *****"
                fuente="seisan"
                python3 $SCRIPTS/$PROYECTO/generajson.py "datos/salida_collect.csv" $fuente
                correr_plotear
                ;;
            2)
                echo -e "\n***** Procesando datos extraidos desde eventquery *****"
                generar_eventquery
                correr_plotear
                ;;
            3)
                echo -e "\nOpción 'Datos de SeisComp' no disponible por ahora."
                ;;
            4)
                echo -e "\n***** Procesando no publicados de seisan *****"
                if [ -f "datos/no_pub_desde_2_5_estricto.csv" ]
                then
                    fuente="seisan"
                    python3 $SCRIPTS/$PROYECTO/generajson.py "datos/no_pub_desde_2_5_estricto.csv" $fuente
                    correr_plotear
                else
                    echo "No se encontró datos/no_pub_desde_2_5_estricto.csv (corra el análisis primero)."
                fi
                ;;
            5)
                echo -e "\nOpción 'No publicados de SeisComp' no disponible por ahora."
                ;;
            6)
                ver_repetidos
                ;;
            7)
                break
                ;;
            *)
                echo -e "\n¡¡¡ Ingrese opción válida !!!"
                ;;
        esac
    done

    # Restaura el archivo original si no hubo eventos excluidos.
    if [ ! -f "$nombre_archivo" ]
    then
        cp origen_$1 $1
    fi
else
    if [ ! -f "$nombre_archivo" ]
    then
        cp origen_$1 $1
    fi
    echo -e "\nGenera .dat para revisión"
    python3 $SCRIPTS/$PROYECTO/proc_query_harz_2.py $1 $2
fi
