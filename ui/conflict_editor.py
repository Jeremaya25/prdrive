#!/usr/bin/env python3
"""Resolver un conflicto de bisync, sin Tkinter.

Mismo guion que `pair_editor`: la ventana (`ui/tk_conflicts.py`) pide un plan,
enseña sus consecuencias en `tk_pairs.confirmar_plan()` y solo si la persona
dice que sí lo ejecuta. Aquí se decide qué fichero se queda con el nombre bueno
y cuáles se borran; allí solo se dibuja.

Resolver es siempre LOCAL. No se habla con el remoto: basta con dejar en este
dispositivo un solo fichero con el nombre de verdad, y la siguiente pasada de
bisync lleva el resultado al otro lado (el fichero que cambia se sube, las
copias que desaparecen se borran allí también). Así la aplicación no escribe en
el remoto por ningún camino que no sea el de siempre.

Qué hace «quedarse con la versión de este dispositivo» depende de dónde esté
esa versión, y por eso no es una regla fija de «borrar la copia»: si perdió
este dispositivo, su versión ES la copia y hay que devolverle el nombre; si
ganó, es el original y lo que sobra es la copia. `common/conflicts.py` ya sabe
cuál es cuál; este módulo solo pregunta.

El llavero tiene una salida más, la primera: «Combinar» (`plan_combinar()`).
Elegir una versión de una base de KeePassXC es perder lo que se guardó en la
otra; combinarlas lo junta. Lo hace `keepassxc-cli merge` en una consola, que
pide la contraseña: prdrive no la ve. La copia combinada va a `.prversions/`,
recuperable, y la siguiente pasada la quita del remoto.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from common import conflicts, keepassxc, model
from common.conflicts import Conflicto, Version

ETIQUETA_LADO = {
    conflicts.DISPOSITIVO: "versión de este dispositivo",
    conflicts.REMOTO: "versión del remoto",
}
"""Cómo se llama para la persona la versión de cada lado."""
ETIQUETA_ORIGINAL = "versión con su nombre"
"""Nombre de la versión con el nombre de verdad cuando no se sabe de qué lado viene."""
ETIQUETA_COPIA = "otra versión"
"""Nombre de una copia de conflicto cuando no se sabe de qué lado viene."""

NOTA_LOCAL = ("Solo se tocan ficheros de este dispositivo. La próxima sincronización "
              "lleva el resultado al remoto y borra allí las copias.")
"""Lo que se dice siempre al resolver: solo se toca este dispositivo."""
PIERDE_LLAVERO = ("Es la base del llavero: lo que se guardó en la versión que se descarta "
                  "se pierde. «Combinar» junta las dos sin perder nada.")
"""El aviso de «quedarse con…» en el llavero."""
ESPERANDO_CONSOLA = ("Combinando en la consola de KeePassXC: escribe allí la contraseña de "
                     "la base. Esta ventana sigue cuando se cierre la consola.")
"""Lo que dice la espera mientras la consola de `keepassxc-cli` está abierta."""


class ResolucionImposible(Exception):
    """El plan no se puede pensar o ejecutar.

    El mensaje es para la persona.
    """


def mover(origen: Path, destino: Path) -> None:
    """Mueve un fichero sobre otro y devuelve cuando está hecho.

    Es `os.replace` y no `rename`: sustituye al destino si existe y lo hace de
    una vez. O la versión elegida queda con su nombre y la anterior se va, o no
    ha cambiado nada; no hay un momento intermedio sin fichero. Es de módulo
    para que un test lo haga fallar.
    """
    os.replace(origen, destino)


def borrar(ruta: Path) -> None:
    """Borra un fichero; es de módulo para que un test lo haga fallar."""
    ruta.unlink()


def etiquetas(conflicto: Conflicto) -> list[tuple[Version, str]]:
    """Devuelve cada versión con su nombre para la persona, en el orden del conflicto.

    Nunca el sufijo: `.conflicto-remoto1` es cosa de rclone. Si dos versiones
    se llaman igual (dos conflictos seguidos que perdió el mismo lado) se
    numeran en el orden en que rclone las fue apartando.
    """
    def base(v: Version) -> str:
        """Devuelve el nombre de una versión sin numerar."""
        if v.lado in ETIQUETA_LADO:
            return ETIQUETA_LADO[v.lado]
        return ETIQUETA_ORIGINAL if v.es_original else ETIQUETA_COPIA

    nombres = [base(v) for v in conflicto.versiones]
    salida, vistos = [], {}
    for v, nombre in zip(conflicto.versiones, nombres):
        if nombres.count(nombre) > 1:
            vistos[nombre] = vistos.get(nombre, 0) + 1
            nombre = f"{nombre} ({vistos[nombre]})"
        salida.append((v, nombre))
    return salida


def etiqueta(conflicto: Conflicto, version: Version) -> str:
    """Devuelve el nombre para la persona de esa versión del conflicto."""
    return dict((v.ruta, e) for v, e in etiquetas(conflicto))[version.ruta]


def huella(ruta: Path) -> tuple[int, int] | None:
    """Devuelve `(tamaño, fecha en ns)` del fichero, o `None` si no está."""
    try:
        st = ruta.stat()
    except OSError:
        return None
    return st.st_size, st.st_mtime_ns


def tamano(octetos: int) -> str:
    """Devuelve un tamaño en octetos como texto («12,3 KB»)."""
    valor = float(octetos)
    for unidad in ("B", "KB", "MB", "GB"):
        if valor < 1024 or unidad == "GB":
            break
        valor /= 1024
    texto = f"{valor:.0f}" if unidad == "B" else f"{valor:.1f}".replace(".", ",")
    return f"{texto} {unidad}"


def fecha(ns: int) -> str:
    """Devuelve una fecha en nanosegundos como texto («10/09/2026 18:20»)."""
    return f"{datetime.fromtimestamp(ns / 1e9):%d/%m/%Y %H:%M}"


def describir(ruta: Path) -> str:
    """Devuelve lo que hace falta para elegir: «12,3 KB · 10/09/2026 18:20»."""
    dato = huella(ruta)
    if dato is None:
        return "ya no está"
    return f"{tamano(dato[0])} · {fecha(dato[1])}"


@dataclass
class ResolvePlan:
    """Qué versión se queda con el nombre de verdad y qué se borra.

    `consequences` y `warnings` se enseñan antes de confirmar (mismo contrato
    que `pair_editor.EditPlan`); `execute()` solo se llama si la persona dice
    que sí.

    Args:
        conflicto: El conflicto que se resuelve.
        conserva: La versión que se queda con el nombre de verdad.
        descartar: Las copias que se borran.
        huellas: Tamaño y fecha de cada fichero cuando se pensó el plan.
        consequences: Una línea por consecuencia.
        warnings: Lo que conviene saber antes de confirmar.
    """
    conflicto: Conflicto
    conserva: Version
    descartar: list[Path]
    huellas: dict[Path, tuple[int, int] | None]
    consequences: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def execute(self) -> list[str]:
        """Pone la versión elegida en su sitio, borra lo demás y devuelve qué ha hecho.

        No hace falta deshacer nada, y es por el orden. Lo primero que cambia
        el disco es `mover()`, que es atómico: si falla, no ha cambiado nada.
        Después solo quedan borrados de versiones que se han decidido
        descartar; si alguno falla, la elegida ya está en su sitio y lo que no
        se ha podido borrar sigue teniendo su nombre de conflicto, así que
        vuelve a salir en la lista. El único estado a medias posible es «falta
        por borrar una copia», que no pierde nada y se arregla repitiendo.

        Antes de tocar nada se comprueba que ningún fichero haya cambiado desde
        que se pensó el plan: lo que se confirmó eran esos tamaños y esas
        fechas, no los de ahora.

        Raises:
            ResolucionImposible: Si algo ha cambiado o no se ha podido mover o
                borrar.
        """
        for ruta, antes in self.huellas.items():
            if huella(ruta) != antes:
                raise ResolucionImposible(
                    f"«{ruta.name}» ha cambiado desde que se preparó esto. Vuelve a "
                    f"abrir el conflicto para ver cómo está ahora.")

        original = self.conflicto.original
        hechos: list[str] = []
        if self.conserva.ruta != original:
            try:
                mover(self.conserva.ruta, original)
            except OSError as e:
                raise ResolucionImposible(
                    f"No se ha podido poner «{self.conserva.ruta.name}» como "
                    f"«{original.name}»; no se ha tocado nada.\n\n{e}") from e
            hechos.append(f"«{original.name}» es ahora la "
                          f"{etiqueta(self.conflicto, self.conserva)}")

        fallidos = []
        for ruta in self.descartar:
            try:
                borrar(ruta)
                hechos.append(f"Borrado «{ruta.name}»")
            except FileNotFoundError:
                pass                              # ya no estaba: lo que se quería
            except OSError as e:
                fallidos.append(f"«{ruta.name}»: {e}")
        if fallidos:
            raise ResolucionImposible(
                f"La versión elegida ya está como «{original.name}», pero no se ha "
                f"podido borrar:\n\n" + "\n".join(fallidos) +
                "\n\nSigue apareciendo como conflicto; se puede repetir.")
        return hechos


def puede(conflicto: Conflicto, lado: str) -> bool:
    """Indica si hay UNA versión de ese lado que conservar; habilita cada botón."""
    version = conflicto.version(lado)
    return version is not None and huella(version.ruta) is not None


def plan_lado(conflicto: Conflicto, lado: str) -> ResolvePlan:
    """Devuelve el plan de quedarse con la versión de un lado.

    Es la de este dispositivo o la del remoto.
    """
    version = conflicto.version(lado)
    if version is None:
        raise ResolucionImposible(
            f"No se sabe cuál es la {ETIQUETA_LADO[lado]} de «{conflicto.relativa}»: "
            f"elige una versión concreta de la lista.")
    return plan_conservar(conflicto, version)


def plan_conservar(conflicto: Conflicto, version: Version) -> ResolvePlan:
    """Devuelve el plan de conservar `version` y borrar las demás.

    La elegida se queda con el nombre de verdad.
    """
    if huella(version.ruta) is None:
        raise ResolucionImposible(
            f"«{version.ruta.name}» ya no está: no se puede conservar. Vuelve a "
            f"abrir los conflictos para ver cómo están ahora.")

    rel = conflicto.relativa
    otras = [v for v in conflicto.versiones if v.ruta != version.ruta]
    # El original descartado no se borra: lo sustituye `mover()`, de una vez.
    a_borrar = [v.ruta for v in otras if not v.es_original]
    plan = ResolvePlan(conflicto=conflicto, conserva=version, descartar=a_borrar,
                       huellas={v.ruta: huella(v.ruta) for v in conflicto.versiones})

    nombre = etiqueta(conflicto, version)
    if version.es_original:
        plan.consequences.append(
            f"Se queda «{rel}» tal como está: la {nombre} ({describir(version.ruta)}).")
    else:
        plan.consequences.append(
            f"La {nombre} ({describir(version.ruta)}) pasa a ser «{rel}».")
    for otra in otras:
        texto = f"la {etiqueta(conflicto, otra)} ({describir(otra.ruta)})"
        if otra.es_original:
            plan.consequences.append(f"Sustituye a {texto}, que se pierde.")
        else:
            plan.consequences.append(f"Se borra {texto}.")
    plan.consequences.append("Lo que se descarta se borra del dispositivo, sin papelera.")
    plan.consequences.append(NOTA_LOCAL)

    elegida = huella(version.ruta)
    if any((h := huella(o.ruta)) is not None and elegida is not None and h[1] > elegida[1]
           for o in otras):
        plan.warnings.append(
            "La versión que se descarta es más reciente que la que se conserva. "
            "Comprueba que es la que quieres perder.")
    if es_del_llavero(conflicto):
        plan.warnings.append(PIERDE_LLAVERO)
    return plan


def nombre_pareja(nombre: str) -> str:
    """Devuelve cómo se enseña la pareja de un conflicto: la del llavero, sin su nombre interno."""
    return "(el llavero)" if nombre == model.LLAVERO else nombre


def es_del_llavero(conflicto: Conflicto) -> bool:
    """Indica si el conflicto es de la base del llavero, que se combina en vez de elegir."""
    return conflicto.pareja == model.LLAVERO and conflicto.original.suffix.lower() == ".kdbx"


def puede_combinar(conflicto: Conflicto) -> bool:
    """Indica si «Combinar» tiene con qué: la base con su nombre, alguna copia y keepassxc-cli."""
    programa = keepassxc.cli()
    return (es_del_llavero(conflicto) and huella(conflicto.original) is not None
            and bool(conflicto.copias) and programa is not None and programa.is_file())


def en_versiones(conflicto: Conflicto, copia: Path, sello: str) -> Path:
    """Devuelve dónde queda una copia combinada: en `.prversions/`, con el sello de rclone.

    El mismo nombre que le pondría `--backup-dir` con `--suffix ~%Y%m%d-%H%M%S
    --suffix-keep-extension` (`personal.conflicto-remoto1~20261005-073000.kdbx`),
    así que «Versiones…» la ve y la purga como las demás.
    """
    relativa = copia.relative_to(conflicto.raiz)
    return (conflicto.raiz / model.VERSIONS_DIR / relativa.parent
            / f"{copia.stem}{sello}{copia.suffix}")


def no_combinado(copia: Path, codigo: int) -> str:
    """Devuelve lo que se dice si `keepassxc-cli` no combina: qué hacer en la ventana de KeePassXC."""
    return (f"No se ha combinado «{copia.name}» (código {codigo}), y no se ha tocado nada: "
            "puede que la contraseña o el fichero llave no fueran los de la base, o que se "
            "cerrara la consola.\n\n"
            "También se puede combinar desde KeePassXC: con la base abierta, «Base de datos → "
            f"Combinar desde base de datos…» y elige la copia:\n\n{copia}")


@dataclass
class CombinarPlan:
    """Combinar en la base del llavero lo de sus copias de conflicto.

    Mismo contrato que `ResolvePlan`: `consequences` y `warnings` se enseñan
    antes de confirmar y `execute()` solo corre si la persona dice que sí.
    `execute()` espera a la consola, así que se lanza desde `working()`.

    Args:
        conflicto: El conflicto de la base.
        llave: El fichero llave de este equipo, si la base lo pide.
        huellas: Tamaño y fecha de la base y las copias cuando se pensó el plan.
        consequences: Una línea por consecuencia.
        warnings: Lo que conviene saber antes de confirmar.
        sin_contrasena: La base va solo con su fichero llave (`llave_interna`):
            no se pide contraseña.
    """
    conflicto: Conflicto
    llave: Path | None
    huellas: dict[Path, tuple[int, int] | None]
    consequences: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sin_contrasena: bool = False

    def execute(self) -> list[str]:
        """Combina cada copia en la base, de una en una, y la aparta a `.prversions/`.

        Una copia que `keepassxc-cli` no combina se queda donde estaba y se
        para ahí: las de antes ya están combinadas y apartadas, y repetirlo
        no combina dos veces (lo que ya está, «no modifica» la base).

        Raises:
            ResolucionImposible: Si algo ha cambiado desde el plan, o una copia
                no se ha combinado o no se ha podido apartar.
        """
        for ruta, antes in self.huellas.items():
            if huella(ruta) != antes:
                raise ResolucionImposible(
                    f"«{ruta.name}» ha cambiado desde que se preparó esto. Vuelve a "
                    f"abrir el conflicto para ver cómo está ahora.")
        base = self.conflicto.original
        sello = datetime.now().strftime("~%Y%m%d-%H%M%S")
        hechos: list[str] = []
        for copia in self.conflicto.copias:
            extra = {"sin_contrasena": True} if self.sin_contrasena else {}
            codigo = keepassxc.combinar(base, copia, self.llave, **extra)
            if codigo != 0:
                raise ResolucionImposible(no_combinado(copia, codigo))
            destino = en_versiones(self.conflicto, copia, sello)
            try:
                destino.parent.mkdir(parents=True, exist_ok=True)
                mover(copia, destino)
            except OSError as e:
                raise ResolucionImposible(
                    f"«{copia.name}» ya está combinada en «{base.name}», pero no se ha podido "
                    f"apartar a {model.VERSIONS_DIR}: sigue saliendo como conflicto, y "
                    f"combinarla otra vez no cambia nada.\n\n{e}") from e
            hechos.append(f"«{copia.name}» combinada en «{base.name}»")
        return hechos


def plan_combinar(conflicto: Conflicto, llave: Path | None, abierto: bool = False,
                  sin_contrasena: bool = False) -> CombinarPlan:
    """Devuelve el plan de combinar en la base del llavero lo de sus copias.

    Args:
        conflicto: El conflicto de la base.
        llave: El fichero llave de este equipo, si la base lo pide.
        abierto: Si el KeePassXC de la unidad está abierto: verá la base
            cambiar y la recargará (S3), o la combinará con lo que tenga sin
            guardar (S5).
        sin_contrasena: La base va solo con su fichero llave: no se pide
            contraseña, y sin la llave no se puede combinar.

    Raises:
        ResolucionImposible: Si no hay con qué combinar.
    """
    if not es_del_llavero(conflicto):
        raise ResolucionImposible("Solo se combina la base del llavero.")
    if huella(conflicto.original) is None:
        raise ResolucionImposible(
            f"«{conflicto.original.name}» no está con su nombre: no hay dónde combinar. "
            "Elige una de las versiones de la lista.")
    if not conflicto.copias:
        raise ResolucionImposible(f"«{conflicto.relativa}» ya no tiene copias de conflicto.")
    programa = keepassxc.cli()
    if programa is None or not programa.is_file():
        raise ResolucionImposible(
            "No hay keepassxc-cli con el que combinar en este equipo (falta en el dispositivo, "
            "o es el KeePassXC de Flathub): no se puede "
            "combinar desde prdrive. Se puede desde la ventana de KeePassXC, con «Base de "
            "datos → Combinar desde base de datos…».")
    if sin_contrasena and llave is None:
        raise ResolucionImposible(
            "Este llavero va sin contraseña y su fichero llave no está en el dispositivo: "
            "sin él no se puede combinar. Dalo en «Ajustes → Llavero…».")
    plan = CombinarPlan(conflicto=conflicto, llave=llave,
                        huellas={v.ruta: huella(v.ruta) for v in conflicto.versiones},
                        sin_contrasena=sin_contrasena)
    base = conflicto.original.name
    for v, nombre in etiquetas(conflicto):
        if not v.es_original:
            plan.consequences.append(
                f"Lo de la {nombre} ({describir(v.ruta)}) entra en «{base}», que se queda "
                "con lo de las dos.")
    if sin_contrasena:
        plan.consequences.append(
            "Se abre una consola de KeePassXC que combina con el fichero llave del "
            "dispositivo: no pide contraseña.")
    else:
        plan.consequences.append(
            "Se abre una consola de KeePassXC que pide la contraseña de la base"
            + (" (el fichero llave de este equipo ya va puesto)" if llave else "")
            + ". prdrive no la ve.")
    plan.consequences.append(
        f"Cada copia combinada pasa a {model.VERSIONS_DIR}, de donde se puede recuperar. Si "
        "no se combina, no se toca nada.")
    plan.consequences.append(NOTA_LOCAL)
    if abierto:
        plan.warnings.append(
            "KeePassXC está abierto: verá que la base ha cambiado y la recargará, o te "
            "propondrá combinarla con lo que tengas sin guardar.")
    return plan
