# Frontend rápido: el mismo Tk, dibujado y refrescado de otra manera — diseño

Fecha: 08/10/2026. Estado: **diseño revisado (versión 2), pendiente de que lo revise el dueño**.
Sustituye la forma de dibujar y de refrescar del rediseño de la 0.7.0. El aspecto se
queda: es el del sistema «prdrive» de la 0.7.1. Las medidas que lo deciden están en
`docs/superpowers/pruebas/2026-10-08-banco-interfaz-resultados.md`.

Decidido con el dueño el 08/10/2026:
- el **enfoque A**: seguir con Tk y rehacer cómo dibuja y cómo refresca;
- los **objetivos de tiempo** de abajo;
- que **lo que más importa es lo que responde la ventana ya abierta**;
- que se **queda una comprobación de tiempos en la CI**.

Lo demás se decidió después sin él, con los datos delante y tras tres revisiones adversarias (hechos contra el código, lo que se rompe, si llega a los objetivos). Va marcado **[decidido sin el dueño]** y reunido en «Decisiones para revisar».

## Qué se quiere

Que las ventanas aparezcan enteras, de golpe y en una fracción de lo que tardan hoy,
y sobre todo que **respondan al momento una vez abiertas**. Con el mismo diseño, las
mismas pantallas y el mismo comportamiento. Sigue siendo Python puro con el Tk del
propio dispositivo: nada nuevo que bajar ni que compilar.

**Objetivos**, en la máquina Windows x64 de GitHub Actions con datos de verdad,
mediana de 7 vueltas. «0.7.1» es lo medido; «Modelo» es lo que estima la revisión
para este diseño sumando costes medidos (ver «Por qué es lenta»):

| Momento | 0.7.1 | Objetivo | Modelo |
|---|---|---|---|
| Ventana principal, desde que se lanza | 1,33 s | **≤ 0,35 s** | 0,38–0,52 s: en riesgo |
| Abrir «Parejas» con el programa abierto | 0,84 s | **≤ 0,15 s** | 0,17–0,22 s; ≤ 0,15 con R7 |
| «Parejas», desde que se lanza (= las dos de arriba) | 2,17 s | **≤ 0,50 s** | en riesgo |
| Abrir «Ajustes» | 0,23 s | **≤ 0,15 s** | 0,11–0,15 s |
| Cambiar de apartado en «Ajustes» | 0,21 s (0,03–0,28 según el apartado) | **≤ 0,06 s** | 0,03–0,05 s si las lecturas no bloquean |
| Pregunta del agente, desde que se lanza | 1,04 s | **≤ 0,30 s** | 0,30–0,34 s: justo (la 0.6.5 ya daba 0,48) |
| Asistente, desde que se lanza | 1,22 s | **≤ 0,30 s** | 0,40–0,45 s; se informa, no se exige (el `.exe` real no se mide) |
| Al 150 % | +23–48 % | **≤ +20 %** | +5–25 % |
| Con 50 parejas en vez de 5 | +6–7 widgets por pareja | **≤ +50 ms** | +40–110 ms: en riesgo; depende de R3 |
| Memoria | 57–67 MB | ≤ 45 MB | 48–55 MB; se informa, no se exige (la 0.6.5 ya usaba 50–54) |

Antes de este diseño se dijo «Parejas ≤ 0,45 s desde que se lanza». No cuadraba: en
todas las máquinas ese momento es la ventana principal más abrir «Parejas»
(2,17 = 1,33 + 0,84), así que con 0,35 + 0,15 el objetivo coherente es 0,50.

**Lo que más importa: la ventana ya abierta**, en la misma máquina:

| Acción con la ventana abierta | 0.7.1 | Objetivo |
|---|---|---|
| Elegir otra pareja o fila | 11–32 ms (Linux); se recarga el editor | **≤ 16 ms** el resaltado y ≤ 40 ms el editor |
| Marcar o desmarcar una pareja en la principal | en el sitio, pero escribe `ui_prefs.json` en la unidad dentro del clic | **≤ 16 ms**, sin tocar la unidad dentro del clic |
| Llega el catálogo del remoto a «Parejas» | **1,2 s** (Windows; la 0.6.5, 50 ms) | **≤ 30 ms** con 5 parejas |
| Volver de «Ajustes» o «Reparación» a la principal | reconstruye la principal (100–130 ms en Linux) | **≤ 30 ms** si nada cambió |
| «Sincronizar ahora» hasta ver la ventana de la pasada | reconstruye la principal antes y después | **≤ 100 ms** |
| 10 000 líneas de log en la ventana de la pasada | 4,8 s (Linux) | **≤ 0,2 s** |

Y dos reglas que no son números:
- **Ninguna ventana se rellena a trozos**: el encubrimiento de DWM (`tk.ensenar()`) se queda, y nada se construye a medias para terminarlo después de enseñarlo.
- **Ningún primer pintado ni ningún clic espera a algo lento**: la red, el catálogo, `schtasks`, la foto de procesos, un recorrido de carpetas o una escritura en la unidad.

## Por qué es lenta (medido)

Con el código de la 0.7.1 y el runtime fijado en Windows x64, Windows ARM64 y Linux
(salvo donde se indica), en GitHub Actions:

