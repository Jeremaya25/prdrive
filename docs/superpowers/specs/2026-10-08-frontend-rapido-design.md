# Frontend rápido: el mismo Tk, dibujado de otra manera — diseño

Fecha: 08/10/2026. Estado: **diseño escrito, pendiente de que lo revise el dueño**.
Sustituye la forma de dibujar del rediseño de la 0.7.0 (el aspecto se queda: es el
del sistema «prdrive» de la 0.7.1). Las medidas que lo deciden están en
`docs/superpowers/pruebas/2026-10-08-banco-interfaz-resultados.md`.

Decidido con el dueño el 08/10/2026: el **enfoque A** (seguir con Tk y rehacer cómo
dibuja), los **presupuestos de tiempo** de abajo, que **lo que más importa es lo que
responde la ventana ya abierta**, y que se **queda una comprobación de tiempos en la
CI**. Lo que se decidió después sin él, con los datos delante, está marcado
**[decidido sin el dueño]** y reunido en «Decisiones para revisar».

## Qué se quiere

Que todas las ventanas aparezcan enteras, de golpe y en una fracción de lo que
tardan hoy, con el mismo diseño, las mismas pantallas y el mismo comportamiento.
Sigue siendo Python puro con el Tk del propio dispositivo: nada nuevo que bajar ni
que compilar.

**Presupuestos**, medidos en la máquina Windows x64 de GitHub Actions con datos de
verdad (la misma del banco), mediana de 7 vueltas. Una etapa está hecha cuando los
cumple:

| Momento | 0.7.1 | Objetivo |
|---|---|---|
| Ventana principal, desde que se lanza | 1,33 s | **≤ 0,35 s** |
| «Parejas», desde que se lanza | 2,17 s | **≤ 0,45 s** |
| Abrir «Parejas» con el programa abierto | 0,84 s | **≤ 0,15 s** |
| Cambiar de apartado en «Ajustes» | 0,21 s | **≤ 0,06 s** |
| Asistente / pregunta del agente, desde que se lanza | 1,22 / 1,04 s | **≤ 0,30 s** |
| Al 150 % | +23–48 % | **≤ +20 %** |
| Con 50 parejas en vez de 5 | 6–7 widgets más por pareja | **≤ +50 ms** |
| Memoria | 61–67 MB | **≤ 45 MB** |

Y dos reglas que no son números:
- **Ninguna ventana se rellena a trozos**: el encubrimiento de DWM (`tk.ensenar()`) se queda.
- **Ningún primer pintado espera a algo lento**: la red, el catálogo, `schtasks`,
  la foto de procesos o un recorrido de carpetas llegan después, con el indicador
  que el diseño ya tiene.

**Lo que más importa es la ventana ya abierta** (dicho por el dueño): abrir
«Parejas», cambiar de apartado, marcar una casilla, elegir una fila, la llegada
del catálogo, volver de «Ajustes». Para eso hay presupuestos propios, con la
ventana ya en pantalla y en la misma máquina:

| Acción con la ventana abierta | 0.7.1 (Linux / Windows) | Objetivo (Windows) |
|---|---|---|
| Elegir otra pareja o fila | 11–32 ms / ? | **≤ 16 ms** |
| Marcar o desmarcar una pareja | un repintado entero / ? | **≤ 16 ms** |
| Llega el catálogo del remoto a «Parejas» | 240–330 ms / ? | **≤ 30 ms** |
| Volver de «Ajustes» o «Reparación» a la principal | 100–130 ms / ? | **≤ 30 ms** |
| «Sincronizar ahora» hasta ver la ventana de la pasada | reconstruye la principal antes / ? | **≤ 100 ms** |
| 10 000 líneas de log en la ventana de la pasada | 4,8 s | **≤ 0,2 s** |

## Por qué es lenta (medido)

En Windows x64, Windows ARM64 y Linux, con el código de verdad de la 0.7.1 y el
runtime fijado (resultados completos en `docs/superpowers/pruebas/`):

1. **El pintado en Python**: `theme.apply()` pinta cada pieza de los controles redondeados píxel a píxel y la codifica en PNG en Python.
   - Son 86 piezas, y el centro de cada una se ensancha a 256×64.
   - También crea 856 estilos, 552 de ellos las variantes «Sobre…».
   - Cuesta 0,7 s en cada proceso que abre una ventana, y crece con la escala (1,2 s al 200 %).
   - Quitarlo deja el arranque en la mitad (Windows 1,33 → 0,68 s).
