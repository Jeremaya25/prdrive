#!/usr/bin/env python3
"""Un registro de Windows de mentira (`HKEY_CURRENT_USER`), en memoria.

`_harness.py` lo pone en `common/registro.py` para TODOS los tests: en el
Windows de quien los ejecuta puede haber un agente instalado de verdad, y un
test que se olvide de sustituir el registro no puede quitarle su arranque ni su
ficha de «Aplicaciones instaladas». Un test que lo mire usa `_harness.REGISTRO`
(o pone uno suyo con `poner()`).

Mismo contrato que `common/registro.py`: claves sin colmena y sin distinguir
mayúsculas; un valor de texto se lee, uno numérico no (`leer()` da `None`).
"""

from __future__ import annotations


class Registro:
    """Un `HKEY_CURRENT_USER` de mentira: clave (en minúsculas) → {valor: dato}.

    Attributes:
        claves: Lo escrito; el nombre del valor predeterminado es `""`.
        roto: Si se da, escribir y borrar lanzan `OSError`.
    """

    def __init__(self) -> None:
        self.claves: dict[str, dict[str, object]] = {}
        self.roto = False

    @staticmethod
    def _k(clave: str) -> str:
        return clave.lower()

    def dato(self, clave: str, nombre: str = ""):
        """Devuelve lo escrito en ese valor, sea del tipo que sea, o `None`."""
        return self.claves.get(self._k(clave), {}).get(nombre.lower())

    def leer(self, clave: str, nombre: str = "") -> str | None:
        valor = self.dato(clave, nombre)
        return valor if isinstance(valor, str) else None

    def _poner(self, clave: str, nombre: str, valor: object) -> None:
        if self.roto:
            raise OSError("acceso denegado")
        partes = clave.split("\\")
        for i in range(1, len(partes)):
            self.claves.setdefault(self._k("\\".join(partes[:i])), {})
        self.claves.setdefault(self._k(clave), {})[nombre.lower()] = valor

    def escribir(self, clave: str, valor: str, nombre: str = "") -> None:
        self._poner(clave, nombre, str(valor))

    def escribir_numero(self, clave: str, numero: int, nombre: str) -> None:
        self._poner(clave, nombre, int(numero))

    def borrar_valor(self, clave: str, nombre: str) -> bool:
        if self.roto:
            raise OSError("acceso denegado")
        valores = self.claves.get(self._k(clave))
        if valores is None or nombre.lower() not in valores:
            return False
        del valores[nombre.lower()]
        return True

    def _hijas(self, clave: str) -> list[str]:
        prefijo = self._k(clave) + "\\"
        return [k for k in self.claves if k.startswith(prefijo)]

    def borrar(self, clave: str) -> bool:
        if self.roto:
            raise OSError("acceso denegado")
        if self._k(clave) not in self.claves:
            return False
        if self._hijas(clave):
            raise OSError("tiene subclaves")
        del self.claves[self._k(clave)]
        return True

    def vacia(self, clave: str) -> bool | None:
        if self._k(clave) not in self.claves:
            return None
        return not self._hijas(clave) and not self.claves[self._k(clave)]

    def subclaves(self, clave: str) -> list[str]:
        prefijo = self._k(clave) + "\\"
        return [k[len(prefijo):] for k in self.claves
                if k.startswith(prefijo) and "\\" not in k[len(prefijo):]]


FUNCIONES = ("leer", "escribir", "escribir_numero", "borrar_valor", "borrar", "vacia",
             "subclaves")
"""Las funciones de `common/registro.py` que se sustituyen."""


def poner(reg: Registro | None = None) -> Registro:
    """Pone un registro de mentira en `common/registro.py` y lo devuelve.

    Args:
        reg: El que se pone; sin él, uno vacío.
    """
    from common import registro
    reg = Registro() if reg is None else reg
    for nombre in FUNCIONES:
        setattr(registro, nombre, getattr(reg, nombre))
    return reg
