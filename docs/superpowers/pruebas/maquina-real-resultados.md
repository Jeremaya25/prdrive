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
| F13 | W | 2026-10-06 | [run](https://github.com/Jeremaya25/prdrive/actions/runs/37483534994) | ok 4/4 | carpeta compartida por SMB de la propia máquina: GetDriveTypeW dice DRIVE_REMOTE, sin avisos y con motivo, el recorrido la ve |
| F14 | W | 2026-10-06 | [run](https://github.com/Jeremaya25/prdrive/actions/runs/37483534994) | ok 30/30 | ReadDirectoryChangesW con la ventana de verdad de la bandeja, en discos VHD NTFS, exFAT y FAT32: crear, guardar, renombrar, carpeta renombrada y lo de dentro, 5 000 ficheros; quieta, nada |
| F15 | W | 2026-10-06 | [run](https://github.com/Jeremaya25/prdrive/actions/runs/37483534994) | saltada | diskpart no creó el disco en la letra R (rc 2147755356), probablemente aún reservada tras F14 |
| F16 | W | 2026-10-06 | [run](https://github.com/Jeremaya25/prdrive/actions/runs/37483534994) | saltada | lo mismo |
| F18 | W | 2026-10-06 | [run](https://github.com/Jeremaya25/prdrive/actions/runs/37483534994) | ok 3/3 | VeraCrypt 1.26.29: su volumen es \\Device\\VeraCryptVolumeP y no se vigila con avisos. Pregunta 2: el aviso de extracción de un handle de su volumen NO se puede registrar (error 1066), y con un handle abierto dentro desmontar sin forzar NO funciona; no llega ningún aviso. Los volúmenes de VeraCrypt se recorren siempre |
| F19 | W | 2026-10-06 | [run](https://github.com/Jeremaya25/prdrive/actions/runs/37483534994) | ok 2/2 | tests/test_avisos_carpeta.py en Windows con su parte de verdad (45 comprobaciones) |
| F16 | W | 2026-10-06 | [run](https://github.com/Jeremaya25/prdrive/actions/runs/37484439718) | ok 3/3 | «Expulsar» del agente (expulsar.expulsar) en un VHD: con la carpeta vigilada abierta falla («Algo está usando la unidad»); tras dejar_raiz() sale bien. No llega ningún aviso de bloqueo a la ventana |
| F15 | W | 2026-10-06 | [run](https://github.com/Jeremaya25/prdrive/actions/runs/37484439718) | fallo 4/8 | la ventana no recibió ningún WM_DEVICECHANGE (ni la llegada del disco): la máquina no entrega avisos de dispositivo a las ventanas; la prueba lo comprueba ahora antes y se salta |
| F15 | W | 2026-10-06 | [run](https://github.com/Jeremaya25/prdrive/actions/runs/37485180580) | saltada | la máquina de GitHub no tiene escritorio interactivo y no entrega WM_DEVICECHANGE a las ventanas: el «Quitar hardware de forma segura» queda para un equipo de verdad |