2. **Pintar cada control dibujado** cuesta 1,2 ms en Windows y en Linux, contra 0,14 ms de un control llano.
   - La causa no es Python. Tk dibuja una imagen con alfa intermedio (bordes suavizados) leyendo de vuelta los píxeles de la pantalla y mezclándolos por software, en cada pintado. `TK_CAN_RENDER_RGBA` no está definido ni en X11 ni en Windows (`tkImgPhInstance.c`).
   - La misma pieza con alfa solo 0 o 255 cuesta 0,18 ms.
3. **Demasiados widgets**:
   - «Parejas» tiene 152 widgets (la 0.6.5 tenía 44): 7 por fila de la lista, y el editor entero construido aunque no se vea.
   - Un widget llano cuesta ~0,5 ms en Windows, tres veces lo de Linux.
4. **Reconstruir en vez de actualizar**: un refresco cuesta lo mismo que abrir.
   - `render()` de la principal (100–130 ms) va después de cada `abrir_*` y antes de abrir la pasada.
   - La llegada del catálogo a «Parejas» (240–330 ms) reconstruye la pantalla, y además borra lo que se estuviera escribiendo en el editor (un fallo).
   - Pasar a «Catálogo» reconstruye; cambiar de apartado en «Ajustes» destruye el apartado y repinta los 9 botones de la barra.
   - Hacer lo mismo en el sitio cuesta 6–16 ms.
5. **Lo que no es dibujar**:
   - **`.pyc`**:
     - Ni el despliegue ni la actualización precompilan los `.pyc`, y el runtime no trae los de su biblioteca.
     - El primer arranque tras instalar tarda 2,2 s en vez de 1,25 s; el primero tras cada actualización, 1,66 s en vez de 1,22 s.
   - **El servicio** solo mira cada 5 s si le piden parar: la ventana sale 0–5 s tarde, y hasta 15 s si el servicio está a mitad de pasada.
   - **La pregunta del agente** arranca desde `agente.py`, que se recompila en cada uso e importa el agente entero.
   - **Imports** que no hacen falta para pintar suman ~60 ms.
   - **La letra**: se crean 31 `tkfont.Font` con sus métricas en cada ventana.

## Decisiones (del dueño)

- **A, no B.** Qt (PySide6) se midió en las mismas máquinas.
  - **Arranque y respuesta:** abre más tarde (Windows 0,44 s con datos, contra ~0,26–0,34 s de un Tk ligero), pero responde más rápido una vez abierto («Parejas» 0,10 s, apartados 0,02 s).
  - **Tamaño:** cuesta +43–47 MB por plataforma Windows y +86 MB en Linux, y el doble de memoria.
  - **Linux:** sube la glibc mínima de 2.17 a 2.34, y ni en el Ubuntu de GitHub arrancó sin instalarle bibliotecas.
  - **Reescritura:** obliga a rehacer las 33 pantallas de una vez.
- **Descartados:**
  - Rust (su ventaja desaparece en cuanto necesita los datos de Python, y es lo más caro de mantener).
  - Una ventana del navegador (depende de un navegador que la unidad no lleva, no puede proteger el QR de capturas, y las preguntas del agente no caben).
  - Hacer toda la interfaz sobre un Canvas.
- **El Tk con Xft de Linux se queda.** Sin él el texto no se suaviza, y solo cuesta ~40 ms. Quitarlo es otra decisión, aparte.

## Diseño

### 1. El motor de dibujo (`ui/theme.py`, `ui/icons.py`)

**1a. Piezas sin alfa intermedio [decidido sin el dueño].** Todas las piezas de los
controles (botones, campos, tarjetas, avisos, chips, grupo segmentado, barra) se
pintan con alfa solo 0 o 255.

- **Cómo:** el borde suavizado se mezcla ya contra el color de la superficie sobre la que va, y lo de fuera de la forma queda transparente del todo.
- **Por qué:** es lo que lleva el pintado de cada control de 1,2 a 0,18 ms. Una escena tipo «Parejas» pinta en 86 ms en vez de 216, y repintar 151 controles cuesta 27 ms en vez de 145–200.
- **Coste visual:** se mezcla contra la superficie de referencia de cada familia.
  - En el tema claro no se ve.
  - En el oscuro, sobre avisos de color, 2–3 píxeles de cada esquina quedan unos tonos fuera, y solo se ve con zoom.
  - Para eso hay **piezas por superficie** de las familias que de verdad van sobre avisos. Las elige el mismo estado que el fondo (1b), dentro del `element_create` del estilo.
  - Siguen con alfa intermedio solo las piezas huecas por dentro: el chip «Apagado» y el anillo de foco de `Quiet`. Son pocos controles.
