#!/usr/bin/bash
#lear
fuente="seisan"
python3 /home/hriquelmez/Revision_Local/generajson.py "no_pub_desde_2_5.csv" $fuente
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
    if [[ $1 = "eventquery" ]]
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
