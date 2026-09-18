#!/usr/bin/env python3
"""
El VeraCrypt que viaja en el dispositivo (Traveler's Disk).

Sin esto, un dispositivo cifrado con VeraCrypt solo sirve en equipos que ya lo
tengan instalado, justo lo contrario de lo que hace el resto del proyecto. Y no
hay CLI para prepararlo: el diálogo de VeraCrypt extrae los binarios de su propio
`VeraCrypt Setup.exe`. Lo que sí es exacto —y es lo que se prueba aquí— es que
`DriverLoad()` carga el `.sys` de la carpeta del ejecutable, así que copiar la
carpeta basta.

Todo sobre árboles falsos: ni se copia un VeraCrypt de verdad ni se toca ninguna
unidad. Lo que se comprueba es lo que decide —qué se copia, para qué
arquitectura, y qué se dice de ello—, más la trampa de integración que estaría
callada hasta el segundo uso del dispositivo: la carpeta nueva tiene que estar en
`device.RUIDO`.
"""

from _harness import Checks, tmpdir

from install import device, traveler

c = Checks("Traveler's Disk: VeraCrypt dentro del dispositivo")


def falso_veracrypt(driver="veracrypt-x64.sys", con_expander=True):
    """Una carpeta con la pinta de un VeraCrypt instalado."""
    carpeta = tmpdir("prdrive-vc-origen-")
    ficheros = ["VeraCrypt.exe", "VeraCrypt Format.exe", "License.txt", driver]
    if con_expander:
        ficheros.append("VeraCryptExpander.exe")
    for nombre in ficheros:
        (carpeta / nombre).write_text(nombre, encoding="utf-8")
    # Lo que NO debe viajar: el instalador pesa lo que pesa y no sirve de nada
    # en el dispositivo.
    (carpeta / "VeraCrypt Setup.exe").write_text("x", encoding="utf-8")
    return {"mount": str(carpeta / "VeraCrypt.exe"),
            "format": str(carpeta / "VeraCrypt Format.exe")}