- **El centro de la pieza:** se pinta a su tamaño (64×32), no ensanchado a 256×64. Con alfa binario el embaldosado ya no cuesta, y el SVG cuesta por área.

**1b. La superficie por estado, no por estilo [decidido sin el dueño].** Las 552
variantes «Sobre<RRGGBB>» se sustituyen.

- **El mecanismo:** cada estilo redondeado base lleva un `style.map(base, background=…)` con los tres bits de estado libres de ttk (`user1..user3`). Siete combinaciones bastan para las seis superficies no papel del sistema: SUPERFICIE, GRIS_FONDO, AVISO_FONDO, PELIGRO_FONDO, ACENTO_SUAVE y OK_FONDO.
- **Al mapearse:** `_asentar` (el mismo `<Map>` de hoy) pone `w.state([...])`. No crea estilos, no dispara `<<ThemeChanged>>` y no recoloca nada.
- **Lo que hereda:** los estilos derivados («Grande.Primary.TButton») heredan el mapa por el nombre.
- **Una superficie desconocida** (una cara de botón de `_CARA`) cae en la variante «Sobre…» perezosa de hoy, que se probó.
- **Regla nueva: ningún estilo se crea, configura ni mapea después del primer widget.** Cada `style configure/map/layout` manda un `<<ThemeChanged>>` a todos los widgets del intérprete (75–160 ms con 177 widgets). `apply()` lo crea todo antes, y una prueba cuenta que no llegue ninguno al abrir pantallas.

**1c. SVG con el Tk 9 del dispositivo, y el pintor de Python de respaldo.**
`icons._foto()` es el único sitio que crea imágenes. Ahí:

- **Con Tk 9** (una prueba de capacidad: `PhotoImage(data=<svg>, format="svg")` dentro de un `try`, no el número de versión), cada pieza, glifo, casilla, disco, baldosa y marca se describe en SVG y la pinta Tk en C.
  - Cuesta 0,16–0,22 ms por glifo, contra 5,5–23 ms en Python, y no crece con la escala.
  - El SVG sale de las **mismas primitivas** (`GLIFOS`, `_capas_marca`, las de `caja()`), así que no hay dos tablas de dibujo que se separen.
  - Detalles comprobados:
    - nanosvg no hace `<mask>`, `<clipPath>` ni `<text>`, así que los anillos van con `fill-rule="evenodd"`;
    - un punto (`d`) va como un `<rect>`;
    - los iconos usan `-scaletoheight icons.px(...)`;
    - las cajas se escriben en píxeles físicos.
- **Sin SVG** (Tk 8.6: la CI de 3.11, un equipo con su propio Python), el pintor de Python de hoy.
  - Pinta las piezas también con alfa binario.
  - Su `_png` se memoiza: sale **byte a byte igual**, comprobado en las 86 piezas, y pasa de 5,4 a 0,65 ms por pieza.
  - Opcional: guardar sus PNG en una caché del equipo (no del dispositivo), por versión y tema.
- `icons.matriz()` (el QR) sigue con `put()`: los lectores necesitan bordes duros.
- `poner_icono()` (el icono de la ventana) pasa también por SVG. Hoy pinta la marca a 64, 32 y 16 px en Python en cada arranque (~55 ms).
- Para lo que no tiene Tk (`.ico`, bandeja, icono de la unidad) sigue el pintor de Python y **no cambia ni un byte**.
  - Los 25 SHA-256 de hoy pasan a ser una prueba.
  - Explorer guarda los iconos por ruta, y un `.ico` ya instalado no se repinta.

**1d. La letra.**
- **Una tabla de métricas por intérprete**, por `(tk scaling, fuente)` → `(linespace, ascent, tamaño)`, que se vacía en `theme.olvidar()`. Hoy `relleno_control()` e `icono_linea()` crean 31 `tkfont.Font` por ventana: 51 → 13 ms.
- **Las fuentes de los roles se crean una vez y se sujetan** con un elemento oculto. Con Xft, `measure`/`metrics` de una fuente que nadie tiene puesta reabre la cara en cada llamada (0,55 ms contra 2 µs).
- **`cargar_fuentes()`** prueba `CDLL("libfontconfig.so.1")` antes de `find_library`, que lanza `ldconfig`.
- **`familia()`** enumera las familias una sola vez.