1. **El pintado en Python.**
   - `theme.apply()` pinta píxel a píxel y codifica en PNG en Python 86 piezas: 72 cajas, cuyo centro se ensancha a 256×64, y 14 pequeñas.
   - Crea 854 estilos, 552 de ellos las variantes «Sobre…».
   - Cuesta 0,68–0,69 s en cada proceso que abre una ventana (Windows), y crece con la escala.
   - Quitarlo deja el arranque de la principal en la mitad (Windows 1,33 → 0,68 s) y el de la pregunta del agente en 0,39 s.
2. **Los widgets.**
   - Un widget llano cuesta ~0,52 ms en Windows (0,28 crearlo y 0,30 enseñarlo), tres veces lo de Linux (0,17).
   - «Parejas» tiene 152 widgets (la 0.6.5, 44): 7 por fila de la lista y el editor entero aunque no se vea.
   - Un botón dibujado añade 0,3–0,6 ms en Windows y ~0,75 ms en Linux. Es el banco de filas, que no aísla el pintado.
   - En Linux, aislado, pintar una pieza con alfa intermedio cuesta 1,18 ms por control contra 0,14 de uno llano: Tk la mezcla por software en cada pintado, porque `TK_CAN_RENDER_RGBA` solo está definido en macOS.
   - En Windows ese efecto no se ha aislado.
3. **Reconstruir en vez de actualizar.**
   - `render()` de la principal (100–130 ms en Linux) va después de cada `abrir_*` y antes y después de una pasada.
   - En «Parejas», la llegada del catálogo (1,2 s en Windows) y pasar a «Catálogo» reconstruyen la lista y el editor, y la llegada **borra lo que se estuviera escribiendo** (un fallo).
   - Cambiar de apartado en «Ajustes» destruye el apartado y repinta los 9 botones de la barra.
   - Hacer lo mismo en el sitio cuesta 6–16 ms.
4. **Lecturas y escrituras en el hilo de Tk.**
   - **Al pintar la principal**:
     - unas 410 llamadas al sistema de ficheros por pintado (`pair_state` ×6, `filters_state` ×6, `raiz_fisica` ×3, que en Windows recorre las letras de unidad);
     - la foto de procesos de la línea del llavero.
   - **Los apartados lentos de «Ajustes»** lo son por lo que leen, no por lo que pintan:
     - «Reparación» vuelve a llamar a `revisar()`;
     - «Arranque automático» llama a `schtasks`/`systemctl` sin límite de tiempo;
     - «Versiones guardadas» no se pinta hasta acabar de leer el remoto.
   - **Marcar una pareja** reescribe `ui_prefs.json` en la unidad dentro del clic.
5. **Lo que no es dibujar.**
   - **Imports de más:** ~60 ms en imports que no hacen falta para pintar.
   - **La pregunta del agente:** `agente.py` se recompila en cada uso (44–49 ms) e importa el agente entero.
   - **La letra:** se crean ≥ 25 `tkfont.Font` con sus métricas por intérprete, y más por cada botón con icono.
   - **`.pyc`:**
     - ni el despliegue ni la actualización precompilan los `.pyc`, y el runtime no trae los de su biblioteca;
     - el primer arranque tras instalar tarda 2,2 s en vez de 1,25 s, y el primero tras cada actualización 1,66 s en vez de 1,22 s (Linux, medido en local, no en el banco).
   - **El servicio** solo mira cada 5 s si le piden parar: la ventana sale 0–5 s tarde, y hasta 15 s a mitad de pasada.

## Decisiones (del dueño)

- **A, no B.** Qt (PySide6) se midió en las mismas máquinas.
  - **Arranque y respuesta:**
    - abre más tarde (Windows 0,44 s con datos, contra 0,26–0,34 s de un Tk ligero con datos de muestra);
    - responde más rápido una vez abierto («Parejas» 0,10 s, apartados 0,02 s).
  - **Tamaño:** cuesta +43–47 MB por plataforma Windows y +86 MB en Linux, y 76–92 MB de memoria.
  - **Linux:** sube la glibc mínima de 2.17 a 2.34, y ni en el Ubuntu de GitHub arrancó sin instalarle bibliotecas.
  - **Reescritura:** obliga a rehacer las 33 pantallas de una vez.
- **Descartados:**
  - Rust: su ventaja desaparece en cuanto necesita los datos de Python, y es lo más caro de mantener.
  - Una ventana del navegador: depende de un navegador que la unidad no lleva, no puede proteger el QR de capturas, y las preguntas del agente no caben.
  - Hacer toda la interfaz sobre un Canvas.
- **El Tk con Xft de Linux se queda.** Sin él el texto no se suaviza, y solo cuesta ~40 ms.

## Diseño

### 1. El motor de dibujo (`ui/theme.py`, `ui/icons.py`)

**1a. SVG con el Tk 9 del dispositivo, y el pintor de Python de respaldo.**
`icons._foto()` es el único camino de las piezas, los glifos y la marca. Fuera quedan
`icons.matriz()` (el QR) y los filetes de 1×1 de `theme._filetes()`, que son opacos.

