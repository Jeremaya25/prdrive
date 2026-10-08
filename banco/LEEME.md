# Banco de la interfaz (temporal)

Mide cuánto tardan en abrirse las ventanas de prdrive con el Python fijado del
dispositivo (python-build-standalone 3.14.8, Tk 9.0.4), en Windows x64, Windows
ARM64 y Linux, para elegir el frontend que sustituye al de la 0.7.x:

- `tk-071`: la 0.7.1 tal cual, como referencia.
- `tk-065`: la 0.6.5, la última de antes del rediseño.
- **Enfoque A**, el mismo Tk sin pintar en Python:
  - `tk-071-pngcache`: la 0.7.1 sin el pintado de iconos en Python;
  - `tk-flat`: una pantalla ttk ligera;
  - `tk-widgets`: el coste de cada widget.
- **Enfoque B**, Qt: `qt-pyside6` (PySide6 Widgets, podado).

Lo corre `.github/workflows/banco-ui.yml` al subir un cambio de `banco/` a una
rama que no es `main`. Al final del registro de cada trabajo van las líneas
`RESULTADO banco …` y `CAPTURA …`. Las capturas, que prueban que la máquina
pinta de verdad, van en el artefacto `banco-<plataforma>`.

En local: `python banco/preparar.py --plataforma linux-x64 --trabajo DIR` y luego
`BANCO_CONF=DIR/banco.json xvfb-run -a python banco/correr.py --salida DIR/salida`.

**Es temporal.** Se borra, junto con el workflow, en cuanto los resultados estén
apuntados en la especificación del nuevo frontend
(`docs/superpowers/specs/`). No es parte del programa ni de `tests/`.
