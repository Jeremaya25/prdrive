# Bloques en lienzo: que lo que cambia no se vea a trozos — diseño

Fecha: 28/10/2026. Estado: **diseño, pendiente de que lo revise el dueño**.
Medidas: `docs/superpowers/pruebas/2026-10-28-repintado-resultados.md`.
Sigue a `docs/superpowers/specs/2026-10-08-frontend-rapido-design.md`, que midió abrir
pantallas, no repintar las que ya están abiertas.

Decidido con el dueño el 28/10/2026:
- **Se descarta CustomTkinter.** Rehecha «Parejas» con él, cambiar de vista tarda un 25 %
  más (0,88 s contra 0,70 s) y la ventana tiene el triple de ventanas nativas (resultados §4).
- **Se pasa a lienzo lo que se mueve, empezando por «Parejas».**
- **La comprobación de tiempos mide el repintado al cambiar de vista** (`vista-*`). Hecho
  con esta spec: es la etapa 0.

Esto **reabre en parte** «hacer toda la interfaz sobre un Canvas», que la spec del
08/10 descartó: solo los bloques que se ven y no se tocan. Lo que se toca sigue siendo ttk.

Lo demás va marcado **[decidido sin el dueño]** y reunido en «Decisiones para revisar».

## Qué se quiere

Que un cambio dentro de una ventana abierta se vea **de golpe**: sin trozos a medias y
sin piezas en su sitio de antes. Con el mismo aspecto, el mismo comportamiento y el mismo
teclado. Sigue siendo Python puro con el Tk del dispositivo.

**Objetivos** [decidido sin el dueño]. En la CI, la máquina Windows x64 de GitHub al 100 %
con 5 parejas, mediana (`[meta_ms]` de `presupuesto.toml`: se informan, no hacen fallar).
«Referencia» es el equipo de los resultados (Windows, 133 %).

| Momento | Hoy, referencia | Hoy, CI | Objetivo CI | Objetivo referencia |
|---|---|---|---|---|
| `vista-catalogo-otra-vez`, `vista-dispositivo` | ~0,7 s | lo mide la etapa 0 | **≤ 50 ms** | ≤ 100 ms |
| `vista-catalogo` (la primera vez: construye su bloque) | ~1,1 s | lo mide la etapa 0 | **≤ 100 ms** | ≤ 200 ms |

Y tres reglas que no son números:
- **Un cambio no mueve lo que no cambia.** Al cambiar de vista, nada de lo que está debajo
  del bloque que cambia se mueve, y la ventana no cambia de tamaño ni se vuelve a centrar.
- **Solo se repinta lo que cambia.** Los `<Expose>` de un cambio de vista son los de los
  widgets que aparecen o cambian (hoy 19–20, casi todos de lo que solo se ha movido).
- **Ningún `<<ThemeChanged>>` ni estilo nuevo al cambiar** (`tema.vista`, `estilos.vista`:
  techo 0 desde la etapa 0).

## Por qué se ve a trozos (medido)

1. **En Windows cada widget de Tk es una ventana del sistema** y se pinta por su cuenta.
   Mientras unos ya están pintados y otros no, los que faltan enseñan lo que había antes en
   su sitio. Es lo que se ve: la franja `[defaults]` asomando dentro del aviso ámbar.
2. **Cambiar a «Catálogo» mete el aviso encima de la franja y empuja todo lo de debajo**:
   la franja, la lista, la barra de botones y el pie. La nota del pie además pasa de una
   línea a dos. La primera vez la ventana crece y se vuelve a centrar.
3. **Cada widget que se mueve se pinta dos veces**: una dentro del clic (`Visor.crecer()`
   resuelve la geometría y pinta) y otra cuando Windows se lo pide (`WM_PAINT` → `<Expose>`).
4. **Pintar un control dibujado es caro**: 10–19 ms un botón, 15 ms un chip, 34 ms la
   franja y 40 ms el aviso. ttk dibuja cada pieza como nueve copias de imagen con alfa, una
   por trozo. Con ttk llano el mismo cambio cuesta la cuarta parte.
