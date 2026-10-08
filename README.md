# revisaapis

## Documentación

- `docs/manual_usuario.md` — manual de usuario (funciones, botones y capturas).
- `docs/manual_tecnico.md` — manual técnico (scripts, interfaces y parámetros
  ajustables).
- `docs/esquema_seiscomp.md` / `docs/esquema_seiscomp.txt` — esquema de la base
  de SeisComp. `docs/esquema_seiscomp_mysql.sql` es la versión importable en
  MySQL Workbench (diagrama EER).
- `docs/versiones/` — manuales anteriores archivados.

## Uso

```
./supervisor.sh
```

Sin parámetros abre la **ventana de solicitud de catálogos**: se pide el
inicio, el fin y la contraseña del servidor remoto. Desde ahí se bajan los
catálogos de Seisan (`select.out`) y eventquery
(`eventquery_<ini>_<fin>.csv`) por SSH/SCP, y se exporta la ventana de SeisComp
para el mismo período. Al terminar se abre la ventana principal de revisión,
donde se pulsa «Procesar catálogos» cuando se quiera procesar.

Los tres catálogos se reusan: si el archivo de esa ventana ya está en disco, no
se vuelve a consultar.

Al abrir, la ventana detecta las ventanas de catálogos que ya están en la carpeta
y precarga la más reciente (si hay varias, lo avisa), así «Ya los tengo» funciona
sin tipear las fechas. La ventana tiene dos caminos: «Solicitar y descargar» baja
lo que falte del servidor, y «Ya los tengo (seguir)» exige que los catálogos de
esa ventana (`select_<ini>_<fin>.out` y `eventquery_<ini>_<fin>.csv`) ya estén en
la carpeta de ejecución; si faltan, los lista en rojo y no continúa. Debajo de
los campos hay un indicador neutro de qué archivos hay para la ventana escrita (y
si la exportación de SeisComp se va a reusar o a consultar la base).

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

### Procesamiento y pestañas

La barra lateral tiene un solo botón de trabajo, «Procesar catálogos»: corre el
análisis (proc_query -> revisaselect -> revisacollect -> compara -> atribución a
SeisComp -> excluidos -> repetidos) y, con los mismos catálogos ya en disco,
genera el JSON de todas las fuentes (Seisan, eventquery, SeisComp y los dos «No
publicados») y arma las tres pestañas de catálogo. Una sola pulsación deja toda
la información disponible para consultar. Al volver a pulsarlo se confirma y se
rehace solo lo necesario.

Al abrir, la aplicación reconoce qué hay en el directorio de ejecución: cada
pestaña queda marcada como con datos, pendiente de procesar o sin datos. Los
paneles cuyo CSV de entrada existe pero cuyo JSON falta o quedó viejo se generan
en segundo plano al abrir su pestaña, sin pulsar nada.

La barra lateral se organiza en tres bloques: **Procesar** (el botón «Procesar
catálogos»), **Consultar** («Ver repetidos» y los listados de «No publicados de
Seisan» y «No publicados de SeisComp», que muestran los eventos en una tabla) y
**Re-exportar** (Seisan / eventquery / SeisComp). De estos últimos solo se
habilita el catálogo que falta o que cambió desde el último procesamiento.

### Extracción tolerante y re-exportación

`solicita_catalogos.py` ya no corta si falla uno de los tres catálogos: baja lo
que pueda, y al abrir la aplicación avisa cuáles quedaron afuera (etiqueta en la
barra, diálogo y Registro). Solo en ese caso se habilita el botón de
«Re-exportar» correspondiente.

- **SeisComp** se re-exporta corriendo el exportador (sin contraseña).
- **Seisan / eventquery** se vuelven a bajar por SSH; la aplicación pide la
  contraseña en el momento.

Re-importar **cualquier** catálogo obliga a rehacer el análisis, porque la
información cruza datos entre ellos (comparación publicados vs procesados,
atribución a SeisComp, repetidos, No publicados, mapas y perfiles). Por eso, al
pulsar «Re-exportar» aparece un popup que lo avisa; si se acepta, tras la bajada
el análisis corre solo (`_accion_procesar`), sin preguntar de nuevo.

