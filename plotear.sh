#!/usr/bin/bash
#clear
SCRIPTS="/home/hriquelmez/Desarrollo"
PROYECTO="revisapubseisan"

echo -e "\n¿Que datos desea procesar para plotear?"
    echo -e "1-Datos de Seisan"
    echo -e "2-Datos de eventquery"
    echo -e "3-No publicados de seisan"
    echo -e "4-Salir"
    opcion="5"
    while [ $opcion != "1" -o $opcion != "2" -o $opcion != "3" -o $opcion != "4" ]
    do
        read -p "Ingrese opción : " -n1 opcion
        #if [ $respuesta = "1" -o $respuesta = "2" ]
        if [ $opcion = "1" -o $opcion = "2" -o $opcion = "3" -o $opcion = "4" ]
        then
            if [ $opcion = "1" ]
            then
                #python3 /home/hriquelmez/Revision_Local/revisaselect.py
                python3 $SCRIPTS/$PROYECTO/revisaselect.py
                #python3 /home/hriquelmez/Revision_Local/revisacollect.py
                python3 $SCRIPTS/$PROYECTO/revisacollect.py
                echo -e "\n***** Procesando datos extraidos desde seisan *****"
                #python3 /home/hriquelmez/Revision_Local/proc_query_harz_2.py $1 $2
                fuente="seisan"
                python3 $SCRIPTS/$PROYECTO/generajson.py "salida_collect.csv" $fuente
            else
                if [ $opcion = "2" ]
                then
                    python3 $SCRIPTS/$PROYECTO/revisaselect.py
                    python3 $SCRIPTS/$PROYECTO/revisacollect.py
                    echo -e "\n***** Procesando datos extraidos desde eventquery *****"
                    #python3 /home/hriquelmez/Revision_Local/proc_query_harz_2.py $1 $2

                    fuente="eventquery"
                    # concatena todos los new_2_*.csv en uno solo (conservando
                    # el encabezado) para generar un único JSON por fuente
                    primera=1
                    : > todos_eventquery.csv
                    for linea in new_2_*.csv
                    do
                        [ -f "$linea" ] || continue
                        if [ $primera = "1" ]
                        then
                            cat "$linea" > todos_eventquery.csv
                            primera=0
                        else
                            tail -n +2 "$linea" >> todos_eventquery.csv
                        fi
                    done
                    python3 $SCRIPTS/$PROYECTO/generajson.py "todos_eventquery.csv" $fuente
                    rm todos_eventquery.csv
                else
                    if [ $opcion = "3" ]
                    then
                        python3 $SCRIPTS/$PROYECTO/revisaselect.py
                        python3 $SCRIPTS/$PROYECTO/revisacollect.py
                        echo -e "\n***** Procesando datos no publicados desde seisan *****"
                        fuente="seisan"
                        python3 $SCRIPTS/$PROYECTO/generajson.py "no_pub_desde_2_5_estricto.csv" $fuente
                    else
                        echo -e "\n¡¡¡ Hasta pronto !!!"
                        exit 0
                    fi
                fi
            fi    
            break
        else
            echo -e "\n¡¡¡ Ingrese opcion valida !!!"
        fi
    done
    #rm $1
    #rm $2
    read -p "¿Desea plotear resultados? S/N : " -n1 respuesta 
    if [ $respuesta = "S" -o $respuesta = "s" ]
    then
        echo -e "\n***** Se mostrarán mapas de perfil y planta *****"
        #python3 /home/hriquelmez/Revision_Local/proc_query_harz_2.py $1 $2
        python3 $SCRIPTS/$PROYECTO/plotear.py "eventos_${fuente}.json" $fuente
        if [[ $fuente = "eventquery" ]]
        then
            percibidos=0

            # Usar la sustitución de procesos para alimentar el bucle desde 'tail'
            while IFS= read -r linea
            do
                # Incrementar el contador. El cambio será persistente.
                ((percibidos++))
            done < <(tail -n +2 "percibidos.txt")
            echo -e "Eventos ploteados, de los cuales $percibidos fueron reportados como percibidos"
        else
            echo -e "Se plotearon eventos"
        fi
    else
        echo -e "\n¡¡¡ Hasta pronto !!!"
    fi
