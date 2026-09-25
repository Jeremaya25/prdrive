#!/usr/bin/env python3
"""
El nombre y el icono de la unidad: `common/autorun.py`, `ui/volumen.py` y su
ventana.

Lo que se comprueba:

  * El `autorun.inf` se EDITA, no se reescribe: cambiar `label` e `icon` deja
    intactas las órdenes del traveler de VeraCrypt, otras secciones y
    comentarios. Y se escribe como el de VeraCrypt: UTF-16 y CRLF.
  * Qué icono hay puesto se lee del propio `icon=`, sin estado aparte, y uno que
    no puso prdrive no se pierde por cambiar solo el nombre.
  * El icono va dentro de `.prdrive/` en una unidad sin cifrar o con BitLocker,
    y junto al autorun.inf, oculto, en la raíz física de un contenedor de
    VeraCrypt, que no tiene `.prdrive/`. Guardar deja un solo icono de prdrive:
    el que se usa, y se lleva también los que quedaron en la raíz. Y el nombre
    del fichero cambia con el dibujo, que es lo que evita la caché del
    Explorador.
  * El traveler, al volver a llevar VeraCrypt, respeta lo elegido.
  * Los iconos no cuentan como contenido ajeno para el asistente.
  * La ventana llama a `volumen.guardar()` con lo que dice el formulario, y
    «Ajustes» la ofrece.

Ningún test toca una unidad de verdad: todo va sobre directorios temporales.
"""

import sys
from pathlib import Path, PureWindowsPath

from _harness import Checks, sandbox, tmpdir

from common import autorun, model, store, vestibulo
from install import deploy, device, traveler
from ui import icons, volumen

c = Checks("nombre e icono de la unidad")

# Pintar la marca a 256 px son un par de segundos por color. Aquí basta con el
# formato de verdad a un tamaño: lo que se prueba es qué fichero se deja y dónde.
ICO_DE_VERDAD = icons.ico
pintados: list[str] = []


def ico_rapido(tamanos=icons.ICO_TAMANOS, campo=icons.CAMPO):
    pintados.append(campo)
    return ICO_DE_VERDAD((16,), campo)


icons.ico = ico_rapido


def utf16(ruta: Path) -> str:
    return ruta.read_bytes().decode("utf-16")


def en_disco(raiz: Path, icono: str) -> Path:
    """Dónde está el fichero de un `icon=`, que va con la barra de Windows."""
    return raiz.joinpath(*PureWindowsPath(icono).parts)


def iconos(carpeta: Path) -> list[str]:
    """Los .ico de una carpeta, por nombre."""
    return sorted(p.name for p in carpeta.iterdir() if p.suffix == ".ico")


# Dónde van los iconos en una unidad sin contenedor: `.prdrive` en un
# dispositivo; aquí, el nombre de la carpeta del checkout.
DENTRO = model.APP_DIR.name

# `store.hide()` no hace nada fuera de Windows: se apunta a quién se le pide.
HIDE_DE_VERDAD = store.hide
ocultados: list[str] = []


# --- 1. el fichero: se edita, no se reescribe ---------------------------------

# El que dejaban las versiones anteriores del traveler, con sus órdenes: es lo
# que hay en las unidades de antes, y editarlo no puede llevárselas por delante
# (las retira el traveler, que es quien las puso: `traveler.write_autorun`).
TRAVELER = ("[autorun]\nlabel=PRDRIVE\nicon=VeraCrypt\\VeraCrypt.exe\n"
            "action=Montar el volumen PRDRIVE\n"
            "shell\\montar=Montar el volumen PRDRIVE\n"
            'shell\\montar\\command=VeraCrypt\\VeraCrypt.exe /q /m rm /v "PRDRIVE.hc"\n'
            "shell\\desmontar=Desmontar todos los volúmenes\n"
            "shell\\desmontar\\command=VeraCrypt\\VeraCrypt.exe /q /dismount\n")