El tilde **«Forzar actualización»** (sección «Re-exportar») habilita los botones
aunque el catálogo figure al día, para poder rebajarlo a propósito (por ejemplo
si se corrigió la fuente en el servidor). Sin el tilde, el botón solo se
habilita si el catálogo falló, falta o cambió.

### Pestañas de la ventana de revisión

`app.py` agrupa las pestañas en filas, con el encabezado arriba y las fuentes
abajo: `Registro`, `Panel de mapas y perfiles` (Seisan / eventquery / SeisComp), `No publicados`
(Seisan / SeisComp), `No actualizados` (Seisan / SeisComp) y `Catálogo`
(SeisComp / Seisan / eventquery). Se agrupan porque las nueve pestañas en una
sola tira piden 947 px de ancho y quedaban cortadas; con los nombres cortos que
aporta el grupo la barra mide ~256 px.

La barra se dibuja a mano y la tira nativa del `Notebook` queda oculta
(`style.layout("TNotebook.Tab", [])`), así que la pestaña activa la marca el
propio botón. Los botones se indexan por frame y no por texto: «SeisComp»
aparece en tres grupos distintos.

La barra arranca a la altura del botón «Procesar catálogos» (el desfasaje se
mide al mapear la ventana, no se escribe un número fijo). La cabecera lleva solo
el título y, en una fila aparte debajo, la carpeta de ejecución a la derecha; el
archivo de entrada no va ahí porque con su ruta completa los textos se pisaban
—queda en el Registro cuando se procesan los catálogos.

El listado de «No actualizados» muestra los eventos que sí están publicados pero
cuyos parámetros (latitud, longitud, profundidad o magnitud) no coinciden con la
solución local. Muestra, por cada parámetro, el valor local y el publicado, más
los deltas, y una columna final que dice cuál o cuáles discreparon. No recalcula
nada: lee `datos/atribucion_<fuente>.csv`, que escribe `compara.py` al correr el
análisis.

La comparación es **numérica**, a la precisión con la que se manejan los datos
(coordenadas a 3 decimales; profundidad y magnitud a 1), y vive en
`comparacion.py`, compartida por `compara.py` y `revisa_seiscomp.py`. Comparar
por texto marcaba como distinto el mismo valor escrito con distinta cantidad de
decimales (`-31.64` contra `-31.639999...`).

El CSV trae una fila por cruce y un mismo evento local puede tener más de un
cruce, así que el listado agrupa por evento y muestra el mejor (menor Δt), que
es lo mismo que hace el informe `informes/no_act_*_estricto.txt`.

El panel de SeisComp es solo la lista de eventos, a todo el ancho. Al hacer
**doble clic** en una fila (o Enter con la fila elegida) los parámetros del
evento (y el botón «Estaciones») abren en una ventana aparte, que se reutiliza al
cambiar de evento y **no bloquea** la lista: son ventanas de consulta, sin
captura de entrada, así que se puede seguir navegando con ellas abiertas. Antes
el detalle iba embebido al lado de la lista y abajo quedaba cortado, justo donde
está ese botón; separarlo deja ver todo sin apretar ninguna mitad. Al abrir la
pestaña, la ventana principal se agranda para que entren las columnas de la
lista.

Las ventanas emergentes se abren ocultas y se muestran recién con su tamaño y
posición finales (no se ve el salto desde la esquina), no pasan del tope de la
app (1920x1080) y se centran sobre el monitor de la ventana principal, no sobre
el escritorio virtual: con dos monitores, centrar en el escritorio completo las
dejaba a caballo entre ambos. Cuando una tabla no entra en el ancho, se desplaza
con su barra horizontal (todas las tablas la tienen).

### Estaciones del evento