5. **El SVG no tiene que ver**: el cambio crea 2 imágenes, y con el pintor de Python cuesta
   lo mismo.
6. **Un lienzo no tiene ese problema**: pinta todos sus elementos de una vez, en memoria, y
   copia el resultado. La misma escena en un lienzo tarda 12–20 ms, sin ningún `<Expose>`,
   y la lista de «Parejas», que ya es un lienzo, se repinta entera en menos de 5 ms.

## Enfoques

- **A. Bloques en lienzo y sitio reservado (el elegido).** Lo que se ve y no se toca pasa a
  un lienzo, y lo que aparece o desaparece tiene su hueco guardado. Quita el movimiento y
  abarata lo que sí cambia.
- **B. Solo reservar el sitio.** Quita el movimiento, pero el aviso y la franja siguen
  costando 40 y 34 ms cada vez que se pintan. Va dentro de A.
- **C. Piezas más baratas** (alfa binario −35/−50 %, piezas opacas −25 %). Acorta los
  trozos pero no los quita, y en tema oscuro deja esquinas fuera de tono. Queda como
  posibilidad para los botones (etapa 4).
- **D. Toda la ventana en un lienzo, botones incluidos.** Lo más rápido, pero obliga a
  rehacer foco, Tab, Intro y Escape, estados y lo que leen los tests. Fuera de alcance.
- **E. CustomTkinter.** Descartado (resultados §4).

## Diseño

### 1. Tres reglas para las ventanas

1. **Lo que se ve y no se toca va en un lienzo**: avisos, franjas, chips, rótulos y textos.
   Un bloque es un `tk.Canvas` con elementos.
2. **Lo que se toca sigue siendo ttk**: botones, campos, casillas sueltas y el interruptor.
   Conservan el foco, el orden del Tab, Intro y Escape, sus estados (`disabled`, `active`)
   y las piezas del tema.
3. **Un cambio no mueve lo que no cambia**: lo que aparece y desaparece tiene su hueco
   reservado en todas las vistas, como las bandas de la ventana principal (`ui.md`).

### 2. Las piezas de dibujo, compartidas (`ui/tk_lienzo.py`)

Hoy viven dentro de `ui/tk_tabla.py`. Se sacan a un módulo propio, sin cambiar cómo dibuja
la tabla, para que la tabla y los bloques dibujen lo mismo de la misma manera:

- **La letra**: la fuente que llevan los estilos (`theme.fuente_tcl(rol)`), medida con
  `font measure` sobre la misma especificación y sujeta por un elemento de texto oculto del
  lienzo (hoy `TablaLienzo._fuente`, `_linea`, `_medir`, `_cortar`).
- **El chip**: la pastilla del tema estirada a su tamaño en una sola imagen, guardada por
  intérprete y tamaño (`_pieza_chip`, `_estirada`, `_Chip`), con su disco y su palabra.
- **La tarjeta**: las cuatro esquinas recortadas de la pieza de `icons.caja()` y los lados
  como rectángulos (hoy `_recorte` y `_tarjeta`).

**Regla del lienzo: cada pieza es una sola imagen, ya del tamaño al que se dibuja.** Nunca
un nueve-trozos: lo caro de ttk son las nueve copias por control en cada pintado.

`tests/test_tk_tabla.py` no cambia y tiene que seguir en verde, también la igualdad píxel a
píxel de su §9a: es la prueba de que sacar las piezas no ha cambiado nada.

### 3. El bloque (`ui/tk_bloque.py`, `BloqueLienzo`)

`BloqueLienzo(parent, superficie="")` dibuja en **un lienzo** una columna de piezas:

- `Aviso(clave, titulo, cuerpo, tono, icono=None)`: lo que dibuja hoy `theme.aviso()`. La
  tarjeta del tono, la baldosa (`icons.baldosa()`), el título en seminegrita y el cuerpo en
  tinta suave, partido a su ancho.
