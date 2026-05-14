#!/usr/bin/bash
clear
read -p "¿Desea plotear resultados? S/N : " -n1 respuesta 
if [ $respuesta = "S" -o $respuesta = "s" ]
then
    echo -e "\n***** Se mostrarán mapas de perfil y planta *****"
    #python3 /home/hriquelmez/Revision_Local/proc_query_harz_2.py $1 $2
    ls file*.json > listado.txt
    while IFS= read -r linea
    do
    # Código que se ejecuta para cada línea
    #echo "Archivo fuente: $linea"
    #fuente="eventquery"
    #python3 /home/hriquelmez/Revision_Local/plotear.py $linea "eventquery" 
    python3 /home/hriquelmez/Revision_Local/plotear.py $linea $1
    done < listado.txt
    rm listado.txt
    if [ $1 = "eventquery" ]
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
        echo -e "Eventos ploteados, de los cuales $percibidos fueron reportados como percibidos"
    else
        echo -e "Se plotearon eventos"
    fi
else
    echo -e "\n¡¡¡ Hasta pronto !!!"
fi