**1e. Estilos que sobran.** Nadie usa:
- `DangerSolid` ni `AmbarDanger`;
- `Pequeno.*` (solo `test_controles.py`);
- `Capa`, `Mono.TCombobox` ni `SolidoOk/Aviso/Acento`;
- probablemente los marcos `Ambar./Rojo./Azul.` antiguos.

Se quitan, y con ellos sus piezas: es orden, no velocidad (6–16 ms).

### 2. Las pantallas: cinco reglas

**R1. Construir una vez, cambiar en el sitio.** Cada pantalla tiene su vista
construida una vez. Un cambio de estado es `vista.aplicar(estado)`, que hace
`configure` de lo que cambió. No se destruye un marco entero para repintarlo, salvo
al cambiar de paso en el asistente.

- `render()` de la principal pasa a ser `aplicar()`:
  - no se llama `reajustar()` al volver de un apartado si lo que devolvió no dice que algo cambió;
  - «Sincronizar ahora» cambia a «ocupado» en el sitio y abre la ventana de la pasada al momento.
- En «Parejas» nada reconstruye la lista ni el editor:
  - la llegada del catálogo actualiza las filas por nombre y los chips en el sitio;
  - pasar a «Catálogo» es enseñar u ocultar;
  - el editor **no se recarga si se está escribiendo en él**, lo que arregla que se borrara al llegar el catálogo;
  - `load_raw`/`parse_config` se guardan hasta la próxima escritura.
- En «Ajustes», `marcar()` solo cambia el estilo del botón de antes y del nuevo (−10–12 ms por cambio), y la barra solo se repinta si cambia un chip.

**R2. Lo que no se ve, no se construye.**
- **Bloques que pocas veces se ven:** los avisos opcionales, «Avanzado», la barra de acciones del catálogo, el formulario de «Conexión» no elegido y las barras de desplazamiento del `Visor` se crean la primera vez que hacen falta.
- **«Ajustes»:**
  - cada apartado se construye la primera vez que se visita y luego se oculta y se enseña (`grid_remove`), con un `al_mostrar()` que refresca lo suyo;
  - el primer apartado se construye en un `after_idle`, sobre el hueco de tamaño fijo que ya existe.
- **«Parejas» se pinta en dos tiempos**:
  1. la cabecera, el selector, la franja de valores comunes y la lista;
  2. el editor, en una tarjeta con su alto ya reservado (el de la última vez, guardado en `ui_prefs.json`) para que la ventana no salte.

**R3. Una lista que crece con los datos es un solo widget [decidido sin el
dueño].** `ui.tk.Tabla` se rehace sobre un `tk.Canvas`.

- **El dibujo:**
  - un rectángulo por fila sobre un lienzo del color de la línea (el hueco de 1 px es el separador);
  - texto con las fuentes de los roles;
  - chips como una imagen (píldora, disco y glifo) más un texto;
  - la ruta acortada con «…».
- **Lo que hace:** selección con el acento, paso del ratón, flechas, Inicio/Fin y espacio, y clic en la casilla.
- **Lo que no cambia para las pruebas:** sigue igual hacia fuera (`filas`, `orden`, `elegida`, `cabeceras`, `al_elegir`), y se añade `leer()`, lo dibujado como texto.
- **Quién la usa:** la lista de parejas de «Parejas» y la de la principal, «Dispositivos», la tabla del editor de flags, los hallazgos de «Reparación» y las tablas de «Comprobaciones»/«Verificación».
- **Medido en Linux, con 50 filas:**

  | | 0.7.1 | La tabla nueva |
  |---|---|---|
  | Construir | 940 ms | 90–105 ms |
  | Elegir | 19 ms | 1,2 ms |
  | Pasar el ratón | — | 1,1 ms |
  | Refrescar | 940 ms | 36 ms |

- **Por qué no las alternativas:**
  - Treeview no hace los separadores, repinta entero en cada selección (~50 ms) y no corta el texto.
  - `Text` descuadra las columnas cuando algo no cabe.