- `Franja(clave, rotulo, chip, texto, acciones=())`: lo que es hoy la franja `[defaults]`.
  La tarjeta gris, el rótulo espaciado (`theme.rotulo()`), el chip y la pista. Sus
  `acciones` son botones ttk que el que llama ya ha creado con el lienzo como padre. El
  bloque los pone a la derecha con `create_window`, y los enseña o esconde con
  `itemconfigure(state=…)` sin mover nada más (regla 2; ver «Decisiones», 3).

Cómo se usa:
- `poner(piezas) -> bool`: compara por `clave`, como `TablaLienzo.poner()`. Una pieza igual
  no toca nada, una cambiada se dibuja de nuevo (solo ella) y una que se va se borra.
  Devuelve si ha cambiado el alto pedido.
- `reservar(alto)`: el alto mínimo del bloque, para guardar el sitio de lo que no siempre
  está (regla 3).
- `alto(pieza) -> int`: lo que ocuparía una pieza, medido con la letra y sin dibujarla.
  Sirve para reservar desde el primer pintado el sitio de una pieza que aún no se ha
  construido (el aviso del catálogo).
- `leer()`: el texto de cada pieza tal como se dibuja, para los tests.
- `marco`: el lienzo, que es lo que se coloca en la ventana.

Lo que hereda de la tabla, igual:
- Los colores se leen del tema al dibujar (claro y oscuro).
- No crea ningún estilo de ttk ni manda ningún `<<ThemeChanged>>`.
- Pasa la rueda del ratón al `Visor`.
- No toma el foco (`takefocus=0`): el Tab se salta el bloque, como se salta hoy las
  etiquetas.
- Su fondo es el de la superficie donde está, así que las esquinas de las tarjetas caen
  sobre el color que toca.

Fuera del bloque y como hoy: el interruptor, las barras de botones, la lista
(`ListaParejas`) y el pie.

### 4. «Parejas»

- **Arriba**: el aviso y la franja `[defaults]` son **un solo** `BloqueLienzo`, en las filas
  2 y 3 de hoy. Al cambiar de vista solo cambia lo que hay dentro de ese lienzo.
- **El hueco del aviso está ocupado en las dos vistas, con el mismo alto**
  [decidido sin el dueño, ver «Decisiones», 1]. «Catálogo» lleva el aviso ámbar de hoy.
  «Este dispositivo» lleva uno con la misma forma y otro tono que diga de qué va esa vista.
  El bloque reserva el alto del mayor de los dos.
- **La franja** pone sus botones de cada vista («Ajustes de este dispositivo…» y «Volver a
  los del catálogo», o «Ajustes del catálogo…») como `acciones`, y solo enseña los de la
  vista que se ve.
- **Las dos listas ocupan el mismo alto**: el de la que tenga más filas, como `minsize` de
  su fila de la rejilla. «Este dispositivo» enseña además las parejas que solo están aquí,
  así que las dos vistas pueden tener distinto número de filas, y sin esto la barra de
  debajo se movería. La lista más corta deja papel en blanco bajo su tarjeta
  [decidido sin el dueño, ver «Decisiones», 4].
- **El pie reserva dos líneas** en las dos vistas, para que la nota del catálogo, más
  larga, no haga crecer la ventana [decidido sin el dueño, ver «Decisiones», 4].
- **La ventana no crece al cambiar de vista.** Con los huecos reservados desde el primer
  pintado, `refrescar()` deja de pedir `crecer()` por un cambio de vista, y no hay nada que
  volver a centrar.
- **Las barras de botones** se siguen cambiando con `grid_remove()`/`grid()`: están debajo
  de la lista y ya no se mueven, así que solo se pintan los botones que aparecen. Si eso
  pasa del objetivo, lo resuelve la etapa 4.
