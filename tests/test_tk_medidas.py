#!/usr/bin/env python3
"""
Que las pantallas quepan en la pantalla.

Lo que se comprueba no es el aspecto sino una sola cosa medible: **ninguna
ventana pide más de lo que hay**, y **nada queda recortado sin barra que lo
avise**. Es el fallo que tuvo el asistente: el hueco de los pasos era un marco de
820x430 px con `grid_propagate(False)`, el paso 1 pedía 486 px de alto en una
pantalla normal y el último campo simplemente no se dibujaba, sin ningún aviso.

Cada pantalla de la lista son **dos** cosas y las dos importan: los píxeles que
dice tener y el `tk scaling` con el que se dibuja. `tk scaling` son píxeles por
punto —1,3333 es 96 ppp, o sea el zoom del sistema al 100 %; 2,0 es el 150 % y
2,6667 el 200 %—, y es lo que de verdad rompe las medidas, porque las fuentes van
en puntos y crecen con él mientras que un recuadro en píxeles no. Una 4K sola no
prueba gran cosa (sobra sitio por todos lados); una 4K al 200 %, o peor, una
1080p al 200 %, es donde el contenido deja de caber.

Las medidas dependen de las fuentes del equipo, así que aquí no se fijan cifras:
se compara lo que pide cada ventana con lo que dice `tk.pantalla_util`, que es
justo lo que mira el código. Para probar una pantalla que no se tiene se
sustituye esa función, que por eso es de módulo, y se le cambia la escala al
intérprete de Tk: es reversible y la cogen los widgets que se creen después.

Las ventanas se crean ocultas y no se entra nunca en el bucle de eventos.
"""

import sys

from _harness import Checks, sandbox, tmpdir

import tomllib

from common import (catalog, components, config_file, conflicts, fleet, model,
                    pairing, pins, update)
from install import device

c = Checks("medidas de las pantallas")

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(0)

from ui import tk as uitk
from ui import remote_picker
from ui import (tk_doctor, tk_fleet, tk_install, tk_pairs, tk_qr, tk_repair,
                tk_update, tk_versions, tk_volumen, versions_editor, volumen)

# Ni una petición a GitHub desde un test.
update.fetch = lambda url, timeout: c("ningún test toca la red", "fetch", "nada")

messagebox.showinfo = lambda *a, **k: None
messagebox.showerror = lambda *a, **k: None

BASE = {"defaults": {"remote": "nas"},
        "pair": [{"name": f"pareja{i}", "local": f"sync-data/p{i}",
                  "remote_path": f"/R/p{i}", "mode": "bisync"} for i in range(12)]}

catalog.load = lambda raw=None: (catalog.Catalog(
    raw=tomllib.loads(config_file.dumps(BASE)), text=config_file.dumps(BASE),
    source="remote", stamp="2026-01-01 00:00:00",
    endpoint="nas:/prdrive-catalog/pairs.toml"), None)
catalog.push = lambda *a, **k: []
catalog.run = lambda args: (_ for _ in ()).throw(
    AssertionError("ningún test puede hablar con el remoto"))

# La flota, con lo más ancho que puede salir: nombres largos, las cuatro
# plataformas y un resultado que enumera parejas. Y el peor de todos al FINAL,
# no el primero: la ventana abre con el primero elegido, así que lo que se mide
# es que el sitio de la ficha se reserva para toda la flota y no solo para ese.
# Sus equipos llevan nombres de 63 caracteres, el límite de una etiqueta DNS.
EQUIPOS_LARGOS = tuple(
    fleet.Equipo((f"sala-de-reuniones-{i}-del-edificio-de-la-oficina-de-arriba-" * 2)[:63],
                 "2026-01-01 00:00:00") for i in range(fleet.MAX_EQUIPOS))
FLOTA = [fleet.Dispositivo(
    id=f"dispositivo{i}", nombre=f"el pendrive de la oficina de arriba {i}",
    version="0.1.4", plataformas=tuple(p.clave for p in pins.PLATAFORMAS),
    last_seen="2026-01-01 00:00:00",
    last_result="fallo en pareja0, pareja1, pareja2") for i in range(7)]
FLOTA.append(FLOTA[0]._replace(
    id="el-peor", equipos=EQUIPOS_LARGOS, ultima_buena="2025-12-01 08:00:00",
    last_result="fallo en " + ", ".join(p["name"] for p in BASE["pair"])))
