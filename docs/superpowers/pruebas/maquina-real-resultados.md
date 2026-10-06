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
| F9 | L | 2026-10-06 | [run](https://github.com/Jeremaya25/prdrive/actions/runs/37483534994) | ok 39/39 | inotify en vfat (FAT32), exFAT (con linux-modules-extra) y ext4 sobre loop: crear, guardar, renombrar, carpeta nueva y movida, 5 000 ficheros |
| F10 | L | 2026-10-06 | [run](https://github.com/Jeremaya25/prdrive/actions/runs/37483534994) | ok 8/8 | umount de vfat y exFAT con vigilancias puestas: rc 0 y la pareja se pierde |
| F11 | L | 2026-10-06 | [run](https://github.com/Jeremaya25/prdrive/actions/runs/37483534994) | ok 4/4 | NFS de la propia máquina: mountinfo dice nfs4, sin avisos y con motivo, el recorrido la ve |
| F12 | L | 2026-10-06 | [run](https://github.com/Jeremaya25/prdrive/actions/runs/37483534994) | ok 4/4 | max_user_watches = 20 000: 10 100 carpetas no caben en la mitad, 3 000 sí y otro programa pone 9 000 más |
