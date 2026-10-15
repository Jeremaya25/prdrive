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
- `comprobar()`: pasa el de la tabla; no pasa uno cambiado, uno sin sello, una
  versión que no está en la tabla ni un nombre que no está; lo que se dice sale
  en español y dice cómo seguir; el resultado se recuerda por ruta, tamaño y
  mtime.
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

# --- comprobar(): el resumen de cada fichero contra la tabla
keepassxc.comprobar = REAL_COMPROBAR
reales = (pins.KEEPASSXC_EJECUTABLES, keepassxc.paquete_del_equipo, keepassxc.lanzar,
          keepassxc.ejecutar_cli, keepassxc.sonda_cli, keepassxc.version_del_equipo,
          registro.escribir, model.APP_DIR)


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
        CONTENIDO = {components.KEEPASSXC_EXE: b"MZ el programa", keepassxc.CLI: b"MZ la cli",
                     keepassxc.PROXY: b"MZ el proxy"}
        for nombre, datos in CONTENIDO.items():
            (pkg / nombre).write_bytes(datos)

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
            keepassxc.RESUMENES.clear()

        sellar("9.9.9")
        fijar("9.9.9")
        exe, cli, proxy = (pkg / n for n in (components.KEEPASSXC_EXE, keepassxc.CLI,
                                             keepassxc.PROXY))
        c("uno con el SHA-256 de la tabla se da por bueno",
          [veredicto(f) for f in (exe, cli, proxy)], [None, None, None])
        keepassxc.RESUMENES.clear()
        cli.write_bytes(b"MZ otra cli")
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
        keepassxc.RESUMENES.clear()
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
        cli.write_bytes(b"MZ otra cli")
        keepassxc.RESUMENES.clear()
        c.contains("si no se puede escribir state/, se dice igual que no es el oficial",
                   veredicto(cli) or "", "no es el oficial")
        model.STATE_DIR = estado_bueno
        cli.write_bytes(CONTENIDO[keepassxc.CLI])
        keepassxc.RESUMENES.clear()
        c("  y no deja nada apuntado", components.keepassxc_alterado(None, "windows-x64"), {})

        # el resultado se recuerda mientras no cambie la ruta, el tamaño ni el mtime
        keepassxc.RESUMENES.clear()
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
            c("el mismo fichero, sin cambios, se lee una vez", leidos, [exe])
            exe.write_bytes(b"MZ el programa!")           # otro tamaño
            c("  si cambia, se vuelve a leer, y ya no cuadra",
              (veredicto(exe) is not None, leidos), (True, [exe, exe]))
            exe.write_bytes(CONTENIDO[components.KEEPASSXC_EXE])
            os.utime(exe, ns=(1, 1))                       # mismo tamaño, otro mtime
            c("  y también con el mismo tamaño y otro mtime",
              (veredicto(exe), len(leidos)), (None, 3))
        finally:
            keepassxc._resumen = resumen_real
        keepassxc.RESUMENES.clear()

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
        fijar("9.9.9", **{keepassxc.PROXY: b"MZ cambiado"})
        resultado, _ = intentar(lambda: keepassxc.abrir_navegador(exe))
        c("registrar el navegador con un proxy cambiado: no escribe ninguna clave",
          (resultado, nada()[3]), ("no oficial", 0))
        fijar("9.9.9")
        resultado, valor = intentar(lambda: keepassxc.abrir_navegador(exe))
        c("  con el de la tabla, las cuatro", (resultado, valor, nada()[3]), ("ok", [], 4))
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
     registro.escribir, model.APP_DIR) = reales

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