# El explorador del remoto lista carpetas con `rclone lsd`; aquí se le da la
# lista hecha, que es lo que hay que medir.
remote_picker.listar = lambda remote, ruta: [f"carpeta-de-nombre-largo-{i}"
                                             for i in range(9)]

fleet.leer = lambda raw=None: (FLOTA, None)
fleet.device_id = lambda app_dir=None: "dispositivo0"
# Este equipo es uno de los largos: la marca «· este equipo» alarga su línea.
fleet.equipo_actual = lambda: EQUIPOS_LARGOS[0].nombre

# Las versiones del lado remoto salen de un `rclone lsf`, que aquí no se lanza.
# Se le da el peor caso de ancho: una ruta larga y una cifra de varios dígitos,
# que es lo que estira esa tarjeta.
VERSIONES_REMOTAS = versions_editor.Lado(
    versions_editor.REMOTO,
    "nas:/datos/documentos/proyectos/2026/bóveda-de-notas/.prversions", True, "",
    tuple(versions_editor.Version(
        ruta=f"documentos/proyecto-{i}/borradores/informe-trimestral-{i}"
            f"~2026010{i % 9 + 1}-120000.docx",
        original=f"informe-trimestral-{i}.docx",
        cuando=__import__("datetime").datetime(2026, 1, i % 28 + 1, 12, 0),
        tamano=1024 * 1024 * 3) for i in range(40)))
versions_editor.leer_remoto = lambda pair: VERSIONES_REMOTAS
# `working()` lanza un hilo y abre su propia ventanita: aquí se mide la de
# versiones, no esa.
tk_versions.working = lambda parent, title, funcion, mensaje="": (True, funcion())

# La ventana de emparejar dibuja un código QR cuyo tamaño sale del tamaño de la
# carga, y la carga lleva una clave privada. Aquí se le da una del tamaño real
# —una ed25519 en PEM son unos 400 bytes— para medir el dibujo que se va a ver,
# no uno de juguete. Nada de esto toca el rclone.conf de nadie.
pairing.construir = lambda raw=None, app_dir=None: pairing.dumps(
    "nas", {"type": "sftp", "host": "nas.example.org", "port": "22",
            "user": "pere", "disable_hashcheck": "true", "shell_type": "none"},
    key_name="id_ed25519", catalog_path="/prdrive-catalog/pairs.toml",
    private_key=(b"-----BEGIN OPENSSH PRIVATE KEY-----\n" + b"b3BlbnNza" * 40
                 + b"\n-----END OPENSSH PRIVATE KEY-----\n"))

# El nombre y el icono de la unidad, en sus casos más altos: con el icono de
# VeraCrypt ofrecido (una fila más), un icono que no puso prdrive con una ruta
# larga, y la raíz en una ruta larga, que es lo que alarga la nota. Las dos notas:
# la de la raíz física de un contenedor, y la de la unidad sin cifrar o con
# BitLocker, que lleva la ruta dos veces (el autorun.inf y `.prdrive/`).
VOLUMENES = [volumen.Estado(
    __import__("pathlib").Path("/media/usuario-de-nombre-largo/PENDRIVE-DE-LA-OFICINA"),
    fisica, "Pendrive de la oficina de arriba", volumen.OTRO,
    "%SystemRoot%\\System32\\imageres.dll,-30", True) for fisica in (True, False)]

# El panel de VeraCrypt sin VeraCrypt: se le da uno de mentira, una unidad
# FAT32 (la pista del tope) y sin dispersos (la estimación de la espera), que es
# el panel más alto que pinta. Nada de esto lanza nada ni escribe en ninguna
# unidad.
from install import crypto  # noqa: E402

crypto.find_veracrypt = lambda extra_dir=None: {"mount": "VeraCrypt.exe",
                                                "format": "VeraCrypt Format.exe"}
crypto.soporta_dispersos = lambda root: False
crypto.sistema_de_ficheros = lambda root: "FAT32"
crypto.medir_escritura = lambda root, muestra=0: 10 * 1024 ** 2
# Y al lado, una instalación sin cifrar con carpetas de nombre largo: el bloque
# rojo que la avisa es lo que más estira ese paso.
EN_CLARO = tmpdir("prdrive-en-claro-")
(EN_CLARO / ".prdrive").mkdir()
(EN_CLARO / ".prdrive" / "PRDRIVE").write_text("id=viejo\n", encoding="utf-8")
for i in range(8):
    (EN_CLARO / f"carpeta-de-datos-con-un-nombre-bastante-largo-{i}").mkdir()

