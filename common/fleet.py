#!/usr/bin/env python3
"""El registro de la flota: quién más lleva este mismo catálogo.

Cada dispositivo publica **un fichero propio** en una carpeta `devices/` junto
al catálogo y reescribe SOLO el suyo. No hay fichero compartido, así que nada
que dos dispositivos puedan pisarse, y por eso no hace falta la ceremonia de
`catalog.push()` (releer, comparar, dejar copia): eso protege un fichero que
gobierna borrados en toda la flota, y esto es una nota de presencia. Permite
ver un dispositivo olvidado en un cajón, con una versión vieja y sin
sincronizar desde hace meses.

Lo que se publica sirve para mirar la lista y decidir: quién es (`id`,
`nombre`), qué lleva (`version`, `plataformas`), cómo está (`last_seen`,
`last_result` y, si falla, `ultima_buena`) y dónde ha estado (`equipos`). Nada
de rutas ni de parejas.

Lo único de fuera del dispositivo que viaja es el nombre de red de los equipos
donde se ha enchufado, a propósito: sin él no hay respuesta a «¿dónde estaba el
otro pendrive?». Quien puede leer `devices/` tiene la clave del remoto y puede
leer todo lo que se sincroniza; el nombre de un equipo es mucho menos que eso.
La ventana lo dice.

`equipos` es «desde dónde ha podido publicar», no «dónde se ha enchufado»: si
la publicación falla no se apunta nada y el reintento sale solo en la pasada
siguiente, porque el equipo sigue sin ser el de la última nota. Un equipo donde
nunca hubo red no aparece, y es correcto: allí tampoco se sincronizó nada.

Se escribe desde dos sitios: `sync.py` al terminar una pasada de verdad e
`install/` al aprovisionar (con su propio rclone, porque el dispositivo aún no
tiene ninguno). Leer la flota entera es cosa de la ventana de parejas.

Como el resto de lo que lee la ventana, nada de aquí lanza: un fichero de otro
dispositivo a medias o un remoto que no contesta significan «no se sabe», no
una excepción en mitad de la pantalla.
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

SUBCARPETA = "devices"
"""Carpeta de las notas, que cuelga de la del catálogo y no de la raíz del remoto.

El catálogo ya se puede mover con `catalog_path` y el registro tiene que
seguirlo; así un remoto puede alojar dos catálogos (pruebas y el de verdad) sin
mezclar sus flotas.
"""
SUFIJO = ".toml"

DIAS_OBSOLETO = 7
"""Días a partir de los cuales un dispositivo se enseña apagado.

Una semana distingue «no lo he usado esta semana» de «esto lleva meses en un
cajón».
"""

HORAS_ENTRE_NOTAS = 6
"""Cada cuántas horas se vuelve a subir la nota aunque no haya cambiado nada.

Sin este freno un servicio con cuatro parejas y ciclo de 30 minutos subiría
ocho ficheros a la hora para decir lo mismo; con él solo se pierde precisión en
`last_seen`, muy por debajo de los siete días que la hacen significar algo.
"""

RESULTADO_OK = "ok"

MAX_EQUIPOS = 5
"""Cuántos equipos recuerda la nota.

Los últimos, que son los que contestan «¿dónde estaba?».

Con un tope la nota no crece con los años.
"""

SIN_BUENA = "ninguna"
"""Valor de `ultima_buena` si de alguna pareja que falla no consta pasada buena.

Es «ninguna que conste», no «nunca»: `results` no distingue una pareja que
jamás fue bien de un registro escrito antes de que existiera la clave `buena`.
"""

RC_SIN_CARPETA = 3
"""Código de salida con el que rclone dice «ese directorio no existe» (3).

