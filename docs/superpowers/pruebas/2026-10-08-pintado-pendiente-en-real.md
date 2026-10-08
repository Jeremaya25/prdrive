# Plan: ventanas que aparecen ya pintadas y el menú propio de la bandeja, en Windows real

Fecha: 2026-10-08 · Estado: **por hacer**. Los resultados van en un fichero
aparte, al lado de este (`2026-10-08-pintado-pendiente-en-real-resultados.md`).

Tras el rediseño de la 0.7.0, en Windows las ventanas tardaban en abrir y se
veían rellenarse widget a widget; el menú de la bandeja seguía siendo el de
Windows y la barra de desplazamiento, al pulsarla, enseñaba una raya clara en
medio. Lo que se cambió:

- `tk.Visor` ya no es un `Canvas`: el interior va con `place` dentro de un
  marco, y no se mapea (ni se pinta) hasta que la ventana se ve.
- `tk.ensenar()` enseña la ventana encubierta por DWM (`DWMWA_CLOAK`), deja que
  se pinte entera y solo entonces la descubre.
- `theme._variantes_sobre()` crea al poner el tema los estilos «Sobre…» que
  antes se creaban al aparecer cada control, y con ellos una vuelta entera de
  repintado.
- La barra de desplazamiento pone `gripsize=0` (Tk 9) y el borde del pulgar
  del color de su relleno.
- El menú de la bandeja es propio (`MFT_OWNERDRAW`): cada fila la pinta
  `bandeja_windows.Api.pintar()` con el aspecto del tablero «Bandeja del
  sistema».

Los tests lo conducen con Windows de mentira (`tests/test_tk_ensenar.py`,
`tests/test_bandeja_windows.py`, `tests/test_controles.py`). En el equipo de
desarrollo se vio, con las ventanas encubiertas y capturadas sin enseñarlas,
que «Parejas» sale entera al descubrirse y que el menú de `TrackPopupMenu`
llega a `WM_MEASUREITEM`/`WM_DRAWITEM` y sale con las filas propias. **Nadie lo
ha visto en una pantalla.** «Lo esperado» sale del código y de la
documentación de Windows; si no coincide, se apunta tal cual.

## Equipos

- **W**: Windows 11 x64, con un dispositivo prdrive 0.7.1 y el agente.
- **W10**: Windows 10 22H2 (otro marco de menú, sin esquinas redondeadas).

## 1. Las ventanas

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| P1 | W | Abrir la ventana principal, «Parejas», «Ajustes» y el asistente («Instalar…» o `prdrive-install.py`). | Cada una aparece **ya entera**, de golpe, sin verse rellenar widget a widget ni un recuadro vacío antes. | `tk.ensenar()` |
| P2 | W | Lo mismo, cronometrando de clic a ventana en «Parejas» con 5 parejas, y comparar con la 0.7.0. | Bastante menos que con la 0.7.0 (en el equipo de desarrollo, cargado, de ~9 s a ~2,5 s). | `tk.Visor`, `theme._variantes_sobre()` |
| P3 | W | En «Parejas», bajar con la rueda, arrastrar el pulgar de la barra y pulsar sus flechas; abrir «Ajustes» en una pantalla pequeña (1366×768) para que aparezca la barra. | Se desplaza como antes, sin dejar restos pintados abajo ni encima de la barra horizontal. | `Visor._desplazar()`, `place` |
| P4 | W | Arrastrar el pulgar de la barra de desplazamiento (claro y oscuro). | El pulgar, al pulsarlo, es un bloque liso más oscuro: **sin la raya clara en medio** ni filetes claros alrededor. | `theme.apply()`, `gripsize` |
| P5 | W | Con un error largo en el asistente que obligue a desplazar (`Visor.ver()`), pulsar el botón de reintentar. | El botón queda a la vista entero, como antes. | `Visor.ver()` |
| P6 | W | Con Windows en oscuro, abrir la ventana principal, «Ajustes», un diálogo («Parejas»), el asistente y «¿Atender esta unidad?» (el agente). | La barra de título de todas, del color del papel oscuro (#171512), con el título en claro: **ni blanca ni gris**. En el equipo de desarrollo (Windows 11 26200, 100 %) se midió en pantalla la de la raíz y la de un diálogo: #171512; antes, #F2F2F2. | `tk.ensenar()` → `theme.barra_titulo()` |
| P7 | W10 | P6. | La barra, **negra** (Windows 10 no admite un color propio: `DWMWA_CAPTION_COLOR` lo rechaza), y ya oscura al aparecer, sin un fotograma claro. | `DWMWA_USE_IMMERSIVE_DARK_MODE` |

## 2. El menú de la bandeja

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| B1 | W | Clic derecho en el icono del agente, con el tema claro. | Fondo blanco, filas de 34 px, Noto Sans, glifos en tinta, separadores finos claros, «Agente 0.7.1» en gris; como el tablero «Bandeja del sistema». | `Api.pintar()`, `aspecto()` |
| B2 | W | Pasar el ratón por las filas y abrir el desplegable de un dispositivo. | La fila bajo el ratón y la del desplegable abierto, en azul suave; el galón a la derecha en gris y **sin la flecha negra de Windows encima**. | `pintura()`, `ExcludeClipRect` |
| B3 | W | En el desplegable: «Configurar» en negrita, «Sincronizar ahora» apagado si la unidad no se atiende. | Negrita la de por defecto; lo apagado, en gris y sin resaltar al pasar por encima. | `pintura()` |
| B4 | W | Doble clic en el nombre de un dispositivo. | Se abre su ventana («Configurar»), como antes. | `SetMenuDefaultItem` |
| B5 | W | Abrir el menú y moverse con las flechas, Intro y Esc. | Funciona como antes; las filas resaltadas siguen el teclado. | `MFT_OWNERDRAW` + texto |
| B6 | W | Pasar Windows a oscuro (Personalización → Colores) **sin reiniciar el agente** y abrir el menú. | El menú sale ya en oscuro (superficie #201D19, tinta clara). Apuntar cómo pinta Windows el marco del menú. | `theme.sistema_oscuro()` en cada apertura |
| B7 | W | Con la escala de pantalla al 150 % (cerrar sesión y volver). | Filas, letra e iconos crecen en proporción, nítidos. | `GetDeviceCaps(LOGPIXELSY)` |
| B8 | W | Con Narrador, abrir el menú y recorrerlo. | Lee el texto de cada entrada. | `MIIM_STRING` conservado |
| B9 | W10 | B1 y B2. | Igual, con el marco cuadrado de Windows 10. | — |

## Qué hacer con lo que salga

- **P1 con la ventana que se rellena**: comprobar si DWM aceptó el
  `DWMWA_CLOAK` (Windows 8 en adelante); si no, `ensenar()` cae a un
  `deiconify()` normal y hay que buscar otra forma.
- **P6/P7 con una barra clara**: es una ventana a la que se le cambia el estilo
  (`resizable`, `transient`…) después de `ensenar()`, que rehace el envoltorio;
  apuntar cuál. En W10, si sale clara y se oscurece al pasarle por encima, la
  barra no se repinta sola: hay que forzarlo (`SetWindowPos` con
  `SWP_FRAMECHANGED`).
- **P2 aún lenta**: perfilar `mostrar()` con la ventana encubierta; lo que
  queda es Tk pintando cada widget (el diseño tiene el triple que la 0.6.5).
- **B2 con la flecha de Windows**: el recorte de `pintar()` no basta en esa
  versión; apuntar cuál.
- **B6 con el marco claro**: es el borde que pinta Windows, no las filas;
  apuntarlo en `docs/agents/reference/tray.md`.