- **Con Tk 9** (comprobado con una prueba de capacidad, no con el número de versión: `PhotoImage(data=<svg>, format="svg")` dentro de un `try`), cada pieza, glifo, casilla, disco, baldosa y marca se describe en SVG y la pinta Tk en C.
  - Por glifo, 0,16–0,22 ms contra 5,5–23 ms en Python, sin crecer con la escala.
  - `apply()` pasa de 0,69–0,75 s a ~0,13–0,20 s (Linux).
  - El aspecto sale casi idéntico: 0,04–0,13 % de píxeles distintos, solo en bordes suavizados, en todas las familias, estados, temas y escalas.
- **El SVG sale de las mismas primitivas** (`GLIFOS`, `_capas_marca`, las de `caja()`), así que no hay dos tablas de dibujo que se separen.
- **Detalles comprobados:**
  - nanosvg no hace `<mask>`, `<clipPath>` ni `<text>`, así que los anillos van con `fill-rule="evenodd"`;
  - un punto (`d`) va como un `<rect>`;
  - los iconos van con `-scaletoheight icons.px(...)`, y `bajar` fraccionario es un `translate`;
  - las cajas se escriben en píxeles físicos.
- **Sin SVG** (Tk 8.6: la pata 3.11 de la CI, o un equipo con su propio Python), el pintor de Python de hoy.
  - Su `_png` se memoiza: sale **byte a byte igual**, comprobado en las 86 piezas, y pasa de 5,4 a 0,65 ms por pieza.
  - Con eso `apply()` baja de ~0,7 a ~0,39 s también en Tk 8.6.
- `poner_icono()` (el icono de la ventana) pasa por SVG. Hoy pinta la marca a 64, 32 y 16 px en Python en cada arranque (~55 ms).
- **Lo que no tiene Tk no cambia ni un byte**: `.ico`, bandeja, icono de la unidad.
  - Se queda el pintor de Python.
  - Los 25 SHA-256 de hoy pasan a ser una prueba.
- **Cachés por intérprete.**
  - Toda caché nueva (fotos, fuentes, métricas) va por intérprete y se suelta en `theme.olvidar`/`icons.olvidar` desde el hilo que la creó.
  - `PhotoImage` y `Font` solo se crean en el hilo de Tk: los hilos de lectura devuelven datos, no imágenes.
  - Así lo exige el aviso de fallo del servicio, que abre intérpretes sucesivos en el mismo hilo (Tk 9 aborta si no).

**1b. La superficie por estado, no por estilo [decidido sin el dueño].**
Las 552 variantes «Sobre<RRGGBB>» se sustituyen.

- **El mecanismo:**
  - cada estilo redondeado base lleva un `style.map(base, background=…)` con los tres bits de estado libres de ttk (`user1..user3`);
  - siete combinaciones bastan para las seis superficies no papel: SUPERFICIE, GRIS_FONDO, AVISO_FONDO, PELIGRO_FONDO, ACENTO_SUAVE y OK_FONDO;
  - nada del repositorio usa esos bits.
- **Al mapearse:** `_asentar` (el mismo `<Map>`) pone `w.state([...])`. No crea estilos, no dispara `<<ThemeChanged>>` y no recoloca nada: 3,4 contra 7,6–9,4 ms por 151 widgets.
- **Lo que hereda:** los estilos derivados («Grande.Primary.TButton») heredan el mapa por el nombre.
- **Las caras de botón de `_CARA`** (Primary, DangerSolid…), que no caben en los bits, se siguen creando como variante **en `apply()`**, como hoy. Ninguna se crea al vuelo.
- **Regla nueva: ningún estilo se crea, configura ni mapea después del primer widget de un intérprete.**
  - Cada `style configure/map/layout` manda un `<<ThemeChanged>>` a todos los widgets (75–160 ms con 177 widgets).
  - La prueba que ya existe en `test_controles.py` se extiende a abrir todas las pantallas.

**1c. Piezas sin alfa intermedio: solo si Windows lo justifica [decidido sin el dueño].**
Una pieza con alfa 0/255 tiene el borde suavizado ya mezclado contra la superficie.
En Linux pinta a 0,18 ms contra 1,18 ms: una escena tipo «Parejas» en 86 ms en vez
de 216.

- **Lo que no se sabe:** en Windows el banco solo ve 0,3–0,6 ms de más por botón dibujado.
- **Lo que cuesta:**
  - un rasterizador más (para Tk 8.6);
  - piezas por superficie;
  - en tema oscuro, 2–3 píxeles de esquina fuera de tono sobre avisos de color.
- **Por eso** se empieza con SVG suavizado (el aspecto exacto de la 0.7.1), y en la etapa 1b se mide en Windows SVG suavizado contra alfa binario en la misma pantalla. Solo se adopta si gana más de 20 ms en «Parejas» o en la principal.

**1d. La letra.**
- **Una tabla de métricas por intérprete:** `(tk scaling, fuente)` → `(linespace, ascent, tamaño)`. La usan `relleno_control()`, `icono_linea()`, `aviso()` y `chip()`, que hoy crean un `tkfont.Font` por llamada: 51 → 13 ms en la principal.
- **Las fuentes de los roles se crean una vez por intérprete y se sujetan** con un elemento oculto. Con Xft, medir una fuente que nadie tiene puesta reabre la cara: 0,55 ms contra 2 µs.
- **`cargar_fuentes()`** prueba `CDLL("libfontconfig.so.1")` antes de `find_library`, que lanza `ldconfig`.
- **`familia()`** enumera las familias una sola vez.
- **`sistema_oscuro()`** (un subproceso de `gsettings`, con hasta 2 s de límite) se mira una vez por proceso, como hoy, pero fuera de la ruta de la primera ventana si se puede leer del registro o de un fichero.

