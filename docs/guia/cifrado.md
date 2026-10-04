[← Guías](README.md)

# Cifrar con VeraCrypt

Cifrar la unidad con VeraCrypt (Windows y Linux), abrirla y cerrarla en cualquier equipo, y el caso de Linux sin VeraCrypt.

Unas cuantas cosas que conviene saber antes de darle a **Crear y montar**.

**En Windows no hace falta tenerlo instalado.** Si el equipo no tiene VeraCrypt,
el paso 2 ofrece **Descargar VeraCrypt Portable**: el paquete oficial de IDRIX,
de la versión fijada en `common/pins.py`, que se abre sin ejecutarlo y se
comprueba antes de usarlo —su SHA-256 contra el fijado, y los CRC-32 del
paquete y de cada fichero, como hace el propio VeraCrypt—. Si lo tienes
descomprimido en una carpeta, también vale indicarla. Con el portable, cada paso
(crear, montar, desmontar) pide permiso de administrador: sin su driver
instalado, VeraCrypt se relanza elevado. Si hay uno instalado, se usa ese.

**En Linux tampoco.** Sin VeraCrypt instalado, el paso ofrece **Descargar
VeraCrypt (AppImage)**: el AppImage oficial de la misma versión fijada, para x64
y ARM64, comprobado contra su SHA-256 antes de usarlo. Es un solo ejecutable y no
instala nada, pero crear y montar siguen pidiendo la contraseña de
administrador, igual que con el instalado. Para abrirlo después ni eso hace
falta: ver [En Linux, sin VeraCrypt](#en-linux-sin-veracrypt). Con la 1.26.29
(la fijada, o una instalada igual o más nueva), en Linux el contenedor también
se crea disperso si el disco lo admite: solo ocupa lo que se guarda.

**Por qué tarda, y cómo no tardar.** Crear el contenedor no es cifrar: es
*escribirlo entero*. VeraCrypt reserva el fichero y luego lo recorre escribiendo
un sector cada 128 MiB para obligar a Windows a reservar cada tramo de verdad, y
eso obliga a rellenar de ceros todo el contenedor. En un disco interno no se
nota; en un USB son unos treinta minutos por cada 50 GiB, y por eso el mismo
contenedor que se crea en un momento dentro del ordenador parece colgarse en el
disco externo.

La salida es la casilla **Contenedor dinámico**: el fichero se marca como
*disperso* y solo ocupa lo que vayas guardando, así que crearlo es instantáneo
sea cual sea el tamaño. Necesita que la unidad esté en **NTFS** —exFAT no admite
ficheros dispersos— y por eso la casilla sale apagada, con el motivo, cuando no
se puede. A cambio pierdes la negación plausible (se ve cuánto ocupa de verdad) y
si llenas la unidad, el volumen de dentro empieza a dar errores de escritura.

Cuando no hay dispersos, el asistente **mide** la velocidad de tu unidad y te
dice cuánto va a tardar **como poco** antes de empezar. Es un mínimo porque lo
que se mide en unos segundos es la velocidad de arranque: muchas memorias USB
escriben rápido solo hasta que se llena su caché, y después bajan a la mitad o
menos. Mientras se crea, la barra enseña el **avance real** —lo que la propia
unidad dice que lleva escrito— y cuánto queda según la velocidad del último
minuto: si la memoria se frena, el tiempo sube con ella. Si el sistema no deja
leer esa cuenta, o deja de moverse, la barra vuelve a ir y venir sin cifra: mejor
sin número que con uno inventado. Y propone un tamaño de trabajo en lugar de casi
el disco entero: si luego se te queda corto, el **VeraCrypt Expander** que viaja
en el propio dispositivo lo agranda.

**En FAT32, 4095M como mucho.** Muchos pendrives de 32 GB o menos vienen en
FAT32 de fábrica, y en FAT32 un fichero no puede llegar a 4 GiB: el contenedor es
un fichero. El asistente lo dice junto al tamaño y no deja pasar de ahí. Si
necesitas más, reformatea la unidad en exFAT o NTFS antes de empezar (eso borra
lo que tenga).

**La contraseña.** Si tiene menos de 20 caracteres, el asistente te pregunta si
quieres seguir con ella, que es lo que haría el propio VeraCrypt y aquí no puede
hacer (se le lanza en silencio). No se guarda en ningún sitio: si la pierdes, el
contenedor no se recupera.

**Si el dispositivo ya iba sin cifrar.** Al reinstalar con VeraCrypt, el
contenedor se crea al lado de la instalación anterior, y esa se queda donde
estaba, con la clave del remoto en claro y tus carpetas. El asistente te lo dice
en rojo antes de crear nada, y no la borra: puede tener cambios que todavía no
están en el remoto. Bórrala tú cuando compruebes que no falta nada, y si alguien
pudo copiar el dispositivo mientras iba sin cifrar, cambia la clave del remoto.

**VeraCrypt viaja dentro.** La casilla **Dejar VeraCrypt en el dispositivo** deja
el VeraCrypt Portable oficial en una carpeta `VeraCrypt\` en la raíz de la unidad
(un *Traveler's Disk*, ≈29 MB), para poder montar el contenedor en un ordenador
que no lo tenga instalado. Lleva las **dos arquitecturas**, x64 y ARM64, con los
nombres del paquete (`VeraCrypt-x64.exe`, `VeraCrypt-arm64.exe`…), y quien abre
el contenedor escoge la del equipo. Es un **componente**, como rclone: lleva un
sello con su versión, se pone al día con el botón de la ventana, y se sustituye
entero —la carpeta nueva al lado, la de antes apartada, un renombrado—, nunca
copiando encima; si no cabe en la unidad no se toca nada. Por eso, con **max**
como tamaño, el contenedor deja 256 MiB libres fuera en vez de 50. Tres avisos
honestos:

- **Sigue haciendo falta ser administrador** en el equipo donde lo enchufes:
  montar carga un driver y eso no se puede hacer de otra forma. Esto te ahorra
  instalar VeraCrypt, no el aviso de permisos.
- **Cada arquitectura vale solo en la suya.** Montar carga un driver, y un driver
  no se emula: por eso viajan las dos. El paso 8 te dice cuáles lleva.
- prdrive **no comprueba la firma** de lo que copia como la comprueba el propio
  VeraCrypt: comprueba que el paquete es el que fija el programa (su SHA-256), y
  ese número lo apunta a mano quien mueve la versión después de comprobar la
  firma Authenticode de IDRIX y la PGP.

Sin conexión, y con VeraCrypt instalado en el equipo, se copia ese en su lugar:
una sola arquitectura, la del equipo, y sin sello. **Añadir plataformas…** lo
cambia por el portable cuando haya red. Lo mismo con un dispositivo hecho con
una versión anterior, que lleva esa copia: su VeraCrypt no se pone al día solo
—su entrada de fuera solo sabe abrir esa disposición—, y la ventana lo dice;
**Añadir plataformas…** cambia a la vez el VeraCrypt y la entrada.

En Linux y macOS no hay traveler disk. En Linux tampoco hace falta VeraCrypt: ver
[En Linux, sin VeraCrypt](#en-linux-sin-veracrypt).

**Abrirlo y cerrarlo, en cualquier equipo.** Con VeraCrypt todo prdrive está
dentro del contenedor, así que el instalador deja fuera, en la raíz de la unidad,
lo justo para llegar a él:

| | |
|---|---|
| `Abrir PRDRIVE` | abre el contenedor y la ventana de prdrive. La contraseña la pide VeraCrypt en su propia ventana: no pasa por prdrive |
| `Expulsar PRDRIVE` | cierra el contenedor para poder quitar la unidad. Si queda algo abierto, VeraCrypt pregunta si forzar |
| `abrir-prdrive.sh`, `expulsar-prdrive.sh` | lo mismo en Linux, con VeraCrypt, udisks2 o cryptsetup |
| `LEEME-PRDRIVE.txt` | cómo se hace, en diez líneas, legible sin abrir nada |

Usan el VeraCrypt instalado en el equipo si lo hay, y si no el que viaja en la
unidad, el de la arquitectura del equipo: con otra versión instalada, el que
viaja no puede cargar su driver. Un dispositivo VeraCrypt hecho con una versión
anterior se los pone con **Añadir plataformas…**, sin reinstalar.

## En Linux, sin VeraCrypt

Un contenedor como los que crea prdrive (AES, SHA-512, PIM 0, sin volumen
oculto) también lo abren **udisks2** y **cryptsetup**, que vienen en casi todas
las distribuciones. `sh abrir-prdrive.sh`, en una terminal, usa lo primero que
haya:

| | | |
|---|---|---|
| 1 | **VeraCrypt** instalado | como siempre: su ventana pide la contraseña |
| 2 | **udisks2**, si reconoce contenedores VeraCrypt | sin ser administrador. Se monta en `/media/$USER/…` o `/run/media/$USER/…` |
| 3 | **cryptsetup** | con `sudo` cada vez. Se monta en `/mnt/prdrive-<id>` |

udisks2 no reconoce un contenedor VeraCrypt hasta que se lo pides, porque su
cabecera no se distingue del ruido. Es **una vez por equipo**, como
administrador:

```bash
sudo touch /etc/udisks2/tcrypt.conf && sudo systemctl restart udisks2
```

prdrive no lo hace por su cuenta: es cambiar la configuración del sistema, y eso
lo decide quien lo administra. Sin eso, el script usa cryptsetup; y sin ninguno
de los tres, dice estas tres salidas.

- **La contraseña la piden `udisksctl` o `cryptsetup` en la terminal**, y no pasa
  por prdrive. Por eso sin VeraCrypt hace falta una terminal: un doble clic que
  no la abre no sirve, y el script lo dice.
- **`expulsar-prdrive.sh` cierra con lo mismo que abrió**, y no lo apunta en
  ningún sitio: lo deduce de lo que dice el sistema (el dispositivo *loop* que
  tiene el contenedor, y quién ha montado encima). Con cryptsetup hace falta ser
  administrador también para cerrar: en una terminal, `sudo`; desde el botón
  **Expulsar** de la ventana, el diálogo del escritorio (`pkexec`).
- **El vigilante no lo abre solo** sin VeraCrypt: no tiene terminal donde pedir
  la contraseña. Lo apunta en su diario, con la orden que lo abre; y en cuanto lo
  abres tú, lo ve montado y abre la ventana como siempre.
- **Sin probar en hardware real todavía**: está hecho contra el código fuente de
  udisks2 y cryptsetup, y lo que hagan las versiones de cada distribución, lo
  que hace el escritorio al ver el contenedor, y que lo escrito desde Linux se lea
  bien en Windows (y al revés) están por comprobar ([#51](https://github.com/Jeremaya25/prdrive/issues/51)).
- Un dispositivo hecho antes de esto sigue con sus `.sh` viejos (solo VeraCrypt)
  hasta que le pases **Añadir plataformas…**.
