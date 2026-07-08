import subprocess
import sys
import os
import re
from datetime import datetime

# ==============================================================================
# CONFIGURACIÓN DE RED Y ENTORNOS REMOTOS (CATÁLOGO WEB)
# ==============================================================================
IP_REMOTA = "10.54.217.9"
USUARIO_REMOTO = "sysop"
DIR_REMOTO = "/home/sysop/tmp"
EXE_EVENTQUERY = "/home/sysop/bin/eventquery"

def solicitar(nombre, ejemplo, tipo_dato, obligatorio=False):
    while True:
        prompt = f"🔹 {nombre:<25} (Ej: {ejemplo})"
        prompt += "\t[OBLIGATORIO]: " if obligatorio else "\t[ENTER para omitir]: "
        
        try:
            entrada = input(prompt).strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\n[-] Operación cancelada por el usuario.")
            sys.exit(1)

        if not entrada:
            if obligatorio:
                print(f"   Error: El campo '{nombre}' no puede estar vacío.")
                continue
            return None
        
        # VALIDACIONES
        if tipo_dato == "tiempo_corto":
            if re.match(r"^\d{14}$", entrada):
                try:
                    dt = datetime.strptime(entrada, "%Y%m%d%H%M%S")
                    return dt.strftime("%Y-%m-%dT%H:%M:%S")
                except ValueError:
                    print("   Error: Fecha o hora inválida (ej. mes 13 o día 32).")
            else:
                print("   Error: Use el formato AAAAMMDDHHMMSS (14 dígitos).")
        
        elif tipo_dato == "numero":
            try:
                float(entrada)
                return entrada
            except ValueError:
                print("   Error: Ingrese un valor numérico válido.")
        
        elif tipo_dato == "texto":
            # Sanear la entrada eliminando caracteres peligrosos para SSH
            return re.sub(r"[`$;\"']", "", entrada)

# ==============================================================================
# INTERFAZ DE USUARIO (CAPTURA DE PARÁMETROS)
# ==============================================================================
print("\n" + "="*70)
print("             INGRESO DE PARÁMETROS PARA EL CATÁLOGO WEB")
print("="*70)

while True:
    print("Ingrese tiempo en formato: AAAAMMDDHHMMSS")
    start = solicitar("Start Time", "20260501000000", "tiempo_corto", obligatorio=True)
    end   = solicitar("End Time",   "20260507235959", "tiempo_corto", obligatorio=True)
    
    t_start = datetime.strptime(start, "%Y-%m-%dT%H:%M:%S")
    t_end   = datetime.strptime(end, "%Y-%m-%dT%H:%M:%S")
    
    if t_end > t_start:
        break
    else:
        print("\n ❌ ERROR LÓGICO: La fecha de FIN debe ser posterior a la de INICIO.")
        print("   Por favor, ingrese el rango de tiempo nuevamente.\n")

output = solicitar("Nombre archivo salida", "datos.csv", "texto", obligatorio=True)
if not output.lower().endswith('.csv'):
    output += '.csv'

directorio = solicitar("Nombre carpeta imágenes", "analista", "texto", obligatorio=True)

print("-" * 70)
min_lat = solicitar("Latitud Mínima", "-38.5", "numero")
max_lat = solicitar("Latitud Máxima", "-32.0", "numero")
min_lon = solicitar("Longitud Mínima", "-75.0", "numero")
max_lon = solicitar("Longitud Máxima", "-69.5", "numero")
min_dep = solicitar("Profundidad Mínima", "0", "numero")
max_dep = solicitar("Profundidad Máxima", "150", "numero")
min_mag = solicitar("Magnitud Mínima", "3.0", "numero")
max_mag = solicitar("Magnitud Máxima", "9.0", "numero")

# ==============================================================================
# CONSTRUCCIÓN DE ARGUMENTOS PARA EVENTQUERY
# ==============================================================================
args_list = ["--start-time", start, "--end-time", end]

opcionales = [
    ("--min-latitude", min_lat), ("--max-latitude", max_lat),
    ("--min-longitude", min_lon), ("--max-longitude", max_lon),
    ("--min-depth", min_dep), ("--max-depth", max_dep),
    ("--min-magnitude", min_mag), ("--max-magnitude", max_mag)
]

for flag, valor in opcionales:
    if valor is not None:
        args_list.extend([flag, valor])

# Añadir el archivo de salida al final
args_list.append(output)

# Unimos los argumentos en una sola cadena para el entorno SSH remoto
args_remotos_str = " ".join(args_list)

# ==============================================================================
# EJECUCIÓN REMOTA VÍA SSH (USANDO SUBPROCESS)
# ==============================================================================
print("\n" + "="*70)
print(f"[+] Conectando a {USUARIO_REMOTO}@{IP_REMOTA} vía SSH...")
print("="*70 + "\n")

# Comando estructurado para asegurar el directorio y correr eventquery
comando_remoto = f"mkdir -p {DIR_REMOTO} && cd {DIR_REMOTO} && {EXE_EVENTQUERY} {args_remotos_str}"

try:
    # Ejecutamos el SSH compartiendo los flujos estándar (el usuario verá el progreso en vivo)
    ssh_resultado = subprocess.run(
        ["ssh", f"{USUARIO_REMOTO}@{IP_REMOTA}", f"/bin/bash -c '{comando_remoto}'"],
        check=True
    )
    
    print("\n[+] Consulta finalizada con éxito en el servidor remoto.")
    
    # ==============================================================================
    # TRANSFERENCIA DEL ARCHIVO GENERADO VÍA SCP
    # ==============================================================================
    # Definimos la ruta local donde se está ejecutando el script
    ruta_local_destino = os.getcwd()
    print(f"[+] Descargando '{output}' hacia la ruta local: {ruta_local_destino}")
    
    subprocess.run(
        ["scp", f"{USUARIO_REMOTO}@{IP_REMOTA}:{DIR_REMOTO}/{output}", ruta_local_destino],
        check=True
    )
    
    print("\n" + "="*70)
    print(f" 🌟 [¡ÉXITO!] Proceso completo terminado.")
    print(f"    -> Archivo descargado: {os.path.join(ruta_local_destino, output)}")
    print(f"    -> Carpeta asignada:  {directorio}")
    print("="*70 + "\n")

except subprocess.CalledProcessError as e:
    print(f"\n❌ Error crítico durante la ejecución del comando del sistema: {e}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"\n❌ Error inesperado: {e}", file=sys.stderr)
    sys.exit(1)