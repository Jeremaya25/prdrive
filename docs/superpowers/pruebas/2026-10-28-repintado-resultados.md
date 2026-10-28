# El repintado al cambiar de vista en «Parejas» — resultados

Fecha: 28/10/2026. Lo que decide la spec
`docs/superpowers/specs/2026-10-28-bloques-en-lienzo-design.md`.

**El problema.** Al pasar «Parejas» de «Este dispositivo» a «Catálogo», la ventana se ve
a trozos durante un momento: dentro del recuadro ámbar que acaba de entrar asoma la
franja `[defaults]` en su sitio de antes, cortada. Se va sola cuando la ventana termina
de pintarse.

**Dónde y cómo.** Un Windows 11 de sobremesa (Intel i5-8500, pantalla de 1920×1080 al
133 %, `tk scaling` 1,333), con el Python fijado del dispositivo (3.14.8, Tk 9.0.4). Las
ventanas se abrían en un escritorio de Windows aparte (`CreateDesktopW`): se pintan de
verdad y nadie las ve. Dispositivo de muestra con 6 parejas y el catálogo igual que el
dispositivo, ya llegado. Las sondas fueron scripts de usar y tirar, fuera del repo; lo
que queda en el repo es la medida que las sustituye (`vista-*` en la comprobación de
tiempos, `commands-testing.md`).

**Lo que no se midió.** Linux, el tema oscuro, 50 parejas y la máquina de GitHub. Las
cifras de la CI llegan con los momentos `vista-*`.

## 1. Qué cuesta el cambio de vista

Cambiar de vista llama a `PantallaParejas.refrescar()`, que coloca lo de la otra vista
(`poner_vista()`: `grid()`/`grid_remove()`, nada se destruye) y, como el contenido pide
otro tamaño, `Visor.crecer()`, cuyo `update_idletasks()` resuelve la geometría y pinta
**dentro del clic**.

| Medida | Primera vez | Las siguientes |
|---|---|---|
| El clic (`invoke()`), casi todo dentro de `crecer()` | 550–820 ms | 280–475 ms |
| Desde el clic hasta que la ventana queda quieta (`update()`) | ~1,1 s¹ | **~0,7 s** |
| Lo mismo hasta el último `<Expose>`, con las piezas de hoy | 0,58–0,87 s | 0,30–0,50 s |
| … y con ttk llano (clam: sin piezas de imagen) | 0,31–0,34 s | **0,08–0,18 s** |
| `<Expose>` en el cambio | 38 | 19–20 |
| Imágenes nuevas (SVG) | 2 | 0 |

¹ La primera vez construye el bloque del catálogo (`montar_catalogo()`, 12 widgets) y la
ventana crece y se vuelve a centrar.

- **Casi todo es pintar.** Con cProfile, el tiempo está dentro de Tk (las llamadas de
  `crecer()` y el bucle de sucesos), no en Python; y con ttk llano el mismo cambio cuesta
  la cuarta parte: tres cuartos son las piezas de imagen.
- **Se pinta dos veces.** El clic ya pinta cada widget que se mueve; después Windows
  le pide a cada uno pintarse otra vez (`WM_PAINT` → `<Expose>`), y esa segunda ronda
  es la otra mitad del tiempo. Una primera sonda que cortaba en el último `<Expose>`
  daba 300–470 ms: se quedaba sin la segunda ronda. La medida buena espera al `update()`.
- **El SVG no es la causa.** Solo se crean 2 imágenes, y con el pintor de Python
  (`USAR_SVG = False`) el cambio cuesta lo mismo. Lo caro es dibujar las piezas ya hechas
  cada vez que un widget se repinta.
- **Lo que se ve.** En Windows cada widget es una ventana del sistema que se pinta por su
  cuenta. Mientras unos ya están pintados y otros no, los que faltan enseñan lo que había
  antes en su sitio: el «[DEFA LTS] catálogo remot» dentro del aviso es la franja
  `[defaults]` en su posición vieja, vista a través de las etiquetas del aviso que aún no
  se habían pintado.

## 2. Lo que cuesta repintar cada widget

Cada widget a la vista de la vista «Catálogo», por separado (`<Expose>` y
`update_idletasks()`, el menor de 5):

| Widget | Piezas suavizadas (hoy) | Alfa binario | ttk llano (clam) |
|---|---|---|---|
| Aviso ámbar (`NotaAmbar.TFrame`, 892×77) | **40,6 ms** | 22,0 | 2,8 |
| Franja `[defaults]` (`Gris.TFrame`, 892×50) | **34,0 ms** | 19,3 | 3,0 |
| Botón `Primary` 130×34 | 19,3 ms | 11,3 | 5,0 |
| Opción del interruptor (`Segmento.Toolbutton`) | 18,1–18,5 ms | 10,2–10,7 | 4,6 |
| Botones `Tonal`, `Danger`, por defecto | 17,2–17,8 ms | 10,5–11,2 | 4,2–5,0 |
| Chip (`Chip.TLabel`) | 14,4–16,1 ms | 8,5–8,8 | 4,5–4,7 |
| Botones `Quiet`, `GrisQuiet` | 10,2–11,3 ms | 9,7–10,9 | 3,0 |
| Etiqueta de texto | ~5 ms | ~5 | ~5 |
| **Los 37 widgets a la vista** | **284 ms** | 190 | 89 |

- Un solo botón cuesta lo que un fotograma entero a 60 Hz.
- Las piezas totalmente opacas (sin nada de alfa) solo bajan un 25 %: lo caro no es solo
  mezclar el alfa, son las nueve copias por widget del nueve-trozos de ttk.