Al seleccionar un evento en el panel de SeisComp, el botón «Estaciones» abre una
ventana con dos solapas: **Con arribos**, con las llegadas de la solución
preferida agrupadas por estación (la que estaba embebida en el detalle), y **Sin
arribos**, con las estaciones del inventario que quedaron dentro del radio y no
tienen arrivals/picks asociados al **origen preferido**. Ambas se pueden
descargar como planilla. El encabezado, siempre visible sobre las dos solapas,
muestra los **parámetros del evento** (fecha/hora, magnitud, profundidad, lat/lon,
región, agencia) y el **analista** en negrita, para no perder de vista qué evento
se está mirando.

La tabla de «Con arribos» muestra, por cada llegada, si el pick fue **manual o
automático** (`pick.m_evaluation_mode`), con el autor, la agencia y el método.
Los picks manuales se resaltan —fuerte si esa llegada entró a la solución
(`Usada`), suave si quedó afuera—, y tanto el encabezado de la ventana como el
de cada estación desglosan las usadas y las sin usar por modo (por ejemplo,
`11 usadas (3 manuales, 8 automáticas)`). En un pick manual el autor es el
analista y el método va vacío; en uno automático el autor es el daemon
(`scautopic…`) y el método, el del autopicker (p. ej. `AIC`).

Las de «Sin arribos» salen del inventario, no de las fases: una estación sin
arribos no tiene fila de llegada, así que el `INNER JOIN` de las fases descarta
justo lo que se busca. **No son estaciones que no grabaron.** La base de
metadatos de SeisComp no sabe qué estaciones tienen formas de onda de cada evento
—eso vive en el archivo de ondas—, así que la ayuda de la solapa y la columna
`actividad_ventana` («Con actividad ±24 h»: cuántos otros eventos tienen picks
de esa estación dentro de ±24 h, o sea 24 h antes y 24 h después) son un
indicador indirecto de operación, no una prueba.

La cadena de inventario se valida entera por evento: red, estación, sensor
location y stream tienen que estar vigentes en la hora del evento. Una estación
sin `sensorlocation`/`stream` vigente no se lista y se cuenta aparte (el aviso
`descartadas_sin_stream` de la marca y del final de la exportación). Las
columnas `loc_ref`/`cha_ref` son el stream de **referencia** (no el único) y
`streams_vigentes` dice cuántos había.

Además se acota a los **bindings** de SeisComp (tabla `configstation`, módulos
habilitados): solo las estaciones que el sistema tiene configurado procesar.
Puede haber dataless cargado sin binding creado, y esas no se listan porque
SeisComp no las trabaja (en esta base son 334 de 477). El binding es la config
**actual** y no tiene épocas, así que en eventos históricos es una aproximación;
si no se encuentran bindings, no se filtra y se avisa.

El radio por defecto es de 400 km (`--radio-km`, se pregunta al exportar y se
puede bajar para catálogos grandes) y la ventana de actividad, de 24 horas
(`--actividad-h`); la distancia se calcula con haversine, porque no hay PostGIS.
**El radio es exclusivo de SeisComp**: corta la lista de estaciones sin arribos
de sus eventos y no tiene nada que ver con los catálogos de Seisan ni de
eventquery. Las columnas van ordenadas por distancia. El resaltado cruza dos
umbrales independientes del radio: el de **cerca** (≤ 50 km por defecto,
ajustable en la ventana) y la actividad ±24 h. Las cuatro categorías, con su
lectura: *cerca y con actividad* (fondo destacado) —estaba operando y cerca,
**no se usó**—; *con actividad, más lejos* (verde); *cerca, sin actividad*
(negrita) —**¿caída?**—; y *lejos, sin actividad* (normal). El umbral de cerca
solo cambia el color, **no recorta la lista**. El reuso de una exportación exige
que el radio coincida con el anotado en la marca: cambiarlo obliga a re-exportar.

Como esa lista crece con los eventos y con el radio (en el histórico completo
pasa de un gigabyte), antes de exportar la interfaz **estima el tamaño** en MB
—con una muestra de eventos, en décimas de segundo— y, si supera los 200 MB
(`AVISO_NO_PICADAS_MB`), pide confirmación. Si la base no responde, se exporta
igual sin el aviso. El exportador imprime la misma estimación en el registro.