editado = autorun.con(TRAVELER, "Pendrive de Pere", ".prdrive\\icono-verde.ico")
c("cambia el nombre", autorun.claves(editado)["label"], "Pendrive de Pere")
c("y el icono", autorun.claves(editado)["icon"], ".prdrive\\icono-verde.ico")
c("sin dejar el nombre de antes", editado.count("label="), 1)
c.contains("y sin tocar la orden de montar del traveler", editado,
           '/q /m rm /v "PRDRIVE.hc"')
c.contains("ni la de desmontar", editado, "/q /dismount")
c("las dos claves van justo debajo de [autorun], como las pone VeraCrypt",
  editado.splitlines()[:3],
  ["[autorun]", "label=Pendrive de Pere", "icon=.prdrive\\icono-verde.ico"])

AJENO = ("; lo escribió otro\n[Autorun]\nLabel=VIEJO\nopen=setup.exe\n"
         "ICON=viejo.ico\n\n[Content]\nMusicFiles=false\n")
editado = autorun.con(AJENO, "Nuevo", "")
c("la sección y las claves se reconocen sin mirar mayúsculas",
  autorun.claves(editado), {"label": "Nuevo", "open": "setup.exe"})
c.contains("lo que no es suyo se queda", editado, "open=setup.exe")
c.contains("las otras secciones también", editado, "[Content]\nMusicFiles=false")
c.contains("y los comentarios", editado, "; lo escribió otro")
c("un icono vacío es quitarlo", "icon" in autorun.claves(editado), False)
c("fuera de [autorun] no se toca nada aunque se llame igual",
  autorun.con("[otra]\nlabel=x\n", "", ""), "[otra]\nlabel=x\n")
c("sin [autorun] se añade una arriba",
  autorun.con("[Content]\nMusicFiles=false\n", "A", "").splitlines()[:2],
  ["[autorun]", "label=A"])
c("sin nombre, sin icono y sin nada más no queda fichero",
  autorun.con("[autorun]\nlabel=A\nicon=b.ico\n", "", ""), "")
c("las comillas que envuelven un valor se quitan, como GetPrivateProfileString",
  autorun.claves('[autorun]\nlabel="Con comillas"\n')["label"], "Con comillas")
c("si una clave se repite vale la primera",
  autorun.claves("[autorun]\nlabel=uno\nlabel=dos\n")["label"], "uno")

raiz = tmpdir("prdrive-autorun-")
escrito = autorun.escribir(raiz, "[autorun]\nlabel=Pendrive de Pere\n")
c("se escribe en la raíz", escrito, raiz / "autorun.inf")
datos = escrito.read_bytes()
c("en UTF-16 con BOM, como el de VeraCrypt", datos[:2] in (b"\xff\xfe", b"\xfe\xff"), True)
c("y con CRLF", "\r\n" in datos.decode("utf-16") and "\n\n" not in datos.decode("utf-16"), True)
c("y se lee de vuelta", autorun.leer(raiz).etiqueta, "Pendrive de Pere")
c("vacío, se borra", (autorun.escribir(raiz, ""), escrito.exists()), (None, False))
c("sin fichero, leer no lanza y no hay nada", autorun.leer(raiz), autorun.Autorun())

mayus = tmpdir("prdrive-autorun-")
(mayus / "AUTORUN.INF").write_bytes("[autorun]\r\nlabel=Año\r\n".encode("cp1252"))
c("uno a mano en la página de códigos de Windows se lee",
  autorun.leer(mayus).etiqueta, "Año")
autorun.escribir(mayus, "[autorun]\nlabel=B\n")
c("y se reescribe ESE, no uno al lado con otro nombre",
  sorted(p.name for p in mayus.iterdir()), ["AUTORUN.INF"])

# --- 2. qué icono es cada `icon=` ------------------------------------------------