- La lista (`TablaLienzo`: un lienzo con 6 filas, 12 chips y sus casillas) no entra entre
  los 14 más caros: menos de 5 ms entera.
- En la máquina de GitHub (100 %) el alfa binario ganó poco en 2026-10 (−48 ms al abrir
  «Parejas», 2–7 ms en los apartados): allí se medía abrir pantallas, donde pesa crear
  widgets, y no repintar los que ya están.

## 3. Banco: un aviso entra arriba y empuja todo hacia abajo

Una escena como «Parejas»: título, interruptor, la franja `[defaults]`, una lista de 6
filas en un lienzo, 5 botones y el pie. El aviso entra y sale 8 veces; mediana desde el
cambio hasta que la ventana queda quieta.

| Enfoque | Entra | Sale | Ventanas nativas | `<Expose>` |
|---|---|---|---|---|
| Tema de hoy (piezas suavizadas) | 159–163 ms | 229–231 ms | 28 | 9,5 |
| Piezas totalmente opacas | 123 ms | 158 ms | 28 | 9,5 |
| ttk llano (clam) | 47 ms | 79 ms | 28 | 9,5 |
| CustomTkinter 6.0 | 60 ms | 71 ms | 59 | 9 |
| **Todo en un lienzo** (rectángulos y texto) | **12–20 ms** | **12–18 ms** | **2** | **0** |

En el lienzo no hay ningún pintado suelto: el lienzo se pinta entero de una vez, en
memoria, y luego se copia. No hay trozos a medias.

## 4. «Parejas» entera, rehecha con CustomTkinter

La pantalla copiada widget a widget con CustomTkinter 6.0: los mismos textos, colores,
letras e iconos, el mismo tamaño en píxeles (`deactivate_automatic_dpi_awareness()`), la
misma lista (`ListaParejas`: CustomTkinter no tiene tabla) y lo del catálogo construido la
primera vez que se ve, como la real. El mismo arnés para las dos, 4 rondas alternadas,
mediana (entre paréntesis, el rango):

| | Tk de hoy | CustomTkinter |
|---|---|---|
| Abrir «Parejas» | 1,28 s (1,18–1,36) | 1,76 s (1,51–2,03) |
| Pasar a «Catálogo» la primera vez | 1,13 s (1,00–1,22) | 1,14 s (0,97–1,21) |
| **Cambiar de vista, las siguientes** | **0,70 s** (0,62–0,84) | **0,88 s** (0,76–1,56) |
| `<Expose>` por cambio | 20 | 64 |
| Repintar la ventana entera, sin que nada se mueva | 0,33 s | 0,09 s |
| Ventanas nativas («Este dispositivo» / «Catálogo») | 39 / 51 | 92 / 125 |
| Memoria | 77 MB | 83 MB |
| Importar `customtkinter` | — | 0,48 s |

- Con cProfile, en las dos casi todo el tiempo está dentro de Tk. Pero CustomTkinter hace
  8 veces más llamadas a Tk (6630 contra 843 en seis cambios) y procesa 4 veces más
  sucesos (863 contra 216): cada widget suyo son 2–4 ventanas nativas (un `Frame`, un
  `Canvas` y una o dos `Label`), y redibuja sus formas desde Python en cada cambio
  (`coords`, ~50 ms por cambio).
- Gana solo al repintar lo que no se mueve, porque su dibujo es más barato que las
  piezas de ttk.
- Lo demás que salió al rehacerla: sus botones no tienen foco de teclado, Intro ni
  Espacio; `CTkImage` exige Pillow (los `PhotoImage` de prdrive valen, con un aviso de
  que no se escalan); su botón segmentado no lleva iconos (hubo que tocar
  `_buttons_dict`); su carga de letras choca con `theme.cargar_fuentes()` (los
  `argtypes` de `AddFontResourceExW` son de todo el proceso); y mira el DPI cada 100 ms,
  también con la ventana quieta.

**Descartado** (el dueño, 28/10/2026).

## 5. La primera pasada de los momentos `vista-*`

La comprobación de tiempos con los momentos nuevos, en el mismo equipo y una sola ronda
(ruidosa: sirve para ver el desglose, no como cifra). 5 parejas, `tk scaling` 1,0 forzado:

| Momento | Total | `clic` (de él, `crecer`) | `pintar` | `<Expose>` | Movidos | Nuevos |
|---|---|---|---|---|---|---|
| `vista-catalogo` | 990 ms | 555 (479) | 435 | 38 | 8 | 13 |
| `vista-dispositivo` | 724 ms | 380 (366) | 344 | 19 | 9 | 1 |
| `vista-catalogo-otra-vez` | 623 ms | 313 (305) | 310 | 20 | 6 | 1 |

- Reproduce lo de §1: la mitad es el clic (casi todo en `crecer()`) y la otra mitad la
  segunda ronda de pintado.
- «Movidos» son los widgets que cambian de sitio dentro de su padre (los hijos de un marco
  que se mueve van con él y no cuentan).
- El widget nuevo de cada cambio es el chip de la franja `[defaults]`: dice «catálogo» en
  una vista y «Catálogo» en la otra, y `HuecoChip` lo sustituye entero cuando cambia su
  texto.
- `tema.vista` y `estilos.vista` salen 0 en las tres.

## 6. Lo que se probó y no sirve

- **Apagar el repintado durante el cambio** (`WM_SETREDRAW` en el marco de la ventana y
  `RedrawWindow` al acabar): la ventana se queda sin crecer y Tk no recibe ningún
  `<Expose>` después. No se siguió.