### 2. Las pantallas: siete reglas

**R1. Construir una vez, cambiar en el sitio.**

- **El patrón:**
  - cada pantalla tiene una vista construida una vez;
  - un cambio de estado es `vista.aplicar(estado)`, una función de estado → `configure`, y no se destruye un marco para repintarlo;
  - la excepción es el cambio de paso del asistente.
- **Para no perder lo que daba reconstruir** (una pantalla siempre coherente con su estado):
  - una prueba diferencial: tras una serie de cambios al azar, la vista aplicada en el sitio es igual a una construida de cero;
  - una prueba de tabla de «desactivado ⇔ ocupado» para cada control que toca el estado;
  - `try/finally` alrededor de «ocupado».
- **La principal:**
  - `render()` pasa a `aplicar()`;
  - al volver de un apartado solo se aplica si lo que devolvió dice que algo cambió;
  - «Sincronizar ahora» pasa a «ocupado» en el sitio, abre la ventana de la pasada y lanza el proceso justo después de enseñarla (R6).
- **«Parejas»:**
  - la llegada del catálogo actualiza las filas por nombre y los chips en el sitio;
  - «Catálogo» es enseñar u ocultar;
  - el editor no se recarga si tiene cambios sin guardar (la marca que ya usa `seguir_sin_guardar`, no el foco): eso arregla que se borrara al llegar el catálogo;
  - `load_raw`/`parse_config` se guardan según la hora y el tamaño de `sync_config.toml`, que se vuelven a mirar antes de cada escritura, porque es editable a mano.
- **«Ajustes»:** `marcar()` solo cambia el botón de antes y el nuevo, y la barra solo se repinta si cambia un chip.

**R2. Lo que no se ve no se construye, y lo construido se guarda.**

- **Bloques que pocas veces se ven** (los avisos opcionales, «Avanzado», la barra de acciones del catálogo, el formulario de «Conexión» no elegido) se crean la primera vez que hacen falta.
  - Se crean **antes** de enseñar la ventana o como respuesta a un clic, nunca después de enseñarla para «terminarla».
- **Los apartados de «Ajustes»** se construyen la primera vez que se visitan y luego se ocultan (`grid_remove`). Cumplen un contrato:
  - `al_mostrar()` refresca lo suyo;
  - `al_ocultar()` pausa su `Sondeo` e `Indicador`;
  - `invalidar()` lo llama `Panel.terminar`, en vez de reconstruir.
  - Una prueba diferencial compara un apartado tras N visitas con uno recién hecho.
- **Los apartados con secretos no se guardan nunca**:
  - el QR se construye al enseñarlo y se destruye al ocultarlo;
  - su protección de capturas se pone antes de crear la imagen y se quita al destruirlo, como hoy;
  - su línea («no aparece en capturas»…) se calcula cada vez;
  - `tests/test_captura_pantalla.py` añade: salir y volver, y el QR que llega después.

**R3. Las listas que crecen con los datos, en un solo widget [decidido sin el dueño].**

- **La medida que decide:** en la etapa 2 se mide en Windows, con 5, 10, 20 y 50 filas, una tabla sobre un `tk.Canvas` contra filas ttk ligeras (≤ 4 widgets por fila). Se usa el Canvas donde gane.
- **El Canvas, medido en Linux con 50 filas:**

  | | 0.7.1 | Canvas |
  |---|---|---|
  | Construir | 940 ms | 90–105 ms |
  | Elegir | 19 ms | 1,2 ms |
  | Pasar el ratón | — | 1,1 ms |
  | Refrescar | 940 ms | 36 ms |

- **Candidatas:**
  - **«Dispositivos» y la tabla del editor de flags**: hoy usan `ui.tk.Tabla` (`tk_fleet.py`, `tk_pairs.py`). `Tabla` se rehace sobre el Canvas manteniendo `filas`, `orden`, `elegida`, `cabeceras` y `al_elegir`, y añade `leer()` (lo dibujado como texto).
  - **La lista de «Parejas»** (`tk_pairs.ListaParejas`), con un adaptador que mantiene lo que la usa:
    - `filas[nombre]` es un diccionario con `"fila"` y demás, y lo leen `tests/test_tk_screens.py` y `puede_dejar`;
    - la casilla es un indicador: elegir la fila no la cambia, la cambian «Usar aquí»/«Quitar».
- **Se quedan en ttk** (R1/R2 y R5 bastan):
  - la lista de la principal, que tiene casillas de varias selecciones con `BooleanVar` compartidas por dos botones y «Marcar todas»;
  - los hallazgos de «Reparación» (tarjetas con botón y texto que se parte en líneas);
  - `tabla_estado()` (detalle que se parte en líneas).
- **Si se hace sobre Canvas:**
  - la tabla dibuja ítems, nunca widgets embebidos: la regla de `ui.md` «no volver a meter el Visor en un Canvas» es por las ventanas embebidas, y aquí no hay;
  - sus distancias pasan por `theme.medida()`/`icons.px()`;
  - las mezclas de color van en `theme`;
  - el teclado: Tab, anillo de foco, flechas, Inicio/Fin, RePág/AvPág, Intro, sin comerse la rueda del `Visor`;
  - una ruta acortada con «…» se ve entera en el editor.

