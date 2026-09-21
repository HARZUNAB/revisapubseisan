#!/usr/bin/bash

SCRIPTS="/home/hriquelmez/Desarrollo"
PROYECTO="revisapubseisan"

cp $1 origen_$1
read -p "¿Desea analizar información? S/N : " -n1 respuesta 
if [ $respuesta = "S" -o $respuesta = "s" ]
then
    echo -e "\n***** Se comienza el análisis de los datos *****"
    #python3 /home/hriquelmez/Revision_Local/proc_query_harz_2.py $1 $2
    python3 $SCRIPTS/$PROYECTO/proc_query_harz_2.py $1 $2
    #python3 $SCRIPTS/$PROYECTO/proc_query.py $1 $2
    #python3 /home/hriquelmez/Revision_Local/revisaselect.py
    python3 $SCRIPTS/$PROYECTO/revisaselect.py
    #python3 /home/hriquelmez/Revision_Local/revisacollect.py
    python3 $SCRIPTS/$PROYECTO/revisacollect.py
    echo -e "\n***** Se comparan publicados v/s procesados en seisan *****"
    #python3 /home/hriquelmez/Revision_Local/compara.py new_2_$1 salida_collect.csv
    python3 $SCRIPTS/$PROYECTO/compara.py new_2_$1 salida_collect.csv
    archivo="excluidos.txt"
    # Verifica si el archivo NO está vacío
    if [[ -s "$archivo" ]]; then
        #echo "El archivo '$archivo' NO está vacío (contiene datos)."
        echo -e "\n***** Revisando excluidos *****"
        #python3 /home/hriquelmez/Revision_Local/revisaexcluidos.py
        python3 $SCRIPTS/$PROYECTO/revisaexcluidos.py
        nombre_archivo="excluidos.txt"
        salida="excluidos.csv"
        #python3 /home/hriquelmez/Revision_Local/repetidosexclu.py excluidos.csv salida_collect.csv
        python3 $SCRIPTS/$PROYECTO/repetidosexclu.py excluidos.csv salida_collect.csv
        echo $archivo
    else
        #echo "El archivo '$archivo' no existe."
        rm excluidos.txt
        rm excluidostmp1.txt
        echo -e "\n¡¡¡ No se excluyeron eventos del select.out !!!"
    fi
    echo -e "\n***** Se revisan repetidos *****"
    #python3 /home/hriquelmez/Revision_Local/repetidos.py new_2_$1 salida_collect.csv
    python3 $SCRIPTS/$PROYECTO/repetidos.py new_2_$1 salida_collect.csv
    echo -e "\n¿Que datos desea procesar para plotear?"
    echo -e "1-Datos de Seisan"
    echo -e "2-Datos de eventquery"
    respuesta="3"
    while [ $respuesta != "1" -o $respuesta != "2" ]
    do
        read -p "Ingrese opción : " -n1 respuesta
        #if [ $respuesta = "1" -o $respuesta = "2" ]
        if [ $respuesta = "1" -o $respuesta = "2" ]
        then
            if [ $respuesta = "1" ]
            then
                echo -e "\n***** Procesando datos extraidos desde seisan *****"
                #python3 /home/hriquelmez/Revision_Local/proc_query_harz_2.py $1 $2
                fuente="seisan"
                #python3 /home/hriquelmez/Revision_Local/generajson.py "salida_collect.csv" $fuente
                python3 $SCRIPTS/$PROYECTO/generajson.py "salida_collect.csv" $fuente
            else
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
                #python3 /home/hriquelmez/Revision_Local/generajson.py $linea $fuente
                python3 $SCRIPTS/$PROYECTO/generajson.py "todos_eventquery.csv" $fuente
                rm todos_eventquery.csv
            fi    
            break
        else
            echo -e "\n¡¡¡ Ingrese opcion valida !!!"
        fi
    done
    #rm $1
    rm $2
    read -p "¿Desea plotear resultados? S/N : " -n1 respuesta 
    if [ $respuesta = "S" -o $respuesta = "s" ]
    then

        echo -e "\n***** Se mostrarán mapas de perfil y planta *****"
        #python3 /home/hriquelmez/Revision_Local/proc_query_harz_2.py $1 $2
        python3 $SCRIPTS/$PROYECTO/plotear.py "eventos_${fuente}.json" $fuente
        if [ $fuente = "eventquery" ]
        then
            # Inicializar la variable en el script principal
            percibidos=0

            # Usar la sustitución de procesos para alimentar el bucle desde 'tail'
            while IFS= read -r linea
            do
                # El bucle se ejecuta en el shell principal
                # Aquí puedes procesar la línea si es necesario
                
                # Incrementar el contador. El cambio será persistente.
                ((percibidos++))
            done < <(tail -n +2 "percibidos.txt")
            #valor_devuelto=$?
            #echo -e "Eventos ploteados $valor_devuelto, de los cuales $percibidos fueron reportados como percibidos"
            echo -e "Eventos ploteados, de los cuales $percibidos fueron reportados como percibidos"
        else
            #echo -e "Se plotearon $valor_devuelto eventos"
            echo -e "Se plotearon eventos"
        fi
    else
        echo -e "\n¡¡¡ Hasta pronto !!!"
    fi
    if [[ ! -f "$nombre_archivo" ]]; then
        cp origen_$1 $1
    fi
else
    if [[ ! -f "$nombre_archivo" ]]; then
        cp origen_$1 $1
    fi
    echo -e "\nGenera .dat para revisión"
    #python3 /home/hriquelmez/Revision_Local/proc_query_harz_2.py $1 $2
    python3 $SCRIPTS/$PROYECTO/proc_query_harz_2.py $1 $2
fi
