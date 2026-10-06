# Resultados de las pruebas en máquina real (GitHub Actions)

Lo que corre `.github/workflows/maquina-real.yml` (`tests/maquina/`, `python
tests/maquina/correr.py --lista`) en máquinas de usar y tirar de GitHub, con
permisos de administrador: discos virtuales (VHD en Windows, loop en Linux) con
su sistema de ficheros de verdad, VeraCrypt instalado, carpetas de red por la
propia máquina. Es la frontera con el sistema; la lógica la prueban los tests
de siempre con sustitutos. Un disco virtual no es un pendrive: una fila con
«nube: ok» sigue en la lista de pruebas en real hasta verla con uno de verdad.

Una línea por fila y ejecución, la más reciente al final. Resultado: `ok N/N`,
`fallo N/M` (la primera que falla), `saltada` (no se pudo hacer en la máquina).

| Fila | Sistema | Fecha | Ejecución | Resultado | Notas |
|---|---|---|---|---|---|
