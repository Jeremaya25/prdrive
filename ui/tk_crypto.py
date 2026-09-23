#!/usr/bin/env python3
"""
tk_crypto.py — El paso de cifrado del asistente de instalación.

Solo dibuja. Todo lo que habla con VeraCrypt o con BitLocker está en
`install/crypto.py`, igual que `tk_pairs.py` no sabe nada de lo que hace
`pair_editor.py`. Está aparte de `tk_install.py` porque es, con diferencia, la
pantalla más enredada: dos tecnologías distintas, con dos repartos de trabajo
distintos, y la única del asistente que maneja una contraseña.

Reglas de esta pantalla:

  * La passphrase **nunca** sale de aquí más que hacia `install.crypto`. No se
    pinta, no se registra y no se pasa a la ventana de salida (que es lo que
    enseña las órdenes de rclone): las órdenes de VeraCrypt van por
    `ui.tk.working()`, que solo enseña una barra.
  * Nada se da por bueno sin comprobarlo. Un contenedor se da por montado cuando
    se puede leer, y de BitLocker se dice «no lo he podido comprobar» tal cual
    cuando no hay permisos, en vez de suponer que todo fue bien.
"""

from __future__ import annotations

from pathlib import Path

from install import CONTAINER_NAME, IS_WIN, InstallError, crypto

from . import theme
from .tk import TITLE, bloque_aviso, working

AVISO_AUTOARRANQUE = (
    "Con contenedor, el programa vive dentro: hasta que el contenedor esté "
    f"abierto, este equipo solo ve el fichero {CONTAINER_NAME}. Ábrelo con VeraCrypt "
    "antes de usar el dispositivo, y ciérralo antes de quitarlo."
)


def dibujar(cuerpo, wiz) -> None:
    """Pinta el paso de cifrado dentro de `cuerpo`. `wiz` es el asistente."""
    import tkinter as tk
    from tkinter import ttk

    estado = wiz.state
    ttk.Label(cuerpo, justify="left", wraplength=theme.medida(760), text=(
        f"Destino elegido: {estado.device}\n"
        "El cifrado se elige ahora porque decide DÓNDE va a vivir la estructura "
        "del dispositivo: sin cifrar o con BitLocker, en el propio volumen; con "
        "VeraCrypt, "
        "dentro del contenedor.")).grid(row=0, column=0, sticky="w", pady=(0, 10))

    modo = tk.StringVar(value=estado.encryption)
    fila_modos = ttk.Frame(cuerpo)
    fila_modos.grid(row=1, column=0, sticky="w")
    for i, (valor, texto) in enumerate((
            ("veracrypt", "VeraCrypt (contenedor portable)"),
            ("bitlocker", "BitLocker (el volumen entero, solo Windows)"),
            ("none", "Sin cifrar"))):
        ttk.Radiobutton(fila_modos, text=texto, value=valor,
                        variable=modo).grid(row=0, column=i, sticky="w", padx=(0, 16))

    panel = ttk.Frame(cuerpo)
    panel.grid(row=2, column=0, sticky="w", pady=(12, 0))

    resumen = ttk.Label(cuerpo, foreground=theme.AVISO, justify="left",
                        wraplength=theme.medida(760))
    resumen.grid(row=3, column=0, sticky="w", pady=(12, 0))

    def refrescar_resumen() -> None:
        if estado.device_root:
            resumen.configure(
                text=f"✔ El programa y los datos irán a: {estado.device_root}",
                foreground=theme.OK)
        else:
            resumen.configure(text="Todavía no hay un destino listo para sembrar.",
                              foreground=theme.AVISO)
        wiz.revisar()

    def repintar(*_) -> None:
        for hijo in panel.winfo_children():
            hijo.destroy()
        estado.encryption = modo.get()
        {"veracrypt": _panel_veracrypt,
         "bitlocker": _panel_bitlocker}.get(modo.get(), _panel_ninguno)(
            panel, wiz, refrescar_resumen)
        refrescar_resumen()

    modo.trace_add("write", repintar)
    repintar()


