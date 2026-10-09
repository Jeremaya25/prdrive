"""F21 (Windows): los `.pyc` de hash comprobado se reutilizan entre sistemas de ficheros; los de hora, no.

Es la mitad de Windows de la prueba (la de Linux, `f21_pyc_entre_sistemas_linux.py`,
deja `$F21_ARBOL` con el árbol precompilado y su `manifiesto.json`). Para FAT32 y
exFAT, en un disco virtual de verdad:

1. copia el árbol al volumen y comprueba que cada `.pyc` copiado es idéntico al de Linux;
2. mueve la hora de cada fuente 7 h, como si el programa hubiera pasado de un equipo a otro;
3. cambia una letra de un comentario de `common/` sin cambiar su tamaño ni su hora;
4. corre UNA vez el Python fijado de Windows con `-I -v`, importando cada módulo;
5. lee el registro de `-v`: `# <pyc> matches <fuente>` es que el `.pyc` se reutiliza;
   `# code object from '<fuente>'` sin esa línea es que el módulo se reconstruye.

Se espera que todo `.pyc` de hash se reutilice sin reescribirse, y que el fuente
cambiado y el control de hora se reconstruyan. Un módulo que no carga (`ui.bandeja_linux`
es de Linux; `ui.tk_install` necesita `install/`, que no va al dispositivo) se apunta
en el registro: su `.pyc` se valida igual, antes de ejecutarse.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path

import comun

CODIGO = "F21"
SISTEMA = "W"
QUE = ("los .pyc de hash comprobado se reutilizan en FAT32 y exFAT, y los de hora "
       "se rehacen (la mitad de Windows)")

ETIQUETA = "cpython-314"
CONTROL = "control_marca_tiempo.py"
TIPOS = ("fat32", "exfat")
SIETE_HORAS_NS = 7 * 3600 * 10**9
REUTILIZADO = "reutilizado"
RECONSTRUIDO = "reconstruido"

SONDA = "import sys; print('%d.%d.%d' % sys.version_info[:3], sys.implementation.cache_tag)"

_IMPORTAR = '''\
import importlib, json, sys
sys.path.insert(0, __RAIZ__)
fallos = {}
for nombre in __MODULOS__:
    try:
        importlib.import_module(nombre)
    except BaseException as e:
        fallos[nombre] = type(e).__name__ + ": " + str(e)[:160]
print("FIN " + json.dumps(fallos))
'''
"""Lo que corre el intérprete: importa cada módulo del programa en un solo proceso."""


def _sha(ruta: Path) -> str:
    """El SHA-256 de un fichero."""
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _foto(ruta: Path) -> tuple[int, str]:
    """La hora y el SHA-256 de un fichero: si cambian, el fichero se ha reescrito."""
    return ruta.stat().st_mtime_ns, _sha(ruta)


def _mutar(destino: Path, candidatos: list[str]) -> tuple[str, bool] | None:
    """Cambia una letra de un comentario por otra, sin tocar tamaño ni hora.

    Args:
        destino: La carpeta `.prdrive/` del volumen.
        candidatos: Fuentes (relativas) donde buscar, en orden.

    Returns:
        `(fuente, conserva)`: el fuente cambiado y si su tamaño y su hora siguen
        iguales; `None` si ningún candidato tiene un comentario con letra.
    """
    for rel in candidatos:
        src = destino / rel
        datos = src.read_bytes()
        m = re.search(rb"# ([A-Za-z])", datos)
        if m is None:
            continue
        st = src.stat()
        nueva = b"Q" if m.group(1) != b"Q" else b"R"
        src.write_bytes(datos[:m.start(1)] + nueva + datos[m.end(1):])
        os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns))
        ahora = src.stat()
        return rel, ahora.st_size == st.st_size and ahora.st_mtime_ns == st.st_mtime_ns
    return None


def clasificar(salida: str, fuentes: list[str]) -> dict[str, str | None]:
    """Dice, para cada fuente, si su `.pyc` se reutilizó, se reconstruyó o no aparece.

    Con `python -v`, un `.pyc` válido se anuncia con `<pyc> matches <fuente>`; un
    módulo reconstruido, con `code object from <fuente>`, con o sin comillas según
    la versión: la comparación no depende de ellas. Las rutas de Windows llegan con
    las barras invertidas, y las de `repr()`, dobladas: se pasan todas a `/` antes.

    Args:
        salida: El registro de `python -v` (su stderr).
        fuentes: Las fuentes relativas al programa (`common/store.py`).

    Returns:
        `REUTILIZADO`, `RECONSTRUIDO` o `None` (no se vio su importación) por fuente.
    """
    lineas = [linea.replace("\\\\", "/").replace("\\", "/").rstrip()
              for linea in salida.splitlines()]
    resultado: dict[str, str | None] = {}
    for rel in fuentes:
        sufijo = "/" + rel
        if any(" matches " in linea and linea.endswith(sufijo) for linea in lineas):
            resultado[rel] = REUTILIZADO
        elif any("code object from " in linea and linea.rstrip("'").endswith(sufijo)
                 for linea in lineas):
            resultado[rel] = RECONSTRUIDO
        else:
            resultado[rel] = None
    return resultado


def probar_copia(p: comun.Prueba, tipo: str, raiz: Path, arbol: Path, python: str,
                 manifiesto: dict) -> None:
    """Corre la prueba entera con el árbol copiado a `raiz`.

    Es lo que `probar()` hace en cada volumen de Windows; se llama también en
    una carpeta cualquiera para probar la lógica en otro sistema.

    Args:
        p: Donde se apuntan las comprobaciones.
        tipo: El sistema de ficheros, para los mensajes.
        raiz: La raíz del volumen; el programa va a `raiz/.prdrive/`.
        arbol: La carpeta `$F21_ARBOL` que dejó la mitad de Linux.
        python: El intérprete fijado de Windows.
        manifiesto: Lo que dejó la mitad de Linux (`manifiesto.json`).
    """
    destino = Path(raiz) / ".prdrive"
    shutil.copytree(arbol / ".prdrive", destino)
    entradas = manifiesto["entradas"]

    malas = [e["pyc"] for e in entradas if _sha(destino / e["pyc"]) != e["sha256"]]
    p.ver(f"{tipo}: cada .pyc copiado es idéntico al de Linux", malas, [])

    for e in entradas:
        src = destino / e["fuente"]
        st = src.stat()
        os.utime(src, ns=(st.st_atime_ns + SIETE_HORAS_NS, st.st_mtime_ns + SIETE_HORAS_NS))

    de_hash = [e for e in entradas if e["bandera"] & 1]
    mutado = _mutar(destino, sorted(e["fuente"] for e in de_hash
                                    if e["fuente"].startswith("common/")))
    p.ver(f"{tipo}: hay un fuente de common/ con un comentario que cambiar",
          mutado is not None, True)
    mut = mutado[0] if mutado else None
    if mutado:
        p.ver(f"{tipo}: el fuente cambiado conserva tamaño y hora", mutado[1], True)

    control = next(e for e in entradas if e["fuente"] == CONTROL)
    cab = (destino / control["pyc"]).read_bytes()[:16]
    guardada = (int.from_bytes(cab[8:12], "little"), int.from_bytes(cab[12:16], "little"))
    ahora = (destino / CONTROL).stat()
    aplicable = (int(ahora.st_mtime), ahora.st_size) != guardada

    antes = {e["pyc"]: _foto(destino / e["pyc"]) for e in entradas}

    script = comun.carpeta("importar") / "importar.py"
    script.write_text(_IMPORTAR.replace("__RAIZ__", repr(str(destino)))
                      .replace("__MODULOS__", repr([e["modulo"] for e in entradas])),
                      encoding="utf-8")
    r = comun.ejecutar([python, "-I", "-v", str(script)], timeout=900)
    fin = [linea for linea in r.stdout.splitlines() if linea.startswith("FIN ")]
    p.ver(f"{tipo}: la pasada del intérprete termina", len(fin), 1)
    if not fin:
        return
    fallos = json.loads(fin[-1][len("FIN "):])
    for modulo, motivo in sorted(fallos.items()):
        print(f"  NOTA   no carga: {modulo}: {motivo}", flush=True)
    if fallos:
        p.nota(f"{tipo}: {len(fallos)} módulos no cargan (véase el registro)")

    clas = clasificar(r.stderr, [e["fuente"] for e in entradas])
    comparables = [e for e in de_hash if e["fuente"] != mut]
    p.ver(f"{tipo}: hay .pyc de hash que comparar", len(comparables) > 0, True)
    p.ver(f"{tipo}: los {len(comparables)} .pyc de hash se reutilizan",
          sorted(e["fuente"] for e in comparables if clas[e["fuente"]] != REUTILIZADO), [])
    reescritos = sorted(e["pyc"] for e in comparables
                        if _foto(destino / e["pyc"]) != antes[e["pyc"]])
    p.ver(f"{tipo}: y ninguno se reescribe (bytes y hora)", reescritos, [])
    if mut is not None:
        p.ver(f"{tipo}: el fuente cambiado con el mismo tamaño y hora se reconstruye",
              clas[mut], RECONSTRUIDO)
    if aplicable:
        p.ver(f"{tipo}: el control de hora se reconstruye", clas[CONTROL], RECONSTRUIDO)
    else:
        p.nota(f"control no aplicable en {tipo}")


def probar(p: comun.Prueba) -> None:
    """Comprueba el intérprete fijado y corre la prueba en FAT32 y en exFAT.

    Raises:
        Saltada: Si no hay `F21_ARBOL` o `PRDRIVE_PYTHON`, o si el sistema no
            deja crear ningún volumen.
    """
    from common import pins

    arbol = os.environ.get("F21_ARBOL", "")
    if not arbol:
        raise comun.Saltada("falta F21_ARBOL (la deja el trabajo pyc-linux)")
    python = os.environ.get("PRDRIVE_PYTHON", "")
    if not Path(python).is_file():
        raise comun.Saltada("no hay Python fijado (PRDRIVE_PYTHON: tests/_runtime_ci.py runtime)")

    manifiesto = json.loads((Path(arbol) / "manifiesto.json").read_text(encoding="utf-8"))
    r = comun.ejecutar([python, "-I", "-c", SONDA], timeout=120)
    p.ver("el Python de Windows es el fijado (versión y etiqueta de .pyc)",
          r.stdout.split(), [pins.PYTHON_VERSION, ETIQUETA])
    p.ver("el manifiesto es de esa etiqueta", manifiesto["etiqueta"], ETIQUETA)
    comun.por_cada(p, TIPOS, lambda tipo: _en_volumen(p, tipo, Path(arbol), python, manifiesto))


def _en_volumen(p: comun.Prueba, tipo: str, arbol: Path, python: str, manifiesto: dict) -> None:
    """Corre la prueba en un disco virtual de ese sistema de ficheros."""
    with comun.volumen_windows(tipo) as raiz:
        probar_copia(p, tipo, raiz, arbol, python, manifiesto)