for icono, clave in (("", volumen.NINGUNO),
                     ("VeraCrypt\\VeraCrypt.exe", volumen.VERACRYPT),
                     ("veracrypt\\veracrypt.EXE", volumen.VERACRYPT),
                     # el portable de ahora, una por arquitectura (#50)
                     ("VeraCrypt\\VeraCrypt-x64.exe", volumen.VERACRYPT),
                     ("VeraCrypt/VeraCrypt-arm64.exe", volumen.VERACRYPT),
                     # dentro de `.prdrive/`, sin cifrar o con BitLocker
                     (f"{DENTRO}\\icono-verde.ico", "verde"),
                     (f"{DENTRO.upper()}/ICONO-VERDE.ICO", "verde"),
                     (f"{DENTRO}\\icono-propio-0123abcd.ico", volumen.PROPIO),
                     (f"{DENTRO}\\icono-fucsia.ico", volumen.OTRO),
                     # en la raíz física de un contenedor, con el prefijo
                     (".prdrive-icono-verde.ico", "verde"),
                     (".prdrive-icono-propio-0123abcd.ico", volumen.PROPIO),
                     # nuestro nombre en un sitio donde prdrive no lo deja
                     ("icono-verde.ico", volumen.OTRO),
                     (f"{DENTRO}\\.prdrive-icono-verde.ico", volumen.OTRO),
                     ("iconos\\icono-verde.ico", volumen.OTRO),
                     ("miicono.ico", volumen.OTRO),
                     ("%SystemRoot%\\system32\\shell32.dll,8", volumen.OTRO)):
    c(f"«{icono}» es {clave}", volumen.clave_de(icono), clave)

# --- 3. el nombre y el .ico propio ---------------------------------------------------

c("el nombre se guarda sin espacios alrededor",
  volumen.revisar_nombre("  Pendrive de Pere  "), "Pendrive de Pere")
c("vacío vale: es quitarlo", volumen.revisar_nombre("   "), "")


def rechaza(funcion, *args) -> str:
    try:
        funcion(*args)
    except volumen.VolumenError as e:
        return str(e)
    return ""


c("uno con salto de línea no: rompería el fichero",
  bool(rechaza(volumen.revisar_nombre, "uno\nicon=otro.ico")), True)
c("ni con un separador de línea Unicode, que splitlines() también parte",
  bool(rechaza(volumen.revisar_nombre, "uno\u2028icon=otro.ico")), True)
c("ni uno más largo de lo que se deja",
  bool(rechaza(volumen.revisar_nombre, "x" * (autorun.MAX_NOMBRE + 1))), True)
c("y con acentos, los que haga falta",
  volumen.revisar_nombre("Pendrive de Íñigo"), "Pendrive de Íñigo")

sueltos = tmpdir("prdrive-ico-")
bueno = sueltos / "bueno.ico"
bueno.write_bytes(ICO_DE_VERDAD((16,)))
c("un .ico de verdad se acepta", volumen.leer_ico(bueno), bueno.read_bytes())
png = sueltos / "foto.ico"
png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)
c("un PNG con extensión .ico no", bool(rechaza(volumen.leer_ico, png)), True)
c("ni un fichero que no está", bool(rechaza(volumen.leer_ico, sueltos / "no.ico")), True)
maximo = volumen.MAX_ICO
volumen.MAX_ICO = 10
c("ni uno que ocupa como una foto", bool(rechaza(volumen.leer_ico, bueno)), True)
volumen.MAX_ICO = maximo

# --- 4. guardar ----------------------------------------------------------------------

store.hide = lambda ruta: ocultados.append(Path(ruta).name)

