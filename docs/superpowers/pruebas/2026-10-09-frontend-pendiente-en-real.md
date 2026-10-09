# Plan: el frontend rápido en máquinas de verdad

Fecha: 2026-10-09 · Estado: **por hacer**.

Los tests sustituyen la pantalla y el disco: no ven cómo se pinta la interfaz en
un monitor de verdad ni cuánto tardan sus ventanas en un dispositivo de verdad.
Esta lista es lo que queda de la etapa 4 (`docs/superpowers/specs/2026-10-08-frontend-rapido-design.md`,
«Limpieza»). Lo que la nube puede ver (los `.pyc` entre sistemas de ficheros, F21)
va aparte, en `maquina-real.yml`.

## Equipos

- **W**: Windows 11 x64, con un dispositivo prdrive de la etapa 4 y el agente.
- **W10**: Windows 10 22H2, con el mismo dispositivo.
- **L**: un escritorio Linux, con systemd y udisks2.

## Pruebas

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| E1 | W, L | Arranque en frío desde una memoria USB (≈80 MB, ≈190 ficheros) con la caché del sistema fría: enchufar el dispositivo, abrir la ventana principal y luego «Parejas», cronometrando de clic a ventana. Repetir con `PRDRIVE_PERF=1` y leer `logs/perf.log` (momentos `start-main` y `open-parejas`; `ui.md`, «Timing on the device»). | Cada ventana aparece entera, sin un hueco vacío ni un recuadro a medio rellenar. Los tiempos se apuntan tal cual: la etapa 4 mide, no fija una cifra. Si el cronómetro y `perf.log` no coinciden, se dice cuál y cuánto. | `ui/__init__.py` (`perf_*`), `ui/tk.py` (`main_window`, `mostrar`), `ui/tk_pairs.py` |
| E2 | W, W10 | En pantalla real, con tema claro y oscuro y con escala de 100 %, 150 % y 200 %, mirar cada ventana de las etapas 1b a 3: la principal, «Parejas», «Ajustes» con sus paneles, «Dispositivos», el editor de opciones de una pareja, el asistente (desde el `.exe` del instalador que compila el workflow `Instalador`) y la pregunta «¿Atender esta unidad?» del agente. | Como en el diseño: los colores del tema (papel, tinta, acento), los iconos nítidos a cada escala, el texto sin cortar y ningún control montado sobre otro. | `ui/theme.py`, `ui/icons.py`, `ui/tk_principal.py`, `ui/tk_pairs.py`, `ui/tk_doctor.py`, `ui/tk_fleet.py`, `ui/tk_install.py`, `ui/tk_agente.py` |
| E3 · nube: ok | F21 · nube | Nada que hacer aquí: la fila se corre sola (`.github/workflows/maquina-real.yml`, trabajos `pyc-linux` y `pyc-windows`). Su resultado va a `docs/superpowers/pruebas/maquina-real-resultados.md`. | Un `.pyc` de hash comprobado se reutiliza al pasar a FAT32 y a exFAT, aunque sus fuentes hayan cambiado de hora; el de hora se reconstruye. La nube ve el sistema de ficheros, no el dispositivo: no sustituye a E1 ni a E2. | `install/deploy.py` (`precompilar`), `tests/maquina/f21_pyc_entre_sistemas_linux.py`, `tests/maquina/f21_pyc_entre_sistemas_windows.py` |

## Qué hacer con lo que salga

- Una diferencia entre lo que se ve y lo que se espera: una incidencia en GitHub, con
  la captura, el equipo (W, W10 o L), el tema y la escala.
- Un tiempo: al fichero de resultados de la etapa 4, con el equipo, la fecha y si se
  midió con cronómetro o con `perf.log`.
- Una fila que se confirma en un equipo de verdad: se marca aquí, como las filas de
  `2026-09-25-equipo-pendiente-en-real.md`, y no se borra.
