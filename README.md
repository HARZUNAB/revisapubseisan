# revisaapis

## Uso

```
./supervisor.sh
```

Sin parámetros abre la **ventana de solicitud de catálogos**: se pide el
inicio, el fin y la contraseña del servidor remoto. Desde ahí se bajan los
catálogos de Seisan (`select.out`) y eventquery
(`eventquery_<ini>_<fin>.csv`) por SSH/SCP, y se exporta la ventana de SeisComp
para el mismo período. Al terminar se abre la ventana principal de revisión,
donde se pulsa «Ejecutar análisis» cuando se quiera procesar.

Los tres catálogos se reusan: si el archivo de esa ventana ya está en disco, no
se vuelve a consultar.

La ventana tiene dos caminos: «Solicitar y descargar» baja lo que falte del
servidor, y «Ya los tengo (seguir)» exige que los catálogos de esa ventana
(`select_<ini>_<fin>.out` y `eventquery_<ini>_<fin>.csv`) ya estén en la carpeta
de ejecución; si faltan, los lista en rojo y no continúa. Debajo de los campos
hay un indicador neutro de qué archivos hay para la ventana escrita (y si la
exportación de SeisComp se va a reusar o a consultar la base).

El avance se muestra con una barra por etapas y un cronómetro, más una línea
discreta con lo que se está obteniendo en cada momento («Obteniendo catálogos…»,
«Obteniendo SeisComp…»): el porcentaje es orientativo, porque las consultas
remotas y a la base no tienen un total conocido de antemano.

### Componentes

- `traer_catalogos.py`: capa de red (SSH/SCP) sin interfaz. Genera el
  `select.inp` a partir de `plantillas/select.inp` y baja `select.out` y el CSV
  de eventquery.
- `solicita_catalogos.py`: ventana de solicitud y orquestación; al terminar
  lanza `app.py`.
- `plantillas/select.inp`: plantilla del `select` de Seisan. Solo se reemplazan
  los valores de `Start time` y `End time`; el resto se copia byte a byte.

### Pestañas de la ventana de revisión

`app.py` agrupa las pestañas en filas, con el encabezado arriba y las fuentes
abajo: `Registro`, `Panel` (Seisan / eventquery / SeisComp), `No publicados`
(Seisan / SeisComp), `No actualizados` (Seisan / SeisComp) y `Catálogo`
(SeisComp / Seisan / eventquery). Se agrupan porque las nueve pestañas en una
sola tira piden 947 px de ancho y quedaban cortadas; con los nombres cortos que
aporta el grupo la barra mide ~256 px.

La barra se dibuja a mano y la tira nativa del `Notebook` queda oculta
(`style.layout("TNotebook.Tab", [])`), así que la pestaña activa la marca el
propio botón. Los botones se indexan por frame y no por texto: «SeisComp»
aparece en tres grupos distintos.

La barra arranca a la altura del botón «Ejecutar análisis» (el desfasaje se mide
al mapear la ventana, no se escribe un número fijo). La cabecera lleva solo el
título y, en una fila aparte debajo, la carpeta de ejecución a la derecha; el
archivo de entrada no va ahí porque con su ruta completa los textos se pisaban
—queda en el Registro cuando se ejecuta el análisis.

El listado de «No actualizados» muestra los eventos que sí están publicados pero
cuyos parámetros (latitud, longitud o profundidad) no coinciden con la solución
local, con el evento local, lo publicado y los deltas. No recalcula nada: lee
`datos/atribucion_<fuente>.csv`, que escribe `compara.py` al correr el análisis.
El CSV trae una fila por cruce y un mismo evento local puede tener más de un
cruce, así que el listado agrupa por evento y muestra el mejor (menor Δt), que
es lo mismo que hace el informe `informes/no_act_*_estricto.txt`.

### Tamaño de la ventana

`ajuste.py` agranda la ventana cuando el contenido no entra, y **solo crece**:
nunca la achica, así que volver a una vista chica no devuelve el tamaño anterior.
Se apoya en lo que Tk dice que necesita cada contenido (`winfo_reqwidth` /
`winfo_reqheight`), acotado por un tope de 1920×1080 combinado con lo que admite
el gestor de ventanas (`wm_maxsize`, que ya descuenta el marco de la ventana).

Ojo con la fuente: **no se agranda**. Al crecer la ventana los textos de la
interfaz mantienen su tamaño en puntos, y en los paneles la figura de matplotlib
se estira (el lienzo va con `expand`), pero como el dpi no cambia, el texto que
dibuja matplotlib mide lo mismo. Lo que mejora es cuánta información entra: más
filas de tabla, las 1064 px de columnas del catálogo de eventquery sin barra
horizontal y más seismograma a la vista.

### Modo antiguo

Para un período suelto con el catálogo ya elegido:

```
./supervisor.sh <archivo_entrada.csv> <archivo_salida.dat>
```

## Conexión remota

- Servidor: `sysopr@10.54.217.9` (configurable en `traer_catalogos.py`).
- Directorio de trabajo remoto: `tmp` (se crea si no existe).
- La contraseña se pide en la ventana y se entrega a `ssh`/`scp` con
  `SSH_ASKPASS` + `SSH_ASKPASS_REQUIRE=force`; no se pasa por la línea de
  comandos ni se necesita `sshpass`.