with sandbox() as dispositivo:
    # Sin cifrar o con BitLocker es lo mismo: `.prdrive/` está en la raíz que
    # se enchufa, y no hay vestíbulo que encontrar.
    vestibulo.raiz_fisica = lambda device_id: None
    programa = dispositivo / DENTRO
    programa.mkdir()
    (programa / "runsync.ico").write_bytes(b"x")
    estado = volumen.leer()
    c("sin contenedor, la raíz es la del dispositivo",
      (estado.raiz, estado.fisica), (dispositivo, False))
    c("y los iconos van en su carpeta del programa", estado.carpeta, programa)
    c("y sin autorun.inf no hay nombre ni icono",
      (estado.nombre, estado.clave), ("", volumen.NINGUNO))

    (dispositivo / "datos-del-usuario").mkdir()
    (dispositivo / ".prdrive-otra-cosa").write_text("x", encoding="utf-8")

    volumen.guardar(estado, "Pendrive de Pere", "verde")
    ahora = volumen.leer()
    c("guarda el nombre", ahora.nombre, "Pendrive de Pere")
    c("y el color, con el icono dentro de la carpeta del programa",
      (ahora.clave, ahora.icono), ("verde", f"{DENTRO}\\icono-verde.ico"))
    c("pintado con su color", pintados[-1], icons.CAMPOS["verde"])
    c("el icono está donde dice icon=",
      en_disco(dispositivo, ahora.icono), programa / "icono-verde.ico")
    c("y existe", (programa / "icono-verde.ico").is_file(), True)
    c("en la raíz no queda ningún icono", iconos(dispositivo), [])
    c("ni se oculta: ya lo esconde su carpeta", ocultados, [])

    pintados.clear()
    volumen.guardar(ahora, "Otro nombre", "verde")
    c("el mismo color no se vuelve a pintar: su nombre dice lo que lleva", pintados, [])

    volumen.guardar(volumen.leer(), "Otro nombre", "granate")
    ahora = volumen.leer()
    c("otro color, otro fichero", ahora.icono, f"{DENTRO}\\icono-granate.ico")
    c("y el anterior se recoge, sin tocar el icono de la aplicación",
      iconos(programa), ["icono-granate.ico", "runsync.ico"])
    c("ni nada que no sea un icono de prdrive",
      ((dispositivo / "datos-del-usuario").is_dir(),
       (dispositivo / ".prdrive-otra-cosa").is_file()), (True, True))

    # Uno que se dejó en la raíz, como hacía la primera versión de esto, se lee
    # igual y se va a su sitio con el siguiente «Guardar».
    (dispositivo / ".prdrive-icono-verde.ico").write_bytes(b"x")
    autorun.escribir(dispositivo, "[autorun]\nlabel=A\nicon=.prdrive-icono-verde.ico\n")
    c("un icono en la raíz se reconoce", volumen.leer().clave, "verde")
    volumen.guardar(volumen.leer(), "A", "verde")
    c("y al guardar pasa a la carpeta del programa",
      (volumen.leer().icono, iconos(dispositivo), iconos(programa)),
      (f"{DENTRO}\\icono-verde.ico", [], ["icono-verde.ico", "runsync.ico"]))
    ahora = volumen.leer()

    mio = ICO_DE_VERDAD((16,), "#123456")
    volumen.guardar(ahora, "Otro nombre", volumen.PROPIO, mio)
    ahora = volumen.leer()
    c("uno propio lleva su hash en el nombre",
      ahora.icono, f"{DENTRO}\\" + volumen.nombre_icono(volumen.PROPIO, mio))
    c("y es una copia exacta", en_disco(dispositivo, ahora.icono).read_bytes(), mio)
    otro_mio = ICO_DE_VERDAD((16,), "#654321")
    c("otro dibujo, otro nombre: la caché del Explorador no enseña el de antes",
      volumen.nombre_icono(volumen.PROPIO, otro_mio) != ahora.icono, True)
    volumen.guardar(ahora, "Cambio solo el nombre", volumen.PROPIO)
    ahora = volumen.leer()
    c("sin elegir otro .ico, el propio que había se queda",
      (ahora.nombre, ahora.clave, en_disco(dispositivo, ahora.icono).is_file()),
      ("Cambio solo el nombre", volumen.PROPIO, True))

    # Escrito a mano con la barra de Unix y en mayúsculas sigue siendo el mismo
    # fichero: guardar solo el nombre no puede llevárselo por delante.
    a_mano = ahora.icono.replace("\\", "/").upper()
    autorun.escribir(dispositivo, f"[autorun]\nlabel=A\nicon={a_mano}\n")
    volumen.guardar(volumen.leer(), "B", volumen.PROPIO)
    c("un icon= a mano con / y mayúsculas no se recoge",
      (volumen.leer().icono, en_disco(dispositivo, ahora.icono).is_file()),
      (a_mano, True))

    c("VeraCrypt sin traveler no se puede elegir",
      bool(rechaza(volumen.guardar, ahora, "x", volumen.VERACRYPT)), True)
    ya_puesto = volumen.Estado(dispositivo, False, "A", volumen.VERACRYPT,
                               autorun.ICONO_VERACRYPT, False)
    c("pero si ya lo tenía, cambiar solo el nombre no lo pide",
      rechaza(volumen.guardar, ya_puesto, "B", volumen.VERACRYPT), "")
    sin_propio = volumen.Estado(dispositivo, False, "", volumen.NINGUNO, "", False)
    c("ni «uno tuyo» sin haber elegido cuál",
      bool(rechaza(volumen.guardar, sin_propio, "x", volumen.PROPIO)), True)

    # Un icono que no puso prdrive sobrevive a cambiar el nombre.
    autorun.escribir(dispositivo, "[autorun]\nlabel=A\nicon=miicono.ico\n")
    ajeno = volumen.leer()
    volumen.guardar(ajeno, "B", ajeno.clave)
    c("un icon= ajeno se queda al cambiar solo el nombre",
      (volumen.leer().nombre, volumen.leer().icono), ("B", "miicono.ico"))
    c("y los iconos de prdrive, que ya no se usan, se van",
      (iconos(dispositivo), iconos(programa)), ([], ["runsync.ico"]))

    # Si el autorun.inf no se puede escribir, no queda un icono huérfano.
    escribir = autorun.escribir

    def falla(raiz, texto):
        raise PermissionError("acceso denegado")

    autorun.escribir = falla
    error = rechaza(volumen.guardar, volumen.leer(), "C", "morado")
    autorun.escribir = escribir
    c.contains("un fallo al escribir se dice con la ruta", error, "autorun.inf")
    c("y no deja el icono nuevo suelto",
      (programa / "icono-morado.ico").exists(), False)
    c("ni cambia lo que había", volumen.leer().nombre, "B")

    volumen.guardar(volumen.leer(), "", volumen.NINGUNO)
    c("sin nombre y sin icono no queda autorun.inf", autorun.buscar(dispositivo), None)
    c("y en .prdrive/ solo lo que era suyo", iconos(programa), ["runsync.ico"])