- **El resto de cada pantalla sigue siendo ttk.** No es la interfaz sobre un Canvas que se descartó: es un componente para lo que crece con los datos.

**R4. Leer después de pintar.** Un módulo sin Tk, `ui/instantanea.py`, hace en una
sola pasada todo lo que hoy se lee varias veces.

- **Qué junta:** `pair_state`, `filters_state`, `last_run`, conflictos, componentes, `raiz_fisica` (una vez, no tres), la línea del llavero y el resumen del vigilante.
- **Con quién se comparte:** la principal, «Parejas» y «Ajustes»; «Reparación» deja de volver a llamar a `revisar()`.
- **El primer pintado** usa solo el config, `ui_prefs.json`, `last_run.json` y las copias guardadas. Lo demás llega por `segundo_plano`/`Sondeo`, sin bloquear.
- **Lo que se ve mientras tanto:**
  - el chip de la cabecera es una píldora neutra del mismo tamaño, no «al día»;
  - los nombres, los modos y las casillas ya están, y los botones también;
  - la ventana solo crece hacia abajo y no se vuelve a centrar.
- **Lo que sale del hilo de Tk, con su límite de tiempo:**
  - `schtasks`/`systemctl` («Arranque automático»), que hoy van por `run_quiet` sin límite;
  - el `rclone lsf -R` de «Versiones guardadas», que hoy bloquea antes de enseñar el apartado;
  - el QR;
  - `device.list_volumes()` y las comprobaciones del asistente.

**R5. Presupuesto de widgets por pantalla**, comprobado por una prueba:

| Pantalla | 0.7.1 (5 parejas) | Objetivo | Con los datos |
|---|---|---|---|
| Principal | 51 (+4–5 por pareja) | ≤ 26 | +0 por pareja |
| «Parejas» | 152 (+7 por pareja) | ≤ 70 | +0 por pareja |
| «Ajustes», marco | 25 | ≤ 18 | — |
| «Ajustes», cada apartado | 5–35 (+6,6 por hallazgo) | ≤ 14 | +0 por hallazgo |
| Editor de flags | 78 | ≤ 34 | +0 por flag |
| «Dispositivos» | 33 + 7 por equipo (+24N al llegar) | ≤ 35 | +0 por equipo |
| Pasos del asistente | 7–71 | ≤ 28 | +0 por comprobación |
| Pregunta del agente | 16 | ≤ 11 | — |

Y tres cosas pequeñas:
- **La ventana de la pasada** mete el log en bloque, un `insert` y un `see` por vuelta: 10 000 líneas pasan de 4,8 s a 0,09 s. Se queda con las últimas 20 000.
- **La barra de espera** avanza cada 40–50 ms, no cada 12 ms: de un 10,6 % a un 2,6 % de un núcleo.
- **Un solo encaje por pantalla**, después de construirla, no varios `update_idletasks` por el medio.

### 3. El arranque

- **`.pyc` al instalar y al actualizar [decidido sin el dueño].**
  - `deploy_code()` y el aplicador de `--update` acaban con un `precompilar()` que se hace si se puede.
  - Usa el intérprete del dispositivo (`deploy.device_python()`): `compileall` de `common/` y `ui/`, más un calentamiento de los módulos de la biblioteca que usa prdrive.
  - Se repite tras actualizar el runtime.
  - Si no se puede (unidad de solo lectura, llena), se sigue sin él.
  - El agente calienta su `PYTHONPYCACHEPREFIX` de los hijos al copiar su código.
  - En FAT32 la hora de un fichero puede moverse al pasar entre Windows y Linux e invalidar los `.pyc` una vez; si una prueba en máquina real lo ve, se pasa a `--invalidation-mode checked-hash`.
  - Escribe ~6 MB en la unidad.
- **La pregunta del agente** arranca desde un `pregunta.py` de diez líneas (en `CODIGO_FICHEROS`), no desde `agente.py`: 288 → 146 ms antes de `Tk()`. Con los imports perezosos de abajo, 111 ms.
- **Imports perezosos:**
  - las ayudas de ventana (`centrar`, `ensenar`, `Visor`…) en un módulo sin imports de `common`;
  - `ui/__init__.py` y `ui/tk.py` sin `bisync`/`results`/`revision`/`components`/`conflicts`/`update` arriba;
  - `main_window` sin importar las pantallas que solo abre un clic;
  - `llavero_editor` solo con `[keychain]`;
  - `penwatch.py` con un `escape` propio en vez de `xml.sax.saxutils` (que arrastra `urllib`/`http`/`ssl`/`email`);
  - `common/update.py` con `urllib`/`zipfile` dentro de las funciones;
  - `runsync.py` con lo del servicio y el llavero perezoso, manteniendo los nombres que las pruebas sustituyen.
