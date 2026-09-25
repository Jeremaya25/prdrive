#!/usr/bin/env python3
"""
install/raiz_equipo.py — La raíz de ESTE equipo: una carpeta del ordenador que
es un prdrive más.

Fase 2 del diseño (`docs/superpowers/specs/2026-09-25-instalacion-en-el-equipo-
design.md`, secciones 1 y 7): la raíz del equipo SIN cifrar. El motor no sabe que
está en un USB —`model.DEVICE_ROOT` es el padre de `.prdrive/` y nada más—, así
que una carpeta con `.prdrive/` dentro es un dispositivo más para `sync.py`, la
ventana y la flota. Lo que cambia es poco y está aquí:

  * **Dónde.** Una carpeta propia (`~/PRDRIVE`, por defecto: el modelo de
    Dropbox, nada de fuera se toca) o la carpeta personal (`~`: se sincroniza
    `~/Documentos/Obsidian` sin moverlo, a cambio de que el límite sea todo el
    usuario). Se elige al instalar y no se cambia después: mover la raíz deja
    cada línea base apuntando a una carpeta que ya no está.
  * **Qué lleva.** `.prdrive/` con el código, rclone para ESTE equipo, la
    conexión y la clave, y el fichero de control con `tipo=equipo`. Sin Python
    propio ni lanzadores: la sincroniza y la abre el agente, con el suyo.
  * **Qué no vale.** La pareja de la raíz entera, ni nada que salga de ella
    (`model.problema_local_equipo`, que también para al parsear).
  * **Qué se avisa.** La clave queda en claro en el disco del equipo (con el
    estado de BitLocker del disco, como información), y una carpeta que ya
    sincroniza otro programa —OneDrive, Dropbox— se pisaría los borrados con él.

Sin Tk, como todo `install/`: lo dibuja `ui/tk_equipo.py`.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from common import APP_NAME, equipo, fleet, model

from . import InstallError, IS_WIN, crypto, deploy, device, platforms

# Qué raíz se pone. «Ninguna» es la instalación «solo agente» de la fase 1.
PROPIA, PERSONAL, NINGUNA = "propia", "personal", "ninguna"
FORMAS = (PROPIA, PERSONAL, NINGUNA)


def carpeta_propia() -> Path:
    return Path.home() / APP_NAME.upper()


def carpeta_personal() -> Path:
    return Path.home()


def por_defecto(forma: str) -> Path | None:
    return {PROPIA: carpeta_propia(), PERSONAL: carpeta_personal()}.get(forma)


# ---------------------------------------------------------------------------
# ¿Vale esta carpeta?
# ---------------------------------------------------------------------------

NUEVA = "nueva"             # no existe o está vacía
YA_EQUIPO = "ya_equipo"     # ya es la raíz de un equipo: se reinstala con su id
CON_COSAS = "con_cosas"     # tiene cosas; no se borra nada
NO_VALE = "no_vale"


@dataclass(frozen=True)
class Examen:
    estado: str
    texto: str
    aviso: bool = False             # se dice en ámbar, pero se puede seguir

    @property
    def vale(self) -> bool:
        return self.estado != NO_VALE


def _dentro(ruta: Path | str, carpeta: Path | str) -> bool:
    """¿`ruta` es `carpeta` o está dentro? Sin resolver enlaces ni tocar el
    disco, y sin distinguir mayúsculas donde el sistema no las distingue."""
    a = os.path.normcase(os.path.abspath(str(ruta)))
    b = os.path.normcase(os.path.abspath(str(carpeta)))
    return a == b or a.startswith(b.rstrip("\\/") + os.sep)


def examinar(ruta: Path | str, forma: str = PROPIA) -> Examen:
    """Qué hay en esa carpeta y si puede ser la raíz de este equipo."""
    texto = str(ruta).strip()
    if not texto:
        return Examen(NO_VALE, "Escribe la carpeta.")
    raiz = Path(texto).expanduser()
    if not raiz.is_absolute():
        return Examen(NO_VALE, "Tiene que ser una ruta completa, no relativa.")
    personal = forma == PERSONAL or _dentro(raiz, carpeta_personal()) \
        and _dentro(carpeta_personal(), raiz)
    if _dentro(raiz, equipo.DIR) or (_dentro(equipo.DIR, raiz) and not personal):
        # Lo segundo es el caso de elegir `~/.local` o `%LOCALAPPDATA%`: la raíz
        # contendría al agente, que no vive dentro de lo que atiende. La carpeta
        # personal lo contiene siempre, en una carpeta oculta que ninguna pareja
        # puede nombrar entera (`..` y `.` no valen) salvo a propósito.
        return Examen(NO_VALE, f"Esa carpeta se cruza con la del agente ({equipo.DIR}). "
                               f"Elige otra.")
    try:
        if raiz.exists() and not raiz.is_dir():
            return Examen(NO_VALE, f"{raiz} existe y no es una carpeta.")
        if (raiz / device.CONTROL_FILE).is_file():
            uid = device.control_id(raiz) or ""
            if device.control_tipo(raiz) == model.TIPO_EQUIPO:
                return Examen(YA_EQUIPO, (
                    f"Ya es la raíz de este equipo (id {uid[:8]}…). Se vuelve a "
                    f"instalar el programa con el mismo id, así que el agente la sigue "
                    f"reconociendo, y las parejas se vuelven a elegir."))
            return Examen(NO_VALE, (
                f"Ahí ya hay una unidad prdrive (id {uid[:8]}…). La raíz del equipo "
                f"es otra cosa: elige otra carpeta, o prepara esa unidad desde «En "
                f"una unidad»."))
        contenido = ([p for p in raiz.iterdir() if not device.es_ruido(p.name)]
                     if raiz.is_dir() else [])
    except OSError as e:
        return Examen(NO_VALE, f"No puedo leer {raiz}: {e}")
    cliente = otro_cliente(raiz)
    if cliente:
        return Examen(CON_COSAS if contenido else NUEVA, (
            f"{raiz} está dentro de una carpeta que ya sincroniza {cliente}. Dos "
            f"programas sincronizando lo mismo se pisan los borrados: mejor una "
            f"carpeta fuera."), aviso=True)
    if personal:
        return Examen(CON_COSAS, (
            "Las parejas pueden ser cualquier carpeta de tu usuario, sin moverla "
            "(por ejemplo Documentos/Obsidian). A cambio, el límite es todo el "
            "usuario: el paso «Parejas» enseña dónde cae cada una antes de "
            "escribir nada."))
    if contenido:
        return Examen(CON_COSAS, (
            f"La carpeta ya tiene {len(contenido)} elemento(s). No se borra nada: "
            f"el programa va en .prdrive/ y cada pareja en su carpeta."), aviso=True)
    return Examen(NUEVA, f"Se creará {raiz} con el programa dentro, en .prdrive/.")


# ---------------------------------------------------------------------------
# Otros clientes de sincronización
# ---------------------------------------------------------------------------

# Las variables que el cliente de OneDrive deja en el entorno del usuario, con la
# carpeta de cada cuenta. Se saben sin adivinar, que es lo que pide el diseño.
VARIABLES_ONEDRIVE = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")


def _info_dropbox() -> list[Path]:
    """Dónde deja Dropbox su `info.json`, con la ruta de cada cuenta. Según su
    ayuda («Find the Dropbox folder path programmatically»): `%APPDATA%` o
    `%LOCALAPPDATA%` en Windows, `~/.dropbox/` en los demás."""
    if IS_WIN:
        return [Path(os.environ[v]) / "Dropbox" / "info.json"
                for v in ("APPDATA", "LOCALAPPDATA") if os.environ.get(v)]
    return [Path.home() / ".dropbox" / "info.json"]


def carpetas_sincronizadas() -> list[tuple[str, Path]]:
    """(programa, carpeta) de lo que ya sincroniza otro cliente en este equipo.

    Punto de indirección: los tests ponen sus propias carpetas."""
    salida: list[tuple[str, Path]] = []
    for var in VARIABLES_ONEDRIVE:
        valor = os.environ.get(var)
        if valor:
            salida.append(("OneDrive", Path(valor)))
    for info in _info_dropbox():
        try:
            datos = json.loads(info.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(datos, dict):
            continue
        for cuenta in ("personal", "business"):
            ruta = datos.get(cuenta, {}).get("path") \
                if isinstance(datos.get(cuenta), dict) else None
            if isinstance(ruta, str) and ruta:
                salida.append(("Dropbox", Path(ruta)))
    vistas: set[str] = set()
    unicas = []
    for nombre, ruta in salida:
        clave = os.path.normcase(os.path.abspath(str(ruta)))
        if clave not in vistas:
            vistas.add(clave)
            unicas.append((nombre, ruta))
    return unicas


def otro_cliente(ruta: Path | str) -> str | None:
    """El programa que ya sincroniza esa carpeta, la contenga o esté dentro, o
    None. En los dos sentidos: una pareja `Documentos` con OneDrive en
    `Documentos/OneDrive` también pisaría lo suyo."""
    for nombre, carpeta in carpetas_sincronizadas():
        if _dentro(ruta, carpeta) or _dentro(carpeta, ruta):
            return f"{nombre} ({carpeta})"
    return None


# ---------------------------------------------------------------------------
# El `local` de cada pareja, visto desde esta raíz
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Local:
    local: str                      # normalizado, como lo escribirá el config
    ruta: Path | None               # dónde cae de verdad
    error: str | None = None        # no vale: no se puede guardar así
    avisos: tuple[str, ...] = ()


def revisar_local(raiz: Path | str, local: str) -> Local:
    """Dónde cae el `local` de una pareja en esta raíz, y qué hay que decir.

    Lo que no vale lo decide `model.problema_local_equipo()`, el mismo que para
    al parsear. Lo que se avisa: otro programa sincronizando lo mismo, y una
    carpeta que ya existe con cosas (el `--resync` las junta con lo del remoto,
    que es lo que se quiere si ya estaban sincronizadas por otro camino)."""
    normal = str(local).strip().replace("\\", "/").strip("/")
    problema = model.problema_local_equipo(normal or ".")
    if problema:
        return Local(normal, None, problema)
    ruta = Path(raiz) / normal
    avisos = []
    cliente = otro_cliente(ruta)
    if cliente:
        avisos.append(f"ya la sincroniza {cliente}: se pisarían los borrados")
    try:
        if ruta.is_dir() and any(ruta.iterdir()):
            avisos.append("ya existe y tiene cosas: la inicialización las junta con "
                          "lo del remoto")
    except OSError:
        pass
    return Local(normal, ruta, None, tuple(avisos))


# ---------------------------------------------------------------------------
# Lo que se avisa antes de instalar
# ---------------------------------------------------------------------------

AVISO_CLAVE = ("Sin cifrar, la clave del remoto queda en claro en el disco de este "
               "equipo, en .prdrive/keys/: la lee cualquier programa de tu sesión, "
               "y quien se lleve el disco. Es lo mismo que en una unidad sin cifrar.")


def cifrado_del_disco(raiz: Path | str) -> str:
    """Una frase sobre el cifrado del disco donde irá la raíz, o '' si no hay
    nada que decir. Solo en Windows: BitLocker leído como en `install/crypto.py`
    (solo `On` cuenta como protegido). Es información, no una exigencia."""
    if not IS_WIN:
        return ""
    letra = Path(os.path.abspath(str(raiz))).drive[:1]
    if not letra:
        return ""
    estado = crypto.bitlocker_status(letra)
    if not estado.known:
        return f"BitLocker del disco {letra}: sin comprobar ({estado.detail})."
    if estado.protected:
        return (f"El disco {letra}: tiene BitLocker activado: con el equipo apagado, "
                f"la clave está protegida.")
    return f"El disco {letra}: no tiene BitLocker activado ({estado.resumen})."


# ---------------------------------------------------------------------------
# Instalar
# ---------------------------------------------------------------------------

def plan_rclone() -> platforms.Plan:
    """Solo rclone, y solo para este equipo: la raíz no sale de aquí, y el
    Python es el del agente."""
    plat = platforms.host()
    if plat is None:
        raise InstallError("La raíz del equipo es para Windows y Linux, y este equipo "
                           "no es ninguno de los dos.")
    return platforms.Plan(rclone=[plat], runtime=[], borrar=[], completa=False)


def instalar(raiz: Path | str, perfil, progreso=None) -> tuple[list[Path], str]:
    """Deja el programa en la raíz del equipo. Devuelve (lo escrito, el id).

    Lo mismo que el paso «Instalación» de una unidad, menos lo que es de viajar:
    rclone solo de este equipo, sin Python ni lanzadores ni guía. Lo de fuera
    (rclone) se consigue ANTES de escribir nada, como en las unidades (#49). Una
    raíz que ya era del equipo conserva su id: el agente la tiene en su lista por
    él."""
    raiz = Path(raiz).expanduser()
    examen = examinar(raiz)
    if not examen.vale:
        raise InstallError(examen.texto)
    plan = plan_rclone()
    conseguido = deploy.conseguir_plataformas(plan, progreso)
    try:
        raiz.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise InstallError(f"No he podido crear {raiz}: {e}") from e
    escrito = deploy.deploy_code(raiz)
    nuevos, _ = deploy.apply_platforms(raiz, plan, conseguido=conseguido)
    escrito += nuevos
    escrito += deploy.write_device_remote(raiz, perfil)
    try:
        from ui import icons                    # sin Tk: rasteriza él solo
        icons.write_ico(deploy.app_dir(raiz) / "runsync.ico")
    except Exception:                           # noqa: BLE001
        pass                                    # la ventana tiene el suyo
    ident = device.ensure_control_file(raiz, renew=examen.estado != YA_EQUIPO,
                                       tipo=model.TIPO_EQUIPO)
    return escrito, ident


def nombre(raiz: Path | str) -> str:
    """Cómo se llama en la flota: el que ya tenga, o el del equipo."""
    return fleet.nombre(deploy.app_dir(raiz) / "state")


def python_consola(python: Path | str) -> list[str]:
    """El Python del agente con consola, para lo que se lee en una ventana de
    salida (la inicialización). En Windows el del agente es `pythonw.exe`."""
    ruta = Path(python)
    if IS_WIN and ruta.name.lower() == "pythonw.exe":
        consola = ruta.with_name("python.exe")
        if consola.is_file():
            return [str(consola)]
    return [str(ruta)]


def verificar(raiz: Path | str, esperadas: list[str] | None = None,
              key_name: str | None = None) -> list[device.Check]:
    """Lo que tiene que estar en la raíz para que el agente la sincronice. Es
    `device.verify_device()`, que ya sabe que una raíz del equipo no lleva
    lanzadores ni Python propio."""
    return device.verify_device(Path(raiz), esperadas, key_name)


# ---------------------------------------------------------------------------
# Las unidades de la flota, para el paso «Unidades»
# ---------------------------------------------------------------------------

def de_la_flota(rclone, endpoint_catalogo: str, timeout: float = 45.0
                ) -> list[fleet.Dispositivo]:
    """Las unidades apuntadas en el registro de la flota, sin las raíces de
    otros equipos (no se enchufan). Mejor esfuerzo: sin red, ninguna.

    Una sola llamada: la carpeta `devices/` se copia a un temporal y se lee aquí.
    Un `cat` de la carpeta las concatenaría (#48), y uno por nota serían N
    viajes al remoto con alguien delante de la barra."""
    tmp = Path(tempfile.mkdtemp(prefix="prdrive-flota-"))
    try:
        res = rclone.run("copy", fleet.carpeta_de(endpoint_catalogo), str(tmp),
                         "--include", f"*{fleet.SUFIJO}", "--max-depth", "1",
                         capture=True, timeout=timeout)
        if res.returncode != 0:
            return []
        salida = []
        for nota in sorted(tmp.glob(f"*{fleet.SUFIJO}")):
            try:
                disp = fleet.parse(nota.read_text(encoding="utf-8"), nota.stem)
            except OSError:
                continue
            if disp is not None and not disp.es_equipo:
                salida.append(disp)
        return salida
    except Exception:                                    # noqa: BLE001
        return []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