# --- 5. con VeraCrypt: la raíz física, y el traveler ---------------------------------

with sandbox() as dentro:
    fisica = tmpdir("prdrive-fisica-")
    vestibulo.raiz_fisica = lambda device_id: fisica
    (fisica / "PRDRIVE.hc").write_text("x", encoding="utf-8")
    (fisica / vestibulo.TRAVELER).mkdir()
    (fisica / vestibulo.TRAVELER / vestibulo.TRAVELER_EXE).write_text("x", encoding="utf-8")
    # El de un dispositivo de antes: lo que escribía el traveler, con sus
    # órdenes, y algo de otro programa al lado.
    autorun.escribir(fisica, TRAVELER + "open=otra-cosa.exe\n")
    # Lo que quedó en claro de antes de cifrar no se toca (`crypto.restos_en_claro`).
    (fisica / DENTRO).mkdir()
    (fisica / DENTRO / "icono-verde.ico").write_bytes(b"x")
    (dentro / DENTRO).mkdir()
    ocultados.clear()

    estado = volumen.leer()
    c("con contenedor, se escribe en la raíz que se enchufa, no en el montado",
      (estado.raiz, estado.fisica), (fisica, True))
    c("y los iconos van en esa raíz: su .prdrive/ está dentro del contenedor",
      estado.carpeta, fisica)
    c("lo que puso el traveler se lee", (estado.nombre, estado.clave),
      ("PRDRIVE", volumen.VERACRYPT))
    c("y su icono se ofrece", estado.veracrypt, True)

    volumen.guardar(estado, "Cifrado de Pere", "azul")
    texto = utf16(fisica / "autorun.inf")
    c.contains("el nombre nuevo", texto, "label=Cifrado de Pere")
    c.contains("sin perder la orden de montar", texto, '/q /m rm /v "PRDRIVE.hc"')
    c.contains("ni lo que no es de prdrive", texto, "open=otra-cosa.exe")
    c("el icono va fuera del contenedor, junto al autorun.inf",
      (volumen.leer().icono, (fisica / ".prdrive-icono-azul.ico").is_file()),
      (".prdrive-icono-azul.ico", True))
    c("y oculto", ocultados, [".prdrive-icono-azul.ico"])
    c("nada dentro del contenedor", (iconos(dentro), iconos(dentro / DENTRO)), ([], []))

    # Volver a llevar VeraCrypt respeta lo elegido, y retira sus órdenes de
    # antes: Windows no las enseña en un extraíble (M2) y apuntaban a un
    # VeraCrypt.exe que el portable no trae (#50).
    traveler.write_autorun(fisica)
    texto = utf16(fisica / "autorun.inf")
    c.contains("el traveler respeta el nombre elegido", texto, "label=Cifrado de Pere")
    c.contains("y el icono", texto, "icon=.prdrive-icono-azul.ico")
    c("y retira sus órdenes de antes", ("shell\\" in texto, "action=" in texto),
      (False, False))
    c.contains("pero no lo que no es suyo", texto, "open=otra-cosa.exe")

    volumen.guardar(volumen.leer(), "Cifrado de Pere", volumen.VERACRYPT)
    c("volver al de VeraCrypt recoge el pintado",
      ((fisica / ".prdrive-icono-azul.ico").exists(), volumen.leer().icono),
      (False, "VeraCrypt\\VeraCrypt.exe"))
    c("y no entra en el .prdrive/ en claro que quedó fuera",
      (fisica / DENTRO / "icono-verde.ico").is_file(), True)

    # Con el portable en lugar de la copia de antes, el icono de VeraCrypt pasa
    # a ser un ejecutable que existe: el `VeraCrypt.exe` ya no está.
    (fisica / vestibulo.TRAVELER / vestibulo.TRAVELER_EXE).unlink()
    for arq in vestibulo.TRAVELER_ARQUITECTURAS:
        (fisica / vestibulo.TRAVELER / vestibulo.traveler_portatil(arq)).write_bytes(b"MZ")
    traveler.write_autorun(fisica)
    c("tras cambiar al portable, el icono es su ejecutable x64",
      (volumen.leer().icono, volumen.leer().clave),
      ("VeraCrypt\\VeraCrypt-x64.exe", volumen.VERACRYPT))
    volumen.guardar(volumen.leer(), "Cifrado de Pere", "azul")
    volumen.guardar(volumen.leer(), "Cifrado de Pere", volumen.VERACRYPT)
    c("y elegirlo en la ventana pone el que hay",
      volumen.leer().icono, "VeraCrypt\\VeraCrypt-x64.exe")

