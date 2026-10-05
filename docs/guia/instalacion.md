[← Guías](README.md)

# Instalación

Preparar una unidad nueva, para qué sistemas, qué hacer con una unidad que ya existe y el instalador de un solo fichero.

Necesitas un remote de rclone al que puedas escribir y, para ejecutar el
instalador desde el repositorio, Python 3.11+ con Tkinter en el equipo desde el
que instalas (el [ejecutable](#un-ejecutable-para-no-repetir-todo-esto) no lo
necesita). El dispositivo que sale de ahí no necesita nada en ningún equipo.

```bash
git clone <este-repo> prdrive
cd prdrive
python prdrive-install.py
```

Lo primero que pregunta es **dónde**: «En una unidad», que es lo de siempre y
lo que se describe aquí, o «En este equipo», que instala [el agente
residente](agente-residente.md) en el ordenador para que sincronice una carpeta
del propio equipo y atienda las unidades que se enchufan.

Para una unidad, el asistente son ocho pasos, y el orden tiene sus motivos: no se puede leer el
catálogo antes de saber con qué remoto se habla, ni elegir parejas antes de saber
dónde va el dispositivo, ni inicializarlas antes de que exista el `sync.py` que
las inicializa. Cada paso tiene su condición y **Siguiente** no se enciende hasta
cumplirla.

| # | paso | qué hace |
|---|---|---|
| 1 | **Dispositivo** | qué unidad. Si ya es un prdrive, atajo para actualizarla |
| 2 | **Cifrado** | VeraCrypt, BitLocker o ninguno |
| 3 | **Conexión** | formulario de remoto nuevo, o importar uno de tu `rclone.conf`. Más la ruta del catálogo: la del fichero (`…/remote.toml`), no la de su carpeta |
| 4 | **Comprobaciones** | consigue un rclone (lo busca, y si no lo descarga), conecta y lee el catálogo |
| 5 | **Instalación** | completa o ligera, y para qué plataformas; copia el programa a `.prdrive/`, rclone y Python de cada plataforma, los lanzadores, el `rclone.conf` y la clave |
| 6 | **Parejas** | cuáles de las del catálogo usa este dispositivo, y apunta el dispositivo en el registro de la flota |
| 7 | **Inicialización** | el `--resync` que fija la referencia de las parejas bisync |
| 8 | **Verificación** | que no falte nada de lo que hace falta para arrancar |

En el paso 1 se listan **todas** las unidades, no solo las que el sistema declara
extraíbles: muchos pendrives y casi todos los SSD por USB se declaran fijos, y
filtrar por ahí es la forma más rápida de que el tuyo no aparezca.

El paso 5 no borra nada fuera de `.prdrive/`. Si esa carpeta ya existe, se
sobrescribe el código y se conserva el resto.

## Plataformas: completa o ligera

En el paso 5 se elige **para qué equipos** va a funcionar el dispositivo: Windows
x64, Windows ARM64, Linux x64 y Linux ARM64. La de este equipo viene marcada.
Cada plataforma lleva su rclone (≈80 MB) y, en la instalación **completa**, su
propio Python (≈40–50 MB); la lista enseña lo que ocupa cada una, el total y el
hueco libre del dispositivo.

| instalación | lleva | en la raíz | necesita en cada equipo |
|---|---|---|---|
| **completa** (por defecto) | rclone + Python por plataforma | `runsync.bat`, `runsync.sh`, `README.md` | nada |
| **ligera** | solo rclone | lo mismo, más `runsync.pyw` | Python 3.11+ con Tkinter |

El Python es [python-build-standalone](https://github.com/astral-sh/python-build-standalone)
(de astral-sh), no el zip «embebible» de python.org, que no trae tkinter. Va en
`.prdrive/runtime/<plataforma>/`, podado de lo que prdrive no usa (pip, idle, los
tests, las cabeceras de C), con un sello de versión que se escribe el último: un
runtime a medias no cuenta como instalado. rclone sigue en `.prdrive/bin/<arch>/`.

Las versiones de los dos están **fijadas** en `common/pins.py` y se mueven con un
commit, no porque alguien publicara algo anoche: se instala lo que se ha probado.
Python va en 3.13 y no en 3.14 porque los 3.14 de python-build-standalone ya traen
Tk 9 en todas las plataformas, y en Windows la interfaz está hecha con Tk 8.6. El
3.13 solo es Tk 8.6 en Windows: el de Linux ya trae Tk 9.0.4 (comprobado el
02/10/2026), así que desde un runtime de Linux la ventana corre con Tk 9. Las
medidas de las pantallas (que quepan, sin recortes) se han pasado con las dos
versiones de Tk (03/10/2026); el aspecto no se ha revisado a ojo con Tk 9.

**Desmarcar una plataforma que el dispositivo ya lleva pregunta si se borra.** Si
dices que no, sus binarios se quedan donde están y simplemente no se reinstalan.

**Si una descarga falla.** Cada fichero se intenta tres veces, con esperas
crecientes, ante un corte o un tiempo de espera. Si ni así llega, **no se ha
tocado el dispositivo**: todo lo de fuera se consigue antes de copiar nada, y lo
ya descargado se queda en la caché del equipo (`%LOCALAPPDATA%\prdrive-install\`,
o el temporal en Linux) y no se vuelve a bajar. El mensaje dice qué plataforma
falta: puedes reintentar, o desmarcarla y seguir sin ella (se añade luego con
**Añadir plataformas…**). Y dice cómo ponerla **a mano**: bajar con el navegador
el zip de rclone (o el archivo de Python) y el `SHA256SUMS` de su versión, y
dejarlos, sin descomprimir y con sus nombres exactos, en la carpeta que indica.
Al reintentar se comprueban igual que una descarga, sin red. Un binario de
rclone suelto no vale para otra plataforma: rclone publica las sumas de sus
zips, no de lo que llevan dentro, así que no habría con qué comprobarlo.

Si enchufas el dispositivo en una plataforma para la que no se preparó, el
lanzador (o `sync.py`, si falta rclone) lo dice y dice la cura: volver a pasar el
instalador y pulsar **Añadir plataformas…**.

## Pasar el instalador por un dispositivo que ya existe

El dispositivo va primero justamente para esto: si la unidad elegida **ya es un
prdrive**, el paso 1 lo dice —con la versión que lleva y la que trae el
instalador— y ofrece tres caminos.

- **Actualizar el programa** son dos pantallas y se acabó. Se sustituye el
  código, se conserva todo lo demás y no se pregunta nada más: ni conexión, ni
  catálogo, ni parejas, porque al actualizar no cambia ninguna de esas cosas. Va
  **sin red**, porque el código sale del propio instalador. Si el instalador
  resulta ser más viejo que el dispositivo, se avisa y hay que confirmarlo.
- **Añadir plataformas…** abre la misma lista del paso 5 sobre el dispositivo tal
  cual está: añade (o quita) rclone y Python de otras plataformas sin tocar la
  conexión, las parejas ni el estado. Es lo que hace falta para llevarse el
  dispositivo a un Linux, o a un portátil ARM, que no estaban previstos.
- **Reinstalar desde cero** sigue el asistente completo, que es lo que hace falta
  para cambiar de remoto, recifrar el volumen o rehacer las parejas.

Con VeraCrypt el `.prdrive/` está dentro del contenedor, así que hasta montarlo
la unidad no se distingue de una vacía: ahí el atajo aparece en el paso 2, en
cuanto el contenedor está abierto.

## La primera vez

El catálogo todavía no existe. Instala un primer dispositivo con la conexión a
mano y crea las parejas desde su ventana (**Parejas → Catálogo → Añadir**), o
sube un `remote.toml` con el formato de
[`sync_config.example.toml`](../../sync_config.example.toml). A partir de ahí, cada
dispositivo nuevo hereda la conexión y las parejas del catálogo.

## Un ejecutable, para no repetir todo esto

```bash
pip install pyinstaller          # solo para compilar
python build_installer.py        # -> dist/prdrive-install.exe
```

Sale un instalador de un solo fichero que **lleva el programa dentro**. Dos
variantes, y la diferencia importa:

- **Sin perfil** (lo normal al clonar el repo): genérico, sin ningún secreto
  dentro, pregunta la conexión al abrirlo. Se puede repartir sin más.
- **Con perfil**: si en el checkout hay un `prdrive-profile.toml` con tu conexión
  y `keys/` con su clave, los **incrusta** y el ejecutable queda llave en mano.
  Ese binario lleva tu clave privada: compártelo solo en privado, y si se filtra
  revoca la clave en el servidor.

`install/secret.py` es el vehículo del perfil: se genera al compilar, está en
`.gitignore` y se borra siempre en un `finally`, también si la compilación falla.
