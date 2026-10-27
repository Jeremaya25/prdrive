#!/usr/bin/env python3
"""El agente residente de prdrive: un proceso por usuario que atiende las unidades.

Es el sucesor de `penwatch.py` en los equipos donde se instala: vive en el
equipo, FUERA de toda raíz (`common/equipo.py` dice dónde), arranca al iniciar
sesión con su propio Python y hace de servicio de cada unidad prdrive que se
enchufa y que tiene en su lista. Sin Tk: la ventana de una unidad y la pregunta
por una unidad nueva son procesos hijos.

Se usa como `python agente.py ORDEN`:
- `run`: el bucle (lo lanza el registro al iniciar sesión).
- `status`: qué atiende y cómo.
- `atender ID`: atiende la unidad conectada a la que se dijo «Ahora no».
- `modo ID MODO`: `ui`, `daemon`, `sync` o `nada`.
- `pasada ID [PAREJA…]`: «Sincronizar ahora», sin moderación.
- `pausa` y `sigue`: dejar de lanzar pasadas, y volver.
- `parar`: que termine (lo usa el instalador).
- `abrir [ID]`: la ventana de la raíz de este equipo (o de esa).
- `desbloquear [ID]` y `bloquear [ID]`: abrir y cerrar el contenedor de la raíz
  cifrada.
- `ajuste CLAVE VALOR`: `pedir_al_iniciar sí|no`, `estirar_intervalo sí|no`,
  `avisos_veracrypt sí|no` (al arrancar) o `espera_unidad_nueva SEG`.
- `actualizar`: baja la versión nueva y la pone (lo que hace la bandeja).
- `actualizar ID`: pone en esa raíz el código de la versión del agente.
- `expulsar ID`: suelta esa unidad extraíble para poder quitarla (el «Expulsar» de
  la bandeja).
- `atajos`: abre la ventana que graba los atajos de teclado (lo que hace la
  bandeja con «Atajos de teclado…»).
- `atajo ACCION`: hace lo de ese atajo (`sincronizar`, `carpeta`, `pausar`,
  `ventana`) como si se hubiera pulsado: sirve para dárselo a un atajo del
  propio escritorio.
- `desinstalar [--si]`: quita el agente de este equipo sin dejar rastro, tras
  enseñar qué hará (el «Desinstalar» de «Aplicaciones instaladas» de Windows;
  `common/presencia.py`).

Las órdenes que no son `run` ni `desinstalar` no hacen nada por sí mismas:
dejan la petición en el buzón del agente (`equipo.pedir()`), que es quien
escribe su configuración.

Cómo trabaja, vuelta a vuelta (`Agente.vuelta()`):
- **Detecta** las unidades con el mismo recorrido de siempre,
  `penwatch.candidate_roots()`, pero no cada 5 s: en Linux se despierta cuando
  cambia `/proc/self/mountinfo` (`POLLPRI`) y de ahí una racha de sondeos,
  porque un volumen cifrado se lee bastante después de montarse. En Windows,
  con el `WM_DEVICECHANGE` que recibe la ventana de la bandeja; sin bandeja,
  sondea como penwatch. Una unidad cuenta cuando se ha visto dos veces
  seguidas.
- **Pregunta** por las unidades que no conoce («Una unidad nueva» del diseño):
  un aviso y una ventanita con cuenta atrás; sin respuesta es «Ahora no», solo
  para esta conexión. Antes del sí no se ejecuta NADA de la unidad: solo se
  leen su id y su nombre.
- **Hace de su servicio** con los ficheros que ya existen en su `state/`, así
  que funciona con unidades de código viejo: escribe `daemon.lock.json`,
  obedece `daemon.stop` (acaba la pareja en curso y suelta), se queda en pausa
  mientras haya una ventana de runsync abierta en este equipo y se aparta si
  otro servicio vivo tiene el lock. Un servicio por raíz: el que tenga el lock.
- **Planifica** con `common/planificador.py`, que es puro: una sola pasada a la
  vez en todo el equipo, espera creciente tras un fallo, batería, red de uso
  medido, remotos sin conexión, «Sincronizar ahora». Un remoto sin conexión se
  sondea cuando el sistema dice que vuelve a haber red (`common/red.py`), una
  vez por ráfaga de avisos, y si no, cada 5 min (cada 30 si hay avisos).
- **Mira los cambios locales** de las parejas con `watch = true`: en Linux
  con los avisos del sistema (`common/avisos_carpeta.py`, inotify), que en
  reposo no cuestan nada; donde no los hay (Windows, una carpeta de red) con
  una foto barata de su carpeta (`common/huella.py`, en un hilo: un pendrive
  tarda segundos) cada 10 s mientras se mueve y cada 2 min si está quieta. Si
  cambia y se calma, la pasada de esa pareja se adelanta a su intervalo. La
  modera todo lo demás (pausa, batería, red de uso medido, la pausa de la
  ventana de la raíz, su ventana abierta) y lo que escribe la propia pasada no
  la dispara otra vez. No ve los cambios del remoto: esos esperan al
  intervalo.
- **Atiende el llavero** de una raíz con `[keychain]` como una pareja
  vigilada, se elija lo que se elija. Mientras su KeePassXC está abierto, lo de
  otro dispositivo se trae cada 5 min (también en modo `sync`), y al abrirlo y
  al cerrarlo hay una pasada enseguida.
- **Ejecuta** cada pasada como el `sync.py` de esa raíz, hijo, con el Python
  del agente y el directorio de trabajo fuera de la raíz: cada raíz ejecuta su
  propio código, un rclone colgado no tumba al agente y entre pasadas no queda
  nada abierto dentro de ninguna unidad, así que se puede expulsar. La
  excepción es Windows con bandeja: la carpeta de cada pareja vigilada queda
  abierta para oír sus cambios, y se cierra en cuanto el sistema pide la
  unidad (`common/avisos_carpeta.py`) y antes de «Expulsar» y «Bloquear».

La raíz de ESTE equipo (una carpeta del ordenador con `.prdrive/` dentro, que
pone el asistente «En este equipo») es una raíz más de la lista, con su `ruta`:
se busca ahí en vez de recorrer volúmenes y todo lo demás es igual. Si falta
(se ha movido o renombrado la carpeta) se avisa una vez y no se lanza nada: una
línea base sin su carpeta local es justo lo que `_bisync_preflight()` frena.

La raíz del equipo puede vivir en un contenedor VeraCrypt (fase 3). Entonces el
agente es quien lo abre y quien lo cierra, con el VeraCrypt INSTALADO y sin que
la contraseña pase nunca por él:
- **Desbloquear** lanza VeraCrypt con `/letter` fija (Windows) o el punto de
  montaje fijo (Linux) y sin `/password`: la pide su ventana. Abierta no es que
  VeraCrypt salga con 0, sino VER el id en la letra con el `.hc` retenido. Una
  letra con el id al lado de un `.hc` libre es el fantasma de las unidades
  (H-10): no se atiende y se dice «Bloquear y volver a desbloquear». Con la
  letra de otro, o un punto de montaje con cosas, no se lanza nada: se dice.
- **Al iniciar sesión**, con `pedir_al_iniciar`, se pide UNA vez; si se
  cancela, hasta que se pida «Desbloquear».
- **Bloquear** deja de encolar la raíz, espera a la pareja en curso y a que se
  cierre su ventana, suelta el lock y lanza el desmontaje SIN `/silent`: si un
  programa tiene algo abierto dentro, VeraCrypt pregunta si forzar, y eso lo
  decide la persona. Bloqueada es el `.hc` libre, no la letra ida.
- **Cerrada, simplemente no está**: no es un fallo, ni un aviso, ni una espera
  más larga. Una raíz cerrada no tiene carpeta ni línea base.

Avisa con los avisos del sistema (`common/avisos.py`), no con Tk, y solo cuando
una pareja EMPIEZA a fallar. Sin avisos, queda en su diario.

Tiene un icono en la bandeja: `ui/bandeja.py` decide qué enseña a partir de
`resumen()` y lo dibuja en su propio hilo `ui/bandeja_windows.py` en Windows
(fase 4) o `ui/bandeja_linux.py` en Linux (fase 6, StatusNotifierItem). Lo que
se elige en su menú llega como las peticiones del buzón (`Agente.pedir()`), por
el mismo camino. Donde el escritorio no tiene bandeja (GNOME sin la extensión
AppIndicator), hace sus veces el acceso «prdrive» del menú de aplicaciones:
`agente.py abrir` arranca el agente si no está, abre la ventana de la raíz o,
sin raíz, dice con un aviso cómo va.

La ventana de una raíz le habla por dos buzones (fase 5): lo del equipo por
`agente.pide` y lo de esa raíz («Pausar» (`pausar_raiz`), «Reanudar»
(`reanudar`), «Bloquear») por el `state/servicio.pide` de la propia raíz, que
solo se lee en las raíces de la lista. Una raíz pausada desde su ventana se
queda así en `agente.json` (`Unidad.pausada`) hasta «Reanudar», aunque el
agente se reinicie; la pausa de todo (`pausa`, la bandeja) no se guarda.

Los **atajos de teclado globales** (`ui/atajos.py`) los pone el agente con el
mecanismo del sistema: `RegisterHotKey` en el hilo de la bandeja en Windows,
`XGrabKey` en X11 y el portal GlobalShortcuts en Wayland (`ui/atajos_linux.py`).
Un atajo pulsado entra como una petición más (`atajo`), por el mismo camino
que el menú de la bandeja, y se convierte en las peticiones de siempre sobre la
última unidad usada. De fábrica no hay ninguno, y sin ninguno no se conecta a
nada para ponerlos.

Cuando hay una versión nueva lo dice una vez; «Actualizar» (`agente.py
actualizar`) baja el código de la release y ejecuta SU instalador, que pone el
agente nuevo al lado de este, lo para y arranca el nuevo.

Una raíz de la lista con un programa anterior al del agente se ofrece a poner
al día desde su desplegable («Actualizar a la vX», `agente.py actualizar ID`):
un hijo suelto baja el código de la versión DEL AGENTE y ejecuta su
`prdrive-install.py --update` sobre esa raíz, como hace su ventana. Mientras,
no se sirve. La huella que deja se apunta como aceptada solo si la de antes lo
era: el agente ha puesto ese código, pero no responde de lo que hubiera al
lado.

Depende de `penwatch.py` para detectar, leer los registros de runsync y abrir
VeraCrypt: el agente importa de penwatch, nunca al revés, y penwatch sigue sin
importar nada del proyecto.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, NamedTuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import penwatch  # noqa: E402
from common import (APP_NAME, autorun, avisos, avisos_buzon, avisos_carpeta, bitlocker,  # noqa: E402
                    catalog, cifrada, components, consumo, equipo, explorador, expulsar, keepassxc,
                    llavero, model, moderacion, nombres, parte, presencia, prioridad, store,
                    update, vestibulo)
from common import huella as huellas  # noqa: E402  (`huella()` es la del código de una raíz)
from common import planificador as pl  # noqa: E402
from ui import atajos, bandeja, prefs, volumen  # noqa: E402

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

IS_WIN = os.name == "nt"
ABRE_LLAVERO = IS_WIN or sys.platform.startswith("linux")
"""Si «Abrir llavero» sale en la bandeja y el aviso de conflicto ofrece combinar."""
HOST = equipo.HOST
APP_SUBDIR = penwatch.APP_SUBDIR

TICK = 2.0
"""Segundos entre las miradas a lo barato: stop, ventana, hijos."""
RECORRIDO_WINDOWS = penwatch.POLL_SECONDS
"""Segundos entre recorridos en Windows sin bandeja, como penwatch.

Sin bandeja no llega `WM_DEVICECHANGE`. Con ella, también mientras haya a la
vista una unidad bloqueada con BitLocker (`Agente.cada_recorrido()`).
"""
RECORRIDO_RESPALDO = 120.0
"""Segundos entre recorridos aunque mountinfo o `WM_DEVICECHANGE` no digan nada.

Es el respaldo: los montajes los dice el sistema, y en Windows además una letra
que aparece o se va se ve en cada vuelta (`letras_de_unidad()`). Eran 30 s; en
un equipo sin unidades el recorrido era la mitad de lo que gastaba el agente.
"""
LOTE = 8
"""Cuántas parejas de una raíz se pasan, como mucho, en un mismo `sync.py`."""
MARGEN_LOTE = 60.0
"""Segundos que se le puede adelantar la pasada a una pareja para que vaya en el `sync.py` de otra."""
REPOSO = 30.0
"""Segundos, como mucho, entre dos vueltas cuando no hay nada que mirar de cerca (`cuanto_esperar()`)."""
MIRAR_CONFIG = 20.0
"""Segundos entre dos miradas a la fecha del `sync_config.toml` de una raíz atendida."""
RELEER_REGISTROS = 20.0
"""Segundos tras los que un registro del `state/` de una raíz se relee aunque su fecha no haya cambiado."""
RAFAGA = 60.0
"""Segundos tras un cambio de montajes en que se recorre en cada vuelta."""
ESTABLE = penwatch.STABLE_CHECKS
"""Sondeos seguidos que hacen falta para que una unidad cuente."""
GRACIA = 15.0
"""Segundos tras ver la ventana o un stop, antes de volver."""
MIRAR_ENTORNO = 60.0
"""Segundos entre las lecturas de batería y red."""
MIRAR_RED_MEDIDA = 1800.0
"""Segundos entre las preguntas por la red de uso medido cuando el sistema avisa de sus cambios.

En Windows el aviso de conectividad que oye `common/red.py`
(`NotifyNetworkConnectivityHintChange`) llega también cuando cambia el coste de
la conexión, así que entre avisos basta con esta pregunta de respaldo: la
llamada COM que lo dice despierta a otros procesos. En Linux un cambio de «uso
medido» no trae aviso de red, y se sigue preguntando cada `MIRAR_ENTORNO`.
"""
DESPERTAR_DOBLE = 10.0
"""Segundos en que un segundo aviso de despertar se toma por el mismo.

Windows avisa dos veces de una vuelta de la suspensión.
"""
PARAR_ESPERA = 10.0
"""Segundos que `parar` espera a que el agente se vaya."""
ESPERA_VENTANA = 60.0
"""Segundos que «Bloquear» espera a que se cierre la ventana de la raíz."""
ESPERA_LLAVERO = (keepassxc.ESPERA_CIERRE + keepassxc.ESPERA_VIGILANTE
                  + keepassxc.TOPE_PASADA + 30.0)
"""Lo más que se espera, antes de bloquear, a que el llavero de la raíz se cierre.

Lo que puede esperar su `--cerrar-llavero` (KeePassXC, el vigilante y la
pasada de lo pendiente) y un margen para arrancar Python.
"""
ESPERA_DESMONTAJE = 300.0
"""Segundos que se espera a que VeraCrypt cierre (puede estar preguntando)."""
GRACIA_DESMONTAJE = 5.0
"""Segundos tras salir VeraCrypt para que el `.hc` quede libre."""
ESPERA_ABRIR = 180.0
"""Segundos que `abrir` espera a que se desbloquee una raíz cerrada."""
GRACIA_ABRIR = 20.0
"""Segundos tras salir VeraCrypt para ver la raíz abierta.

Si no se ve, se da por cancelada.
"""
ESPERA_SUBIR = 120.0
"""Segundos que «Expulsar» espera, como mucho, a que suba lo pendiente de la unidad."""
ESPERA_TURNO = 20.0
"""Segundos que «Expulsar» espera a que la cola, ocupada por la pasada de otra raíz, llegue a lo suyo."""
RECIEN_PASADA = 30.0
"""Una pareja pasada hace menos que esto no se vuelve a pasar antes de expulsar."""
ESPERA_EXPULSION = 60.0
"""Segundos que se espera a que acabe una expulsión ya lanzada."""
GRACIA_EXPULSION = 30.0
"""Segundos que una expulsión que fue bien sigue contando mientras la unidad se ve.

Pasado ese tiempo con la unidad todavía ahí (el sistema no la ha retirado), se
vuelve a atender.
"""
COLA_SALIDA = 64 * 1024
"""Bytes que se leen de la salida de una pasada."""
SALIDA_DE_LOTE = 16 * 1024 * 1024
"""Bytes que se leen de la salida de un `sync.py` que pasó varias parejas: hacen falta todos sus partes."""
MIRAR_VERSION = 6 * 3600.0
"""Segundos entre comprobaciones de versión nueva (`update.check` guarda 24 h)."""
ESPERA_ATAJOS = 180.0
"""Segundos que se espera a que el sistema diga si ha puesto los atajos pedidos.

`RegisterHotKey` y `XGrabKey` contestan en el acto; el portal, cuando el
usuario confirma en la ventana del escritorio. Pasado el plazo se dan por no
puestos («el sistema no ha contestado»).
"""
REINTENTO_ATAJOS = 30.0
"""Segundos hasta volver a intentar poner los atajos si no se ha podido; se dobla en cada fallo.

Al entrar en la sesión, el bus, el portal (que se arranca al pedirlo) o la
bandeja pueden tardar más que lo que espera un intento.
"""
REINTENTO_ATAJOS_MAX = 900.0
"""Segundos, como mucho, entre dos intentos de poner los atajos."""
MIRAR_EMBLEMA = 60.0
"""Segundos entre lecturas de lo que una raíz enseña en la bandeja.

Son su icono (su `autorun.inf`) y su versión (su `VERSION`). Se leen al
conectarla y luego como mucho una vez por minuto: así se ve un icono cambiado
o una actualización hecha desde su ventana sin leer la unidad en cada vuelta.
"""

IGNORAR_CAMBIOS = huellas.IGNORAR + (APP_SUBDIR, model.LLAVERO_LOCAL)
"""Carpetas de la raíz de una pareja vigilada que no se miran.

Además de `.prversions/`, el propio `.prdrive/`: una pareja con `local = "."`
lo tendría dentro, y lo que escribe cada pasada en su `state/` la dispararía
otra vez. Y `.keychain/`, que esa pareja no sincroniza (`model.REGLA_SIN_LLAVERO`)
y que tiene su propia vigilancia. Si esa carpeta es la raíz del dispositivo se
añade lo que el sistema deja en un volumen (`model.RUIDO_DEL_SISTEMA`, vía
`ruido_en()`).
"""


def ruido_en(raiz: Path, carpeta: Path) -> tuple[str, ...]:
    """Devuelve lo que se añade a `IGNORAR_CAMBIOS` en la carpeta de una pareja vigilada.

    El ruido que el sistema deja en un volumen (`model.RUIDO_DEL_SISTEMA`:
    `System Volume Information`, `$RECYCLE.BIN`…) cuando la carpeta ES la raíz
    de la unidad (`local = "."`): ahí entra en la foto, no es contenido de
    nadie y en Windows ni siquiera se deja abrir. En cualquier otra carpeta,
    nada: lo que se llame así dentro de los datos de alguien es suyo.

    Args:
        raiz: Dónde está montada la raíz.
        carpeta: La carpeta local de la pareja.
    """
    try:
        es_la_raiz = os.path.normcase(os.path.realpath(carpeta)) \
            == os.path.normcase(os.path.realpath(raiz))
    except (OSError, ValueError):
        es_la_raiz = False
    return model.RUIDO_DEL_SISTEMA if es_la_raiz else ()


OK, FALLO, RED, SALTADA = pl.OK, pl.FALLO, pl.RED, pl.SALTADA

SIN_TOCAR = 4
"""Código de salida de `actualizar-raiz` cuando no ha llegado a tocar la raíz.

No se pudo saber qué bajar, ni bajarlo, ni comprobarlo: la raíz sigue como
estaba y se sigue sirviendo.
"""

VERSION_MINIMA = "0.5.0"
"""Primera versión cuyo `sync.py` usa el rclone del agente (`model.RCLONE_DEL_AGENTE`).

Las anteriores ejecutarían el de la unidad, que la huella no cubre: el agente
no las atiende hasta que se actualicen.
"""
SIN_VERACRYPT = ("No hay VeraCrypt en este equipo: ni instalado ni el del agente. "
                 "Vuelve a pasar el asistente, que se lo pone, o instala VeraCrypt.")
"""Lo que se dice cuando hay que abrir una raíz y no hay VeraCrypt."""
TEXTO_EVENTO = {"": "", equipo.EVENTO_BLOQUEO: "Al bloquear la sesión",
                equipo.EVENTO_SUSPENSION: "Al suspender el equipo",
                equipo.EVENTO_FIN: "Al cerrar la sesión"}
"""Cómo se dice, en un aviso, el evento de la sesión que pidió bloquear una raíz."""
SIN_RCLONE = ("no encuentro el rclone del agente; sin él no ejecuto nada de las "
              "unidades. Reinstala el agente o actualízalo.")
"""Lo que se dice cuando el agente no tiene rclone propio."""
SIN_MOTOR_DE_AVISOS = "este sistema no avisa de los cambios de las carpetas"
REARMAR_INTENTOS = 5
"""Cuántas veces, en una conexión, se intenta volver a oír los avisos de una pareja que los perdió."""
REARMAR_CADA = 120.0
"""Segundos, como poco, entre perder los avisos de una pareja y volver a intentarlo."""
VUELVEN = (avisos_carpeta.MOTIVO_SE_FUE, avisos_carpeta.MOTIVO_SIN_RESPUESTA)
"""Los motivos de quedarse sin avisos que tienen arreglo: la carpeta puede volver a estar."""
"""Por qué se recorre una carpeta vigilada cuando el agente no tiene motor de avisos."""
TEXTO_RESULTADO = {OK: "bien", FALLO: "FALLÓ", RED: "FALLÓ por la red",
                   SALTADA: "saltada: pide --resync"}
"""Cómo se dice, en el diario, el resultado de una pasada."""


LLAVERO_EN_CONFLICTO = ("Se guardó en dos dispositivos sin sincronizar en medio, y las dos "
                        "versiones están en el dispositivo: no se ha perdido nada. ")
"""El principio del aviso de un conflicto del llavero; lo acaba cómo combinarlas."""
COMBINAR_AQUI = "«Abrir llavero» ofrece combinarlas antes de abrir."
COMBINAR_A_MANO = ("Combínalas en KeePassXC: «Base de datos → Combinar desde base de "
                   "datos…».")


def lanzar(args: list[str], **kwargs) -> Any:
    """Lanza un proceso hijo.

    Punto de indirección: los tests lo sustituyen.
    """
    return subprocess.Popen(args, **kwargs)


def bajar_prioridad(pid: int) -> None:
    """Baja la prioridad de una pasada o una sonda recién lanzada (POSIX).

    `Popen` no tiene cómo pedirla al crear el hijo; un `sync.py` tarda más de
    0,1 s en llegar a lanzar su rclone, que la hereda. En Windows va en los
    `creationflags` (`_opciones_hijo()`). Punto de indirección: los tests lo
    sustituyen.
    """
    prioridad.bajar(pid)


def hay_pantalla() -> bool:
    """Indica si hay dónde abrir una ventana; en Windows, la sesión del usuario."""
    return IS_WIN or bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def avisar(titulo: str, texto: str, urgente: bool = False) -> bool:
    """Avisa con las notificaciones del sistema y lo deja en el diario.

    Returns:
        `False` si no hay avisos del sistema y solo quedó en el diario.
    """
    ok = avisos.enviar(titulo, texto, urgente)
    diario(f"aviso{'' if ok else ' (sin avisos del sistema: solo aquí)'}: "
           f"{titulo} — {texto}")
    return ok


def abrir_contenedor(raiz: Path) -> bool:
    """Le pide a VeraCrypt que abra el contenedor de `raiz`.

    Lo lanza desde la carpeta del agente (`penwatch.open_container`).
    """
    return penwatch.open_container(raiz, cwd=equipo.DIR)


def orden_explorar(ruta: Path) -> list[str] | None:
    """Devuelve la orden que abre el explorador de archivos en `ruta`, o `None`.

    En Windows, `explorer.exe` con la carpeta, y no `os.startfile()`: abrir una
    raíz de unidad «como documento» pasa por los verbos del Shell para esa
    unidad, y explorer.exe con una ruta solo la enseña. En Linux, `xdg-open`,
    que la abre con el gestor de archivos del escritorio; sin él, `None`.
    """
    if IS_WIN:
        sistema = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
        return [str(Path(sistema) / "explorer.exe"), str(ruta)]
    xdg = shutil.which("xdg-open")
    return [xdg, str(ruta)] if xdg else None


def explorar(ruta: Path) -> bool:
    """Abre el explorador de archivos en `ruta`, sin esperar.

    Se lanza desde la carpeta del agente, fuera de toda raíz. Punto de
    indirección: los tests lo sustituyen o miran lo que pasa a `lanzar()`.

    Returns:
        `False` si este equipo no tiene con qué (Linux sin `xdg-open`).

    Raises:
        OSError: Si no se ha podido lanzar.
    """
    orden = orden_explorar(ruta)
    if orden is None:
        return False
    lanzar(orden, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
           stderr=subprocess.DEVNULL, cwd=str(equipo.DIR), close_fds=True)
    return True


def desbloquear_bitlocker(raiz: Path) -> Any | None:
    """Saca la ventana de Windows que desbloquea una unidad con BitLocker, sin esperar.

    Es la orden de `bitlocker.orden_desbloquear()`: la contraseña la pide
    Windows y el agente no la ve. Se lanza desde la carpeta del agente, y de la
    unidad no se ejecuta nada. Punto de indirección: los tests lo sustituyen o
    miran lo que pasa a `lanzar()`.

    Returns:
        El proceso lanzado, o `None` si este equipo no tiene con qué.

    Raises:
        OSError: Si no se ha podido lanzar.
    """
    orden = bitlocker.orden_desbloquear(raiz)
    if orden is None:
        return None
    return lanzar(orden, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL, cwd=str(equipo.DIR), close_fds=True)


def diario(msg: str) -> None:
    """Añade una línea al diario del agente (`penwatch.log`)."""
    penwatch.log(msg)


def hilo(funcion) -> None:
    """Corre `funcion` en un hilo aparte, para lo que puede tardar (la red o un disco).

    Punto de indirección: los tests la corren en el sitio.
    """
    threading.Thread(target=funcion, daemon=True).start()


def hay_keepassxc() -> bool:
    """Indica si en el equipo corre algo que pueda ser el KeePassXC de una unidad.

    En Windows se pregunta por el nombre a la instantánea de Toolhelp
    (`store.foto_de_procesos()`), que no abre ningún proceso: sin ningún
    `KeePassXC.exe` en el equipo no hace falta recorrerlos todos para saber
    desde dónde corre cada uno (`keepassxc_abierto()`). Si no se puede saber, o
    en Linux (allí cuenta la línea de órdenes), sí. Punto de indirección: los
    tests dicen lo que hay.
    """
    foto = store.foto_de_procesos()
    if foto is None:
        return True
    return any(exe.lower() == components.KEEPASSXC_EXE.lower() for exe in foto.values())


def keepassxc_abierto(raiz: Path) -> bool:
    """Indica si el KeePassXC de esa raíz está abierto en este equipo.

    Es `llavero.keepassxc_abierto()` sobre su `.prdrive/`: en Windows recorre
    todos los procesos del equipo. Punto de indirección: los tests dicen si lo
    está, sin procesos de verdad.
    """
    return llavero.keepassxc_abierto(app(raiz))


def limpiar_navegador() -> tuple[int, list[str]]:
    """Quita lo del navegador que apunta a un KeePassXC de prdrive que ya no está.

    Es lo que no pudo hacer «Expulsar» con una unidad que se quitó sin
    expulsarla: `presencia.limpiar_navegador()`, lo mismo que hace
    desinstalar. Punto de indirección: los tests no tocan el registro ni los
    navegadores.

    Returns:
        Cuántas claves o manifiestos ha tocado y lo que no ha podido hacer.
    """
    return presencia.limpiar_navegador()


def cerrar_keepassxc_huerfano(raiz: Path) -> int:
    """Le pide que se cierre al KeePassXC de una raíz que se ha ido; devuelve a cuántos.

    En Linux corre extraído en el equipo, no desde la unidad, así que no muere
    con ella como en Windows: seguiría con la base abierta en memoria, y sus
    passkeys, en un equipo del que la unidad ya se ha ido. Se le pide como lo
    haría la persona (`keepassxc.pedir_cierre()`): con algo sin guardar,
    pregunta él. Es de módulo para que los tests no cierren nada.
    """
    return 0 if IS_WIN else keepassxc.cerrar_huerfano(raiz / APP_SUBDIR)


def keepassxc_huerfano_abierto(raiz: Path) -> bool:
    """Indica si sigue abierto el KeePassXC de una raíz que se ha ido (Linux).

    Tras pedirle que se cierre tarda en salir (medio segundo, o lo que tarde la
    persona si tiene algo sin guardar), y mientras tanto el navegador no se
    puede dejar como estaba. Es de módulo para que los tests no miren procesos.
    """
    return False if IS_WIN else bool(llavero.pids_keepassxc(raiz / APP_SUBDIR))


def ruido_de_editor(pareja: str) -> tuple[str, ...]:
    """Devuelve los ficheros de la carpeta de una pareja vigilada cuyo cambio no cuenta.

    Lo que dejan los programas con los que se trabaja (`huellas.RUIDO_DE_EDITOR`),
    a cualquier profundidad: ni lo avisan los motores ni entra en la foto. Del
    llavero se mira todo: son cuatro ficheros, y lo que más importa tener al día.

    Args:
        pareja: El nombre de la pareja.
    """
    return () if pareja == model.LLAVERO else huellas.RUIDO_DE_EDITOR


def huella_local(ruta: Path, tope: int, ignorar: tuple[str, ...]) -> pl.Huella | None:
    """Toma la foto de la carpeta local de una pareja vigilada (`watch = true`).

    Es `huella.de_carpeta()`: recorre la carpeta sin abrir ningún fichero y sin
    seguir enlaces. Punto de indirección: los tests devuelven la foto que
    quieren, sin tocar el disco.

    Args:
        ruta: La carpeta.
        tope: Cuántas entradas se cuentan como mucho.
        ignorar: Patrones de las entradas de su raíz que no se miran.

    Returns:
        La foto, o `None` si no se pudo tomar.
    """
    return huellas.de_carpeta(ruta, tope, ignorar)


def cache_version() -> Path:
    """Devuelve dónde se guarda lo último que dijo GitHub sobre versiones.

    Vive en la carpeta del agente: no es de ninguna raíz y el `state/` de su
    código se va con cada versión.
    """
    return equipo.DIR / "update.json"


def buscar_version() -> "update.Release | None":
    """Devuelve la release más nueva que este agente, o `None`.

    Respeta la caché de `update.check()` (24 h), así que casi nunca sale a la
    red.
    """
    update.check(cache=cache_version())
    return update.pending(SCRIPT_DIR, cache=cache_version())


def buscar_version_ya() -> "tuple[update.Release | None, str | None]":
    """Pregunta a GitHub por la última release, sin mirar la caché.

    Es el «Buscar actualizaciones» de la bandeja. Punto de indirección: los
    tests la sustituyen.

    Returns:
        Lo que devuelve `update.check()`: la release que se sabe y, si algo
        fue mal, qué decir.
    """
    return update.check(force=True, cache=cache_version())


def ejecutar(args: list[str], **kwargs) -> Any:
    """Corre un proceso hasta que acaba.

    Punto de indirección: los tests la sustituyen.
    """
    return subprocess.run(args, **kwargs)


def python(ventana: bool = False) -> str:
    """Devuelve el Python del agente, para sus hijos: sin consola en Windows."""
    exe = sys.executable
    if IS_WIN:
        w = Path(exe).with_name("pythonw.exe")
        if w.is_file():
            return str(w)
    return exe


def rclone_propio() -> Path | None:
    """Devuelve el rclone del agente, o `None` si no está.

    Lo pone el instalador en `rclone/<versión fijada>/` y lo apunta
    `instalacion.json`. Es el que se pasa a las pasadas y a las ventanas, y con
    el que se sondea un remoto: el de una unidad no se ejecuta nunca. Punto de
    indirección: los tests lo sustituyen.
    """
    ruta = equipo.leer_instalacion().get("rclone")
    if not isinstance(ruta, str) or not ruta:
        return None
    try:
        return Path(ruta) if Path(ruta).is_file() else None
    except OSError:
        return None


def veracrypt_propio() -> str | None:
    """Devuelve el VeraCrypt del agente para ESTE equipo, comprobado, o `None`.

    Lo pone el instalador en `veracrypt/<versión fijada>/` solo cuando atiende
    una raíz cifrada y no hay VeraCrypt instalado
    (`install/agente.quiere_veracrypt()`), y lo apunta en `instalacion.json`,
    que se lee aquí cada vez: añadirlo no obliga a parar el agente. Se vuelve a
    resumir contra su sello antes de devolverlo, porque lo que se lanza pide
    administrador (UAC) y tiene que ser lo que se comprobó al instalar. En
    Windows, el ejecutable y el driver de la arquitectura NATIVA, como en el
    vestíbulo: VeraCrypt elige su driver por ella y un driver no se emula.
    Punto de indirección: los tests lo sustituyen.
    """
    carpeta = equipo.leer_instalacion().get("veracrypt")
    if not isinstance(carpeta, str) or not carpeta:
        return None
    if IS_WIN:
        arq = penwatch.native_arch()
        if arq not in penwatch.TRAVELER_ARCHS:
            return None
        exe = penwatch.TRAVELER_PORTABLE.format(arq=arq)
        necesarios = (exe, f"veracrypt-{arq}.sys")
    else:
        exe = "veracrypt"
        necesarios = (exe,)
    if not components.veracrypt_integro(carpeta, necesarios):
        diario(f"el VeraCrypt del agente en {carpeta} no cuadra con su sello: no lo "
               f"lanzo. Reinstala el agente.")
        return None
    return str(Path(carpeta) / exe)


def veracrypt_de_la_raiz() -> str | None:
    """Devuelve con qué VeraCrypt se abre y se cierra la raíz cifrada, o `None`.

    El instalado primero: con su driver cargado no pide administrador, y con
    otra versión menor cargada el portable fallaría con `ERR_DRIVER_VERSION`.
    Si no, el del agente.
    """
    return penwatch.installed_veracrypt() or veracrypt_propio()


def procesos(nombre: str) -> set[int]:
    """Devuelve los pid vivos con ese nombre de ejecutable (Windows; en POSIX, vacío).

    Punto de indirección: los tests lo sustituyen.
    """
    return store.procesos_llamados(nombre)


def _opciones_hijo(cwd: Path, separado: bool = False, baja: bool = False) -> dict:
    """Devuelve los argumentos de `Popen` para un hijo del agente.

    Sus `.pyc` van a la carpeta del agente: los `__pycache__` de una raíz no
    entran en su huella (`huella()`), así que Python no debe leerlos de ahí, y
    de paso no se escribe en la unidad. Y siempre con su rclone: sin él, una
    ruta que no existe, para que el `sync.py` de la raíz falle diciéndolo en
    vez de usar el de la unidad.

    Args:
        cwd: Directorio de trabajo, fuera de la raíz.
        separado: En su propio grupo de procesos (Windows) o sesión (POSIX),
            para poder cortar la pasada entera.
        baja: Con prioridad baja, que heredan sus hijos (`common/prioridad.py`).
            En Windows va aquí; en POSIX la baja `bajar_prioridad()` al lanzarlo.
    """
    rclone = rclone_propio() or equipo.dir_rclone() / "falta" / model.rclone_name()
    kwargs: dict = {"stdin": subprocess.DEVNULL, "cwd": str(cwd), "close_fds": True,
                    "env": {**os.environ,
                            "PYTHONPYCACHEPREFIX": str(equipo.DIR / "pycache"),
                            model.RCLONE_DEL_AGENTE: str(rclone)}}
    if IS_WIN:
        kwargs["creationflags"] = penwatch.CREATE_NO_WINDOW | (
            penwatch.CREATE_NEW_PROCESS_GROUP if separado else 0) | (
            prioridad.CLASE_WINDOWS if baja else 0)
    elif separado:
        kwargs["start_new_session"] = True
    return kwargs


def orden_pregunta(nombre: str, espera: float, cambiada: bool) -> list[str]:
    """Devuelve la orden que abre la ventanita que pregunta por una unidad.

    Es `pregunta.py`, que no compila ni carga el agente. Si falta junto a este
    `agente.py`, vuelve a `agente.py pregunta`, que hace lo mismo más despacio.

    Args:
        nombre: El nombre de la unidad.
        espera: Segundos de la cuenta atrás.
        cambiada: Si la unidad ya estaba en la lista pero con otro código.
    """
    entrada = SCRIPT_DIR / "pregunta.py"
    guion = ([str(entrada)] if entrada.is_file()
             else [str(SCRIPT_DIR / "agente.py"), "pregunta"])
    return [python(ventana=True), *guion, "--nombre", nombre, "--segundos", str(int(espera)),
            *(["--cambiada"] if cambiada else [])]


def orden_atajos(motivo: str = "") -> list[str]:
    """Devuelve la orden que abre la ventana que graba los atajos de teclado.

    Es `pregunta.py --atajos`, la entrada pequeña de las ventanitas del agente
    (`ui/tk_atajos.py`).

    Args:
        motivo: Por qué en este equipo no se pueden poner: la ventana lo dice
            y no ofrece grabar. Vacío si se puede.
    """
    return [python(ventana=True), str(SCRIPT_DIR / "pregunta.py"), "--atajos",
            *(["--motivo", motivo] if motivo else [])]


def app(raiz: Path) -> Path:
    """Devuelve la carpeta del programa dentro de una raíz."""
    return raiz / APP_SUBDIR


HUELLA_SIN_CARPETAS = frozenset({"state", "logs", "filters", "keys", "runtime", "bin",
                                 "keepassxc"})
"""Carpetas que la huella deja fuera: lo que cambia con el uso y no se lee entero.

`keepassxc/` es el programa del llavero y su configuración, que KeePassXC
reescribe al usarlo. El programa SÍ se ejecuta, pero no por la huella: cada
ejecutable se comprueba contra su SHA-256 en `common/pins.py` justo antes de
lanzarlo (`keepassxc.comprobar()`), y esos dos ficheros sí entran en la huella.
"""
HUELLA_SIN_FICHEROS = frozenset({"sync_config.toml", Path(penwatch.CONTROL_FILE).name})
"""Ficheros que la huella deja fuera: la configuración y el fichero de control."""
HUELLA_SIN_EXTENSIONES = frozenset({".ico"})
"""Extensiones que la huella deja fuera."""


def huella(raiz: Path) -> str | None:
    """Devuelve el sha256 de lo que el agente ejecutaría de esa raíz.

    Es `None` si no se puede leer. El id del fichero de control lo lleva
    escrito la unidad: copiarlo junto a un `.prdrive/` modificado bastaría para
    que el agente ejecutara ese código como si fuera el de la unidad que se
    atendió. Por eso al decir que sí se apunta esta huella
    (`equipo.Unidad.codigo`) y con otra se vuelve a preguntar. No hay firmas de
    las que fiarse: tras actualizar la unidad se pregunta una vez más, y es lo
    esperado.

    Entra todo `.prdrive/` menos lo que cambia con el uso: `state/`, `logs/`,
    `filters/`, `keys/`, `runtime/` (el agente usa su propio Python),
    `sync_config.toml` (lo edita la ventana), el fichero de control y los
    iconos. Todo lo demás cuenta, también lo desconocido: con la carpeta de la
    unidad en `sys.path`, un `json.py` suelto se importaría antes que el de
    verdad. Los `__pycache__` no, porque los hijos del agente los buscan en su
    carpeta (`PYTHONPYCACHEPREFIX`, `_opciones_hijo()`). `bin/` tampoco: el
    agente no ejecuta el rclone de la unidad, pasa el suyo
    (`model.RCLONE_DEL_AGENTE`), y por eso la huella cuesta milisegundos y no
    lo que tarda en leerse un binario de 60 MB. `keepassxc/` tampoco (78 MB y
    una configuración que cambia con el uso): lo que de ahí se lanza se
    comprueba contra un SHA-256 fijado en `common/pins.py`, que sí entra en la
    huella, antes de lanzarlo (`keepassxc.comprobar()`); las DLL y los demás
    ficheros que van al lado del programa no se comprueban. `rclone.conf`
    entra: la opción `ssh` de un remoto sftp es una orden.
    """
    base = app(raiz)
    rutas: list[Path] = []
    try:
        for carpeta, carpetas, ficheros in os.walk(base):
            rel = Path(carpeta).relative_to(base)
            arriba = rel == Path(".")
            carpetas[:] = [c for c in carpetas if c != "__pycache__"
                           and not (arriba and c in HUELLA_SIN_CARPETAS)]
            for f in ficheros:
                if arriba and f in HUELLA_SIN_FICHEROS:
                    continue
                if Path(f).suffix.lower() in HUELLA_SIN_EXTENSIONES:
                    continue
                rutas.append(rel / f)
        h = hashlib.sha256()
        for rel in sorted(set(rutas), key=lambda r: r.as_posix()):
            ruta = base / rel
            h.update(f"{rel.as_posix()}\0{ruta.stat().st_size}\0".encode("utf-8"))
            with ruta.open("rb") as f:
                for trozo in iter(lambda: f.read(1 << 20), b""):
                    h.update(trozo)
    except (OSError, ValueError):
        return None
    return h.hexdigest()


def version_vieja(raiz: Path) -> str | None:
    """Devuelve la versión de esa raíz si es anterior a `VERSION_MINIMA`.

    Es `None` si vale y `""` si no se sabe, que también cuenta como vieja. De
    una unidad de la lista la `VERSION` es de fiar: entra en la huella que se
    aceptó.
    """
    version = update.installed_version(app(raiz))
    if version and not update.is_newer(VERSION_MINIMA, version):
        return None
    return version


def estado_de(raiz: Path) -> Path:
    """Devuelve la carpeta `state/` de una raíz."""
    return app(raiz) / "state"


def nombre_guardado(unidad: equipo.Unidad | None, uid: str) -> str:
    """Devuelve el nombre de una unidad que no se está viendo ahora.

    Es el que el agente le conoció (`Unidad.nombre`) y, sin él,
    `nombres.por_defecto()` con su id: la etiqueta del volumen solo se lee al
    conectarla.
    """
    return (unidad.nombre if unidad is not None else "") or nombres.por_defecto(uid)


def nombre_de(raiz: Path, uid: str, otros: Iterable[str] = (),
              con_etiqueta: bool = True) -> str:
    """Devuelve el nombre con que se enseña la unidad conectada en `raiz`.

    Es el de la bandeja, los avisos y el diario. Lo decide `nombres`: el que
    alguien puso, y sin él la etiqueta del volumen o «prdrive · <id>». Lo que
    se sabe de la unidad sale de su `state/fleet.json` (solo se lee): su
    `nombre` y los equipos desde los que ha publicado, que dicen si ese nombre es
    de verdad suyo o el del ordenador que la aprovisionó; y del `label=` de su
    `autorun.inf`, que solo escribe «Nombre e icono»: con el mismo nombre, es
    suyo aunque se llame como el ordenador. El que el agente recuerda de ella
    (`Unidad.nombre`) no cuenta: lo calculó él, no lo puso nadie, y darlo por
    propio lo congelaría.

    Args:
        raiz: Donde está montada.
        uid: Su id.
        otros: Los nombres de las demás unidades: con uno igual se añade el
            equipo (`nombres.distinguir()`).
        con_etiqueta: Si se lee la etiqueta del volumen; una carpeta del equipo
            no tiene la suya.
    """
    estado = store.read_json(estado_de(raiz) / "fleet.json")
    guardado = estado.get("nombre")
    guardado = guardado.strip() if isinstance(guardado, str) else ""
    publicado = estado.get("publicado")
    equipos = publicado.get("equipos") if isinstance(publicado, dict) else None
    equipos = [e for e in equipos if isinstance(e, str)] if isinstance(equipos, list) else []
    etiqueta = nombres.etiqueta_de(raiz) if con_etiqueta else ""
    elegido = nombres.elegir(uid, guardado, etiqueta, equipos, autorun.leer(raiz).etiqueta)
    return nombres.distinguir(elegido, uid, otros)


@dataclass(frozen=True)
class Servicio:
    """Lo que el servicio de una raíz sincroniza: sus parejas y cada cuánto.

    Args:
        parejas: Las parejas, con su remoto.
        minutos: El intervalo entre pasadas.
        locales: La carpeta local, normalizada como la entiende el motor
            (`model.normalizar_local()`), de cada pareja que pide vigilar sus
            cambios (`watch = true`), por nombre.
        excluidos: De cada una de esas parejas, los ficheros que excluye por
            su nombre (`model.excluidos_por_nombre()`): sus cambios no
            cuentan, la pasada no los subiría.
    """
    parejas: tuple[pl.Pareja, ...]
    minutos: float
    locales: Mapping[str, str] = field(default_factory=dict)
    excluidos: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


class ConfigRechazada(ValueError):
    """El config de una raíz trae algo que no puede llegar a la línea de órdenes de rclone.

    Es el `ConfigError` de `model.comprobar_seguridad()` como `ValueError`, que
    es lo que dice por qué no se sirve una raíz. Se distingue de los demás para
    avisar de lo que es: un config rechazado no es «nada que sincronizar».
    """


def leer_config(raiz: Path) -> dict:
    """Lee el `sync_config.toml` de una raíz, a pelo, y lo pasa por la puerta de seguridad.

    Es lo que el agente comprueba de un config ajeno antes de servir una raíz
    (`leer_servicio()`) y de lanzar una pasada (`Agente._lanzar()`): el `sync.py`
    de una raíz de antes de esa puerta no comprueba nada, y el agente solo
    relee el config si cambia su fecha, que quien lo edite puede conservar.

    Args:
        raiz: La raíz de la unidad.

    Returns:
        El config tal como salió del TOML.

    Raises:
        ConfigRechazada: Si `model.comprobar_seguridad()` lo rechaza.
        ValueError: Si no se puede leer o no es TOML válido.
    """
    fichero = app(raiz) / "sync_config.toml"
    try:
        crudo = tomllib.loads(fichero.read_text(encoding="utf-8"))
    except OSError as e:
        raise ValueError(f"no se puede leer sync_config.toml ({e})") from e
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"sync_config.toml no es TOML válido ({e})") from e
    try:
        model.comprobar_seguridad(crudo, model.es_equipo(app(raiz)),
                                  carpeta_programa=APP_SUBDIR)
    except model.ConfigError as e:
        # El fichero del dispositivo está oculto (`.prdrive/`): el aviso lo nombra.
        raise ConfigRechazada(f"{e} (en {fichero})") from e
    return crudo


def leer_servicio(raiz: Path) -> Servicio:
    """Devuelve las parejas y el intervalo del servicio de esa raíz.

    Los elige como su propio runsync: `ui_prefs.json` > `[daemon]` > todas
    (`prefs.elegir()`). Con `[keychain]`, además la del llavero, siempre y
    vigilada (`common/llavero.py`). Se lee el TOML a pelo y no con `model.parse_config()`
    porque la raíz puede ir en otra versión que el agente: lo que valida es su
    `sync.py`, y un modo que este agente no conozca no puede dejarla sin
    servicio. Lo único que sí comprueba el agente es lo que acabaría en la
    línea de órdenes de rclone en ESTE equipo (`model.comprobar_seguridad()`,
    que también mira que el `local` de cada pareja no salga de la raíz, con la
    regla de la raíz del equipo si lo es, ni sea la carpeta del programa de ESA
    raíz: el agente corre en su propia carpeta, no en la `.prdrive` de la
    unidad): el `sync.py` de una raíz de antes de esa regla no comprueba nada, y
    `orden_sonda()` pasa el `remote` de cada pareja a un `rclone lsd`.

    Raises:
        ValueError: Con la frase que decir si no hay nada que atender, o
            `ConfigRechazada` si el config trae algo que no puede llegar a
            rclone (`leer_config()`).
    """
    crudo = leer_config(raiz)
    defaults = crudo.get("defaults") if isinstance(crudo.get("defaults"), dict) else {}
    remotos: dict[str, str] = {}
    locales: dict[str, str] = {}
    excluidos: dict[str, tuple[str, ...]] = {}
    for p in crudo.get("pair") if isinstance(crudo.get("pair"), list) else []:
        # El nombre va a la línea de órdenes de su `sync.py` y a sus carpetas
        # de `state/` y `filters/`: uno que su parser no admitiría (`--resync`,
        # `a/b`) no se lanza, aunque el `sync.py` de esa raíz sea de antes de
        # la regla.
        if isinstance(p, dict) and isinstance(p.get("name"), str) \
                and model.problema_nombre(p["name"]) is None:
            remotos[p["name"]] = str(p.get("remote", defaults.get("remote",
                                                                  model.DEFAULT_REMOTE)))
            # Se vigila solo lo que pide `watch = true` en un modo con el local
            # de origen (`model.pide_watch()`) y tiene dónde mirar.
            # El `local` se normaliza como lo hace el motor (`model.normalizar_local()`):
            # `sync-data\docs` sincroniza, y sin eso se miraría una carpeta que
            # no existe.
            local = p.get("local")
            if model.pide_watch(p) and isinstance(local, str) and local.strip():
                locales[p["name"]] = model.normalizar_local(local)
                excluidos[p["name"]] = model.excluidos_por_nombre(p, defaults)
            else:
                locales.pop(p["name"], None)
                excluidos.pop(p["name"], None)
    if not remotos:
        raise ValueError("sync_config.toml no tiene ninguna pareja")
    daemon = crudo.get("daemon") if isinstance(crudo.get("daemon"), dict) else {}
    elegidas, minutos, _ = prefs.elegir(list(remotos), daemon,
                                        store.read_json(estado_de(raiz) / "ui_prefs.json"))
    parejas = [pl.Pareja(n, remotos[n], vigila=n in locales) for n in elegidas]
    vigiladas = {n: locales[n] for n in elegidas if n in locales}
    # El llavero no se elige: con `[keychain]` se atiende siempre, como una
    # pareja con `watch = true` en `.keychain/`. Una pareja del usuario con su
    # nombre la invalidaría su `sync.py`; aquí no se lanza la del llavero.
    if isinstance(crudo.get("keychain"), dict) and model.LLAVERO not in remotos:
        remoto, _ = model.carpeta_del_catalogo(defaults)
        parejas.append(pl.Pareja(model.LLAVERO, remoto, vigila=True, llavero=True))
        vigiladas[model.LLAVERO] = model.LLAVERO_LOCAL
    return Servicio(tuple(parejas), minutos, vigiladas,
                    {n: excluidos[n] for n in vigiladas if excluidos.get(n)})


def orden_sonda(raiz: Path, remoto: str) -> list[str] | None:
    """Devuelve la orden que pregunta a rclone por el remoto de esa raíz.

    Es `None` sin rclone. Es `lsd` del remoto con `catalog.NET_FLAGS`: lo
    mínimo que exige conectar y entrar, con plazos cortos para que un remoto
    caído no tenga la cola parada.
    """
    binario = rclone_propio()
    if binario is None:
        return None
    return [str(binario), "--config", str(app(raiz) / "rclone.conf"),
            *catalog.NET_FLAGS, "lsd", f"{remoto}:", "--max-depth", "1"]


def en_la_raiz(raiz: Path, ruta: Path) -> Path | None:
    """Devuelve `ruta` si, con los enlaces resueltos, sigue dentro de `raiz`.

    Si no, `None`. Lo que el agente escribe en una raíz (el diario y el lock de
    su servicio) va a donde diga ESA raíz, y una unidad es de quien la trae: un
    `state/daemon.log` que fuera un enlace a `~/.bashrc`, o un `state/` que
    llevara a la carpeta personal, haría que el agente escribiera en el equipo.
    Solo se escribe donde la ruta resuelta sigue dentro de la raíz resuelta.
    """
    try:
        real, base = os.path.realpath(ruta), os.path.realpath(raiz)
        if os.path.commonpath([os.path.normcase(real), os.path.normcase(base)]) \
                != os.path.normcase(base):
            return None
    except (OSError, ValueError):
        return None
    return ruta


_SIN_ENLACE = getattr(os, "O_NOFOLLOW", 0)
"""Abre para añadir sin seguir un enlace en el último tramo (POSIX).

Lo demás lo descarta `en_la_raiz()`.
"""


def dlog(raiz: Path, msg: str) -> None:
    """Añade una línea al diario del servicio de la raíz (`state/daemon.log`).

    Como el de runsync. Se abre y se cierra en cada línea: nada se queda
    abierto en la unidad. Pasado `store.DIARIO_TOPE` se recorta antes de
    añadir (`store.recortar_diario()`), igual que el de runsync.
    """
    ruta = en_la_raiz(raiz, estado_de(raiz) / "daemon.log")
    if ruta is None:
        return
    store.recortar_diario(ruta)
    try:
        fd = os.open(ruta, os.O_WRONLY | os.O_APPEND | os.O_CREAT | _SIN_ENLACE, 0o666)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(f"{store.stamp()} {msg}\n")
    except OSError:
        pass


def presente(raiz: Path) -> bool:
    """Indica si la raíz tiene su fichero de control a la vista."""
    try:
        return (raiz / penwatch.CONTROL_FILE).is_file()
    except OSError:
        return False


NOMBRE_LOCK = Path(penwatch.DAEMON_LOCK_REL).name
NOMBRE_VENTANA = Path(penwatch.UI_LOCK_REL).name
NOMBRE_STOP = "daemon.stop"
NOMBRE_PREFS = "ui_prefs.json"
ESTADO_QUE_SE_MIRA = frozenset({NOMBRE_LOCK, NOMBRE_VENTANA, NOMBRE_STOP, NOMBRE_PREFS,
                                equipo.BUZON_SERVICIO})
"""Los ficheros del `state/` de una raíz con los que se cumple su contrato de servicio."""


def mirar_estado(raiz: Path) -> dict[str, tuple[int, int]] | None:
    """Devuelve lo que hay del contrato en el `state/` de una raíz, con UNA lectura de la carpeta.

    Es lo que el agente mira de cada raíz conectada en cada vuelta. Antes eran
    nueve operaciones sueltas (existe el stop, lee el lock dos veces, lee el de
    la ventana, intenta renombrar el buzón, dos fechas, el fichero de
    control): en un pendrive, 273 por minuto, y el USB no descansaba nunca.
    Listar la carpeta dice de una vez qué hay y con qué fecha, y solo se abre
    lo que ha cambiado (`Agente._registro()`).

    Returns:
        `{nombre: (mtime en ns, tamaño)}` de los ficheros de
        `ESTADO_QUE_SE_MIRA` que están; `None` si la raíz ya no está a la vista.
    """
    visto: dict[str, tuple[int, int]] = {}
    try:
        with os.scandir(estado_de(raiz)) as entradas:
            for e in entradas:
                if e.name not in ESTADO_QUE_SE_MIRA:
                    continue
                try:
                    st = e.stat()
                except OSError:
                    continue                # se fue entre listarlo y mirarlo
                visto[e.name] = (st.st_mtime_ns, st.st_size)
    except (FileNotFoundError, NotADirectoryError):
        # Sin `state/` todavía (una raíz recién puesta), o ya sin unidad.
        return {} if presente(raiz) else None
    except OSError:
        return None
    return visto


def letras_de_unidad() -> int | None:
    """Devuelve las letras de unidad que hay ahora en Windows, como máscara, o `None` fuera de él.

    `GetLogicalDrives`: un par de microsegundos, sin tocar ningún disco. Que
    cambie es que ha aparecido o se ha ido un volumen, lo diga o no la bandeja.
    """
    if not IS_WIN:
        return None
    try:
        import ctypes
        return int(ctypes.windll.kernel32.GetLogicalDrives())
    except (OSError, AttributeError):
        return None


def _registro_vivo(raiz: Path, rel: Path) -> dict | None:
    """Devuelve ese registro de la raíz si es de un proceso vivo de este equipo y arranque.

    Es el `penwatch._vivo_aqui()` del agente, con el arranque del sistema
    (`store.vivo_en_este_arranque()`). Penwatch se queda con el pid solo porque
    únicamente decide si lanzar o no; el agente pausa una raíz por lo que
    diga, y el registro de una ventana de antes de reiniciar, con su pid
    reutilizado, la dejaría en pausa para siempre. Solo lee: no limpia lo
    rancio ni escribe en el dispositivo, que bloquearía su extracción.

    Args:
        raiz: La raíz de la unidad.
        rel: El registro, relativo a la raíz (`penwatch.UI_LOCK_REL`,
            `penwatch.DAEMON_LOCK_REL`).

    Returns:
        El registro, o `None`.
    """
    info = store.read_json(raiz / rel)
    return info if store.vivo_en_este_arranque(info, HOST) else None


def _aplicacion_en_marcha(raiz: Path) -> str | None:
    """Devuelve qué hay ya en marcha para esa raíz en este equipo, o `None`.

    Es `penwatch.aplicacion_en_marcha()` con `_registro_vivo()`, y dice lo
    mismo: la ventana de runsync o el servicio periódico (el de runsync o
    el del propio agente). Solo mira.
    """
    ventana = _registro_vivo(raiz, penwatch.UI_LOCK_REL)
    if ventana is not None:
        return f"la ventana de runsync ya está abierta (pid {ventana.get('pid')})"
    servicio = _registro_vivo(raiz, penwatch.DAEMON_LOCK_REL)
    if servicio is not None:
        return f"el servicio periódico ya está en marcha (pid {servicio.get('pid')})"
    return None


def punto_ocupado(unidad: equipo.Unidad) -> str | None:
    r"""Devuelve por qué no se puede montar ahí la raíz cifrada, o `None` si se puede.

    El agente no se inventa otra letra ni otro sitio: los programas apuntan a
    la raíz, y un almacén de Obsidian en `P:\\obsidian` se rompería si mañana
    fuera `Q:`. En Linux, el punto de montaje vacío es una carpeta normal, y lo
    que se guarde ahí con el contenedor cerrado quedaría tapado al montarlo.
    """
    if unidad.letra:
        raiz = Path(f"{unidad.letra}:\\")
        try:
            existe = raiz.exists()
        except OSError:
            existe = True
        if not existe:
            return None
        try:
            suya = penwatch.control_id(raiz) == unidad.id
        except OSError:
            suya = False
        if suya:
            return (f"La letra {unidad.letra}: tiene su raíz, pero el contenedor está "
                    f"cerrado: es un volumen fantasma (se desconectó sin bloquear). "
                    f"Bloquéala y vuelve a desbloquearla.")
        return (f"La letra {unidad.letra}: está ocupada por otra unidad, y no se "
                f"cambia: los programas apuntan a {unidad.letra}:\\. Libérala y "
                f"vuelve a desbloquear.")
    punto = Path(unidad.ruta)
    try:
        if os.path.ismount(punto):
            return f"Ya hay algo montado en {punto}."
        if punto.is_dir() and any(punto.iterdir()):
            return (f"{punto} tiene cosas con el contenedor cerrado: no se monta "
                    f"encima, porque quedarían tapadas. Muévelas a otro sitio y "
                    f"vuelve a desbloquear.")
    except OSError as e:
        return f"No puedo mirar {punto}: {e}"
    return None


def bloqueada(unidad: equipo.Unidad) -> bool:
    """Indica si el contenedor de esa raíz ya está cerrado.

    En Windows, que la letra se vaya no basta: forzando el desmontaje con un
    fichero abierto dentro, la letra desaparece y el driver sigue reteniendo el
    `.hc`. Bloqueada es el `.hc` libre y la letra ida (la de un fantasma
    también tiene que irse). En Linux no hay esa prueba (`vestibulo.retenido()`
    no contesta): es el punto de montaje sin montar.
    """
    raiz = Path(unidad.ruta)
    if unidad.letra:
        return vestibulo.retenido(unidad.contenedor) is not True and not presente(raiz)
    try:
        return not os.path.ismount(raiz) and not presente(raiz)
    except OSError:
        return False


def bloqueada_unidad(fisica: Path, raiz: Path) -> bool:
    """Indica si el contenedor de una unidad con vestíbulo ya está cerrado.

    Es la prueba de `bloqueada()` con el `.hc` de su raíz física: libre, y el
    volumen de dentro ido.

    Args:
        fisica: La raíz física de la unidad, donde están su marca y su `.hc`.
        raiz: Donde estaba montado el volumen de dentro (su letra).
    """
    return (vestibulo.retenido(fisica / penwatch.CONTAINER_FILE) is not True
            and not presente(raiz))


def orden_bloquear(unidad: equipo.Unidad, desatendido: bool = False,
                   raiz: Path | None = None, veracrypt: str | None = None) -> list[str] | None:
    """Devuelve el desmontaje de una raíz cifrada, o `None` sin el VeraCrypt que hace falta.

    Pedido por una persona va SIN `/silent`, como `Expulsar PRDRIVE.bat`: con
    un fichero abierto dentro VeraCrypt pregunta si forzar, y esa decisión es
    suya. Sin VeraCrypt es que no hay ni el instalado ni el del agente.

    Desatendido (al bloquear la sesión, suspender o apagar) no hay nadie que
    conteste, así que ni pregunta ni fuerza: `/silent` y nunca `/force`. En
    `UnmountVolumeBase()` (`src/Common/Dlgcode.c` de VeraCrypt), con `Silent`
    no sale la espera ni, si el volumen tiene ficheros abiertos
    (`ERR_FILES_OPEN`), el «¿forzar?» (`AskWarnYesNoTopmost`), y el `Error()`
    del fallo no enseña nada: el volumen se queda montado. Forzar es
    `bForceUnmount`, que solo pone `/force` (`src/Mount/Mount.c`). Y solo con
    el VeraCrypt INSTALADO: el portable del agente pide UAC en cada
    desmontaje, y con la sesión bloqueada saldría uno que nadie ha pedido.

    Args:
        unidad: La raíz de la lista.
        desatendido: Si no hay nadie delante.
        raiz: El volumen de dentro de una unidad con vestíbulo (Windows), que
            se desmonta por su letra; sin ella, la raíz del equipo cifrada.
        veracrypt: El VeraCrypt instalado, si ya se sabe; sin él, desatendido
            se pregunta (`penwatch.installed_veracrypt()`).
    """
    exe = (veracrypt or penwatch.installed_veracrypt()) if desatendido \
        else veracrypt_de_la_raiz()
    if exe is None:
        return None
    if IS_WIN:
        letra = str(raiz)[:1] if raiz is not None else unidad.letra or unidad.ruta[:1]
        return [exe, "/dismount", letra, *(["/silent"] if desatendido else []), "/quit"]
    if raiz is not None:
        return None                 # el vestíbulo de una unidad lo cierra su script
    if hay_pantalla() and not desatendido:
        return [exe, "-d", unidad.contenedor]
    return [exe, "--text", "--non-interactive", "-d", unidad.contenedor]


def resultado(rc: int, texto: str) -> str:
    """Devuelve cómo acabó una pasada, con el criterio de `runsync.daemon_cycle()`.

    Args:
        rc: Código de salida de `sync.py`.
        texto: Su salida.
    """
    if rc != 0:
        return RED if moderacion.es_de_red(texto) else FALLO
    if "saltada" in texto.lower():
        return SALTADA
    return OK


@dataclass
class Conexion:
    """Lo que el agente recuerda de una unidad conectada.

    Args:
        id: El id de la unidad (el de su fichero de control).
        raiz: Dónde está montada.
        nombre: Su nombre en la flota.
        desde: Cuándo se la vio por primera vez.
        pregunta: Si no está en la lista, la pregunta en curso.
        hijo: La ventanita de la pregunta.
        respuesta: `AHORA_NO`, para esta conexión.
        lanzada: Modo `ui`: su ventana ya se ha abierto.
        pausa: La última vez que se vio una ventana o un stop.
        lock: El `daemon.lock.json` que tenemos escrito.
        intento_lock: Cuándo se intentó reescribir `lock` tras un fallo, o `None`
            (`_al_dia_el_lock()`).
        soltando: Soltado, pero su fichero sigue sin borrar.
        servicio: Lo que sincroniza su servicio.
        error: Por qué no hay servicio que atender.
        avisado_error: Si ese error ya se ha dicho.
        firma: Los mtimes de lo que decide el servicio.
        motivo: Qué le pasa, para `status`.
        reanudar: «Iniciar servicio» en su ventana (`reanudar` en su buzón): al
            irse la ventana se vuelve enseguida, sin la `GRACIA` que se da a un
            servicio que la ventana arrancara por su cuenta.
        huella: Su huella al conectarla (`huella()`).
        cambiada: La huella no es la que se aceptó: una unidad de la lista con
            otro código se trata como una que no lo está hasta que se vuelva a
            decir que sí.
        vieja: Su versión (o «») si es anterior a `VERSION_MINIMA`: ejecutaría
            el rclone de la unidad, así que no se atiende ni se abre.
        emblema: Su icono para la bandeja (`volumen.emblema()`), o `None` si
            todavía no se ha leído.
        emblema_leido: Cuándo se leyó.
        version: La versión de su programa (`""` si no lleva `VERSION`), o
            `None` si todavía no se ha leído.
        version_leida: Cuándo se leyó.
        actualizacion: Su «Actualizar a la vX», pedido o en marcha.
        a_medias: Una actualización suya no acabó bien y la dejó tocada: no se
            atiende ni se abre hasta que otra acabe.
        confiada: Si su código era el aceptado cuando se pidió la primera
            actualización de esta conexión (`None`, si no se ha pedido ninguna):
            solo entonces la huella que deje se apunta como aceptada.
        version_avisada: La versión suya de la que ya se dijo que el agente
            la puede poner al día.
        llavero: Si lleva llavero (`[keychain]`), o `None` si todavía no se
            ha mirado.
        llavero_leido: Cuándo se miró.
        copias: Las copias de conflicto de su llavero, rutas relativas a la
            raíz (`_copias_del_llavero()`).
        copias_leidas: Cuándo se miraron.
        copias_avisadas: Las que ya se han avisado en esta conexión.
        compatible: Si es un volumen que se puede expulsar
            (`expulsar.compatible()`), o `None` si todavía no se ha mirado.
        compatible_leido: Cuándo se miró.
        ventana: Si en la última vuelta tenía su ventana de runsync abierta: al
            abrirse, la raíz cuenta como usada (`Agente.usadas`).
    """
    id: str
    raiz: Path
    nombre: str
    desde: float
    pregunta: pl.Pregunta | None = None
    hijo: Any = None
    respuesta: str | None = None
    lanzada: bool = False
    pausa: float | None = None
    lock: dict | None = None
    intento_lock: float | None = None
    soltando: bool = False
    servicio: Servicio | None = None
    error: str | None = None
    avisado_error: bool = False
    firma: tuple = ()
    motivo: str = ""
    reanudar: bool = False
    huella: str | None = None
    cambiada: bool = False
    vieja: str | None = None
    emblema: dict | None = None
    emblema_leido: float = -math.inf
    version: str | None = None
    version_leida: float = -math.inf
    actualizacion: Actualizacion | None = None
    a_medias: bool = False
    confiada: bool | None = None
    version_avisada: str | None = None
    llavero: bool | None = None
    llavero_leido: float = -math.inf
    copias: tuple[str, ...] = ()
    copias_leidas: float = -math.inf
    copias_avisadas: frozenset[str] = frozenset()
    compatible: bool | None = None
    compatible_leido: float = -math.inf
    vista: dict | None = None
    ventana: bool = False
    con_partes: bool = False
    leidos: dict = field(default_factory=dict)
    config_visto: int | None = None
    config_mirado: float = -math.inf


@dataclass
class Expulsion:
    """«Expulsar» de una unidad, pedido y todavía no acabado.

    Args:
        desde: Cuándo se pidió.
        lanzada: Cuándo se lanzó la expulsión (en un hilo), o `None` mientras
            espera a que nada lo impida.
        resultado: Cómo acabó, o `None` si sigue en marcha. Lo escribe el hilo
            y lo lee el agente.
        avisada: Si ya se ha dicho cómo acabó.
        subir: Las parejas que se pasan antes de soltar la unidad y todavía no
            han acabado (`Agente._por_subir()`).
        sin_subir: Las que no ha dado tiempo a pasar, o han fallado: se dicen
            con el resultado.
    """
    desde: float
    lanzada: float | None = None
    resultado: expulsar.Resultado | None = None
    avisada: bool = False
    subir: list[str] = field(default_factory=list)
    sin_subir: list[str] = field(default_factory=list)


@dataclass
class Actualizacion:
    """«Actualizar a la vX» de una raíz: ponerle el código de la versión del agente.

    Args:
        desde: Cuándo se pidió.
        proc: El `agente.py actualizar-raiz` en marcha; `None` mientras espera
            a que acabe la pareja en curso de esa raíz.
    """
    desde: float
    proc: Any = None


@dataclass
class Desbloqueo:
    """«Desbloquear», lanzado: VeraCrypt está pidiendo la contraseña.

    Args:
        desde: Cuándo se lanzó.
        proc: El VeraCrypt que monta.
        salio: Cuándo se vio que había salido.
        abrir: Abrir su ventana en cuanto se vea abierta.
        copia: La copia elevada que puede seguir tras él.
        explorar: Abrirla en el explorador de archivos en cuanto se vea
            abierta.
    """
    desde: float
    proc: Any = None
    salio: float | None = None
    abrir: bool = False
    copia: Copia | None = None
    explorar: bool = False


@dataclass
class AlAbrirse:
    """Lo que se ha pedido de una unidad bloqueada para cuando se vea abierta.

    Es «Abrir su carpeta» o «Abrir su ventana» (un atajo) sobre una unidad de
    la lista bloqueada con BitLocker o con el contenedor de VeraCrypt cerrado:
    se pide su contraseña y, al conectarse, se abre. Lo mismo de la raíz cifrada
    de este equipo va en su `Desbloqueo`.

    Args:
        desde: Cuándo se pidió por última vez; pasado `ESPERA_ABRIR` sin
            abrirse, se olvida.
        abrir: Abrir su ventana.
        explorar: Abrirla en el explorador de archivos.
    """
    desde: float
    abrir: bool = False
    explorar: bool = False


@dataclass
class Bloqueo:
    """«Bloquear», pedido y todavía no hecho.

    Args:
        desde: Cuándo se pidió.
        proc: El VeraCrypt que desmonta, ya lanzado.
        lanzado: Cuándo se lanzó.
        copia: La copia elevada que puede seguir tras él.
        llavero: El `runsync.py --cerrar-llavero` de la raíz, si lleva
            llavero: va antes que VeraCrypt.
        llavero_desde: Cuándo se lanzó.
        llavero_cerrado: Si ya acabó bien.
        por: El evento de la sesión de Windows que lo pidió
            (`equipo.EVENTO_BLOQUEO`, `EVENTO_SUSPENSION`), o vacío si lo pidió
            una persona. Con él no hay nadie delante: VeraCrypt va desatendido
            (`orden_bloquear(desatendido=True)`), no se espera a la ventana de
            la raíz y lo que no se pudo se dice al volver (`Agente.sin_bloquear`).
        fisica: La raíz física de una unidad con vestíbulo (su marca y su
            `.hc`); `None` en la raíz del equipo cifrada.
        raiz: Donde está montado el volumen de dentro de esa unidad.
    """
    desde: float
    proc: Any = None
    lanzado: float = 0.0
    copia: Copia | None = None
    llavero: Any = None
    llavero_desde: float = 0.0
    llavero_cerrado: bool = False
    por: str = ""
    fisica: Path | None = None
    raiz: Path | None = None


@dataclass(frozen=True)
class Copia:
    """Los VeraCrypt que ya había antes de lanzar el nuestro, por nombre.

    VeraCrypt sin su driver instalado y sin administrador (el portable del
    agente) se relanza elevado (`/q UAC`) y el proceso que lanzamos sale con 0
    a los dos segundos (`InitApp`, `LaunchElevatedProcess` en
    `Common/Dlgcode.c`), mientras la copia elevada sigue: pide la contraseña o
    pregunta si forzar el desmontaje. Esa copia es la misma imagen, así que se
    la reconoce por el nombre y por no estar antes, como hacen
    `crypto._esperar_copia_elevada()` y `:vc_pendiente` del vestíbulo. Sin
    esto, un «Desbloquear» se daría por cancelado con la persona todavía en el
    aviso de UAC, y un «Bloquear», por fallido mientras VeraCrypt pregunta.

    Args:
        imagen: Nombre del ejecutable.
        antes: Los pid con esa imagen antes de lanzar el nuestro.
    """
    imagen: str
    antes: frozenset[int]

    @staticmethod
    def antes_de(cmd: list[str]) -> Copia:
        """Anota los procesos que hay con la imagen de `cmd[0]` antes de lanzarlo.

        En Linux no hay copia (el que lanzamos es el que pregunta) y
        `procesos()` no ve nada: la copia no sigue nunca.
        """
        imagen = Path(cmd[0]).name
        return Copia(imagen, frozenset(procesos(imagen)))

    def sigue(self) -> bool:
        """Indica si hay un proceso nuevo con esa imagen."""
        return bool(procesos(self.imagen) - self.antes)


def _sigue_vivo(proc: Any, copia: Copia | None) -> bool:
    """Indica si VeraCrypt sigue en ello: el proceso lanzado o su copia elevada."""
    if proc is not None and proc.poll() is None:
        return True
    return copia is not None and copia.sigue()


@dataclass
class Pasada:
    """Una pasada en marcha: el `sync.py` hijo de una pareja.

    Args:
        proc: El proceso hijo.
        tarea: Lo que se está sincronizando.
        desde: Cuándo empezó.
        salida: Fichero temporal donde va su salida.
        nombre: Nombre de la unidad a la que pertenece.
        otras: Las demás parejas de la misma raíz que pasa ese mismo proceso,
            detrás de la de `tarea` (`Agente._acompanan()`).
    """
    proc: Any
    tarea: pl.Tarea
    desde: float
    salida: Path
    nombre: str
    otras: tuple[pl.Tarea, ...] = ()

    @property
    def tareas(self) -> tuple[pl.Tarea, ...]:
        """Devuelve todo lo que pasa este proceso, en orden."""
        return (self.tarea, *self.otras)

    @property
    def claves(self) -> set[tuple[str, str]]:
        """Devuelve las parejas que pasa este proceso, como `(raíz, pareja)`; ninguna si es una sonda."""
        return {(t.raiz, t.pareja) for t in self.tareas if t.tipo == pl.PASADA}


class Sospecha(NamedTuple):
    """Un fallo que parece de red y espera a la sonda de su remoto.

    Args:
        remoto: El remoto de la pareja, que es el que se sondea.
        antes: La marca de la pareja antes de aquella pasada: la que, si el
            remoto contesta, pasa a contar el fallo.
        tras: La marca que dejó registrarla como `RED`. Si ya no es esa, la
            pareja ha hecho otra cosa desde entonces y el fallo ya no se
            discute.
    """
    remoto: str
    antes: pl.Marca
    tras: pl.Marca


class Mirar(NamedTuple):
    """Una carpeta que toca mirar en un muestreo.

    Args:
        clave: `(raíz, pareja)`.
        con: La conexión de la raíz cuando se pidió: si al recoger la foto ya
            no es esa, la unidad se fue (o se fue y volvió) y la foto no vale.
        raiz: Dónde estaba montada la raíz.
        carpeta: La carpeta local de la pareja, sin resolver.
        armar: Si en vez de tomar su foto hay que ponerle (o rehacerle) la
            vigilancia de los avisos del sistema.
        excluidos: Los ficheros que la pareja excluye por su nombre
            (`Servicio.excluidos`): no se miran, estén donde estén.
    """
    clave: tuple[str, str]
    con: Conexion
    raiz: Path
    carpeta: Path
    armar: bool = False
    excluidos: tuple[str, ...] = ()


class Muestreo:
    """Una vuelta a las carpetas vigiladas, corriendo en su propio hilo.

    Recorrer una carpeta de un pendrive o de la red puede llevar segundos, y la
    vuelta del agente (la cola, la bandeja, los buzones) no puede esperar a
    ella: el hilo toma las fotos, o pone las vigilancias de los avisos del
    sistema (que también recorre las carpetas), y lo deja aquí; la vuelta
    siguiente lo recoge. Solo hay un muestreo a la vez. El hilo escribe y el
    del agente lee; `hecho` se pone el último, así que quien lo ve a `True` ya
    tiene el resto.

    Args:
        trabajo: Las carpetas que hay que mirar.
        tope: Cuántas entradas se cuentan como mucho en cada una.
        ignorar: Patrones de las entradas de la raíz de cada carpeta que no se
            miran; en la raíz de la unidad se suma `ruido_en()`.
        avisos: El motor de avisos del agente, para las carpetas con `armar`.

    Attributes:
        fotos: La foto de cada pareja, o `None` si no se pudo tomar.
        armadas: Lo que dijo el motor al ponerle la vigilancia a cada pareja:
            `None` si se vigila, o por qué no.
        fuera: Las parejas cuya carpeta, con los enlaces resueltos, queda fuera
            de su raíz: no se mira.
        descartar: Las parejas cuya pasada ha empezado o acabado mientras se
            miraba. Su foto es de antes o de a medias y no cuenta.
        hecho: Si ya ha terminado.
    """

    def __init__(self, trabajo: list[Mirar], tope: int, ignorar: tuple[str, ...],
                 avisos: Any = None) -> None:
        """Prepara el muestreo sin correrlo."""
        self.trabajo = trabajo
        self.tope = tope
        self.ignorar = ignorar
        self.avisos = avisos
        self.fotos: dict[tuple[str, str], pl.Huella | None] = {}
        self.armadas: dict[tuple[str, str], str | None] = {}
        self.fuera: set[tuple[str, str]] = set()
        self.descartar: set[tuple[str, str]] = set()
        self.hecho = False

    def correr(self) -> None:
        """Toma la foto de cada carpeta, o le pone la vigilancia; es lo que corre el hilo.

        Una carpeta que no se deja mirar (cualquier error) queda sin foto: es
        «no sé», no un cambio, y el hilo no se cae. Una vigilancia que falla
        de cualquier modo es una carpeta que se recorrerá.
        """
        try:
            for mirar in self.trabajo:
                if en_la_raiz(mirar.raiz, mirar.carpeta) is None:
                    self.fuera.add(mirar.clave)
                    continue
                ignorar = (self.ignorar + ruido_en(mirar.raiz, mirar.carpeta)
                           + ruido_de_editor(mirar.clave[1])
                           + tuple(huellas.EXACTO + p for p in mirar.excluidos))
                if mirar.armar:
                    try:
                        self.armadas[mirar.clave] = self.avisos.vigilar(
                            mirar.clave, mirar.carpeta, ignorar)
                    except Exception as e:          # noqa: BLE001
                        self.armadas[mirar.clave] = f"no se ha podido vigilar: {e}"
                    continue
                try:
                    self.fotos[mirar.clave] = huella_local(mirar.carpeta, self.tope, ignorar)
                except Exception:                   # noqa: BLE001
                    self.fotos[mirar.clave] = None
        finally:
            self.hecho = True


@dataclass
class Agente:
    """Lo que el agente recuerda y decide, vuelta a vuelta.

    Args:
        reloj: La hora, en segundos; los tests la sustituyen.
        ajustes: Su configuración (`agente.json`).
        conexiones: Las unidades conectadas y contadas, por id.
        vistas: Las unidades abiertas que se han visto y cuántas veces seguidas
            (hasta `ESTABLE`).
        cerradas: Lo mismo para las VeraCrypt cerradas, por la marca de su
            vestíbulo.
        vestibulos: Los vestíbulos ya tratados en esta conexión, por id: su
            raíz física, o `""` si ya se abrió y todavía no se ha visto la
            entrada.
        marcas: El estado de cada pareja para el planificador, por `(raíz,
            pareja)`.
        saltadas: Las parejas cuya última pasada se saltó por pedir un
            `--resync`, por `(raíz, pareja)`: se avisa al entrar, una vez.
        entorno: Batería, red de uso medido, remotos sin conexión y pausa, para
            el planificador.
        entorno_leido: Cuándo se leyó el entorno por última vez; con menos
            infinito se lee entero en la vuelta siguiente.
        red_leida: Cuándo se preguntó por última vez si la red es de uso medido.
        pasada: La pasada en marcha, si la hay.
        heredada: La de un agente anterior que sigue viva al arrancar
            (`pasada.json`).
        cortada: La pasada que el instalador cortó al parar al agente anterior:
            su pareja espera a que caduque el `.lck` que dejó
            (`equipo.ESPERA_TRAS_CORTE`).
        urgentes: Las parejas pedidas con «Sincronizar ahora», como `(raíz,
            pareja)`.
        pausado: Si se ha pedido pausa.
        terminar: Si se ha pedido parar.
        sospechas: Los fallos que parecen de red y esperan a la sonda de su
            remoto, por `(raíz, pareja)`: uno por pareja, para que el segundo
            fallo de otra pareja del mismo remoto no pise al primero.
        sin_red_avisado: Los `(raíz, remoto)` sin conexión ya avisados.
        retenido: Por qué no se lanza nada ahora, para no repetirlo en el
            diario.
        rafaga_hasta: Hasta cuándo se recorre en cada vuelta.
        proximo_recorrido: Cuándo toca recorrer aunque nadie avise de un
            montaje; lo deja dicho cada recorrido (`cada_recorrido()`).
        despertado: La última vuelta de la suspensión apuntada.
        ultimo_estado: Lo último que se escribió en `estado.json`.
        ultima_vista: La última `bandeja.Vista` puesta.
        ultima_buena: Cuándo acabó bien la última pasada (el reloj).
        ausentes: Las raíces del equipo que no están donde dice su `ruta`, ya
            avisadas.
        desbloqueos: Los «Desbloquear» lanzados, por id de la raíz cifrada.
        pedidas: Las raíces cifradas cuya contraseña ya se pidió al iniciar
            sesión.
        bloqueos: Los «Bloquear» en marcha.
        expulsiones: Los «Expulsar» en marcha, por id de la unidad.
        fantasmas: Los volúmenes fantasma ya dichos.
        fantasmas_extraibles: Los ids de unidades extraíbles cifradas cuyo
            fantasma ya se ha dicho en esta conexión (`_fantasmas_extraibles()`).
        bitlocker: Las unidades de la lista que el último recorrido vio
            enchufadas y bloqueadas con BitLocker, con su raíz, por id.
        desbloqueos_bitlocker: La ventana de desbloqueo de Windows pedida para
            cada una de esas (su proceso), por id.
        con_vestibulo: Las unidades cuya marca de vestíbulo vio el último
            recorrido, con el contenedor cerrado o abierto, con su raíz física
            (la de la marca y el `.hc`), por id: son las de VeraCrypt
            (`_cifrado_de()`), y la raíz física es la que dice si su
            contenedor se ha cerrado (`bloqueada_unidad()`).
        vestibulos_pedidos: Cuándo se le pidió a VeraCrypt por última vez que
            abriera el contenedor de cada unidad cerrada, por id: un atajo no
            lo vuelve a pedir durante `GRACIA_ABRIR`.
        al_abrirse: Lo que se abre de cada unidad bloqueada en cuanto se
            conecte (un atajo con ella bloqueada), por id.
        bloqueadas_desde: Desde cuándo se ve enchufada y bloqueada cada unidad
            de la lista (BitLocker, o VeraCrypt con el contenedor cerrado), por
            id: para un atajo cuenta como cuándo se conectó.
        bitlocker_presentes: Las unidades de la lista con BitLocker cuyo
            volumen está enchufado según el último recorrido, bloqueadas o no.
        bitlocker_tratadas: Las unidades con BitLocker que ya tuvieron su
            decisión de «Pedir la contraseña al conectarla» en esta conexión
            (`_pedir_bitlocker()`): salga la ventana o no, no se vuelve a
            decidir hasta que se desenchufen.
        recorridos: Los recorridos hechos desde que arrancó.
        sin_rclone_avisado: Si ya se dijo que el agente no tiene rclone.
        peticiones: Lo que pide la bandeja, que corre en otro hilo: los mismos
            diccionarios que el buzón, sin pasar por disco.
        bandeja: La bandeja, si la hay (`poner(vista)`), para enseñarle el
            estado.
        inicio: Cuándo arrancó, en hora de verdad (`equipo.pedir()` sella con
            ella): un «parar» de antes iba para el agente anterior.
        version: La de este agente.
        nueva: La más nueva que se sabe (su tag), o `None`.
        version_mirada: Cuándo se miró.
        nueva_avisada: La que ya se avisó.
        actualizando: El `agente.py actualizar` en marcha.
        buscando: Si hay un «Buscar actualizaciones» preguntando a GitHub.
        avisos_de_red: Lo que oye los cambios de red (`red.AvisosDeRed`), si
            lo hay: con él, un remoto sin conexión se sondea cuando vuelve la
            red y el temporizador es solo el respaldo largo.
        cambio_de_red: La ráfaga de avisos de red que todavía no se ha
            sondeado (`pl.CambioDeRed`).
        cambios: Las reglas de los cambios locales (`watch = true`).
        vigiladas: Lo que se recuerda de cada pareja que pide `watch`, por
            `(raíz, pareja)`; se olvida al irse la raíz.
        muestreo: El muestreo de carpetas en marcha, si lo hay.
        avisos_carpeta: El motor de los avisos del sistema de las carpetas
            vigiladas (`avisos_carpeta.Inotify`), si lo hay: con él una pareja
            vigilada no se recorre.
        sin_avisos: Las parejas vigiladas que se recorren aunque haya motor, y
            por qué (de red, sin sitio, se perdió la vigilancia); se olvida al
            dejar de servirlas.
        rearmar: Las parejas cuya vigilancia hay que rehacer (se movió una
            carpeta o se perdieron avisos).
        rearmes: De cada pareja que perdió los avisos del sistema, cuántas
            veces se ha intentado volver a oírlos en esta conexión y cuándo se
            perdieron (o se intentó) por última vez.
        keepassxc: Las raíces atendidas con su KeePassXC abierto en este
            equipo, por id (`_mirar_keepassxc()`).
        keepassxc_mirado: Cuándo se miró.
        navegador_mirado: Si ya se han mirado, al arrancar, las claves del
            navegador que dejó una unidad quitada sin expulsar.
        letras_vistas: Las letras de unidad que vio el último recorrido, o
            `None` antes del primero: una que aparece de nuevo hace limpiar el
            nombre y el icono que quedaban de otra unidad en ella
            (`_limpiar_letras()`).
        poner_motor: Crea lo que pone los atajos de teclado en este sistema
            (`poner_atajos()`), o `None` sin bandeja ni vigía (los tests).
        atajos_motor: Lo que pone los atajos (`poner(combos)`, `cerrar()`,
            `nombre`, `suspende`), una vez creado; `None` si no se puede.
        atajos_reintento: Cuándo (`reloj`) se puede volver a intentar crearlo
            tras no haber podido; `None` mientras no se haya intentado, e
            infinito si no hay remedio (sin escritorio). Se intenta la primera
            vez que hace falta, no al arrancar, así que sin atajos no se
            conecta a nada.
        atajos_fallos: Los intentos seguidos que han fallado.
        atajos_motivo: Por qué no hay atajos en este equipo, si no los hay.
        atajos_hechos: Lo que contesta el motor desde su hilo, `(combos,
            rechazados)`: se recoge en cada vuelta.
        atajos_pedidos: Lo último pedido al motor, por acción, o `None` si nada.
        atajos_en_vuelo: Cuándo se le pidió, mientras no conteste.
        atajos_vencida: Si lo último pedido lleva `ESPERA_ATAJOS` sin respuesta:
            ya se dio por no puesto, pero su respuesta, si llega, se acepta.
        atajos_errores: Por qué el sistema no ha dejado poner cada atajo, por
            acción: lo que enseñan la bandeja y la ventana.
        atajos_avisados: Las `(acción, combinación)` rechazadas ya avisadas.
        atajos_prueba: Un «Guardar» que se está probando con el sistema:
            `(vez, combos, rechazados al validarlos)`.
        atajos_respuesta: Lo último contestado a un «Guardar» (`vez`,
            `rechazados`, `guardados`), para la ventana que espera.
        ventana_atajos: La ventana que graba los atajos, mientras está abierta.
        usadas: Cuándo se usó por última vez cada raíz, por id: su ventana se
            abrió, o se pidió algo de ella (conectada, o a la vista y
            bloqueada) desde la bandeja, su ventana o un atajo. Es lo que
            decide sobre qué unidad actúa un atajo.
        sin_bloquear: Las raíces que un evento de la sesión pidió bloquear y
            no se han podido, con el evento y el motivo, por id: se dicen una
            vez, al volver la persona (`_decir_sin_bloquear()`).
        sesion_bloqueada: Si la bandeja ha dicho que la sesión de Windows está
            bloqueada y todavía no que se ha desbloqueado.
        suspendido: Si la bandeja ha dicho que el equipo se suspende y todavía
            no que ha vuelto.
        al_salir: Las órdenes de VeraCrypt que se lanzan si Windows cierra la
            sesión o se apaga (`lanzar_al_salir()`), preparadas en cada vuelta
            para no hacer nada más en ese momento. Se sustituye entera: la lee
            el hilo de la bandeja.
        veracrypt_instalado: El VeraCrypt instalado en este equipo, el único
            con el que se bloquea sin nadie delante, o `None`.
        veracrypt_mirado: Cuándo se miró (`MIRAR_EMBLEMA`).
    """
    reloj: Any = time.time
    ajustes: equipo.Ajustes = field(default_factory=equipo.leer_ajustes)
    conexiones: dict[str, Conexion] = field(default_factory=dict)
    vistas: dict[str, int] = field(default_factory=dict)
    cerradas: dict[str, int] = field(default_factory=dict)
    vestibulos: dict[str, str] = field(default_factory=dict)
    marcas: dict[tuple[str, str], pl.Marca] = field(default_factory=dict)
    saltadas: set[tuple[str, str]] = field(default_factory=set)
    entorno: pl.Entorno = field(default_factory=pl.Entorno)
    entorno_leido: float = -math.inf
    red_leida: float = -math.inf
    pasada: Pasada | None = None
    heredada: dict | None = field(default_factory=equipo.pasada_viva)
    cortada: dict | None = field(default_factory=equipo.pasada_cortada)
    urgentes: list[tuple[str, str]] = field(default_factory=list)
    pausado: bool = False
    terminar: bool = False
    sospechas: dict[tuple[str, str], Sospecha] = field(default_factory=dict)
    sin_red_avisado: set[tuple[str, str]] = field(default_factory=set)
    retenido: str | None = None
    rafaga_hasta: float = -math.inf
    proximo_recorrido: float = -math.inf
    despertado: float = -math.inf
    ultimo_estado: dict | None = None
    ultima_vista: Any = None
    ultima_buena: float | None = None
    ausentes: set[str] = field(default_factory=set)
    desbloqueos: dict[str, Desbloqueo] = field(default_factory=dict)
    pedidas: set[str] = field(default_factory=set)
    bloqueos: dict[str, Bloqueo] = field(default_factory=dict)
    expulsiones: dict[str, Expulsion] = field(default_factory=dict)
    fantasmas: set[str] = field(default_factory=set)
    fantasmas_extraibles: set[str] = field(default_factory=set)
    bitlocker: dict[str, Path] = field(default_factory=dict)
    desbloqueos_bitlocker: dict[str, Any] = field(default_factory=dict)
    con_vestibulo: dict[str, Path] = field(default_factory=dict)
    vestibulos_pedidos: dict[str, float] = field(default_factory=dict)
    al_abrirse: dict[str, AlAbrirse] = field(default_factory=dict)
    bloqueadas_desde: dict[str, float] = field(default_factory=dict)
    bitlocker_presentes: set[str] = field(default_factory=set)
    bitlocker_tratadas: set[str] = field(default_factory=set)
    recorridos: int = 0
    sin_rclone_avisado: bool = False
    peticiones: Any = field(default_factory=queue.SimpleQueue)
    bandeja: Any = None
    inicio: float = field(default_factory=time.time)
    version: str = field(default_factory=lambda: update.installed_version(SCRIPT_DIR))
    nueva: str | None = None
    version_mirada: float = -math.inf
    nueva_avisada: str | None = None
    actualizando: Any = None
    buscando: bool = False
    avisos_de_red: Any = None
    cambio_de_red: pl.CambioDeRed | None = None
    cambios: pl.PoliticaCambios = field(default_factory=pl.PoliticaCambios)
    vigiladas: dict[tuple[str, str], pl.Vigilada] = field(default_factory=dict)
    muestreo: Muestreo | None = None
    avisos_carpeta: Any = None
    sin_avisos: dict[tuple[str, str], str] = field(default_factory=dict)
    rearmar: set[tuple[str, str]] = field(default_factory=set)
    rearmes: dict[tuple[str, str], tuple[int, float]] = field(default_factory=dict)
    keepassxc: set[str] = field(default_factory=set)
    keepassxc_mirado: float = -math.inf
    oye_buzon: bool = False
    letras: int | None = None
    navegador_mirado: bool = False
    letras_vistas: set[str] | None = None
    navegador_tras_cierre: dict[str, tuple[str, Path]] = field(default_factory=dict)
    poner_motor: Any = None
    atajos_motor: Any = None
    atajos_reintento: float | None = None
    atajos_fallos: int = 0
    atajos_motivo: str = ""
    atajos_hechos: Any = field(default_factory=queue.SimpleQueue)
    atajos_pedidos: dict[str, str] | None = None
    atajos_en_vuelo: float | None = None
    atajos_vencida: bool = False
    atajos_errores: dict[str, str] = field(default_factory=dict)
    atajos_avisados: set[tuple[str, str]] = field(default_factory=set)
    atajos_prueba: tuple[str, dict[str, str], dict[str, str]] | None = None
    atajos_respuesta: dict | None = None
    ventana_atajos: Any = None
    usadas: dict[str, float] = field(default_factory=dict)
    sin_bloquear: dict[str, tuple[str, str]] = field(default_factory=dict)
    sesion_bloqueada: bool = False
    suspendido: bool = False
    al_salir: tuple[list[str], ...] = ()
    veracrypt_instalado: str | None = None
    veracrypt_mirado: float = -math.inf

    def vuelta(self, recorrer: bool = True) -> pl.Decision | None:
        """Hace una vuelta del agente y devuelve lo que decidió lanzar, si algo.

        Lee los buzones, recorre los volúmenes, gestiona las conexiones
        (preguntas, fin de pasada, bloqueos, el contrato con el servicio de
        cada raíz, sus actualizaciones), lee el entorno, mira si hay versión nueva, mira los cambios
        locales de las parejas con `watch = true` y, si no hay una pasada en
        marcha, decide la siguiente. Termina escribiendo el estado.

        Args:
            recorrer: Si en esta vuelta toca recorrer los volúmenes.

        Returns:
            La decisión del planificador, o `None`.
        """
        ahora = self.reloj()
        if not self.navegador_mirado:
            # Las de una unidad que se fue mientras el agente no estaba.
            self.navegador_mirado = True
            self._limpiar_navegador("al arrancar")
            self._limpiar_letras("al arrancar")
        self._buzon(ahora)
        if recorrer:
            self._recorrer(ahora)
            self._al_iniciar(ahora)
        self._seguir_desbloqueos(ahora)
        for con in list(self.conexiones.values()):
            # La única mirada de esta vuelta al `state/` de cada raíz: dice si
            # sigue ahí y qué ha cambiado de su contrato.
            con.vista = mirar_estado(con.raiz)
            if con.vista is None:
                self._desconectar(con.id, ahora, {})
        self._tras_cierre()
        self._preguntas(ahora)
        self._fin_de_pasada(ahora)
        self._cambios_de_red(ahora)
        self._buzones_de_raices(ahora)
        self._bloqueos(ahora)
        self._expulsiones(ahora)
        for con in self.conexiones.values():
            self._contrato(con, ahora)
            self._copias_del_llavero(con, ahora)
        self._actualizaciones(ahora)
        self._leer_entorno(ahora)
        self._mirar_version(ahora)
        self._mirar_keepassxc(ahora)
        self._vigilar(ahora)
        self._atajos(ahora)
        decision = None
        if self.pasada is None and not self.terminar and not self._heredada():
            decision = self._decidir(ahora)
        self._preparar_al_salir()           # tras lanzar: una pasada recién lanzada cuenta
        self._escribir_estado()
        for con in self.conexiones.values():
            con.vista = None                # la mirada vale para esta vuelta, no para la siguiente
        return decision

    def _recorrer(self, ahora: float) -> None:
        """Recorre las unidades y pone al día conexiones, vestíbulos y raíces ausentes.

        Una unidad cuenta cuando se ha visto `ESTABLE` veces seguidas. Las
        abiertas se reconocen por su fichero de control y las de VeraCrypt
        cerradas por la marca de su vestíbulo.
        """
        # Por si el recorrido se quedara a medias: el siguiente, al ritmo de antes.
        self.proximo_recorrido = ahora + self.cada_recorrido()
        abiertas: dict[str, Path] = {}
        cerradas: dict[str, Path] = {}
        resto: list[Path] = []
        # Las raíces del equipo, primero y por su ruta: son carpetas, no
        # volúmenes, y el recorrido no las vería. Van como las raíces extra de
        # penwatch: el recorrido sigue siendo uno.
        propias = [u.ruta for u in self.ajustes.raices.values()]
        letras: set[str] = set()
        for raiz in penwatch.candidate_roots(
                {"extra_roots": propias + list(self.ajustes.extra_roots)}):
            letra = explorador.letra_de(raiz)
            if letra is not None:
                letras.add(letra)
            try:
                if (raiz / penwatch.CONTROL_FILE).is_file():
                    if not (raiz / penwatch.STRUCT_MARKER).is_file():
                        continue
                    uid = penwatch.control_id(raiz)
                    if uid:
                        abiertas.setdefault(uid, raiz)
                elif ((raiz / penwatch.VESTIBULE_MARKER).is_file()
                      and (raiz / penwatch.CONTAINER_FILE).is_file()):
                    uid = penwatch.vestibule_id(raiz)
                    if uid:
                        cerradas.setdefault(uid, raiz)
                else:
                    resto.append(raiz)
            except OSError:
                resto.append(raiz)  # un volumen bloqueado contesta con error: ahora no
        if self.letras_vistas is not None and letras - self.letras_vistas:
            # Una letra que no estaba: la puede haber tomado una unidad a la que
            # le quedaría el nombre y el icono de otra. La primera vez ya se
            # limpió al arrancar.
            self._limpiar_letras("letra nueva")
        self.letras_vistas = letras
        self._fantasmas(abiertas)
        self._fantasmas_extraibles(abiertas, cerradas)
        self.con_vestibulo = dict(cerradas)

        for uid in list(self.vistas):
            if uid not in abiertas:
                del self.vistas[uid]
        for uid, raiz in abiertas.items():
            con = self.conexiones.get(uid)
            if con is not None:
                con.raiz = raiz                 # remontada en otra letra
                continue
            self.vistas[uid] = self.vistas.get(uid, 0) + 1
            if self.vistas[uid] >= ESTABLE:
                del self.vistas[uid]
                self._conectar(uid, raiz, ahora)
            else:
                self.rafaga_hasta = max(self.rafaga_hasta, ahora + 3 * TICK)
        for uid in list(self.conexiones):
            if uid not in abiertas:
                self._desconectar(uid, ahora, cerradas)
        self._vestibulos(cerradas, ahora)
        self._raices_ausentes(abiertas)
        self._mirar_bitlocker(resto)
        self._pedir_bitlocker(ahora)
        bloqueadas = set(self.bitlocker) | {uid for uid in self.vestibulos
                                            if self._cerrada_veracrypt(uid) is not None}
        self.bloqueadas_desde = {uid: self.bloqueadas_desde.get(uid, ahora) for uid in bloqueadas}
        # Con lo que se acaba de ver: una unidad bloqueada con BitLocker lo acorta.
        self.proximo_recorrido = ahora + self.cada_recorrido()
        self.recorridos += 1

    def _mirar_bitlocker(self, resto: list[Path]) -> None:
        """Apunta qué unidades de la lista están enchufadas y bloqueadas con BitLocker.

        Un volumen bloqueado no enseña nada de lo que lleva dentro: se reconoce
        por el nombre de volumen que se apuntó la última vez que se atendió
        (`_apuntar_volumen()`), y solo cuenta si Windows dice que está
        bloqueado. De la unidad no se lee ni se ejecuta nada, así que basta
        verla una vez. Sin ninguna unidad con volumen apuntado (fuera de
        Windows, siempre) no se pregunta nada de ninguna letra.

        Args:
            resto: Las raíces del recorrido que no han dado ni fichero de
                control ni vestíbulo, o que han contestado con un error.
        """
        conocidas = {u.volumen: uid for uid, u in self.ajustes.unidades.items()
                     if u.volumen and not u.es_raiz and u.modo != equipo.NADA
                     and uid not in self.conexiones}
        vistas: dict[str, Path] = {}
        presentes: set[str] = set()
        for raiz in resto if conocidas else ():
            uid = conocidas.get(bitlocker.volumen_de(raiz))
            if uid is None:
                continue
            presentes.add(uid)
            if uid in vistas:
                continue
            if cifrada.bitlocker_de(raiz).locked:
                vistas[uid] = raiz
        self.bitlocker_presentes = presentes
        for uid, raiz in vistas.items():
            if uid not in self.bitlocker:
                diario(f"{nombre_guardado(self.ajustes.unidades[uid], uid)}: bloqueada con "
                       f"BitLocker en {raiz}")
        # La ventana de Windows de una que ya no está bloqueada (se abrió o se
        # quitó) se olvida, sin cerrarla: es de Windows.
        for uid in list(self.desbloqueos_bitlocker):
            if uid not in vistas:
                del self.desbloqueos_bitlocker[uid]
        self.bitlocker = vistas

    def _cifrado_de(self, uid: str) -> str:
        """Devuelve cómo va cifrada una unidad de la lista, o una cadena vacía.

        VeraCrypt si su marca de vestíbulo está a la vista (el contenedor,
        abierto o cerrado, vive en una unidad que se ve); BitLocker si lleva
        el volumen apuntado (`Unidad.volumen`). Es lo que decide si tiene
        sentido enseñar su «Pedir la contraseña al conectarla». Una raíz del
        equipo no lleva ese ajuste (el suyo es `pedir_al_iniciar`).

        Returns:
            `equipo.CIFRADO_VERACRYPT`, `equipo.CIFRADO_BITLOCKER` o `""`.
        """
        unidad = self.ajustes.unidades.get(uid)
        if unidad is None or unidad.es_raiz:
            return ""
        if uid in self.con_vestibulo:
            return equipo.CIFRADO_VERACRYPT
        return equipo.CIFRADO_BITLOCKER if unidad.volumen else ""

    def _pide_al_conectar(self, uid: str) -> bool:
        """Indica si el agente pide la contraseña de esa unidad al conectarla (el valor de verdad)."""
        unidad = self.ajustes.unidades.get(uid)
        return unidad is not None and unidad.pide_al_conectar(self._cifrado_de(uid))

    def _pedir_bitlocker(self, ahora: float) -> None:
        """Pide la ventana de Windows de las unidades con BitLocker que lo piden al conectarlas.

        Es el «Pedir la contraseña al conectarla» de una unidad con BitLocker
        (`Unidad.pide_al_conectar()`, que sin decir nada es que no). La
        decisión se toma una sola vez por conexión, con el valor del primer
        recorrido que la ve enchufada y bloqueada (también al iniciar sesión,
        porque el agente arranca sin nada visto): salga la ventana o no, no se
        vuelve a decidir hasta que se desenchufe, así que si se cancela no se
        insiste, y encenderlo con ella ya vista vale desde la siguiente
        conexión. Una unidad que se conectó y vuelve bloqueada con la unidad
        puesta (`_desconectar()`) cuenta como la misma conexión. Es una ventana
        del sistema y no un aviso: no depende de la moderación.

        Args:
            ahora: La hora del reloj del agente.
        """
        self.bitlocker_tratadas &= (set(self.bitlocker) | self.bitlocker_presentes
                                    | set(self.conexiones))
        for uid in sorted(self.bitlocker):
            if uid in self.bitlocker_tratadas:
                continue
            self.bitlocker_tratadas.add(uid)
            unidad = self.ajustes.unidades.get(uid)
            if unidad is None or not unidad.pide_al_conectar(equipo.CIFRADO_BITLOCKER):
                continue
            diario(f"{nombre_guardado(unidad, uid)}: su ajuste pide la contraseña al conectarla")
            self._desbloquear_bitlocker(uid, ahora)

    def _bloqueada_bitlocker(self, uid: str) -> Path | None:
        """Devuelve la raíz donde esa unidad se ve bloqueada con BitLocker, o `None`.

        Es lo del último recorrido, si la unidad sigue en la lista y no está
        en modo `nada`: lo que se pida entre dos recorridos no espera al
        siguiente para dejar de contar.
        """
        unidad = self.ajustes.unidades.get(uid)
        if unidad is None or unidad.modo == equipo.NADA:
            return None
        return self.bitlocker.get(uid)

    def _es_de_bitlocker(self, uid: str) -> bool:
        """Indica si ese id es de una unidad de la lista con un volumen de BitLocker apuntado.

        Su «Desbloquear» es la ventana de Windows, no el contenedor de una
        raíz cifrada de este equipo.
        """
        unidad = self.ajustes.unidades.get(uid)
        return unidad is not None and not unidad.es_raiz and bool(unidad.volumen)

    def _desbloqueando_bitlocker(self, uid: str) -> bool:
        """Indica si la ventana de desbloqueo de Windows de esa unidad sigue abierta."""
        proc = self.desbloqueos_bitlocker.get(uid)
        return proc is not None and proc.poll() is None

    def _desbloquear_bitlocker(self, uid: str, ahora: float) -> bool:
        """Le pide a Windows la ventana que desbloquea una unidad con BitLocker. No espera.

        Solo si se ve bloqueada ahora y su ventana no está ya abierta.
        Desbloqueada es cuando el recorrido lee su fichero de control, así que
        se recorre en cada vuelta durante `RAFAGA`. Si Windows no la abre, se
        avisa de cómo hacerlo a mano.

        Args:
            uid: El id de una unidad de la lista (`_es_de_bitlocker()`).
            ahora: La hora del reloj del agente.

        Returns:
            `True` si la ventana de Windows está abierta: pedida ahora o antes.
        """
        nombre = nombre_guardado(self.ajustes.unidades[uid], uid)
        raiz = self._bloqueada_bitlocker(uid)
        if raiz is None:
            diario(f"{nombre}: no está bloqueada con BitLocker ahora")
            return False
        if self._desbloqueando_bitlocker(uid):
            return True
        self.desbloqueos_bitlocker.pop(uid, None)
        try:
            proc = desbloquear_bitlocker(raiz)
            motivo = "este equipo no trae con qué"
        except OSError as e:
            proc, motivo = None, str(e)
        if proc is None:
            diario(f"{nombre}: Windows no abre la ventana de desbloqueo de {raiz} ({motivo})")
            avisar(f"{nombre}: no he podido abrir el desbloqueo de Windows",
                   "Desbloquéala desde el Explorador.", True)
            return False
        self.desbloqueos_bitlocker[uid] = proc
        self.rafaga_hasta = max(self.rafaga_hasta, ahora + RAFAGA)
        diario(f"{nombre}: pedida a Windows la ventana que desbloquea {raiz}")
        return True

    def cada_recorrido(self) -> float:
        """Devuelve cada cuántos segundos toca recorrer aunque nadie avise de un montaje.

        Sin quien avise (Windows sin bandeja) se recorre como penwatch. Con una
        unidad bloqueada con BitLocker a la vista, también: no se sabe que
        Windows avise al desbloquearla, y se atiende en cuanto se lee.
        """
        if IS_WIN and (self.bandeja is None or self.bitlocker):
            return RECORRIDO_WINDOWS
        return RECORRIDO_RESPALDO

    def toca_recorrer(self, ahora: float) -> bool:
        """Indica si en esta vuelta toca recorrer los volúmenes.

        Toca cuando ha pasado lo que el último recorrido dejó dicho
        (`cada_recorrido()` con lo que acababa de ver), y en cada vuelta
        mientras dure una racha (`rafaga_hasta`).
        """
        letras = letras_de_unidad()
        if letras != self.letras:
            if self.letras is not None:
                # Ha aparecido o se ha ido una letra: como un aviso de montajes.
                self.rafaga_hasta = max(self.rafaga_hasta, ahora + RAFAGA)
            self.letras = letras
        return ahora >= self.proximo_recorrido or ahora < self.rafaga_hasta

    def en_reposo(self) -> bool:
        """Indica si no hay nada que el agente tenga que mirar de cerca.

        Ni unidades a la vista (atendidas o no: su contrato, su pregunta, su
        vestíbulo), ni una pasada u otro hijo en marcha, ni nada a medias, ni
        una racha de montajes. Entonces lo único que puede pasar llega avisado:
        un montaje, la bandeja, la red, una petición en el buzón.
        """
        return not (self.terminar or self.pasada is not None
                    or self.conexiones or self.vistas or self.cerradas or self.vestibulos
                    or self.desbloqueos or self.bloqueos or self.expulsiones
                    or self.bitlocker or self.desbloqueos_bitlocker
                    or self.actualizando is not None or self.buscando
                    or self.muestreo is not None or self.heredada is not None
                    or self.cortada is not None or self.urgentes
                    or self.cambio_de_red is not None or self.navegador_tras_cierre
                    or not self.navegador_mirado or not self.peticiones.empty()
                    or self.ventana_atajos is not None or self.atajos_en_vuelo is not None
                    or self.atajos_prueba is not None or not self.atajos_hechos.empty()
                    or self.reloj() < self.rafaga_hasta)

    def _fantasmas(self, abiertas: dict[str, Path]) -> None:
        """Quita de `abiertas` las raíces cifradas que son un volumen fantasma.

        Una raíz cifrada vista en su letra con el `.hc` LIBRE no está abierta:
        es lo que deja un volumen que se fue sin desmontar (suspender con el
        cierre automático de VeraCrypt, H-10), que sirve el fichero de control
        de la caché. No se atiende y se dice una vez cómo salir.
        """
        for uid, unidad in self.ajustes.cifradas.items():
            if uid not in abiertas:
                self.fantasmas.discard(uid)
                continue
            if vestibulo.retenido(unidad.contenedor) is not False:
                self.fantasmas.discard(uid)
                continue
            del abiertas[uid]
            if uid not in self.fantasmas:
                self.fantasmas.add(uid)
                avisar(f"{nombre_guardado(unidad, uid)}: el volumen no responde",
                       f"{unidad.ruta} sigue ahí, pero su contenedor está cerrado. "
                       f"Bloquéala y vuelve a desbloquearla.", True)

    def _fantasmas_extraibles(self, abiertas: dict[str, Path],
                              cerradas: dict[str, Path]) -> None:
        """Quita de `abiertas` el fantasma de una unidad extraíble cifrada (#41).

        Desenchufar sin expulsar deja la letra de dentro sirviendo el fichero de
        control desde la caché; al volver a enchufar, el id está a la vez en
        `abiertas` (esa letra) y en `cerradas` (el vestíbulo de la raíz física),
        y si el `.hc` de la física está LIBRE el volumen no está abierto de
        verdad: es el fantasma. Entonces el id sale de `abiertas` (la conexión
        se desconecta como cualquier otra y no se pasa nada contra él) y no se
        pide abrir el contenedor (`_vestibulos()`): montarlo con el fantasma
        puesto dejaría dos letras con el mismo id. Se dice UNA vez por conexión.
        El agente no desmonta el fantasma: la decisión es de la persona (con el
        VeraCrypt que viaja pide UAC). Mismo criterio que `_fantasmas()` y que
        `:fantasma` de «Abrir PRDRIVE». En Linux `retenido()` da `None`.
        """
        for uid in list(self.fantasmas_extraibles):
            if uid not in abiertas or uid not in cerradas:
                self.fantasmas_extraibles.discard(uid)
        for uid in [u for u in abiertas if u in cerradas]:
            if vestibulo.retenido(cerradas[uid] / penwatch.CONTAINER_FILE) is not False:
                self.fantasmas_extraibles.discard(uid)
                continue
            del abiertas[uid]
            if uid in self.fantasmas_extraibles:
                continue
            self.fantasmas_extraibles.add(uid)
            unidad = self.ajustes.unidades.get(uid)
            nombre = nombre_guardado(unidad, uid) if unidad is not None else uid[:8]
            diario(f"{nombre}: fantasma de una conexión anterior en {cerradas[uid]}")
            avisar(f"{nombre}: el volumen no responde",
                   f"{nombre} sigue ahí, pero su contenedor está cerrado: ciérrala con "
                   f"«Expulsar PRDRIVE» y vuelve a abrirla.", True)

    def _raices_ausentes(self, abiertas: dict[str, Path]) -> None:
        """Dice UNA vez que una raíz del equipo no está en su ruta.

        No se busca en otro sitio ni se recrea: mover la carpeta deja las
        líneas base apuntando a lo que ya no está, y eso se arregla
        reinstalando.
        """
        for uid, unidad in self.ajustes.raices.items():
            if uid in abiertas:
                if uid in self.ausentes:
                    self.ausentes.discard(uid)
                    diario(f"{nombre_guardado(unidad, uid)}: la raíz vuelve a estar en "
                           f"{unidad.ruta}")
                continue
            if unidad.cifrada:
                # Cerrada no es ausente: es lo normal con el contenedor
                # bloqueado. Lo que falta es el contenedor mismo.
                try:
                    hay = Path(unidad.contenedor).is_file()
                except OSError:
                    hay = True
                if hay:
                    if uid in self.ausentes:
                        self.ausentes.discard(uid)
                        diario(f"{nombre_guardado(unidad, uid)}: su contenedor vuelve a "
                               f"estar en {unidad.contenedor}")
                elif uid not in self.ausentes:
                    self.ausentes.add(uid)
                    avisar(f"{nombre_guardado(unidad, uid)}: no encuentro su contenedor",
                           f"La raíz cifrada de este equipo tenía que estar en "
                           f"{unidad.contenedor}. Si lo has movido, vuelve a ponerlo "
                           f"ahí o reinstala.", True)
                continue
            if uid not in self.ausentes:
                self.ausentes.add(uid)
                avisar(f"{nombre_guardado(unidad, uid)}: no encuentro su carpeta",
                       f"La raíz de este equipo tenía que estar en {unidad.ruta}. "
                       f"Si la has movido, vuelve a ponerla ahí o reinstala.", True)

    def _nombres_de_otras(self, uid: str) -> set[str]:
        """Devuelve los nombres que ya tienen las demás unidades, conectadas o de la lista."""
        otros = {c.nombre for k, c in self.conexiones.items() if k != uid}
        otros.update(u.nombre for k, u in self.ajustes.unidades.items()
                     if k != uid and u.nombre)
        return otros

    def _conectar(self, uid: str, raiz: Path, ahora: float) -> None:
        """Da por conectada una unidad que se ha visto `ESTABLE` veces.

        Una que no está en la lista se pregunta. De una de la lista con otro
        código, o de una versión anterior a `VERSION_MINIMA`, no se ejecuta
        nada suyo. Si no, se atiende según su modo.
        """
        unidad = self.ajustes.unidades.get(uid)
        nombre = nombre_de(raiz, uid, self._nombres_de_otras(uid),
                           con_etiqueta=not (unidad is not None and unidad.es_raiz))
        con = Conexion(uid, raiz, nombre, ahora)
        # Un lock con nuestro pid es de la conexión anterior (se desenchufó y
        # no se escribe en una unidad que no está): si no se la vuelve a servir
        # se borra (`_soltar`), si sí se reescribe (`_tomar`). De una que no
        # está en la lista no se lee más que su id y su nombre.
        con.soltando = unidad is not None and self._lock_es_nuestro(con)
        self.conexiones[uid] = con
        desbloqueo = self.desbloqueos.pop(uid, None)
        # Lo que un atajo pidió con ella bloqueada, si no ha caducado.
        pedido = self.al_abrirse.pop(uid, None)
        if pedido is not None and ahora - pedido.desde >= ESPERA_ABRIR:
            pedido = None
        # Cada conexión empieza de cero, como el servicio que se arrancaba al
        # enchufar: se sincroniza enseguida y el modo `sync` vuelve a tocar.
        for clave in [k for k in self.marcas if k[0] == uid]:
            del self.marcas[clave]
        self.saltadas = {k for k in self.saltadas if k[0] != uid}
        self._olvidar_vigiladas(uid)
        con.vieja = version_vieja(raiz)
        if con.vieja is not None:
            # Antes de preguntar y de la huella: no hay nada que decidir hasta
            # que se actualice.
            como = (self._como_actualizar(con) if unidad is not None
                    else "con el instalador («Actualizar»)")
            avisar(f"{nombre}: su programa es anterior a la {VERSION_MINIMA}",
                   f"Lleva la {con.vieja or 'versión desconocida'}. El agente no la "
                   f"atiende hasta que la actualices {como}.", True)
            con.version_avisada = con.vieja
            diario(f"{nombre}: versión {con.vieja or 'desconocida'}, anterior a la "
                   f"{VERSION_MINIMA}; no se atiende")
            return
        if unidad is None:
            self._preguntar(con, ahora)
            return
        if not unidad.es_raiz:
            con.huella = huella(raiz)
            if not unidad.codigo and con.huella:
                # Atendida sin haberla visto (el asistente, `atender ID` con
                # ella fuera): la huella se apunta la primera vez que se
                # conecta.
                unidad = replace(unidad, codigo=con.huella)
                self._guardar(self.ajustes.con_unidad(unidad))
                diario(f"{nombre}: apuntada la huella de su código")
            elif con.huella != unidad.codigo:
                con.cambiada = True
                diario(f"{nombre}: su código no es el que tenía cuando se atendió; "
                       f"no se ejecuta nada suyo hasta que se vuelva a decir que sí")
                self._preguntar(con, ahora)
                return
        if unidad.nombre != nombre:
            self._guardar(self.ajustes.con_unidad(replace(unidad, nombre=nombre)))
        self._apuntar_volumen(con)
        # Su nombre y su icono, que el Explorador no lee de un volumen VeraCrypt.
        explorador.poner(raiz, APP_SUBDIR)
        diario(f"{nombre}: " + ("raíz de este equipo" if unidad.es_raiz else "conectada")
               + f" en {raiz} (modo {unidad.modo})")
        abrir = (desbloqueo is not None and desbloqueo.abrir) or (pedido is not None
                                                                   and pedido.abrir)
        explorar = (desbloqueo is not None and desbloqueo.explorar) or (pedido is not None
                                                                         and pedido.explorar)
        if unidad.modo == equipo.UI:
            self._abrir_ventana(con)
        elif abrir:
            self._lanzar_ventana(con)       # «Abrir» con ella bloqueada
        if explorar:
            self._explorar(con)             # «Abrir en explorador» con ella bloqueada
        if pedido is not None:
            self._usada(uid, ahora)

    def _desconectar(self, uid: str, ahora: float, cerradas: dict[str, Path]) -> None:
        """Olvida la conexión de una unidad que ya no está.

        Args:
            uid: El id de la unidad.
            ahora: La hora del reloj del agente.
            cerradas: Los vestíbulos que se ven ahora.
        """
        con = self.conexiones.pop(uid, None)
        if con is None:
            return
        # La letra queda para otra unidad: fuera el nombre y el icono que se le
        # pasaron al Explorador (los de esta unidad, no los de otra que la tome).
        explorador.quitar(con.raiz, uid)
        if con.hijo is not None and con.hijo.poll() is None:
            try:
                con.hijo.terminate()
            except OSError:
                pass
        # No se escribe en una unidad que ya no está. Si sigue ahí la entrada
        # del contenedor, se ha cerrado con la unidad puesta: es «Expulsar», no
        # una conexión nueva, y no se vuelve a pedir la contraseña. Se apunta
        # como ya pedida aunque no se sepa todavía: si en el siguiente
        # recorrido no hay entrada, `_vestibulos()` la rearma.
        self.vestibulos[uid] = str(cerradas.get(uid, ""))
        self.urgentes = [u for u in self.urgentes if u[0] != uid]
        self.entorno = replace(self.entorno, sin_conexion={
            k: v for k, v in self.entorno.sin_conexion.items() if k[0] != uid})
        self.sospechas = {k: v for k, v in self.sospechas.items() if k[0] != uid}
        self.sin_red_avisado = {k for k in self.sin_red_avisado if k[0] != uid}
        self._olvidar_vigiladas(uid)
        self.keepassxc.discard(uid)
        if con.actualizacion is not None and con.actualizacion.proc is not None:
            # El hijo sigue solo y fallará; al volver, la huella dirá si la tocó.
            diario(f"{con.nombre}: se ha ido mientras se actualizaba")
        unidad = self.ajustes.unidades.get(uid)
        if unidad is not None and unidad.volumen:
            # Con BitLocker puede volver bloqueada con la unidad puesta: es la
            # misma conexión, y su ventana ya no se decide otra vez.
            self.bitlocker_tratadas.add(uid)
        diario(f"{con.nombre} " + ("bloqueada: su contenedor se ha cerrado"
                                   if unidad is not None and unidad.cifrada else
                                   "ya no está en su carpeta"
                                   if unidad is not None and unidad.es_raiz
                                   else "desconectada"))
        # Si se quitó sin expulsar: en Linux su KeePassXC sigue abierto, y el
        # navegador sigue apuntando a él.
        try:
            huerfanos = cerrar_keepassxc_huerfano(con.raiz)
        except OSError:
            huerfanos = 0
        if huerfanos:
            diario(f"{con.nombre}: se ha ido con KeePassXC abierto; le pido que se cierre")
            # Mientras corra un KeePassXC extraído, `limpiar_navegador()` no
            # toca nada: se hace cuando salga (`_tras_cierre()`).
            self.navegador_tras_cierre[uid] = (con.nombre, con.raiz)
            return
        self._limpiar_navegador(con.nombre)

    def _tras_cierre(self) -> None:
        """Deja el navegador como estaba cuando sale el KeePassXC de una raíz que se fue.

        Es lo que `_desconectar()` deja pendiente al pedirle que se cierre. Si
        la raíz ha vuelto, su KeePassXC ya no es un huérfano: lo suyo lo hará
        «Expulsar», o la próxima vez que se vaya.
        """
        for uid, (nombre, raiz) in list(self.navegador_tras_cierre.items()):
            if uid in self.conexiones:
                del self.navegador_tras_cierre[uid]
            elif not keepassxc_huerfano_abierto(raiz):
                del self.navegador_tras_cierre[uid]
                self._limpiar_navegador(nombre)

    def _limpiar_navegador(self, por: str) -> None:
        """Hace `limpiar_navegador()` y lo dice en el diario, si ha tocado algo.

        Nunca lanza: es lo de después de que una unidad se vaya, y un fallo
        del registro no puede tumbar al agente.

        Args:
            por: Quién se ha ido, o cuándo, para el diario.
        """
        try:
            tocadas, fallos = limpiar_navegador()
        except OSError as e:
            tocadas, fallos = 0, [str(e)]
        if tocadas:
            que = ((f"{tocadas} clave{'s' if tocadas != 1 else ''} del registro") if IS_WIN
                   else f"{tocadas} manifiesto{'s' if tocadas != 1 else ''}")
            diario(f"{por}: el navegador ya no busca un KeePassXC que no está ({que})")
        if fallos:
            diario(f"{por}: no he podido dejar como estaban las claves del navegador: "
                   f"{fallos[0]}")

    def _limpiar_letras(self, por: str) -> None:
        """Hace `explorador.limpiar()` y apunta en el diario las letras que ha limpiado.

        Quita el nombre y el icono que prdrive le puso a la letra de un volumen
        VeraCrypt que se cerró sin que el agente lo viese (con el agente
        parado, desde VeraCrypt, tras un fallo): si no, la unidad que tome esa
        letra saldría en el Explorador con lo de otra. No toca las de un
        volumen que sigue abierto. Nunca lanza.

        Args:
            por: Cuándo se hace, para el diario.
        """
        try:
            letras = explorador.limpiar(APP_SUBDIR)
        except Exception as e:                          # noqa: BLE001
            diario(f"{por}: no he podido limpiar el nombre y el icono de las letras: {e}")
            return
        if letras:
            que = (f"la letra {letras[0]}:" if len(letras) == 1
                   else "las letras " + ", ".join(f"{letra}:" for letra in letras))
            diario(f"{por}: quito el nombre y el icono que quedaban en {que}")

    def _vestibulos(self, cerradas: dict[str, Path], ahora: float) -> None:
        """Abre las unidades VeraCrypt de la lista que se ven cerradas.

        Se le pide a VeraCrypt una vez por conexión, como hace penwatch. Una
        que no está en la lista, nunca: no se ejecuta nada de una unidad que no
        se ha aceptado. Tampoco una a la que se le ha quitado el «Pedir la
        contraseña al conectarla» (`Unidad.pide_al_conectar()`): se apunta como
        tratada igual, para no contarla ni decirlo otra vez en esa conexión.
        """
        for uid in list(self.vestibulos):
            if uid not in cerradas:
                self.vestibulos_pedidos.pop(uid, None)
                if self.vestibulos.pop(uid):
                    diario("entrada de una unidad cifrada retirada; apertura rearmada")
        for uid in list(self.cerradas):
            if uid not in cerradas:
                del self.cerradas[uid]
        for uid, raiz in cerradas.items():
            if (uid in self.conexiones or uid in self.vestibulos
                    or uid in self.fantasmas_extraibles):
                continue
            unidad = self.ajustes.unidades.get(uid)
            if unidad is None or unidad.modo == equipo.NADA:
                continue
            self.cerradas[uid] = self.cerradas.get(uid, 0) + 1
            if self.cerradas[uid] < ESTABLE:
                self.rafaga_hasta = max(self.rafaga_hasta, ahora + 3 * TICK)
                continue
            del self.cerradas[uid]
            self.vestibulos[uid] = str(raiz)
            nombre = nombre_guardado(unidad, uid)
            if not unidad.pide_al_conectar(equipo.CIFRADO_VERACRYPT):
                diario(f"{nombre}: cifrada y cerrada en {raiz}; no se abre sola (su "
                       f"«Pedir la contraseña al conectarla» está apagado)")
                continue
            diario(f"{nombre}: cifrada y cerrada en {raiz}")
            if abrir_contenedor(raiz):
                self.vestibulos_pedidos[uid] = ahora

    def _cerrada_veracrypt(self, uid: str) -> Path | None:
        """Devuelve la raíz física de esa unidad de VeraCrypt si se ve con el contenedor cerrado.

        Es una unidad de la lista, no en modo `nada`, cuyo vestíbulo el
        recorrido ya ha dado por estable (`vestibulos`), y que ni está
        conectada ni se acaba de ver abierta (`vistas`).

        Returns:
            La raíz donde está su vestíbulo, o `None`.
        """
        unidad = self.ajustes.unidades.get(uid)
        raiz = self.vestibulos.get(uid)
        if (not raiz or unidad is None or unidad.es_raiz or unidad.modo == equipo.NADA
                or uid in self.conexiones or uid in self.vistas):
            return None
        return Path(raiz)

    def _abrir_vestibulo(self, uid: str, ahora: float) -> bool:
        """Le pide a VeraCrypt que abra el contenedor de una unidad cerrada. No espera.

        Es lo que hace el agente al enchufarla (`_vestibulos()`), pedido por la
        persona con un atajo: va aunque su «Pedir la contraseña al conectarla»
        esté apagado. Si se le acaba de pedir (`GRACIA_ABRIR`, también al
        enchufarla), no se pide otra vez: su ventana estará todavía abierta.

        Args:
            uid: El id de la unidad (`_cerrada_veracrypt()` no es `None`).
            ahora: La hora del reloj del agente.

        Returns:
            `True` si VeraCrypt está pidiendo su contraseña: lanzado ahora o
            hace nada.
        """
        raiz = self._cerrada_veracrypt(uid)
        if raiz is None:
            return False
        nombre = nombre_guardado(self.ajustes.unidades[uid], uid)
        if ahora - self.vestibulos_pedidos.get(uid, -math.inf) < GRACIA_ABRIR:
            diario(f"{nombre}: VeraCrypt acaba de pedir su contraseña")
            return True
        if not abrir_contenedor(raiz):
            diario(f"{nombre}: no hay VeraCrypt con el que abrir su contenedor en {raiz}")
            avisar(f"{nombre}: no puedo pedir su contraseña",
                   "Ábrela desde la propia unidad, con "
                   + ("«Abrir PRDRIVE»." if IS_WIN else "abrir-prdrive.sh."), True)
            return False
        self.vestibulos_pedidos[uid] = ahora
        diario(f"{nombre}: pedida a VeraCrypt la contraseña de su contenedor en {raiz}")
        return True

    def _preguntar(self, con: Conexion, ahora: float) -> None:
        """Pregunta por una unidad que no está en la lista, o cuyo código ha cambiado.

        Avisa y abre la ventanita de la pregunta con cuenta atrás. Sin pantalla
        donde preguntar cuenta como «Ahora no».
        """
        espera = self.ajustes.espera_unidad_nueva
        if con.cambiada:
            avisar(f"{con.nombre}: su código ha cambiado",
                   "¿Seguir atendiéndola en este equipo? Hasta que contestes, no se "
                   "ejecuta nada suyo.", True)
        else:
            avisar(f"Se ha conectado {con.nombre}", "¿Atenderla en este equipo?")
        if not hay_pantalla():
            con.respuesta = pl.AHORA_NO
            diario(f"{con.nombre} ({con.id[:8]}) "
                   + ("tiene otro código" if con.cambiada else "no está en la lista")
                   + f" y no hay entorno gráfico donde preguntar: cuenta como «Ahora "
                     f"no». Para atenderla: agente.py atender {con.id}")
            return
        con.pregunta = pl.Pregunta(con.id, ahora, espera)
        try:
            con.hijo = lanzar(orden_pregunta(con.nombre, espera, con.cambiada),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              **_opciones_hijo(equipo.DIR))
        except OSError as e:
            diario(f"no he podido abrir la pregunta por {con.nombre}: {e}")
            con.hijo = None

    def _preguntas(self, ahora: float) -> None:
        """Recoge las respuestas de las preguntas en curso.

        El sí atiende la unidad; el no, o el tiempo, la deja sin atender
        mientras siga conectada.
        """
        for con in self.conexiones.values():
            if con.pregunta is None:
                continue
            rc = con.hijo.poll() if con.hijo is not None else 2
            respuesta = None if rc is None else (pl.ATENDER if rc == 0 else pl.AHORA_NO)
            final = pl.resolver(con.pregunta, respuesta, ahora)
            if final is None:
                continue
            if con.hijo is not None and con.hijo.poll() is None:
                try:
                    con.hijo.terminate()   # se cierra sola a cero; por si no
                except OSError:
                    pass
            con.pregunta, con.hijo = None, None
            if final == pl.ATENDER:
                self._atender(con)
            else:
                con.respuesta = pl.AHORA_NO
                diario(f"{con.nombre}: «Ahora no»; no se atiende mientras siga "
                       f"conectada. Para atenderla: agente.py atender {con.id}")

    def _atender(self, con: Conexion) -> None:
        """Es el sí: la unidad entra en la lista con la huella de su código de ahora.

        Si ya estaba (su código había cambiado), conserva su modo.
        """
        con.respuesta = None
        codigo = huella(con.raiz) or ""
        con.huella = codigo or None
        antes = self.ajustes.unidades.get(con.id)
        if antes is not None:
            con.cambiada = False
            self._guardar(self.ajustes.con_unidad(replace(antes, codigo=codigo)))
            self._apuntar_volumen(con)
            diario(f"{con.nombre}: se sigue atendiendo, con su código de ahora")
            if antes.modo == equipo.UI:
                self._abrir_ventana(con)
            return
        self._guardar(self.ajustes.con_unidad(
            equipo.Unidad(con.id, equipo.MODO_AL_ATENDER, con.nombre, codigo=codigo)))
        self._apuntar_volumen(con)
        diario(f"{con.nombre} añadida a la lista (modo {equipo.MODO_AL_ATENDER})")

    def _apuntar_volumen(self, con: Conexion) -> None:
        """Apunta en qué volumen está una unidad de la lista que lleva BitLocker.

        Con él se la reconoce cuando vuelve bloqueada y no se puede leer su
        fichero de control. Sin BitLocker se olvida; si Windows no dice el
        nombre del volumen o su estado, se deja como estaba. Un volumen no
        nombra a dos unidades: al apuntarlo a una se le quita a la que lo
        tuviera. Las raíces de este equipo no lo llevan.
        """
        unidad = self.ajustes.unidades.get(con.id)
        if unidad is None or unidad.es_raiz:
            return
        nombre = bitlocker.volumen_de(con.raiz)
        if not nombre:
            # Fuera de Windows, siempre. Y sin nombre no se pregunta el estado:
            # el de una carpeta donde se monta la unidad sería el de la letra
            # en la que está esa carpeta, que es otro volumen.
            return
        estado = cifrada.bitlocker_de(con.raiz)
        if not estado.known:
            return
        volumen = nombre if estado.present else ""
        if volumen == unidad.volumen:
            return
        ajustes = self.ajustes
        if volumen:
            for otra in list(ajustes.unidades.values()):
                if otra.id != con.id and otra.volumen == volumen:
                    ajustes = ajustes.con_unidad(replace(otra, volumen=""))
        self._guardar(ajustes.con_unidad(replace(unidad, volumen=volumen)))
        diario(f"{con.nombre}: " + ("apuntado su volumen, para reconocerla si vuelve "
                                    "bloqueada con BitLocker" if volumen else
                                    "ya no lleva BitLocker; olvidado su volumen"))

    def _guardar(self, ajustes: equipo.Ajustes) -> None:
        """Guarda los ajustes.

        Si no se pueden escribir, el cambio vale hasta que se reinicie el
        agente.
        """
        self.ajustes = ajustes
        if not equipo.guardar_ajustes(ajustes):
            diario("no he podido escribir agente.json; el cambio vale hasta que "
                   "me reinicie")

    def _abrir_ventana(self, con: Conexion) -> None:
        """Hace el modo `ui`: abre la ventana al conectarla.

        No la abre si ya hay una ventana o un servicio en marcha.
        """
        con.lanzada = True
        ocupado = _aplicacion_en_marcha(con.raiz)
        if ocupado:
            diario(f"{con.nombre}: no abro la ventana: {ocupado}")
            return
        self._lanzar_ventana(con)

    def _lanzar_ventana(self, con: Conexion) -> None:
        """Abre la ventana de runsync de esa raíz.

        Se lanza con el Python del agente y desde fuera de la raíz. Nuestro
        servicio no estorba: la ventana lo pausa al abrirse (`daemon.stop`).
        Otra ventana sí, y runsync ya se negaría.
        """
        if self._por_actualizar(con) or rclone_propio() is None:
            diario(f"{con.nombre}: no abro su ventana: "
                   + (self._motivo_sin_servicio(con) if self._por_actualizar(con)
                      else SIN_RCLONE))
            return
        ventana = _registro_vivo(con.raiz, penwatch.UI_LOCK_REL)
        if ventana is not None:
            diario(f"{con.nombre}: su ventana ya está abierta (pid {ventana.get('pid')})")
            return
        if not hay_pantalla():
            diario(f"{con.nombre}: sin entorno gráfico; no hay dónde abrir "
                   f"la ventana")
            return
        try:
            lanzar([python(ventana=True), str(app(con.raiz) / "runsync.py")],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   **_opciones_hijo(equipo.DIR, separado=True))
            diario(f"{con.nombre}: ventana abierta")
            self._usada(con.id, self.reloj())
        except OSError as e:
            diario(f"{con.nombre}: no he podido abrir la ventana: {e}")

    def _lanzar_llavero(self, con: Conexion) -> None:
        """Hace el «Abrir llavero» de la bandeja: el `runsync.py --llavero` de esa raíz.

        Con el Python del agente y desde fuera de la raíz, como su ventana, y
        con sus mismas guardas, salvo una ventana abierta: «Abrir llavero» no
        para el servicio ni choca con ella (es lo que hace también
        `Llavero.bat`). Lo que diga (el fichero llave, combinar) lo dice él.
        Lanzado, pide la pasada que trae lo último si no la va a hacer nadie
        (`_traer_al_abrir()`).
        """
        if self._por_actualizar(con) or rclone_propio() is None:
            diario(f"{con.nombre}: no abro su llavero: "
                   + (self._motivo_sin_servicio(con) if self._por_actualizar(con)
                      else SIN_RCLONE))
            return
        if not self._llavero_de(con):
            diario(f"{con.nombre}: no lleva llavero")
            return
        if not hay_pantalla():
            diario(f"{con.nombre}: sin entorno gráfico; no hay dónde abrir su llavero")
            return
        try:
            lanzar([python(ventana=True), str(app(con.raiz) / "runsync.py"), "--llavero"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   **_opciones_hijo(equipo.DIR, separado=True))
            diario(f"{con.nombre}: abriendo su llavero")
        except OSError as e:
            diario(f"{con.nombre}: no he podido abrir su llavero: {e}")
            return
        self._traer_al_abrir(con)

    def _traer_al_abrir(self, con: Conexion) -> None:
        """Encola la pasada que trae lo último del llavero al abrirlo, si no la hará nadie.

        Su `runsync.py --llavero` no la hace cuando el agente atiende la raíz
        (`llavero.atiende_el_servicio()`), y la del agente al verse KeePassXC
        abierto no sale si la moderación retiene al llavero
        (`pl.retiene_al_llavero()`: la pausa de la bandeja, la batería, el
        ahorro de energía). Entonces va como urgente, que se salta la
        moderación; lo de después (lo que se guarde, al cerrarlo) sigue
        retenido. Con su KeePassXC ya abierto no se pide: abrirlo solo lo trae
        delante, como en `keepassxc.mirar_apertura()`.
        """
        clave = (con.id, model.LLAVERO)
        if con.lock is None or con.servicio is None or con.id in self.bloqueos \
                or con.id in self.keepassxc or clave in self.urgentes \
                or not any(p.nombre == model.LLAVERO for p in con.servicio.parejas):
            return
        motivo = pl.moderacion(replace(self.entorno, pausado=self.pausado),
                               self.ajustes.politica)
        if pl.retiene_al_llavero(motivo):
            self.urgentes.append(clave)
            diario(f"{con.nombre}: se trae lo último de su llavero aunque no se "
                   f"sincroniza ({motivo})")

    def _sirve(self, con: Conexion) -> bool:
        """Indica si el agente tiene que servir esa conexión.

        Es una unidad de la lista, con su código aceptado, de una versión
        válida y sin una actualización a medias, en modo `daemon` o `sync` y
        sin el «Pausar» de su ventana.
        """
        unidad = self.ajustes.unidades.get(con.id)
        return unidad is not None and not con.cambiada and not self._por_actualizar(con) \
            and unidad.modo in (equipo.DAEMON, equipo.SYNC) and not unidad.pausada

    @staticmethod
    def _por_actualizar(con: Conexion) -> bool:
        """Indica si de esa raíz no se ejecuta nada hasta ponerla al día.

        Es anterior a `VERSION_MINIMA`, o una actualización suya la dejó a
        medias.
        """
        return con.vieja is not None or con.a_medias

    def _cargar_servicio(self, con: Conexion) -> None:
        """Relee las parejas y el intervalo si cambió el TOML o la memoria del servicio.

        La ventana los edita mientras el agente sigue vivo.
        """
        ahora = self.reloj()
        if con.vista is None or not con.firma or ahora - con.config_mirado >= MIRAR_CONFIG:
            # La fecha del TOML, de tarde en tarde: `_lanzar()` lo relee antes
            # de cada pasada, y aquí solo sirve para enseñar pronto lo editado.
            try:
                con.config_visto = (app(con.raiz) / "sync_config.toml").stat().st_mtime_ns
            except OSError:
                con.config_visto = None
            con.config_mirado = ahora
        if con.vista is None:
            try:
                prefs = (estado_de(con.raiz) / NOMBRE_PREFS).stat().st_mtime_ns
            except OSError:
                prefs = None
        else:
            prefs = con.vista.get(NOMBRE_PREFS, (None,))[0]
        firma = [con.config_visto, prefs]
        if tuple(firma) == con.firma and (con.servicio or con.error):
            return
        con.firma = tuple(firma)
        try:
            con.servicio, con.error = leer_servicio(con.raiz), None
        except ValueError as e:
            self._sin_servicio(con, e)

    def _sin_servicio(self, con: Conexion, error: ValueError) -> None:
        """Deja esa conexión sin servicio por su config, y lo avisa una vez.

        El aviso dice lo que pasa: un config que la puerta de seguridad rechaza
        (`ConfigRechazada`) es «config rechazado», y lo demás (no se puede leer,
        no es TOML, no tiene ninguna pareja) es «nada que sincronizar».

        Args:
            con: La conexión.
            error: Por qué no hay servicio (`leer_servicio()`, `leer_config()`).
        """
        con.servicio, con.error = None, str(error)
        con.motivo = f"sin servicio: {con.error}"
        if not con.avisado_error:
            con.avisado_error = True
            que = "config rechazado" if isinstance(error, ConfigRechazada) \
                else "nada que sincronizar"
            avisar(f"{con.nombre}: {que}", con.error)

    def _otro_servicio(self, con: Conexion) -> dict | None:
        """Devuelve el registro de otro servicio vivo de este equipo en esa raíz.

        Es `None` si no hay otro, o si el registro es de antes de reiniciar.
        Dentro de una vuelta vale lo leído mientras el fichero no haya cambiado
        (`_registro()`, con la mirada de esa vuelta); fuera, se lee de verdad.
        """
        info = self._registro(con, NOMBRE_LOCK)
        if not store.vivo_en_este_arranque(info, HOST) or info.get("pid") == os.getpid():
            return None
        return info

    def _registro(self, con: Conexion, nombre: str) -> dict:
        """Devuelve un registro JSON del `state/` de una raíz, releyéndolo solo si ha cambiado.

        Manda lo que vio la mirada de esta vuelta (`Conexion.vista`): si el
        fichero no está, `{}` sin tocar la unidad; si su fecha y su tamaño son
        los de la última lectura y esta tiene menos de `RELEER_REGISTROS`, lo
        leído entonces. Con dos segundos de resolución de fecha (FAT, exFAT)
        un registro reescrito con el mismo tamaño puede no notarse hasta esa
        relectura: por eso lo que decide de verdad no pasa por aquí
        (`_lanzar()` y `_soltar()` leen el lock, y `_tomar()` lo crea con
        `O_EXCL`).
        """
        ruta = estado_de(con.raiz) / nombre
        if con.vista is None:
            return store.read_json(ruta)
        firma = con.vista.get(nombre)
        if firma is None:
            con.leidos.pop(nombre, None)
            return {}
        ahora = self.reloj()
        antes = con.leidos.get(nombre)
        if antes is not None and antes[0] == firma and 0 <= ahora - antes[1] < RELEER_REGISTROS:
            return antes[2]
        info = store.read_json(ruta)
        con.leidos[nombre] = (firma, ahora, info)
        return info

    def _contrato(self, con: Conexion, ahora: float) -> None:
        """Cumple el contrato de servicio de esa raíz con los ficheros de su `state/`.

        Toma o suelta el lock, obedece `daemon.stop`, se pone en pausa mientras
        haya una ventana de runsync abierta y se aparta si otro servicio vivo
        tiene el lock. Deja en `con.motivo` por qué no sirve, si no sirve.
        """
        ocupada = self.pasada is not None and self.pasada.tarea.raiz == con.id
        if con.id in self.bloqueos:
            # Se está bloqueando: ni se encola ni se vuelve a tomar el lock.
            if not ocupada:
                self._soltar(con)
            con.motivo = "bloqueándose"
            return
        if con.id in self.expulsiones and not self.expulsiones[con.id].subir:
            # Se está expulsando: igual que al bloquearla, y tampoco se
            # vuelve a tomar el lock mientras la unidad siga a la vista.
            # Mientras sube lo pendiente (`Expulsion.subir`) se la sigue
            # sirviendo como siempre.
            if not ocupada:
                self._soltar(con)
            con.motivo = "expulsándose"
            return
        if con.actualizacion is not None:
            # Igual que al bloquearla: se suelta acabada la pareja en curso, y
            # entonces se lanza la actualización (`_actualizaciones`).
            if not ocupada:
                self._soltar(con)
            con.motivo = "actualizándose"
            return
        if not self._sirve(con):
            if not ocupada:                 # el lock se suelta al acabar la pareja
                self._soltar(con)
            con.motivo = self._motivo_sin_servicio(con)
            return
        if rclone_propio() is None:
            if not ocupada:
                self._soltar(con)
            con.motivo = SIN_RCLONE
            if not self.sin_rclone_avisado:
                self.sin_rclone_avisado = True
                avisar(f"{APP_NAME}: el agente no tiene su rclone", SIN_RCLONE, True)
            return
        stop = estado_de(con.raiz) / NOMBRE_STOP
        if con.vista is not None:
            parar = NOMBRE_STOP in con.vista
        else:
            try:
                parar = stop.exists()
            except OSError:
                parar = False
        otro = self._otro_servicio(con)
        if parar and not ocupada and otro is None:
            # Lo que hace runsync al abrir su ventana (o con `--auto`, o con
            # cualquier orden pasada a `sync.py`, o su servicio al arrancar):
            # acabada la pareja en curso se suelta el lock y se borra el stop.
            # No se sale: se hace pausa. Con otro servicio vivo en el lock, el
            # stop es para ESE: borrarlo lo dejaría corriendo.
            self._soltar(con)
            stop.unlink(missing_ok=True)
            con.pausa = ahora
            diario(f"{con.nombre}: runsync ha pedido parar el servicio; en pausa")
            dlog(con.raiz, "servicio (agente del equipo) en pausa: lo ha pedido runsync")
        ventana = store.vivo_en_este_arranque(self._registro(con, NOMBRE_VENTANA), HOST)
        if ventana:
            con.pausa = ahora
            if not con.ventana:
                self._usada(con.id, ahora)      # se acaba de abrir su ventana
        con.ventana = bool(ventana)
        if otro is not None and con.lock is not None:
            con.lock = None                 # el lock ya es de otro
        self._cargar_servicio(con)

        if con.pausa is not None and (ventana or (ahora - con.pausa < GRACIA
                                                  and not con.reanudar)):
            con.motivo = "en pausa: hay una ventana de runsync abierta"
        elif otro is not None:
            con.motivo = f"la atiende otro servicio (pid {otro.get('pid')})"
        elif con.servicio is None:
            con.motivo = f"sin servicio: {con.error}"
        else:
            if con.pausa is not None:
                # La otra mitad de «en pausa»: sin ella, el diario no decía
                # cuándo se volvía a atender tras cerrar la ventana (visto en
                # real).
                diario(f"{con.nombre}: sin ventana de runsync; vuelvo a atenderla")
                dlog(con.raiz, "servicio (agente del equipo) reanudado")
            con.pausa = None
            con.reanudar = False
            con.motivo = ""
            if con.lock is None:
                self._tomar(con)
            elif not self._lock_es_nuestro(con, de_memoria=True):
                con.lock = None             # lo borró runsync al cansarse de esperar
            else:
                self._al_dia_el_lock(con)   # la config pudo cambiar desde la última vuelta
            return
        if not ocupada:
            self._soltar(con)

    def _motivo_sin_servicio(self, con: Conexion) -> str:
        """Devuelve por qué el agente no atiende esa conexión, para `status`."""
        if con.pregunta is not None:
            return "preguntando si atenderla"
        if con.respuesta == pl.AHORA_NO:
            return "«Ahora no» en esta conexión"
        if con.vieja is not None:
            return (f"su programa es de la {con.vieja or 'versión desconocida'}: el agente "
                    f"atiende desde la {VERSION_MINIMA}")
        if con.a_medias:
            return "su actualización no acabó bien: vuelve a pedir «Actualizar»"
        if con.cambiada:
            return "su código ha cambiado desde que se atendió"
        unidad = self.ajustes.unidades.get(con.id)
        if unidad is None:
            return "sin atender"
        if unidad.pausada and unidad.modo in (equipo.DAEMON, equipo.SYNC):
            return "en pausa desde su ventana: no se sincroniza hasta «Reanudar»"
        return f"modo {unidad.modo}: {equipo.TEXTO_MODO[unidad.modo]}"

    def _lock_es_nuestro(self, con: Conexion, de_memoria: bool = False) -> bool:
        """Indica si el `daemon.lock.json` de la raíz es de este agente.

        Args:
            de_memoria: Si vale lo leído mientras el fichero no haya cambiado
                (`_registro()`): es la mirada de cada vuelta. Sin ello se lee
                de verdad, que es lo que hace quien va a lanzar o a soltar.
        """
        info = self._registro(con, NOMBRE_LOCK) if de_memoria \
            else store.read_json(con.raiz / penwatch.DAEMON_LOCK_REL)
        return info.get("pid") == os.getpid() and info.get("host") == HOST

    def _tomar(self, con: Conexion) -> None:
        """Se hace servicio de la raíz, si nadie vivo lo es.

        Mirar y escribir son UN paso (`store.tomar_registro()`, O_EXCL) y el
        servicio de runsync toma el mismo fichero igual
        (`runsync.tomar_lock()`): de los dos que llegan a la vez, solo uno lo
        crea y el otro se aparta. Mirar primero y escribir después dejaba que
        los dos se creyeran el servicio. Un runsync de antes todavía escribe
        sin mirar: lo que queda es la pareja en curso, y en la vuelta siguiente
        el agente ve su lock y se aparta (`_otro_servicio`).
        """
        unidad = self.ajustes.unidades[con.id]
        datos = {"pid": os.getpid(), "host": HOST, "started": store.stamp(),
                 "arranque": store.arranque_del_sistema(),
                 "pairs": [p.nombre for p in con.servicio.parejas],
                 "interval_min": con.servicio.minutos, "agente": True,
                 "modo": unidad.modo}
        destino = en_la_raiz(con.raiz, con.raiz / penwatch.DAEMON_LOCK_REL)
        if destino is None:
            return
        tomado, otro = store.tomar_registro(destino, datos, equipo.vivo_aqui)
        if tomado is False and otro and otro.get("pid") == os.getpid() \
                and otro.get("host") == HOST:
            # El nuestro, que no se pudo borrar al soltarlo (`soltando`).
            tomado = store.write_json(destino, datos)
        con.leidos.pop(NOMBRE_LOCK, None)   # lo que hubiera leído ya no vale
        if tomado:
            con.lock = datos
            con.soltando = False        # el fichero vuelve a ser uno vivo
            # Lo que pasó mientras no la servía no lo ha visto (su ventana
            # pudo aprobar un --resync, o mover media carpeta): sus parejas
            # vuelven al intervalo de fábrica.
            self._despertar(con.id)
            dlog(con.raiz, f"servicio (agente del equipo, pid {os.getpid()}) atendiendo: "
                           f"{', '.join(datos['pairs'])}"
                           + ("" if unidad.modo == equipo.SYNC
                              else f" cada {con.servicio.minutos:g} min"))

    def _soltar(self, con: Conexion) -> None:
        """Deja de atender la raíz y borra nuestro `daemon.lock.json`.

        En Windows no se borra un fichero que otro tiene abierto, y runsync lee
        este cada 0,3 s mientras espera a que el servicio pare (WinError 32,
        H-2 de las pruebas en real). Entonces se deja de atender igual
        (`con.lock` a `None`, que es lo que mira el planificador) y el fichero
        se reintenta en la vuelta siguiente (`soltando`): con el pid del agente
        dentro, runsync esperaría hasta rendirse.
        """
        if con.lock is None and not con.soltando:
            return
        con.lock = None
        if self._lock_es_nuestro(con):
            try:
                (con.raiz / penwatch.DAEMON_LOCK_REL).unlink(missing_ok=True)
            except OSError:
                con.soltando = True
                return
        con.soltando = False

    def _despertar(self, uid: str, remoto: str | None = None) -> None:
        """Devuelve al intervalo de fábrica las parejas de una raíz (`pl.despierta()`).

        Args:
            uid: La raíz.
            remoto: Si se da, solo las que van a ese remote.
        """
        con = self.conexiones.get(uid)
        de_ese = None if remoto is None or con is None or con.servicio is None \
            else {p.nombre for p in con.servicio.parejas if p.remoto == remoto}
        for clave, marca in list(self.marcas.items()):
            if clave[0] == uid and (de_ese is None or clave[1] in de_ese):
                self.marcas[clave] = pl.despierta(marca)

    def _ritmo(self, con: Conexion, pareja: str, marca: pl.Marca) -> tuple[float, float] | None:
        """Devuelve `(intervalo de fábrica, intervalo de ahora)` de una pareja, en segundos.

        `None` si no es del servicio del agente o la raíz va en modo `sync`,
        que no tiene intervalo.
        """
        unidad = self.ajustes.unidades.get(con.id)
        if con.servicio is None or unidad is None or unidad.modo != equipo.DAEMON:
            return None
        p = next((x for x in con.servicio.parejas if x.nombre == pareja), None)
        if p is None:
            return None
        raiz = pl.Raiz(con.id, con.servicio.parejas, con.servicio.minutos * 60)
        return pl.intervalo_de(raiz, p), pl.cada(raiz, p, marca, self.ajustes.politica)

    def _decir_ritmo(self, con: Conexion, pareja: str, antes: pl.Marca,
                     despues: pl.Marca) -> None:
        """Dice en los diarios cuándo una pareja pasa a sincronizarse menos, y cuándo vuelve."""
        a, d = self._ritmo(con, pareja, antes), self._ritmo(con, pareja, despues)
        if a is None or d is None or a[1] == d[1] or despues.saltada or antes.saltada:
            return
        if d[1] > d[0]:
            texto = (f"lleva {despues.vacias} pasadas sin nada que hacer; ahora cada "
                     f"{d[1] / 60:g} min (hasta que algo cambie)")
        else:
            texto = f"vuelve a sincronizarse cada {d[0] / 60:g} min"
        diario(f"[{con.nombre}] {pareja}: {texto}")
        dlog(con.raiz, f"[{pareja}] {texto}")

    def _estiradas(self, con: Conexion) -> dict[str, float]:
        """Devuelve las parejas de una raíz que ahora se pasan menos, con sus minutos."""
        if con.lock is None:
            return {}
        salida = {}
        for (uid, pareja), marca in self.marcas.items():
            if uid != con.id or not (marca.vacias or marca.saltada):
                continue
            ritmo = self._ritmo(con, pareja, marca)
            if ritmo is not None and ritmo[1] > ritmo[0]:
                salida[pareja] = round(ritmo[1] / 60, 1)
        return salida

    def _raices(self) -> list[pl.Raiz]:
        """Devuelve las raíces que el planificador puede atender.

        Las que tienen nuestro lock y su servicio y no se están bloqueando,
        expulsando ni actualizando. De la raíz de la pasada cortada se quita su pareja
        mientras espera. Con su KeePassXC abierto, el llavero trae lo de otro
        dispositivo cada `llavero.REMOTO_ABIERTO` como mucho, también en modo
        `sync`.
        """
        raices = []
        cortada = self._cortada()
        for con in self.conexiones.values():
            if con.lock is None or con.servicio is None or con.id in self.bloqueos \
                    or con.actualizacion is not None:
                continue
            modo = self.ajustes.unidades[con.id].modo
            intervalo = math.inf if modo == equipo.SYNC else con.servicio.minutos * 60
            parejas = con.servicio.parejas
            expulsion = self.expulsiones.get(con.id)
            if expulsion is not None:
                # Expulsándose: solo lo que se sube antes de soltarla, y nada más.
                parejas = tuple(p for p in parejas if p.nombre in expulsion.subir)
                if not parejas:
                    continue
            if cortada is not None and cortada.get("raiz") == con.id:
                cortadas = {cortada.get("pareja"), *(cortada.get("parejas") or ())}
                parejas = tuple(p for p in parejas if p.nombre not in cortadas)
            if con.id in self.keepassxc:
                parejas = tuple(replace(p, intervalo=min(intervalo, llavero.REMOTO_ABIERTO))
                                if p.nombre == model.LLAVERO else p for p in parejas)
            raices.append(pl.Raiz(con.id, parejas, intervalo))
        return raices

    def _mirar_keepassxc(self, ahora: float) -> None:
        """Mira en qué raíces atendidas está abierto su KeePassXC (`keepassxc_abierto()`).

        Se mira cada `PoliticaCambios.sondeo`, no en cada vuelta: en Windows es
        recorrer todos los procesos del equipo, y solo se hace si alguno se
        llama como KeePassXC (`hay_keepassxc()`, una pregunta para todas las
        raíces). Solo en las raíces que sirve el agente y llevan llavero; las
        demás las atiende su vigilante.

        Al abrirse y al cerrarse, toca una pasada del llavero enseguida (su
        marca vuelve a «nunca intentada»): al abrirse trae lo último antes de
        que se desbloquee la base, porque «Abrir llavero» no hace pasada si el
        agente atiende la raíz; al cerrarse sube lo que se guardó justo antes,
        que en modo `sync` no vigila nadie más. Si ya hay una pasada del
        llavero en marcha, el cambio se deja para la próxima mirada: esa
        pasada pudo empezar antes.
        """
        if ahora - self.keepassxc_mirado < self.cambios.sondeo:
            return
        self.keepassxc_mirado = ahora
        servidas: set[str] = set()
        abiertos: set[str] = set()
        alguno: bool | None = None
        for con in self.conexiones.values():
            if con.lock is None or con.servicio is None \
                    or not any(p.nombre == model.LLAVERO for p in con.servicio.parejas):
                continue
            servidas.add(con.id)
            if alguno is None:
                alguno = hay_keepassxc()
            if not alguno:
                continue
            try:
                if keepassxc_abierto(con.raiz):
                    abiertos.add(con.id)
            except OSError as e:
                diario(f"{con.nombre}: no he podido mirar si KeePassXC está abierto: {e}")
        en_marcha = (self.pasada.tarea.raiz, self.pasada.tarea.pareja) \
            if self.pasada is not None else None
        # Una raíz que el agente deja de servir (su ventana, una pausa) se
        # olvida sin más: no es que KeePassXC se haya cerrado.
        for uid in (abiertos ^ self.keepassxc) & servidas:
            if en_marcha == (uid, model.LLAVERO):
                # Su cambio se trata en la próxima mirada, con la pasada acabada.
                abiertos.symmetric_difference_update({uid})
                continue
            marca = self.marcas.get((uid, model.LLAVERO), pl.Marca())
            self.marcas[(uid, model.LLAVERO)] = pl.Marca(None, marca.fallos)
            nombre = self.conexiones[uid].nombre
            diario(f"{nombre}: KeePassXC abierto; el llavero se trae ahora y cada "
                   f"{llavero.REMOTO_ABIERTO / 60:.0f} min" if uid in abiertos
                   else f"{nombre}: KeePassXC cerrado; se sube lo que quede del llavero")
        self.keepassxc = abiertos

    def _cortada(self) -> dict | None:
        """Devuelve la pasada que cortó el instalador, mientras su pareja espere.

        Lanzarla antes de que caduque el `.lck` que dejó falla con «prior lock
        file found» y se avisaría de un fallo que no es (H-15). Solo esa
        pareja: las demás siguen como siempre.
        """
        c = self.cortada
        if c is None:
            return None
        if self.reloj() >= c["cortada"] + equipo.ESPERA_TRAS_CORTE:
            diario(f"[{c.get('unidad')}] {c.get('pareja')}: ya ha caducado el bloqueo "
                   f"de la pasada cortada; vuelve a su turno")
            self.cortada = None
            return None
        if not c.get("avisada"):
            c["avisada"] = True
            diario(f"[{c.get('unidad')}] {c.get('pareja')}: su pasada se cortó al parar "
                   f"el agente anterior; espera a que caduque su bloqueo")
        return c

    def _heredada(self) -> bool:
        """Indica si sigue viva la pasada que dejó en marcha el agente anterior.

        Se fue con SIGTERM al cerrar sesión, o el instalador lo terminó a la
        fuerza: la pasada es otro proceso y sigue. Mientras viva no se lanza
        otra: serían dos a la vez, quizá sobre la misma pareja.
        """
        if self.heredada is None:
            return False
        viva = equipo.pasada_viva()
        if viva is not None:
            texto = (f"sigue la pasada de {viva.get('pareja')} en {viva.get('unidad')} "
                     f"que dejó en marcha el agente anterior (pid {viva.get('pid')})")
            if self.retenido != texto:
                diario(f"no se lanza nada: {texto}")
                self.retenido = texto
            return True
        diario("ha acabado la pasada que dejó en marcha el agente anterior")
        self.heredada = None
        self.retenido = None
        return False

    def _decidir(self, ahora: float) -> pl.Decision:
        """Pide al planificador la siguiente tarea y la lanza.

        Returns:
            La decisión, con la tarea o el motivo de no lanzar nada.
        """
        entorno = replace(self.entorno, pausado=self.pausado)
        decision = pl.decidir(self._raices(), self.marcas, entorno, ahora,
                              self.ajustes.politica, urgentes=self.urgentes,
                              vigiladas=self.vigiladas, cambios=self.cambios)
        if decision.retenido != self.retenido:
            salvo = " salvo el llavero" if decision.retenido == pl.MOTIVO_RED_MEDIDA else ""
            diario(f"no se lanza nada{salvo}: {decision.retenido}" if decision.retenido
                   else "se vuelve a sincronizar")
            self.retenido = decision.retenido
        if decision.tarea is not None:
            self._lanzar(decision.tarea, ahora, self._acompanan(decision.tarea, entorno, ahora))
        return decision

    def _acompanan(self, tarea: pl.Tarea, entorno: pl.Entorno,
                   ahora: float) -> tuple[pl.Tarea, ...]:
        """Devuelve las demás parejas de la raíz a las que también les toca ya: van en el mismo `sync.py`.

        Cada `sync.py` es un Python que arranca (0,26 s de procesador de los
        0,65 de una pasada sin cambios): cuatro parejas con el mismo intervalo
        son cuatro arranques seguidos para hacer lo que hace uno. Se le
        pregunta al planificador qué tocaría después, quitando lo ya elegido,
        así que valen las mismas reglas (moderación, remoto sin conexión,
        espera tras un fallo). Solo si el `sync.py` de esa raíz ya ha dicho
        cómo le fue a una pareja con su parte (`Conexion.con_partes`): el de
        una unidad sin actualizar no lo escribe, y con varias parejas en un
        proceso no se sabría cuál falló. El llavero va siempre solo.
        """
        con = self.conexiones.get(tarea.raiz)
        if tarea.tipo != pl.PASADA or con is None or not con.con_partes \
                or tarea.pareja == model.LLAVERO:
            return ()
        raiz = next((r for r in self._raices() if r.clave == tarea.raiz), None)
        if raiz is None:
            return ()
        elegidas, otras = {tarea.pareja}, []
        while len(otras) < LOTE - 1:
            resto = replace(raiz, parejas=tuple(p for p in raiz.parejas
                                                if p.nombre not in elegidas and not p.llavero))
            if not resto.parejas:
                break
            # «Ya» es con un margen: cada pareja se apunta al acabar la suya,
            # así que las de un mismo intervalo van unos segundos una detrás
            # de otra y sin él nunca coincidirían. Una vez juntas, acaban a la
            # vez y siguen juntas.
            d = pl.decidir([resto], self.marcas, entorno, ahora + MARGEN_LOTE,
                           self.ajustes.politica, urgentes=self.urgentes,
                           vigiladas=self.vigiladas, cambios=self.cambios)
            if d.tarea is None or d.tarea.tipo != pl.PASADA:
                break
            elegidas.add(d.tarea.pareja)
            if d.tarea.por_cambios:
                # La adelantan sus cambios: esa espera a su calma, no se le
                # quita el margen (subiría a media ráfaga).
                sola = replace(raiz, parejas=tuple(p for p in raiz.parejas
                                                   if p.nombre == d.tarea.pareja))
                ya = pl.decidir([sola], self.marcas, entorno, ahora, self.ajustes.politica,
                                urgentes=self.urgentes, vigiladas=self.vigiladas,
                                cambios=self.cambios)
                if ya.tarea is None or ya.tarea.tipo != pl.PASADA:
                    continue
            otras.append(d.tarea)
        return tuple(otras)

    def _olvidar_vigiladas(self, uid: str) -> None:
        """Olvida lo recordado de las parejas vigiladas de una raíz, y deja sus avisos."""
        self.vigiladas = {k: v for k, v in self.vigiladas.items() if k[0] != uid}
        self.sin_avisos = {k: v for k, v in self.sin_avisos.items() if k[0] != uid}
        self.rearmar = {k for k in self.rearmar if k[0] != uid}
        self.rearmes = {k: v for k, v in self.rearmes.items() if k[0] != uid}
        if self.avisos_carpeta is not None:
            self.avisos_carpeta.dejar_raiz(uid)

    def _dejar_avisos(self, clave: tuple[str, str]) -> None:
        """Deja la vigilancia de una pareja que ya no se sirve, y olvida por qué se recorría."""
        self.sin_avisos.pop(clave, None)
        self.rearmar.discard(clave)
        self.rearmes.pop(clave, None)
        if self.avisos_carpeta is not None:
            self.avisos_carpeta.dejar(clave)

    def _soltar_avisos(self, uid: str) -> None:
        """Deja las vigilancias de una raíz antes de soltarla («Expulsar», «Bloquear»).

        En Linux no haría falta (desmontar con vigilancias puestas funciona),
        pero así nada queda abierto en ella, y si se vuelve a servir se ponen
        de nuevo.
        """
        if self.avisos_carpeta is not None:
            self.avisos_carpeta.dejar_raiz(uid)
        for clave in [k for k, v in self.vigiladas.items() if k[0] == uid and v.avisos]:
            del self.vigiladas[clave]

    def _vigilar(self, ahora: float) -> None:
        """Mira los ficheros locales de las parejas con `watch = true`.

        Con motor de avisos (`avisos_carpeta`), a cada pareja que empieza a
        servirse se le pone su vigilancia y ya no se recorre: cada vuelta se
        recogen sus avisos (`_recoger_avisos()`). Sin motor, o si su carpeta no
        admite avisos, se recorre: cada vuelta recoge el muestreo que haya
        terminado y, si no hay otro en marcha, pide el de las parejas a las que
        les toca (`pl.a_recorrer()`: a su ritmo, y no mientras la moderación
        retenga las pasadas). Ponerle la vigilancia a una pareja no espera a la
        moderación: es lo que deja apuntar los avisos mientras retiene.

        Solo se mira donde el servicio de la raíz está en marcha: sin pausa de
        su ventana (`Unidad.pausada`), sin ventana de runsync abierta, sin otro
        servicio y sin estar bloqueándose. Lo recordado de una pareja que deja
        de estarlo se olvida, y su vigilancia se deja: al volver, se parte de
        cero y los cambios de entretanto (hechos, por ejemplo, desde la
        ventana, que sincroniza por su cuenta) no disparan nada. Una pareja
        abandonada por grande no se vuelve a mirar en esta conexión.

        Recorrer y poner vigilancias va en un hilo (`hilo()`): en un pendrive
        tarda segundos y esta vuelta no espera.
        """
        raices = [r for r in self._raices() if not self.conexiones[r.clave].motivo]
        validas = {(r.clave, p.nombre) for r in raices for p in r.parejas if p.vigila}
        for clave in [k for k, v in self.vigiladas.items()
                      if k not in validas and not v.abandonada]:
            del self.vigiladas[clave]
            self._dejar_avisos(clave)
        self._recoger_avisos(ahora, validas)
        self._recoger_fotos(ahora, validas)
        if self.muestreo is not None or self.terminar or self.heredada is not None:
            return
        armar: list[tuple[str, str]] = []
        if self.avisos_carpeta is not None:
            for raiz in raices:
                for pareja in raiz.parejas:
                    clave = (raiz.clave, pareja.nombre)
                    if not pareja.vigila or math.isinf(pl.intervalo_de(raiz, pareja)):
                        continue
                    v = self.vigiladas.get(clave)
                    if v is None:
                        self.vigiladas[clave] = pl.Vigilada(avisos=True)
                        armar.append(clave)
                    elif v.avisos and clave in self.rearmar:
                        armar.append(clave)
                    elif self._toca_volver_a_oir(clave, v, ahora):
                        # Su carpeta vuelve a dejarse mirar (hay foto): se
                        # intenta oírla otra vez, que es lo barato.
                        veces = self.rearmes.get(clave, (0, 0.0))[0]
                        self.rearmes[clave] = (veces + 1, ahora)
                        del self.sin_avisos[clave]
                        # El cambio que ya vio el recorrido va como firme: el
                        # motor no sabe de él y no puede retirarlo.
                        self.vigiladas[clave] = pl.Vigilada(avisos=True, cambio=v.cambio,
                                                            movida=v.movida,
                                                            firme=v.cambio is not None)
                        armar.append(clave)
                        diario(f"[{self.conexiones[raiz.clave].nombre}] {pareja.nombre}: su "
                               f"carpeta vuelve a estar; se intenta oír sus avisos otra vez")
            self.rearmar -= set(armar)
        motivo = pl.moderacion(replace(self.entorno, pausado=self.pausado),
                               self.ajustes.politica)
        pasada = self.pasada
        ocupadas = sorted(pasada.claves) if pasada is not None else []
        claves = pl.a_recorrer(raices, self.vigiladas, ahora, self.cambios,
                               ocupadas=ocupadas, motivo=motivo,
                               con_bateria=self.entorno.con_bateria)
        if not claves and not armar:
            return
        trabajo = []
        for (raiz, pareja), poner in [(k, True) for k in armar] + [(k, False) for k in claves]:
            con = self.conexiones[raiz]
            trabajo.append(Mirar((raiz, pareja), con, con.raiz,
                                 con.raiz / con.servicio.locales[pareja], armar=poner,
                                 excluidos=con.servicio.excluidos.get(pareja, ())))
        self.muestreo = Muestreo(trabajo, self.cambios.tope_entradas, IGNORAR_CAMBIOS,
                                 self.avisos_carpeta)
        hilo(self.muestreo.correr)

    def _recoger_avisos(self, ahora: float, validas: set[tuple[str, str]]) -> None:
        """Pone en lo recordado de cada pareja los avisos del sistema que han llegado.

        Un cambio (o un desbordado, que además pide rehacer la vigilancia) es
        lo mismo que una foto distinta (`pl.avisado()`). No cuenta el de una
        pareja que ya no se vigila con avisos. El de una con su pasada en
        marcha lo escribe rclone: se apunta, pero `pl.tras_pasada()` lo borra
        al acabar ella, y lo que quede en la cola lo tira `_rehacer_foto()`.
        Una pérdida (su carpeta se fue, o no caben más vigilancias) la deja
        recorriéndose, y se dice.

        Args:
            ahora: La hora del reloj del agente.
            validas: Las parejas que se vigilan ahora.
        """
        if self.avisos_carpeta is None:
            return
        for clave, aviso in self.avisos_carpeta.recoger().items():
            v = self.vigiladas.get(clave)
            con = self.conexiones.get(clave[0])
            if clave not in validas or v is None or not v.avisos or con is None:
                continue
            if aviso.tipo == avisos_carpeta.PERDIDA:
                self._sin_avisos(con, clave, aviso.motivo)
                continue
            if aviso.tipo == avisos_carpeta.RETIRADO:
                # Lo que se avisó se ha deshecho solo (un temporal que nació
                # y murió): ya no hay nada que adelantar.
                self.vigiladas[clave] = pl.retirado(v)
                continue
            if aviso.tipo == avisos_carpeta.DESBORDADO:
                self.rearmar.add(clave)
            self.vigiladas[clave] = pl.avisado(v, ahora)

    def _toca_volver_a_oir(self, clave: tuple[str, str], v: pl.Vigilada, ahora: float) -> bool:
        """Indica si a una pareja que se recorre le toca intentar oír otra vez los avisos del sistema.

        Solo si los perdió por algo con arreglo (`VUELVEN`: movieron o
        borraron su carpeta), su carpeta se deja mirar otra vez (ya hay una
        foto), ha pasado `REARMAR_CADA` y no se ha intentado ya
        `REARMAR_INTENTOS` veces en esta conexión. Sin esto una pareja cuya
        carpeta se renombró y se volvió a crear se recorría para siempre.
        """
        veces, cuando = self.rearmes.get(clave, (0, -math.inf))
        return (self.sin_avisos.get(clave) in VUELVEN and not v.avisos and not v.abandonada
                and v.huella is not None and veces < REARMAR_INTENTOS
                and ahora - cuando >= REARMAR_CADA)

    def _sin_avisos(self, con: Conexion, clave: tuple[str, str], motivo: str) -> None:
        """Deja una pareja vigilada recorriéndose, sin avisos del sistema, y dice por qué.

        La primera foto es la de partida, enseguida: lo que cambió mientras se
        perdía la vigilancia no lo ve nadie, como lo de una pareja recién
        conectada.
        """
        if self.avisos_carpeta is not None:
            self.avisos_carpeta.dejar(clave)
        self.vigiladas[clave] = pl.Vigilada()
        self.sin_avisos[clave] = motivo
        self.rearmes[clave] = (self.rearmes.get(clave, (0, 0.0))[0], self.reloj())
        self.rearmar.discard(clave)
        diario(f"[{con.nombre}] {clave[1]}: sin avisos del sistema, se recorre su carpeta: "
               f"{motivo}")
        dlog(con.raiz, f"[{clave[1]}] watch: sin avisos del sistema, se recorre su carpeta: "
                       f"{motivo}")

    def _mirando(self, uid: str) -> bool:
        """Indica si hay una foto en marcha de alguna carpeta de esa raíz.

        Mientras dura, el hilo tiene la carpeta abierta: desmontar el
        contenedor en ese momento haría que VeraCrypt preguntara si forzar.
        """
        m = self.muestreo
        return m is not None and not m.hecho and any(x.clave[0] == uid for x in m.trabajo)

    def _recoger_fotos(self, ahora: float, validas: set[tuple[str, str]]) -> None:
        """Pone en lo recordado de cada pareja la foto del muestreo terminado.

        No cuenta la foto de una pareja que ya no se vigila, de una unidad que
        se fue (aunque volviera), ni de una cuya pasada está en marcha o ha
        empezado o acabado mientras se miraba: lo que ve ahí lo ha escrito
        rclone, no la persona. La pareja que supera el tope o cuya carpeta cae
        fuera de la raíz se abandona, y se dice una vez en el diario y en el de
        la raíz. También se dice una vez cuando `PoliticaCambios.fotos_fallidas`
        recorridos seguidos de una pareja no dan foto (y cuando vuelve a darla):
        sin esa línea, una carpeta que no se deja mirar parece una quieta.

        Args:
            ahora: La hora del reloj del agente.
            validas: Las parejas que se vigilan ahora.
        """
        m = self.muestreo
        if m is None or not m.hecho:
            return
        self.muestreo = None
        pasada = self.pasada
        en_curso = pasada.claves if pasada is not None else set()
        for mirar in m.trabajo:
            clave = mirar.clave
            con = self.conexiones.get(clave[0])
            if mirar.armar:
                self._recoger_armado(m, mirar, con, ahora, validas)
                continue
            if con is not mirar.con or clave not in validas or clave in m.descartar \
                    or clave in en_curso:
                continue
            antes = self.vigiladas.get(clave, pl.Vigilada())
            if clave in m.fuera:
                self._fuera_de_la_raiz(con, clave, ahora)
                continue
            despues = pl.observar(antes, m.fotos.get(clave), ahora, self.cambios)
            self.vigiladas[clave] = despues
            if pl.se_abandona(antes, despues):
                diario(f"[{con.nombre}] {clave[1]}: más de {self.cambios.tope_entradas} "
                       f"entradas; deja de vigilarse y sigue por su intervalo")
                dlog(con.raiz, f"[{clave[1]}] watch: más de {self.cambios.tope_entradas} "
                               f"entradas; no se vigila, manda el intervalo")
            elif pl.se_queda_sin_foto(antes, despues, self.cambios):
                # Sin foto no hay cambio que ver: una carpeta que no se deja
                # mirar y una quieta serían lo mismo sin esta línea.
                veces = self.cambios.fotos_fallidas
                diario(f"[{con.nombre}] {clave[1]}: no se puede mirar su carpeta "
                       f"({veces} recorridos seguidos); no se ven sus cambios y "
                       f"manda el intervalo")
                dlog(con.raiz, f"[{clave[1]}] watch: no se puede mirar su carpeta "
                               f"({veces} recorridos seguidos); manda el intervalo")
            elif pl.vuelve_a_haber_foto(antes, despues, self.cambios):
                diario(f"[{con.nombre}] {clave[1]}: su carpeta vuelve a poder mirarse")
                dlog(con.raiz, f"[{clave[1]}] watch: su carpeta vuelve a poder mirarse")

    def _fuera_de_la_raiz(self, con: Conexion, clave: tuple[str, str], ahora: float) -> None:
        """Abandona una pareja cuya carpeta, con los enlaces resueltos, cae fuera de su raíz."""
        self.vigiladas[clave] = pl.Vigilada(None, None, ahora, abandonada=True)
        diario(f"[{con.nombre}] {clave[1]}: su carpeta cae fuera de la raíz; "
               f"no se vigilan sus cambios")
        dlog(con.raiz, f"[{clave[1]}] watch: su carpeta cae fuera de la raíz; no se vigila")

    def _recoger_armado(self, m: Muestreo, mirar: Mirar, con: Conexion | None, ahora: float,
                        validas: set[tuple[str, str]]) -> None:
        """Recoge lo que dijo el motor al ponerle la vigilancia a una pareja.

        Lo puesto para una pareja que ya no se sirve, o de una conexión
        anterior de su raíz, se deja y no cuenta. Si no se pudo poner, la
        pareja se recorre y se dice por qué.
        """
        clave = mirar.clave
        v = self.vigiladas.get(clave)
        motivo = m.armadas.get(clave, "no se llegó a poner su vigilancia")
        if con is not mirar.con or clave not in validas or v is None or not v.avisos:
            if motivo is None and self.avisos_carpeta is not None:
                self.avisos_carpeta.dejar(clave)
            return
        if clave in m.fuera:
            self._fuera_de_la_raiz(con, clave, ahora)
        elif motivo == avisos_carpeta.DEJADA:
            del self.vigiladas[clave]       # se dejó a medias: se vuelve a poner
        elif motivo is not None:
            self._sin_avisos(con, clave, motivo)

    def _rehacer_foto(self, clave: tuple[str, str], ahora: float) -> None:
        """Deja una pareja lista para tomar su foto de después de una pasada.

        La pasada, buena o mala, ha escrito en su carpeta: la foto siguiente es
        la de partida y no dispara nada (`pl.tras_pasada()`), y se pide ya, sin
        esperar al sondeo. Si había un muestreo en marcha, lo que vea de esa
        pareja es de antes de acabar la pasada y no cuenta.

        Args:
            clave: `(raíz, pareja)` de la pasada que acaba de terminar.
            ahora: La hora del reloj del agente.
        """
        if self.muestreo is not None:
            self.muestreo.descartar.add(clave)
        antes = self.vigiladas.get(clave)
        if antes is not None and antes.avisos:
            # Lo que escribió la pasada se tira; si hizo desbordar, se rehace.
            tirado = None if self.avisos_carpeta is None \
                else self.avisos_carpeta.descartar(clave)
            if tirado is not None and tirado.tipo == avisos_carpeta.DESBORDADO:
                self.rearmar.add(clave)
            self.vigiladas[clave] = pl.tras_pasada(antes, None, ahora)
        elif antes is not None:
            self.vigiladas[clave] = replace(pl.tras_pasada(antes, None, ahora),
                                            revisada=None)

    def _lanzar(self, tarea: pl.Tarea, ahora: float,
                otras: tuple[pl.Tarea, ...] = ()) -> None:
        """Lanza una tarea: una pasada (el `sync.py` de la raíz) o una sonda del remoto.

        Con `otras`, ese mismo `sync.py` pasa también esas parejas de la raíz,
        detrás (`_acompanan()`).

        Antes de una pasada se comprueba otra vez que el lock sigue siendo
        nuestro y se lee de nuevo el config de la raíz (`leer_config()`): el
        agente solo lo relee si cambia su fecha, y un config editado conservándola
        (en una unidad cuyo `sync.py` no comprueba nada) correría sin mirar. Si
        ya no vale, no se lanza, y la raíz queda sin servicio con su motivo.
        """
        con = self.conexiones[tarea.raiz]
        if tarea.tipo == pl.PASADA and not self._lock_es_nuestro(con):
            # Justo antes de lanzar, otra vez: un runsync de antes escribe su
            # lock sin mirar, y el que haya ahí es el servicio.
            con.lock = None
            diario(f"[{con.nombre}] el lock ya no es mío; no lanzo {tarea.pareja}")
            return
        if tarea.tipo == pl.PASADA:
            try:
                leer_config(con.raiz)
            except ValueError as e:
                self._sin_servicio(con, e)
                con.firma = ()              # la vuelta que viene lo lee entero otra vez
                diario(f"[{con.nombre}] no lanzo {tarea.pareja}: {e}")
                return
        todas = (tarea, *otras)
        pedidas = {(t.raiz, t.pareja) for t in todas if t.urgente}
        if pedidas:
            self.urgentes = [u for u in self.urgentes if u not in pedidas]
        if tarea.tipo == pl.SONDA:
            args = orden_sonda(con.raiz, tarea.remoto)
            if args is None:
                # Sin rclone para este equipo no hay con qué preguntar: se hace
                # como si el remoto contestara. Así el fallo que se sospechaba
                # de red cuenta como fallo de la pareja y espera lo suyo;
                # tomarlo por red otra vez la relanzaría en cada vuelta.
                self._fin_de_sonda(con, tarea.remoto, 0, "", ahora)
                return
            cwd = app(con.raiz)             # rclone.conf resuelve contra aquí
            que = f"¿contesta {tarea.remoto}?"
        else:
            # `--`: lo que sigue es un nombre, nunca una opción de sync.py.
            args = [python(), str(app(con.raiz) / "sync.py"), "--", *(t.pareja for t in todas)]
            cwd = equipo.DIR
            que = ", ".join(t.pareja for t in todas)
        salida = equipo.DIR / "pasada.out"
        try:
            equipo.DIR.mkdir(parents=True, exist_ok=True)
            with salida.open("wb") as f:
                # En su propio grupo: si hay que cortarla
                # (`install/agente.parar_agente()`, pasado su plazo), se corta
                # con su rclone. Y con prioridad baja: nadie la está mirando.
                proc = lanzar(args, stdout=f, stderr=subprocess.STDOUT,
                              **_opciones_hijo(cwd, separado=tarea.tipo == pl.PASADA,
                                               baja=True))
            if not IS_WIN and getattr(proc, "pid", None):
                bajar_prioridad(proc.pid)
        except OSError as e:
            diario(f"[{con.nombre}] no he podido lanzar {que}: {e}")
            if tarea.tipo == pl.PASADA:
                expulsion = self.expulsiones.get(tarea.raiz)
                for t in todas:
                    self.marcas[(t.raiz, t.pareja)] = pl.registrar(
                        self.marcas.get((t.raiz, t.pareja), pl.Marca()), FALLO, ahora)
                    # Si era lo que «Expulsar» subía antes de soltarla, se dice
                    # con el resultado: ya no está en la cola y no va a subir.
                    if expulsion is not None and t.pareja in expulsion.subir \
                            and t.pareja not in expulsion.sin_subir:
                        expulsion.sin_subir.append(t.pareja)
            return
        self.pasada = Pasada(proc, tarea, ahora, salida, con.nombre, tuple(otras))
        if tarea.tipo == pl.PASADA:
            equipo.apuntar_pasada({"pid": getattr(proc, "pid", None), "agente": os.getpid(),
                                   "raiz": tarea.raiz,
                                   "unidad": con.nombre, "pareja": tarea.pareja,
                                   **({"parejas": [t.pareja for t in todas]} if otras else {}),
                                   "desde": store.stamp()})
        diario(f"[{con.nombre}] {que}" + (" (a petición)" if tarea.urgente
                                          else " (han cambiado sus ficheros)"
                                          if tarea.por_cambios else ""))

    def _fin_de_pasada(self, ahora: float) -> None:
        """Recoge el resultado de la pasada que haya acabado.

        Lo apunta en el planificador, en el diario de la raíz y en su lock, y
        avisa solo si la pareja EMPIEZA a fallar. Un fallo que parece de red
        dispara la sonda.
        """
        pasada = self.pasada
        if pasada is None:
            return
        rc = pasada.proc.poll()
        if rc is None:
            return
        self.pasada = None
        if store.read_json(equipo.pasada_json()).get("agente") == os.getpid():
            equipo.pasada_json().unlink(missing_ok=True)
        texto = ""
        try:
            with pasada.salida.open("rb") as f:
                f.seek(0, os.SEEK_END)
                # Con varias parejas en el proceso se lee (casi) entera: el
                # parte de la primera va muy arriba si otra tardó en mover lo
                # suyo, y sin él contaría como que falló.
                f.seek(max(0, f.tell() - (SALIDA_DE_LOTE if pasada.otras else COLA_SALIDA)))
                texto = f.read().decode("utf-8", errors="replace")
        except OSError:
            pass
        pasada.salida.unlink(missing_ok=True)
        tarea = pasada.tarea
        con = self.conexiones.get(tarea.raiz)
        if con is None or not presente(con.raiz):
            # Una unidad desenchufada a mitad de pasada no es un fallo de la
            # pareja y no se avisa de nada.
            diario(f"[{pasada.nombre}] la unidad se ha ido a mitad de "
                   f"{tarea.pareja or 'la comprobación'}; no cuenta")
            return
        segundos = ahora - pasada.desde
        if tarea.tipo == pl.SONDA:
            self._fin_de_sonda(con, tarea.remoto, rc, texto, ahora)
            return

        # Lo que cuenta el propio `sync.py` de cada pareja; uno de antes no dice nada.
        partes = parte.leer(texto)
        if tarea.pareja in partes:
            con.con_partes = True           # desde ahora sus parejas pueden ir juntas
        if not pasada.otras:
            self._fin_de_pareja(con, tarea, rc, resultado(rc, texto), texto, segundos,
                                partes.get(tarea.pareja), ahora)
            return
        # Varias parejas en un proceso: cada una con su parte y con su trozo de
        # la salida. La que no llegó a escribirlo (el proceso murió antes)
        # cuenta como fallo, con el código del proceso.
        trozos = parte.trozos(texto)
        resto = parte.resto(texto)          # lo que salió tras el último parte
        for i, t in enumerate(pasada.tareas):
            dicho = partes.get(t.pareja)
            if dicho is None and rc == 0:
                # Sin su parte pero con el proceso acabado en 0: `sync.py` sale
                # con 1 si alguna falla, así que esta no falló (su parte quedó
                # fuera de lo leído). No se le apunta un fallo que no tuvo.
                suyo, codigo, como = "", 0, OK
            elif dicho is None:
                # El proceso murió antes de escribirlo: lo que quedó al final
                # de la salida es de la que estaba en marcha, y es lo que dice
                # si fue la red.
                suyo, codigo = resto, rc
                como = resultado(codigo, suyo)
            elif dicho.rc == parte.SALTADA:
                suyo, codigo, como = trozos.get(t.pareja, ""), 0, SALTADA
            else:
                suyo, codigo = trozos.get(t.pareja, ""), dicho.rc
                como = resultado(codigo, suyo)
            self._fin_de_pareja(con, t, codigo, como, suyo, segundos, dicho, ahora,
                                primera=i == 0)

    def _fin_de_pareja(self, con: Conexion, tarea: pl.Tarea, rc: int, como: str, texto: str,
                       segundos: float, dicho: "parte.Parte | None", ahora: float,
                       primera: bool = True) -> None:
        """Apunta cómo le fue a una pareja en la pasada que acaba de terminar.

        Args:
            con: La conexión de su raíz.
            tarea: La pareja.
            rc: Su código: el del proceso si iba sola, el de su parte si no.
            como: `OK`, `FALLO`, `RED` o `SALTADA`.
            texto: Su salida: la del proceso, o su trozo.
            segundos: Lo que duró el proceso entero.
            dicho: Su parte, si `sync.py` lo escribió.
            primera: Si es la primera del proceso: es la que carga con el
                proceso y con su duración en la cuenta de lo gastado.
        """
        clave = (tarea.raiz, tarea.pareja)
        consumo.apuntar(con.id, consumo.Cuenta(
            1, int(dicho is not None and dicho.vacia),
            int(primera) + (dicho.ordenes if dicho is not None else int(como != SALTADA)),
            segundos if primera else 0.0, dicho.escrito if dicho is not None else 0))
        antes = self.marcas.get(clave, pl.Marca())
        despues = pl.registrar(antes, como, ahora,
                               vacia=dicho is not None and dicho.vacia,
                               por_cambios=tarea.por_cambios, urgente=tarea.urgente)
        self.marcas[clave] = despues
        self._decir_ritmo(con, tarea.pareja, antes, despues)
        self._rehacer_foto(clave, ahora)
        if como == FALLO or como == RED:
            dlog(con.raiz, f"[{tarea.pareja}] FALLÓ (rc={rc}, {segundos:.0f}s); salida:")
            for linea in texto.splitlines()[-12:]:
                dlog(con.raiz, f"[{tarea.pareja}]   {linea}")
        elif como == SALTADA:
            dlog(con.raiz, f"[{tarea.pareja}] saltada: requiere --resync; ejecútalo a "
                           f"mano desde la ventana")
        else:
            dlog(con.raiz, f"[{tarea.pareja}] OK ({segundos:.0f}s)")
            if como == OK:
                self.ultima_buena = ahora
        diario(f"[{con.nombre}] {tarea.pareja}: {TEXTO_RESULTADO[como]} "
               f"(rc={rc}, {segundos:.0f}s)")
        self._apuntar_en_lock(con, tarea.pareja, como, rc, segundos)
        if tarea.pareja == model.LLAVERO:
            self._copias_del_llavero(con, ahora, ya=True)

        expulsion = self.expulsiones.get(tarea.raiz)
        if expulsion is not None and como != OK and tarea.pareja not in expulsion.sin_subir:
            expulsion.sin_subir.append(tarea.pareja)
        if como == RED:
            # ¿De verdad es la red? La sonda va ya: si el remoto contesta,
            # aquel fallo era de la pareja y se apunta como tal
            # (`_fin_de_sonda`).
            self.sospechas[clave] = Sospecha(tarea.remoto, antes, despues)
            self.entorno = pl.sin_conexion(self.entorno, tarea.raiz, tarea.remoto, ahora)
        else:
            # Un resultado que no es de red cierra la duda de esa pareja: su
            # pasada ya dice cómo está, y no se vuelve a apuntar el fallo de
            # antes encima.
            self.sospechas.pop(clave, None)
            if pl.empieza_a_fallar(antes, despues):
                avisar(f"{con.nombre}: falla {tarea.pareja}", self._donde_mirar(con), True)
        # Saltada no es un fallo para el planificador (vuelve a su intervalo),
        # pero la pareja deja de sincronizarse sin que nadie lo vea: se avisa
        # cuando EMPIEZA a pedir el --resync, como con un fallo, y no otra vez
        # hasta que deje de pedirlo.
        if como == SALTADA and clave not in self.saltadas:
            self.saltadas.add(clave)
            avisar(f"{tarea.pareja} necesita --resync",
                   f"{con.nombre}: no se sincroniza sola. El resync se aprueba en "
                   f"«Reparación». {self._donde_mirar(con)}", True)
        elif como in (OK, FALLO):           # una de red no dice cómo está la pareja
            self.saltadas.discard(clave)

    def _fin_de_sonda(self, con: Conexion, remoto: str, rc: int, texto: str,
                      ahora: float) -> None:
        """Recoge el resultado de una sonda al remoto.

        Si contesta, el fallo sospechado de red de cada pareja de ese remoto
        era de la pareja y se apunta como tal, salvo en la que ya ha hecho otra
        cosa desde entonces; si no, el remoto queda sin conexión hasta el
        próximo sondeo.
        """
        clave = (con.id, remoto)
        dudosas = {k: v for k, v in self.sospechas.items()
                   if k[0] == con.id and v.remoto == remoto}
        for k in dudosas:
            del self.sospechas[k]
        # Un error que no es de red (credenciales, una ruta) es un remoto que
        # contesta: no hay nada que esperar.
        if rc == 0 or not moderacion.es_de_red(texto):
            self.entorno = pl.con_conexion(self.entorno, con.id, remoto)
            apuntadas = False
            for (_, pareja), sospecha in dudosas.items():
                if self.marcas.get((con.id, pareja)) != sospecha.tras:
                    continue
                apuntadas = True
                despues = pl.registrar(sospecha.antes, FALLO, ahora)
                self.marcas[(con.id, pareja)] = despues
                diario(f"[{con.nombre}] {remoto} contesta: el fallo de {pareja} no era "
                       f"de la red")
                if pl.empieza_a_fallar(sospecha.antes, despues):
                    avisar(f"{con.nombre}: falla {pareja}", self._donde_mirar(con), True)
            if not apuntadas and clave in self.sin_red_avisado:
                self.sin_red_avisado.discard(clave)
                diario(f"[{con.nombre}] vuelve la conexión con {remoto}")
            self._despertar(con.id, remoto)
            return
        self.entorno = pl.sin_conexion(
            self.entorno, con.id, remoto,
            ahora + pl.sondeo(self.ajustes.politica, self.avisa_la_red()))
        if clave not in self.sin_red_avisado:
            self.sin_red_avisado.add(clave)
            avisar(f"{con.nombre}: sin conexión con {remoto}",
                   "Sus parejas esperan a que vuelva la red; no hace falta hacer nada.")

    def avisa_la_red(self) -> bool:
        """Indica si el sistema le dice ahora al agente cuándo vuelve la red."""
        return bool(self.avisos_de_red is not None
                    and getattr(self.avisos_de_red, "activa", False))

    def _cambios_de_red(self, ahora: float) -> None:
        """Sondea los remotos sin conexión cuando se calma una ráfaga de avisos de red.

        Una sonda por remoto y por ráfaga (`pl.red_asentada()`); con una tarea
        en marcha espera a que acabe. Si no hay ningún remoto sin conexión, la
        ráfaga se olvida sin más.
        """
        if not pl.red_asentada(self.cambio_de_red, ahora, self.pasada is not None):
            return
        self.cambio_de_red = None
        # La red por la que se sale ya es la que va a ser: si es de uso medido.
        self.entorno_leido = -math.inf
        if self.entorno.sin_conexion:
            self.entorno = pl.sondear_ya(self.entorno, ahora)
            diario("la red ha cambiado: se prueban ya los remotos sin conexión")

    def _donde_mirar(self, con: Conexion) -> str:
        """Devuelve dónde mirar para ver qué ha pasado.

        Depende de si es la raíz del equipo o una unidad.
        """
        unidad = self.ajustes.unidades.get(con.id)
        if unidad is not None and unidad.es_raiz:
            return f"Abre la ventana de {APP_NAME} en este equipo para ver qué ha pasado."
        return f"Abre {APP_NAME} desde la unidad para ver qué ha pasado."

    def _al_dia_el_lock(self, con: Conexion) -> None:
        """Pone en el lock de la raíz las parejas y el intervalo que el agente atiende ahora.

        El lock lo escribe el agente al tomar la raíz y tras cada pasada. Si la
        config cambia mientras la atiende (la ventana añade el llavero, quita
        una pareja, cambia el intervalo), se quedaba con lo de antes, y
        `llavero.atiende_el_servicio()` daba por no atendido el llavero. Lo
        llama `_contrato()` en cada vuelta que sirve la raíz con su lock, y sin
        nada que cambiar no toca el disco: compara con `con.lock`, que solo
        cambia cuando la escritura ha salido. Si la escritura falla (fichero en
        uso, unidad de solo lectura), se reintenta cada `RELEER_REGISTROS`, sin
        esperar a una pasada ni a un cambio de config.

        Args:
            con: La conexión, con el servicio que atiende ahora.
        """
        if con.lock is None or con.servicio is None:
            return
        parejas = [p.nombre for p in con.servicio.parejas]
        if con.lock.get("pairs") == parejas \
                and con.lock.get("interval_min") == con.servicio.minutos:
            return
        ahora = self.reloj()
        if con.intento_lock is not None and ahora - con.intento_lock < RELEER_REGISTROS:
            return
        if not self._lock_es_nuestro(con, de_memoria=True):
            return
        con.intento_lock = ahora
        nuevo = {**con.lock, "pairs": parejas, "interval_min": con.servicio.minutos}
        if self._escribir_lock(con, nuevo):
            con.lock = nuevo
            con.intento_lock = None

    def _escribir_lock(self, con: Conexion, datos: dict) -> bool:
        """Escribe `datos` en el `daemon.lock.json` de la raíz, si sigue dentro de ella.

        Returns:
            `True` si se ha escrito; `False` si la ruta sale de la raíz o el
            fichero no se deja escribir (`store.write_json()`).
        """
        destino = en_la_raiz(con.raiz, con.raiz / penwatch.DAEMON_LOCK_REL)
        return destino is not None and store.write_json(destino, datos)

    def _apuntar_en_lock(self, con: Conexion, pareja: str, como: str, rc: int,
                         segundos: float) -> None:
        """Deja en el lock lo mismo que el servicio de runsync tras cada ciclo."""
        if con.lock is None or not self._lock_es_nuestro(con):
            return
        texto = {OK: f"OK ({segundos:.0f}s)", SALTADA: "saltada (requiere --resync manual)"
                 }.get(como, f"ERROR rc={rc}")
        con.lock.setdefault("last_results", {})[pareja] = texto
        con.lock["last_cycle"] = store.stamp()
        con.lock["arranque"] = store.arranque_del_sistema()     # cancela la deriva del reloj
        self._escribir_lock(con, con.lock)

    def _cifrada(self, uid: str) -> equipo.Unidad | None:
        """Devuelve la raíz cifrada de ese id, o la única que haya si no se dice."""
        cifradas = self.ajustes.cifradas
        if uid:
            return cifradas.get(uid)
        return next(iter(cifradas.values())) if len(cifradas) == 1 else None

    def _al_iniciar(self, ahora: float) -> None:
        """Pide la contraseña de las raíces cifradas al iniciar sesión.

        Es `pedir_al_iniciar`, UNA vez por arranque del agente. Se espera a
        haber recorrido lo bastante para saber que no está ya abierta (una raíz
        cuenta al verla `ESTABLE` veces). Si se cancela, no se vuelve a pedir
        hasta «Desbloquear»: es la regla de «una vez por conexión» de las
        unidades cifradas.
        """
        if self.recorridos < ESTABLE:
            return
        for uid, unidad in self.ajustes.cifradas.items():
            if uid in self.pedidas:
                continue
            self.pedidas.add(uid)
            if (self.ajustes.pedir_al_iniciar and unidad.modo != equipo.NADA
                    and uid not in self.conexiones and uid not in self.vistas):
                self._desbloquear(unidad, ahora, "al iniciar sesión")

    def _desbloquear(self, unidad: equipo.Unidad, ahora: float, por: str = "",
                     abrir: bool = False, explorar: bool = False) -> bool:
        """Le pide a VeraCrypt que abra la raíz cifrada. No espera.

        Abierta es cuando el recorrido VE su id con el `.hc` retenido.

        Args:
            unidad: La raíz cifrada.
            ahora: La hora del reloj del agente.
            por: Por qué se desbloquea, para el diario.
            abrir: Abrir su ventana en cuanto se vea abierta («Configurar» en
                la bandeja).
            explorar: Abrirla en el explorador de archivos en cuanto se vea
                abierta («Abrir en explorador» en la bandeja).

        Returns:
            `True` si lanzó VeraCrypt.
        """
        nombre = nombre_guardado(unidad, unidad.id)
        if unidad.id in self.conexiones or unidad.id in self.vistas:
            diario(f"{nombre}: ya está abierta")
            return False
        if unidad.id in self.bloqueos:
            diario(f"{nombre}: se está bloqueando; desbloquear después")
            return False
        if unidad.id in self.desbloqueos:
            # VeraCrypt ya está pidiendo la contraseña: una segunda ventana
            # suya no ayuda.
            self.desbloqueos[unidad.id].abrir |= abrir
            self.desbloqueos[unidad.id].explorar |= explorar
            diario(f"{nombre}: ya se está desbloqueando")
            return False
        try:
            hay = Path(unidad.contenedor).is_file()
        except OSError:
            hay = False
        if not hay:
            avisar(f"{nombre}: no encuentro su contenedor",
                   f"Tenía que estar en {unidad.contenedor}.", True)
            return False
        ocupado = punto_ocupado(unidad)
        if ocupado:
            avisar(f"{nombre}: no la desbloqueo", ocupado, True)
            return False
        exe = veracrypt_de_la_raiz()
        cmd = penwatch.veracrypt_command(None, Path(unidad.contenedor),
                                         unidad.letra or unidad.ruta, respaldo=exe)
        if cmd is None:
            avisar(f"{nombre}: no la puedo desbloquear",
                   SIN_VERACRYPT if exe is None else
                   "No hay escritorio donde VeraCrypt pida la contraseña", True)
            return False
        if not unidad.letra:
            try:
                Path(unidad.ruta).mkdir(parents=True, exist_ok=True)
            except OSError:
                pass                # que lo diga VeraCrypt
        copia = Copia.antes_de(cmd)
        try:
            proc = lanzar(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          **_opciones_hijo(equipo.DIR, separado=True))
        except OSError as e:
            avisar(f"{nombre}: no he podido lanzar VeraCrypt", str(e), True)
            return False
        self.desbloqueos[unidad.id] = Desbloqueo(ahora, proc, abrir=abrir, copia=copia,
                                                 explorar=explorar)
        diario(f"{nombre}: desbloqueando" + (f" ({por})" if por else "")
               + f" en {unidad.ruta}; la contraseña la pide VeraCrypt")
        return True

    def _seguir_desbloqueos(self, ahora: float) -> None:
        """Olvida los «Desbloquear» que no han acabado en la raíz abierta.

        Un «Desbloquear» así se ha cancelado (o la contraseña no era):
        VeraCrypt ha salido y, pasado un rato, no se ve. Se olvida para que la
        bandeja vuelva a ofrecerlo. Con un VeraCrypt que no sale (el de
        escritorio de Linux se queda abierto), al acabarse `ESPERA_ABRIR`.
        Lo que un atajo pidió abrir de una unidad bloqueada (`al_abrirse`) se
        olvida también al acabarse `ESPERA_ABRIR`: desbloqueada mucho después,
        abrirla sola sorprendería.
        """
        for uid, pedido in list(self.al_abrirse.items()):
            if ahora - pedido.desde >= ESPERA_ABRIR:
                del self.al_abrirse[uid]
                que = " ni ".join(q for q, si in (("su ventana", pedido.abrir),
                                                  ("su carpeta", pedido.explorar)) if si)
                diario(f"{nombre_guardado(self.ajustes.unidades.get(uid), uid)}: no se ha "
                       f"desbloqueado a tiempo; ya no abro {que}")
        for uid, d in list(self.desbloqueos.items()):
            if uid in self.conexiones or uid in self.vistas:
                continue
            if d.salio is None and not _sigue_vivo(d.proc, d.copia):
                d.salio = ahora
            if ((d.salio is not None and ahora - d.salio >= GRACIA_ABRIR)
                    or ahora - d.desde >= ESPERA_ABRIR):
                del self.desbloqueos[uid]
                unidad = self.ajustes.unidades.get(uid)
                diario(f"{nombre_guardado(unidad, uid)}: no se ha "
                       f"desbloqueado (¿contraseña cancelada?); sigue bloqueada")

    def _bloqueos(self, ahora: float) -> None:
        """Lleva los «Bloquear» pedidos hasta ver la raíz cerrada de verdad.

        Primero se espera a que nada lo impida (la pareja en curso, la foto de
        una de sus carpetas durante `ESPERA_VENTANA` como mucho, su ventana);
        si lleva llavero, se cierra (`_cerrar_llavero()`); luego VeraCrypt
        desmonta y se espera a verlo cerrado. Es la raíz del equipo cifrada o,
        pedida por un evento de la sesión (`Bloqueo.por`), también una unidad
        con vestíbulo (`Bloqueo.fisica`). Con `por` no hay nadie delante:
        VeraCrypt va desatendido, una ventana abierta hace abandonar en el
        acto y lo que no se pudo se guarda para decirlo al volver
        (`_no_bloqueada()`).
        """
        for uid, b in list(self.bloqueos.items()):
            unidad = self.ajustes.unidades.get(uid)
            if unidad is None or not (unidad.cifrada or b.fisica is not None):
                del self.bloqueos[uid]
                continue
            nombre = nombre_guardado(unidad, uid)
            con = self.conexiones.get(uid)
            if b.proc is None:
                if con is None and uid not in self.fantasmas:
                    del self.bloqueos[uid]
                    diario(f"{nombre}: ya estaba bloqueada")
                    continue
                if self.pasada is not None and self.pasada.tarea.raiz == uid:
                    continue                # acaba la pareja en curso
                if self._mirando(uid) and ahora - b.desde < ESPERA_VENTANA:
                    continue                # y la foto en curso: tiene la carpeta abierta
                if con is not None and _registro_vivo(
                        con.raiz, penwatch.UI_LOCK_REL) is not None:
                    # Su ventana pide bloquear y se cierra; se le da un rato. A
                    # un evento de la sesión, no: nadie va a cerrarla.
                    if b.por or ahora - b.desde >= ESPERA_VENTANA:
                        del self.bloqueos[uid]
                        self._no_bloqueada(uid, b, f"{nombre}: no la bloqueo",
                                           "Su ventana sigue abierta. Ciérrala y vuelve a "
                                           "pedirlo.", "su ventana estaba abierta")
                    continue
                if con is not None and not self._cerrar_llavero(con, b, ahora):
                    continue
                cmd = orden_bloquear(unidad, desatendido=bool(b.por),
                                     raiz=b.raiz if b.fisica is not None else None)
                if cmd is None:
                    del self.bloqueos[uid]
                    self._no_bloqueada(uid, b, f"{nombre}: no la puedo bloquear",
                                       SIN_VERACRYPT,
                                       "no hay VeraCrypt instalado en este equipo")
                    continue
                self._soltar_avisos(uid)
                if con is not None:
                    self._soltar(con)
                b.copia = Copia.antes_de(cmd)
                try:
                    b.proc = lanzar(cmd, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    **_opciones_hijo(equipo.DIR, separado=True))
                except OSError as e:
                    del self.bloqueos[uid]
                    self._no_bloqueada(uid, b, f"{nombre}: no he podido lanzar VeraCrypt",
                                       str(e), f"no he podido lanzar VeraCrypt ({e})")
                    continue
                b.lanzado = ahora
                diario(f"{nombre}: bloqueando ({TEXTO_EVENTO[b.por].lower()}); si algo "
                       f"tiene un fichero abierto dentro, se queda abierta" if b.por else
                       f"{nombre}: bloqueando; si algo tiene un fichero abierto "
                       f"dentro, VeraCrypt pregunta si forzar")
                continue
            if (bloqueada_unidad(b.fisica, b.raiz) if b.fisica is not None
                    else bloqueada(unidad)):
                del self.bloqueos[uid]
                self.desbloqueos.pop(uid, None)
                self.fantasmas.discard(uid)
                self.sin_bloquear.pop(uid, None)
                if con is not None:
                    # Una unidad sigue a la vista cerrada: «ya pedida», como al expulsarla.
                    self._desconectar(uid, ahora,
                                      {uid: b.fisica} if b.fisica is not None else {})
                diario(f"{nombre}: bloqueada")
                continue
            salio = not _sigue_vivo(b.proc, b.copia)
            if (salio and ahora - b.lanzado >= GRACIA_DESMONTAJE) \
                    or ahora - b.lanzado >= ESPERA_DESMONTAJE:
                del self.bloqueos[uid]
                self._no_bloqueada(uid, b, f"{nombre}: sigue abierta",
                                   "VeraCrypt no la ha cerrado: si un programa tiene un "
                                   "fichero abierto dentro, ciérralo y vuelve a bloquear.",
                                   "un programa tenía un fichero abierto dentro")

    def _no_bloqueada(self, uid: str, b: Bloqueo, titulo: str, texto: str,
                      motivo: str) -> None:
        """Dice que un «Bloquear» no ha salido: en el acto, o al volver si lo pidió la sesión.

        Pedido por una persona, es un aviso ya. Pedido por un evento de la
        sesión (`Bloqueo.por`) no hay nadie delante: se guarda en
        `sin_bloquear` y sale una vez al volver (`_decir_sin_bloquear()`).

        Args:
            uid: El id de la raíz.
            b: El bloqueo, ya quitado de `bloqueos`.
            titulo: El título del aviso inmediato.
            texto: Su texto.
            motivo: Lo que se dice al volver, en minúsculas y sin punto.
        """
        if not b.por:
            avisar(titulo, texto, True)
            return
        self.sin_bloquear[uid] = (b.por, motivo)
        diario(f"{nombre_guardado(self.ajustes.unidades.get(uid), uid)}: no la he bloqueado "
               f"({TEXTO_EVENTO[b.por].lower()}): {motivo}")
        self._decir_sin_bloquear()

    def _veracrypt_del_equipo(self) -> str | None:
        """Devuelve el VeraCrypt instalado (`penwatch.installed_veracrypt()`), mirado cada `MIRAR_EMBLEMA`.

        Es el único con el que el agente bloquea sin nadie delante
        (`orden_bloquear()`): en Windows mirarlo es leer el registro, y no se
        hace en cada vuelta.
        """
        ahora = self.reloj()
        if ahora - self.veracrypt_mirado >= MIRAR_EMBLEMA:
            self.veracrypt_instalado = penwatch.installed_veracrypt()
            self.veracrypt_mirado = ahora
        return self.veracrypt_instalado

    def _bloqueable(self, uid: str) -> bool:
        """Indica si un evento de la sesión puede bloquear esa raíz ahora.

        Es una raíz de la lista abierta (conectada), que no se está expulsando
        ni actualizando: la raíz del equipo cifrada, o, en Windows, una unidad
        con vestíbulo de VeraCrypt (`con_vestibulo`) con su código aceptado
        (ni `cambiada`, ni `vieja`, ni `a_medias`) y que no está en modo `nada`.
        BitLocker y las unidades sin cifrar, nunca. Que haya VeraCrypt
        instalado no se mira aquí: sin él, el bloqueo se intenta y se dice que
        no se ha podido.
        """
        unidad = self.ajustes.unidades.get(uid)
        con = self.conexiones.get(uid)
        if unidad is None or con is None or uid in self.expulsiones \
                or con.actualizacion is not None:
            return False
        if unidad.cifrada:
            return True
        return (IS_WIN and not unidad.es_raiz and unidad.modo != equipo.NADA
                and uid in self.con_vestibulo and not con.cambiada and not con.vieja
                and not con.a_medias)

    def _evento_de_sesion(self, evento: Any, ahora: float) -> None:
        """Atiende lo que la bandeja de Windows oye de la sesión (`equipo.PIDE_SESION`).

        Al bloquear la sesión o suspender el equipo, cada raíz que tiene puesto
        su ajuste de ese evento (`equipo.BLOQUEAR_AL`) y es bloqueable
        (`_bloqueable()`) recibe su `Bloqueo` con `por`, y deja de encolarse,
        como con «Bloquear». Lo demás es lo de siempre (`_bloqueos()`): se
        espera a la pareja en curso, nunca se fuerza. Es seguridad, no
        sincronización: no mira la moderación ni la pausa. Si el equipo se
        duerme antes de acabar, sigue al despertar. Al desbloquear la sesión
        se cancela lo que todavía no ha lanzado VeraCrypt y se dice, una vez
        por raíz, lo que no se ha podido bloquear.

        Args:
            evento: `equipo.EVENTO_BLOQUEO`, `EVENTO_DESBLOQUEO` o
                `EVENTO_SUSPENSION`.
            ahora: La hora del reloj del agente.
        """
        if evento == equipo.EVENTO_DESBLOQUEO:
            self.sesion_bloqueada = self.suspendido = False
            diario("la sesión de Windows se ha desbloqueado")
            for uid, b in list(self.bloqueos.items()):
                if b.por and b.proc is None:
                    del self.bloqueos[uid]
                    self.sin_bloquear[uid] = (b.por, self._por_que_espera(uid, b))
            self._decir_sin_bloquear()
            return
        clave = equipo.BLOQUEAR_AL.get(evento) if evento in equipo.EVENTOS_DE_SESION else None
        if clave is None:
            diario(f"evento de la sesión desconocido: {evento!r}; ignorado")
            return
        if evento == equipo.EVENTO_BLOQUEO:
            self.sesion_bloqueada = True
            diario("la sesión de Windows se ha bloqueado")
        else:
            self.suspendido = True
            diario("el equipo se suspende")
        for uid, unidad in self.ajustes.unidades.items():
            if not getattr(unidad, clave) or uid in self.bloqueos or not self._bloqueable(uid):
                continue
            con = self.conexiones[uid]
            fisica = None if unidad.cifrada else self.con_vestibulo.get(uid)
            self.bloqueos[uid] = Bloqueo(ahora, por=evento, fisica=fisica,
                                         raiz=None if fisica is None else con.raiz)
            self.urgentes = [u for u in self.urgentes if u[0] != uid]
            self.sin_bloquear.pop(uid, None)
            diario(f"{con.nombre}: se bloquea sola ({TEXTO_EVENTO[evento].lower()})")

    def _por_que_espera(self, uid: str, b: Bloqueo) -> str:
        """Devuelve por qué un bloqueo de la sesión no había lanzado VeraCrypt todavía."""
        if self.pasada is not None and self.pasada.tarea.raiz == uid:
            return "había una sincronización en marcha"
        if b.llavero is not None and not b.llavero_cerrado:
            return "su llavero todavía se estaba cerrando"
        if self._mirando(uid):
            return "se estaba mirando una de sus carpetas"
        return "no ha dado tiempo"

    def _decir_sin_bloquear(self) -> None:
        """Dice, una vez por raíz, lo que un evento de la sesión no ha podido bloquear.

        Solo con la persona delante: ni con la sesión bloqueada ni con el
        equipo suspendido. Sin una bandeja que oiga la sesión, sale al volver
        de la suspensión (`PIDE_DESPERTAR`).
        """
        if self.sesion_bloqueada or self.suspendido:
            return
        for uid, (por, motivo) in sorted(self.sin_bloquear.items()):
            nombre = nombre_guardado(self.ajustes.unidades.get(uid), uid)
            avisar(f"{nombre}: no la he bloqueado", f"{TEXTO_EVENTO[por]}: {motivo}.", True)
        self.sin_bloquear.clear()

    def _preparar_al_salir(self) -> None:
        """Deja en `al_salir` lo que se lanza si Windows cierra la sesión o se apaga.

        Es el desmontaje desatendido (`orden_bloquear(desatendido=True)`) de
        cada raíz con `bloquear_al_cerrar_sesion` que es bloqueable y está
        libre: sin una pasada suya en marcha, sin su ventana abierta, sin su
        KeePassXC abierto y sin otro bloqueo en curso. Solo con la bandeja de
        Windows, que es quien oye el fin de la sesión.
        """
        ordenes: list[list[str]] = []
        quieren = [uid for uid, u in self.ajustes.unidades.items()
                   if u.bloquear_al_cerrar_sesion]
        exe = self._veracrypt_del_equipo() if quieren and IS_WIN \
            and self.bandeja is not None else None
        for uid in quieren if exe else ():
            con = self.conexiones.get(uid)
            if (not self._bloqueable(uid) or con.ventana or uid in self.keepassxc
                    or uid in self.bloqueos
                    or (self.pasada is not None and self.pasada.tarea.raiz == uid)):
                continue
            unidad = self.ajustes.unidades[uid]
            cmd = orden_bloquear(unidad, desatendido=True, veracrypt=exe,
                                 raiz=None if unidad.cifrada else con.raiz)
            if cmd is not None:
                ordenes.append(cmd)
        self.al_salir = tuple(ordenes)

    def lanzar_al_salir(self) -> int:
        """Lanza lo que `al_salir` tiene preparado, sin esperar a nada. Es el fin de la sesión.

        Se llama desde el hilo de la bandeja al llegar `WM_ENDSESSION`: tras
        contestar, Windows puede terminar el proceso, así que no hay vuelta
        del agente que valga. Solo lanza: no toca el estado del agente, no
        suelta locks ni cierra el llavero, y lo que no salga no se avisa (solo
        queda en el diario).

        Returns:
            Cuántas órdenes se han lanzado.
        """
        ordenes = self.al_salir
        lanzadas = 0
        for cmd in ordenes:
            try:
                lanzar(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, cwd=str(equipo.DIR), close_fds=True,
                       **({"creationflags": penwatch.CREATE_NO_WINDOW} if IS_WIN else {}))
                lanzadas += 1
            except OSError:
                pass
        if ordenes:
            diario(f"se cierra la sesión: lanzo el bloqueo de {lanzadas} de "
                   f"{len(ordenes)} raíz{'es' if len(ordenes) != 1 else ''}")
        return lanzadas

    def _bloquear_solo(self, con: Conexion) -> dict[str, bool] | None:
        """Devuelve los ajustes de bloquear sola que este agente puede cumplir en esa raíz.

        Es lo que la ventana enseña como casillas (`watch.bloquear_solo()`):
        cada clave de `equipo.AJUSTES_BLOQUEAR_SOLO` cuyo evento se oye aquí,
        con su valor. El bloqueo de la sesión exige que la bandeja se haya
        registrado para oírlo (`oye_sesion`); la suspensión y el fin de la
        sesión, la bandeja de Windows. Sin raíz bloqueable, sin VeraCrypt
        instalado o sin bandeja, `None`.
        """
        if not IS_WIN or self.bandeja is None or not self._bloqueable(con.id) \
                or self._veracrypt_del_equipo() is None:
            return None
        unidad = self.ajustes.unidades[con.id]
        claves = [k for k in equipo.AJUSTES_BLOQUEAR_SOLO
                  if k != "bloquear_al_bloquear_sesion"
                  or getattr(self.bandeja, "oye_sesion", False)]
        return {k: getattr(unidad, k) for k in claves}

    def _cerrar_llavero(self, con: Conexion, b: Bloqueo, ahora: float) -> bool:
        """Cierra el llavero de una raíz antes de bloquearla; dice si ya se puede seguir.

        KeePassXC corre desde dentro del contenedor y lo retiene, y lo que
        quede sin subir se perdería de vista hasta desbloquearla. Es su
        `runsync.py --cerrar-llavero`, el de «Expulsar PRDRIVE.bat», con el
        Python del agente y sin consola: sin nadie que conteste, cierra
        KeePassXC como lo haría la persona (si tiene algo sin guardar, pregunta
        él), sube lo pendiente y deja el navegador como estaba. Si KeePassXC no
        se cierra (sale con 1) o tarda más de `ESPERA_LLAVERO`, no se bloquea y
        se dice. Una raíz sin llavero sigue sin más.

        Returns:
            True si ya se puede lanzar VeraCrypt.
        """
        if b.llavero_cerrado or not self._llavero_de(con):
            return True
        nombre = con.nombre
        if b.llavero is None:
            try:
                b.llavero = lanzar([python(), str(app(con.raiz) / "runsync.py"),
                                    "--cerrar-llavero"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   **_opciones_hijo(equipo.DIR, separado=True))
            except OSError as e:
                diario(f"{nombre}: no he podido cerrar su llavero ({e}); se bloquea igual")
                b.llavero_cerrado = True
                return True
            b.llavero_desde = ahora
            diario(f"{nombre}: cerrando su llavero antes de bloquearla")
            return False
        rc = b.llavero.poll()
        if rc is None:
            if ahora - b.llavero_desde < ESPERA_LLAVERO:
                return False
            try:
                b.llavero.terminate()
            except OSError:
                pass
            rc = 1
        if rc == 1:
            del self.bloqueos[con.id]
            self._no_bloqueada(con.id, b, f"{nombre}: no la bloqueo",
                               "KeePassXC sigue abierto: puede que esté preguntando algo. "
                               "Ciérralo y vuelve a bloquearla.",
                               "KeePassXC seguía abierto (quizá preguntando algo)")
            return False
        b.llavero_cerrado = True
        return True
    def _compatible(self, con: Conexion) -> bool:
        """Indica si el volumen de esa unidad es de los que se pueden expulsar.

        Lo decide `expulsar.compatible()`, que lee del sistema: como mucho una
        vez cada `MIRAR_EMBLEMA`, y al conectarla.
        """
        ahora = self.reloj()
        if con.compatible is None or ahora - con.compatible_leido >= MIRAR_EMBLEMA:
            con.compatible = expulsar.compatible(con.raiz)
            con.compatible_leido = ahora
        return con.compatible

    def _expulsable(self, con: Conexion) -> bool:
        """Indica si a esa unidad se le puede ofrecer «Expulsar» ahora.

        Es una unidad de la lista, con su código aceptado, que no es una raíz
        de este equipo (una carpeta), con un volumen compatible y sin nada en
        marcha que la tenga ocupada: una expulsión, un «Bloquear» o una
        actualización. De una que no está en la lista no se hace nada desde
        aquí, como con «Configurar».
        """
        unidad = self.ajustes.unidades.get(con.id)
        return (unidad is not None and not unidad.es_raiz and not con.cambiada
                and not self._por_actualizar(con) and con.actualizacion is None
                and con.id not in self.expulsiones and con.id not in self.bloqueos
                and self._compatible(con))

    def _pedir_expulsion(self, uid: str, ahora: float) -> None:
        """Atiende «Expulsar» de una unidad: lo deja pedido.

        Se lleva a cabo en `_expulsiones()`, cuando nada lo impide.
        """
        con = self.conexiones.get(uid)
        if con is None:
            diario(f"expulsar {uid[:8]!r}: no está conectada")
        elif uid in self.expulsiones:
            diario(f"{con.nombre}: ya se está expulsando")
        elif not self._expulsable(con):
            diario(f"{con.nombre}: no se puede expulsar desde aquí (no es un volumen "
                   f"extraíble de la lista, o está ocupada)")
        else:
            subir = self._por_subir(con, ahora)
            self.expulsiones[uid] = Expulsion(ahora, subir=subir)
            self.urgentes = [u for u in self.urgentes if u[0] != uid]
            self.urgentes += [(uid, n) for n in subir]
            diario(f"{con.nombre}: se pide expulsarla"
                   + (f"; antes se sincroniza {', '.join(subir)}" if subir else ""))

    def _por_subir(self, con: Conexion, ahora: float) -> list[str]:
        """Devuelve las parejas de una unidad que se pasan antes de expulsarla.

        Son las que pueden tener algo sin subir: todas las del servicio en modo
        `daemon`, menos las que se sabe que no (oyen los avisos del sistema y
        no hay ningún cambio pendiente; se acaban de pasar), las que no iban a
        subir nada (saltándose, su remoto sin conexión) y, si el
        agente se está moderando (pausa, batería, red de uso medido), ninguna:
        expulsar no se salta lo que la persona pidió. Sin esto una unidad se
        iría con lo cambiado desde la última pasada, que con el intervalo
        estirado pueden ser muchos minutos.
        """
        unidad = self.ajustes.unidades.get(con.id)
        if con.lock is None or con.servicio is None or unidad is None \
                or unidad.modo != equipo.DAEMON or self.heredada is not None \
                or pl.moderacion(replace(self.entorno, pausado=self.pausado),
                                 self.ajustes.politica) is not None:
            return []
        nombres = []
        for p in con.servicio.parejas:
            marca = self.marcas.get((con.id, p.nombre), pl.Marca())
            v = self.vigiladas.get((con.id, p.nombre))
            if (con.id, p.remoto) in self.entorno.sin_conexion or marca.saltada:
                continue
            if v is not None and v.avisos and v.cambio is None \
                    and marca.ultimo_intento is not None:
                continue                    # si hubiera cambiado algo, se sabría
            if marca.ultimo_intento is not None \
                    and ahora - marca.ultimo_intento < RECIEN_PASADA \
                    and (v is None or v.cambio is None):
                continue
            pasada = self.pasada
            if pasada is not None and (con.id, p.nombre) in pasada.claves \
                    and ahora - pasada.desde < RECIEN_PASADA:
                continue                    # la que está en marcha acaba de empezar
            nombres.append(p.nombre)
        return nombres

    def _expulsiones(self, ahora: float) -> None:
        """Lleva los «Expulsar» pedidos hasta ver la unidad suelta o el motivo de que no.

        Primero se espera a que nada lo impida (la pareja en curso, la foto de
        una de sus carpetas durante `ESPERA_VENTANA` como mucho, su ventana,
        que corre desde la propia unidad); luego se suelta el lock y se lanza
        la expulsión en un hilo, que puede tardar. Con el resultado se avisa:
        «ya puedes quitarla», o por qué no. Una expulsión que fue bien se
        recuerda hasta que la unidad desaparece (`GRACIA_EXPULSION`) para no
        volver a atenderla en lo que el sistema la retira.
        """
        for uid, e in list(self.expulsiones.items()):
            con = self.conexiones.get(uid)
            unidad = self.ajustes.unidades.get(uid)
            nombre = con.nombre if con is not None else nombre_guardado(unidad, uid)
            if e.resultado is not None:
                if not e.avisada:
                    e.avisada = True
                    if e.resultado.ok:
                        diario(f"{nombre}: expulsada")
                        avisar(f"{nombre}: ya puedes quitarla", e.resultado.texto
                               + (f" Se ha quedado sin sincronizar: {', '.join(e.sin_subir)}."
                                  if e.sin_subir else ""))
                    else:
                        diario(f"{nombre}: no se ha podido expulsar: {e.resultado.texto}")
                        avisar(f"{nombre}: no la expulso", e.resultado.texto, True)
                if not e.resultado.ok or con is None \
                        or ahora - (e.lanzada or ahora) >= GRACIA_EXPULSION:
                    del self.expulsiones[uid]
                continue
            if con is None and e.lanzada is None:
                del self.expulsiones[uid]
                continue
            if e.lanzada is not None:
                # Lanzada: se espera el resultado aunque la unidad ya se haya
                # ido, que es lo normal cuando va bien.
                if ahora - e.lanzada >= ESPERA_EXPULSION:
                    del self.expulsiones[uid]
                    avisar(f"{nombre}: no la expulso",
                           "El sistema no ha contestado a tiempo. Comprueba que se puede "
                           "quitar antes de tirar del cable.", True)
                continue
            if e.subir:
                # Lo pendiente sube antes de soltarla: son urgentes de esta
                # raíz, y cada una sale de la cola al lanzarse.
                en_curso = {p for r, p in self.pasada.claves if r == uid} \
                    if self.pasada is not None else set()
                e.subir = [n for n in e.subir if (uid, n) in self.urgentes or n in en_curso]
                servida = con is not None and con.lock is not None and con.servicio is not None
                # La cola es una para todo el equipo: a la pasada de otra raíz
                # se la espera poco, que quien pide expulsar está delante.
                ajena = self.pasada is not None and not en_curso
                plazo = ESPERA_TURNO if ajena else ESPERA_SUBIR
                if e.subir and (not servida or ahora - e.desde >= plazo):
                    # No ha dado tiempo, o ya no la sirve el agente (su ventana,
                    # otro servicio): no hay quien las pase.
                    e.sin_subir += [n for n in e.subir if n not in en_curso]
                    self.urgentes = [u for u in self.urgentes if u[0] != uid]
                    e.subir = []
                if e.subir:
                    continue
            if self.pasada is not None and self.pasada.tarea.raiz == uid:
                continue                    # acaba la pareja en curso
            if self._mirando(uid) and ahora - e.desde < ESPERA_VENTANA:
                continue                    # y la foto en curso: tiene la carpeta abierta
            if _registro_vivo(con.raiz, penwatch.UI_LOCK_REL) is not None:
                # Su ventana corre desde la propia unidad y la tiene ocupada.
                if ahora - e.desde >= ESPERA_VENTANA:
                    del self.expulsiones[uid]
                    avisar(f"{nombre}: no la expulso",
                           "Su ventana sigue abierta. Ciérrala y vuelve a pedirlo.", True)
                continue
            self._soltar_avisos(uid)
            self._soltar(con)
            e.lanzada = ahora
            diario(f"{nombre}: expulsándola; si algo la tiene ocupada, no se fuerza")
            hilo(lambda e=e, raiz=con.raiz: self._expulsar_en_hilo(e, raiz))

    @staticmethod
    def _expulsar_en_hilo(e: Expulsion, raiz: Path) -> None:
        """Expulsa `raiz` y deja el resultado en `e`; es lo que corre el hilo."""
        try:
            e.resultado = expulsar.expulsar(raiz)
        except Exception as ex:                     # noqa: BLE001
            e.resultado = expulsar.Resultado(False, f"No he podido expulsarla: {ex}")

    def _leer_entorno(self, ahora: float) -> None:
        """Lee la batería, el modo de ahorro y la red, como mucho cada `MIRAR_ENTORNO` segundos.

        La red de uso medido, cada `MIRAR_RED_MEDIDA` si el sistema avisa de
        sus cambios (`_avisa_el_coste()`): el aviso, y la ráfaga al asentarse,
        hacen leerlo todo ya.
        """
        if ahora - self.entorno_leido < MIRAR_ENTORNO:
            return
        if not self.conexiones:
            # Sin ninguna unidad a la vista no hay pasada que moderar: ni se
            # pregunta por la batería ni por la red (en Windows, una llamada
            # COM que despierta a otros procesos). Al llegar una, se lee ya.
            return
        cada = MIRAR_RED_MEDIDA if self._avisa_el_coste() else MIRAR_ENTORNO
        medida = self.entorno.red_medida
        if self.entorno_leido == -math.inf or ahora - self.red_leida >= cada:
            self.red_leida = ahora
            medida = moderacion.red_medida()
        self.entorno_leido = ahora
        energia = moderacion.energia()
        self.entorno = replace(self.entorno, con_bateria=energia.con_bateria,
                               bateria=energia.porcentaje,
                               ahorro_energia=energia.ahorro,
                               red_medida=medida)

    def _avisa_el_coste(self) -> bool:
        """Indica si un cambio de «red de uso medido» llega como aviso de red (Windows)."""
        return IS_WIN and self.avisa_la_red()

    def _mirar_version(self, ahora: float) -> None:
        """Mira, de tarde en tarde, si hay una versión más nueva que la de este agente.

        Va en un hilo, porque es la red. Cuando la hay se dice una vez, y la
        bandeja ofrece «Actualizar» (sección 8 del diseño).
        """
        if self.actualizando is not None and self.actualizando.poll() is not None:
            # Si el agente sigue siendo este, la actualización no ha llegado a
            # sustituirlo: lo cuenta su diario y se puede volver a pedir.
            self.actualizando = None
        if self.nueva and self.nueva != self.nueva_avisada:
            self.nueva_avisada = self.nueva
            avisar(f"Hay una versión nueva de {APP_NAME}: {self.nueva}",
                   f"Tienes la {self.version or 'desconocida'}. "
                   + ("Actualízala desde su icono de la bandeja." if self.con_bandeja()
                      else "Para ponerla: python agente.py actualizar"))
        if ahora - self.version_mirada < MIRAR_VERSION:
            return
        self.version_mirada = ahora

        def trabajo() -> None:
            """Busca la versión nueva y apunta su tag.

            Si falla, lo deja en el diario.
            """
            try:
                rel = buscar_version()
            except Exception as e:                  # noqa: BLE001
                diario(f"no he podido mirar si hay versión nueva: {e}")
                return
            self.nueva = rel.tag if rel is not None else None

        hilo(trabajo)

    def _buscar_ahora(self, ahora: float) -> None:
        """Hace el «Buscar actualizaciones»: pregunta a GitHub ya, en un hilo.

        Con una versión nueva apunta su tag y deja que `_mirar_version()` la
        diga, como la dice siempre; sin ella, o si falla, lo cuenta con un
        aviso, porque quien lo pide espera una respuesta. Un fallo no borra lo
        que ya se sabía. Mientras corre no se acepta otro.

        Args:
            ahora: La hora de esta vuelta; retrasa la próxima mirada de fondo.
        """
        if self.buscando:
            diario("ya se está buscando una versión nueva")
            return
        self.buscando = True
        self.version_mirada = ahora

        def trabajo() -> None:
            """Pregunta, apunta la respuesta y avisa si no hay nada nuevo que ofrecer."""
            try:
                try:
                    rel, motivo = buscar_version_ya()
                except Exception as e:                  # noqa: BLE001
                    rel, motivo = None, f"No he podido mirar si hay versión nueva: {e}"
                if motivo is None and rel is not None:
                    hay = update.is_newer(rel.version, self.version)
                    self.nueva = rel.tag if hay else None
                    if hay:
                        self.nueva_avisada = None
                        return
                avisar(f"{APP_NAME}: buscar actualizaciones",
                       update.veredicto(rel, motivo, self.version))
            finally:
                self.buscando = False

        hilo(trabajo)

    def con_bandeja(self) -> bool:
        """Indica si hay un icono en la bandeja que ofrezca lo que dice un aviso."""
        return self.bandeja is not None and bool(getattr(self.bandeja, "puesta", True))

    def _actualizar(self) -> None:
        """Hace el «Actualizar»: lanza un hijo suelto (`agente.py actualizar`).

        Baja la versión nueva y la pone con su propio instalador, que para a
        este agente y arranca el nuevo. Aquí no se espera nada: la red y la
        copia no pueden tener parada la cola.
        """
        if self.actualizando is not None and self.actualizando.poll() is None:
            diario("ya se está actualizando")
            return
        try:
            self.actualizando = lanzar([python(), str(SCRIPT_DIR / "agente.py"),
                                        "actualizar"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       **_opciones_hijo(equipo.DIR, separado=True))
        except OSError as e:
            avisar(f"{APP_NAME}: no he podido actualizar", str(e), True)
            return
        diario(f"actualizando a la {self.nueva or 'última versión'}; lo que pase, "
               f"aquí mismo")

    def _actualizandose(self) -> bool:
        """Indica si está en marcha el «Actualizar» del propio agente."""
        return self.actualizando is not None and self.actualizando.poll() is None

    def _como_actualizar(self, con: Conexion) -> str:
        """Devuelve dónde se pide poner al día esa raíz, para terminar un aviso."""
        if self.con_bandeja():
            return "desde su desplegable en el icono de la bandeja"
        return f"con «python agente.py actualizar {con.id}»"

    def _actualizable(self, con: Conexion) -> bool:
        """Indica si a esa raíz se le puede ofrecer «Actualizar a la vX».

        Es una raíz de la lista, con su código aceptado, que no se está
        bloqueando, con un programa anterior al del agente (o sin `VERSION`), o
        que una actualización dejó a medias. De una que no está en la lista no
        se toca nada, y con el código cambiado primero hay que volver a decir
        que sí. Mientras el propio agente se actualiza, tampoco: él mismo pone
        al día las raíces del equipo que estén abiertas.
        """
        if con.id not in self.ajustes.unidades or con.cambiada or con.pregunta is not None \
                or con.id in self.bloqueos or con.id in self.expulsiones \
                or not self.version or self._actualizandose():
            return False
        return con.a_medias or update.is_newer(self.version, self._version_de(con))

    def _con_ventana(self, con: Conexion) -> bool:
        """Indica si esa raíz tiene su ventana abierta, y entonces avisa de que no se actualiza.

        La ventana ofrece su propia actualización, y no se le cambia el
        programa por debajo.
        """
        if _registro_vivo(con.raiz, penwatch.UI_LOCK_REL) is None:
            return False
        avisar(f"{con.nombre}: tiene su ventana abierta",
               "No la actualizo por debajo de ella: actualízala desde la ventana, o "
               "ciérrala y vuelve a pedirlo.", True)
        return True

    def _pedir_actualizacion(self, uid: str, ahora: float) -> None:
        """Atiende «Actualizar a la vX» de una raíz: lo deja pedido.

        Se lanza en `_actualizaciones()`, acabada la pareja en curso. La
        primera vez en esta conexión se mira si su código es el aceptado
        (`confiada`), antes de tocar nada.
        """
        con = self.conexiones.get(uid)
        if con is None:
            diario(f"actualizar {uid[:8]!r}: no está conectada")
            return
        if con.actualizacion is not None:
            diario(f"{con.nombre}: ya se está actualizando")
            return
        if not self._actualizable(con):
            diario(f"{con.nombre}: no hay nada que ponerle desde aquí (lleva la "
                   f"{self._version_de(con) or 'versión desconocida'}; el agente, la "
                   f"{self.version or 'versión desconocida'})")
            return
        if self._con_ventana(con):
            return
        unidad = self.ajustes.unidades[uid]
        if con.confiada is None:
            con.confiada = unidad.es_raiz or not unidad.codigo \
                or huella(con.raiz) == unidad.codigo
        con.actualizacion = Actualizacion(ahora)
        self.urgentes = [u for u in self.urgentes if u[0] != uid]
        diario(f"{con.nombre}: se pide ponerla a la {self.version}")

    def _actualizaciones(self, ahora: float) -> None:
        """Lanza las actualizaciones pedidas, recoge las que acaban y ofrece las que hay.

        Una pedida espera a que acabe la pareja en curso de su raíz, la de este
        agente o la que dejó el anterior, y a que se suelte su lock
        (`_contrato()`). De una raíz que se puede poner al día se avisa una vez
        por cada versión suya.
        """
        heredada = equipo.pasada_viva() if self.heredada is not None else None
        for con in list(self.conexiones.values()):
            act = con.actualizacion
            if act is None:
                self._avisar_actualizable(con)
            elif act.proc is None:
                ocupada = (self.pasada is not None and self.pasada.tarea.raiz == con.id) \
                    or (heredada or {}).get("raiz") == con.id
                if not ocupada and con.lock is None:
                    self._lanzar_actualizacion(con, act)
            elif act.proc.poll() is not None:
                self._fin_de_actualizacion(con, act.proc.poll(), ahora)

    def _avisar_actualizable(self, con: Conexion) -> None:
        """Dice, una vez por cada versión suya, que esa raíz se puede poner al día."""
        if con.a_medias or not self._actualizable(con):
            return
        version = self._version_de(con)
        if con.version_avisada == version:
            return
        con.version_avisada = version
        avisar(f"{con.nombre} tiene la {version or 'versión desconocida'}",
               f"El agente de este equipo es de la {self.version}. Puedes ponerla al día "
               f"{self._como_actualizar(con)}.")

    def _lanzar_actualizacion(self, con: Conexion, act: Actualizacion) -> None:
        """Lanza el hijo suelto que pone al día esa raíz (`agente.py actualizar-raiz`).

        Si entretanto se ha abierto su ventana, se deja: se dice y no se lanza.
        """
        if self._con_ventana(con):
            con.actualizacion = None
            return
        try:
            act.proc = lanzar([python(), str(SCRIPT_DIR / "agente.py"), "actualizar-raiz",
                               str(con.raiz)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              **_opciones_hijo(equipo.DIR, separado=True))
        except OSError as e:
            con.actualizacion = None
            avisar(f"{con.nombre}: no he podido actualizarla", str(e), True)
            return
        diario(f"{con.nombre}: actualizándola a la {self.version}; lo que pase, aquí mismo")

    def _fin_de_actualizacion(self, con: Conexion, rc: int, ahora: float) -> None:
        """Recoge una actualización acabada y dice cómo ha ido.

        Ha ido bien si el instalador sale con 0 y la raíz lleva ahora la
        versión del agente. Entonces, de una unidad, la huella nueva se apunta
        como aceptada si la de antes lo era (`confiada`); si no, se vuelve a
        preguntar, como con cualquier código cambiado. Si ha ido mal pero la
        tocó, queda `a_medias`: no se atiende hasta que otra acabe bien.

        Args:
            con: La conexión de la raíz.
            rc: Con qué salió `actualizar-raiz` (`SIN_TOCAR`: no la tocó).
            ahora: La hora del reloj del agente.
        """
        con.actualizacion = None
        con.version, con.version_leida = None, -math.inf
        puesta = update.installed_version(app(con.raiz))
        bien = rc == 0 and puesta == self.version
        con.a_medias = not bien and rc != SIN_TOCAR
        con.vieja = version_vieja(con.raiz)
        unidad = self.ajustes.unidades.get(con.id)
        if unidad is not None and not unidad.es_raiz:
            nueva = huella(con.raiz)
            if nueva == unidad.codigo:
                con.a_medias = False            # no ha llegado a cambiar nada
            elif bien and con.confiada and nueva:
                self._guardar(self.ajustes.con_unidad(replace(unidad, codigo=nueva)))
                con.huella = nueva
                diario(f"{con.nombre}: apuntada la huella de su código nuevo")
            elif bien:
                con.cambiada = True
                diario(f"{con.nombre}: actualizada, pero su código no era el que se "
                       f"aceptó; no se ejecuta nada suyo hasta que se vuelva a decir que sí")
                self._preguntar(con, ahora)
        if bien:
            con.confiada = None
            diario(f"{con.nombre}: actualizada a la {puesta}")
            dlog(con.raiz, f"programa actualizado a la {puesta} por el agente del equipo")
            avisar(f"{con.nombre} actualizada a la {puesta}",
                   "Se conservan su configuración, sus claves y su estado.")
            return
        diario(f"{con.nombre}: la actualización ha salido con {rc}"
               + ("" if rc else f" pero lleva la {puesta or 'versión desconocida'}"))
        avisar(f"{con.nombre}: no he podido actualizarla",
               f"Lo que ha pasado está en {equipo.diario_log()}."
               + (" No se atiende hasta que vuelvas a pedirlo y acabe bien."
                  if con.a_medias else ""), True)

    def pedir(self, peticion: dict) -> None:
        """Deja una petición de la bandeja (otro hilo) para la próxima vuelta.

        Se atiende en el hilo del agente, igual que una del buzón.
        """
        self.peticiones.put(dict(peticion))

    def _usada(self, uid: Any, ahora: float) -> None:
        """Apunta que se acaba de usar esa raíz, si está conectada o a la vista y bloqueada.

        Es lo que decide sobre qué unidad actúa un atajo (`atajos.objetivo()`):
        tras un atajo con ella bloqueada, volver a pulsarlo (si se cerró la
        ventana de la contraseña) vuelve a ella.
        """
        if isinstance(uid, str) and (uid in self.conexiones or self._bloqueada(uid)):
            self.usadas[uid] = ahora

    def _bloqueada(self, uid: str) -> bool:
        """Indica si esa raíz de la lista está a la vista y bloqueada, y el agente sabe abrirla.

        Es la raíz cifrada de este equipo cerrada (`atajos.RAIZ_BLOQUEADA`), o
        una unidad bloqueada con BitLocker o con el contenedor de VeraCrypt
        cerrado: lo que un atajo de abrir su carpeta o su ventana desbloquea.
        """
        unidad = self.ajustes.unidades.get(uid)
        if unidad is None or uid in self.conexiones:
            return False
        if unidad.cifrada:
            return self._estado_raiz(uid, unidad) in atajos.RAIZ_BLOQUEADA
        return (self._bloqueada_bitlocker(uid) is not None
                or self._cerrada_veracrypt(uid) is not None)

    def _buzon(self, ahora: float) -> None:
        """Atiende las peticiones del buzón de `agente.pide` y las de la bandeja.

        Lo que la bandeja pide de UNA raíz cuenta como usarla; «Sincronizar todo
        ahora» (`todas`) no. Un evento de la sesión (`equipo.PIDE_SESION`) solo
        vale de la bandeja: por el fichero se rechaza.
        """
        pendientes = [(p, False) for p in equipo.recoger()]
        while True:
            try:
                p = self.peticiones.get_nowait()
            except queue.Empty:
                break
            if isinstance(p, dict) and not p.get("todas"):
                self._usada(p.get("id"), ahora)
            pendientes.append((p, True))
        for p, de_bandeja in pendientes:
            try:
                if p.get("pide") != equipo.PIDE_SESION:
                    self._atender_peticion(p, ahora)
                elif de_bandeja:
                    self._evento_de_sesion(p.get("evento"), ahora)
                else:
                    diario(f"un evento de la sesión por el buzón ({p.get('evento')!r}): "
                           f"solo lo dice la bandeja; ignorado")
            except Exception as e:                      # noqa: BLE001
                diario(f"petición ilegible {p!r}: {e}")

    def _buzones_de_raices(self, ahora: float) -> None:
        """Atiende el buzón de cada raíz conectada y en la lista.

        Es `state/servicio.pide`: lo que su ventana le pide a su servicio. Lo
        que llega por ahí es de ESA raíz, sea cual sea el id que traiga, y solo
        lo que es de una raíz (`equipo.PIDE_SERVICIO`). El de una unidad que no
        está en la lista ni se mira: de ella solo se lee su id y su nombre.
        """
        for con in list(self.conexiones.values()):
            if con.id not in self.ajustes.unidades or con.cambiada \
                    or self._por_actualizar(con):
                continue
            if con.vista is not None and equipo.BUZON_SERVICIO not in con.vista:
                continue                    # la mirada de esta vuelta dice que no hay buzón
            for p in equipo.recoger(estado_de(con.raiz) / equipo.BUZON_SERVICIO):
                if p.get("pide") not in equipo.PIDE_SERVICIO:
                    diario(f"{con.nombre}: su buzón pide {p.get('pide')!r}, que no es "
                           f"cosa de una raíz; ignorado")
                    continue
                self._usada(con.id, ahora)
                try:
                    self._atender_peticion({**p, "id": con.id}, ahora)
                except Exception as e:                  # noqa: BLE001
                    diario(f"petición ilegible {p!r}: {e}")

    def _atender_peticion(self, p: dict, ahora: float) -> None:
        """Atiende una petición del buzón o de la bandeja.

        Cada petición es un `equipo.PIDE_*`: pausar o reanudar el servicio de
        una raíz, atender o poner modo a una unidad, añadir una raíz,
        desbloquear o bloquear una raíz cifrada, pedir a Windows que desbloquee
        una unidad con BitLocker, abrir la ventana o la carpeta
        de una raíz, expulsar una unidad extraíble, despertar, sondear, un cambio de red, cambiar un ajuste,
        una pasada urgente, actualizar el agente o una raíz, un atajo de
        teclado pulsado, guardar los atajos o abrir la ventana que los graba,
        pausa, sigue y parar. Los eventos de la sesión (`equipo.PIDE_SESION`)
        no llegan aquí: `_buzon()` los separa, porque solo valen de la bandeja.

        Args:
            p: La petición.
            ahora: La hora del reloj del agente.
        """
        que = p.get("pide")
        uid = p.get("id") if isinstance(p.get("id"), str) else ""
        if que == equipo.PIDE_REANUDAR:
            # «Reanudar» (o «Iniciar servicio» desde la consola) en la ventana
            # de esa raíz: no arranca un servicio suyo, le quita su pausa y le
            # dice al agente que vuelva en cuanto se cierre. Como el servicio
            # que se arrancaba, empieza con una pasada.
            unidad = self.ajustes.unidades.get(uid)
            if unidad is not None and unidad.pausada:
                self._guardar(self.ajustes.con_unidad(replace(unidad, pausada=False)))
            con = self.conexiones.get(uid)
            if con is None:
                diario(f"reanudar {uid[:8]}: no está conectada")
                return
            con.reanudar = True
            for clave in [k for k in self.marcas if k[0] == uid]:
                del self.marcas[clave]
            diario(f"{con.nombre}: su ventana pide volver a sincronizarla")
            if unidad is not None and unidad.pausada:
                dlog(con.raiz, "servicio (agente del equipo): «Reanudar» desde su ventana")
        elif que == equipo.PIDE_PAUSAR_RAIZ:
            # «Pausar» en la ventana de esa raíz: que no vuelva al cerrarla. Se
            # guarda (`Unidad.pausada`) para que tampoco vuelva al reiniciarse
            # el agente; el lock se suelta en `_contrato`, acabada la pareja en
            # curso, porque `_sirve` ya no la cuenta.
            unidad = self.ajustes.unidades.get(uid)
            if unidad is None:
                diario(f"pausar {uid[:8]!r}: no está en la lista")
                return
            if not unidad.pausada:
                self._guardar(self.ajustes.con_unidad(replace(unidad, pausada=True)))
            self.urgentes = [u for u in self.urgentes if u[0] != uid]
            con = self.conexiones.get(uid)
            nombre = con.nombre if con is not None else nombre_guardado(unidad, uid)
            if con is not None:
                con.reanudar = False
                dlog(con.raiz, "servicio (agente del equipo) en pausa: «Pausar» desde su "
                               "ventana")
            diario(f"{nombre}: su ventana pide pausarla; no se sincroniza hasta «Reanudar»")
        elif que == equipo.PIDE_ATENDER:
            con = self.conexiones.get(uid)
            if con is None:
                diario(f"atender {uid[:8]}: no está conectada; se atiende enchufada")
            elif uid in self.ajustes.unidades and not con.cambiada:
                diario(f"atender {con.nombre}: ya estaba en la lista")
            else:
                if con.hijo is not None and con.hijo.poll() is None:
                    con.hijo.terminate()
                con.pregunta, con.hijo = None, None
                self._atender(con)
        elif que == equipo.PIDE_MODO:
            # Una que no está en la lista entra con ese modo: es lo que hace el
            # asistente vuelto a pasar con el agente ya instalado, que añade
            # las unidades elegidas en su paso «Unidades».
            modo = p.get("modo")
            if not uid.strip() or modo not in equipo.MODOS:
                diario(f"modo {modo!r} para {uid[:8]!r}: no es un id o no es un modo")
                return
            nombre = p.get("nombre") if isinstance(p.get("nombre"), str) else ""
            unidad = self.ajustes.unidades.get(uid) or equipo.Unidad(uid, modo, nombre)
            unidad = replace(unidad, modo=modo, nombre=unidad.nombre or nombre)
            con = self.conexiones.get(uid)
            if con is not None and (uid not in self.ajustes.unidades or con.cambiada):
                # Pedido a mano con ella enchufada: es el sí, con su código de ahora.
                if con.hijo is not None and con.hijo.poll() is None:
                    con.hijo.terminate()
                con.pregunta, con.hijo, con.respuesta = None, None, None
                con.huella = huella(con.raiz)
                con.cambiada = False
                unidad = replace(unidad, codigo=con.huella or "")
            self._guardar(self.ajustes.con_unidad(unidad))
            diario(f"{unidad.nombre or nombre}: modo {modo}")
        elif que == equipo.PIDE_RAIZ:
            # Lo que pide el asistente vuelto a pasar con el agente instalado:
            # la raíz que acaba de poner en este equipo.
            ruta = p.get("ruta") if isinstance(p.get("ruta"), str) else ""
            if not uid.strip() or not ruta.strip():
                diario(f"añadir raíz {uid[:8]!r} en {ruta!r}: falta el id o la ruta")
                return
            nombre = p.get("nombre") if isinstance(p.get("nombre"), str) else ""
            modo = p.get("modo") if p.get("modo") in equipo.MODOS else equipo.DAEMON
            hc = p.get("contenedor") if isinstance(p.get("contenedor"), str) else ""
            # Se parte de la que ya hay: el asistente vuelto a pasar cambia la
            # ruta, el modo o el contenedor, no la pausa de su ventana ni el
            # código que se aceptó.
            previa = self.ajustes.unidades.get(uid) or equipo.Unidad(uid)
            self._guardar(self.ajustes.con_unidad(
                replace(previa, modo=modo, nombre=nombre or previa.nombre,
                        ruta=ruta.strip(), contenedor=hc.strip())))
            self.ausentes.discard(uid)
            self.pedidas.add(uid)           # la acaba de dejar abierta el asistente
            diario(f"raíz de este equipo añadida: {nombre or nombres.por_defecto(uid)} en {ruta}"
                   + (f" (cifrada, contenedor {hc})" if hc else ""))
        elif que == equipo.PIDE_DESBLOQUEAR and self._es_de_bitlocker(uid):
            self._desbloquear_bitlocker(uid, ahora)
        elif que in (equipo.PIDE_DESBLOQUEAR, equipo.PIDE_BLOQUEAR):
            unidad = self._cifrada(uid)
            if unidad is None:
                diario(f"{que} {uid[:8]!r}: no hay esa raíz cifrada en este equipo")
            elif que == equipo.PIDE_DESBLOQUEAR:
                self._desbloquear(unidad, ahora, "pedido")
            elif unidad.id not in self.bloqueos:
                self.bloqueos[unidad.id] = Bloqueo(ahora)
                self.urgentes = [u for u in self.urgentes if u[0] != unidad.id]
        elif que == equipo.PIDE_ABRIR:
            self._abrir(uid, ahora)
        elif que == equipo.PIDE_EXPLORAR:
            self._abrir(uid, ahora, explorador=True)
        elif que == equipo.PIDE_LLAVERO:
            self._abrir(uid, ahora, llavero=True)
        elif que == equipo.PIDE_EXPULSAR:
            self._pedir_expulsion(uid, ahora)
        elif que == equipo.PIDE_DESPERTAR:
            # Vuelta de la suspensión: la batería y la red pueden ser otras y
            # un remoto «sin conexión» quizá ya contesta. Se mira todo ya.
            self.entorno_leido = -math.inf
            self.entorno = pl.sondear_ya(self.entorno, ahora)
            self.rafaga_hasta = max(self.rafaga_hasta, ahora + RAFAGA)
            # Windows manda dos eventos de reanudación seguidos (visto en real,
            # a 1 s): repetir lo de arriba no hace daño; el diario sí.
            if ahora - self.despertado >= DESPERTAR_DOBLE:
                diario("el equipo vuelve de la suspensión")
            self.despertado = ahora
            # Lo que la suspensión no pudo bloquear se dice ya, salvo que la
            # sesión siga bloqueada: entonces, al desbloquearla.
            self.suspendido = False
            self._decir_sin_bloquear()
        elif que == equipo.PIDE_SONDEAR:
            # «Probar ahora» en un aviso de «Sin conexión»: la sonda de cada
            # remoto sin conexión, ya, en vez de a su hora.
            self.entorno = pl.sondear_ya(self.entorno, ahora)
            diario("se prueban ya los remotos sin conexión")
        elif que == equipo.PIDE_CAMBIO_DE_RED:
            # El sistema dice que vuelve a haber red (`common/red.py`). No se
            # sondea ya: se agrupa la ráfaga y va una sonda por remoto cuando
            # se calma (`_cambios_de_red`). Si la red es de uso medido, sí:
            # en Windows es este aviso el que lo trae (`MIRAR_RED_MEDIDA`).
            self.cambio_de_red = pl.cambia_la_red(self.cambio_de_red, ahora)
            self.entorno_leido = -math.inf
        elif que == equipo.PIDE_AJUSTE:
            clave, valor = p.get("clave"), p.get("valor")
            if clave not in equipo.AJUSTES_PEDIBLES:
                diario(f"ajuste desconocido: {clave!r}")
                return
            crudo = equipo.a_dict(self.ajustes)
            crudo[clave] = valor
            self._guardar(equipo.desde_dict(crudo))
            diario(f"ajuste {clave} = {getattr(self.ajustes, clave)}")
        elif que == equipo.PIDE_AJUSTE_UNIDAD:
            self._ajuste_de_unidad(uid, p.get("clave"), p.get("valor"))
        elif que == equipo.PIDE_PASADA:
            con = self.conexiones.get(uid)
            if con is None or con.servicio is None:
                diario(f"pasada de {uid[:8]}: no está conectada o no tiene servicio")
                return
            pedidas = p.get("parejas") if isinstance(p.get("parejas"), list) else []
            nombres = [x.nombre for x in con.servicio.parejas
                       if not pedidas or x.nombre in pedidas]
            self.urgentes += [(uid, n) for n in nombres if (uid, n) not in self.urgentes]
        elif que == equipo.PIDE_ACTUALIZAR:
            self._actualizar()
        elif que == equipo.PIDE_ACTUALIZAR_UNIDAD:
            self._pedir_actualizacion(uid, ahora)
        elif que == equipo.PIDE_BUSCAR_VERSION:
            self._buscar_ahora(ahora)
        elif que == equipo.PIDE_ATAJO:
            self._atajo(p.get("accion"), ahora)
        elif que == equipo.PIDE_ATAJOS:
            self._guardar_atajos(p.get("atajos"), p.get("vez"))
        elif que == equipo.PIDE_GRABAR_ATAJOS:
            self._abrir_atajos()
        elif que == equipo.PIDE_PAUSA:
            self.pausado = True
        elif que == equipo.PIDE_SIGUE:
            self.pausado = False
        elif que == equipo.PIDE_PARAR:
            cuando = p.get("cuando")
            if isinstance(cuando, (int, float)) and cuando < self.inicio:
                # Se lo pidieron al agente anterior, que se fue sin leerlo (el
                # instalador lo terminó a la fuerza): no va con este.
                diario("un «parar» de antes de arrancar: no es para este agente")
                return
            self.terminar = True
            diario("parada pedida: termina en cuanto acabe lo que esté en marcha")

    def _ajuste_de_unidad(self, uid: str, clave: Any, valor: Any) -> None:
        """Cambia un ajuste de UNA unidad de la lista (`equipo.AJUSTES_DE_UNIDAD`).

        Lo que no vale se deja en el diario y no toca nada: otra clave, una
        unidad que no está en la lista, una raíz de este equipo donde ese
        ajuste no cabe o un valor que no es verdadero, falso ni `None`. Se
        decide clave por clave: `pedir_al_conectar` no vale en ninguna raíz
        del equipo (su ajuste es el global `pedir_al_iniciar`), y los de
        bloquear sola (`equipo.AJUSTES_BLOQUEAR_SOLO`) valen en una raíz del
        equipo cifrada pero no en una sin cifrar; en ellos `None` es apagado.

        Args:
            uid: El id de la unidad.
            clave: El campo de `Unidad` que se cambia.
            valor: Su valor nuevo.
        """
        if clave not in equipo.AJUSTES_DE_UNIDAD:
            diario(f"ajuste de unidad desconocido: {clave!r}")
            return
        unidad = self.ajustes.unidades.get(uid)
        solo = clave in equipo.AJUSTES_BLOQUEAR_SOLO
        if unidad is None or (unidad.es_raiz and not (solo and unidad.cifrada)):
            diario(f"ajuste {clave} de {uid[:8]!r}: no es una unidad de la lista"
                   + (" donde quepa" if unidad is not None else ""))
            return
        nombre = nombre_guardado(unidad, uid)
        if valor is not None and not isinstance(valor, bool):
            diario(f"{nombre}: ajuste {clave} = {valor!r}: no es sí, no ni lo de siempre")
            return
        if solo:
            valor = bool(valor)
        self._guardar(self.ajustes.con_unidad(replace(unidad, **{clave: valor})))
        diario(f"{nombre}: ajuste {clave} = {valor}")

    # Los atajos de teclado globales (`ui/atajos.py`).

    def _motor_de_atajos(self, ya: bool = False) -> Any:
        """Devuelve lo que pone los atajos, creándolo cuando hace falta.

        Hace falta con algún atajo guardado o al abrir la ventana que los
        graba: un equipo sin ninguno no se conecta a X ni al portal. Si no se
        puede, `atajos_motivo` dice por qué y se vuelve a intentar más tarde,
        cada vez más espaciado (`REINTENTO_ATAJOS`, hasta
        `REINTENTO_ATAJOS_MAX`). Sin escritorio no: eso no cambia sin
        reiniciar el agente.

        Args:
            ya: Intentarlo aunque no toque todavía: lo pide el usuario al abrir
                la ventana que los graba.
        """
        if self.atajos_motor is not None or self.atajos_reintento == math.inf:
            return self.atajos_motor
        ahora = self.reloj()
        if self.atajos_reintento is not None and ahora < self.atajos_reintento and not ya:
            return None
        if self.poner_motor is None:
            motor, motivo = None, atajos.SIN_BANDEJA
        else:
            try:
                motor, motivo = self.poner_motor()
            except Exception as e:                      # noqa: BLE001
                motor, motivo = None, f"no se pueden poner: {e}"
        if motor is not None:
            self.atajos_motor, self.atajos_motivo = motor, ""
            self.atajos_reintento, self.atajos_fallos = None, 0
            diario(f"atajos de teclado: con {motor.nombre}")
            return motor
        self.atajos_fallos += 1
        if self.poner_motor is None or motivo == atajos.SIN_ESCRITORIO:
            self.atajos_reintento = math.inf
            luego = ""
        else:
            espera = min(REINTENTO_ATAJOS_MAX, REINTENTO_ATAJOS * 2 ** (self.atajos_fallos - 1))
            self.atajos_reintento = ahora + espera
            luego = f"; lo vuelvo a intentar en {espera:g} s"
        if motivo != self.atajos_motivo:
            diario(f"atajos de teclado: no se pueden poner aquí ({motivo}){luego}")
        self.atajos_motivo = motivo
        return None

    def _grabando_atajos(self) -> bool:
        """Indica si la ventana que graba los atajos está abierta."""
        return self.ventana_atajos is not None and self.ventana_atajos.poll() is None

    def _atajos_guardados(self) -> tuple[dict[str, str], dict[str, str]]:
        """Separa los atajos de `agente.json` en los que valen y los que no (`atajos.validar()`).

        Lo que se guarda desde la ventana ya vale, pero `agente.json` se puede
        haber escrito a mano o con otra versión: una combinación sin Ctrl, Alt
        ni el logotipo, Ctrl+Alt con una letra en Windows (AltGr) o la misma en
        dos acciones no se pone nunca.

        Returns:
            `(validos, rechazados)`, los dos por acción.
        """
        return atajos.validar(self.ajustes.atajos, IS_WIN)

    def _atajos_deseados(self) -> dict[str, str]:
        """Devuelve los atajos que tiene que haber puestos ahora mismo, por acción.

        Los de un «Guardar» mientras se prueban; ninguno mientras la ventana
        que los graba está abierta, para que la combinación que se pulse le
        llegue a ella y no dispare su acción (salvo con el portal, que no los
        suelta: `suspende`); si no, los guardados que valen.
        """
        if self.atajos_prueba is not None:
            return dict(self.atajos_prueba[1])
        if self._grabando_atajos() and getattr(self.atajos_motor, "suspende", True):
            return {}
        return self._atajos_guardados()[0]

    def _atajos(self, ahora: float) -> None:
        """Pone al día los atajos de teclado con el sistema.

        Recoge lo que ha contestado el motor desde su hilo, da por no puesto lo
        que lleva `ESPERA_ATAJOS` sin respuesta y, si lo que tiene que haber
        (`_atajos_deseados()`) no es lo último pedido, o es un «Guardar» que
        aún se prueba, lo pide. Una petición a la vez: el portal puede tener al
        usuario delante de su ventana, así que al vencer la espera no se vuelve
        a pedir (cerraría su ventana), pero la respuesta tardía a lo último
        pedido se acepta (`atajos_vencida`).
        """
        if self.ventana_atajos is not None and self.ventana_atajos.poll() is not None:
            self.ventana_atajos = None
            diario("se ha cerrado la ventana de los atajos de teclado")
        for accion, motivo in self._atajos_guardados()[1].items():
            combo = self.ajustes.atajos.get(accion, "")
            if (accion, combo) not in self.atajos_avisados:
                self.atajos_avisados.add((accion, combo))
                diario(f"atajo guardado que no vale: {accion} {combo!r} ({motivo})")
                avisar(*atajos.aviso_de_rechazo(accion, combo, motivo, IS_WIN))
        while True:
            try:
                combos, rechazados = self.atajos_hechos.get_nowait()
            except queue.Empty:
                break
            if ((self.atajos_en_vuelo is not None or self.atajos_vencida)
                    and combos == self.atajos_pedidos):
                self.atajos_en_vuelo, self.atajos_vencida = None, False
                self._atajos_puestos(combos, rechazados)
        if self.atajos_en_vuelo is not None and ahora - self.atajos_en_vuelo >= ESPERA_ATAJOS:
            combos = dict(self.atajos_pedidos or {})
            self.atajos_en_vuelo, self.atajos_vencida = None, True
            diario(f"atajos de teclado: {self.atajos_motor.nombre} no ha contestado en "
                   f"{ESPERA_ATAJOS:g} s")
            self._atajos_puestos(combos, {a: atajos.SIN_RESPUESTA for a in combos})
        deseados = self._atajos_deseados()
        if self.atajos_en_vuelo is not None \
                or (deseados == self.atajos_pedidos and self.atajos_prueba is None) \
                or not (deseados or self.atajos_pedidos):
            return
        motor = self._motor_de_atajos()
        if motor is None:
            if self.atajos_prueba is not None:
                self._atajos_puestos(deseados, {a: self.atajos_motivo for a in deseados})
            return
        self.atajos_pedidos, self.atajos_en_vuelo, self.atajos_vencida = deseados, ahora, False
        motor.poner(deseados)

    def _atajos_puestos(self, combos: dict[str, str], rechazados: Mapping[str, str]) -> None:
        """Hace lo que toca con lo que el sistema ha dejado poner.

        Si era un «Guardar» que se probaba, se guardan solo los que ha dejado
        (los demás quedan sin asignar) y se contesta a la ventana que espera; si
        ya no está abierta, un aviso dice cuáles no. Si nadie ha decidido (se
        canceló en la ventana del escritorio, el sistema no contestó:
        `atajos.SIN_DECIDIR`), no se guarda nada y siguen los de antes, que la
        vuelta siguiente vuelve a poner. Si eran los guardados de siempre (al
        arrancar, al cerrarse la ventana), los que no ha dejado siguen
        guardados (quien los tenía puede soltarlos) y se avisa una vez de cada
        uno.

        Args:
            combos: Lo que se pidió, por acción.
            rechazados: Por qué no se ha podido poner cada uno de los que no.
        """
        if self.atajos_prueba is not None and combos == self.atajos_prueba[1]:
            vez, pedidos, previos = self.atajos_prueba
            self.atajos_prueba = None
            todos = {**previos, **rechazados}
            nadie = atajos.sin_decidir(rechazados)
            if nadie:
                diario(f"atajos de teclado: no se ha guardado nada ({nadie}); siguen los de antes")
            else:
                self._guardar(replace(self.ajustes, atajos={a: c for a, c in pedidos.items()
                                                             if a not in rechazados}))
                self.atajos_errores = dict(todos)
                diario("atajos de teclado guardados: " + (", ".join(
                    f"{a} {atajos.texto(c, IS_WIN)}" for a, c in self.ajustes.atajos.items())
                    or "ninguno") + "".join(f"; {a} no: {m}" for a, m in todos.items()))
            self.atajos_respuesta = {"vez": vez, "rechazados": todos,
                                     "guardados": dict(self.ajustes.atajos)}
            if not self._grabando_atajos():
                if nadie:
                    avisar(*atajos.aviso_sin_guardar(nadie))
                    return
                for accion, motivo in todos.items():
                    avisar(*atajos.aviso_de_rechazo(accion, pedidos.get(accion, ""), motivo,
                                                    IS_WIN))
            return
        if combos != self._atajos_guardados()[0]:
            return                      # la suspensión mientras se graba: nada que decir
        self.atajos_errores = dict(rechazados)
        for accion, motivo in rechazados.items():
            if (accion, combos.get(accion, "")) not in self.atajos_avisados:
                self.atajos_avisados.add((accion, combos.get(accion, "")))
                avisar(*atajos.aviso_de_rechazo(accion, combos.get(accion, ""), motivo, IS_WIN))

    def _atajo(self, accion: Any, ahora: float) -> None:
        """Hace lo de un atajo pulsado sobre la última unidad usada (`atajos.pulsado()`).

        Lo que hace son las peticiones de la bandeja de siempre, atendidas aquí
        mismo; si la acción no se ve sola, un aviso lo dice. Abrir la carpeta o
        la ventana de una unidad bloqueada la desbloquea antes (`_abrir()`).
        Con la ventana que graba los atajos abierta no hace nada: es la
        combinación que se está grabando.
        """
        if accion not in atajos.ACCIONES:
            diario(f"atajo desconocido: {accion!r}")
            return
        if self._grabando_atajos():
            diario(f"atajo «{atajos.NOMBRES[accion]}» con la ventana de los atajos abierta: "
                   f"no hago nada")
            return
        desde = {**self.bloqueadas_desde,
                 **{uid: con.desde for uid, con in self.conexiones.items()}}
        r = atajos.pulsado(accion, self.resumen(), self.usadas, desde)
        con = self.conexiones.get(r.unidad)
        if con is not None:
            sobre = con.nombre
        elif r.unidad in self.ajustes.unidades:
            sobre = f"{nombre_guardado(self.ajustes.unidades[r.unidad], r.unidad)} (bloqueada)"
        else:
            sobre = "ninguna unidad"
        diario(f"atajo «{atajos.NOMBRES[accion]}»: {sobre}")
        for p in r.peticiones:
            self._atender_peticion(dict(p), ahora)
        self._usada(r.unidad, ahora)
        if r.aviso is not None:
            avisar(*r.aviso)

    def _guardar_atajos(self, pedidos: Any, vez: Any) -> None:
        """Atiende el «Guardar» de la ventana de los atajos: los prueba con el sistema.

        Lo que no vale ni para pedirlo (`atajos.validar()`) se rechaza ya; lo
        demás se pone de verdad (`atajos_prueba`) y se guarda lo que el sistema
        deje (`_atajos_puestos()`). Sin ninguno que pedir, se guarda que no hay
        ninguno.

        Args:
            pedidos: Los atajos de la ventana, por acción.
            vez: Lo que identifica este «Guardar» en la respuesta.
        """
        validos, rechazados = atajos.validar(pedidos, IS_WIN)
        vez = vez if isinstance(vez, str) else ""
        if not validos:
            self._guardar(replace(self.ajustes, atajos={}))
            self.atajos_errores = dict(rechazados)
            self.atajos_respuesta = {"vez": vez, "rechazados": dict(rechazados), "guardados": {}}
            diario("atajos de teclado guardados: ninguno")
            return
        if self._motor_de_atajos() is None:
            todos = {**rechazados, **{a: self.atajos_motivo for a in validos}}
            self.atajos_errores = dict(todos)
            self.atajos_respuesta = {"vez": vez, "rechazados": todos,
                                     "guardados": dict(self.ajustes.atajos)}
            diario(f"atajos de teclado: no se pueden guardar ({self.atajos_motivo})")
            return
        self.atajos_prueba = (vez, validos, rechazados)

    def _abrir_atajos(self) -> None:
        """Abre la ventana que graba los atajos de teclado («Atajos de teclado…»).

        Una a la vez. Si en este equipo no se pueden poner, la ventana lo dice
        y no ofrece grabar nada (`--motivo`).
        """
        if self._grabando_atajos():
            diario("la ventana de los atajos de teclado ya está abierta")
            return
        if not hay_pantalla():
            diario("sin entorno gráfico; no hay dónde abrir la ventana de los atajos")
            return
        motor = self._motor_de_atajos(ya=True)
        try:
            self.ventana_atajos = lanzar(orden_atajos("" if motor is not None
                                                      else self.atajos_motivo),
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         **_opciones_hijo(equipo.DIR))
            diario("ventana de los atajos de teclado abierta")
        except OSError as e:
            diario(f"no he podido abrir la ventana de los atajos de teclado: {e}")

    def _resumen_de_atajos(self) -> dict:
        """Devuelve lo que se cuenta de los atajos en `resumen()` (`atajos.resumen_de()`)."""
        mecanismo, motivo = atajos.mecanismo(IS_WIN, os.environ)
        if self.atajos_motivo:
            mecanismo, motivo = None, self.atajos_motivo
        errores = {**self.atajos_errores, **self._atajos_guardados()[1]}
        return atajos.resumen_de(mecanismo, motivo, self.ajustes.atajos, errores,
                                 self._grabando_atajos(), self.atajos_respuesta)

    def _abrir(self, uid: str, ahora: float, explorador: bool = False,
               llavero: bool = False) -> None:
        """Hace «Configurar», «Abrir en explorador» o «Abrir llavero» de una raíz.

        Una unidad que no está en la lista no: sería ejecutar su código sin el
        sí, y tampoco se abre su carpeta (la misma regla, sin excepciones). Ni
        una que se está actualizando, hasta que acabe. Bloqueada (la raíz
        cifrada de este equipo, una unidad con BitLocker o una de VeraCrypt con
        el contenedor cerrado) se pide antes su contraseña, y su ventana o su
        carpeta salen al verla abierta, si su código sigue siendo el aceptado;
        su llavero no, porque bloqueada no se sabe si lo lleva.

        Args:
            uid: El id de la raíz.
            ahora: La hora del reloj del agente.
            explorador: Abrirla en el explorador de archivos en vez de su
                ventana.
            llavero: Abrir su llavero (`runsync.py --llavero`) en vez de su
                ventana.
        """
        que = ("abrir en el explorador" if explorador else
               "abrir el llavero" if llavero else "abrir")
        unidad = self.ajustes.unidades.get(uid)
        con = self.conexiones.get(uid)
        if unidad is None or (con is not None and (con.cambiada or self._por_actualizar(con))):
            diario(f"{que} {uid[:8]!r}: no está en la lista, o su código ha cambiado; "
                   f"no se ejecuta nada suyo")
        elif con is not None and con.actualizacion is not None:
            diario(f"{que} {con.nombre}: se está actualizando; cuando acabe")
        elif con is not None and con.id in self.expulsiones:
            diario(f"{que} {con.nombre}: se está expulsando")
        elif con is not None:
            if explorador:
                self._explorar(con)
            elif llavero:
                self._lanzar_llavero(con)
            else:
                self._lanzar_ventana(con)
        elif llavero:
            diario(f"{que} {nombre_guardado(unidad, uid)}: no está abierta aquí ahora")
        elif unidad.cifrada and uid not in self.ausentes:
            self._desbloquear(unidad, ahora, "para abrirla en el explorador" if explorador
                              else "para abrirla", abrir=not explorador, explorar=explorador)
        elif self._bloqueada_bitlocker(uid) is not None:
            if self._desbloquear_bitlocker(uid, ahora):
                self._abrir_al_abrirse(uid, ahora, explorador)
        elif self._cerrada_veracrypt(uid) is not None:
            if self._abrir_vestibulo(uid, ahora):
                self._abrir_al_abrirse(uid, ahora, explorador)
        else:
            diario(f"{que} {nombre_guardado(unidad, uid)}: no está aquí ahora")

    def _abrir_al_abrirse(self, uid: str, ahora: float, explorador: bool) -> None:
        """Apunta que, al conectarse esa unidad bloqueada, se abra su carpeta o su ventana.

        Pedirlo otra vez renueva el plazo (`ESPERA_ABRIR`) y suma lo pedido:
        carpeta y ventana pueden ir las dos.

        Args:
            uid: El id de la unidad.
            ahora: La hora del reloj del agente.
            explorador: Su carpeta; si no, su ventana.
        """
        pedido = self.al_abrirse.setdefault(uid, AlAbrirse(ahora))
        pedido.desde = ahora
        if explorador:
            pedido.explorar = True
        else:
            pedido.abrir = True
        diario(f"{nombre_guardado(self.ajustes.unidades.get(uid), uid)}: al abrirse, se abre "
               + ("su carpeta" if explorador else "su ventana"))

    def _explorar(self, con: Conexion) -> None:
        """Abre esa raíz en el explorador de archivos (`explorar()`)."""
        if not hay_pantalla():
            diario(f"{con.nombre}: sin entorno gráfico; no hay dónde abrir su carpeta")
            return
        try:
            if explorar(con.raiz):
                diario(f"{con.nombre}: abierta en el explorador de archivos")
            else:
                diario(f"{con.nombre}: no hay con qué abrir su carpeta en este equipo "
                       f"(falta xdg-open)")
        except OSError as e:
            diario(f"{con.nombre}: no he podido abrir su carpeta: {e}")

    def _emblema(self, con: Conexion) -> dict:
        """Devuelve el icono de esa raíz para la bandeja (`volumen.emblema()`).

        Solo de una raíz de la lista, con su código aceptado y de una versión
        válida: de las demás no se lee nada más que su id y su nombre, y llevan
        la marca de prdrive (`{}`). Se lee su `autorun.inf` donde lo pone
        «Nombre e icono…»: en la propia raíz, que en una unidad o una raíz del
        equipo cifradas es el volumen montado. Como mucho una vez cada
        `MIRAR_EMBLEMA`.
        """
        if (con.id not in self.ajustes.unidades or con.cambiada
                or self._por_actualizar(con)):
            return {}
        ahora = self.reloj()
        if con.emblema is None or ahora - con.emblema_leido >= MIRAR_EMBLEMA:
            con.emblema = volumen.emblema(con.raiz, APP_SUBDIR)
            con.emblema_leido = ahora
        return con.emblema

    def _version_de(self, con: Conexion) -> str:
        """Devuelve la versión del programa de esa raíz, para su desplegable.

        Es su `VERSION`, un fichero de texto que se lee y no se ejecuta, como
        el de `version_vieja()` al conectarla: también la de una unidad que no
        está en la lista. Como mucho una vez cada `MIRAR_EMBLEMA`, porque
        actualizarla desde su ventana la cambia sin desconectarla. `""` si no
        se sabe.
        """
        ahora = self.reloj()
        if con.version is None or ahora - con.version_leida >= MIRAR_EMBLEMA:
            con.version = update.installed_version(app(con.raiz))
            con.version_leida = ahora
        return con.version

    def _llavero_de(self, con: Conexion) -> bool:
        """Indica si esa raíz lleva llavero (`[keychain]` en su `sync_config.toml`).

        Solo de una raíz de la lista, con su código aceptado y de una versión
        válida, como su icono: de las demás no se lee nada más. Se lee el TOML
        sin el modelo (`components.llavero_activo()`), como mucho una vez cada
        `MIRAR_EMBLEMA`: activarlo desde su ventana lo cambia sin desconectarla.
        """
        if (con.id not in self.ajustes.unidades or con.cambiada
                or self._por_actualizar(con)):
            return False
        ahora = self.reloj()
        if con.llavero is None or ahora - con.llavero_leido >= MIRAR_EMBLEMA:
            con.llavero = components.llavero_activo(app(con.raiz))
            con.llavero_leido = ahora
        return con.llavero

    def _copias_del_llavero(self, con: Conexion, ahora: float, ya: bool = False) -> None:
        """Mira si el llavero de esa raíz tiene copias de conflicto, y avisa de las nuevas.

        Es lo que su `sync.py` apunta en `state/conflicts.json` tras cada
        pasada (`conflicts.actualizar_pareja()`): un JSON que se lee y no se
        ejecuta, porque el agente no lleva el modelo de la raíz. Se mira tras
        cada pasada del llavero (`ya`) y si no, como mucho cada
        `MIRAR_EMBLEMA`: «Combinar» las quita sin pasada del agente.

        Se avisa una vez por conexión de cada copia nueva: no hay que elegir,
        combinarlas no pierde nada, y el aviso dice cómo. Cuando ya no queda
        ninguna se olvida lo avisado, para que un conflicto nuevo con el mismo
        nombre se vuelva a decir.

        Args:
            con: La conexión.
            ahora: La hora del reloj del agente.
            ya: Mirarlas ahora, haya pasado lo que haya pasado.
        """
        if not ya and ahora - con.copias_leidas < MIRAR_EMBLEMA:
            return
        con.copias_leidas = ahora
        copias: list = []
        if self._llavero_de(con):
            datos = store.read_json(estado_de(con.raiz) / "conflicts.json")
            parejas = datos.get("parejas")
            copias = parejas.get(model.LLAVERO) if isinstance(parejas, dict) else []
        con.copias = tuple(sorted(c for c in copias if isinstance(c, str))) \
            if isinstance(copias, list) else ()
        if not con.copias:
            con.copias_avisadas = frozenset()
            return
        nuevas = set(con.copias) - con.copias_avisadas
        if nuevas:
            con.copias_avisadas |= nuevas
            diario(f"{con.nombre}: el llavero tiene copias de conflicto: "
                   f"{', '.join(sorted(nuevas))}")
            avisar(f"{con.nombre}: el llavero tiene dos versiones",
                   LLAVERO_EN_CONFLICTO + (COMBINAR_AQUI if ABRE_LLAVERO else COMBINAR_A_MANO))

    def _estado_raiz(self, uid: str, unidad: equipo.Unidad) -> str:
        """Devuelve en qué está una raíz de este equipo, para la bandeja."""
        if uid in self.ausentes:
            return bandeja.AUSENTE
        if uid in self.fantasmas:
            return bandeja.FANTASMA
        if uid in self.bloqueos:
            return bandeja.BLOQUEANDO
        if uid in self.conexiones:
            return bandeja.ABIERTA
        if uid in self.desbloqueos:
            return bandeja.DESBLOQUEANDO
        return bandeja.BLOQUEADA if unidad.cifrada else bandeja.BUSCANDO

    def _vigilancia(self, con: Conexion) -> tuple[list[str], list[str], dict[str, str]]:
        """Devuelve las parejas de una raíz que se vigilan, las abandonadas y las que se recorren.

        Solo cuentan las del servicio del agente en modo `daemon` (en `sync` no
        hay intervalo que adelantar). Las abandonadas son las que pasaron del
        tope de entradas o cuya carpeta cae fuera de la raíz: siguen por su
        intervalo. De las vigiladas, las que se recorren en vez de oír los
        avisos del sistema van con el porqué.
        """
        unidad = self.ajustes.unidades.get(con.id)
        if con.lock is None or con.servicio is None or unidad is None \
                or unidad.modo != equipo.DAEMON:
            return [], [], {}
        pedidas = [p.nombre for p in con.servicio.parejas if p.vigila]
        dejadas = [n for n in pedidas
                   if self.vigiladas.get((con.id, n), pl.Vigilada()).abandonada]
        vigila = sorted(set(pedidas) - set(dejadas))
        if self.avisos_carpeta is None:
            recorre = {n: SIN_MOTOR_DE_AVISOS for n in vigila}
        else:
            recorre = {n: self.sin_avisos[(con.id, n)] for n in vigila
                       if (con.id, n) in self.sin_avisos}
        return vigila, sorted(dejadas), recorre

    def resumen(self) -> dict:
        """Devuelve lo que el agente cuenta de sí mismo.

        Es lo que va a `estado.json` y lo que la bandeja convierte en su vista
        (`bandeja.vista()`).
        """
        unidades = []
        for con in self.conexiones.values():
            unidad = self.ajustes.unidades.get(con.id)
            vigila, abandonadas, recorre = self._vigilancia(con)
            unidades.append({"id": con.id, "nombre": con.nombre, "raiz": str(con.raiz),
                             "del_equipo": bool(unidad and unidad.es_raiz),
                             "cifrada": bool(unidad and unidad.cifrada),
                             "modo": unidad.modo if unidad else None,
                             "atendida": con.lock is not None,
                             "motivo": con.motivo,
                             "en_lista": unidad is not None and not con.cambiada
                             and not self._por_actualizar(con),
                             "cambiada": con.cambiada,
                             "vieja": con.vieja,
                             "a_medias": con.a_medias,
                             "actualizable": con.actualizacion is None
                             and self._actualizable(con),
                             "actualizando": con.actualizacion is not None,
                             "ahora_no": con.respuesta == pl.AHORA_NO,
                             "preguntando": con.pregunta is not None,
                             "error": con.error,
                             "pausada": bool(unidad and unidad.pausada),
                             "fallando": sorted(p for (r, p), m in self.marcas.items()
                                                if r == con.id and m.fallos > 0),
                             "saltadas": sorted(p for r, p in self.saltadas
                                                if r == con.id),
                             "estiradas": self._estiradas(con),
                             "vigila": vigila,
                             "vigila_abandonada": abandonadas,
                             "vigila_recorre": recorre,
                             "emblema": self._emblema(con),
                             "cifrado": self._cifrado_de(con.id),
                             "pedir_al_conectar": self._pide_al_conectar(con.id),
                             "version": self._version_de(con),
                             "llavero": self._llavero_de(con),
                             "llavero_abierto": con.id in self.keepassxc,
                             "llavero_conflicto": len(con.copias),
                             "expulsable": self._expulsable(con),
                             "expulsando": con.id in self.expulsiones})
            solo = self._bloquear_solo(con)
            if solo:
                unidades[-1]["bloquear_solo"] = solo
        cerradas = [nombre_guardado(u, u.id) for u in self.ajustes.cifradas.values()
                    if u.id not in self.conexiones and u.id not in self.ausentes]
        return {"pid": os.getpid(), "pausado": self.pausado, "retenido": self.retenido,
                "pasada": None if self.pasada is None else {
                    "unidad": self.pasada.nombre,
                    "pareja": ", ".join(t.pareja for t in self.pasada.tareas)
                    if self.pasada.tarea.pareja else None,
                    "tipo": self.pasada.tarea.tipo},
                "sin_conexion": sorted(f"{self.conexiones[r].nombre}: {m}"
                                       for r, m in self.entorno.sin_conexion
                                       if r in self.conexiones),
                "cambios_de_red": self.avisos_de_red.fuente
                if self.avisa_la_red() else "",
                "unidades": unidades,
                "ausentes": sorted((self.ajustes.unidades[u].contenedor
                                    or self.ajustes.unidades[u].ruta)
                                   for u in self.ausentes if u in self.ajustes.unidades),
                "bloqueadas": sorted(cerradas),
                "desbloqueando": sorted(nombre_guardado(self.ajustes.unidades[u], u)
                                        for u in self.desbloqueos
                                        if u in self.ajustes.unidades),
                "bloqueando": sorted(nombre_guardado(self.ajustes.unidades[u], u)
                                     for u in self.bloqueos if u in self.ajustes.unidades),
                "fantasmas": sorted(self.ajustes.unidades[u].ruta for u in self.fantasmas
                                    if u in self.ajustes.unidades),
                # Las unidades de la lista enchufadas y bloqueadas con BitLocker.
                "bitlocker": sorted(
                    ({"id": uid, "nombre": nombre_guardado(self.ajustes.unidades[uid], uid),
                      "raiz": str(raiz),
                      "desbloqueando": self._desbloqueando_bitlocker(uid),
                      "pedir_al_conectar": self.ajustes.unidades[uid].pide_al_conectar(
                          equipo.CIFRADO_BITLOCKER)}
                     for uid, raiz in self.bitlocker.items()
                     if self._bloqueada_bitlocker(uid) is not None),
                    key=lambda b: (b["nombre"], b["id"])),
                # Las unidades de VeraCrypt de la lista enchufadas y con el
                # contenedor cerrado: un atajo de abrir su carpeta las abre.
                "vestibulos": sorted(
                    ({"id": uid, "nombre": nombre_guardado(self.ajustes.unidades[uid], uid),
                      "raiz": str(raiz)}
                     for uid in self.vestibulos
                     if (raiz := self._cerrada_veracrypt(uid)) is not None),
                    key=lambda v: (v["nombre"], v["id"])),
                # Las raíces de este equipo, con su estado: lo que pinta la bandeja.
                "equipo": [{"id": uid, "nombre": nombre_guardado(u, uid), "ruta": u.ruta,
                            "cifrada": u.cifrada, "estado": self._estado_raiz(uid, u)}
                           for uid, u in self.ajustes.raices.items()],
                "pedir_al_iniciar": self.ajustes.pedir_al_iniciar,
                # Dónde se abre el llavero: Windows y Linux (fase 2).
                "abre_llavero": ABRE_LLAVERO,
                "ultima_pasada": self.ultima_buena,
                "version": self.version, "nueva": self.nueva,
                "actualizando": self._actualizandose(),
                "buscando": self.buscando,
                # Los atajos de teclado: lo que enseñan la bandeja y su ventana.
                "atajos": self._resumen_de_atajos()}

    def _escribir_estado(self) -> None:
        """Escribe `estado.json` y le pasa la vista a la bandeja, si cambian."""
        resumen = self.resumen()
        if resumen != self.ultimo_estado:
            self.ultimo_estado = resumen
            store.write_json(equipo.estado_json(), {**resumen, "actualizado": store.stamp()})
        if self.bandeja is not None:
            # Se compara la vista y no el resumen: el texto del ratón dice
            # «sincronizado hace N min», que cambia sin que cambie nada más.
            try:
                vista = bandeja.vista(resumen, self.reloj())
                if vista != self.ultima_vista:
                    self.ultima_vista = vista
                    self.bandeja.poner(vista)
            except Exception as e:                  # noqa: BLE001
                diario(f"la bandeja no se ha podido poner al día: {e}")

    def cerrar(self) -> None:
        """Se despide: suelta los locks que sean nuestros.

        Una pasada en marcha sigue sola hasta acabar; nadie la mata desde aquí.
        """
        for con in self.conexiones.values():
            if presente(con.raiz):
                self._soltar(con)
        store.write_json(equipo.estado_json(), {"pid": None, "actualizado": store.stamp()})


MOUNTINFO = Path("/proc/self/mountinfo")
"""Tabla de montajes de Linux, que avisa con `POLLPRI` cuando cambia."""
CALLAR_AVISOS = 0.25
"""Segundos que el vigía deja de oír los avisos de carpeta tras leerlos.

Una copia grande da miles de avisos por segundo: se leen a ratos (la cola del
núcleo aguanta miles entre lectura y lectura) y no uno a uno.
"""


class Vigia:
    """Espera el tic, o menos si cambian los montajes o alguien lo despierta.

    En Linux, `/proc/self/mountinfo` avisa con `POLLPRI` (y `POLLERR`) cuando
    cambia la tabla de montajes; hay que releerlo entero para rearmar el aviso.
    En Windows los montajes los dice la bandeja (`WM_DEVICECHANGE`), desde su
    hilo, con `despertar(montajes=True)`; y lo que se elige en su menú, con
    `despertar()`, para no esperar al tic. En Linux ese despertar va por un
    pipe que se vigila junto a mountinfo, y con ellos el descriptor de los
    avisos de carpeta (`oir()`), que se lee sin acabar la espera.
    """

    def __init__(self) -> None:
        """Prepara la espera.

        En Linux, mountinfo y el pipe; en Windows, solo el evento.
        """
        self._f = None
        self._poll = None
        self._evento = threading.Event()
        self._montajes = False
        self._pipe: tuple[int, int] | None = None
        self._oido: tuple[int, Any] | None = None
        self._buzon: tuple[int, Any] | None = None
        if IS_WIN:
            return
        try:
            import select
            self._poll = select.poll()
            self._pipe = os.pipe()
            os.set_blocking(self._pipe[1], False)
            self._poll.register(self._pipe[0], select.POLLIN)
            self._f = MOUNTINFO.open("rb")
            self._f.read()
            self._poll.register(self._f.fileno(), select.POLLPRI | select.POLLERR)
        except (OSError, AttributeError, ImportError):
            if self._f is not None:
                self._f.close()
            self._f = None
            if self._pipe is None:
                self._poll = None

    def despertar(self, montajes: bool = False) -> None:
        """Hace que la espera acabe ya; se puede llamar desde cualquier hilo.

        Args:
            montajes: Avisa además de que han cambiado los montajes.
        """
        if montajes:
            self._montajes = True
        self._evento.set()
        if self._pipe is not None:
            try:
                os.write(self._pipe[1], b"!")
            except OSError:
                pass                # lleno: ya hay un despertar pendiente

    def oir(self, fd: int, leer) -> None:
        """Espera también en el descriptor de los avisos de carpeta.

        Cuando tiene algo se llama a `leer()`, que lo vacía en el acto (la cola
        del núcleo no se llena entre dos vueltas), y se le deja de oír
        `CALLAR_AVISOS` segundos. La espera NO acaba por él: la pasada espera a
        la calma igualmente, y una copia de miles de ficheros no puede hacer
        girar la vuelta miles de veces. Como el que lo vacía es el vigía, una
        vuelta que falla o que se salta los avisos no lo deja con algo dentro
        haciendo que `poll` vuelva enseguida. Un `leer()` que lanza se deja de
        oír, y se dice. Sin `poll` (Windows), nada.

        Args:
            fd: El descriptor (`avisos_carpeta.Inotify.fd`).
            leer: Lo que lo vacía (`avisos_carpeta.Inotify.leer`).
        """
        if self._poll is None:
            return
        import select
        try:
            self._poll.register(fd, select.POLLIN)
        except (OSError, ValueError):
            return
        self._oido = (fd, leer)

    def oir_buzon(self, fd: int, leer) -> bool:
        """Espera también en el descriptor del oyente del buzón (`avisos_buzon`, Linux).

        Cuando tiene algo se llama a `leer()`, que lo vacía y dice si era el
        buzón: entonces la espera acaba, como con `despertar()`.

        Returns:
            `True` si queda oído; `False` sin `poll` o si no se deja registrar.
        """
        if self._poll is None:
            return False
        import select
        try:
            self._poll.register(fd, select.POLLIN)
        except (OSError, ValueError):
            return False
        self._buzon = (fd, leer)
        return True

    def _leer_avisos(self) -> None:
        """Vacía el descriptor oído; si falla, deja de oírlo y lo dice."""
        fd, leer = self._oido
        try:
            leer()
        except Exception as e:                              # noqa: BLE001
            self._dejar_de_oir()
            diario(f"dejo de oír los avisos de las carpetas: {type(e).__name__}: {e}")

    def _dejar_de_oir(self) -> None:
        """Quita el descriptor oído de la espera."""
        if self._oido is not None:
            try:
                self._poll.unregister(self._oido[0])
            except (OSError, KeyError, ValueError):
                pass
            self._oido = None

    def _tomar_montajes(self) -> bool:
        """Devuelve si hubo aviso de montajes, y lo olvida."""
        montajes, self._montajes = self._montajes, False
        self._evento.clear()
        return montajes

    def esperar(self, segundos: float) -> bool:
        """Espera hasta `segundos`, o hasta que lo despierten o cambien los montajes.

        Los avisos de carpeta (`oir()`) se leen por el camino sin acabarla.

        Returns:
            `True` si han cambiado los montajes (hay que recorrer en racha).
        """
        if self._poll is None:
            self._evento.wait(segundos)
            return self._tomar_montajes()
        import select
        fin = time.monotonic() + segundos
        montajes = False
        callado: float | None = None        # hasta cuándo no se oyen los avisos
        try:
            while True:
                ahora = time.monotonic()
                if callado is not None and ahora >= callado:
                    callado = None
                    if self._oido is not None:
                        self._poll.modify(self._oido[0], select.POLLIN)
                resto = fin - ahora
                if resto <= 0:
                    break
                if callado is not None:
                    resto = min(resto, callado - ahora)
                despierto = False
                for fd, que in self._poll.poll(math.ceil(resto * 1000)):
                    if self._pipe is not None and fd == self._pipe[0]:
                        os.read(fd, 4096)
                        despierto = True
                    elif self._buzon is not None and fd == self._buzon[0]:
                        try:
                            if que & (select.POLLERR | select.POLLHUP | select.POLLNVAL):
                                raise OSError("descriptor cerrado")
                            if self._buzon[1]():
                                despierto = True
                        except Exception:               # noqa: BLE001
                            try:
                                self._poll.unregister(fd)
                            except (OSError, KeyError, ValueError):
                                pass
                            self._buzon = None
                    elif self._oido is not None and fd == self._oido[0]:
                        if que & (select.POLLERR | select.POLLHUP | select.POLLNVAL):
                            self._dejar_de_oir()
                            continue
                        self._leer_avisos()
                        if self._oido is not None:
                            self._poll.modify(fd, 0)
                            callado = time.monotonic() + CALLAR_AVISOS
                    elif self._f is not None and fd == self._f.fileno():
                        self._f.seek(0)
                        self._f.read()
                        montajes = despierto = True
                if despierto:
                    break
        except OSError:
            time.sleep(max(0.0, fin - time.monotonic()))
        finally:
            if callado is not None and self._oido is not None:
                try:
                    self._poll.modify(self._oido[0], select.POLLIN)
                except OSError:
                    pass
        return self._tomar_montajes() or montajes


def poner_bandeja(agente: Agente, vigia: Vigia) -> Any:
    """Devuelve la bandeja del agente, o `None` si no se ha podido poner.

    Punto de indirección: los tests no ponen ninguna.

    Windows (fase 4): `Shell_NotifyIconW`. Linux (fase 6): StatusNotifierItem
    en el bus de sesión; sin nadie que haga de `StatusNotifierWatcher`, la
    bandeja existe pero sin icono (`puesta` False), se dice en el diario y el
    icono se pone solo si el watcher aparece después. Mientras, el acceso
    «prdrive» del menú hace sus veces.
    """

    def pedir(peticion: dict) -> None:
        """Pasa al agente una petición de la bandeja y lo despierta."""
        agente.pedir(peticion)
        vigia.despertar()

    if not IS_WIN:
        from ui import bandeja_linux
        b = bandeja_linux.Bandeja(pedir)
        if not b.arrancar():
            diario("sin bus de sesión: sigo sin bandeja (el acceso del menú hace sus "
                   "veces)")
            return None
        if not b.puesta:
            diario(f"este escritorio no tiene bandeja (nadie es {bandeja_linux.WATCHER}): "
                   f"el acceso «{APP_NAME}» del menú hace sus veces; si aparece una, el "
                   f"icono se pone solo")
        return b
    from ui import bandeja_windows, icons
    try:
        icons.write_bandeja(SCRIPT_DIR, solo_si_faltan=True)
    except Exception as e:                              # noqa: BLE001
        diario(f"no he podido pintar los iconos de la bandeja: {e}")

    b = bandeja_windows.Bandeja(SCRIPT_DIR, pedir, lambda: vigia.despertar(montajes=True))
    b.fin_de_sesion = agente.lanzar_al_salir
    if not b.arrancar():
        diario("no he podido poner la bandeja: sigo sin ella")
        return None
    return b


class MotorDeBandeja:
    """Los atajos de teclado de Windows: los pone la bandeja, en su hilo (`RegisterHotKey`).

    Da a la bandeja la forma de los motores de Linux (`ui/atajos_linux.py`):
    `poner()`, `cerrar()`, `nombre` y `suspende`.

    Args:
        bandeja_: La bandeja de Windows, ya arrancada.
    """

    nombre = atajos.NOMBRE_MECANISMO[atajos.WINDOWS]
    suspende = True

    def __init__(self, bandeja_: Any) -> None:
        """Guarda la bandeja."""
        self.bandeja = bandeja_

    def poner(self, combos: dict[str, str]) -> None:
        """Pide a la bandeja estos atajos; sin ventana, ninguno se ha podido poner."""
        if not self.bandeja.poner_atajos(combos) and self.bandeja.atajos_puestos is not None:
            self.bandeja.atajos_puestos(dict(combos),
                                        {a: atajos.SIN_BANDEJA for a in combos})

    def cerrar(self) -> None:
        """No hace nada: los atajos se sueltan al cerrarse la ventana de la bandeja."""


def poner_atajos(agente: Agente, vigia: Vigia) -> tuple[Any, str]:
    """Crea lo que pone los atajos de teclado globales en este equipo.

    Punto de indirección: los tests ponen uno de mentira. Lo llama el agente
    la primera vez que hace falta (`Agente._motor_de_atajos()`), no al
    arrancar.

    En Windows es la bandeja (`MotorDeBandeja`): sin ella no hay hilo con bucle
    de mensajes que reciba `WM_HOTKEY`. En Linux, `XGrabKey` en X11 y el portal
    en Wayland (`ui/atajos_linux.py`), cada uno en su hilo. Cada atajo pulsado
    es una petición más del agente (`atajo`), y lo que contesta el sistema al
    ponerlos va a `Agente.atajos_hechos`; las dos cosas despiertan al vigía.

    Returns:
        `(motor, "")`, o `(None, por qué no se puede)`.
    """
    mecanismo, motivo = atajos.mecanismo(IS_WIN, os.environ)
    if mecanismo is None:
        return None, motivo

    def pulsado(accion: str) -> None:
        """Pasa al agente un atajo pulsado y lo despierta."""
        agente.pedir({"pide": equipo.PIDE_ATAJO, "accion": accion})
        vigia.despertar()

    def puestos(combos: dict, rechazados: dict) -> None:
        """Pasa al agente lo que ha dejado poner el sistema y lo despierta."""
        agente.atajos_hechos.put((combos, rechazados))
        vigia.despertar()

    if IS_WIN:
        if agente.bandeja is None or not getattr(agente.bandeja, "hwnd", None):
            return None, atajos.SIN_BANDEJA
        agente.bandeja.atajos_puestos = puestos
        return MotorDeBandeja(agente.bandeja), ""
    from ui import atajos_linux
    motor = atajos_linux.poner(mecanismo, pulsado, puestos)
    if not motor.arrancar():
        motor.cerrar()
        return None, motor.motivo or "no se han podido poner"
    return motor, ""


def poner_red(agente: Agente, vigia: Vigia) -> Any:
    """Devuelve lo que oye los cambios de red, o `None` si no se oye ninguno.

    Punto de indirección: los tests no ponen ninguno.

    Es `common/red.py`, independiente de la bandeja: el agente sin icono también
    se entera. Cada aviso es un `equipo.PIDE_CAMBIO_DE_RED` en la cola del
    agente, que lo despierta. Sin avisos, un remoto sin conexión se sigue
    sondeando cada `Politica.sondeo_sin_conexion`.
    """
    from common import red

    def avisar() -> None:
        """Pasa al agente el aviso de que vuelve a haber red y lo despierta."""
        agente.pedir({"pide": equipo.PIDE_CAMBIO_DE_RED})
        vigia.despertar()

    avisos_de_red = red.AvisosDeRed(avisar)
    respaldo = pl.sondeo(agente.ajustes.politica, True) / 60
    sin_avisos = pl.sondeo(agente.ajustes.politica, False) / 60
    if not avisos_de_red.arrancar():
        avisos_de_red.cerrar()
        diario(f"no oigo los cambios de red: un remoto sin conexión se prueba cada "
               f"{sin_avisos:g} min")
        return None
    if avisos_de_red.activa:
        diario(f"oigo los cambios de red ({avisos_de_red.fuente}): un remoto sin "
               f"conexión se prueba cuando vuelve la red, y si no, cada {respaldo:g} min")
    else:
        diario(f"todavía no oigo los cambios de red (sin NetworkManager): un remoto sin "
               f"conexión se prueba cada {sin_avisos:g} min")
    return avisos_de_red


def poner_avisos_carpeta(agente: Agente, vigia: Vigia) -> Any:
    """Devuelve el motor de los avisos de cambios de las carpetas vigiladas, o `None`.

    Punto de indirección: los tests ponen uno de mentira en `Agente.avisos_carpeta`.

    Es `common/avisos_carpeta.py`. En Linux, inotify: el vigía lee su
    descriptor (`Vigia.oir()`). En Windows, `ReadDirectoryChangesW`, que deja
    abierta la carpeta de cada pareja vigilada y necesita la ventana de la
    bandeja: por ella llega el aviso de que el sistema pide la unidad, y la
    bandeja se lo pasa (`Bandeja.dispositivo`) para cerrarla a tiempo. Sin
    bandeja no hay motor. Sin motor, las carpetas de las parejas con
    `watch = true` se recorren a su ritmo (`pl.cada_cuanto()`). Se dice en el
    diario cuál de los dos.
    """
    cambios = agente.cambios
    recorre = (f"las carpetas de las parejas con watch se recorren (cada "
               f"{cambios.sondeo:g} s tras un cambio, cada {cambios.sondeo_quieto / 60:g} min "
               f"si están quietas)")
    hwnd = None
    if IS_WIN:
        hwnd = getattr(agente.bandeja, "hwnd", None)
        if not hwnd:
            diario(f"sin bandeja no se dejan carpetas abiertas en las unidades: {recorre}")
            return None
    try:
        motor = avisos_carpeta.abrir(hwnd=hwnd, veracrypt=agente.ajustes.avisos_veracrypt)
    except OSError as e:
        diario(f"no oigo los cambios de las carpetas ({e}): {recorre}")
        return None
    if motor is None:
        diario(f"en este sistema {recorre}")
        return None
    if getattr(motor, "fd", None) is not None:
        vigia.oir(motor.fd, motor.leer)
    if IS_WIN:
        agente.bandeja.dispositivo = motor.dispositivo
        agente.bandeja.volumen = motor.volumen
    diario("oigo los cambios de las carpetas de las parejas con watch ("
           + ("ReadDirectoryChangesW" if IS_WIN else "inotify")
           + "); se recorre solo la que no avisa"
           + ("; también oigo los volúmenes de VeraCrypt (avisos_veracrypt)"
              if IS_WIN and agente.ajustes.avisos_veracrypt else ""))
    return motor


def poner_buzon(agente: Agente, vigia: Vigia) -> Any:
    """Devuelve el oyente del buzón del agente, o `None` si aquí no se puede oír.

    Punto de indirección: los tests no ponen ninguno. Es `common/avisos_buzon.py`:
    el sistema dice cuándo alguien escribe `agente.pide`, y entonces el vigía
    despierta. Con él (`Agente.oye_buzon`) el agente deja de mirar el buzón
    cada 2 s cuando no tiene nada a la vista (`cuanto_esperar()`).
    """
    try:
        equipo.DIR.mkdir(parents=True, exist_ok=True)
        oyente = avisos_buzon.abrir(equipo.DIR, equipo.buzon().name, vigia.despertar)
    except OSError:
        oyente = None
    if oyente is not None and oyente.fd is not None \
            and not vigia.oir_buzon(oyente.fd, oyente.leer):
        oyente.cerrar()
        oyente = None
    agente.oye_buzon = oyente is not None
    diario("oigo el buzón del agente: sin nada a la vista, miro cada "
           f"{REPOSO:g} s" if oyente is not None
           else f"no oigo el buzón del agente: lo miro cada {TICK:g} s")
    return oyente


def cuanto_esperar(agente: Agente, decision: pl.Decision | None = None) -> float:
    """Devuelve cuántos segundos puede esperar el bucle del agente hasta su vuelta siguiente.

    El tic de siempre (`TICK`) mientras haya algo que mirar de cerca
    (`Agente.en_reposo()`): una pasada u otro hijo, una unidad a la vista, una
    racha de montajes, algo a medias. Sin nada de eso, y solo si el buzón avisa
    (`Agente.oye_buzon`), hasta `REPOSO`, o hasta que toque el recorrido de
    respaldo si es antes: todo lo demás que puede pasar (un montaje, la
    bandeja, la red, una petición) despierta al vigía.

    Args:
        decision: Lo que decidió la vuelta; no se usa todavía (con una unidad
            a la vista manda su contrato, que se mira cada `TICK`).
    """
    if not agente.oye_buzon or not agente.en_reposo():
        return TICK
    return max(TICK, min(REPOSO, agente.proximo_recorrido - agente.reloj()))


def _enganchar_penwatch() -> None:
    """Lleva a penwatch al diario del agente.

    Lo que penwatch escribe en su diario va al del agente: el agente lo
    sustituye en este equipo y su carpeta ya no existe.
    """
    penwatch.HOST_DIR = equipo.DIR
    penwatch.LOG_FILE = equipo.diario_log()


def _terminar_con_finally(*_args) -> None:
    """Hace de SIGTERM una salida normal.

    Cerrar sesión, `systemctl stop` o `timeout` mandan SIGTERM: sin esto Python
    muere sin pasar por los `finally` y el lock de la unidad se queda escrito
    con un pid muerto.
    """
    raise SystemExit(0)


def cmd_run(_args: argparse.Namespace) -> int:
    """Es el bucle del agente: recorre, vuelve a vuelta y espera al tic.

    Returns:
        0 al terminar; 1 si no puede usar su carpeta.
    """
    _enganchar_penwatch()
    if not IS_WIN:
        import signal
        signal.signal(signal.SIGTERM, _terminar_con_finally)
        signal.signal(signal.SIGHUP, _terminar_con_finally)
    try:
        equipo.DIR.mkdir(parents=True, exist_ok=True)
        os.chdir(equipo.DIR)            # nunca dentro de una unidad
    except OSError as e:
        print(f"No puedo usar {equipo.DIR}: {e}", file=sys.stderr)
        return 1
    # Tomar el lock es mirar y escribir en un paso (`equipo.tomar_lock()`): dos
    # arranques a la vez no pueden ver los dos que no hay nadie.
    otro = equipo.tomar_lock({"pid": os.getpid(), "host": HOST, "started": store.stamp(),
                              "arranque": store.arranque_del_sistema(),
                              "codigo": str(SCRIPT_DIR)})
    if otro is not None:
        print(f"Ya hay un agente en marcha (pid {otro.get('pid', '?')}).")
        return 0
    icono = SCRIPT_DIR / "runsync.ico"
    if icono.is_file():
        avisos.ICONO = icono
    agente = Agente()
    diario(f"agente iniciado (pid {os.getpid()}, {len(agente.ajustes.unidades)} "
           f"unidades en la lista)")
    vigia = Vigia()
    agente.bandeja = poner_bandeja(agente, vigia)
    agente.avisos_de_red = poner_red(agente, vigia)
    agente.avisos_carpeta = poner_avisos_carpeta(agente, vigia)
    agente.poner_motor = lambda: poner_atajos(agente, vigia)
    oyente_del_buzon = poner_buzon(agente, vigia)
    # Sin quien avise de los montajes (Windows sin bandeja) se recorre como
    # penwatch; con él, el recorrido de respaldo y las rachas tras cada aviso.
    try:
        while not (agente.terminar and agente.pasada is None):
            recorrer = agente.toca_recorrer(time.time())
            decision = None
            try:
                decision = agente.vuelta(recorrer)
            except Exception as e:                      # noqa: BLE001
                # Un fallo de una vuelta no puede tumbar al agente de todas las
                # unidades: se apunta y se sigue en la siguiente.
                diario(f"error en una vuelta: {type(e).__name__}: {e}")
            if vigia.esperar(cuanto_esperar(agente, decision)):
                agente.rafaga_hasta = time.time() + RAFAGA
    except KeyboardInterrupt:
        diario("interrumpido por teclado")
    finally:
        agente.cerrar()
        if agente.avisos_de_red is not None:
            agente.avisos_de_red.cerrar()
        if agente.avisos_carpeta is not None:
            agente.avisos_carpeta.cerrar()
        if oyente_del_buzon is not None:
            oyente_del_buzon.cerrar()
        if agente.atajos_motor is not None:
            agente.atajos_motor.cerrar()
        if agente.bandeja is not None:
            agente.bandeja.cerrar()
        info = store.read_json(equipo.lock_json())
        if info.get("pid") == os.getpid() and info.get("host") == HOST:
            equipo.lock_json().unlink(missing_ok=True)
        diario("agente detenido")
    return 0


def _bloquea_sola(u: equipo.Unidad) -> str:
    """Devuelve cuándo bloquea el agente esa raíz por sí solo, para `status`; vacío si nunca."""
    cuando = [texto for clave, texto in (
        ("bloquear_al_bloquear_sesion", "al bloquear la sesión"),
        ("bloquear_al_suspender", "al suspender"),
        ("bloquear_al_cerrar_sesion", "al cerrar sesión o apagar")) if getattr(u, clave)]
    if not cuando:
        return ""
    return "se bloquea sola " + (", ".join(cuando[:-1]) + " y " + cuando[-1]
                                 if len(cuando) > 1 else cuando[0])


def cmd_status(_args: argparse.Namespace) -> int:
    """Imprime qué atiende el agente y cómo."""
    aj = equipo.leer_ajustes()
    vivo = equipo.agente_vivo()
    print(f"Agente:         {'vivo (pid ' + str(vivo.get('pid')) + ')' if vivo else 'parado'}")
    print(f"En el equipo:   {equipo.DIR}")
    nueva = update.pending(SCRIPT_DIR, cache=cache_version())
    print(f"Versión:        {update.installed_version(SCRIPT_DIR) or 'desconocida'}"
          + (f" (hay una nueva, {nueva.tag}: agente.py actualizar)" if nueva else ""))
    print(f"Unidad nueva:   se pregunta y se espera {aj.espera_unidad_nueva:g} s")
    pausa = " · en pausa desde su ventana («Reanudar» para volver)"
    for u in aj.raices.values():
        print(f"Raíz del equipo: {u.nombre or '(sin nombre)'} en {u.ruta} ({u.modo}: "
              f"{equipo.TEXTO_MODO[u.modo]})" + (pausa if u.pausada else ""))
        if u.cifrada:
            print(f"  cifrada: {u.contenedor}; al iniciar sesión "
                  + ("se pide la contraseña" if aj.pedir_al_iniciar
                     else "no se pide nada (agente.py desbloquear)"))
        if _bloquea_sola(u):
            print(f"  {_bloquea_sola(u)}")
    unidades = [u for u in aj.unidades.values() if not u.es_raiz]
    print("Unidades en la lista:" if unidades else "Unidades en la lista: ninguna")
    for u in unidades:
        print(f"  {u.nombre or '(sin nombre)':<20} {u.id[:12]}…  {u.modo}: "
              f"{equipo.TEXTO_MODO[u.modo]}" + (pausa if u.pausada else "")
              + ("" if u.pedir_al_conectar is None else
                 " · al conectarla " + ("se pide" if u.pedir_al_conectar else "no se pide")
                 + " la contraseña")
              + (f" · {_bloquea_sola(u)}" if _bloquea_sola(u) else ""))
    estado = equipo.leer_estado() if vivo else {}
    if estado.get("retenido"):
        print(f"No se lanza nada: {estado['retenido']}")
    if estado.get("pausado"):
        print("En pausa (agente.py sigue para volver).")
    if estado.get("pasada"):
        p = estado["pasada"]
        print(f"Ahora: {p.get('unidad')} · {p.get('pareja') or 'comprobando la conexión'}")
    for u in estado.get("unidades") or []:
        print(f"{'Raíz' if u.get('del_equipo') else 'Conectada'}: {u.get('nombre')} "
              f"en {u.get('raiz')}"
              + (f" — {u['motivo']}" if u.get("motivo") else " — atendida"))
        gastado = consumo.del_dia(str(u.get("id") or ""))
        if gastado.pasadas:
            print(f"  Hoy: {consumo.texto(gastado)}")
        if u.get("cifrado") and isinstance(u.get("pedir_al_conectar"), bool):
            como = "VeraCrypt" if u["cifrado"] == equipo.CIFRADO_VERACRYPT else "BitLocker"
            print(f"  Cifrada con {como}: al conectarla "
                  + ("se pide" if u["pedir_al_conectar"] else "no se pide") + " la contraseña")
        if u.get("estiradas"):
            print("  Sin nada que hacer desde hace rato, se pasan menos: "
                  + ", ".join(f"{n} cada {m:g} min" for n, m in sorted(u["estiradas"].items())))
        if u.get("actualizable"):
            print(f"  Lleva la {u.get('version') or 'versión desconocida'}; para ponerla a "
                  f"la {estado.get('version')}: agente.py actualizar {u.get('id')}")
        if u.get("vigila"):
            print(f"  Sincroniza al cambiar sus ficheros: {', '.join(u['vigila'])}")
        if u.get("vigila_recorre"):
            print("  Recorre su carpeta (sin avisos del sistema): "
                  + "; ".join(f"{n} ({m})" for n, m in sorted(u["vigila_recorre"].items())))
        if u.get("vigila_abandonada"):
            print(f"  No vigila sus cambios (demasiado grande o fuera de la raíz; "
                  f"sigue por su intervalo): {', '.join(u['vigila_abandonada'])}")
        if u.get("llavero"):
            print("  Lleva llavero" + ("; su KeePassXC está abierto: se trae cada "
                                       f"{llavero.REMOTO_ABIERTO / 60:.0f} min"
                                       if u.get("llavero_abierto") else ""))
    for ruta in estado.get("ausentes") or []:
        print(f"Falta la raíz del equipo: no está en {ruta}")
    for nombre in estado.get("bloqueadas") or []:
        print(f"Bloqueada: {nombre} (agente.py desbloquear)")
    for b in estado.get("bitlocker") or []:
        print(f"Bloqueada con BitLocker: {b.get('nombre')} en {b.get('raiz')} "
              f"(agente.py desbloquear {b.get('id')})")
    for nombre in estado.get("desbloqueando") or []:
        print(f"Desbloqueando: {nombre}; la contraseña la pide VeraCrypt")
    for nombre in estado.get("bloqueando") or []:
        print(f"Bloqueando: {nombre}")
    for ruta in estado.get("fantasmas") or []:
        print(f"Volumen fantasma en {ruta}: bloquéala y vuelve a desbloquearla")
    for linea in estado.get("sin_conexion") or []:
        print(f"Sin conexión: {linea}")
    if vivo:
        oye = estado.get("cambios_de_red")
        if oye:
            print(f"Cambios de red: los oye ({oye}); un remoto sin conexión se prueba "
                  f"cuando vuelve la red, y si no, cada "
                  f"{pl.sondeo(aj.politica, True) / 60:g} min")
        else:
            print(f"Cambios de red: no los oye; un remoto sin conexión se prueba cada "
                  f"{pl.sondeo(aj.politica, False) / 60:g} min")
    errores = ((estado.get("atajos") or {}).get("acciones") or {}) if vivo else {}
    if aj.atajos or errores:
        print("Atajos de teclado (sobre la última unidad usada):")
        for accion in atajos.ACCIONES:
            combo = aj.atajos.get(accion, "")
            error = (errores.get(accion) or {}).get("error", "")
            if combo or error:
                print(f"  {atajos.NOMBRES[accion]:<20} "
                      f"{atajos.texto(combo, IS_WIN) or 'sin atajo'}"
                      + (f" · no se ha podido poner: {error}" if error else ""))
    motivo = (estado.get("atajos") or {}).get("motivo", "") if vivo else ""
    if motivo:
        print(f"Atajos de teclado: no se pueden poner aquí ({motivo})")
    return 0


def _pedir(peticion: dict) -> int:
    """Deja una petición en el buzón del agente y dice cuándo se atenderá.

    Returns:
        0 si se dejó; 1 si no se pudo.
    """
    if not equipo.pedir(peticion):
        print(f"No he podido dejar la petición en {equipo.buzon()}.", file=sys.stderr)
        return 1
    if equipo.agente_vivo() is None:
        print("Petición apuntada, pero el agente no está en marcha: la atenderá al "
              "arrancar.")
    else:
        print("Petición apuntada; el agente la atiende en unos segundos.")
    return 0


def cmd_parar(_args: argparse.Namespace) -> int:
    """Pide parar al agente y espera un rato a que se vaya."""
    vivo = equipo.agente_vivo()
    if vivo is None:
        print("El agente no está en marcha.")
        return 0
    equipo.pedir({"pide": equipo.PIDE_PARAR})
    limite = time.monotonic() + PARAR_ESPERA
    while time.monotonic() < limite and equipo.agente_vivo() is not None:
        time.sleep(0.3)
    print("Agente detenido." if equipo.agente_vivo() is None else
          "El agente sigue terminando una pasada; parará al acabarla.")
    return 0


def raiz_para_abrir(uid: str | None) -> tuple[Path | None, str]:
    """Devuelve qué raíz abre `agente.py abrir`, y por qué no hay ninguna.

    Es la de ese id (del equipo, o una unidad conectada según el estado del
    agente) o la única raíz del equipo.

    Returns:
        `(raíz, motivo)`; el motivo va vacío cuando hay raíz.
    """
    aj = equipo.leer_ajustes()
    if uid:
        unidad = aj.unidades.get(uid)
        if unidad is not None and unidad.es_raiz:
            return Path(unidad.ruta), ""
        for u in equipo.leer_estado().get("unidades") or []:
            if u.get("id") == uid and u.get("raiz"):
                return Path(u["raiz"]), ""
        return None, f"No conozco ninguna raíz conectada con el id {uid}."
    raices = list(aj.raices.values())
    if not raices:
        return None, ("Este equipo no tiene raíz propia: las unidades se abren desde "
                      "ellas.")
    if len(raices) > 1:
        return None, ("Hay más de una raíz en este equipo; di cuál: "
                      + ", ".join(f"{u.id} ({u.ruta})" for u in raices))
    return Path(raices[0].ruta), ""


def arrancar_agente() -> bool:
    """Arranca el agente desde `abrir` cuando no está en marcha.

    Se cerró con «Cerrar el agente» o la sesión no lo arrancó. Va suelto y
    fuera de toda raíz.
    """
    try:
        lanzar([python(), str(SCRIPT_DIR / "agente.py"), "run"],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
               **_opciones_hijo(equipo.DIR, separado=True))
    except OSError as e:
        print(f"No he podido arrancar el agente: {e}", file=sys.stderr)
        return False
    return True


def cmd_abrir(args: argparse.Namespace) -> int:
    """Hace el acceso «prdrive» del menú del sistema, que sin bandeja hace sus veces.

    Es la fase 6:
    - Con el agente parado, lo arranca.
    - Con una raíz en este equipo, abre su ventana de runsync, con el Python
      del agente y el directorio de trabajo fuera de ella (la raíz del equipo
      no lleva Python propio); bloqueada, pide antes desbloquearla.
    - Sin raíz («solo agente»), dice con un aviso cómo va el agente.
    """
    _enganchar_penwatch()
    vivo = equipo.agente_vivo() is not None
    arrancado = False if vivo else arrancar_agente()
    raiz, porque = raiz_para_abrir(args.id)
    if raiz is None:
        if args.id or equipo.leer_ajustes().raices:
            print(porque, file=sys.stderr)
            return 1
        if not vivo:
            if not arrancado:
                return 1
            print("Agente arrancado.")
            avisar(f"{APP_NAME}: agente arrancado",
                   "Atiende las unidades de su lista en cuanto se enchufen.")
            return 0
        titulo, texto = bandeja.aviso_de_estado(equipo.leer_estado())
        print(f"{titulo}\n{texto}")
        avisar(titulo, texto)
        return 0
    if not presente(raiz):
        unidad = equipo.leer_ajustes().unidades.get(args.id or "") \
            or next((u for u in equipo.leer_ajustes().raices.values()
                     if Path(u.ruta) == raiz), None)
        if unidad is None or not unidad.cifrada:
            print(f"No encuentro {APP_NAME} en {raiz}.", file=sys.stderr)
            return 1
        # Cerrada: se le pide al agente que la desbloquee (la contraseña la
        # pide VeraCrypt) y se abre la ventana en cuanto aparezca. Es lo que
        # hace el acceso «prdrive» del menú con la raíz bloqueada.
        if not (vivo or arrancado):
            print(f"{raiz} está bloqueada y el agente no está en marcha: no hay quien "
                  f"la desbloquee.", file=sys.stderr)
            return 1
        equipo.pedir({"pide": equipo.PIDE_DESBLOQUEAR, "id": unidad.id})
        print(f"{raiz} está bloqueada: VeraCrypt pedirá la contraseña.")
        limite = time.monotonic() + ESPERA_ABRIR
        while not presente(raiz):
            if time.monotonic() >= limite:
                print("No se ha desbloqueado a tiempo; vuelve a intentarlo.",
                      file=sys.stderr)
                return 1
            time.sleep(1.0)
    # El servicio no estorba (lo pausa la propia ventana al abrirse); otra
    # ventana sí, y runsync ya se negaría: se dice aquí, sin lanzar nada.
    ventana = _registro_vivo(raiz, penwatch.UI_LOCK_REL)
    if ventana is not None:
        print(f"La ventana de {raiz} ya está abierta (pid {ventana.get('pid')}).")
        return 0
    try:
        lanzar([python(ventana=True), str(app(raiz) / "runsync.py")],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
               **_opciones_hijo(equipo.DIR, separado=True))
    except OSError as e:
        print(f"No he podido abrir la ventana: {e}", file=sys.stderr)
        return 1
    return 0


VERDAD = {"si": True, "sí": True, "s": True, "true": True, "1": True, "yes": True,
          "no": False, "n": False, "false": False, "0": False}
"""Cómo se escribe un sí o un no en la línea de órdenes."""


def valor_ajuste(clave: str, texto: str) -> Any:
    """Devuelve el valor de un ajuste escrito en la línea de órdenes, con su tipo.

    Un texto donde va un sí o un no volvería al valor de fábrica al leerlo, sin
    decir nada: por eso se rechaza aquí.

    Raises:
        ValueError: Si no es un sí o un no, o un número.
    """
    if clave in ("pedir_al_iniciar", "estirar_intervalo", "avisos_veracrypt"):
        valor = VERDAD.get(texto.strip().lower())
        if valor is None:
            raise ValueError(f"{clave} es sí o no, no {texto!r}")
        return valor
    return float(texto)


def cmd_ajuste(args: argparse.Namespace) -> int:
    """Pide cambiar un ajuste del agente."""
    try:
        valor = valor_ajuste(args.clave, args.valor)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    return _pedir({"pide": equipo.PIDE_AJUSTE, "clave": args.clave, "valor": valor})


def cmd_actualizar(args: argparse.Namespace) -> int:
    """Hace el «Actualizar» de la bandeja (o a mano).

    Baja el código de la última release, lo comprueba (`update.download()`) y
    ejecuta SU instalador con `--update-agente`, que pone el agente nuevo al
    lado, para a este, vuelve a registrarlo, pone al día las raíces abiertas y
    arranca el nuevo. Lo que dice va al diario del agente. Nunca se descarga
    dentro de ninguna raíz.

    Con un id es el «Actualizar a la vX» de esa raíz: se le pide al agente,
    que es quien sabe si se puede y cuándo.
    """
    if getattr(args, "id", None):
        return _pedir({"pide": equipo.PIDE_ACTUALIZAR_UNIDAD, "id": args.id})
    _enganchar_penwatch()

    def decir(msg: str) -> None:
        """Dice un mensaje por pantalla y en el diario."""
        print(msg)
        diario(f"actualizar: {msg}")

    rel, motivo = update.check(force=True, cache=cache_version())
    actual = update.installed_version(SCRIPT_DIR)
    if rel is None:
        decir(motivo or "no sé qué versión es la última")
        return 1
    if not update.is_newer(rel.version, actual):
        decir(f"ya está en la última versión ({actual or rel.version})")
        return 0
    trabajo = Path(tempfile.mkdtemp(prefix=f"{APP_NAME}-agente-"))
    try:
        try:
            update.download(rel.tag, trabajo / "codigo", progreso=decir)
        except update.UpdateError as e:
            decir(str(e))
            avisar(f"{APP_NAME}: no he podido actualizar", str(e).splitlines()[0], True)
            return 1
        kwargs = _opciones_hijo(equipo.DIR)
        proc = ejecutar(update.agent_command(trabajo / "codigo", sys.executable),
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", **kwargs)
        for linea in ((proc.stdout or "") + (proc.stderr or "")).splitlines():
            if linea.strip():
                decir(linea.rstrip())
        if proc.returncode != 0:
            avisar(f"{APP_NAME}: no he podido actualizar",
                   f"Lo que ha pasado está en {equipo.diario_log()}.", True)
            return proc.returncode
        avisar(f"{APP_NAME} actualizado a la {rel.tag}",
               "El agente se ha reiniciado con la versión nueva.")
        return 0
    finally:
        shutil.rmtree(trabajo, ignore_errors=True)


def cmd_actualizar_raiz(args: argparse.Namespace) -> int:
    """Pone en una raíz el código de la versión de este agente.

    Es el hijo suelto que lanza «Actualizar a la vX» de una raíz
    (`Agente._lanzar_actualizacion()`). Baja el código del tag de ESTE agente
    (`update.source_tag()`), no el de la última release: es la versión que el
    agente sabe atender y la de su rclone. Lo comprueba (`update.download()`),
    a un temporal y nunca dentro de una raíz, y ejecuta SU instalador con
    `--update RAIZ` y el Python del agente, como hace la ventana de la raíz:
    se cambia el programa y se conservan su configuración, sus claves, su
    estado y sus componentes. Lo que dice va al diario del agente; quien avisa
    de cómo ha ido es el agente, que mira su código de salida.

    Returns:
        0 si ha ido bien, `SIN_TOCAR` si no se ha llegado a tocar la raíz, y
        si no, con lo que salga el instalador.
    """
    _enganchar_penwatch()
    raiz = Path(args.raiz)

    def decir(msg: str) -> None:
        """Dice un mensaje por pantalla y en el diario."""
        print(msg)
        diario(f"actualizar {raiz}: {msg}")

    tag = update.source_tag(SCRIPT_DIR)
    if not tag:
        decir("no sé de qué versión es este agente: no hay nada que ponerle")
        return SIN_TOCAR
    trabajo = Path(tempfile.mkdtemp(prefix=f"{APP_NAME}-raiz-"))
    try:
        try:
            update.download(tag, trabajo / "codigo", progreso=decir)
        except update.UpdateError as e:
            decir(str(e))
            return SIN_TOCAR
        proc = ejecutar(update.apply_command(trabajo / "codigo", raiz, sys.executable),
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", **_opciones_hijo(equipo.DIR))
        for linea in ((proc.stdout or "") + (proc.stderr or "")).splitlines():
            if linea.strip():
                decir(linea.rstrip())
        return proc.returncode
    finally:
        shutil.rmtree(trabajo, ignore_errors=True)


def cmd_pregunta(args: argparse.Namespace) -> int:
    """Abre la ventanita que pregunta por una unidad nueva (proceso hijo del agente)."""
    from ui import tk_agente
    return tk_agente.main(args.nombre, args.segundos, args.cambiada)


def cmd_desinstalar(args: argparse.Namespace) -> int:
    """Quita el agente de este equipo sin dejar rastro: el «Desinstalar» de Windows.

    Lo lanza «Aplicaciones instaladas» con el Python sin consola del agente
    (`presencia.registrar_ficha()`), así que lo normal es la ventana
    (`ui/tk_desinstalar.py`), que enseña qué hará y espera un sí. Sin Tk o sin
    pantalla, lo mismo por la consola. Con `--si` no pregunta: es la
    desinstalación silenciosa. Este proceso corre desde la carpeta que borra,
    así que lo último es `presencia.rematar()`, que la termina de borrar cuando
    sale.

    Returns:
        0 si se ha desinstalado; 1 si se ha cancelado o no se ha podido; 2 si
        no hay ni ventana ni consola a la que preguntar (no se ha tocado nada).
    """
    _enganchar_penwatch()
    try:
        os.chdir(tempfile.gettempdir())     # nunca dentro de la carpeta que se borra
    except OSError:
        pass
    plan = presencia.plan_desinstalar()
    try:
        if not args.si:
            from ui import tk_desinstalar
            rc = tk_desinstalar.main(plan)
            if rc != tk_desinstalar.SIN_VENTANA:
                return rc
        return desinstalar_por_consola(plan, preguntar=not args.si)
    finally:
        presencia.rematar()


def desinstalar_por_consola(plan: presencia.Desinstalacion, preguntar: bool) -> int:
    """Hace `cmd_desinstalar()` sin ventana: lo dice por la consola y pregunta en ella.

    Sin consola (el Python sin ella, con `--si`) desinstala sin decir nada.

    Args:
        plan: El de `presencia.plan_desinstalar()`.
        preguntar: Si hay que esperar un sí antes de tocar nada.

    Returns:
        Como `cmd_desinstalar()`.
    """
    def decir(texto: str = "") -> None:
        """Escribe una línea, si hay dónde."""
        if sys.stdout is not None:
            print(texto)

    decir(f"Desinstalar {APP_NAME} de este equipo:")
    for linea in plan.consequences:
        decir(f"  - {linea}")
    for linea in plan.warnings:
        decir(f"  ! {linea}")
    if preguntar:
        if sys.stdin is None or not sys.stdin.isatty():
            decir("No hay a quién preguntar: con «desinstalar --si» se hace sin preguntar.")
            return 2
        if input("¿Desinstalar? [s/N] ").strip().lower() not in ("s", "si", "sí"):
            decir("No se ha tocado nada.")
            return 1
    try:
        hecho = plan.execute(presencia.decirlo(decir))
    except presencia.DesinstalacionError as e:
        decir(str(e))
        return 1
    for linea in hecho:
        decir(f"  {linea}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Atiende la línea de comandos del agente."""
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    ap = argparse.ArgumentParser(prog="agente.py",
                                 description=f"{APP_NAME} residente: atiende las "
                                             f"unidades que se enchufan en este equipo.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="El bucle del agente.").set_defaults(func=cmd_run)
    sub.add_parser("status", help="Qué atiende y cómo.").set_defaults(func=cmd_status)
    p = sub.add_parser("atender", help="Atender una unidad conectada.")
    p.add_argument("id")
    p.set_defaults(func=lambda a: _pedir({"pide": equipo.PIDE_ATENDER, "id": a.id}))
    p = sub.add_parser("modo", help="Qué hacer con una unidad al enchufarla.")
    p.add_argument("id")
    p.add_argument("modo", choices=equipo.MODOS)
    p.set_defaults(func=lambda a: _pedir({"pide": equipo.PIDE_MODO, "id": a.id,
                                          "modo": a.modo}))
    p = sub.add_parser("pasada", help="Sincronizar ahora, sin moderación.")
    p.add_argument("id")
    p.add_argument("parejas", nargs="*")
    p.set_defaults(func=lambda a: _pedir({"pide": equipo.PIDE_PASADA, "id": a.id,
                                          "parejas": a.parejas}))
    sub.add_parser("pausa", help="Dejar de lanzar pasadas.").set_defaults(
        func=lambda a: _pedir({"pide": equipo.PIDE_PAUSA}))
    sub.add_parser("sigue", help="Volver a lanzarlas.").set_defaults(
        func=lambda a: _pedir({"pide": equipo.PIDE_SIGUE}))
    sub.add_parser("parar", help="Que el agente termine.").set_defaults(func=cmd_parar)
    p = sub.add_parser("abrir", help="La ventana de la raíz de este equipo.")
    p.add_argument("id", nargs="?")
    p.set_defaults(func=cmd_abrir)
    p = sub.add_parser("desbloquear", help="Abrir el contenedor de la raíz cifrada; con el "
                       "id de una unidad bloqueada con BitLocker, la ventana de Windows que "
                       "la desbloquea.")
    p.add_argument("id", nargs="?", default="")
    p.set_defaults(func=lambda a: _pedir({"pide": equipo.PIDE_DESBLOQUEAR, "id": a.id}))
    p = sub.add_parser("bloquear", help="Cerrarlo.")
    p.add_argument("id", nargs="?", default="")
    p.set_defaults(func=lambda a: _pedir({"pide": equipo.PIDE_BLOQUEAR, "id": a.id}))
    p = sub.add_parser("expulsar", help="Soltar una unidad extraíble para quitarla.")
    p.add_argument("id")
    p.set_defaults(func=lambda a: _pedir({"pide": equipo.PIDE_EXPULSAR, "id": a.id}))
    p = sub.add_parser("actualizar", help="Bajar la versión nueva y ponerla; con un id, "
                                          "poner esa raíz a la versión del agente.")
    p.add_argument("id", nargs="?", default="")
    p.set_defaults(func=cmd_actualizar)
    p = sub.add_parser("actualizar-raiz", help=argparse.SUPPRESS)
    p.add_argument("raiz")
    p.set_defaults(func=cmd_actualizar_raiz)
    sub.add_parser("atajos", help="Abrir la ventana que graba los atajos de teclado.").set_defaults(
        func=lambda a: _pedir({"pide": equipo.PIDE_GRABAR_ATAJOS}))
    p = sub.add_parser("atajo", help="Hacer lo de un atajo de teclado, como si se pulsara.")
    p.add_argument("accion", choices=atajos.ACCIONES)
    p.set_defaults(func=lambda a: _pedir({"pide": equipo.PIDE_ATAJO, "accion": a.accion}))
    p = sub.add_parser("ajuste", help="Cambiar un ajuste del agente.")
    p.add_argument("clave", choices=equipo.AJUSTES_PEDIBLES)
    p.add_argument("valor")
    p.set_defaults(func=cmd_ajuste)
    p = sub.add_parser("desinstalar", help="Quitar el agente de este equipo sin dejar "
                                           "rastro; las unidades y la raíz no se tocan.")
    p.add_argument("--si", action="store_true", help="Sin preguntar antes.")
    p.set_defaults(func=cmd_desinstalar)
    p = sub.add_parser("pregunta", help=argparse.SUPPRESS)
    p.add_argument("--nombre", required=True)
    p.add_argument("--segundos", type=int, default=int(equipo.ESPERA_UNIDAD_NUEVA))
    p.add_argument("--cambiada", action="store_true")
    p.set_defaults(func=cmd_pregunta)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