Es el de su tabla de códigos de salida (0 bien, 1 uso, 2 error sin clasificar,
3 directorio no encontrado). Aquí no es un error: es una flota en la que aún no
ha dejado nota nadie, y enseñarla como «sin conexión» sería mentir.
"""

CABECERA = (
    f"# {APP_NAME} — nota de presencia de un dispositivo.\n"
    "# La escribe el propio dispositivo al sincronizar. No la edites a mano: se\n"
    "# reescribe entera, y el nombre se cambia en «Nombre e icono de la unidad».\n"
)
"""Cabecera de comentarios de cada nota."""


class Equipo(NamedTuple):
    """Un equipo desde el que el dispositivo ha publicado su nota.

    Args:
        nombre: `socket.gethostname()`, tal cual.
        visto: `store.stamp()`, o una cadena vacía si la nota no lo dice.
    """
    nombre: str
    visto: str


class Dispositivo(NamedTuple):
    """Un dispositivo de la flota, tal como él mismo se ha descrito.

    Args:
        id: El `id=` de su fichero de control.
        nombre: Cómo se llama.
        version: Versión del programa.
        plataformas: Claves de las plataformas para las que lleva rclone.
        last_seen: Cuándo publicó por última vez, con el formato de
            `store.stamp()`.
        last_result: `ok` o un resumen del fallo.
        equipos: Los equipos desde los que ha publicado: el más reciente
            primero, sin repetir, como mucho `MAX_EQUIPOS`.
        ultima_buena: Solo si `last_result` es un fallo: desde cuándo no consta
            una pasada buena (`store.stamp()`), o `SIN_BUENA`.
        tipo: El `tipo=` de su fichero de control: vacío en una unidad (la nota
            de siempre, sin la clave) y `model.TIPO_EQUIPO` en la raíz de un
            equipo.
        cifrado: `veracrypt` en la raíz de un equipo que vive en un contenedor;
            vacío en todo lo demás.
    """
    id: str
    nombre: str
    version: str
    plataformas: tuple[str, ...]
    last_seen: str
    last_result: str
    equipos: tuple[Equipo, ...] = ()
    ultima_buena: str = ""
    tipo: str = ""
    cifrado: str = ""

    @property
    def es_equipo(self) -> bool:
        """Indica si es la raíz de un equipo y no una unidad."""
        return self.tipo == model.TIPO_EQUIPO

    @property
    def bien(self) -> bool:
        """Indica si su última pasada acabó bien."""
        return self.last_result == RESULTADO_OK

    @property
    def ultimo_equipo(self) -> str:
        """Devuelve el equipo desde el que publicó por última vez.

        Es el primero de `equipos`, que va con el más reciente delante. Una
        cadena vacía si la nota no dice ninguno (la escribió una versión sin
        esa lista, o nadie conocía el nombre de la máquina).
        """
        return self.equipos[0].nombre if self.equipos else ""

    def visto(self) -> datetime | None:
        """Devuelve cuándo publicó por última vez, o `None` si la fecha no se lee."""
        return _momento(self.last_seen)

    def obsoleto(self, ahora: datetime | None = None) -> bool:
        """Indica si hace tanto que no se sabe de él que hay que mirarlo.

        Sin fecha legible cuenta como obsoleto: lo que se pregunta es «¿consta
        que se haya usado esta semana?», y de uno que no dice cuándo no consta.
        """
        return sello_obsoleto(self.last_seen, ahora)


def _momento(sello: str) -> datetime | None:
    """Convierte un sello de `store.stamp()` en fecha; `None` si no se lee."""
    try:
        return datetime.strptime(sello, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def sello_obsoleto(sello: str, ahora: datetime | None = None) -> bool:
    """Indica si esa fecha es de hace más de `DIAS_OBSOLETO`.

    Es la regla de `Dispositivo.obsoleto()` para cualquier fecha de una nota:
    la ventana la usa también con la de cada equipo.
    """
    momento = _momento(sello)
    if momento is None:
        return True
    return (ahora or datetime.now()) - momento > timedelta(days=DIAS_OBSOLETO)


def endpoint_catalogo(raw_local: Mapping[str, Any] | None = None) -> str:
    """Devuelve dónde está el catálogo de ESTE dispositivo.

    Sin el dict del config se lee del TOML, porque quien publica la nota es
    `sync.py`, que trabaja con un `model.Config` y no con el crudo: pedirle que
    lo cargue solo para esto sería meter el catálogo en el motor. Que no se
    pueda leer no es un problema: se cae a los valores por defecto y, como
    mucho, la nota no se sube.
    """
    if raw_local is None:
        try:
            raw_local = config_file.load_raw()
        except Exception:                                # noqa: BLE001
            raw_local = None
    return catalog.endpoint(raw_local)


def carpeta(raw_local: Mapping[str, Any] | None = None) -> str:
    """Devuelve `remote:/ruta/devices`, junto al `pairs.toml` del catálogo."""
    return carpeta_de(endpoint_catalogo(raw_local))


def carpeta_de(endpoint_catalogo: str) -> str:
    """Devuelve la carpeta de notas a partir del endpoint del catálogo.

    Es lo que tiene el instalador, donde aún no hay ningún `sync_config.toml`
    que consultar.
    """
    remoto, _, ruta = endpoint_catalogo.partition(":")
    base = ruta.rsplit("/", 1)[0] if "/" in ruta else ""
    return f"{remoto}:{base}/{SUBCARPETA}"


def fichero(endpoint_catalogo: str, device_id: str) -> str:
    """Devuelve la ruta de la nota de UN dispositivo.

    Va por su id y no por su nombre: el nombre se puede cambiar, y un fichero
    que se renombra deja el anterior ahí para siempre, contando como un
    dispositivo más.
    """
    return f"{carpeta_de(endpoint_catalogo)}/{device_id}{SUFIJO}"


def _tabla(disp: Dispositivo) -> dict[str, Any]:
    """Devuelve la nota como dict.

    Lo que se publica y lo que se recuerda haber publicado.

    Tienen que ser lo mismo o el freno compararía con otra cosa. Los equipos
    van en DOS listas paralelas y no en una lista de tablas porque
    `config_file.dumps_table()` solo escribe escalares y listas de cadenas, y
    enseñarle tablas en línea sería tocar el módulo que escribe el config y el
    catálogo. Lo que está vacío no se escribe.
    """
    tabla: dict[str, Any] = {
        "id": disp.id, "nombre": disp.nombre, "version": disp.version,
        "plataformas": list(disp.plataformas),
        "last_seen": disp.last_seen, "last_result": disp.last_result}
    if disp.equipos:
        tabla["equipos"] = [e.nombre for e in disp.equipos]
        tabla["equipos_visto"] = [e.visto for e in disp.equipos]
    if disp.ultima_buena:
        tabla["ultima_buena"] = disp.ultima_buena
    if disp.tipo:
        tabla["tipo"] = disp.tipo
    if disp.cifrado:
        tabla["cifrado"] = disp.cifrado
    return tabla


def dumps(disp: Dispositivo) -> str:
    """Devuelve la nota como texto TOML, ya releída.

    Pasa por `config_file.dumps_table` (el serializador del config) y se vuelve
    a parsear antes de devolverla, como `dumps_checked`: más vale no publicar
    nada que publicar algo que no se relee igual.

    Raises:
        model.ConfigError: Si la nota generada no se relee igual.
    """
    texto = CABECERA + config_file.dumps_table(_tabla(disp)) + "\n"
    if parse(texto) != disp:
        raise model.ConfigError("La nota generada no se relee igual. No se publica.")
    return texto


def _equipos(nombres: Any, vistos: Any) -> tuple[Equipo, ...]:
    """Empareja por posición las dos listas paralelas de una nota.

    Es tolerante como el resto de `parse()`: la puede haber escrito otra
    versión, o nadie (una nota vieja no las trae). Una entrada de `equipos` que
    no sea un nombre se descarta con su fecha; una fecha que falte o no sea
    texto queda vacía; y lo que pase del tope se corta aquí, sin fiarse de que
    quien escribió lo respetara.
    """
    if not isinstance(nombres, (list, tuple)):
        return ()
    if not isinstance(vistos, (list, tuple)):
        vistos = ()
    salida = []
    for i, nombre in enumerate(nombres):
        if not isinstance(nombre, str) or not nombre:
            continue
        visto = vistos[i] if i < len(vistos) and isinstance(vistos[i], str) else ""
        salida.append(Equipo(nombre, visto))
    return tuple(salida[:MAX_EQUIPOS])


def parse(texto: str, device_id: str = "") -> Dispositivo | None:
    """Lee una nota del remoto.

    Es tolerante a propósito: la escribió OTRO dispositivo, puede ser de una
    versión más nueva con campos que aquí no existen, o haberse quedado a
    medias. Lo que no se entienda se ignora y lo que falte se enseña vacío.

    Args:
        texto: El TOML de la nota.
        device_id: Id a usar si la nota no lo trae (el nombre del fichero).

    Returns:
        El dispositivo, o `None` si no hay nada aprovechable.
    """
    try:
        datos = tomllib.loads(texto)
    except (tomllib.TOMLDecodeError, ValueError):
        return None
    if not isinstance(datos, dict):
        return None

    def cadena(clave: str) -> str:
        """Devuelve la clave como texto, o una cadena vacía si no es escalar."""
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
        last_result=cadena("last_result") or "desconocido",
        equipos=_equipos(datos.get("equipos"), datos.get("equipos_visto")),
        ultima_buena=cadena("ultima_buena"),
        tipo=cadena("tipo").strip().lower(),
        cifrado=cadena("cifrado").strip().lower())


def ruta_estado() -> Path:
    """Devuelve `state/fleet.json`: cómo se llama este dispositivo y qué publicó.

    Es función y no constante, como en `results.py`: los tests reapuntan
    `model.STATE_DIR` en caliente.
    """
    return model.STATE_DIR / "fleet.json"


def _estado(state_dir: Path | str | None) -> Path:
    """Devuelve el `fleet.json` de `state_dir`, o el de este dispositivo si no se da."""
    return (Path(state_dir) / "fleet.json") if state_dir is not None else ruta_estado()


def control_file(app_dir: Path | str | None = None) -> Path:
    """Devuelve el fichero de control `PRDRIVE` dentro de la carpeta del programa.

    Repite la ruta en vez de importarla de `install/device.py` porque
    `install/` no viaja al dispositivo. Es la tercera copia (con la de
    `penwatch.py`) y, como las otras, un test las mantiene juntas.
    """
    return Path(app_dir or model.APP_DIR) / APP_NAME.upper()


def device_id(app_dir: Path | str | None = None) -> str:
    """Devuelve el id del fichero de control, o una cadena vacía si no hay."""
    try:
        texto = control_file(app_dir).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for linea in texto.splitlines():
        if linea.strip().lower().startswith("id="):
            return linea.strip()[3:].strip()
    return ""


def equipo_actual() -> str:
    """Devuelve el nombre de red del equipo donde está enchufado ahora.

    Es función de módulo para que los tests la sustituyan: el nombre de la
    máquina que ejecuta los tests no es algo que un test pueda afirmar.

    Returns:
        El nombre, o una cadena vacía si no se sabe.
    """
    try:
        return socket.gethostname() or ""
    except OSError:
        return ""


def nombre_por_defecto() -> str:
    """Devuelve el nombre inicial: el del equipo que aprovisiona, o `APP_NAME`.

    Es un punto de partida reconocible que invita a cambiarlo por «el pendrive
    azul».
    """
    return equipo_actual() or APP_NAME


def nombre(state_dir: Path | str | None = None) -> str:
    """Devuelve cómo se llama este dispositivo en la flota.

    Args:
        state_dir: `state/` de otro dispositivo, para el instalador, que
            pregunta por uno que no es aquel desde el que corre.
    """
    guardado = store.read_json(_estado(state_dir)).get("nombre")
    if isinstance(guardado, str) and guardado.strip():
        return guardado.strip()
    return nombre_por_defecto()


def guardar_nombre(texto: str, state_dir: Path | str | None = None) -> bool:
    """Cambia cómo se llama este dispositivo.

    Vive en `state/` y no solo en la nota del remoto porque el dispositivo
    tiene que seguir sabiendo cómo se llama sin red, y porque si dependiera del
    equipo cambiaría de nombre al cambiar de ordenador.

    No toca `publicado`: eso es lo último que SE SUBIÓ, y que ya no coincida
    con el nombre es justo lo que hace que `hace_falta_publicar()` deje pasar
    la nota nueva en la siguiente pasada. Apuntarlo ahí con `recordar()` la
    daría por subida sin haberla subido. Este es el único sitio donde se
    cambia el nombre: lo llama «Nombre e icono de la unidad» (`ui/volumen.py`)
    y, al aprovisionar, el instalador.

    Returns:
        True si se ha podido escribir.
    """
    destino = _estado(state_dir)
    datos = store.read_json(destino)
    datos["nombre"] = texto.strip()
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return store.write_json(destino, datos)


def plataformas_instaladas(app_dir: Path | str | None = None) -> tuple[str, ...]:
    """Devuelve para qué equipos sirve este dispositivo: donde tenga rclone.

    Se mira el rclone y no el runtime a propósito: sin rclone no sincroniza en
    ningún caso, mientras que sin runtime todavía puede tirar del Python del
    equipo (la instalación ligera).
    """
    salida = []
    for plat in PLATAFORMAS:
        try:
            if components.rclone_path(app_dir, plat).is_file():
                salida.append(plat.clave)
        except OSError:
            continue
    return tuple(salida)


def estado(config: model.Config | None) -> tuple[str, str]:
    """Devuelve cómo acabó lo último y, si fue mal, desde cuándo.

    Las dos cosas salen de UNA lectura de `results.fallos()`: leídas por
    separado, una pasada que terminara entre las dos lecturas las haría
    contradecirse (una nota con 'ok' y fecha de última buena, o un fallo sin
    ella). La fecha es la pasada buena MÁS ANTIGUA de las parejas que fallan,
    porque se pregunta desde cuándo hay algo roto; si de alguna no consta
    ninguna, se dice (`SIN_BUENA`) en vez de callarlo tras la fecha de otra.

    Returns:
        `(last_result, ultima_buena)`.
    """
    if config is None:
        return RESULTADO_OK, ""
    try:
        fallos = results.fallos(config)
    except Exception:                                    # noqa: BLE001
        return "desconocido", ""
    if not fallos:
        return RESULTADO_OK, ""
    last_result = "fallo en " + ", ".join(f.pareja for f in fallos)
    buenas = [f.buena for f in fallos]
    if not all(buenas):
        return last_result, SIN_BUENA
    # `store.stamp()` se ordena como texto: año, mes, día, hora.
    return last_result, min(buenas)


def _estado_de(app_dir: Path | str | None) -> Path:
    """Devuelve el `fleet.json` de ese dispositivo: el de este o el de otro.

    `<app_dir>/state/` guarda con `app_dir` la misma relación que
    `model.STATE_DIR` con `model.APP_DIR`.
    """
    return _estado(Path(app_dir) / "state" if app_dir is not None else None)


def _equipos_previos(app_dir: Path | str | None,
                     identificador: str) -> tuple[Equipo, ...]:
    """Devuelve los equipos de la última nota que el dispositivo recuerda publicada.

    Solo si era de este mismo id: «Reinstalar desde cero» lo renueva y para la
    flota eso es otro dispositivo, que empieza de cero.
    """
    anterior = store.read_json(_estado_de(app_dir)).get("publicado")
    if not isinstance(anterior, dict) or anterior.get("id") != identificador:
        return ()
    return _equipos(anterior.get("equipos"), anterior.get("equipos_visto"))


def _con_equipo(previos: tuple[Equipo, ...], aqui: str,
                cuando: str) -> tuple[Equipo, ...]:
    """Devuelve la lista con el equipo de ahora delante.

    Sin repetirlo y cortada al tope.

    Sin nombre de equipo no hay nada que poner delante: la lista se queda como
    estaba.
    """
    if not aqui:
        return previos
    resto = tuple(e for e in previos if e.nombre != aqui)
    return ((Equipo(aqui, cuando),) + resto)[:MAX_EQUIPOS]


def nota_de(app_dir: Path | str | None, como_se_llama: str,
            version: str, last_result: str,
            ultima_buena: str = "") -> Dispositivo | None:
    """Devuelve la nota de un dispositivo cualquiera.

    El id y las plataformas salen de él.

    Con `app_dir` se describe uno que no es este, que es lo que necesita el
    instalador: acaba de sembrarlo y aún no puede ejecutar nada suyo. La lista
    de equipos se hereda de la última nota publicada, que el propio dispositivo
    recuerda (`recordar()`), con el equipo de ahora delante: no hace falta
    ninguna escritura más en el dispositivo y la fecha de cada equipo tiene la
    precisión de `last_seen`.

    Returns:
        La nota, o `None` si no hay fichero de control.
    """
    identificador = device_id(app_dir)
    if not identificador:
        return None            # sin fichero de control no hay a quién apuntar
    ahora = store.stamp()
    return Dispositivo(id=identificador, nombre=como_se_llama,
                       version=version or "desconocida",
                       plataformas=plataformas_instaladas(app_dir),
                       last_seen=ahora, last_result=last_result,
                       equipos=_con_equipo(_equipos_previos(app_dir, identificador),
                                           equipo_actual(), ahora),
                       ultima_buena=ultima_buena,
                       tipo="" if not model.es_equipo(app_dir) else model.TIPO_EQUIPO,
                       cifrado=_cifrado(app_dir, identificador))


CIFRADO_VERACRYPT = "veracrypt"
"""Valor de `cifrado` de la raíz de un equipo que vive en un contenedor VeraCrypt."""


def _cifrado(app_dir: Path | str | None, identificador: str) -> str:
    """Devuelve `veracrypt` si es una raíz de equipo que su agente tiene cifrada.

    Se pregunta a `agente.json` y no a las unidades porque es un fichero del
    equipo y la nota se escribe tras cada pasada. Una unidad cifrada no lo dice
    (no hace falta: se reconoce por su vestíbulo).
    """
    if not model.es_equipo(app_dir):
        return ""
    try:
        from . import equipo
        unidad = equipo.leer_ajustes().unidades.get(identificador)
    except Exception:                                   # noqa: BLE001
        return ""
    return CIFRADO_VERACRYPT if unidad is not None and unidad.cifrada else ""


def nota(config: model.Config | None = None) -> Dispositivo | None:
    """Devuelve la nota de ESTE dispositivo ahora mismo, o `None` si no tiene id."""
    last_result, ultima_buena = estado(config)
    return nota_de(None, nombre(), update.installed_version(), last_result,
                   ultima_buena)


def _sin_fecha(disp: Dispositivo) -> tuple:
    """Devuelve la nota sin lo que cambia en cada pasada.

    Con ello se decide si hay algo nuevo que contar o solo se está diciendo la
    hora. Del equipo cuenta solo cuál es el de ahora (el primero de la lista),
    no sus fechas: en la misma máquina todo sigue igual (una nota cada tantas
    horas) y en otra se publica en la primera pasada, que es cuando más
    importa. `ultima_buena` solo cambia cuando cambia `last_result`, así que no
    añade notas.
    """
    return (disp.id, disp.nombre, disp.version, disp.plataformas, disp.last_result,
            disp.ultimo_equipo, disp.ultima_buena, disp.tipo, disp.cifrado)


def hace_falta_publicar(disp: Dispositivo, ahora: datetime | None = None) -> bool:
    """Indica si vale la pena subir esta nota.

    Sí si ha cambiado algo de fondo (la versión, el nombre, las plataformas, el
    último resultado, el equipo) y sí si la última subida ya tiene horas
    (`HORAS_ENTRE_NOTAS`). Lo que se evita es el caso tonto: cuatro parejas por
    ciclo repitiendo la misma nota.
    """
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
    """Apunta en el dispositivo lo último que se publicó de él.

    Es lo que lee `hace_falta_publicar()`, y por eso lo escribe también el
    instalador: sin esto el dispositivo recién hecho volvería a publicar la
    misma nota en su primera pasada.
    """
    datos = store.read_json(_estado(state_dir))
    datos["nombre"] = disp.nombre
    # Entera, equipos incluidos: de aquí hereda la lista la nota siguiente.
    datos["publicado"] = _tabla(disp)
    store.write_json(_estado(state_dir), datos)


def subir(texto: str, destino: str) -> bool:
    """Deja el texto en esa ruta del remoto.

    Se escribe desde un temporal del sistema y no desde el dispositivo, que
    puede estar de solo lectura. `catalog.run()` es el único punto por el que
    este módulo habla con el remoto y el que los tests sustituyen.

    Returns:
        True si se ha podido.
    """
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
    """Deja constancia de que este dispositivo está vivo; nunca lanza.

    La llama `sync.py` al terminar, haya ido bien o mal: `last_result` existe
    justo para eso, y una flota en la que todo el mundo dice 'ok' no sirve para
    encontrar el dispositivo que lleva semanas fallando. Que falle (sin red,
    remoto que no contesta, dispositivo de solo lectura) no tiene
    consecuencias: es una nota, no la sincronización.

    Args:
        config: El config, para saber cómo acabó lo último.
        raw_local: El config en bruto, para saber dónde está el catálogo.
        forzar: Publicar aunque `hace_falta_publicar()` diga que no.

    Returns:
        True si la nota se ha subido.
    """
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


def olvidar(quien: str, raw_local: Mapping[str, Any] | None = None) -> str | None:
    """Quita de la lista la nota de OTRO dispositivo.

    Es la única escritura de este módulo sobre el fichero de otro, y rompe la
    regla que hace innecesaria la ceremonia de `catalog.push()` (que cada uno
    toca solo el suyo). Se puede permitir porque NO destruye nada: la nota no
    es el dispositivo sino su rastro, y si el que se quita vuelve a enchufarse
    publica otra vez y reaparece con todo, porque lo de verdad vive en el
    propio dispositivo (`state/fleet.json` y el `id=` de su fichero de
    control). Por eso es «quitarlo de la lista» y no pasa por
    `confirmar_plan()`.

    El dispositivo actual no puede quitarse a sí mismo: volvería a publicarse
    en la siguiente pasada y el botón parecería roto. Es una propiedad de la
    operación y por eso está aquí y no en la ventana. El parámetro se llama
    `quien` para no tapar a `device_id()`.

    A diferencia de `publicar()` y `leer()` hay alguien esperando respuesta: no
    lanza, pero dice qué ha pasado en vez de devolver un False mudo.

    Args:
        quien: Id del dispositivo a quitar.
        raw_local: El config en bruto, para saber dónde está el catálogo.

    Returns:
        `None` si se ha podido; si no, el motivo, para enseñarlo.
    """
    if not quien:
        return "No se sabe qué dispositivo se quiere quitar de la lista."
    try:
        if quien == device_id():
            return ("Este es el dispositivo que estás usando: se volvería a "
                    "apuntar en la siguiente pasada.")
    except Exception:                                    # noqa: BLE001
        pass          # sin id propio no se puede comparar, y quitar otro es legal
    destino = fichero(endpoint_catalogo(raw_local), quien)
    try:
        res = catalog.run(["deletefile", destino])
    except Exception as e:                               # noqa: BLE001
        return f"No se ha podido quitar la nota de {destino}: {e}"
    if res.returncode == RC_SIN_CARPETA:
        return None   # ya no estaba: el resultado que se pedía, por otro camino
    if res.returncode != 0:
        return (f"No se ha podido quitar la nota de {destino}: "
                f"{(res.stderr or '').strip()}")
    return None


def leer(raw_local: Mapping[str, Any] | None = None
         ) -> tuple[list[Dispositivo], str | None]:
    """Devuelve todos los dispositivos que hayan dejado nota, y qué decir si algo falló.

    Trae la carpeta entera de una vez (`rclone copy`) en vez de listar y leer
    uno por uno: con SFTP cada invocación es una conexión nueva, y esto lo abre
    la ventana con el usuario esperando. Nunca lanza: sin remoto devuelve la
    lista vacía y el motivo, y la ventana lo enseña como lo que es.

    Returns:
        `(dispositivos, mensaje)`; el mensaje es `None` si todo fue bien.
    """
    donde = carpeta(raw_local)
    tmpdir = Path(tempfile.mkdtemp(prefix="prdrive-flota-"))
    try:
        res = catalog.run(["copy", donde, str(tmpdir), "--include", "*" + SUFIJO])
        if res.returncode == RC_SIN_CARPETA:
            return [], None
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
    """Ordena los dispositivos: los vistos hace poco, primero.

    El orden en que se mira una lista así es «qué está al día» y, al final,
    «qué llevo meses sin tocar».
    """
    return sorted(dispositivos,
                  key=lambda d: (d.last_seen or "", d.nombre.lower()), reverse=True)