store.hide = HIDE_DE_VERDAD

nuevo = tmpdir("prdrive-fisica-")
traveler.write_autorun(nuevo)
c("un traveler sin autorun.inf previo pone el nombre y el icono de VeraCrypt",
  (autorun.leer(nuevo).etiqueta, autorun.leer(nuevo).icono),
  ("PRDRIVE", "VeraCrypt\\VeraCrypt-x64.exe"))
c("y ninguna orden", "shell" in autorun.leer(nuevo).texto, False)

# --- 6. el asistente no los toma por contenido de otro ---------------------------------

for nombre in (".prdrive-icono-verde.ico", ".prdrive-icono-propio-0123abcd.ico",
               "autorun.inf", "AUTORUN.INF"):
    c(f"«{nombre}» es ruido", device.es_ruido(nombre), True)
c("una carpeta de datos no", device.es_ruido("fotos"), False)
limpio = tmpdir("prdrive-limpio-")
(limpio / "autorun.inf").write_text("x", encoding="utf-8")
(limpio / ".prdrive-icono-granate.ico").write_bytes(b"x")
c("un volumen con solo su nombre y su icono se lee vacío",
  device.install_target(limpio)[0], device.VACIO)

# --- 7. lo que se movió de sitio sigue donde se buscaba ---------------------------------

