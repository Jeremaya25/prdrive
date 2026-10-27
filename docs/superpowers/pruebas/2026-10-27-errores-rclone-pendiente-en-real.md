# Plan: los errores de rclone en un Windows en español

Fecha: 2026-10-27 · Estado: **por hacer**.

El catálogo de errores (`common/errores.py`, #96) reconoce cuatro textos de Windows
que no escribe rclone sino el sistema (`FormatMessage`), y que salen **en el idioma
del sistema**. Los ingleses los comprueba el CI en su Windows
(`tests/test_errores.py` pide `ctypes.FormatError()` de cada código). Los españoles
se escribieron a mano y no los ha visto ningún Windows en español: hasta que esta
fila se confirme, una de esas agujas puede no casar nunca y el fallo saldría
«sin reconocer» (con lo que dijo rclone tal cual), nunca con una explicación falsa.

## Equipos

- **WE**: Windows 10 u 11 con la interfaz en español (es-ES), con un dispositivo
  prdrive y su runtime.

## Pruebas

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| R1 | WE | En el runtime del dispositivo: `python -c "import ctypes; [print(n, ctypes.FormatError(n)) for n in (5, 32, 112, 123)]"`, y luego `python tests/test_errores.py`. | Cada mensaje contiene su aguja española del catálogo: 5 «Acceso denegado», 32 «está siendo utilizado por otro proceso», 112 «No hay espacio suficiente en el disco», 123 «La sintaxis del nombre de archivo». El test pasa con las comprobaciones `FormatError(…)` en español (no «(saltado)»). | `common/errores.py` (`EN_USO`, `DISCO_LLENO`, `NOMBRE_INVALIDO`), `tests/test_errores.py` |
| R2 | WE | Abrir con Word (o cualquier programa que bloquee el fichero) un documento de una pareja que lo vaya a subir cambiado, y lanzar la pasada con el fichero abierto. Abrir «Reparación». | La fila «la última pasada falló» dice «Un fichero está en uso» con su explicación, y ofrece «Reintentar la pasada» y «Ver el log» debajo del texto. `python sync.py --doctor` imprime el mismo texto. | `common/revision.py`, `ui/repair.py` (`arreglos_fallo`), `ui/tk_repair.py` |

## Qué hacer con lo que salga

- Una aguja que no casa: se corrige en `common/errores.py` con el texto que dé
  `FormatError()` y se apunta aquí el mensaje entero.
- Una fila que se confirma: se marca aquí, como las filas de
  `2026-09-25-equipo-pendiente-en-real.md`, y no se borra.
