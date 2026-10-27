#!/usr/bin/env python3
"""Lo que prdrive lanza o registra desde `.prdrive/keepassxc/` es el KeePassXC oficial.

La carpeta `keepassxc/` no entra en la huella del agente (`agente.huella()`):
su configuración cambia con el uso y leerla entera cuesta segundos. A cambio,
cada ejecutable de la unidad se comprueba contra el SHA-256 de
`pins.KEEPASSXC_EJECUTABLES` justo antes de lanzarlo o de registrarlo
(`keepassxc.comprobar()`). Sin ficheros de verdad ni lanzar nada: son ficheros
de mentira cuya suma se pone en la tabla, y `lanzar()`, `ejecutar_cli()`,
`sonda_cli()` y el registro apuntan lo que se les pide. Lo que se sujeta:
- La tabla: la versión fijada, los tres ejecutables de Windows y el AppImage de
  Linux con la suma del pin del paquete (no repetida).
- La tabla del árbol (`common/keepassxc_arbol.json`): cada versión con Windows
  en `pins.KEEPASSXC_EJECUTABLES` tiene su árbol, y sus ejecutables dan las sumas
  de los pines.
- `comprobar()`: pasa el de la tabla; no pasa uno cambiado, uno sin sello, una
  versión que no está en la tabla ni un nombre que no está; lo que se dice sale
  en español y dice cómo seguir; el fichero se lee entero cada vez, sin caché.
- El árbol (con `components.keepassxc_arbol` sustituido por uno de mentira): pasa
  un paquete con su sello y lo que el navegador y la CLI dejan en `config/`; no
  pasa un fichero añadido (una DLL junto al exe, un `qt.conf`, un plugin), uno
  con otro tamaño, uno que falta, uno en `config/sub/`, un enlace ni un fichero
  pequeño cambiado con el mismo tamaño; una versión sin árbol no pasa y no se
  apunta.
- `abrir_navegador()` escribe el JSON de cada clave, con el proxy comprobado,
  antes de la clave; sin JSON no hay clave.
- Ningún camino lanza ni registra lo que no cuadra: la ventana (KeePassXC y su
  proxy, que KeePassXC registra por su cuenta), el registro del navegador, la
  CLI de «Combinar», la de «dejar sin contraseña» y la sonda de la llave. Y
  con el KeePassXC del equipo (Linux ARM64) no se comprueba nada.
- Una guarda estática: ninguna función de `common/keepassxc.py` que lance o
  registre algo lo hace sin pasar por la comprobación.
"""

import ast
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
from pathlib import Path

from _harness import REAL_COMPROBAR, REPO, Checks, sandbox

from common import components, keepassxc, model, pins, registro

c = Checks("KeePassXC oficial antes de lanzarlo (common/keepassxc.py, common/pins.py)")

# --- la tabla
V = pins.KEEPASSXC_VERSION
tabla = pins.KEEPASSXC_EJECUTABLES
c("la tabla lleva la versión fijada", V in tabla, True)
c("  en Windows, los tres ejecutables que prdrive lanza o registra",
  sorted(tabla[V]["windows-x64"]),
  sorted([components.KEEPASSXC_EXE, keepassxc.CLI, keepassxc.PROXY]))
c("  cada uno con un SHA-256 de 64 cifras hexadecimales en minúsculas",
  all(re.fullmatch(r"[0-9a-f]{64}", s) for s in tabla[V]["windows-x64"].values()), True)
c("  y en Linux el AppImage, con la suma del pin del paquete (no repetida)",
  tabla[V]["linux-x64"], {components.KEEPASSXC_APPIMAGE: pins.KEEPASSXC["linux-x64"][1]})
c("  solo de paquetes que prdrive instala (Linux ARM64 usa el del equipo)",
  all(paquete in pins.KEEPASSXC for porversion in tabla.values() for paquete in porversion),
  True)

