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

from install import CONTAINER_NAME, InstallError, crypto

from . import theme
from .tk import TITLE, working

AVISO_AUTOARRANQUE = (
    "Con contenedor, el arranque automático necesita que VeraCrypt lo monte al "
    "conectar el dispositivo: el vigilante solo ve la unidad una vez montada. "
    "En el "
    "último paso se puede dejar configurado."
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
    ttk.Label(panel, justify="left", wraplength=theme.medida(760), text=(
        f"Contenedor: {contenedor}\n"
        + ("Ya existe: se puede montar con su contraseña."
           if existe else "Todavía no existe: se va a crear."))).grid(
        row=0, column=0, sticky="w")

    formulario = ttk.Frame(panel)
    formulario.grid(row=1, column=0, sticky="w", pady=(10, 0))
    fila = 0

    tam = tk.StringVar(value=crypto.suggested_size(_libre(estado.device)))
    sistema = tk.StringVar(value=crypto.FILESYSTEMS[0])
    if not existe:
        ttk.Label(formulario, text="Tamaño:").grid(row=fila, column=0, sticky="w")
        ttk.Entry(formulario, textvariable=tam, width=10).grid(row=fila, column=1, sticky="w")
        ttk.Label(formulario, foreground=theme.TINTA3,
                  text=f"libre en la unidad: {_libre(estado.device) / 1024**3:.1f} GiB "
                       f"— admite 20G, 500M o 'max'").grid(
            row=fila, column=2, sticky="w", padx=(10, 0))
        fila += 1
        ttk.Label(formulario, text="Sistema de ficheros:").grid(row=fila, column=0, sticky="w")
        ttk.Combobox(formulario, textvariable=sistema, state="readonly", width=8,
                     values=list(crypto.FILESYSTEMS)).grid(row=fila, column=1, sticky="w")
        ttk.Label(formulario, foreground=theme.TINTA3,
                  text="exFAT es lo más portable entre Windows, Linux y macOS").grid(
            row=fila, column=2, sticky="w", padx=(10, 0))
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

    ttk.Label(panel, foreground=theme.AVISO, wraplength=theme.medida(760), justify="left",
              text=AVISO_AUTOARRANQUE).grid(row=2, column=0, sticky="w", pady=(10, 0))

    def crear_y_montar() -> None:
        password = pw1.get()
        if not password:
            messagebox.showwarning(TITLE, "Falta la contraseña.", parent=wiz.root)
            return
        if not existe and password != pw2.get():
            messagebox.showwarning(TITLE, "Las dos contraseñas no coinciden.",
                                   parent=wiz.root)
            return
        try:
            if not existe:
                bytes_ = crypto.size_to_bytes(tam.get(), _libre(estado.device))
                ok, res = working(
                    wiz.root, "creando el contenedor",
                    lambda: crypto.create_container(
                        estado.veracrypt, contenedor, bytes_, password, sistema.get()),
                    f"Creando {contenedor} ({bytes_ / 1024**3:.1f} GiB).\n"
                    "Según el tamaño y la unidad, esto puede tardar bastante.")
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
        hecho()
        wiz.repintar()

    botones = ttk.Frame(panel)
    botones.grid(row=3, column=0, sticky="w", pady=(12, 0))
    ttk.Button(botones, text="Montar" if existe else "Crear y montar",
               command=crear_y_montar).grid(row=0, column=0)
    if estado.device_root and estado.mounted_by_us:
        ttk.Label(botones, foreground=theme.OK,
                  text=f"montado en {estado.device_root}").grid(row=0, column=1, padx=(12, 0))


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
        "abre el asistente de Windows, se comprueba después cómo quedó, y se "
        "ofrece guardar la clave de recuperación en el remoto.")).grid(
        row=0, column=0, sticky="w")

    marca = ttk.Label(panel, wraplength=theme.medida(760), justify="left")
    marca.grid(row=1, column=0, sticky="w", pady=(10, 0))

    def pintar_estado(st) -> None:
        color = "#116611" if (st.known and st.encrypted and st.unlocked) else "#775500"
        marca.configure(text=f"Estado de {letra}: {st.resumen}", foreground=color)

    pintar_estado(crypto.BitLockerStatus(False, detail="sin comprobar todavía"))

    def abrir() -> None:
        try:
            crypto.open_bitlocker_setup(letra)
        except InstallError as e:
            messagebox.showerror(TITLE, str(e), parent=wiz.root)

    def comprobar() -> None:
        ok, res = working(
            wiz.root, "comprobando BitLocker",
            lambda: crypto.bitlocker_status(letra, elevate=True),
            "Consultando el estado de BitLocker.\nWindows va a pedir permisos: "
            "es una consulta de solo lectura.")
        if not ok:
            messagebox.showerror(TITLE, f"{res}", parent=wiz.root)
            return
        pintar_estado(res)
        if res.known and res.encrypted and res.unlocked:
            estado.device_root = estado.device
            hecho()

    def subir_clave() -> None:
        ok, texto = working(
            wiz.root, "leyendo la clave de recuperación",
            lambda: crypto.bitlocker_recovery_key(letra),
            "Leyendo la clave de recuperación (Windows pedirá permisos).")
        if not ok or not str(texto).strip():
            messagebox.showwarning(TITLE, (
                "No he podido leer ninguna clave de recuperación. Guárdala tú "
                "desde el asistente de BitLocker y súbela a mano al remoto."),
                parent=wiz.root)
            return
        from install import deploy
        ok, res = working(
            wiz.root, "subiendo la clave al remoto",
            lambda: deploy.upload_recovery_key(wiz.rclone, str(texto), letra,
                                               wiz.perfil.recovery_path),
            "Subiendo la clave de recuperación al remoto.")
        if ok:
            messagebox.showinfo(TITLE, f"Guardada en {res}.\n\nEstá en el remoto y "
                                "no en el dispositivo a propósito: dentro del "
                                "volumen que descifra no serviría de nada.",
                                parent=wiz.root)
        else:
            messagebox.showerror(TITLE, str(res), parent=wiz.root)

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
            ("Subir la clave de recuperación", subir_clave),
            ("Seguir de todas formas", seguir_igual))):
        ttk.Button(botones, text=texto, command=accion).grid(row=0, column=i, padx=(0, 6))
