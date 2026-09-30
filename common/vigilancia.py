#!/usr/bin/env python3
"""
vigilancia.py — Ver que una carpeta local ha cambiado, para no esperar al intervalo.

Con `watch = true` en una pareja, el servicio no espera a su próximo ciclo para
sincronizarla cuando alguien toca sus ficheros: en cuanto los cambios se calman,
lanza una pasada de ESA pareja. Lo que llega del remoto sigue esperando al
intervalo, como antes: desde aquí no se puede ver.

**Sondeo, no eventos del sistema.** Es lo mismo que decide `penwatch.py` para los
montajes, y por lo mismo: inotify, `ReadDirectoryChangesW` y FSEvents son tres
API distintas, sin biblioteca estándar, y en un dispositivo extraíble —exFAT,
contenedores de VeraCrypt, carpetas de red— unas avisan y otras no. Una pasada de
`os.scandir` mirando tamaño y fecha funciona igual en todas partes y se prueba
con un reloj de mentira. El coste es un recorrido de stats cada `CADA` segundos,
y por eso hay un tope de ficheros (`TOPE_FICHEROS`): pasado ese tamaño el sondeo
se apaga para esa pareja —se dice una vez— y vuelve a mandar el intervalo.

**Las reglas** (todas de `Vigia`, que es PURO: el reloj y el recorrido entran
como datos, como en `planificador.py`):

  * **Calma.** Un cambio no dispara nada hasta que pasan `CALMA` segundos sin
    otro: guardar un fichero grande, o descomprimir un zip, son cientos de
    eventos seguidos y deben ser UNA pasada, no cientos.
  * **Separación.** Entre dos pasadas disparadas por cambios, al menos `MINIMO`
    segundos, aunque no pare de cambiar: una carpeta que se reescribe sin parar
    (un log, una base de datos abierta) no puede tener a rclone corriendo
    siempre. Lo que cambie mientras tanto queda pendiente, no se pierde.
  * **`.prversions/` no cuenta** (`model.VERSIONS_DIR`): lo escribe la propia
    sincronización, y vigilarla sería dispararse con lo que uno mismo hace.
  * **La instantánea se toma ANTES de la pasada** (`Vigia.iniciar()`), no
    después: lo que el usuario toque mientras rclone trabaja tiene que contar
    como cambio. El precio es que lo que la pasada escribe en la carpeta (lo
    que baja del remoto) se ve como un cambio y provoca UNA pasada más, que no
    encuentra nada que hacer y no escribe, así que no se encadena.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

CADA = 5.0              # s entre recorridos de una carpeta
CALMA = 10.0            # s sin cambios antes de sincronizar
MINIMO = 60.0           # s entre dos pasadas disparadas por cambios
TOPE_FICHEROS = 50_000  # más que esto y el sondeo se apaga para esa pareja

# Lo que se mira de cada fichero: si alguna de las dos cosas cambia, cambió.
Firma = tuple[int, int]             # (mtime_ns, tamaño)
Instantanea = Mapping[str, Firma]


class Excedido(Exception):
    """La carpeta tiene más de `TOPE_FICHEROS` ficheros."""


def instantanea(raiz: Path, ignorar: tuple[str, ...] = (),
                tope: int = TOPE_FICHEROS) -> dict[str, Firma]:
    """Firma de cada fichero bajo `raiz`, por ruta relativa con «/».

    No sigue enlaces a carpetas (un bucle, o salir de la raíz: lo que
    `pair_editor.ruta_local_relativa` ya cuida al elegir la carpeta). Una carpeta
    que desaparece o no se deja leer a media vuelta se salta: una carpeta
    sin leer no puede hacer caer al servicio. `raiz` que no existe da {}.
    Lanza `Excedido` al pasar de `tope` ficheros."""
    vista: dict[str, Firma] = {}
    pendientes = [(raiz, "")]
    while pendientes:
        carpeta, prefijo = pendientes.pop()
        try:
            with os.scandir(carpeta) as it:
                entradas = list(it)
        except OSError:
            continue
        for e in entradas:
            if e.name in ignorar:
                continue
            try:
                if e.is_dir(follow_symlinks=False):
                    pendientes.append((Path(e.path), f"{prefijo}{e.name}/"))
                    continue
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            vista[f"{prefijo}{e.name}"] = (st.st_mtime_ns, st.st_size)
            if len(vista) > tope:
                raise Excedido(str(raiz))
    return vista


def cambiada(antes: Instantanea, despues: Instantanea) -> bool:
    """¿Es distinta? Ficheros nuevos, desaparecidos o con otra firma."""
    return antes != despues


@dataclass
class _Estado:
    ruta: Path
    base: Instantanea | None = None     # lo último visto
    cambio: float | None = None         # cuándo se vio el último cambio sin atender
    ultima_pasada: float | None = None  # cuándo se disparó la anterior
    proximo: float = 0.0                # cuándo volver a recorrerla
    apagada: bool = False


@dataclass
class Vigia:
    """Qué parejas han cambiado y ya toca sincronizarlas.

    `recorrer(ruta, ignorar)` devuelve la instantánea (por defecto, la real;
    un test pone otra). Se le da el reloj en cada `mirar()`."""
    parejas: dict[str, Path]
    ignorar: tuple[str, ...] = ()
    cada: float = CADA
    calma: float = CALMA
    minimo: float = MINIMO
    recorrer: Callable[[Path, tuple[str, ...]], Instantanea] = instantanea
    avisar: Callable[[str], None] = lambda texto: None
    _estado: dict[str, _Estado] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self._estado = {n: _Estado(Path(r)) for n, r in self.parejas.items()}

    def _leer(self, nombre: str, est: _Estado) -> Instantanea | None:
        try:
            return self.recorrer(est.ruta, self.ignorar)
        except Excedido:
            est.apagada = True
            self.avisar(f"[{nombre}] tiene demasiados ficheros para vigilarla "
                        f"(más de {TOPE_FICHEROS}): solo se sincroniza por intervalo")
            return None

    def iniciar(self, nombre: str, ahora: float) -> None:
        """Se va a sincronizar esa pareja (por lo que sea, también por el
        intervalo): lo que había pendiente queda atendido y se parte de lo que
        hay AHORA, antes de que rclone toque nada."""
        est = self._estado.get(nombre)
        if est is None or est.apagada:
            return
        est.base = self._leer(nombre, est)
        est.cambio = None
        est.proximo = ahora + self.cada

    def mirar(self, ahora: float) -> list[str]:
        """Las parejas a sincronizar ya: cambiaron, se calmaron y ha pasado el
        tiempo mínimo desde la última vez. En el orden en que se dieron."""
        listas: list[str] = []
        for nombre, est in self._estado.items():
            if est.apagada:
                continue
            if est.base is None:
                # Primera vez: solo se toma nota, sin disparar nada. La pasada
                # completa con la que arranca el servicio ya cubre lo anterior.
                est.base = self._leer(nombre, est)
                est.proximo = ahora + self.cada
                continue
            if ahora >= est.proximo:
                est.proximo = ahora + self.cada
                ahora_vista = self._leer(nombre, est)
                if ahora_vista is not None and cambiada(est.base, ahora_vista):
                    est.base = ahora_vista
                    est.cambio = ahora
            if est.cambio is None or ahora - est.cambio < self.calma:
                continue
            if est.ultima_pasada is not None and ahora - est.ultima_pasada < self.minimo:
                continue                # queda pendiente; no se pierde
            est.ultima_pasada = ahora
            listas.append(nombre)
        return listas

    def pendiente(self, nombre: str) -> bool:
        """¿Hay un cambio visto que aún no se ha sincronizado?"""
        est = self._estado.get(nombre)
        return bool(est and est.cambio is not None)