c("deploy.hide es el de common/store", deploy.hide, store.hide)
c("y deploy.unhide también", deploy.unhide, store.unhide)
c("los cinco colores son distintos", len(set(icons.CAMPOS.values())), len(icons.CAMPOS))
c("y el primero es el de la aplicación", volumen.MARCAS[0].campo, icons.CAMPO)
c("otro color es otro dibujo",
  ICO_DE_VERDAD((16,), icons.CAMPOS["verde"]) != ICO_DE_VERDAD((16,)), True)
salida = tmpdir("prdrive-ico-") / "runsync.ico"
icons.write_ico(salida, (16,))
c("write_ico escribe lo mismo que ico()", salida.read_bytes(), ICO_DE_VERDAD((16,)))

# --- 8. la ventana: el cableado --------------------------------------------------------

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    tk_raiz = tk.Tk()
    tk_raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) la ventana: no hay entorno gráfico: {e}")
    raise SystemExit(c.report())

from ui import tk_doctor, tk_volumen  # noqa: E402

c("«Ajustes» la ofrece",
  [clave for *_, clave in tk_doctor.ENTRADAS].count("volumen"), 1)

llamadas: list[tuple] = []
avisos: list[str] = []
messagebox.showinfo = lambda *a, **k: avisos.append("info")
messagebox.showerror = lambda titulo, texto=None, **k: avisos.append(str(texto))
tk_volumen.working = lambda parent, title, funcion, mensaje="": (True, funcion())
volumen.guardar = lambda estado, nombre, clave, propio=None: llamadas.append(
    (estado.nombre, nombre, clave, propio))
volumen.leer = lambda: volumen.Estado(Path("E:/"), False, "PRDRIVE", "azul",
                                      ".prdrive\\icono-azul.ico", False)


def rellenar_y_pulsar(nombre: str, clave: str, boton: str = "Guardar"):
    def falso_mostrar(dlg, parent=None):
        pila = [dlg]
        while pila:
            w = pila.pop()
            pila += list(w.winfo_children())
            if isinstance(w, ttk.Entry):
                w.delete(0, "end")
                w.insert(0, nombre)
            elif isinstance(w, ttk.Radiobutton) and w.cget("value") == clave:
                w.invoke()
        pila = [dlg]
        while pila:
            w = pila.pop()
            pila += list(w.winfo_children())
            if isinstance(w, ttk.Button) and w.cget("text") == boton:
                w.invoke()
                return
    return falso_mostrar


tk_volumen.mostrar = rellenar_y_pulsar("Pendrive de Pere", "morado")
tk_volumen.open_dialog(tk_raiz)
c("«Guardar» guarda lo que dice el formulario", llamadas,
  [("PRDRIVE", "Pendrive de Pere", "morado", None)])
c("y lo confirma", avisos, ["info"])

llamadas.clear()
avisos.clear()
tk_volumen.mostrar = rellenar_y_pulsar("uno\tdos", "verde")
tk_volumen.open_dialog(tk_raiz)
c("un nombre que no vale ni llega a guardarse", llamadas, [])
c("y se dice por qué", len(avisos) == 1 and "control" in avisos[0], True)

llamadas.clear()
tk_volumen.mostrar = rellenar_y_pulsar("Pendrive de Pere", "verde", "Cancelar")
tk_volumen.open_dialog(tk_raiz)
c("«Cancelar» no guarda nada", llamadas, [])

tk_raiz.destroy()
sys.exit(c.report())