El **encabezado de la ventana Estaciones** tiene los controles de **radio** y de
**cerca (km)** y tres acciones, siempre visibles. «Cerca (km)» es el umbral de
resaltado (≤ 50 km por defecto): solo cambia los colores, no recorta la lista.
«Filtrar» recorta hacia abajo la lista exportada, sin tocar la base: sirve para
mirar un radio más chico que el del corte, y de paso reaplica el umbral de cerca.
«Ampliar (consulta a la base)» recalcula, **para ese evento**, el inventario
vigente a su hora y la actividad de las estaciones, y abre el resultado en una
ventana aparte —con su propia descarga— para no pisar el corte exportado. «Todo
(sin límite)» hace lo mismo pero sin tope de distancia: trae todas las
estaciones del inventario con la cadena de épocas vigente a la hora del evento.
Si la ampliación trae más de `UMBRAL_AVISO_AMPLIADO` (2000) filas, pide
confirmación antes de mostrarla. La ampliación necesita conexión a la base; si no
está, avisa y deja el corte exportado como estaba.

La columna de actividad se llama **«Actividad ±24 h»** y, arriba de la tabla, hay
una línea fija que aclara qué mide: «con actividad ±24 h» es que la estación picó
otros eventos entre 24 h antes y 24 h después del origen (48 h en total). Es un
indicador indirecto: 0 no prueba que la estación haya estado caída.

El archivo ya trae los campos `waveform_status`, `availability_source`,
`cobertura_desde` y `cobertura_hasta` para cuando se integren SDS,
scardac/DataAvailability o FDSN Availability. Hoy `waveform_status` vale
`NO_CONSULTADO` y los otros van vacíos: no se afirma nada sobre las formas de
onda.

Esta ventana necesita el tercer archivo. Las exportaciones anteriores a este
cambio no lo tienen: la solapa avisa que hay que re-exportar en vez de mostrar una
tabla vacía, que se leería como «no había ninguna estación cerca».

### Análisis rápido de sin arribos cercanos

En el catálogo de SeisComp, **arriba de la lista y al lado de «Exportar lista»**,
hay un botón **«Análisis rápido»** (solo si la exportación trae el archivo de sin
arribos). Recorre **TODO el catálogo** —no usa el filtro del panel, y lo advierte—
y busca los eventos que tienen estaciones sin arribos **cercanas** (dentro de un
umbral configurable, 50 km por defecto), para acotar la revisión a esos casos.

Abre una ventana con dos pestañas: **Contexto** (qué mide y cómo se lee) y
**Resultados** (la tabla, con el umbral editable y «Recalcular», «Descargar» y
doble clic al detalle del evento). La lista trae los datos clave del evento y el
operador, más cuántas son *cercanas con actividad* (estaba operando y no se usó →
calidad de la solución) y *cercanas sin actividad* (posible caída). Se ordena por
severidad por defecto, y se puede **reordenar por cualquier columna** haciendo
clic en su encabezado (ascendente → descendente → vuelta al orden por severidad;
la columna activa se marca con ▲/▼). La descarga sale en **formato largo**,
siguiendo el orden en pantalla: una fila por evento y estación cercana, con la
clasificación, la distancia, la actividad y la estación.

### Esquema de la base de SeisComp

`docs/esquema_seiscomp.md` documenta las tablas de SeisComp que consulta el
proyecto, sus relaciones (por `_parent_oid` y por id público a través de
`publicobject`) y una descripción de cada una. Hay una versión en texto plano en
`docs/esquema_seiscomp.txt`, sin el diagrama Mermaid.

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

## Qué se genera y qué no

El flujo escribe dos cosas de naturaleza distinta, y la diferencia importa porque
determina qué se puede borrar sin romper la app.

**Caché: se genera siempre y no se borra.** Son los resultados que la app relee al
reabrir, gracias a una comparación de fechas contra su entrada. Borrarlos obliga a
repetir el análisis:

- `datos/salida_collect.csv` (collect local), `datos/new_2_<base>.csv`,
  `datos/todos_eventquery.csv`, `datos/excluidos.csv`, `datos/seiscomp_parametros.csv`
