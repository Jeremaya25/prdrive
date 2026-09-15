#!/usr/bin/env python3
"""
fleet.py — El registro de la flota: quién más lleva este mismo catálogo.

Hasta ahora los dispositivos eran anónimos entre sí. Cada uno sabía lo suyo y
nada de los demás, así que un dispositivo olvidado en un cajón —con una versión
vieja y sin sincronizar desde hace meses— no aparecía por ningún sitio hasta que
alguien lo enchufaba y se llevaba la sorpresa.

Esto lo arregla con la pieza más pequeña que lo resuelve: **un fichero por
dispositivo**, en una carpeta `devices/` al lado del catálogo, y cada dispositivo
reescribe SOLO el suyo. No hay fichero compartido, así que no hay nada que dos
dispositivos puedan pisarse, y por eso tampoco hay aquí la ceremonia de
`catalog.push()` (releer, comparar, dejar copia): eso protege un fichero que
gobierna borrados en toda la flota, y esto es una nota de presencia.

Lo que se publica es lo que sirve para mirar la lista y decidir: quién es
(`id`, `nombre`), qué lleva (`version`, `plataformas`) y cómo está (`last_seen`,
`last_result`). Nada de rutas, ni de parejas, ni de nada que no se pueda enseñar.

Se escribe desde dos sitios y son los dos únicos: `sync.py` al terminar una
pasada de verdad, e `install/` al aprovisionar (por su propio rclone, que en ese
momento el dispositivo todavía no tiene ninguno). Leer la flota entera es cosa
de la ventana de parejas.

Como el resto de lo que lee la ventana, **nada de aquí lanza**: un fichero de
otro dispositivo escrito a medias, o un remoto que no contesta, significan «no se
sabe», no una excepción en mitad de la pantalla.
"""

from __future__ import annotations

import shutil
import socket
import tempfile
import tomllib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, NamedTuple

from . import APP_NAME, catalog, components, config_file, model, results, store, update
from .pins import PLATAFORMAS

# La carpeta cuelga de la del catálogo, no de la raíz del remoto: el catálogo ya
# se puede mover con `catalog_path`, y el registro tiene que seguirlo. Un remoto
# puede alojar dos catálogos —pruebas y el de verdad— sin mezclar sus flotas.
SUBCARPETA = "devices"
SUFIJO = ".toml"

# A partir de cuándo un dispositivo se enseña apagado. Una semana es lo que
# distingue «no lo he usado esta semana» de «esto lleva meses en un cajón».
DIAS_OBSOLETO = 7

# Cada cuánto se vuelve a subir la nota aunque no haya cambiado nada. Sin este
# freno, un servicio con cuatro parejas y ciclo de 30 minutos subiría ocho
# ficheros a la hora para decir lo mismo; con él, lo que se pierde es precisión
# en `last_seen` muy por debajo de los siete días que la hacen significar algo.
HORAS_ENTRE_NOTAS = 6

RESULTADO_OK = "ok"

CABECERA = (
    f"# {APP_NAME} — nota de presencia de un dispositivo.\n"
    "# La escribe el propio dispositivo al sincronizar. No la edites a mano: se\n"
    "# reescribe entera, y el nombre se cambia desde la ventana de parejas.\n"
)