**R4. Leer después de pintar, y una sola vez.**

- **Una sola pasada por refresco:** un módulo sin Tk, `ui/instantanea.py`, junta lo que hoy se lee varias veces:
  - `pair_state`, `filters_state`, `last_run` y conflictos;
  - componentes, y `raiz_fisica` una vez (no tres);
  - `expulsion`, `bloqueo` y `del_equipo`;
  - la línea del llavero y el resumen del vigilante.
- **Cuándo y dónde:** se lanza al enseñar la ventana, en un hilo (`segundo_plano`/`Sondeo`), y se comparte con «Parejas» y «Ajustes».
- **El primer pintado** usa solo el config, `ui_prefs.json`, `last_run.json` y las copias guardadas.
- **Mientras llega:**
  - el chip de la cabecera es una píldora neutra del mismo tamaño, no «al día»;
  - lo que necesita la lectura está **desactivado u oculto hasta que llega**: «Sincronizar ahora» (estado de resync), «Abrir llavero» (foto de procesos) y «Expulsar»/«Bloquear»;
  - la raíz física se vuelve a resolver al pulsar «Expulsar»;
  - la ventana solo crece hacia abajo, sin pasar de `pantalla_util`, y no se vuelve a centrar.
- **«Reparación»** puede usar la lectura compartida para pintar si es más reciente que la última pasada y que `state/`.
  - Hacer un plan, y repintar tras ejecutarlo, **siempre** vuelve a llamar a `revisar()`.
  - `plan.execute()` vuelve a comprobar sus condiciones, porque el plan puede añadir `--yes`.
- **Sale del hilo de Tk, con su límite de tiempo:**
  - `schtasks`/`systemctl` de «Arranque automático»: `run_quiet` gana un `timeout=` opcional, solo para consultas, que devuelve un resultado 124 en vez de lanzar. Las operaciones que cambian el sistema siguen sin límite.
  - «Versiones guardadas»: el apartado se pinta primero y lee el remoto después, con un `Indicador`, no con el `working()` modal.
  - «Nombre e icono»: la lectura del volumen y los 5 iconos de color.
  - El QR: se codifica en un hilo, y la imagen se crea en el de Tk después de proteger.
  - Del asistente: `device.list_volumes()`, las comprobaciones y la verificación (`schtasks`/D-Bus), `publish_fleet_note` (un `rclone` de hasta 45 s), la sonda de escritura de `tk_crypto` y las validaciones del sistema de ficheros en cada tecla de `tk_equipo`.
- **Hijos y salida:** los hijos que se lanzan desde el contenedor (`rclone lsf`, `schtasks`) se apuntan para `matar_arbol` al expulsar o cerrar. Todos los hilos nuevos son `daemon`.

**R5. Presupuesto de widgets por pantalla**, comprobado por una prueba con 5 y con 50 parejas:

| Pantalla | 0.7.1 (5 parejas) | Objetivo |
|---|---|---|
| Principal | 51 (+4–5 por pareja) | ≤ 30, +≤ 3 por pareja |
| «Parejas» | 152 (+7 por pareja) | ≤ 70; +0 por pareja con R3, ≤ 4 sin él |
| «Ajustes», marco | 25 | ≤ 18 |
| «Ajustes», cada apartado | 5–35 | ≤ 20 (y «Reparación» ≤ 4 por hallazgo) |
| Editor de flags | 78 | ≤ 34 |
| «Dispositivos» | 33 + 7 por equipo (+24N al llegar) | ≤ 35, sin construir fichas para medirlas |
| Pasos del asistente | 7–71 | ≤ 40 |
| Pregunta del agente | 16 | ≤ 11 |

**R6. Entre un clic y su repintado, ni unidad ni procesos.**
- **Marcar una pareja** repinta al momento.
  - `ui_prefs.json` se escribe agrupado (un `after` de ~250 ms).
  - Se vuelca antes de lanzar una pasada o iniciar el servicio, y al cerrar.
  - Es un fichero de coordinación con el servicio y el agente: lo que escriben ellos sigue igual.
- **«Sincronizar ahora»** enseña la ventana de la pasada y lanza `sync.py` en el siguiente `after`.

**R7. Ventanas que se esconden en vez de destruirse [decidido sin el dueño].**
«Parejas», «Ajustes» y la ventana de la pasada se ocultan al cerrarlas (`withdraw`),
y reabrirlas es `aplicar(estado)` + enseñar. En Windows enseñar una ventana tiene un
suelo de ~45–80 ms y la primera apertura cuesta el doble que las siguientes (0.6.5:
201 contra 105 ms). Es la palanca que lleva «Abrir Parejas» a ≤ 0,15 s.

- **Cuidados:**
  - la captura del ratón (`grab`) se pone y se suelta como hoy;
  - lo que se cancelaba al destruirse (`Sondeo`, `Indicador`) se pausa al esconder;
  - el QR nunca se esconde (R2).
- **Prueba:** reabrir equivale a abrir de cero.
- **Se mide antes de adoptarlo**, porque cambia el ciclo de vida de los diálogos.