- Lo de hoy no cambia: lo del catálogo se crea la primera vez que se ve (y con ello su
  pieza del bloque), el Tab va de arriba abajo como se ve, y `dlg.lista`, `dlg.pantalla` y
  `dlg.indicador` siguen ahí para los tests.

### 5. Medir (etapa 0, hecha con esta spec)

`tests/rendimiento/driver.py` (`cambiar_vistas()`) mide en el flujo `parejas` (5 y 50
parejas al 100 %, y 5 al 150 %):

| Momento | Qué es |
|---|---|
| `vista-catalogo` | Pasar a «Catálogo» la primera vez, cuando se construye su bloque |
| `vista-dispositivo` | Volver a «Este dispositivo» |
| `vista-catalogo-otra-vez` | Pasar a «Catálogo» otra vez: solo enseñar y esconder |

- **Cuándo empieza y cuándo acaba.** Cada uno va del `invoke()` de la opción, que es lo que
  hace un clic, hasta que el `update()` de después deja la ventana quieta. Así entra la
  segunda ronda de pintado: cortar en el último `<Expose>` deja fuera la mitad (resultados §1).
- **El desglose**, en `crudo.jsonl`, con la traza de `_trazar()`: `fases` (`clic`, `pintar`
  y, dentro del clic, `refrescar` y el `crecer` del visor), los `<Expose>`/`<Configure>` por
  clase de widget y la geometría (`movidos`, `redimensionados`, `nuevos`).
- **Lo que hace fallar.** `tema.vista` y `estilos.vista`, con techo 0. Los tiempos se juzgan
  contra la base como los demás momentos, y sus metas son las de «Objetivos».
- **Tras la etapa 3**, `geometria.movidos` de un cambio de vista pasa a ser una cuenta con
  techo 0 (`movidos.vista`), para que nadie vuelva a meter algo que empuje.

## Etapas

0. **Medir** (esta spec): los momentos `vista-*`, sus techos y sus metas, y los resultados
   de hoy. La primera ejecución en la CI pone la columna «Hoy, CI» de «Objetivos».
1. **Sacar las piezas de dibujo** a `ui/tk_lienzo.py` sin cambiar nada: `test_tk_tabla` en
   verde, píxel a píxel.
2. **`BloqueLienzo`** con `Aviso` y `Franja`, y sus pruebas (abajo). Antes de usarlo en una
   pantalla, se mide lo que cuesta repintar un bloque con su aviso y su franja frente a
   `theme.aviso()` más la franja de hoy, en el equipo de referencia y en la CI.
3. **«Parejas»** con el bloque y los huecos reservados (diseño §4). Se mide `vista-*` en la CI
   y en el equipo de referencia, y entra el techo `movidos.vista`.
4. **Las barras de botones**, solo si `vista-*` sigue por encima del objetivo. Se mide qué
   cuesta: reconfigurar en su sitio los botones que comparten posición, o piezas más
   baratas para los botones (enfoque C). Se elige por medida.
5. **Las demás pantallas**, una a una y **siempre midiendo antes**: primero un momento suyo
   en la comprobación de tiempos, luego el cambio. Candidatas, por lo que se mueve en
   ellas: los apartados de «Ajustes» (avisos que llegan con la lectura), el asistente (los
   avisos de `Resultado` bajo los botones), la ventana de una pareja y los avisos de la
   ventana principal que aún no tienen banda reservada.

Cada etapa es su propio PR, con su área en `ui.md` puesta al día. Un módulo nuevo entra en
la regla de su área (`.claude/rules/ui.md`; `tests/test_reglas_claude.py`).

## Pruebas