ANTERIOR = "2.7.12"
fila_vieja = tabla.get(ANTERIOR, {})
c("la fila de la versión anterior (2.7.12) se queda, con sus tres sumas de Windows",
  (V != ANTERIOR, sorted(fila_vieja.get("windows-x64", {})),
   all(len(s) == 64 for s in fila_vieja.get("windows-x64", {}).values())),
  (True, sorted(["KeePassXC.exe", "keepassxc-cli.exe", "keepassxc-proxy.exe"]), True))
suma_linux = fila_vieja.get("linux-x64", {}).get(components.KEEPASSXC_APPIMAGE, "")
c("  y la de Linux, una suma literal de 64 cifras distinta de la del pin actual",
  (len(suma_linux) == 64 and all(h in "0123456789abcdef" for h in suma_linux),
   suma_linux != pins.KEEPASSXC["linux-x64"][1]), (True, True))

# --- la tabla del árbol, sobre los datos de verdad
arboles_ok, sumas_ok = [], []
for version, porpaquete in sorted(tabla.items()):
    if "windows-x64" not in porpaquete:
        continue
    arbol_real = components.keepassxc_arbol(version, "windows-x64")
    arboles_ok.append((version, arbol_real is not None))
    sumas_ok.append((version, {n: (arbol_real or {}).get(n, (0, ""))[1]
                               for n in porpaquete["windows-x64"]} == porpaquete["windows-x64"]))
c("cada versión con Windows en KEEPASSXC_EJECUTABLES tiene árbol en common/keepassxc_arbol.json "
  "(si falla: python generar_arbol_keepassxc.py)", all(ok for _, ok in arboles_ok), True)
c("  y sus tres ejecutables dan las sumas de KEEPASSXC_EJECUTABLES",
  all(ok for _, ok in sumas_ok) and bool(sumas_ok), True)
c("  la versión fijada tiene árbol", components.keepassxc_arbol(V, "windows-x64") is not None,
  True)
c("  con el .portable y un .qm pequeño del ZIP (los pequeños se resumen)",
  [n in (components.keepassxc_arbol(V, "windows-x64") or {})
   for n in (".portable", "translations/qt_en.qm")],
  [True, True])
c("  y el AppImage de Linux no tiene árbol: se copia y se comprueba entero en el equipo",
  (components.keepassxc_usa_arbol("linux-x64"), components.keepassxc_usa_arbol("windows-x64")),
  (False, True))

# --- comprobar(): el árbol y el resumen de cada fichero contra la tabla
keepassxc.comprobar = REAL_COMPROBAR
reales = (pins.KEEPASSXC_EJECUTABLES, keepassxc.paquete_del_equipo, keepassxc.lanzar,
          keepassxc.ejecutar_cli, keepassxc.sonda_cli, keepassxc.version_del_equipo,
          registro.escribir, model.APP_DIR, components.keepassxc_arbol)
ARBOLES: dict[str, dict] = {}
"""Los árboles de mentira por versión; `components.keepassxc_arbol` los da."""


def suma(datos: bytes) -> str:
    """Devuelve el SHA-256 de esos bytes."""
    return hashlib.sha256(datos).hexdigest()


def veredicto(ruta: Path, paquete: str = "windows-x64") -> str | None:
    """Devuelve lo que dice `comprobar()` al rechazar ese fichero, o `None` si lo da por bueno."""
    try:
        keepassxc.comprobar(ruta, paquete)
    except keepassxc.NoOficial as e:
        return str(e)
    return None


class Proc:
    """Un KeePassXC de mentira que sale enseguida con 0, como el que le pasa la base al abierto."""

    def poll(self):
        """Devuelve su código de salida."""
        return 0