Y cuatro cosas pequeñas:
- **La ventana de la pasada:**
  - mete el log en bloque, un `insert` y un `see` por vuelta: 10 000 líneas pasan de 4,8 s a 0,09 s;
  - **guarda la salida entera aparte** (una lista o un fichero temporal), porque «Guardar el log» es la única copia de una pasada buena;
  - solo el widget se queda con las últimas 20 000 líneas;
  - la línea de progreso se sigue reescribiendo en su sitio también dentro de un bloque.
- **La barra de espera** avanza cada 40–50 ms en vez de cada 12, con un paso proporcional para que barra a la misma velocidad: de un 10,6 % a un 2,6 % de un núcleo.
- **`update_idletasks()` en medio de construir**: ninguno, como el de `render()`. Los de `mostrar()`/`ensenar()` siguen donde están (`ui.md`).
- **«Dispositivos»** deja de construir una ficha por equipo para medir su alto (`reservar()`). Su ficha son etiquetas fijas que cambian con `configure`.

### 3. El arranque

- **`.pyc` al instalar y al actualizar [decidido sin el dueño].**
  - `deploy_code()` acaba con `deploy.precompilar(destino, python)`, que también usa `--update` porque llama a `deploy_code`. Es una función de módulo que las pruebas sustituyen.
  - Hace `compileall` de `common/` y `ui/` y un calentamiento de los módulos de la biblioteca que usa prdrive, en modo **`checked-hash`**: en FAT32/exFAT la hora de un fichero cambia entre Windows y Linux, y con hora los `.pyc` se rehacerían en cada cambio de equipo.
  - **El intérprete:** solo el runtime del dispositivo para este equipo (`cpython-314`), nunca un Python del equipo de otra versión.
  - **Los demás runtimes** se calientan en su primer uso.
  - **Si no se puede** (unidad llena, de solo lectura, sin runtime para este equipo), se sigue sin él. Tiene tope de tiempo.
  - **El relevo que cambia el runtime** precompila antes de reabrir, con su fase en la barra.
  - **Lo que no toca:** las raíces del equipo ni el agente. Sus hijos usan su propio `PYTHONPYCACHEPREFIX`, que `install/agente.py` calienta al copiar su código. La huella del agente ya excluye `__pycache__`.
  - Escribe unos MB en la unidad.
- **La pregunta del agente arranca desde un `pregunta.py`** de diez líneas: 288 → 146 ms antes de `Tk()`, y 111 ms con los imports perezosos.
  - Hace lo mismo que `cmd_pregunta`: `import ui` antes que `tkinter`, `theme.nitidez()`, los mismos códigos de salida y el mismo entorno (`_opciones_hijo`).
  - Va en `CODIGO_FICHEROS` (`install/agente.py`) y en `build_installer.DATOS_FICHEROS`.
  - El agente vuelve a `agente.py pregunta` si `pregunta.py` falta.
  - Al actualizarse, el agente copia `pregunta.py` antes que `agente.py`.
- **Imports perezosos:**
  - `ui/__init__.py` y `ui/tk.py` sin `bisync`/`results`/`revision`/`components`/`conflicts`/`update` arriba;
  - `main_window` sin importar las pantallas que solo abre un clic;
  - `llavero_editor` solo con `[keychain]`;
  - `common/update.py` con `urllib`/`zipfile` dentro de las funciones;
  - `runsync.py` con lo del servicio y del llavero perezoso.
- **Cuidados de los imports perezosos:**
  - Las ayudas de ventana (`centrar`, `ensenar`, `Visor`, `pantalla_util`, `mostrar`) **se quedan en `ui.tk`**, porque las pruebas las sustituyen ahí.
  - Los nombres que sustituyen las pruebas (`runsync.ui`, `runsync.prioridad`, `runsync.update`…) siguen existiendo en el módulo.
  - Antes de aplicar una actualización se importa todo lo que el proceso vaya a necesitar después.
  - PyInstaller recibe los `--hidden-import` que hagan falta.
  - Las pantallas que se importan tarde se precargan en el hilo de Tk a ratos, después del primer pintado, para que el primer clic no lo pague.
  - **`penwatch.py` no se toca** para ahorrar 20 ms: cambiar sus bytes deja «desfasado» cada vigilante instalado.
- **Relanzar tras una actualización:** hoy la ventana nueva puede encontrarse el cerrojo de la vieja (`tomar_ui` no espera) y decir «Ya hay una ventana abierta». Con un arranque más rápido sería lo normal. `tomar_ui` espera hasta ~3 s si quien lo tiene es el proceso padre. Va con prueba.
- **El servicio no retrasa la ventana.**
  - El bucle del servicio mira `stop_requested()`/`pen_present()` cada segundo.
  - El llavero y el cerrojo siguen cada 5 s: son una foto de procesos.
  - Quien lo para mira cada 0,1 s.
  - De media, de ~2,5 s a ~0,6 s de espera.
  - La ventana sigue abriéndose **después** de parar el servicio: así se mantiene que con la ventana abierta no hay servicio.

### 4. Tk 8.6, el instalador y la CI

- **La CI ejecuta la suite dos veces**:
  - una con el 3.11 de `setup-python` (Tk 8.6: la versión mínima y el pintor de respaldo);
  - otra con el runtime fijado (3.14.8, Tk 9.0.4) en Linux y Windows: el único sitio donde se prueba el camino SVG.
  - El runtime se baja en un paso previo (comprobado su SHA-256, en caché), no en una prueba, porque la suite no toca la red.
  - Ya pasa entera en local: 110 de 110 ficheros.