- `datos/atribucion_<fuente>.csv`, `datos/no_pub_desde_2_5_*estricto.csv`
- `datos/eventos_<vista>.json`, `datos/conteo_perfiles_<vista>.json`
- `informes/rep_*.txt`, `informes/rep_seisan_exclu.txt`,
  `informes/no_act_*estricto.txt` (lo usa `app.py` para distinguir «el análisis
  nunca corrió» de «corrió y no encontró cruces»), `informes/excluidos.txt`
- `ploteo/percibidos.txt`, y en `trabajo/` el `newcollect.txt` final

**Entregables: no se generan salvo que los pidas.** No los lee nadie y se
reconstruyen desde la caché, así que la app ofrece descargarlos a mano:

- Los listados con tabla de «No actualizados», «No publicados» y «Ver repetidos»,
  y los paneles y mapas de `plotear.py`, tienen botón de descarga. Escriben en
  `descargas/`, en CSV o en TXT separado por tabulaciones.
- Los entregables automáticos del pipeline (`cabeceras.txt`, `revisar.txt`,
  `constation0.txt`, `sinestructura.txt`, `no_pub_todos_*.txt`,
  `no_pub_desde_2_5_*.txt`, `*amplio.csv`, `analistas/*.csv` y
  `sospechosos_<vista>.csv`) se escriben en `descargas/` solo con:

```
RV_ENTREGABLES=1 ./supervisor.sh <archivo_entrada.csv> <archivo_salida.dat>
```

Sin ese flag los scripts siguen su curso y las escrituras caen a un descarte, sin
cortarse a mitad.

### Descargas

Todo lo que se baja va a `descargas/` dentro de la carpeta del análisis, y se abre
con «Abrir carpeta» en la barra lateral. El CSV usa `utf-8-sig` (el BOM que necesita
Excel para no romper los acentos) y el TXT va sin BOM, porque el BOM se le cuelga a
la primera columna y rompe `cut -f1` y `pandas.read_csv`:

- **CSV** separado por comas.
- **TXT** separado por tabulaciones, que pega directo en las planillas que se usan
  para revisar y distribuir.

El diálogo recuerda el formato de la descarga anterior. En «Ver repetidos» no hay
diálogo: el informe viene alineado por espacios, no es una tabla, y guardarlo como
CSV lo volvía ilegible, así que siempre se baja como `.txt` con el contenido tal
cual.

En las vistas con tabla, «Descargar» arma el archivo con el filtro y el orden que
se ven en pantalla, y «Descargar todo» lo escribe entero. En el panel de análisis,
«Descargar» pregunta el ámbito: el perfil de la fila seleccionada, todos los
perfiles visibles o los eventos sin perfil, con la cantidad de cada uno. Si el
filtro «Solo sospechosos» está prendido, solo entran los eventos sospechosos. En
«Ver repetidos» la ventana muestra solo las primeras 2000 líneas para seguir siendo
usable, pero la descarga baja el informe completo.

Al escribir en las tablas se respeta lo que se está mostrando, incluido el guion
de «sin dato»: un vacío en el archivo significa que el dato no está, y no que valga
cero.

## Conexión remota

- Servidor: `sysopr@10.54.217.9` (configurable en `traer_catalogos.py`).
- Directorio de trabajo remoto: `tmp` (se crea si no existe).
- El catálogo de eventquery se baja con el binario remoto `eventquery2` (la
  versión nueva). La vieja (`eventquery`) traía soluciones duplicadas para un
  mismo evento, por eso no se usa.
- La contraseña se pide en la ventana y se entrega a `ssh`/`scp` con
  `SSH_ASKPASS` + `SSH_ASKPASS_REQUIRE=force`; no se pasa por la línea de
  comandos ni se necesita `sshpass`.
- El `trabajo/select.inp` local se borra apenas se sube: el `select` remoto corre
  con la copia que queda en `tmp/`, y cada corrida (incluida «Re-exportar»)
  lo regenera desde `plantillas/select.inp`.