# nombre, ancho, alto, tk scaling
PANTALLAS = (
    ("1080p", 1920, 1080, 1.3333),
    ("1080p al 150 %", 1920, 1080, 2.0),
    ("1080p al 200 %", 1920, 1080, 2.6667),
    ("2K", 2560, 1440, 1.3333),
    ("2K al 150 %", 2560, 1440, 2.0),
    ("4K al 150 %", 3840, 2160, 2.0),
    ("4K al 200 %", 3840, 2160, 2.6667),
    ("portátil 1366x768", 1366, 768, 1.3333),
    ("1280x720", 1280, 720, 1.3333),
    ("1024x600", 1024, 600, 1.3333),
)

PANTALLA_REAL = uitk.pantalla_util
ESCALA_REAL = float(raiz.tk.call("tk", "scaling"))


def pantalla(ancho, alto, escala):
    """Hace creer al código que la pantalla es esa, y con ese zoom."""
    uitk.pantalla_util = lambda win: (ancho, alto)
    raiz.tk.call("tk", "scaling", escala)


def cabe(ventana) -> bool:
    ventana.update_idletasks()
    util_x, util_y = uitk.pantalla_util(ventana)
    return (ventana.winfo_reqwidth() <= util_x
            and ventana.winfo_reqheight() <= util_y)


def recortado(visor) -> bool:
    """Contenido fuera del recuadro sin barra que lo enseñe: lo que no puede pasar."""
    visor.interior.update_idletasks()
    ancho, alto = visor._medida()
    return ((visor.interior.winfo_reqheight() > alto
             and not visor.vertical.grid_info())
            or (visor.interior.winfo_reqwidth() > ancho
                and not visor.horizontal.grid_info()))


def usar_conexion(wiz) -> None:
    """Pulsa «Usar esta conexión» con lo que deja más alto el paso: la línea de
    «preparada», larga, y debajo el aviso de un sftp sin usuario (#47). Las dos
    aparecen con el paso ya pintado, que es cuando un hueco se queda corto."""
    pendientes, caja, usar = list(wiz.cuerpo.winfo_children()), None, None
    while pendientes:
        w = pendientes.pop()
        pendientes += list(w.winfo_children())
        if isinstance(w, tk.Text):
            caja = w
        elif isinstance(w, ttk.Button) and w.cget("text") == "Usar esta conexión":
            usar = w
    caja.delete("1.0", "end")
    caja.insert("1.0", "host = servidor-de-la-oficina-de-arriba.example.org\n"
                       "port = 22\n")
    usar.invoke()
    wiz.root.update_idletasks()


def medir_dialogo(fabricar, ancho, alto, escala, modulo=None) -> tuple[bool, bool]:
    """Abre un diálogo sin enseñarlo y devuelve (cabe, recortado).

    `modulo` es aquel cuyo `mostrar` hay que interceptar: cada pantalla importa
    el suyo con `from .tk import mostrar`, así que sustituirlo en una no lo
    sustituye en las demás."""
    pantalla(ancho, alto, escala)
    medida: dict = {}
    modulo = modulo or tk_pairs

    def falso_mostrar(dlg, parent=None):
        dlg.visor.encajar(dlg)
        medida["cabe"] = cabe(dlg)
        medida["recortado"] = recortado(dlg.visor)

    previo = modulo.mostrar
    modulo.mostrar = falso_mostrar
    tk.Toplevel.wait_window = lambda self, *a, **k: None
    try:
        fabricar()
    finally:
        modulo.mostrar = previo
    return medida.get("cabe", False), medida.get("recortado", True)