class Dispositivo(NamedTuple):
    """Un dispositivo de la flota, tal y como él mismo se ha descrito."""
    id: str
    nombre: str
    version: str
    plataformas: tuple[str, ...]
    last_seen: str              # con el formato de `store.stamp()`
    last_result: str

    @property
    def bien(self) -> bool:
        return self.last_result == RESULTADO_OK

    def visto(self) -> datetime | None:
        try:
            return datetime.strptime(self.last_seen, "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            return None

    def obsoleto(self, ahora: datetime | None = None) -> bool:
        """¿Hace tanto que no se sabe de él que hay que mirarlo?

        Sin fecha legible cuenta como obsoleto: lo que se pregunta es «¿consta
        que este dispositivo se haya usado esta semana?», y de uno que no dice
        cuándo no consta."""
        momento = self.visto()
        if momento is None:
            return True
        return (ahora or datetime.now()) - momento > timedelta(days=DIAS_OBSOLETO)


# ---------------------------------------------------------------------------
# Dónde vive cada nota
# ---------------------------------------------------------------------------

def endpoint_catalogo(raw_local: Mapping[str, Any] | None = None) -> str:
    """Dónde está el catálogo de ESTE dispositivo.

    Sin el dict del config se lee del TOML, porque quien publica la nota es
    `sync.py`, que trabaja con un `model.Config` y no con el crudo: pedirle que
    lo cargue solo para esto sería meter el catálogo en el motor. Que no se pueda
    leer no es un problema aquí —se cae a los valores por defecto y, como mucho,
    la nota no se sube—."""
    if raw_local is None:
        try:
            raw_local = config_file.load_raw()
        except Exception:                                # noqa: BLE001
            raw_local = None
    return catalog.endpoint(raw_local)


def carpeta(raw_local: Mapping[str, Any] | None = None) -> str:
    """'remote:/ruta/devices', al lado del pairs.toml del catálogo."""
    return carpeta_de(endpoint_catalogo(raw_local))


def carpeta_de(endpoint_catalogo: str) -> str:
    """Lo mismo a partir del endpoint del catálogo, que es lo que tiene el
    instalador: allí no hay ningún `sync_config.toml` que consultar todavía."""
    remoto, _, ruta = endpoint_catalogo.partition(":")
    base = ruta.rsplit("/", 1)[0] if "/" in ruta else ""
    return f"{remoto}:{base}/{SUBCARPETA}"


def fichero(endpoint_catalogo: str, device_id: str) -> str:
    """La nota de UN dispositivo. Por su id y no por su nombre: el nombre se
    cambia desde la ventana, y un fichero que se renombra solo deja el anterior
    ahí para siempre, contando como un dispositivo más."""
    return f"{carpeta_de(endpoint_catalogo)}/{device_id}{SUFIJO}"


# ---------------------------------------------------------------------------
# El texto de una nota
# ---------------------------------------------------------------------------

def dumps(disp: Dispositivo) -> str:
    """La nota como texto TOML, ya releída.

    Pasa por `config_file.dumps_table` —el mismo serializador que escribe el
    config— y se vuelve a parsear antes de devolverla, por lo mismo que
    `dumps_checked`: más vale no publicar nada que publicar algo que no se relee
    igual."""
    tabla = {"id": disp.id, "nombre": disp.nombre, "version": disp.version,
             "plataformas": list(disp.plataformas),
             "last_seen": disp.last_seen, "last_result": disp.last_result}
    texto = CABECERA + config_file.dumps_table(tabla) + "\n"
    if parse(texto) != disp:
        raise model.ConfigError("La nota generada no se relee igual. No se publica.")
    return texto


def parse(texto: str, device_id: str = "") -> Dispositivo | None:
    """Una nota leída del remoto. None si no hay nada aprovechable.

    Tolerante a propósito: la escribió OTRO dispositivo, puede ser de una versión
    más nueva con campos que aquí no existen, o haberse quedado a medias. Lo que
    no se entienda se ignora; lo que falte, se enseña vacío."""
    try:
        datos = tomllib.loads(texto)
    except (tomllib.TOMLDecodeError, ValueError):
        return None
    if not isinstance(datos, dict):
        return None

    def cadena(clave: str) -> str:
        valor = datos.get(clave)
        return str(valor) if isinstance(valor, (str, int, float)) else ""

    identificador = cadena("id") or device_id
    if not identificador:
        return None
    plataformas = datos.get("plataformas")
    if not isinstance(plataformas, (list, tuple)):
        plataformas = []
    return Dispositivo(
        id=identificador,
        nombre=cadena("nombre") or identificador[:8],
        version=cadena("version") or "desconocida",
        plataformas=tuple(str(p) for p in plataformas),
        last_seen=cadena("last_seen"),
        last_result=cadena("last_result") or "desconocido")


# ---------------------------------------------------------------------------
# Quién es ESTE dispositivo
# ---------------------------------------------------------------------------

def ruta_estado() -> Path:
    """Lo que este dispositivo recuerda de su propia nota: cómo se llama y qué
    publicó la última vez. Función y no constante, como en `results.py`: los
    tests reapuntan `model.STATE_DIR` en caliente."""
    return model.STATE_DIR / "fleet.json"


def _estado(state_dir: Path | str | None) -> Path:
    return (Path(state_dir) / "fleet.json") if state_dir is not None else ruta_estado()


def control_file(app_dir: Path | str | None = None) -> Path:
    """El PRDRIVE de dentro de la carpeta del programa.

    Se repite aquí la ruta en vez de importarla de `install/device.py` porque
    `install/` no viaja al dispositivo. Es la tercera copia (con la de
    `penwatch.py`), y como las otras dos, con un test que las mantiene juntas."""
    return Path(app_dir or model.APP_DIR) / APP_NAME.upper()


def device_id(app_dir: Path | str | None = None) -> str:
    """El id del fichero de control, o '' si no hay ninguno que leer."""
    try:
        texto = control_file(app_dir).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for linea in texto.splitlines():
        if linea.strip().lower().startswith("id="):
            return linea.strip()[3:].strip()
    return ""


def nombre_por_defecto() -> str:
    """El nombre del equipo que lo aprovisiona. Es un punto de partida
    reconocible, y lo primero que invita a cambiar por «el pendrive azul»."""
    try:
        return socket.gethostname() or APP_NAME
    except OSError:
        return APP_NAME


def nombre(state_dir: Path | str | None = None) -> str:
    """Cómo se llama este dispositivo en la flota.

    `state_dir` es para el instalador, que pregunta por un dispositivo que no es
    aquel desde el que corre."""
    guardado = store.read_json(_estado(state_dir)).get("nombre")
    if isinstance(guardado, str) and guardado.strip():
        return guardado.strip()
    return nombre_por_defecto()


def guardar_nombre(texto: str, state_dir: Path | str | None = None) -> bool:
    """Cambiar cómo se llama este dispositivo. Devuelve si se ha podido escribir.

    Vive en `state/` y no solo en la nota del remoto porque es el dispositivo
    quien tiene que seguir sabiendo cómo se llama cuando no hay red —y porque si
    dependiera del equipo, el mismo dispositivo cambiaría de nombre al cambiar
    de ordenador."""
    destino = _estado(state_dir)
    datos = store.read_json(destino)
    datos["nombre"] = texto.strip()
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return store.write_json(destino, datos)


def plataformas_instaladas(app_dir: Path | str | None = None) -> tuple[str, ...]:
    """Para qué equipos sirve este dispositivo: donde tenga rclone, sirve.

    Se mira el rclone y no el runtime a propósito: sin rclone no sincroniza en
    ningún caso, mientras que sin runtime todavía puede tirar del Python del
    equipo (la instalación ligera)."""
    salida = []
    for plat in PLATAFORMAS:
        try:
            if components.rclone_path(app_dir, plat).is_file():
                salida.append(plat.clave)
        except OSError:
            continue
    return tuple(salida)


def resultado(config: model.Config | None) -> str:
    """Cómo acabó lo último: 'ok', o qué parejas siguen fallando."""
    if config is None:
        return RESULTADO_OK
    try:
        fallos = results.fallos(config)
    except Exception:                                    # noqa: BLE001
        return "desconocido"
    if not fallos:
        return RESULTADO_OK
    return "fallo en " + ", ".join(f.pareja for f in fallos)


def nota_de(app_dir: Path | str | None, como_se_llama: str,
            version: str, last_result: str) -> Dispositivo | None:
    """La nota de un dispositivo cualquiera: el id y las plataformas salen de él.

    Con `app_dir` se describe uno que no es este, que es lo que necesita el
    instalador: acaba de sembrarlo y todavía no puede ejecutar nada suyo."""
    identificador = device_id(app_dir)
    if not identificador:
        return None            # sin fichero de control no hay a quién apuntar
    return Dispositivo(id=identificador, nombre=como_se_llama,
                       version=version or "desconocida",
                       plataformas=plataformas_instaladas(app_dir),
                       last_seen=store.stamp(), last_result=last_result)


def nota(config: model.Config | None = None) -> Dispositivo | None:
    """La nota de ESTE dispositivo, ahora mismo. None si no tiene id."""
    return nota_de(None, nombre(), update.installed_version(), resultado(config))


# ---------------------------------------------------------------------------
# Publicar
# ---------------------------------------------------------------------------

def _sin_fecha(disp: Dispositivo) -> tuple:
    """La nota sin lo que cambia en cada pasada: con lo que se decide si hay algo
    nuevo que contar o solo estamos diciendo la hora."""
    return (disp.id, disp.nombre, disp.version, disp.plataformas, disp.last_result)


def hace_falta_publicar(disp: Dispositivo, ahora: datetime | None = None) -> bool:
    """¿Vale la pena subir esta nota?

    Sí si ha cambiado algo de fondo (la versión, el nombre, las plataformas, el
    último resultado) y sí si la última que se subió ya tiene horas. Lo que se
    evita es el caso tonto: cuatro parejas por ciclo repitiendo la misma nota."""
    anterior = store.read_json(ruta_estado()).get("publicado")
    if not isinstance(anterior, dict):
        return True
    previa = parse(CABECERA + config_file.dumps_table(anterior) + "\n")
    if previa is None or _sin_fecha(previa) != _sin_fecha(disp):
        return True
    momento = previa.visto()
    if momento is None:
        return True
    return (ahora or datetime.now()) - momento > timedelta(hours=HORAS_ENTRE_NOTAS)


def recordar(disp: Dispositivo, state_dir: Path | str | None = None) -> None:
    """Deja apuntado en el dispositivo lo último que se publicó de él.

    Es lo que lee `hace_falta_publicar()`, y por eso lo escribe también el
    instalador: sin esto, el dispositivo recién hecho volvería a publicar la
    misma nota en su primera pasada."""
    datos = store.read_json(_estado(state_dir))
    datos["nombre"] = disp.nombre
    datos["publicado"] = {"id": disp.id, "nombre": disp.nombre,
                          "version": disp.version,
                          "plataformas": list(disp.plataformas),
                          "last_seen": disp.last_seen,
                          "last_result": disp.last_result}
    store.write_json(_estado(state_dir), datos)


def subir(texto: str, destino: str) -> bool:
    """Deja el texto en esa ruta del remoto. True si se ha podido.

    Se escribe desde un temporal del sistema y no desde el dispositivo: puede
    estar de solo lectura, y esto no es asunto suyo. `catalog.run()` es el único
    punto por el que este módulo habla con el remoto, y es el que los tests
    sustituyen."""
    tmpdir = Path(tempfile.mkdtemp(prefix="prdrive-fleet-"))
    try:
        tmp = tmpdir / "nota.toml"
        tmp.write_text(texto, encoding="utf-8", newline="\n")
        return catalog.run(["copyto", str(tmp), destino]).returncode == 0
    except Exception:                                    # noqa: BLE001
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def publicar(config: model.Config | None = None,
             raw_local: Mapping[str, Any] | None = None,
             forzar: bool = False) -> bool:
    """Deja constancia de que este dispositivo está vivo. Nunca lanza.

    La llama `sync.py` al terminar, haya ido bien o mal: `last_result` existe
    justo para eso, y una flota en la que todo el mundo dice 'ok' no sirve para
    encontrar el dispositivo que lleva semanas fallando. Que falle —no hay red,
    el remoto no contesta, el dispositivo va de solo lectura— no tiene
    consecuencias: es una nota, no la sincronización."""
    try:
        disp = nota(config)
        if disp is None:
            return False
        if not forzar and not hace_falta_publicar(disp):
            return False
        texto = dumps(disp)
    except Exception:                                    # noqa: BLE001
        return False
    if not subir(texto, fichero(endpoint_catalogo(raw_local), disp.id)):
        return False
    try:
        recordar(disp)
    except Exception:                                    # noqa: BLE001
        pass
    return True


# ---------------------------------------------------------------------------
# Leer la flota
# ---------------------------------------------------------------------------

def leer(raw_local: Mapping[str, Any] | None = None
         ) -> tuple[list[Dispositivo], str | None]:
    """Todos los dispositivos que hayan dejado nota, y qué decir si algo falló.

    Se trae la carpeta entera de una vez (`rclone copy`) en vez de listar y
    después leer uno por uno: con SFTP, cada invocación es una conexión nueva, y
    esto lo abre la ventana con el usuario esperando.

    Nunca lanza: sin remoto se devuelve la lista vacía y el motivo, y la ventana
    lo enseña como lo que es."""
    donde = carpeta(raw_local)
    tmpdir = Path(tempfile.mkdtemp(prefix="prdrive-flota-"))
    try:
        res = catalog.run(["copy", donde, str(tmpdir), "--include", "*" + SUFIJO])
        if res.returncode != 0:
            return [], (f"No se ha podido leer la flota en {donde}: "
                        f"{(res.stderr or '').strip()}")
        encontrados = []
        for archivo in sorted(tmpdir.glob("*" + SUFIJO)):
            try:
                texto = archivo.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            disp = parse(texto, archivo.stem)
            if disp is not None:
                encontrados.append(disp)
        return ordenar(encontrados), None
    except Exception as e:                               # noqa: BLE001
        return [], f"No se ha podido leer la flota en {donde}: {e}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def ordenar(dispositivos: list[Dispositivo]) -> list[Dispositivo]:
    """Los vistos hace poco primero: el orden en el que se mira una lista así es
    'qué está al día' y, al final, 'qué llevo meses sin tocar'."""
    return sorted(dispositivos,
                  key=lambda d: (d.last_seen or "", d.nombre.lower()), reverse=True)