- **El instalador se compila con Python 3.14.8** [decidido sin el dueño]. En Windows ya trae Tk 9.0.4.
  - Lleva `pyinstaller` fijado a una versión ≥ 6.22 comprobada, porque hoy va sin fijar.
  - `build_installer.py` comprueba Tk ≥ 9.
  - El flujo de release prueba el `.exe` construido (`--probe`).
  - El `.exe` deja de abrir en Windows 8.1, cosa que se dice en `docs/guia/`. Los dispositivos ya piden Windows 10.
  - Va en la etapa 3: el asistente es de una vez.
  - Pasar de `--onefile` a `--onedir` queda como pregunta abierta.
- **Python del equipo** («instalación ligera», `runsync.pyw`): se queda.
  - Con Tk 8.6 va por el pintor de respaldo, con el mismo aspecto y más lento.
  - **Se cambiará `install/device.py:check_python()`.** Hoy importa `tkinter` en su propio proceso: con el `.exe` mira el Tk del `.exe`, no el del equipo.
  - Preguntará al Python del equipo con un subproceso (`DEVNULL` y `CREATE_NO_WINDOW`, porque el `.exe` no tiene consola).

### 5. La comprobación de tiempos que se queda (`rendimiento.yml`)

El banco temporal (`banco/`, `banco-ui.yml`) se convierte en `rendimiento.yml`.

- **Cuándo corre:** en cada PR que toca `ui/`, `common/`, `runsync.py`, `sync.py`, `agente.py`, `pregunta.py`, `penwatch.py`, `install/`, `prdrive-install.py` o `build_installer.py`, y a mano.
- **Dónde:** en Windows x64 y Linux, con el runtime fijado. ARM64, a mano.
- **Mide las pantallas de verdad** con un dispositivo de muestra de 5 y de 50 parejas:
  - los momentos de las dos tablas de «Qué se quiere», al 100 % y al 150 %;
  - el `apply()` de cada ventana;
  - el suelo de una ventana vacía (`tk-bare`), para normalizar.
- **Falla un PR** solo por:
  - **cuentas deterministas**: widgets por pantalla (R5), `<<ThemeChanged>>` al abrir pantallas, estilos creados tras el primer widget, módulos importados antes del primer pintado;
  - **un empeoramiento claro frente a `main` medido en el mismo trabajo**: más de un 25 % y más de 30 ms en un momento de las tablas.
- **Los objetivos** salen en el resumen del trabajo, frente a lo medido, pero no hacen fallar. La máquina de GitHub varía de una ejecución a otra.
- **Lo que se quita:** la mitad de Qt, la 0.6.5 y las variantes de prueba.
- **Para el equipo del dueño:** `PRDRIVE_PERF=1` escribe en el registro lo que tarda cada momento.

### 6. Pruebas

- **Lo que se adapta:**
  - `test_controles` deja de comparar nombres «Sobre…» y mira los bits de estado y las variantes de `_CARA`.
  - Las pruebas que buscan casillas, botones o filas por widget se adaptan a las vistas en el sitio y, si R3 lo adopta, a `leer()`:
    - `test_tk_servicio`, `test_ui`;
    - `test_tk_screens` (`lista.filas[n]["fila"]`, `tabla.marco.winfo_children()`);
    - `test_tk_segundo_plano`.
- **Lo nuevo:**
  - **Paridad:** la misma pieza por SVG y por el pintor de respaldo coincide en alfa, con tolerancia, y las pruebas de alineación de iconos pasan con los dos.
  - **Iconos:** los 25 iconos sin Tk salen byte a byte iguales.
  - **Estilos:** ningún `<<ThemeChanged>>` al abrir ninguna pantalla.
  - **Widgets:** el presupuesto de R5 con 5 y 50 parejas.
  - **Vistas y ventanas:** las diferenciales de R1, R2 y R7, y la de «desactivado ⇔ ocupado».
  - **El aviso de fallo** abierto dos veces en el mismo hilo (`test_daemon_aviso`), en la pata de Tk 9.
  - **La pasada:** 25 000 líneas con líneas de progreso en medio de un bloque, y «Guardar el log» completo.
  - **El relanzado** con el cerrojo del padre.
  - **`precompilar()`** sustituido, y una vez de verdad sobre un directorio temporal.
- Todo corre en las dos patas: Tk 8.6 y Tk 9.

## Etapas

Cada etapa es un PR con su versión y un título para el usuario, y se mide con
`rendimiento.yml`. **Cada PR lleva lo suyo:**
- la documentación que cambia su comportamiento (`ui.md`, `service.md`, `agent.md`, `updating.md`, `pairing-qr.md`, `repair.md`, `commands-testing.md`, `provisioning.md`);
- la regla de `.claude/rules/` de cada módulo nuevo (`tests/test_reglas_claude.py` falla sin ella);
- las listas de ficheros (`CODIGO_FICHEROS`, `DATOS_FICHEROS`, el mapa de `AGENTS.md`);
- y sus pruebas.

Cada etapa tiene su propio plan en `docs/superpowers/plans/`. El de la siguiente se
escribe cuando la anterior está medida.