# ---------------------------------------------------------------------------
# Sin cifrar
# ---------------------------------------------------------------------------

def _panel_ninguno(panel, wiz, hecho) -> None:
    from tkinter import ttk

    estado = wiz.state
    ttk.Label(panel, justify="left", wraplength=theme.medida(760),
              foreground=theme.PELIGRO, text=(
        "El dispositivo quedará SIN CIFRAR. Ten en cuenta que dentro va a vivir la clave "
        "privada de tu remoto (.prdrive/keys/): quien encuentre el dispositivo "
        "tiene acceso a tus datos hasta que revoques esa clave.")).grid(
        row=0, column=0, sticky="w")

    def usar() -> None:
        estado.device_root = estado.device
        estado.container = None
        estado.mounted_by_us = False
        hecho()

    ttk.Button(panel, text="Entendido, usar el dispositivo tal cual",
               command=usar).grid(row=1, column=0, sticky="w", pady=(10, 0))


# ---------------------------------------------------------------------------
# VeraCrypt
# ---------------------------------------------------------------------------

def _panel_veracrypt(panel, wiz, hecho) -> None:
    import tkinter as tk
    from tkinter import messagebox, ttk

    estado = wiz.state
    contenedor = Path(estado.device) / CONTAINER_NAME
    estado.container = contenedor
    estado.veracrypt = estado.veracrypt or crypto.find_veracrypt()

    if not estado.veracrypt:
        ttk.Label(panel, foreground=theme.PELIGRO, justify="left",
                  wraplength=theme.medida(760), text=(
            "No encuentro VeraCrypt en este equipo. Instálalo desde "
            "veracrypt.jp/en/Downloads.html, o dime dónde está:")).grid(
            row=0, column=0, sticky="w")
        ruta = tk.StringVar()
        fila = ttk.Frame(panel)
        fila.grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(fila, textvariable=ruta, width=52).grid(row=0, column=0)

        def buscar() -> None:
            estado.veracrypt = crypto.find_veracrypt(ruta.get().strip() or None)
            if estado.veracrypt:
                hecho()
                wiz.repintar()
            else:
                messagebox.showerror(TITLE, "Ahí tampoco está VeraCrypt.",
                                     parent=wiz.root)
        ttk.Button(fila, text="Buscar aquí", command=buscar).grid(row=0, column=1, padx=6)
        return

    existe = contenedor.is_file()
    libre = _libre(estado.device)
    ttk.Label(panel, justify="left", wraplength=theme.medida(760), text=(
        f"Contenedor: {contenedor}\n"
        + ("Ya existe: se puede montar con su contraseña."
           if existe else "Todavía no existe: se va a crear."))).grid(
        row=0, column=0, sticky="w")

    # Una instalación sin cifrar en la raíz física: la de antes de un
    # «Reinstalar desde cero». El contenedor va al lado y ella se queda, con la
    # clave en claro. Se dice antes de crear nada, y no se borra sola.
    restos = crypto.restos_en_claro(estado.device)
    if restos:
        bloque_aviso(panel, crypto.aviso_restos(restos), ancho=720,
                     tipo="Rojo").grid(row=1, column=0, sticky="ew", pady=(10, 0))

    formulario = ttk.Frame(panel)
    formulario.grid(row=2, column=0, sticky="w", pady=(10, 0))
    fila = 0

    # La pregunta que decide si esto tarda segundos o media hora. Se rehace en
    # cada repintado a propósito —es una consulta al sistema de ficheros, ni
    # escribe ni tarda, y cachearla daría la respuesta de la unidad anterior si
    # se cambia de destino—. Lo que sí se recuerda en el estado es la MEDIDA de
    # velocidad, que sí escribe en la unidad: ver `refrescar_espera`.
    dispersos = crypto.soporta_dispersos(estado.device) if not existe else False
    # El sistema de ficheros de la unidad, por lo mismo: en FAT32 un fichero no
    # llega a 4 GiB, y el contenedor es un fichero (`crypto.tope_contenedor`).
    fs = crypto.sistema_de_ficheros(estado.device) if not existe else ""
    tope = crypto.tope_contenedor(fs)
    dinamico = tk.BooleanVar(value=dispersos if estado.dinamico is None
                             else (estado.dinamico and dispersos))
    tam = tk.StringVar(value=crypto.suggested_size(libre, dinamico.get(), tope))
    sistema = tk.StringVar(value=crypto.FILESYSTEMS[0])
    espera = ttk.Label(formulario, foreground=theme.TINTA3, justify="left",
                       wraplength=theme.medida(560))

    if not existe:
        ttk.Label(formulario, text="Tamaño:").grid(row=fila, column=0, sticky="w")
        ttk.Entry(formulario, textvariable=tam, width=10).grid(row=fila, column=1, sticky="w")
        ttk.Label(formulario, foreground=theme.AVISO if tope else theme.TINTA3,
                  text=(f"libre en la unidad: {libre / 1024**3:.1f} GiB "
                        + (f"— es {fs}: como mucho {tope // 1024**2}M"
                           if tope else "— admite 20G, 500M o 'max'"))).grid(
            row=fila, column=2, sticky="w", padx=(10, 0))
        fila += 1
        ttk.Label(formulario, text="Sistema de ficheros:").grid(row=fila, column=0, sticky="w")
        ttk.Combobox(formulario, textvariable=sistema, state="readonly", width=8,
                     values=list(crypto.FILESYSTEMS)).grid(row=fila, column=1, sticky="w")
        ttk.Label(formulario, foreground=theme.TINTA3,
                  text="exFAT es lo más portable entre Windows, Linux y macOS").grid(
            row=fila, column=2, sticky="w", padx=(10, 0))
        fila += 1

        ttk.Checkbutton(
            formulario, variable=dinamico, state="normal" if dispersos else "disabled",
            text="Contenedor dinámico: solo ocupa lo que guardes").grid(
            row=fila, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(formulario, foreground=theme.TINTA3, justify="left",
                  wraplength=theme.medida(360), text=(
            "sin negación plausible, y si la unidad se llena el volumen da "
            "errores de E/S" if dispersos else
            f"esta unidad ({fs or 'sin identificar'}) no admite ficheros "
            "dispersos: el contenedor hay que escribirlo entero")).grid(
            row=fila, column=2, sticky="w", padx=(10, 0), pady=(6, 0))
        fila += 1
        espera.grid(row=fila, column=0, columnspan=3, sticky="w", pady=(6, 0))
        fila += 1

    ttk.Label(formulario, text="Contraseña:").grid(row=fila, column=0, sticky="w")
    pw1 = tk.StringVar()
    ttk.Entry(formulario, textvariable=pw1, show="•", width=32).grid(
        row=fila, column=1, columnspan=2, sticky="w")
    fila += 1

    pw2 = tk.StringVar()
    if not existe:
        ttk.Label(formulario, text="Repítela:").grid(row=fila, column=0, sticky="w")
        ttk.Entry(formulario, textvariable=pw2, show="•", width=32).grid(
            row=fila, column=1, columnspan=2, sticky="w")
        fila += 1

    ttk.Label(formulario, foreground=theme.PELIGRO, justify="left",
              wraplength=theme.medida(560), text=(
        "Esta contraseña no se guarda en ningún sitio. Si la pierdes, el "
        "contenedor no se recupera: apúntala en tu gestor de contraseñas ANTES "
        "de seguir.")).grid(row=fila, column=0, columnspan=3, sticky="w", pady=(8, 0))
    fila += 1

    def refrescar_espera(*_) -> None:
        """Cuánto va a tardar esto, medido, no adivinado.

        La medida escribe en la unidad, así que se hace UNA vez y se guarda en el
        estado; lo que se recalcula al cambiar el tamaño es la división."""
        estado.dinamico = bool(dinamico.get())
        if estado.dinamico:
            espera.configure(text="Creación prácticamente inmediata.")
            return
        try:
            bytes_ = crypto.size_to_bytes(tam.get(), libre, tope)
        except InstallError as e:
            espera.configure(text=str(e))
            return
        if estado.velocidad_escritura is None:
            # 0.0 es «medido y no se ha podido»: sin eso, cada tecla del tamaño
            # volvería a escribir la sonda en la unidad.
            estado.velocidad_escritura = crypto.medir_escritura(estado.device) or 0.0
        segundos = (bytes_ / estado.velocidad_escritura
                    if estado.velocidad_escritura else None)
        espera.configure(text=(
            f"Hay que escribir el contenedor entero: {crypto.describir_espera(segundos)}."))

    def al_cambiar_dinamico(*_) -> None:
        tam.set(crypto.suggested_size(libre, bool(dinamico.get()), tope))
        refrescar_espera()

    if not existe:
        dinamico.trace_add("write", al_cambiar_dinamico)
        tam.trace_add("write", refrescar_espera)
        refrescar_espera()

    # El traveler disk es cosa de Windows: en Linux y macOS VeraCrypt necesita
    # instalarse (driver y FUSE) y no hay nada que llevar. Ni se ofrece.
    traveler = tk.BooleanVar(value=estado.traveler and IS_WIN)
    if IS_WIN:
        ttk.Checkbutton(
            panel, variable=traveler,
            text="Dejar VeraCrypt en el dispositivo, para montarlo en equipos que "
                 "no lo tengan").grid(row=3, column=0, sticky="w", pady=(10, 0))

    ttk.Label(panel, foreground=theme.AVISO, wraplength=theme.medida(760), justify="left",
              text=AVISO_AUTOARRANQUE).grid(row=4, column=0, sticky="w", pady=(6, 0))

    def crear_y_montar() -> None:
        password = pw1.get()
        # Al crear, lo que diría VeraCrypt sin `/silent`; al montar uno que ya
        # existe, basta con que haya algo: la contraseña ya es la que es.
        error, aviso = (crypto.revisar_contrasena(password) if not existe
                        else (None if password else "Falta la contraseña.", None))
        if error:
            messagebox.showwarning(TITLE, error, parent=wiz.root)
            return
        if not existe and password != pw2.get():
            messagebox.showwarning(TITLE, "Las dos contraseñas no coinciden.",
                                   parent=wiz.root)
            return
        # «No» por defecto, como la pregunta de VeraCrypt (MB_DEFBUTTON2).
        if aviso and not messagebox.askyesno(TITLE, aviso, default="no",
                                             icon="warning", parent=wiz.root):
            return
        estado.dinamico = bool(dinamico.get()) and dispersos
        estado.traveler = bool(traveler.get())
        try:
            if not existe:
                bytes_ = crypto.size_to_bytes(tam.get(), libre, tope)
                ok, res = working(
                    wiz.root, "creando el contenedor",
                    lambda: crypto.create_container(
                        estado.veracrypt, contenedor, bytes_, password,
                        sistema.get(), estado.dinamico),
                    f"Creando {contenedor} ({bytes_ / 1024**3:.1f} GiB).\n"
                    + ("Es un contenedor dinámico: esto va a ser rápido."
                       if estado.dinamico else espera.cget("text")))
                if not ok:
                    raise res if isinstance(res, Exception) else InstallError("Falló.")

            ok, res = working(
                wiz.root, "montando el contenedor",
                lambda: crypto.mount_container(estado.veracrypt, contenedor, password),
                "Montando el contenedor.\nVeraCrypt puede pedir permisos de "
                "administrador: acepta el aviso.")
            if not ok:
                raise res if isinstance(res, Exception) else InstallError("Falló.")
        except InstallError as e:
            messagebox.showerror(TITLE, str(e), parent=wiz.root)
            return
        except Exception as e:                       # noqa: BLE001 — se enseña tal cual
            messagebox.showerror(TITLE, f"{type(e).__name__}: {e}", parent=wiz.root)
            return

        estado.device_root = Path(res)
        estado.mounted_by_us = True
        if estado.traveler:
            _llevar_veracrypt(wiz)
        hecho()
        wiz.repintar()

    botones = ttk.Frame(panel)
    botones.grid(row=5, column=0, sticky="w", pady=(12, 0))
    ttk.Button(botones, text="Montar" if existe else "Crear y montar",
               command=crear_y_montar).grid(row=0, column=0)
    if estado.device_root and estado.mounted_by_us:
        ttk.Label(botones, foreground=theme.OK,
                  text=f"montado en {estado.device_root}").grid(row=0, column=1, padx=(12, 0))


def _llevar_veracrypt(wiz) -> None:
    """Copia VeraCrypt al volumen. **Mejor esfuerzo**: no puede tumbar la instalación.

    Va a la raíz FÍSICA, fuera del contenedor —dentro haría falta VeraCrypt para
    llegar a VeraCrypt—, y es lo único de este paso que puede fallar sin que
    importe: sin traveler disk el dispositivo funciona igual en cualquier equipo
    que tenga VeraCrypt instalado."""
    from install import traveler

    estado = wiz.state
    try:
        traveler.instalar(estado.veracrypt, estado.device)
        traveler.write_autorun(estado.device)
    except InstallError as e:
        wiz.aviso("El dispositivo ha quedado montado, pero no he podido dejar "
                  f"VeraCrypt dentro:\n\n{e}\n\nSe puede reintentar desde el "
                  "último paso.")


def _libre(root) -> int:
    import shutil
    try:
        return shutil.disk_usage(str(root)).free
    except OSError:
        return 0


# ---------------------------------------------------------------------------
# BitLocker
# ---------------------------------------------------------------------------

def _panel_bitlocker(panel, wiz, hecho) -> None:
    from tkinter import messagebox, ttk

    estado = wiz.state
    estado.container = None          # con BitLocker no hay contenedor que montar
    estado.mounted_by_us = False
    letra = str(estado.device)[0] if estado.device else ""

    ttk.Label(panel, justify="left", wraplength=theme.medida(760), text=(
        "Cifrar lo hace Windows, no el instalador: automatizarlo exige permisos "
        "de administrador, tarda mucho y falla distinto en cada edición. Aquí se "
        "abre el asistente de Windows y se comprueba después cómo quedó.\n\n"
        "Guarda la clave de recuperación donde te diga Windows, pero NO dentro "
        "de este volumen: ahí no serviría de nada.")).grid(
        row=0, column=0, sticky="w")

    marca = ttk.Label(panel, wraplength=theme.medida(760), justify="left")
    marca.grid(row=1, column=0, sticky="w", pady=(10, 0))

    def pintar_estado(st) -> None:
        color = "#116611" if (st.known and st.protected) else "#775500"
        marca.configure(text=f"Estado de {letra}: {st.resumen}", foreground=color)

    pintar_estado(crypto.BitLockerStatus(False, detail="sin comprobar todavía"))

    def abrir() -> None:
        try:
            crypto.open_bitlocker_setup(letra)
        except InstallError as e:
            messagebox.showerror(TITLE, str(e), parent=wiz.root)

    def comprobar() -> None:
        res = crypto.bitlocker_status(letra)
        pintar_estado(res)
        if res.known and res.protected:
            estado.device_root = estado.device
            hecho()

    def seguir_igual() -> None:
        if not messagebox.askokcancel(TITLE, (
                "Vas a seguir sin haber comprobado que el volumen quedó "
                "cifrado.\n\nDentro va la clave privada de tu remoto."),
                parent=wiz.root):
            return
        estado.device_root = estado.device
        hecho()

    botones = ttk.Frame(panel)
    botones.grid(row=2, column=0, sticky="w", pady=(12, 0))
    for i, (texto, accion) in enumerate((
            ("Abrir el asistente de Windows", abrir),
            ("Comprobar cómo quedó", comprobar),
            ("Seguir de todas formas", seguir_igual))):
        ttk.Button(botones, text=texto, command=accion).grid(row=0, column=i, padx=(0, 6))
