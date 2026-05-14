#!/usr/bin/bash
#lear
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
                python3 /home/hriquelmez/Revision_Local/revisaselect.py
                python3 /home/hriquelmez/Revision_Local/revisacollect.py
                echo -e "\n***** Procesando datos extraidos desde seisan *****"
                #python3 /home/hriquelmez/Revision_Local/proc_query_harz_2.py $1 $2
                fuente="seisan"
                python3 /home/hriquelmez/Revision_Local/generajson.py "salida_collect.csv" $fuente
            else
                if [ $opcion = "2" ]
                then
                    python3 /home/hriquelmez/Revision_Local/revisaselect.py
                    python3 /home/hriquelmez/Revision_Local/revisacollect.py
                    echo -e "\n***** Procesando datos extraidos desde eventquery *****"
                    #python3 /home/hriquelmez/Revision_Local/proc_query_harz_2.py $1 $2

                    ls new_2_*.csv > listadocsv.txt
                    while IFS= read -r linea
                    do
                        #echo -e $linea
                        fuente="eventquery"
                        python3 /home/hriquelmez/Revision_Local/generajson.py $linea $fuente
                        rm listadocsv.txt
                    done < listadocsv.txt
                else
                    if [ $opcion = "3" ]
                    then
                        python3 /home/hriquelmez/Revision_Local/revisaselect.py
                        python3 /home/hriquelmez/Revision_Local/revisacollect.py
                        echo -e "\n***** Procesando datos no publicados desde seisan *****"
                        fuente="seisan"
                        python3 /home/hriquelmez/Revision_Local/generajson.py "no_pub_desde_2_5.csv" $fuente
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
        ls file*.json > listado.txt
        while IFS= read -r linea
        do
        #python3 /home/hriquelmez/Revision_Local/plotear.py $linea "seisan"
        python3 /home/hriquelmez/Revision_Local/plotear.py $linea $fuente
        done < listado.txt
        rm listado.txt
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