- **`tests/test_tk_tabla.py`** sin cambios (etapa 1).
- **`tests/test_tk_bloque.py`** (etapa 2):
  - Igual que lo de hoy, píxel a píxel: en X11 con ImageMagick, como el §9a de la tabla, un
    `Aviso` contra `theme.aviso()` y una `Franja` contra la franja de hoy, en claro y en
    oscuro y a `tk scaling` 1,0, 1,333, 2,0 y 2,667. Se permiten solo los bordes suavizados
    de las esquinas, con un umbral escrito en el test.
  - `poner()` por diferencias: una serie al azar de piezas que van, vienen y cambian dibuja
    lo mismo que un bloque recién hecho con las últimas (la prueba diferencial de la tabla).
    Repetir las mismas no toca ningún elemento.
  - `reservar()`: el alto pedido es el mayor entre lo reservado y lo que piden las piezas.
  - Las `acciones`: enseñar y esconder un botón no mueve los demás, el botón queda asentado
    en la superficie del bloque y el Tab pasa por él.
  - Ningún `<<ThemeChanged>>` ni estilo nuevo, y el bloque no toma el foco.
- **`tests/test_tk_parejas_vista.py`** (etapa 3): cambiar de vista no mueve ningún widget
  fuera del bloque ni cambia el tamaño de la ventana, y el Tab sigue de arriba abajo. Lo
  que hoy leen los tests como etiquetas lo leen del bloque, con `leer()`, como se hizo con
  la tabla.
- **`tests/test_tk_medidas.py`**: «Parejas» sigue cabiendo en toda su matriz de resolución y
  escala con los huecos reservados.

## Decisiones para revisar

1. **Qué va en el hueco del aviso en «Este dispositivo»** [decidido sin el dueño]. Un aviso
   de otro tono con el mismo alto, por ejemplo «Estás editando este dispositivo» y «Lo que
   cambies aquí solo afecta a esta unidad; lo que vale para todas se cambia en Catálogo».
   Es texto nuevo para el usuario. La otra opción es dejar el hueco vacío, que se ve como un
   salto en blanco.
2. **Los objetivos**: ≤ 50 ms los cambios en su sitio y ≤ 100 ms la primera vez, en la CI.
3. **Botones dentro de un lienzo con `create_window`.** Un lienzo mapea sus ventanas
   embebidas en cuanto piden sitio, aunque la ventana esté retirada: es por lo que el
   `Visor` dejó de ser un lienzo (`ui.md`). Aquí son uno o dos botones, no una pantalla, y
   la etapa 2 lo mide. Si sale caro, los botones de la franja van fuera del lienzo, en su
   fila, y la tarjeta gris se dibuja detrás con el bloque.
4. **Los huecos que se reservan fuera del bloque**: el pie, dos líneas en las dos vistas (la
   otra opción es acortar la nota del catálogo a una línea); y las dos listas, el alto de la
   más larga (la otra opción es aceptar que la barra se mueva cuando las vistas tienen
   distinto número de filas).
5. **El alcance de lo reabierto**: solo los bloques que no se tocan. La interfaz entera en
   un lienzo (enfoque D) sigue fuera.

## Preguntas abiertas

- **Linux (X11)**: un widget cuesta allí la tercera parte que en Windows (spec del 08/10). Se
  sabrá con los `vista-*` de la CI de Linux.
- **El tema oscuro, el 150 % y 50 parejas** en el equipo de referencia: no se midieron.
- **La lista no cambia**, pero hay dos (la de cada vista). Si cambiar una por otra se viera
  en los `<Expose>`, se puede probar una sola lista con las filas de cada vista.

## Fuera de alcance

- CustomTkinter, Qt y cualquier otra biblioteca.
- Botones y campos dibujados en el lienzo (enfoque D).
- Cambios de aspecto, salvo el aviso nuevo de «Este dispositivo» (decisión 1).
- La accesibilidad: Tk no la tiene, así que nada empeora.

## De dónde sale cada número

- `docs/superpowers/pruebas/2026-10-28-repintado-resultados.md`: el cambio de vista
  desglosado, lo que cuesta repintar cada widget, el banco de cinco enfoques y «Parejas»
  rehecha con CustomTkinter, medidos en el equipo de referencia.
- La columna «Hoy, CI»: los momentos `vista-*` de la comprobación de tiempos, desde la
  etapa 0.
