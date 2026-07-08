#!/bin/bash

# ==============================================================================
# CONFIGURACIÓN DE VARIABLES
# ==============================================================================
IP_REMOTA="10.54.218.77"
USUARIO_REMOTO="sysop"
DIR_REMOTO="/home/sysop/tmp/extraedatos"
# Ruta exacta del binario que encontraste en el servidor remoto
EXE_SC="/home/sysop/seiscomp/bin/scquery"

# ==============================================================================
# FUNCIONES DE VALIDACIÓN Y CASTEO
# ==============================================================================

# Función para validar el nombre del archivo de forma segura en Bash
validar_nombre_archivo() {
    if [[ -z "$1" ]]; then
        return 1
    fi
    if [[ "$1" =~ [[:space:]/\\\?\%\*\:\|\"\'\<\>] ]]; then
        return 1
    fi
    return 0
}

# Función para validar el formato de entrada plano (14 números exactos: YYYYMMDDHHMMSS)
validar_formato_entrada() {
    local fecha_raw="$1"
    if [[ ! "$fecha_raw" =~ ^[0-9]{14}$ ]]; then
        return 1
    fi
    return 0
}

# Función para transformar YYYYMMDDHHMMSS a YYYY-MM-DD HH:MM:SS
castear_fecha() {
    local entrada="$1"
    local anio="${entrada:0:4}"
    local mes="${entrada:4:2}"
    local dia="${entrada:6:2}"
    local hora="${entrada:8:2}"
    local min="${entrada:10:2}"
    local seg="${entrada:12:2}"
    
    echo "${anio}-${mes}-${dia} ${hora}:${min}:${seg}"
}

# Función para validar si es una fecha real en el calendario
validar_fecha_real() {
    if ! date -d "$1" >/dev/null 2>&1; then
        return 1
    fi
    return 0
}

# Función para obtener los segundos Unix (Epoch) de una fecha
obtener_epoch() {
    date -d "$1" +"%s"
}

# ==============================================================================
# SOLICITUD Y VALIDACIÓN DE DATOS (AL INICIO)
# ==============================================================================
echo "=== Configuración de extracción de datos remotos ==="
echo "Por favor, ingrese los parámetros requeridos."
echo "----------------------------------------------------"

# 1. Solicitar y validar Nombre del Archivo de Salida
while true; do
    read -p "1. Ingrese el NOMBRE DEL ARCHIVO DE SALIDA (Ej: datos): " NOMBRE_SALIDA
    if validar_nombre_archivo "$NOMBRE_SALIDA"; then
        break
    else
        echo ">> Nombre inválido. No use espacios ni caracteres especiales."
    fi
done

# 2. Solicitar, validar y castear Fecha de Inicio
while true; do
    read -p "2. Ingrese la FECHA DE INICIO (Formato: YYYYMMDDHHMMSS): " FECHA_INICIO_RAW
    if validar_formato_entrada "$FECHA_INICIO_RAW"; then
        FECHA_INICIO=$(castear_fecha "$FECHA_INICIO_RAW")
        
        if validar_fecha_real "$FECHA_INICIO"; then
            EPOCH_INICIO=$(obtener_epoch "$FECHA_INICIO")
            break
        else
            echo ">> La fecha de inicio no existe en el calendario. Intente de nuevo."
        fi
    else
        echo ">> Formato incorrecto. Use exactamente 14 números sin signos (Ej: 20260601000000)."
    fi
done

# 3. Solicitar, validar, castear y comparar Fecha de Término
while true; do
    read -p "3. Ingrese la FECHA DE TÉRMINO (Formato: YYYYMMDDHHMMSS): " FECHA_TERMINO_RAW
    if validar_formato_entrada "$FECHA_TERMINO_RAW"; then
        FECHA_TERMINO=$(castear_fecha "$FECHA_TERMINO_RAW")
        
        if validar_fecha_real "$FECHA_TERMINO"; then
            EPOCH_TERMINO=$(obtener_epoch "$FECHA_TERMINO")
            
            # Validación cronológica inter-mensual/anual
            if [ "$EPOCH_TERMINO" -gt "$EPOCH_INICIO" ]; then
                break
            else
                echo ">> ERROR: La fecha de término debe ser posterior a la fecha de inicio."
                echo "   Inicio ingresado: $FECHA_INICIO"
            fi
        else
            echo ">> La fecha de término no existe en el calendario. Intente de nuevo."
        fi
    else
        echo ">> Formato incorrecto. Use exactamente 14 números sin signos (Ej: 20260613235959)."
    fi
done

echo -e "\n[+] Cronología y datos validados con éxito."
echo "    -> Rango transformado: '$FECHA_INICIO' hasta '$FECHA_TERMINO'"
echo "----------------------------------------------------------------"

# ==============================================================================
# EJECUCIÓN REMOTA Y TRANSFERENCIA
# ==============================================================================

# Construimos el comando forzando la carga del entorno exacto de SeisComP6 que tienes en tu .bashrc
COMANDO_REMOTO="
    mkdir -p $DIR_REMOTO && cd $DIR_REMOTO
    
    # Exportamos manualmente las variables de SeisComP6 declaradas en tu .bashrc
    export SEISCOMP_ROOT='/home/sysop/seiscomp'
    export PATH='/home/sysop/seiscomp/bin:\$PATH'
    export LD_LIBRARY_PATH='/home/sysop/seiscomp/lib:\$LD_LIBRARY_PATH'
    export PYTHONPATH='/home/sysop/seiscomp/lib/python:\$PYTHONPATH'
    export MANPATH='/home/sysop/seiscomp/share/man:\$MANPATH'
    export SEISCOMP_SCRIPT_EXPORT_CONFIG=/home/sysop/.seiscomp_export_script.ini
    
    # Ejecutamos scquery con el entorno completamente recreado
    scquery eventFilter '$FECHA_INICIO' '$FECHA_TERMINO' --print-column-name > '$NOMBRE_SALIDA'
"

echo "[+] Conectando a $IP_REMOTA vía SSH para generar el archivo..."
ssh "${USUARIO_REMOTO}@${IP_REMOTA}" "/bin/bash -c \"$COMANDO_REMOTO\""

if [ $? -eq 0 ]; then
    echo "[+] Archivo '$NOMBRE_SALIDA' generado correctamente en el servidor."
    echo "[+] Copiando el archivo a la máquina local..."
    
    # Trae el archivo al directorio actual local (./)
    scp "${USUARIO_REMOTO}@${IP_REMOTA}:${DIR_REMOTO}/${NOMBRE_SALIDA}" ./
    
    if [ $? -eq 0 ]; then
        echo "----------------------------------------------------------------"
        echo "[+] Archivo original '$NOMBRE_SALIDA' copiado localmente."
        echo "[+] Iniciando transformación a formato CSV estructurado..."
        
        # Nombre del archivo CSV final de salida
        ARCHIVO_CSV="${NOMBRE_SALIDA}.csv"
        
        # Procesamiento estándar forzando entorno internacional (LC_ALL=C)
        LC_ALL=C awk -F '|' '
        BEGIN {
            # Encabezado iniciando con coma
            print ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista,Event_id,P_phases,S_phases"
            idx = 0
        }
        NR > 1 {
            # Limpiar espacios en blanco al inicio y final de cada campo
            for(i=1; i<=NF; i++) {
                gsub(/^[ \t]+|[ \t]+$/, "", $i)
            }
            
            # Validar que la línea tenga datos y no esté vacía
            if ($1 != "") {
                
                # Extraer Fecha_Hora ($2) y aplicar el DOBLE ESPACIO estricto
                fecha_hora_raw = $2
                gsub(/ /, "  ", fecha_hora_raw)
                
                # Formatear e imprimir usando los puntos nativos del archivo
                printf "%d,%s,%.3f,%.3f,%.1f,%.1f,%s,%s,%s,%s,%s\n", 
                    idx++,               # Índice autoincremental (0, 1, 2...)
                    fecha_hora_raw,      # Fecha y Hora con DOBLE espacio
                    $3,                  # Latitud (redondea correctamente a 3 decimales)
                    $4,                  # Longitud (redondea correctamente a 3 decimales)
                    $5,                  # Prof. (depth, redondea a 1 decimal)
                    $7,                  # Mag. (mag_value, redondea a 1 decimal)
                    $6,                  # Tipo_mag (mag_type)
                    $8,                  # Analista (author)
                    $1,                  # id del evento origen
                    $9,                  # número de fases P
                    $10                  # número de fases S
            }
        }' "$NOMBRE_SALIDA" > "$ARCHIVO_CSV"
        
        if [ $? -eq 0 ]; then
            echo "[¡ÉXITO!] El archivo formateado '$ARCHIVO_CSV' se generó correctamente."
            echo "----------------------------------------------------------------"
        else
            echo "[-] Error al procesar el archivo de texto con AWK."
        fi
    else
        echo "[-] Error: No se pudo transferir el archivo mediante SCP."
    fi

else
    echo "[-] Error: Falló la ejecución de scquery en el servidor remoto."
fi