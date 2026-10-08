# Etapa 2 del frontend rápido: medidas en Windows (09/10/2026)

Las dos decisiones que la especificación
(`docs/superpowers/specs/2026-10-08-frontend-rapido-design.md`, «Decisiones para revisar»
3 y 4) deja a una medida en Windows:

- **R7**, esconder una ventana en lugar de destruirla: ¿cuánto se ahorra al volver a abrir
  «Parejas», «Ajustes» o la ventana de la pasada?
- **R3**, la lista de «Parejas»: ¿hace falta una tabla sobre un solo lienzo, bastan unas
  filas con menos widgets, o se queda como está?

Las dos se miden con `tests/rendimiento/etapa2_medir.py` (temporal, como los
`etapa2_*` que lo acompañan) en el trabajo `medida-etapa2` (Windows x64 y Linux x64, el
Python fijado del dispositivo: 3.14.8, Tk 9.0.4). La tarea 1 lo construye y lo lanza sobre
la rama con las etapas 1a y 1b; la tarea 12 lo repite sobre la rama con la etapa 2 y
decide. Esta nota recoge qué se mide, con qué regla se decide y lo que salió.

## Qué se mide

Cada medida es un proceso nuevo y en frío, con `--rondas` vueltas (siete en CI) más una de
calentamiento que se tira, y con el orden de las variantes alternado de una vuelta a otra.
Valen las medianas.

**Lista de «Parejas»** (`etapa2_tabla.py`), con 5, 10, 20 y 50 filas, de tres maneras:

| Variante | Qué es | Widgets por fila |
|---|---|---|
| `ref` | la `ListaParejas` del árbol | 7 (con el separador) |
| `ligera` | `etapa2_ligera.ListaLigera`: la casilla dentro de la etiqueta del nombre, las líneas entre filas sin separadores y diferenciada por nombre | 5 |
| `lienzo` | `etapa2_lienzo.ListaLienzo`: un `tk.Canvas`, las píldoras como imágenes SVG (solo Tk 9) | 0 |

Momentos (en ms, cada uno seguido de un `update()`): `construir` (crear la ventana y la
lista y enseñarla), `elegir` (otra fila), `refrescar` (`poner()` de los mismos nombres con
un tercio de los estados cambiados), `reemplazar` (`poner()` de nombres nuevos) y los
widgets de la lista. Tras cada `poner()` el hijo compara lo que la lista dibuja (nombre,
«local ↔ remoto», modo y estado) con lo que dicen las filas, y falla si difiere: una lista
más rápida que enseña otra cosa no decide nada.

**Rehacer o esconder** (`etapa2_reabrir.py`), con la ventana principal real:
`abrir-1` (en frío), `abrir-2` (cerrada y abierta otra vez: se rehace), `abrir-3` y
`reabrir-oculta` (la tercera apertura se esconde con `withdraw` en lugar de destruirla y se
enseña de nuevo con `ensenar()`, `grab_set()` y, si la pantalla la tiene, `aplicar()`), y lo
que cuesta cerrar de cada manera. «Parejas» pide el catálogo en cuanto se abre y repinta al
llegar: el hijo lo retiene (`common.catalog.load` espera a un `Event`) durante `abrir-1`,
`abrir-2` y `reabrir-oculta` y lo suelta después de cada medida, para que esa llegada no
caiga dentro de ninguna. Se comprobó con un contador de `ListaParejas.poner`: una llamada
por apertura y ninguna en la reapertura (con el catálogo suelto, dos por apertura).

**Perfil** (`etapa2_perfil.py`): un `cProfile` por momento (abrir «Parejas», llegar el
catálogo, abrir «Ajustes» y los apartados «Reparación» y «Configuración») con 5 y con 50
parejas, y el reparto del tiempo propio entre Python y Tcl/Tk.

## Reglas de decisión

- **R7, por ventana:** `ganancia = 1 − reabrir-oculta / abrir-2`. Se adopta para esa
  ventana con **0,50 o más** en Windows x64.
- **R3, con 20 filas y `construir`, en Windows x64:** el lienzo si `ligera − lienzo` es de
  **20 ms o más**; si no, las filas ligeras si `ref − ligera` es de **10 ms o más**; si no,
  ninguna. La ganadora no puede ser más de 5 ms peor que otra en `elegir` y `refrescar`.

El resumen del trabajo las aplica solo, en sus primeras líneas, pero las aplica la tarea 12
con la medida de la rama fusionada, no esta.

## Lo que hay que saber al leer los números

- **Un proceso quieto.** La ventana principal arranca dos hilos (la versión nueva y los
  conflictos) que con 50 parejas corren un segundo entero; el hijo espera a que acaben antes
  de medir, porque alargan la medida y se cuelan en el perfil. El driver de `correr.py` no
  espera, así que sus cifras de «abrir» pueden llevar dentro ese trabajo.
- **`lienzo` solo con SVG.** En un Tk 8.6 la variante se salta (`saltado: sin SVG`). Las
  píldoras del lienzo son aproximaciones del chip de verdad (disco, glifo y palabra), no
  las mismas piezas.
- **`ligera` tiene cinco widgets por fila.** Con cuatro habría que quitar un chip o el
  resalte de la fila, que cambia lo que se ve. Con cinco se ve lo mismo salvo el hueco exacto
  entre la casilla y el nombre y las esquinas de los chips: su padre es el marco del color de
  la línea, que el tema no conoce como superficie (`theme` lo avisa una vez por la salida de
  error y las esquinas se asientan sobre la superficie más cercana). Para adoptarla habría
  que resolverlo; para medir lo que cuesta, no importa.
- **La pasada.** La ventana de la pasada se prueba con `output_window()` y una orden que no
  hace nada; esconderla es limpiar su `Text` y volver a enseñarla. `reabrir-oculta` no
  cuenta el proceso que una pasada escondida tendría que lanzar: se mide aparte (`proceso`).
- **El perfil de «Ajustes».** «Ajustes» abre en «Configuración», así que hacer clic en ella
  primero no haría nada: se va antes a «Reparación» y luego a «Configuración». Un perfil
  alarga lo que es Python, y solo vale el reparto.

## Cómo repetirlo

```
xvfb-run -a -s "-screen 0 1920x1080x24" $PYTHON tests/rendimiento/etapa2_medir.py \
    --arbol . --trabajo /tmp/e2 --python $PYTHON --rondas 7 [--solo tabla|reabrir|perfil]
```

En CI, el trabajo `medida-etapa2` se lanza al subir cambios a los `etapa2_*` o al propio
workflow (tocarlo es la manera de repetirlo) y a mano. Deja en el resumen del trabajo las
decisiones y las tablas, y en el artefacto `medida-etapa2-<plataforma>` el `resumen.md`, el
`resultados.json` y el `crudo.jsonl` (todas las líneas, con las de los hijos que fallaron
marcadas).

## Primera lectura (B1)

Pendiente: se rellena con la primera ejecución en Windows x64 (tarea 1, paso 4), sobre la
rama con las etapas 1a y 1b (`b410738`). Aquí van las medianas por variante y tamaño, las
ganancias de reabrir y las primeras líneas del perfil de «Parejas» al abrir y al llegar el
catálogo (a dónde se van los 1,2 s).

## Decisión

Pendiente: la completa la tarea 12, con la medida de la rama fusionada.