- **El servicio no retrasa la ventana [decidido sin el dueño].**
  - El servicio mira `daemon.stop` cada segundo, no cada 5 s, y quien lo para mira cada 0,1 s.
  - Además, la ventana **se abre antes** y lo para en segundo plano: un `Indicador` lo dice, y «Sincronizar ahora» espera desactivado hasta que ha parado, para que nunca haya dos pasadas a la vez.

### 4. Tk 8.6, el instalador y la CI

- **El instalador se compila con Python 3.14.8**, que en Windows ya trae Tk 9.0.4, y con `pyinstaller==6.22.3` fijado (hoy va sin fijar) [decidido sin el dueño].
  - `build_installer.py` comprueba Tk ≥ 9 antes de compilar.
  - El `.exe` deja de abrir en Windows 8.1. Los dispositivos ya piden Windows 10.
  - La primera compilación va por una rama, antes de una release.
  - Pasar de `--onefile` a `--onedir` (que no desempaquetaría en cada arranque) cambia lo que se descarga, y queda como pregunta abierta.
- **La CI ejecuta la suite dos veces**:
  - una con el 3.11 de `setup-python` (Tk 8.6: la versión mínima y el pintor de respaldo);
  - otra con el runtime fijado (3.14.8, Tk 9.0.4), bajado como en F20, en Linux y en Windows.
  - Ya pasa entera con el runtime: 110 de 110 ficheros.
- **Python del equipo («instalación ligera», `runsync.pyw`)**: se queda. Con Tk 8.6 va por el pintor de respaldo, con el mismo aspecto y más lento. `install/device.py:check_python()` pregunta al Python del equipo con un subproceso, no al del propio `.exe`.

### 5. La comprobación de tiempos que se queda

El banco temporal (`banco/`, `banco-ui.yml`) se convierte en **`rendimiento.yml`**
(acordado con el dueño).

- **Cuándo corre:** en cada PR que toca `ui/`, `runsync.py`, `agente.py` o `install/deploy.py`, y a mano.
- **Dónde:** en Windows x64 y Linux con el runtime fijado. ARM64, a mano.
- **Qué mide:** las pantallas de verdad, con un dispositivo de muestra de 5 y de 50 parejas.
  - Arranque de la principal, de «Parejas», del asistente y de la pregunta del agente.
  - Abrir «Parejas» y cambiar de apartado.
  - Las acciones de la ventana abierta de la tabla de arriba.
  - Lo mismo al 150 %.
- **Qué deja:** una tabla en el resumen del trabajo, y **falla si una mediana pasa de 1,25 × su presupuesto** (margen para el ruido de la máquina compartida).
- **Los presupuestos van en un fichero del repositorio**, cada uno con su objetivo y si ya se exige.
  - Funciona como un trinquete: un presupuesto empieza solo informando, y el PR que lo cumple por primera vez lo pasa a exigido.
  - Desde entonces ningún PR puede volver a pasarse.
  - Así la etapa 1 no falla por lo que es trabajo de la 2.
- **Lo que se quita:** la mitad de Qt, la 0.6.5 y las variantes de prueba.

### 6. Pruebas

Las de hoy se adaptan donde comparan nombres de estilo «Sobre…»: `test_controles` pasa a mirar los bits de estado. Además:
- **Paridad:** la misma pieza por SVG y por el pintor de respaldo coincide en alfa, con tolerancia.
- **Piezas:** ninguna pieza (salvo las huecas) tiene alfa intermedio.
- **Iconos:** los 25 iconos sin Tk salen byte a byte iguales.
- **Estilos:** ningún `<<ThemeChanged>>` al abrir pantallas.
- **Widgets:** cada pantalla cumple su presupuesto con 5 y con 50 parejas.
- **Refrescos:** la principal y «Parejas» no destruyen widgets al refrescarse.
- **La tabla:** `Tabla` responde como antes (`filas`, `orden`, `elegida`, `cabeceras`) y su `leer()` da lo pintado.