try:
    with sandbox() as root:
        model.APP_DIR = root / ".prdrive"
        keepassxc.paquete_del_equipo = lambda: "windows-x64"
        pkg = components.keepassxc_dir(model.APP_DIR, "windows-x64")
        pkg.mkdir(parents=True)
        RELLENO = b"\0" * (components.KEEPASSXC_RESUMIR_HASTA + 1)
        """Para que los ejecutables de mentira, como los de verdad, solo los resuma su suma."""
        CONTENIDO = {components.KEEPASSXC_EXE: b"MZ el programa" + RELLENO,
                     keepassxc.CLI: b"MZ la cli" + RELLENO,
                     keepassxc.PROXY: b"MZ el proxy" + RELLENO}
        OTRA_CLI = b"MZ la cLI" + RELLENO
        """La CLI cambiada con el mismo tamaño: el árbol la deja pasar y su suma no."""
        RESTO = {".portable": b"", "Qt5Core.dll": b"MZ qt core",
                 "plugins/imageformats/qjpeg.dll": b"MZ jpeg",
                 "share/docs/guia.html": b"<html>" + b"x" * 5000}
        """Lo demás del paquete de mentira: lo que el árbol mide y la tabla de pines no fija."""
        for nombre, datos in {**CONTENIDO, **RESTO}.items():
            (pkg / nombre).parent.mkdir(parents=True, exist_ok=True)
            (pkg / nombre).write_bytes(datos)

        def arbol_de(ficheros: dict[str, bytes]) -> dict[str, tuple[int, str]]:
            """Devuelve el árbol de esos ficheros, como lo daría `keepassxc_arbol()`."""
            return {n: (len(d), suma(d)) for n, d in ficheros.items()}

        components.keepassxc_arbol = lambda version, paquete: (
            ARBOLES.get(version) if paquete == "windows-x64" else None)

        def sellar(version: str | None) -> None:
            """Pone (o quita) el sello del paquete con esa versión."""
            sello = pkg / components.KEEPASSXC_STAMP
            if version is None:
                sello.unlink(missing_ok=True)
                return
            sello.write_text(components.keepassxc_stamp_text(
                version, "KeePassXC-x-Win64.zip", "0" * 64, {}), encoding="utf-8")

        def fijar(version: str, **cambios: bytes) -> None:
            """Pone en la tabla lo que debería haber, con los `cambios` por nombre."""
            ficheros = {**CONTENIDO, **cambios}
            pins.KEEPASSXC_EJECUTABLES = {version: {"windows-x64": {
                n: suma(d) for n, d in ficheros.items()}}}
            ARBOLES.clear()
            ARBOLES[version] = arbol_de({**CONTENIDO, **RESTO})

        sellar("9.9.9")
        fijar("9.9.9")
        exe, cli, proxy = (pkg / n for n in (components.KEEPASSXC_EXE, keepassxc.CLI,
                                             keepassxc.PROXY))
        c("uno con el SHA-256 de la tabla se da por bueno",
          [veredicto(f) for f in (exe, cli, proxy)], [None, None, None])
        cli.write_bytes(OTRA_CLI)
        malo = veredicto(cli)
        c("uno cambiado no", malo is not None, True)
        c.contains("  y se dice en español que no es el oficial", malo or "",
                   "El KeePassXC de la unidad no es el oficial")
        c.contains("  con cuál ha sido", malo or "", keepassxc.CLI)
        c.contains("  y cómo seguir: «Actualizar…», que lo vuelve a poner", malo or "",
                   "«Actualizar…»")
        c("  sin pedir que se borre nada ni nombrar la carpeta",
          ("Borra" in (malo or ""), str(pkg) in (malo or "")), (False, False))
        c("  y deja apuntado en state/ que el paquete no cuadra, para que la ventana ofrezca "
          "«Actualizar…» sin resumir nada al pintarse",
          components.keepassxc_alterado(None, "windows-x64"),
          {"version": "9.9.9", "fichero": keepassxc.CLI})
        c("  y uno cambiado no hace daño a los demás", veredicto(exe), None)
        cli.write_bytes(CONTENIDO[keepassxc.CLI])
        components.keepassxc_olvidar_alterado(None, "windows-x64")

        sellar("9.9.8")
        sin_pin = veredicto(exe)
        c("una versión que no está en la tabla no se lanza", sin_pin is not None, True)
        c.contains("  y se dice cuál", sin_pin or "", "9.9.8")
        c.contains("  y que «Actualizar…» pone el oficial", sin_pin or "", "«Actualizar…»")
        sellar(None)
        sin_sello = veredicto(exe)
        c("sin sello, tampoco", sin_sello is not None, True)
        c.contains("  y se dice", sin_sello or "", "sello")
        c("  y ni lo uno ni lo otro se apunta: la versión ya dice que toca «Actualizar…»",
          components.keepassxc_alterado(None, "windows-x64"), {})
        sellar("9.9.9")
        (pkg / "otro.exe").write_bytes(b"MZ otro")
        c("un fichero que la tabla no nombra tampoco", veredicto(pkg / "otro.exe") is not None,
          True)
        (pkg / "otro.exe").unlink()
        c("un paquete que no es de la tabla tampoco",
          veredicto(exe, "windows-arm64") is not None, True)
        c("  y esos tampoco se apuntan: no son un fichero cambiado",
          components.keepassxc_alterado(None, "windows-x64"), {})
        pins.KEEPASSXC_EJECUTABLES["9.9.9"]["windows-x64"]["falta.exe"] = suma(b"x")
        falta = veredicto(pkg / "falta.exe")
        c("uno que la tabla nombra y no se puede leer se dice, no se da por bueno",
          falta is not None, True)
        c.contains("  con el motivo", falta or "", "no se ha podido leer")
        c.contains("  y que «Actualizar…» lo repone", falta or "", "«Actualizar…»")
        c("  y se apunta como uno que no cuadra, porque `al_dia()` también lo contaría",
          components.keepassxc_alterado(None, "windows-x64"),
          {"version": "9.9.9", "fichero": "falta.exe"})
        components.keepassxc_olvidar_alterado(None, "windows-x64")

        # apuntarlo es un favor a la ventana: si no se puede, el aviso sale igual
        estado_bueno = model.STATE_DIR
        model.STATE_DIR = root / "estado-roto"
        model.STATE_DIR.write_text("no soy una carpeta", encoding="utf-8")
        cli.write_bytes(OTRA_CLI)
        c.contains("si no se puede escribir state/, se dice igual que no es el oficial",
                   veredicto(cli) or "", "no es el oficial")
        model.STATE_DIR = estado_bueno
        cli.write_bytes(CONTENIDO[keepassxc.CLI])
        c("  y no deja nada apuntado", components.keepassxc_alterado(None, "windows-x64"), {})

        # sin caché: el fichero se lee entero cada vez (en FAT/exFAT el mtime se pone a mano)
        leidos: list[Path] = []
        resumen_real = keepassxc._resumen

        def contando(ruta: Path) -> str:
            """Apunta qué fichero se lee entero."""
            leidos.append(Path(ruta))
            return resumen_real(ruta)

        keepassxc._resumen = contando
        try:
            veredicto(exe)
            veredicto(exe)
            c("el mismo fichero, sin cambios, se lee cada vez", leidos, [exe, exe])
            antes = exe.stat()
            exe.write_bytes(b"MZ el progrXma" + RELLENO)   # mismo tamaño, otros bytes
            os.utime(exe, ns=(antes.st_atime_ns, antes.st_mtime_ns))
            c("  y uno cambiado con el mismo tamaño y el mtime de antes no pasa",
              (veredicto(exe) is not None, len(leidos)), (True, 3))
            exe.write_bytes(CONTENIDO[components.KEEPASSXC_EXE])
            c("  y vuelto a poner, pasa", veredicto(exe), None)
        finally:
            keepassxc._resumen = resumen_real
        components.keepassxc_olvidar_alterado(None, "windows-x64")

        # --- el árbol: la forma de la carpeta entera, antes de resumir nada
        def apunte() -> dict:
            """Devuelve lo apuntado del paquete en `state/`."""
            return components.keepassxc_alterado(None, "windows-x64")

        config_pkg = pkg / "config"
        config_pkg.mkdir()
        (config_pkg / "org.keepassxc.keepassxc_browser_chrome.json").write_text("{}")
        (config_pkg / "keepassxc.ini").write_text("[General]\n")
        c("pasa un paquete que cuadra, con su sello, los JSON del navegador y el .ini de la CLI "
          "en config/", [veredicto(f) for f in (exe, cli, proxy)], [None, None, None])
        shutil.rmtree(config_pkg)

        def rechazado(que: str, poner, quitar, fichero: str) -> None:
            """Comprueba que con `poner()` hecho no pasa, se apunta `fichero` y nada se lanza."""
            components.keepassxc_olvidar_alterado(None, "windows-x64")
            poner()
            try:
                mensaje = veredicto(exe)
                c(f"no pasa con {que}", mensaje is not None, True)
                c.contains("  y dice cuál", mensaje or "", fichero)
                c(f"  y lo apunta para «Actualizar…»", apunte(),
                  {"version": "9.9.9", "fichero": fichero})
            finally:
                quitar()
            components.keepassxc_olvidar_alterado(None, "windows-x64")

        def anadir(rel: str, datos: bytes = b"MZ"):
            """Devuelve el par `(poner, quitar)` de un fichero añadido al paquete."""
            ruta = pkg / rel

            def poner():
                ruta.parent.mkdir(parents=True, exist_ok=True)
                ruta.write_bytes(datos)
            return poner, lambda: ruta.unlink()

        rechazado("un VCRUNTIME140.dll añadido junto al exe (K3)", *anadir("VCRUNTIME140.dll"),
                  "VCRUNTIME140.dll")
        rechazado("un qt.conf añadido", *anadir("qt.conf", b"[Paths]\nPrefix=E:/x\n"),
                  "qt.conf")
        rechazado("un plugin añadido en imageformats/", *anadir("plugins/imageformats/x.dll"),
                  "plugins/imageformats/x.dll")
        rechazado("un fichero en config/sub/ (solo se admite lo de config/ mismo)",
                  *anadir("config/sub/x.dll"), "config/sub/x.dll")
        shutil.rmtree(pkg / "config")
        core = pkg / "Qt5Core.dll"
        rechazado("una DLL de la tabla con otro tamaño",
                  lambda: core.write_bytes(b"MZ qt core, otro"),
                  lambda: core.write_bytes(RESTO["Qt5Core.dll"]), "Qt5Core.dll")
        rechazado("una DLL de la tabla que falta", core.unlink,
                  lambda: core.write_bytes(RESTO["Qt5Core.dll"]), "Qt5Core.dll")
        otra = pkg / "QT5CORE.DLL"
        if otra.exists():
            print("  (saltado) mayúsculas: este sistema de ficheros no las distingue")
        else:
            core.rename(otra)
            c("las rutas se comparan sin mayúsculas, como en Windows", veredicto(exe), None)
            otra.rename(core)
            rechazado("dos ficheros que solo se distinguen en mayúsculas",
                      *anadir("QT5CORE.DLL", RESTO["Qt5Core.dll"]), "Qt5Core.dll")
        guia = pkg / "share/docs/guia.html"
        guia.write_bytes(b"<html>" + b"y" * 5000)
        c("un fichero grande que no es ejecutable, cambiado con el mismo tamaño, pasa (es lo "
          "aceptado)", veredicto(exe), None)
        guia.write_bytes(RESTO["share/docs/guia.html"])
        ARBOLES["9.9.9"]["qt.conf"] = (len(b"[Platforms]\n"), suma(b"[Platforms]\n"))
        qtconf = pkg / "qt.conf"
        qtconf.write_bytes(b"[Platforms]\n")
        c("un fichero pequeño del árbol (qt.conf) que es el oficial pasa", veredicto(exe), None)
        rechazado("un qt.conf del árbol cambiado con el mismo tamaño: los pequeños se resumen",
                  lambda: qtconf.write_bytes(b"[Paths]\nP=E\n"),
                  lambda: qtconf.write_bytes(b"[Platforms]\n"), "qt.conf")
        del ARBOLES["9.9.9"]["qt.conf"]
        qtconf.unlink()
        enlace = pkg / "enlace.dll"
        try:
            enlace.symlink_to(core)
        except (OSError, NotImplementedError):
            print("  (saltado) un enlace simbólico: aquí no se pueden crear")
        else:
            enlace.unlink()
            rechazado("un enlace simbólico", lambda: enlace.symlink_to(core), enlace.unlink,
                      "enlace.dll")
        c("con todo en su sitio vuelve a pasar", veredicto(exe), None)
        fuera = root / "fuera" / components.KEEPASSXC_EXE
        fuera.parent.mkdir()
        fuera.write_bytes(CONTENIDO[components.KEEPASSXC_EXE])
        c.contains("un ejecutable igual pero fuera de la carpeta de su paquete no pasa",
                   veredicto(fuera) or "", "no está en la carpeta de su paquete")
        c("  y no se apunta: no es un fichero cambiado del paquete", apunte(), {})
        arbol_bueno = ARBOLES.pop("9.9.9")
        sin_arbol = veredicto(exe)
        c("una versión sin fila en el árbol no pasa", sin_arbol is not None, True)
        c.contains("  y se dice", sin_arbol or "", "lista de ficheros de la versión 9.9.9")
        c("  y no se apunta, como una versión desconocida", apunte(), {})
        ARBOLES["9.9.9"] = arbol_bueno

        # --- ningún camino lanza ni registra lo que no cuadra
        lanzadas, cli_corridas, sondas, claves = [], [], [], []
        keepassxc.lanzar = lambda orden, entorno: (lanzadas.append(orden), Proc())[1]
        keepassxc.ejecutar_cli = lambda orden: (cli_corridas.append(orden), 0)[1]
        keepassxc.sonda_cli = lambda orden, entorno: (sondas.append(orden), 0)[1]
        registro.escribir = lambda clave, valor: claves.append((clave, valor))
        base, copia, llave = (root / n for n in ("personal.kdbx", "copia.kdbx", "llave.keyx"))
        ap = keepassxc.Apertura(None, exe=exe, base=base, paquete="windows-x64")

        def intentar(accion):
            """Devuelve `('ok', resultado)` o `('no oficial', mensaje)`; lo impreso, aparte."""
            salida = io.StringIO()
            try:
                with contextlib.redirect_stdout(salida):
                    return "ok", accion()
            except keepassxc.NoOficial as e:
                return "no oficial", str(e)
            finally:
                intentar.dicho = salida.getvalue()

        def nada() -> tuple:
            """Devuelve lo que se ha lanzado, corrido, sondeado y registrado, y si se escribió config."""
            return (len(lanzadas), len(cli_corridas), len(sondas), len(claves),
                    (pkg.parent / "config").exists())

        fijar("9.9.9")
        # una configuración que pide otro proxy (en la unidad, fuera de la huella) haría
        # que KeePassXC registrara ESE programa en el navegador: se pisa en cada arranque
        configuracion = keepassxc.carpeta_config("windows-x64")
        configuracion.mkdir(parents=True)
        (configuracion / keepassxc.INI).write_text(
            "[Browser]\r\nUseCustomProxy=true\r\nCustomProxyLocation=C:/malo/proxy.exe\r\n",
            encoding="utf-8")
        veredictos, _ = intentar(lambda: keepassxc.abrir(ap))
        ini = (configuracion / keepassxc.INI).read_text(encoding="utf-8")
        c("abrir deja el proxy propio: UseCustomProxy=false aunque la configuración dijera otra cosa",
          ("UseCustomProxy=false" in ini, "UseCustomProxy=true" in ini), (True, False))
        c("abrir con todo en regla: lanza KeePassXC de la unidad",
          (veredictos, nada()[0], lanzadas[-1][0] if lanzadas else None), ("ok", 1, str(exe)))
        c("  y registra las cuatro claves del navegador y la configuración",
          (nada()[3], nada()[4]), (4, True))
        lanzadas.clear(), claves.clear()
        # (la configuración queda escrita; para ver que no se escribe nada, se quita)
        shutil.rmtree(pkg.parent / "config")

        for que, cambios in (("KeePassXC.exe", {components.KEEPASSXC_EXE: b"MZ cambiado"}),
                             ("el proxy", {keepassxc.PROXY: b"MZ cambiado"})):
            fijar("9.9.9", **cambios)
            resultado, mensaje = intentar(lambda: keepassxc.abrir(ap))
            c(f"abrir con {que} cambiado: no lanza, no registra y no escribe configuración",
              (resultado, nada()), ("no oficial", (0, 0, 0, 0, False)))
            c.contains("  y dice por qué", mensaje, "no es el oficial")
        fijar("9.9.9")
        jsons_antes = sorted(p.name for p in (pkg / "config").glob("*"))
        for que, rel in (("un VCRUNTIME140.dll añadido", "VCRUNTIME140.dll"),
                         ("un imageformats/x.dll añadido", "plugins/imageformats/x.dll")):
            (pkg / rel).write_bytes(b"MZ")
            resultado, mensaje = intentar(lambda: keepassxc.abrir(ap))
            (pkg / rel).unlink()
            c(f"abrir con {que}: no lanza, no registra y no escribe configuración",
              (resultado, nada(), sorted(p.name for p in (pkg / "config").glob("*"))),
              ("no oficial", (0, 0, 0, 0, False), jsons_antes))
            c.contains("  y dice por qué", mensaje, rel)
        components.keepassxc_olvidar_alterado(None, "windows-x64")
        fijar("9.9.9", **{keepassxc.PROXY: b"MZ cambiado"})
        shutil.rmtree(pkg / "config")
        resultado, _ = intentar(lambda: keepassxc.abrir_navegador(exe))
        c("registrar el navegador con un proxy cambiado: no escribe ninguna clave ni JSON",
          (resultado, nada()[3], (pkg / "config").exists()), ("no oficial", 0, False))
        fijar("9.9.9")

        # antes de cada clave, su JSON ya está, y nombra el proxy comprobado
        vistos_al_escribir = []

        def escribir_mirando(clave, valor):
            """Apunta la clave y lo que dice en ese momento el JSON al que apunta."""
            try:
                datos = json.loads(Path(valor).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                datos = None
            vistos_al_escribir.append((clave, datos))
            claves.append((clave, valor))

        registro.escribir = escribir_mirando
        resultado, valor = intentar(lambda: keepassxc.abrir_navegador(exe))
        c("  con el de la tabla, las cuatro", (resultado, valor, nada()[3]), ("ok", [], 4))
        c("  y al escribir cada una su JSON ya existe y nombra el proxy comprobado",
          [d.get("path") if d else None for _, d in vistos_al_escribir], [str(proxy)] * 4)
        c("  el de Mozilla con su extensión, los demás con sus orígenes",
          [("allowed_extensions" in d, "allowed_origins" in d) if d else None
           for _, d in vistos_al_escribir],
          [(False, True), (False, True), (True, False), (False, True)])
        c("  y es lo que escribiría KeePassXC (manifiesto())",
          (pkg / "config" / "org.keepassxc.keepassxc_browser_firefox.json")
          .read_text(encoding="utf-8"), keepassxc.manifiesto(proxy, mozilla=True))
        claves.clear(), vistos_al_escribir.clear()
        edge = keepassxc.json_nativo(pkg / "config", "edge")
        edge.unlink()
        edge.mkdir()                                    # ahí no se puede escribir el JSON
        resultado, valor = intentar(lambda: keepassxc.abrir_navegador(exe))
        c("un JSON que no se puede escribir deja su clave sin escribir",
          sorted(k for k, _ in claves),
          sorted(keepassxc.clave_nativa(b) for b, _ in keepassxc.NAVEGADORES
                 if b != "Software\\Microsoft\\Edge"))
        c.contains("  y lo cuenta en los fallos", " ".join(valor or []), edge.name)
        edge.rmdir()
        registro.escribir = lambda clave, valor: claves.append((clave, valor))
        claves.clear()

        for que, cambios in (("la CLI", {keepassxc.CLI: b"MZ cambiada"}), ("", {})):
            fijar("9.9.9", **cambios)
            cli_corridas.clear()
            nombre = "con " + que + " cambiada" if que else "con todo en regla"
            dicho = []
            estado, codigo = intentar(lambda: keepassxc.combinar_aqui(
                base, copia, llave, esperar=lambda texto: dicho.append(texto)))
            if que:
                c(f"«Combinar» {nombre}: no corre keepassxc-cli y sale con 2",
                  (estado, codigo, cli_corridas), ("ok", 2, []))
                c.contains("  y lo dice en la consola", intentar.dicho, "no es el oficial")
            else:
                c(f"«Combinar» {nombre}: corre la keepassxc-cli de la unidad",
                  [o[0] for o in cli_corridas], [str(cli)])
            cli_corridas.clear()
            intentar(lambda: keepassxc.convertir_aqui(
                base, llave, esperar=lambda texto: dicho.append(texto)))
            if que:
                c(f"«dejar sin contraseña» {nombre}: tampoco la corre", cli_corridas, [])
            else:
                c(f"«dejar sin contraseña» {nombre}: la corre", [o[0] for o in cli_corridas],
                  [str(cli)])
            sondas.clear()
            c(f"la sonda de la llave {nombre}",
              (keepassxc.llave_vale(base, llave), [o[0] for o in sondas]),
              (None, []) if que else (True, [str(cli)]))
        c("  (sin contar con ninguna ventana abierta por el camino)", len(lanzadas), 0)

        # con el KeePassXC del equipo (Linux ARM64) no hay nada que comprobar
        comprobadas: list = []
        keepassxc.comprobar = lambda *args, **kwargs: comprobadas.append(args)
        keepassxc.version_del_equipo = lambda externo: None
        externo = keepassxc.Externo(("/usr/bin/keepassxc",))
        abierto = keepassxc.abrir(keepassxc.Apertura(None, base=base, externo=externo))
        c("el KeePassXC del equipo se lanza sin comprobar nada (no es de la unidad)",
          (comprobadas, lanzadas[-1][0], abierto.codigo), ([], "/usr/bin/keepassxc", 0))
        keepassxc.comprobar = REAL_COMPROBAR
finally:
    (pins.KEEPASSXC_EJECUTABLES, keepassxc.paquete_del_equipo, keepassxc.lanzar,
     keepassxc.ejecutar_cli, keepassxc.sonda_cli, keepassxc.version_del_equipo,
     registro.escribir, model.APP_DIR, components.keepassxc_arbol) = reales

# --- guarda estática: lo que lanza o registra algo pasa por la comprobación
LANZA = {"lanzar", "ejecutar_cli", "sonda_cli", "extraer_appimage", "escribir"}
"""Lo que, llamado desde `common/keepassxc.py`, pone en marcha o registra algo."""
COMPRUEBA = {"comprobar", "esperado", "cli_lanzable", "_cli_listo", "preparar_appimage"}
"""Lo que garantiza la comprobación: ella misma, la suma fijada o quien las llama."""
DEL_EQUIPO = {"cerrar_navegador"}
"""Lo que registra algo que no es de la unidad.

`cerrar_navegador()` devuelve las claves del navegador al KeePassXC instalado en
el equipo, que es justo quitar lo que registró `abrir_navegador()`.
"""
arbol = ast.parse((REPO / "common" / "keepassxc.py").read_text(encoding="utf-8"))
sin_comprobar, lanzan = [], []
for nodo in ast.walk(arbol):
    if not isinstance(nodo, ast.FunctionDef):
        continue
    llamadas = {(n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", ""))
                for n in ast.walk(nodo) if isinstance(n, ast.Call)}
    if llamadas & LANZA and nodo.name not in DEL_EQUIPO:
        lanzan.append(nodo.name)
        if not llamadas & COMPRUEBA:
            sin_comprobar.append(nodo.name)
c("las funciones que lanzan o registran algo en common/keepassxc.py (si salta una nueva, "
  "que pase por comprobar())", sorted(lanzan),
  sorted(["abrir", "abrir_navegador", "combinar_aqui", "convertir_aqui", "llave_vale",
          "preparar_appimage"]))
c("  y todas pasan por la comprobación", sin_comprobar, [])

raise SystemExit(c.report())
