# Etapa 1a del frontend rápido: resultados (08/10/2026)

Lo que midió la comprobación de tiempos (`tests/rendimiento/`, workflow `rendimiento.yml`)
al acabar la etapa 1a de `docs/superpowers/specs/2026-10-08-frontend-rapido-design.md`:
la rama (`3e40893`) frente a `main` (la 0.7.1), en la misma máquina y con las vueltas
intercaladas. Python fijado del dispositivo (3.14.8, Tk 9.0.4), 7 vueltas, mediana en ms.

- [Rendimiento 37843538665](https://github.com/Jeremaya25/prdrive/actions/runs/37843538665)
  (`3e40893`); la repetición sobre `95c683f`
  ([37845359345](https://github.com/Jeremaya25/prdrive/actions/runs/37845359345)) da las
  mismas cuentas y tiempos dentro del ruido.
- Suelo (una ventana vacía de Tk): 143 ms en Windows x64.

La etapa 1a era la de «ni un píxel cambia»: el tema sin trabajo repetido, la tabla de
letras, los imports perezosos, los `.pyc` precompilados en el dispositivo, el servicio que
ve la parada en 1 s, la ventana de la pasada con un tope de líneas y la barra de espera a
menos pasos. Abrir «Parejas», la llegada del catálogo y los apartados de «Ajustes» son de
la etapa 2 y aquí no se mueven, como se esperaba.

## Windows x64, 100 %, 5 parejas

| Momento | 0.7.1 | Etapa 1a | Dif. | Meta |
|---|---|---|---|---|
| Ventana principal, desde que se lanza | 1346 | 911 | −32 % | 350 |
|   `theme.apply()` | 681 | 286 | −58 % | |
| Pregunta del agente, desde que se lanza | 1126 | 591 | −47 % | 300 |
| Asistente, desde que se lanza | 1224 | 812 | −34 % | 300 |
| «Parejas», desde que se lanza | 2201 | 1765 | −20 % | 500 |
| Abrir «Parejas» | 842 | 861 | = | 150 |
| Llega el catálogo a «Parejas» | 1210 | 1212 | = | 30 |
| Abrir «Ajustes» | 232 | 250 | = | 150 |
| Apartado «Reparación» | 213 | 211 | = | 60 |
| Apartado «Nombre e icono» | 286 | 281 | = | 60 |
| Apartado «Actualizaciones» | 31 | 29 | = | 60 |
| Apartado «Configuración» | 165 | 162 | = | 60 |
| 10 000 líneas en la ventana de la pasada | 20207 | 6 | −100 % | 200 |

Con 50 parejas: la principal 1953 → 1500, abrir «Parejas» 2126 → 2127 y la llegada del
catálogo 6234 → 6297 (etapa 2). Al 150 %: la principal 1649 → 1177.

## Linux x64 (xvfb), 100 %, 5 parejas

| Momento | 0.7.1 | Etapa 1a | Dif. |
|---|---|---|---|
| Ventana principal, desde que se lanza | 680 | 475 | −30 % |
|   `theme.apply()` | 382 | 194 | −49 % |
| Pregunta del agente | 660 | 382 | −42 % |
| Asistente | 638 | 444 | −31 % |
| Abrir «Parejas» | 216 | 203 | −6 % |
| Llega el catálogo | 147 | 140 | −5 % |
| Abrir «Ajustes» | 97 | 91 | −6 % |
| 10 000 líneas en la ventana de la pasada | 2774 | 5 | −100 % |

Linux sirve de segunda opinión: los objetivos son los de Windows.

## Cuentas deterministas

Iguales en las dos plataformas salvo los módulos. Los techos de `presupuesto.toml` se
han puesto con estas cifras de CI (fuera de CI, los módulos salen distintos).

| Cuenta | 0.7.1 | Etapa 1a |
|---|---|---|
| Módulos importados al abrir la principal (Windows / Linux) | 252 / 254 | 223 / 224 |
| … la pregunta del agente | 241 / 242 | 160 / 159 |
| … el asistente | 237 / 237 | 235 / 234 |
| Widgets de la principal, de «Parejas», de «Ajustes», del agente | 51, 152, 39, 16 | igual |
| Estilos creados tras el primer widget (principal, «Parejas», «Ajustes», apartado) | 2, 3, 2, 7 | igual |
| Pasadas de `<<ThemeChanged>>` al arrancar / al abrir / al cambiar de apartado | 1 / 0 / 0 | igual |

Los widgets y los estilos son de las etapas 1b y 2.

## Tests

`tests/run_all.py` en verde en los cuatro trabajos de `tests.yml` (Linux y Windows, con
Tk 8.6 y con el Python fijado y su Tk 9) sobre `95c683f`
([Tests 37845359340](https://github.com/Jeremaya25/prdrive/actions/runs/37845359340)).
El primer intento (`3e40893`) falló solo en Windows por `test_precompilar`, que calculaba
el hash esperado sobre el texto y no sobre los bytes (`\r\n`); arreglado en `95c683f`.

## Revisión

Una revisión de toda la rama (sin bloqueos) encontró un fallo serio y varios menores,
arreglados antes de empezar la etapa 1b:

- «Parejas» conservaba lo escrito al releer el catálogo aunque otro dispositivo hubiera
  cambiado esa pareja, y guardarlo deshacía su cambio sin decirlo. Ahora lo escrito solo
  se conserva si la pareja sigue igual; si no, el editor se recarga y lo dice.
- En Windows, borrar `ui.lock.json`/`daemon.lock.json` mientras otro proceso los lee
  falla (WinError 32), y el sondeo más rápido lo hacía más probable: ahora se borran con
  `_borrar()`, que reintenta. Y la ventana relanzada tras actualizar, si su padre muere
  sin soltar el registro, ya lo retira y lo toma en vez de abrirse sin él.
- Los `.pyc` se escriben lo último en el asistente, para no quitarle sitio a los
  lanzadores ni al fichero de control en una unidad casi llena.
- La barra de espera, de 48 ms a 32 ms por paso: a 21 pasos por segundo se veía a saltos.
- Dos tests que pasaban por la razón equivocada, el `results` que el servicio importaba
  tarde y las vueltas de `rendimiento.yml` metidas en la orden en vez de por el entorno.