1. **1a. Sin riesgo visual** (lo primero, para que todo lo demás se mida):
   - `rendimiento.yml` y la pata de Tk 9 en la CI;
   - el `_png` memoizado y la letra (1d);
   - los imports perezosos y `pregunta.py`;
   - `.pyc` y el relanzado;
   - el ritmo del servicio;
   - el log en bloque con la salida entera aparte, y la barra de espera;
   - el `timeout=` de las consultas de `run_quiet`;
   - el editor de «Parejas» que no se borra.

   **1b. El motor:**
   - SVG con respaldo, y el icono de la ventana;
   - la superficie por bits de estado;
   - ningún estilo tras el primer widget;
   - la medida en Windows del alfa binario, y la decisión (1c).
2. **2. La ventana abierta** (la prioridad del dueño):
   - **R1:** la principal con `aplicar()`, «Parejas» en el sitio con la llegada del catálogo por diferencias, y «Ajustes» con `marcar()` de dos botones;
   - **R6:** sin unidad ni procesos en el clic;
   - **R4:** `ui/instantanea.py` y las lecturas de los apartados de «Ajustes» después de pintar;
   - **R2:** apartados guardados con su contrato, y el QR aparte;
   - **R7:** medirlo y adoptarlo si gana;
   - **R3:** medir Canvas contra filas ttk ligeras en Windows, y decidir.
3. **3. El resto:**
   - «Dispositivos», el editor de flags y la tabla si R3 la adoptó;
   - los pasos del asistente y sus lecturas;
   - la pregunta del agente a ≤ 11 widgets;
   - el instalador con 3.14.
4. **4. Limpieza:**
   - quitar `banco/`;
   - filas nuevas de máquina real: primer arranque en frío desde una memoria USB, `.pyc` en FAT32 y exFAT entre sistemas, y el aspecto en una pantalla de Windows de verdad.

## Decisiones para revisar

Tomadas sin el dueño el 08/10/2026:

1. **La superficie por bits de estado** en vez de las 552 variantes (§1b). Mismo aspecto.
2. **Piezas con alfa binario solo si en Windows ganan más de 20 ms** (§1c). Si se adoptan, en tema oscuro hay unos píxeles de esquina fuera de tono sobre avisos de color.
3. **Una tabla sobre Canvas** para «Dispositivos», el editor de flags y la lista de «Parejas», si en Windows gana a filas ttk ligeras (§2 R3). El dueño descartó la interfaz entera sobre un Canvas; esto es un componente que se adopta por medida.
4. **Ventanas que se esconden en vez de destruirse** (§2 R7), si en Windows gana.
5. **`.pyc` precompilados en la unidad** al instalar y actualizar, en modo `checked-hash` (§3): unos MB más en la unidad.
6. **El instalador con Python 3.14 y PyInstaller fijado**: el `.exe` deja Windows 8.1 (§4).
7. **La comprobación de tiempos falla un PR** por cuentas deterministas y por empeorar claramente frente a `main` en el mismo trabajo, no por los objetivos (§5).

Descartado tras la revisión: abrir la ventana antes de parar el servicio. Rompía que con la ventana abierta no hay servicio, del que dependen guardar «Parejas», «Reparación», «Expulsar» y el cerrojo del servicio. El ritmo de 1 s / 0,1 s deja la espera en ~0,6 s de media.

## Preguntas abiertas

- **El alfa binario en Windows** (§1c), **la tabla sobre Canvas** (§2 R3) y **esconder en vez de destruir** (§2 R7) se deciden por medida en las etapas 1b y 2.
- **El instalador `--onefile` frente a `--onedir`** (§4).
- **El primer arranque en frío desde una memoria USB** (unos 80 MB y 190 ficheros), y **los `.pyc` en FAT32**: filas de máquina real.
- **El aspecto en una pantalla de Windows de verdad**: la máquina de GitHub pinta, pero nadie la ha mirado.
- **Tk 9.0.4 sin API de accesibilidad**: comprobado en la biblioteca de Linux, no en la DLL de Windows.

## Fuera de alcance

- El motor (`sync.py`), la lógica del agente y la bandeja, que ya es nativa.
- Funciones nuevas o cambios de aspecto.
- Qt, Rust, el navegador y la interfaz entera sobre un Canvas.
- Quitar el Tk con Xft de Linux.
- Quitar estilos del sistema de diseño que hoy no se usan: es orden y no velocidad (6–16 ms).
- La accesibilidad: Tk no la tiene, así que nada empeora.

## De dónde sale cada número

- `docs/superpowers/pruebas/2026-10-08-banco-interfaz-resultados.md` (banco en GitHub Actions: Windows x64 y ARM64, Linux) y su artefacto en bruto (`crudo.jsonl`, con el detalle por apartado y la llegada del catálogo).
- Las investigaciones del 08/10/2026 (en la sesión que escribió esto):
  - el mapa de `theme.py`/`icons.py`;
  - la auditoría de cada pantalla;
  - la prueba del SVG y de las superficies por estado;
  - la de la tabla;
  - la de Tk 8.6, el instalador y la CI;
  - la del arranque.

  Todo en Linux con el runtime fijado, salvo lo que dice Windows.
- Las tres revisiones adversarias de la versión 1:
  - hechos contra el código;
  - lo que se rompe u olvida (las 26 tareas del sistema que hace la interfaz);
  - si llega a los objetivos, con un modelo de costes de Windows.
