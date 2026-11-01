"""La carpeta de una pareja en el dispositivo: con qué otra choca y qué arriesga un espejo en ella.

La carpeta la elige cada dispositivo al meter una pareja (#196): «Usar aquí»
(`ui/pair_editor.plan_enable()`) y los dos asistentes del instalador
(`install/deploy.avisos_carpetas()`, `install/raiz_equipo.revisar_local()`).
Los tres avisan de lo mismo porque lo dice esto. No cambia nada: solo mira el
disco, y lo que no puede mirar no lo da por peligroso.

Dos peligros:

- **Dos parejas sobre los mismos ficheros** (la misma carpeta, o una dentro de
  la otra): cada una borra lo que la otra no tiene.
- **Un espejo en la carpeta equivocada.** El de subida (`up-mirror`) hace del
  remoto una copia de la carpeta: vacía, lo vacía, y sin carpeta la pasada
  aborta sin crearla (#151). El de bajada (`down-mirror`) hace de la carpeta una
  copia del remoto: lo que ya tuviera y el remoto no, se borra.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from . import model


def tramos(local: Any) -> tuple[str, ...]:
    """Devuelve los tramos de una carpeta local, para compararla con otra.

    Sin mayúsculas (Windows y exFAT no las distinguen), con `\\` como `/` y sin
    tramos vacíos ni `.`: la raíz entera (`"."`) no tiene ninguno y así contiene
    a todas.
    """
    texto = str(local).replace("\\", "/").strip()
    return tuple(t.casefold() for t in texto.split("/") if t.strip() not in ("", "."))


def solapadas(otras: Mapping[str, str], local: str) -> list[str]:
    """Devuelve las parejas de `otras` (`{nombre: local}`) cuya carpeta choca con `local`.

    Chocan la misma carpeta, una que la contiene y una que está dentro.
    """
    mia = tramos(local)
    salida = []
    for nombre, suya in otras.items():
        otra = tramos(suya)
        corto = min(len(mia), len(otra))
        if mia[:corto] == otra[:corto]:
            salida.append(nombre)
    return salida


def tiene_cosas(carpeta: Path) -> bool | None:
    """Dice si la carpeta tiene algo dentro; `None` si no existe o no se puede mirar."""
    try:
        return any(carpeta.iterdir()) if carpeta.is_dir() else None
    except OSError:
        return None


def riesgo_espejo(modo: str, carpeta: Path) -> str | None:
    """Dice qué arriesga un espejo en esa carpeta, como el final de una frase; `None` si nada.

    Es lo que dicen las tres que eligen carpeta, cada una con su principio de
    frase: el plan de «Usar aquí» y el asistente con el nombre de la pareja, la
    nota de cada caja de «En este equipo» sin él.
    """
    if modo == "up-mirror" and not carpeta.exists():
        return ("no existe, y es un espejo de subida: la pasada no la crea y abortará "
                "hasta que exista con lo que quieras subir")
    cosas = tiene_cosas(carpeta)
    if modo == "up-mirror" and cosas is False:
        return ("está vacía, y es un espejo de subida: la primera pasada vaciaría el "
                "remoto. Pon antes lo que quieras subir")
    if modo == "down-mirror" and cosas:
        return ("tiene cosas, y es un espejo de bajada: la primera pasada borrará de ella "
                "lo que no esté en el remoto")
    return None


def avisos(nombre: str, modo: str, local: str, raiz: Path,
           otras: Mapping[str, str]) -> list[str]:
    """Devuelve lo que hay que avisar antes de poner a `nombre` en la carpeta `local`.

    Args:
        nombre: La pareja.
        modo: Su modo.
        local: La carpeta elegida, relativa a la raíz.
        raiz: La raíz del dispositivo.
        otras: Las demás parejas del dispositivo, `{nombre: local}`.
    """
    salida = []
    riesgo = riesgo_espejo(modo, Path(raiz) / model.normalizar_local(local))
    if riesgo:
        salida.append(f"La carpeta '{local}' de '{nombre}' {riesgo}.")
    chocan = solapadas(otras, local)
    if chocan:
        salida.append(
            f"La carpeta '{local}' de '{nombre}' ya la usa {', '.join(chocan)} (la misma, o "
            f"una dentro de la otra): dos parejas sobre los mismos ficheros se pisan los "
            f"borrados.")
    return salida
