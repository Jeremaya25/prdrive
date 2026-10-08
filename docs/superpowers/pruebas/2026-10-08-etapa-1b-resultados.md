# Etapa 1b del frontend rápido: resultados (08/10/2026)

Lo que midió la comprobación de tiempos (`rendimiento.yml`) al acabar la etapa 1b de
`docs/superpowers/specs/2026-10-08-frontend-rapido-design.md`: el motor de dibujo. La rama frente
a `main` (la 0.7.1), en la misma máquina, con las vueltas intercaladas; Python fijado del
dispositivo (3.14.8, Tk 9.0.4), 7 vueltas, mediana en ms.

- El SVG solo (`7d170b6`): [Rendimiento 37850628131](https://github.com/Jeremaya25/prdrive/actions/runs/37850628131).
- El SVG y la superficie por bits (`b410738`): [Rendimiento 37852859630](https://github.com/Jeremaya25/prdrive/actions/runs/37852859630).
  Esta máquina de Windows salió más rápida que las anteriores (suelo de 121 ms frente a 143):
  cuenta la diferencia con la base en el mismo trabajo, no la cifra suelta.

La etapa 1b son dos cosas:

- **Los iconos y las piezas de los controles los dibuja Tk** (SVG con nanosvg, el Tk 9 del
  dispositivo), con el pintor de Python de respaldo para Tk 8.6 y para lo que no se sabe
  describir en SVG. Con el SVG apagado (`PRDRIVE_SIN_SVG=1`) las pantallas salen iguales píxel a
  píxel que en la 0.7.1; con él, solo cambia el suavizado de los bordes.
- **La superficie de cada control es su estado** (los bits `user1`…`user3` de ttk) y no un
  estilo por superficie: de 854 estilos a 448, y ninguno se crea con una ventana abierta.

## Windows x64, 100 %, 5 parejas (`b410738`)

| Momento | 0.7.1 | Etapa 1b | Dif. | Meta |
|---|---|---|---|---|
| Ventana principal, desde que se lanza | 748 | 416 | −44 % | 350 |
|   `theme.apply()` | 348 | 64 | −82 % | |
| Pregunta del agente, desde que se lanza | 654 | 235 | −64 % | 300, **cumple** |
| Asistente, desde que se lanza | 715 | 389 | −46 % | 300 |
| «Parejas», desde que se lanza | 1242 | 867 | −30 % | 500 |
| Abrir «Parejas» | 470 | 453 | −4 % | 150 |
| Llega el catálogo a «Parejas» | 676 | 671 | = | 30 |
| Abrir «Ajustes» | 131 | 137 | = | 150, **cumple** |
| Apartado «Reparación» | 119 | 107 | −10 % | 60 |
| Apartado «Nombre e icono» | 158 | 155 | = | 60 |
| Apartado «Configuración» | 89 | 99 | ruido | 60 |
| 10 000 líneas en la ventana de la pasada | 11822 | 4 | −100 % | 200, cumple |

Al 150 %: la principal 890 → 484 (+17 % sobre el 100 %, dentro del +20 % de la meta).
Abrir «Parejas», la llegada del catálogo y los apartados son de la etapa 2 (la lista de
«Parejas» por sí sola es lo que pesa: `2026-10-09-etapa-2-medidas.md`).

## Linux x64 (xvfb), 100 %, 5 parejas (`b410738`)

| Momento | 0.7.1 | Etapa 1b |
|---|---|---|
| Ventana principal, desde que se lanza | 668 | 297 |
| Pregunta del agente | 658 | 222 |
| Asistente | 627 | 292 |
| Abrir «Parejas» | 212 | 143 |
| Abrir «Ajustes» | 94 | 56 |

## Cuentas deterministas

| Cuenta | 0.7.1 | Etapa 1b |
|---|---|---|
| Estilos creados después del primer widget (principal, «Parejas», «Ajustes», apartado) | 2, 3, 2, 7 | **0, 0, 0, 0** |
| Pasadas de `<<ThemeChanged>>` al abrir «Parejas»/«Ajustes»/un apartado | 0 | 0 |
| Módulos de la pregunta del agente (Windows / Linux) | 241 / 242 | 158 / 157 |
| Imágenes que se rasterizan en Python con el Tk 9 (`theme.apply()` y una pantalla de muestra) | todas | 0 |

## El alfa binario de las piezas (§1c)

Medido y aplazado: [run 37848307713](https://github.com/Jeremaya25/prdrive/actions/runs/37848307713),
el mismo commit con las piezas suavizadas y con su alfa cortado. Gana al pintar mucho de golpe
(abrir «Parejas» −48 ms, la llegada del catálogo −57) y casi nada en lo demás; lo que gana está
en los repintados enteros que quita la etapa 2. La especificación lo apunta en §1c.

## Pruebas

- `tests/run_all.py` en verde en los cuatro trabajos de `tests.yml` (Linux y Windows, Tk 8.6 y
  Tk 9) sobre `9ad1563`, y en la fila F20 de máquina real en Windows (18/18: el Tk 9 de Windows
  lee SVG y no rasteriza nada en Python).
- En local, además, la pata de Tk 9 con `PRDRIVE_SIN_SVG=1` (todo por el pintor de Python).
- La CI de Windows encontró un fallo que ya estaba en una prueba (`test_llavero_combinar`
  dependía de en qué segundo caían dos combinaciones): arreglado en `893ad91`.

## Revisión

Una revisión de toda la etapa (sin bloqueos ni fallos serios) comparó capturas de antes y de
después en todas las pantallas que se miden, a 100/150/200 % y en los dos temas. Arreglado tras
ella:

- un chip sobre un botón ya asentado veía el papel y no la superficie del botón (no pasaba en
  ninguna pantalla todavía);
- la prueba del SVG podía aprobar comparando el pintor de Python consigo mismo: ahora exige que
  su lado SVG haya salido del SVG;
- `theme.reasentar()`, para que lo de dentro siga a un padre que cambia de superficie (la fila
  elegida de «Parejas», la barra lateral de «Ajustes»: dos fallos que ya tenía la 0.7.1 y que
  arregla la etapa 2).

Quedan apuntados para más adelante: probar todas las pantallas (no solo «Parejas» y el primer
apartado de «Ajustes») sin `<<ThemeChanged>>` ni superficies sin bits, y que el recorte de la
pastilla de `marca_estado()` en SVG es opaco (hoy siempre cae sobre el papel).