win_original = traveler.IS_WIN
try:
    # --- 1. qué se copia, sin copiar nada -----------------------------------
    vc = falso_veracrypt()
    raiz = tmpdir("prdrive-volumen-")
    nombres = sorted(destino.name for _, destino in traveler.plan(vc, raiz))
    c("viaja el ejecutable", "VeraCrypt.exe" in nombres, True)
    c("viaja el driver, que es lo que carga desde su propia carpeta",
      "veracrypt-x64.sys" in nombres, True)
    c("viaja el Expander, que es lo que agranda el contenedor luego",
      "VeraCryptExpander.exe" in nombres, True)
    c("viaja la licencia, que estamos copiando su programa",
      "License.txt" in nombres, True)
    c("NO viaja el instalador", "VeraCrypt Setup.exe" in nombres, False)
    c("y todo va a la subcarpeta VeraCrypt/",
      {d.parent.name for _, d in traveler.plan(vc, raiz)}, {traveler.CARPETA})
    c("sin VeraCrypt de dónde copiar, no hay plan", traveler.plan(None, raiz), [])

    # --- 2. la arquitectura se lee, no se supone ----------------------------
    #
    # Un VeraCrypt instalado deja el driver de SU máquina. Suponer «x64» dejaría
    # un dispositivo que no monta en el equipo para el que se preparó.
    carpeta_origen = traveler.origen(vc)
    c("x64 se reconoce", traveler.arquitecturas(carpeta_origen), ["x64"])
    c("y arm64 también",
      traveler.arquitecturas(traveler.origen(falso_veracrypt("veracrypt-arm64.sys"))),
      ["arm64"])

    # --- 3. la copia, y que se pueda repetir para poner al día -------------
    traveler.IS_WIN = True
    escritos = traveler.instalar(vc, raiz)
    c("se ha copiado algo", len(escritos) >= 5, True)
    c("y el ejecutable está donde lo va a buscar el usuario",
      traveler.exe_portatil(raiz).is_file(), True)
    c("el volumen ya lleva VeraCrypt", traveler.instalado(raiz), True)
    # Idempotente a propósito: es también el botón «poner al día».
    traveler.instalar(vc, raiz)
    c("repetirlo no falla", traveler.instalado(raiz), True)

    pelado = falso_veracrypt()
    (traveler.origen(pelado) / "VeraCrypt.exe").unlink()
    try:
        traveler.instalar(pelado, tmpdir("prdrive-volumen-"))
        fallo = "no ha protestado"
    except Exception as e:                                   # noqa: BLE001
        fallo = type(e).__name__
    c("sin el ejecutable se protesta en vez de dejar una carpeta inútil",
      fallo, "InstallError")

    # --- 4. el autorun.inf --------------------------------------------------
    #
    # No ejecuta nada al conectar —AutoRun lleva desactivado para extraíbles
    # desde Windows 7—, pero la etiqueta y el icono sí los lee el Explorador.
    texto = traveler.autorun_texto("PRDRIVE")
    c.contains("pone nombre a la unidad", texto, "label=PRDRIVE")
    c.contains("y su icono", texto, "icon=VeraCrypt\\VeraCrypt.exe")
    c.contains("y deja desmontar desde el menú", texto, "/q /u")
    destino = traveler.write_autorun(raiz, "PRDRIVE")
    c("se escribe en la raíz física, junto al .hc", destino.parent, raiz)
    c("en UTF-16, que es lo que lee el Explorador",
      destino.read_bytes()[:2] in (b"\xff\xfe", b"\xfe\xff"), True)

    # --- 5. lo que se le cuenta al usuario ---------------------------------
    etiquetas = {chk.etiqueta: chk for chk in traveler.comprobar(raiz)}
    c("dice que lleva VeraCrypt", etiquetas["VeraCrypt portátil"].ok, True)
    c("dice para qué arquitectura",
      "x64" in etiquetas["Driver de VeraCrypt"].detalle, True)
    c("y que el x64 vale también en Windows ARM",
      "ARM" in etiquetas["Driver de VeraCrypt"].detalle, True)
    c("y que se podrá agrandar el contenedor",
      etiquetas["VeraCrypt Expander"].ok, True)

    solo_arm = tmpdir("prdrive-volumen-")
    traveler.instalar(falso_veracrypt("veracrypt-arm64.sys", con_expander=False), solo_arm)
    etiquetas = {chk.etiqueta: chk for chk in traveler.comprobar(solo_arm)}
    c("un traveler solo de ARM se avisa: no vale en un x64",
      "no servirá" in etiquetas["Driver de VeraCrypt"].detalle, True)
    c("y sin Expander se dice, no se calla",
      etiquetas["VeraCrypt Expander"].ok, False)

    vacio = tmpdir("prdrive-volumen-")
    c("y sin nada, la lista es de una fila y roja",
      [(k.etiqueta, k.ok) for k in traveler.comprobar(vacio)],
      [("VeraCrypt portátil", False)])

    # --- 6. la trampa de integración ---------------------------------------
    #
    # Con contenedor, la raíz FÍSICA lleva el .hc, el autorun.inf y ahora la
    # carpeta VeraCrypt/. Si esa carpeta no está en RUIDO, la siguiente vez que
    # se enchufe el dispositivo el asistente lo lee como «aquí hay cosas de
    # otro» y esconde el recorrido corto. Es el mismo fallo contra el que avisa
    # el comentario de `device.RUIDO`, una carpeta más tarde.
    c("la carpeta de VeraCrypt no cuenta como contenido ajeno",
      traveler.CARPETA.lower() in device.RUIDO, True)
    fisica = tmpdir("prdrive-fisica-")
    (fisica / "PRDRIVE.hc").write_text("x", encoding="utf-8")
    (fisica / traveler.CARPETA).mkdir()
    (fisica / "autorun.inf").write_text("x", encoding="utf-8")
    estado, _ = device.install_target(fisica)
    c("y la raíz de un dispositivo VeraCrypt no se lee como ajena",
      estado, device.VACIO)
finally:
    traveler.IS_WIN = win_original

raise SystemExit(c.report())