Todo se ejecuta en las dos patas de la CI: Tk 8.6 y Tk 9.

## Etapas

Cada etapa es un PR con su versión y un título para el usuario, y se mide con `rendimiento.yml` contra los presupuestos. Cada una tiene su propio plan en `docs/superpowers/plans/`: se escribe el de la siguiente cuando la anterior está medida, para que lo aprendido entre.

1. **Medir siempre y el motor.**
   - `rendimiento.yml`.
   - El motor: piezas sin alfa intermedio, SVG, la superficie por estado, el `_png` memoizado, el icono de la ventana y la letra.
   - El arranque: `.pyc`, `pregunta.py`, imports perezosos y el servicio.
   - Lo pequeño: el log en bloque, la barra a 40–50 ms, el límite a `run_quiet` y el editor que no se borra.
   - Se espera el arranque a la mitad o menos en todas las ventanas.
2. **La ventana abierta** (la prioridad del dueño):
   - `ui/instantanea.py`;
   - la `Tabla` sobre Canvas;
   - la principal con `aplicar()`;
   - «Parejas» en dos tiempos y en el sitio;
   - «Ajustes» con apartados guardados.
3. **El resto de pantallas:**
   - los apartados que leen después de pintar (arranque, versiones, QR, reparación);
   - «Dispositivos», el editor de flags, los pasos del asistente y la pregunta del agente;
   - el instalador con 3.14 y la pata de Tk 9 en la CI.
4. **Limpieza:**
   - quitar `banco/` y los estilos que sobran;
   - `docs/agents/reference/ui.md` y `provisioning.md`;
   - filas nuevas de máquina real: `.pyc` en FAT32 y exFAT entre sistemas, y el aspecto en una pantalla de Windows de verdad.

## Decisiones para revisar

Tomadas sin el dueño el 08/10/2026, con los datos de arriba:

1. **Piezas con alfa binario**, con el borde mezclado contra la superficie (§1a). Mismo aspecto en claro; en oscuro, unos píxeles de esquina sobre avisos, salvo con piezas por superficie.
2. **La superficie por bits de estado** en vez de las 552 variantes (§1b).
3. **La tabla sobre un Canvas** para las listas que crecen con los datos (§2 R3). El dueño descartó la interfaz entera sobre un Canvas; esto es un solo componente.
4. **`.pyc` precompilados en la unidad** al instalar y actualizar (§3): ~6 MB más en la unidad.
5. **La ventana se abre antes de parar el servicio**, con «Sincronizar ahora» esperando (§3).
6. **El instalador con Python 3.14 y PyInstaller fijado**: el `.exe` deja Windows 8.1 (§4).
7. **La comprobación de tiempos falla un PR** a 1,25 × el presupuesto (§5).

## Preguntas abiertas

- **El efecto en Windows de las piezas con alfa binario** se deduce del código de Tk (la misma rama sin `TK_CAN_RENDER_RGBA`) y de la CI (1,2 contra 0,5 ms por widget), pero no se ha medido aún. Es lo primero que dirá `rendimiento.yml` en la etapa 1.
- **El instalador `--onefile` frente a `--onedir`** (§4).
- **Los `.pyc` en FAT32** al cambiar de sistema (§3).
- **El aspecto en una pantalla de Windows de verdad**: la máquina de GitHub pinta, pero nadie la ha mirado.

## Fuera de alcance

- El motor (`sync.py`), la lógica del agente y la bandeja, que ya es nativa.
- Funciones nuevas o cambios de aspecto.
- Qt, Rust, el navegador y la interfaz entera sobre un Canvas.
- Quitar el Tk con Xft de Linux.
- La accesibilidad: Tk 9.0.4 no tiene API de accesibilidad, así que nada empeora; queda para otro día.

## De dónde sale cada número

- `docs/superpowers/pruebas/2026-10-08-banco-interfaz-resultados.md` (banco en GitHub Actions: Windows x64 y ARM64, Linux).
- Las investigaciones del 08/10/2026 (en la sesión que escribió esto):
  - el mapa de `theme.py`/`icons.py`;
  - la auditoría de cada pantalla (widgets, reconstrucciones, lecturas);
  - la prueba del SVG y de las superficies por estado;
  - la de la tabla;
  - la de Tk 8.6, el instalador y la CI;
  - la del arranque.

  Todo en Linux con el runtime fijado salvo lo que dice Windows.