try:
    # --- el asistente, paso a paso ---------------------------------------------------
    # Instalación, Parejas y Verificación necesitan un dispositivo elegido; los que
    # se pueden pintar sin nada montado son los que llevan formulario, que son los
    # que se salían.
    #
    # Por NOMBRE y no por índice: el orden de los pasos ya ha cambiado una vez
    # (el dispositivo pasó a ser el primero), y una lista de números habría
    # seguido pasando mientras medía los pasos equivocados.
    PASO = {t: i for i, (t, _, _) in enumerate(tk_install.PASOS_INSTALACION)}
    DIBUJABLES = ("Dispositivo", "Cifrado", "Conexión", "Comprobaciones",
                  "Inicialización")
    # Un dispositivo de mentira con su VERSION, para que la pantalla de
    # actualizar tenga que pintar la tabla de versiones de verdad.
    DISPOSITIVO_FALSO = tmpdir("prdrive-medidas-")
    (DISPOSITIVO_FALSO / ".prdrive").mkdir()
    (DISPOSITIVO_FALSO / ".prdrive" / "VERSION").write_text("0.0.1", encoding="utf-8")

    for nombre, ancho, alto, escala in PANTALLAS:
        pantalla(ancho, alto, escala)
        top = tk.Toplevel(raiz)
        top.withdraw()
        wiz = tk_install.build(top)
        for paso in DIBUJABLES:
            wiz.indice = PASO[paso]
            wiz.repintar()
            c(f"{nombre}: el paso «{paso}» cabe en la ventana", cabe(top), True)
            c(f"{nombre}: el paso «{paso}» no queda recortado",
              recortado(wiz.visor), False)
        # «Conexión» después de pulsar su botón, con el estado y el aviso puestos.
        wiz.indice = PASO["Conexión"]
        wiz.repintar()
        usar_conexion(wiz)
        c(f"{nombre}: «Conexión» con su estado y su aviso cabe", cabe(top), True)
        c(f"{nombre}: «Conexión» con su estado y su aviso no queda recortado",
          recortado(wiz.visor), False)
        # El paso de cifrado con VeraCrypt, en su peor caso (ver EN_CLARO).
        wiz.state.device, wiz.state.device_root = EN_CLARO, None
        wiz.state.encryption = "veracrypt"
        wiz.indice = PASO["Cifrado"]
        wiz.repintar()
        c(f"{nombre}: el panel de VeraCrypt cabe", cabe(top), True)
        c(f"{nombre}: el panel de VeraCrypt no queda recortado",
          recortado(wiz.visor), False)
        wiz.state.encryption = "none"
        # La pantalla del recorrido corto. Solo esa: la otra es «Dispositivo», que
        # ya se ha medido arriba, y volver a pintarla cuesta otra consulta de
        # unidades al sistema por cada resolución de la tabla.
        wiz.pasos = tk_install.PASOS_ACTUALIZACION
        wiz.state.device = DISPOSITIVO_FALSO
        wiz.indice = len(tk_install.PASOS_ACTUALIZACION) - 1
        wiz.repintar()
        c(f"{nombre}: «Actualización» cabe", cabe(top), True)
        c(f"{nombre}: «Actualización» no queda recortado",
          recortado(wiz.visor), False)
        # La lista de plataformas, en su recorrido corto: cuatro filas, el total y
        # los avisos, que es lo más ancho que pinta el asistente.
        wiz.pasos = tk_install.PASOS_PLATAFORMAS
        wiz.indice = len(tk_install.PASOS_PLATAFORMAS) - 1
        wiz.repintar()
        c(f"{nombre}: «Plataformas» cabe", cabe(top), True)
        c(f"{nombre}: «Plataformas» no queda recortado",
          recortado(wiz.visor), False)
        top.destroy()

    # --- lo que aparece DESPUÉS de pintar el paso -----------------------------
    #
    # Reportado: al elegir una unidad que ya es un prdrive, el panel del desvío
    # sale por debajo del borde y sin barra que lo avise. Lo que fallaba era el
    # momento: `repintar()` ajustaba el hueco al terminar de dibujar, pero este
    # panel lo monta el `<<TreeviewSelect>>`, o sea después. Y no basta con que
    # el visor se entere solo, porque su interior es un item del lienzo con la
    # altura fijada: al añadirle widgets cambia lo que PIDE y no lo que MIDE, así
    # que el <Configure> del que cuelga la barra tampoco llega a dispararse.
    #
    # Se mide en una pantalla amplia y en una pequeña porque la respuesta
    # correcta es distinta y las dos valen: crecer donde hay sitio, y poner la
    # barra donde no lo hay. Lo que no vale es ninguna de las dos.
    PRDRIVE_FALSO = tmpdir("prdrive-desvio-")
    (PRDRIVE_FALSO / ".prdrive").mkdir()
    (PRDRIVE_FALSO / ".prdrive" / "VERSION").write_text("0.0.1", encoding="utf-8")
    (PRDRIVE_FALSO / ".prdrive" / "PRDRIVE").write_text("id=abc\n", encoding="utf-8")
    (PRDRIVE_FALSO / ".prdrive" / "runsync.py").write_text("#\n", encoding="utf-8")
    # `.prdrive` está en `device.RUIDO`, así que un volumen que solo lo lleve se
    # lee como vacío: hace falta algo más para que dé YA_INSTALADO.
    (PRDRIVE_FALSO / "docs").mkdir()

    volumenes_real = device.list_volumes
    device.list_volumes = lambda: [device.Volume(
        root=PRDRIVE_FALSO, label="PRDRIVE", filesystem="exFAT",
        drive_type="Removable", size=8049885184, free=7000000000)]
    try:
        for nombre, ancho, alto, escala in (("1080p", 1920, 1080, 1.3333),
                                            ("1024x600", 1024, 600, 1.3333)):
            pantalla(ancho, alto, escala)
            top = tk.Toplevel(raiz)
            top.withdraw()
            wiz = tk_install.build(top)
            wiz.indice = PASO["Dispositivo"]
            wiz.repintar()
            top.update()

            arbol = None
            pendientes = list(wiz.cuerpo.winfo_children())
            while pendientes:
                w = pendientes.pop(0)
                if isinstance(w, ttk.Treeview):
                    arbol = w
                    break
                pendientes += list(w.winfo_children())
            c(f"{nombre}: la lista de unidades está ahí", arbol is not None, True)

            arbol.selection_set(str(PRDRIVE_FALSO))
            top.update()
            c(f"{nombre}: al elegir un prdrive sale el desvío",
              wiz.ya_instalado, True)
            c(f"{nombre}: y el panel del desvío no queda recortado",
              recortado(wiz.visor), False)
            c(f"{nombre}: la ventana sigue cabiendo con el desvío puesto",
              cabe(top), True)
            top.destroy()
    finally:
        device.list_volumes = volumenes_real

    # El caso que se reportó era el formulario de «Conexión»: en una pantalla
    # normal tiene que verse entero, no desplazarse. Una barra ahí sería tapar el
    # fallo, no arreglarlo. En una 4K, donde sobra sitio, igual. Se busca por
    # nombre porque ese paso ya no es el primero.
    for nombre, ancho, alto, escala in (("1080p", 1920, 1080, 1.3333),
                                        ("4K al 150 %", 3840, 2160, 2.0)):
        pantalla(ancho, alto, escala)
        top = tk.Toplevel(raiz)
        top.withdraw()
        wiz = tk_install.build(top)
        wiz.indice = PASO["Conexión"]
        wiz.repintar()
        top.update_idletasks()          # sin esto la barra aún no está puesta
        c(f"{nombre}: «Conexión» se ve entero, sin barra",
          bool(wiz.visor.vertical.grid_info()), False)
        c(f"{nombre}: el hueco de los pasos llega a lo que pide «Conexión»",
          wiz.visor._medida()[1] >= wiz.visor.interior.winfo_reqheight(), True)
        # ...y el hueco crece con el paso más grande, pero no encoge con el más
        # pequeño: el asistente no puede cambiar de tamaño a cada paso.
        alto_conexion = wiz.visor._medida()[1]
        wiz.indice = PASO["Inicialización"]
        wiz.repintar()
        c(f"{nombre}: un paso corto no encoge el hueco",
          wiz.visor._medida()[1], alto_conexion)
        # Lo que sale al pulsar «Usar esta conexión» tampoco puede traer la barra:
        # el hueco crece con ello.
        wiz.indice = PASO["Conexión"]
        wiz.repintar()
        usar_conexion(wiz)
        c(f"{nombre}: «Conexión» con su estado y su aviso se ve entero, sin barra",
          bool(wiz.visor.vertical.grid_info()), False)
        top.destroy()

    # Cuando «Conexión» no cabe por mucho que se estire, la barra es obligatoria:
    # es la comprobación de que un recorte nunca es silencioso. También va por
    # nombre: al abrirse, el asistente ya no enseña ese paso sino el del
    # dispositivo, que sí cabe.
    #
    # Se afirma **también que no cabe**, y no solo que hay barra: el día que el
    # paso adelgace lo bastante para entrar, esta comprobación se quedaría sin
    # asunto y pasaría sola sin comprobar nada. Es justo lo que pasó al escalar
    # el ancho de corte de los párrafos: en una 1080p al 200 % el mismo texto
    # cabe ahora en menos líneas, y este caso dejó de desbordar.
    #
    # Por eso el alto de la pantalla se SACA de lo que el paso pide, en vez de
    # escribir aquí una resolución concreta: cuánto pide depende de la letra del
    # sistema, que no es la misma en Windows que en el equipo de al lado, así que
    # una 1366x768 al 200 % desborda en una y entra de sobra en la otra —y el
    # caso fallaba sin que nada estuviera roto—. Con la mitad de lo que pide, la
    # premisa la fija el test y no la tipografía de quien lo ejecuta.
    pantalla(3840, 2160, 2.6667)
    top = tk.Toplevel(raiz)
    top.withdraw()
    wiz = tk_install.build(top)
    wiz.indice = PASO["Conexión"]
    wiz.repintar()
    top.update_idletasks()
    pide = wiz.visor.interior.winfo_reqheight()
    top.destroy()

    pantalla(1366, max(200, pide // 2), 2.6667)
    top = tk.Toplevel(raiz)
    top.withdraw()
    wiz = tk_install.build(top)
    wiz.indice = PASO["Conexión"]
    wiz.repintar()
    top.update_idletasks()
    no_cabe = wiz.visor.interior.winfo_reqheight() > wiz.visor._medida()[1]
    c("en una pantalla que no da para «Conexión», se desplaza con su barra",
      (no_cabe, bool(wiz.visor.vertical.grid_info())), (True, True))
    top.destroy()

    # Y en las pantallas apretadas de verdad, lo que sí es invariante haya o no
    # desbordamiento: que nada quede fuera del recuadro sin una barra que lo
    # enseñe.
    for nombre, ancho, alto in (("1366x768 al 200 %", 1366, 768),
                                ("1024x600 al 200 %", 1024, 600)):
        pantalla(ancho, alto, 2.6667)
        top = tk.Toplevel(raiz)
        top.withdraw()
        wiz = tk_install.build(top)
        wiz.indice = PASO["Conexión"]
        wiz.repintar()
        top.update_idletasks()
        c(f"{nombre}: «Conexión» no se recorta en silencio",
          recortado(wiz.visor), False)
        top.destroy()

    # --- los diálogos -----------------------------------------------------------------
    REAL_MOSTRAR, REAL_WAIT = tk_pairs.mostrar, tk.Toplevel.wait_window
    try:
        for nombre, ancho, alto, escala in PANTALLAS:
            with sandbox():
                model.CONFIG_FILE.write_text(config_file.dumps(BASE), encoding="utf-8")
                cfg = model.parse_config(BASE)
                for que, fabricar in (
                        ("la pantalla de parejas",
                         lambda: tk_pairs.open_dialog(raiz, cfg)),
                        ("el formulario de una pareja",
                         lambda: tk_pairs.formulario(raiz, dict(BASE), "pareja0",
                                                     dict(BASE["pair"][0]))),
                        ("el editor de flags",
                         lambda: tk_pairs.flags_form(raiz, "Flags", "pareja0", {},
                                                     [], "bisync", {}))):
                    entra, corta = medir_dialogo(fabricar, ancho, alto, escala)
                    c(f"{nombre}: {que} cabe", entra, True)
                    c(f"{nombre}: {que} no queda recortado", corta, False)

                # El explorador del remoto: una lista de carpetas con nombres
                # que los pone el usuario, y su diálogo de carpeta nueva.
                for que, fabricar in (
                        ("el explorador del remoto",
                         lambda: tk_pairs.explorador_remoto(raiz, "nas",
                                                            "/datos/documentos")),
                        ("la carpeta nueva",
                         lambda: tk_pairs.pedir_texto(
                             raiz, "Nueva carpeta",
                             "Se creará dentro de nas:/datos/documentos."))):
                    entra, corta = medir_dialogo(fabricar, ancho, alto, escala)
                    c(f"{nombre}: {que} cabe", entra, True)
                    c(f"{nombre}: {que} no queda recortado", corta, False)

                # La flota crece con cada dispositivo y con lo largo que sea su
                # nombre, que lo pone el usuario.
                for que, fabricar in (
                        ("la flota",
                         lambda: tk_fleet.open_dialog(raiz, cfg, dict(BASE))),
                        ("el nombre del dispositivo",
                         lambda: tk_fleet.pedir_nombre(
                             raiz, "el pendrive de la oficina de arriba"))):
                    entra, corta = medir_dialogo(fabricar, ancho, alto, escala,
                                                 modulo=tk_fleet)
                    c(f"{nombre}: {que} cabe", entra, True)
                    c(f"{nombre}: {que} no queda recortado", corta, False)

                # «Reparación» es la pantalla que más crece de todas: una fila
                # por avería, con su explicación, y debajo la lista de conflictos
                # con cada fichero y cada versión. Se mide con las doce parejas
                # sin baseline —o sea, con una avería por pareja— y con varios
                # conflictos de ruta larga, que es lo que la estira.
                pareja0 = cfg.pairs[0]
                for i in range(6):
                    carpeta = pareja0.local_abs / "documentos" / f"proyecto-{i}" / "borradores"
                    carpeta.mkdir(parents=True, exist_ok=True)
                    (carpeta / f"informe-trimestral-{i}.docx").write_text("a", encoding="utf-8")
                    (carpeta / f"informe-trimestral-{i}.docx.conflicto-remoto1").write_text(
                        "b", encoding="utf-8")
                conflicts.actualizar_pareja(pareja0)
                entra, corta = medir_dialogo(
                    lambda: tk_repair.open_dialog(raiz, cfg, lambda *a: None),
                    ancho, alto, escala, modulo=tk_repair)
                c(f"{nombre}: la pantalla de reparación cabe", entra, True)
                c(f"{nombre}: la pantalla de reparación no queda recortada", corta, False)

                # La de actualizar crece con las notas de la release, que las
                # escribe quien publica y aquí no las controla nadie: se mide con
                # las más largas que se enseñan (`tk_update` recorta a 1200).
                for que, notas in (("la pantalla de actualizar", "Arreglado esto."),
                                   ("la pantalla de actualizar con notas largas",
                                    "Una línea de novedades. " * 60)):
                    rel = update.Release("v9.9.9", "9.9.9", "La novena",
                                         "https://x/9", "2026-08-28T08:12:13Z", notas)
                    entra, corta = medir_dialogo(
                        lambda r=rel: tk_update.open_dialog(raiz, r),
                        ancho, alto, escala, modulo=tk_update)
                    c(f"{nombre}: {que} cabe", entra, True)
                    c(f"{nombre}: {que} no queda recortado", corta, False)

                # La de componentes crece con una fila por componente: se mide
                # con el peor caso posible, las cuatro plataformas con sus dos
                # componentes cada una.
                pends = [components.Pendiente(p, que, "v0.0.1 (20200101)",
                                              "v9.9.9 (20260901)")
                         for p in pins.PLATAFORMAS
                         for que in (components.RCLONE, components.PYTHON)]
                entra, corta = medir_dialogo(
                    lambda: tk_update.open_components_dialog(raiz, pends),
                    ancho, alto, escala, modulo=tk_update)
                c(f"{nombre}: la pantalla de componentes cabe", entra, True)
                c(f"{nombre}: la pantalla de componentes no queda recortada",
                  corta, False)

                # «Ajustes»: una tarjeta con una entrada por acción, que crece
                # con cada una que se le añada.
                entra, corta = medir_dialogo(
                    lambda: tk_doctor.open_dialog(raiz, cfg, lambda *a: None),
                    ancho, alto, escala, modulo=tk_doctor)
                c(f"{nombre}: la pantalla de Ajustes cabe", entra, True)
                c(f"{nombre}: la pantalla de Ajustes no queda recortada",
                  corta, False)

                # Versiones: dos tarjetas con una ruta larga cada una, más el
                # desplegable de parejas. Se mide con y sin parejas versionadas,
                # porque el caso vacío es un párrafo y el otro son dos tarjetas.
                for que, datos in (
                        ("la pantalla de versiones", [
                            {"name": f"pareja{i}", "local": f"sync-data/p{i}",
                             "remote_path": f"/R/p{i}", "mode": "bisync",
                             "versions": True} for i in range(12)]),
                        ("la pantalla de versiones sin ninguna", BASE["pair"])):
                    cfg_v = model.parse_config({"defaults": BASE["defaults"],
                                                "pair": datos})
                    entra, corta = medir_dialogo(
                        lambda c_=cfg_v: tk_versions.open_dialog(raiz, c_),
                        ancho, alto, escala, modulo=tk_versions)
                    c(f"{nombre}: {que} cabe", entra, True)
                    c(f"{nombre}: {que} no queda recortada", corta, False)

                # El nombre y el icono de la unidad: una fila de muestras de
                # color que miden en píxeles de la pantalla (`icons.px`), y
                # debajo el resto de opciones y dos párrafos de notas.
                for estado_v in VOLUMENES:
                    volumen.leer = lambda e_=estado_v: e_
                    que = "con VeraCrypt" if estado_v.fisica else "sin contenedor"
                    entra, corta = medir_dialogo(
                        lambda: tk_volumen.open_dialog(raiz),
                        ancho, alto, escala, modulo=tk_volumen)
                    c(f"{nombre}: la ventana del nombre e icono ({que}) cabe",
                      entra, True)
                    c(f"{nombre}: la ventana del nombre e icono ({que}) no queda "
                      "recortada", corta, False)

                # El código de emparejamiento: el único dibujo de la aplicación
                # que mide en píxeles y no puede encoger —un módulo por debajo
                # de dos píxeles no lo lee ninguna cámara—, así que en una
                # pantalla pequeña la respuesta correcta es la barra.
                entra, corta = medir_dialogo(
                    lambda: tk_qr.open_dialog(raiz, dict(BASE)),
                    ancho, alto, escala, modulo=tk_qr)
                c(f"{nombre}: la ventana de emparejar cabe", entra, True)
                c(f"{nombre}: la ventana de emparejar no queda recortada",
                  corta, False)

        # La ficha de la flota cambia con la fila elegida, y el recuadro se
        # encaja una sola vez, al abrir: lo que se reservó entonces tiene que
        # valer para todas. Se recorre la lista entera y se mira lo que PIDE el
        # contenido, no lo que mide el recuadro —ese no cambia después de
        # encajar, pase lo que pase dentro—. Sin la reserva, elegir el peor
        # hacía crecer el contenido y aparecer una barra que al abrir no estaba.
        for nombre, ancho, alto, escala in (("1080p", 1920, 1080, 1.3333),
                                            ("1080p al 200 %", 1920, 1080, 2.6667)):
            with sandbox():
                model.CONFIG_FILE.write_text(config_file.dumps(BASE), encoding="utf-8")
                cfg = model.parse_config(BASE)
                pantalla(ancho, alto, escala)
                recorrido: dict = {"cortes": [], "pide": set(), "barras": set()}

                def recorrer(dlg, parent=None):
                    dlg.visor.encajar(dlg)
                    pila, arbol = [dlg], None
                    while pila and arbol is None:
                        w = pila.pop()
                        pila += list(w.winfo_children())
                        arbol = w if isinstance(w, ttk.Treeview) else None
                    for iid in arbol.get_children():
                        arbol.selection_set(iid)
                        dlg.update()
                        visor = dlg.visor
                        recorrido["cortes"].append(recortado(visor))
                        recorrido["pide"].add((visor.interior.winfo_reqwidth(),
                                               visor.interior.winfo_reqheight()))
                        recorrido["barras"].add((bool(visor.vertical.grid_info()),
                                                 bool(visor.horizontal.grid_info())))

                previo = tk_fleet.mostrar
                tk_fleet.mostrar = recorrer
                tk.Toplevel.wait_window = lambda self, *a, **k: None
                try:
                    tk_fleet.open_dialog(raiz, cfg, dict(BASE))
                finally:
                    tk_fleet.mostrar = previo
                c(f"{nombre}: se recorre la flota entera",
                  len(recorrido["cortes"]), len(FLOTA))
                c(f"{nombre}: ninguna ficha queda cortada", any(recorrido["cortes"]), False)
                c(f"{nombre}: lo que pide la ventana no cambia al elegir otra",
                  len(recorrido["pide"]), 1)
                c(f"{nombre}: ni aparece o desaparece una barra",
                  len(recorrido["barras"]), 1)
    finally:
        tk_pairs.mostrar, tk.Toplevel.wait_window = REAL_MOSTRAR, REAL_WAIT
finally:
    uitk.pantalla_util = PANTALLA_REAL
    raiz.tk.call("tk", "scaling", ESCALA_REAL)

raiz.destroy()
sys.exit(c.report())
