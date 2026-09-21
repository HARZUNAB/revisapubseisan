#!/usr/bin/bash
clear
SCRIPTS="/home/hriquelmez/Desarrollo"
PROYECTO="revisapubseisan"
read -p "¿Desea plotear resultados? S/N : " -n1 respuesta 
if [ $respuesta = "S" -o $respuesta = "s" ]
then
    echo -e "\n***** Se mostrarán mapas de perfil y planta *****"
    #python3 /home/hriquelmez/Revision_Local/proc_query_harz_2.py $1 $2
    python3 $SCRIPTS/$PROYECTO/plotear.py "eventos_${1}.json" $1
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
