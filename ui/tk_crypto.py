#!/usr/bin/env python3
"""El paso de cifrado del asistente de instalación.

Solo dibuja. Todo lo que habla con VeraCrypt o con BitLocker está en
`install/crypto.py`, igual que `tk_pairs.py` no sabe nada de lo que hace
`pair_editor.py`. Está aparte de `tk_install.py` porque es, con diferencia, la
pantalla más enredada: dos tecnologías distintas, con dos repartos de trabajo
distintos, y la única del asistente que maneja una contraseña.

Reglas de esta pantalla:
- La passphrase **nunca** sale de aquí más que hacia `install.crypto`. No se
  pinta, no se registra y no se pasa a la ventana de salida (que es lo que
  enseña las órdenes de rclone): las órdenes de VeraCrypt van por
  `ui.tk.working()`, que solo enseña una barra y, al crear un contenedor fijo,
  cuánto lleva escrito la unidad.
- Nada se da por bueno sin comprobarlo. Un contenedor se da por montado cuando
  se puede leer y de BitLocker se dice «no lo he podido comprobar» tal cual
  cuando no hay permisos, en vez de suponer que todo fue bien.
- La sonda que mide lo que escribe la unidad (8 MiB con `fsync`) corre en otro
  hilo, una sola vez por volumen, y mientras escribe no se crea el contenedor:
  iría al lado de lo que está escribiendo.
"""

from __future__ import annotations

from pathlib import Path

from common import pins
from install import CONTAINER_NAME, IS_WIN, InstallError, crypto, veracrypt_bin

from . import theme
from .tk import TITLE, Sondeo, bloque_aviso, working

AVISO_AUTOARRANQUE = (
    "Con contenedor, el programa vive dentro: hasta abrirlo, un equipo solo ve "
    f"el fichero {CONTAINER_NAME}. Fuera quedan «Abrir PRDRIVE» y «Expulsar "
    "PRDRIVE» para hacerlo en cualquier equipo; y donde esté instalado el "
    "arranque automático, al conectar el dispositivo aparece directamente la "
    "contraseña de VeraCrypt."
)
"""Lo que se dice sobre dónde vive el programa cuando hay contenedor."""

def dibujar(cuerpo, wiz) -> None:
    """Pinta el paso de cifrado dentro de `cuerpo`.

    Args:
        cuerpo: Donde se pinta.
        wiz: El asistente.
    """
    import tkinter as tk
    from tkinter import ttk

    estado = wiz.state
    ttk.Label(cuerpo, justify="left", wraplength=theme.medida(760), style="Campo.TLabel",
              text=(
        f"Destino elegido: {estado.device}\n"
        "El cifrado se elige ahora porque decide DÓNDE va a vivir la estructura "
        "del dispositivo: sin cifrar o con BitLocker, en el propio volumen; con "
        "VeraCrypt, "
        "dentro del contenedor.")).grid(row=0, column=0, sticky="w", pady=(0, theme.E3))

    modo = tk.StringVar(value=estado.encryption)
    fila_modos = ttk.Frame(cuerpo)
    fila_modos.grid(row=1, column=0, sticky="w")
    for i, (valor, texto) in enumerate((
            ("veracrypt", "VeraCrypt (contenedor portable)"),
            ("bitlocker", "BitLocker (el volumen entero, solo Windows)"),
            ("none", "Sin cifrar"))):
        ttk.Radiobutton(fila_modos, text=texto, value=valor,
                        variable=modo).grid(row=0, column=i, sticky="w", padx=(0, theme.E4))

    panel = ttk.Frame(cuerpo)
    panel.grid(row=2, column=0, sticky="w", pady=(theme.E3, 0))

    resumen = ttk.Frame(cuerpo)
    resumen.grid(row=3, column=0, sticky="w", pady=(theme.E4, 0))

    def refrescar_resumen() -> None:
        """Dice a dónde irán el programa y los datos, en un chip.

        Revisa también los botones del asistente.
        """
        for hijo in resumen.winfo_children():
            hijo.destroy()
        if estado.device_root:
            theme.chip(resumen, f"El programa y los datos irán a: {estado.device_root}",
                       "Ok.").grid(row=0, column=0, sticky="w")
        else:
            theme.chip(resumen, "Todavía no hay un destino listo para sembrar",
                       "Aviso.").grid(row=0, column=0, sticky="w")
        wiz.revisar()

    def repintar(*_) -> None:
        """Pinta el panel de la forma de cifrar elegida."""
        for hijo in panel.winfo_children():
            hijo.destroy()
        estado.encryption = modo.get()
        {"veracrypt": _panel_veracrypt,
         "bitlocker": _panel_bitlocker}.get(modo.get(), _panel_ninguno)(
            panel, wiz, refrescar_resumen)
        refrescar_resumen()

    modo.trace_add("write", repintar)
    repintar()


def _panel_ninguno(panel, wiz, hecho) -> None:
    """Pinta el panel de «sin cifrar», con su advertencia."""
    from tkinter import ttk

    estado = wiz.state
    bloque_aviso(panel, (
        "El dispositivo quedará SIN CIFRAR\nDentro va a vivir la clave privada de tu "
        "remoto (.prdrive/keys/): quien encuentre el dispositivo tiene acceso a tus "
        "datos hasta que revoques esa clave."), tipo="Rojo", ancho=640).grid(
        row=0, column=0, sticky="ew")

    def usar() -> None:
        """Da por bueno el dispositivo tal cual."""
        estado.device_root = estado.device
        estado.container = None
        estado.mounted_by_us = False
        hecho()

    ttk.Button(panel, text="Entendido, usar el dispositivo tal cual",
               command=usar).grid(row=1, column=0, sticky="w", pady=(theme.E3, 0))


def _panel_veracrypt(panel, wiz, hecho) -> None:
    """Pinta el panel de VeraCrypt.

    Deja buscarlo o bajarlo y crear y montar el contenedor.
    """
    import tkinter as tk
    from tkinter import messagebox, ttk

    from . import lecturas_asistente

    estado = wiz.state
    contenedor = Path(estado.device) / CONTAINER_NAME
    estado.container = contenedor
    estado.veracrypt = estado.veracrypt or crypto.find_veracrypt()

    if not estado.veracrypt:
        # No hace falta instalar nada: el VeraCrypt Portable oficial en Windows,
        # el AppImage oficial en Linux, bajados y comprobados
        # (`install/veracrypt_bin.py`). En Linux montar sigue pidiendo la
        # contraseña de administrador, como con el instalado.
        bloque_aviso(panel, ancho=640, texto=(
            f"No hay VeraCrypt instalado en este equipo. Puedo usar el VeraCrypt "
            f"Portable oficial {pins.VERACRYPT_VERSION}, sin instalarlo: se "
            f"descarga (≈39 MB) y se comprueba contra el SHA-256 que fija este "
            f"programa antes de usarlo. O dime dónde tienes uno (una instalación "
            f"o un portable descomprimido):" if IS_WIN else
            f"No hay VeraCrypt instalado en este equipo. Puedo usar el AppImage "
            f"oficial de VeraCrypt {pins.VERACRYPT_VERSION}, sin instalarlo: se "
            f"descarga (≈13 MB) y se comprueba contra el SHA-256 que fija este "
            f"programa antes de usarlo. Para montar pedirá la contraseña de "
            f"administrador, igual que el instalado. O dime dónde está:")).grid(
            row=0, column=0, sticky="ew")
        ruta = tk.StringVar()
        fila = ttk.Frame(panel)
        fila.grid(row=1, column=0, sticky="w", pady=(theme.E2, 0))

        def descargar() -> None:
            """Baja VeraCrypt, lo comprueba y lo da por encontrado.

            Es el Portable en Windows y el AppImage en Linux.
            """
            ok, res = working(
                wiz.root, "descargando VeraCrypt",
                lambda: veracrypt_bin.para_este_equipo(),
                f"Descargando VeraCrypt {pins.VERACRYPT_VERSION} y comprobándolo.")
            estado.veracrypt = (crypto.find_veracrypt(res if IS_WIN else None)
                                if ok else None)
            if estado.veracrypt:
                hecho()
                wiz.repintar()
            else:
                messagebox.showerror(TITLE, (
                    f"No se ha podido usar el VeraCrypt Portable:\n\n{res}" if not ok
                    else "El VeraCrypt Portable no trae los ejecutables de este "
                         "equipo."), parent=wiz.root)

        ttk.Button(fila, text=("Descargar VeraCrypt Portable" if IS_WIN else
                               "Descargar VeraCrypt (AppImage)"),
                   style="Primary.TButton", command=descargar).grid(
            row=0, column=0, sticky="w", padx=(0, theme.E3))
        ttk.Entry(fila, textvariable=ruta, width=52).grid(row=0, column=1)

        def buscar() -> None:
            """Busca VeraCrypt en la carpeta escrita."""
            estado.veracrypt = crypto.find_veracrypt(ruta.get().strip() or None)
            if estado.veracrypt:
                hecho()
                wiz.repintar()
            else:
                messagebox.showerror(TITLE, "Ahí tampoco está VeraCrypt.",
                                     parent=wiz.root)
        ttk.Button(fila, text="Buscar aquí", command=buscar).grid(row=0, column=2, padx=theme.E2)
        return

    existe = contenedor.is_file()
    libre = lecturas_asistente.libre(estado.device)
    ttk.Label(panel, justify="left", wraplength=theme.medida(760), text=(
        f"Contenedor: {contenedor}\n"
        + ("Ya existe: se puede montar con su contraseña."
           if existe else "Todavía no existe: se va a crear.")
        + ("\nCon el VeraCrypt Portable, sin instalar: cada paso pedirá permiso "
           "de administrador." if crypto.portatil(estado.veracrypt) else ""))).grid(
        row=0, column=0, sticky="w")

    # Una instalación sin cifrar en la raíz física: la de antes de un
    # «Reinstalar desde cero». El contenedor va al lado y ella se queda, con la
    # clave en claro. Se dice antes de crear nada, y no se borra sola.
    restos = crypto.restos_en_claro(estado.device)
    if restos:
        bloque_aviso(panel, crypto.aviso_restos(restos, estado.device), ancho=720,
                     tipo="Rojo").grid(row=1, column=0, sticky="ew", pady=(theme.E3, 0))

    formulario = ttk.Frame(panel)
    formulario.grid(row=2, column=0, sticky="w", pady=(theme.E3, 0))
    fila = 0

    # La pregunta que decide si esto tarda segundos o media hora. Se rehace en
    # cada repintado a propósito: es una consulta al sistema de ficheros que ni
    # escribe ni tarda, y cachearla daría la respuesta de la unidad anterior si
    # se cambia de destino. Lo que sí se recuerda en el estado es la MEDIDA de
    # velocidad, que sí escribe en la unidad (`lecturas_asistente.sonda_de`). En Linux no
    # hay casilla que valga: `--quick` va siempre y que el contenedor salga
    # disperso lo decide la versión de VeraCrypt y el disco
    # (`crypto.creacion_dispersa()`, `None` si no se sabe). Se enseña marcada o
    # no, sin poder cambiarla, y la frase de al lado dice por qué.
    disperso = (crypto.creacion_dispersa(estado.device, estado.veracrypt)
                if not existe else False)
    dispersos = disperso is True
    # El sistema de ficheros de la unidad, por lo mismo: en FAT32 un fichero no
    # llega a 4 GiB, y el contenedor es un fichero (`crypto.tope_contenedor`).
    fs = crypto.sistema_de_ficheros(estado.device) if not existe else ""
    tope = crypto.tope_contenedor(fs)
    dinamico = tk.BooleanVar(value=dispersos if estado.dinamico is None
                             else (estado.dinamico and dispersos))
    tam = tk.StringVar(value=crypto.suggested_size(libre, dinamico.get(), tope))
    sistema = tk.StringVar(value=crypto.FILESYSTEMS[0])
    # El traveler disk es cosa de Windows: en Linux y macOS VeraCrypt necesita
    # instalarse (driver y FUSE) y no hay nada que llevar, ni se ofrece. Se
    # crea aquí arriba porque `max` depende de él: con VeraCrypt de viaje deja
    # más sitio fuera del contenedor (`crypto.RESERVA_VIAJERO`).
    traveler = tk.BooleanVar(value=estado.traveler and IS_WIN)
    espera = ttk.Label(formulario, style="Pista.TLabel", justify="left",
                       wraplength=theme.medida(560))

    if not existe:
        ttk.Label(formulario, text="Tamaño:").grid(row=fila, column=0, sticky="w")
        ttk.Entry(formulario, textvariable=tam, width=10).grid(row=fila, column=1, sticky="w")
        ttk.Label(formulario, style="Aviso.TLabel" if tope else "Pista.TLabel",
                  text=(f"libre en la unidad: {libre / 1024**3:.1f} GiB "
                        + (f"— es {fs}: como mucho {tope // 1024**2}M"
                           if tope else "— admite 20G, 500M o 'max'"))).grid(
            row=fila, column=2, sticky="w", padx=(theme.E3, 0))
        fila += 1
        ttk.Label(formulario, text="Sistema de ficheros:").grid(row=fila, column=0, sticky="w")
        ttk.Combobox(formulario, textvariable=sistema, state="readonly", width=8,
                     values=list(crypto.FILESYSTEMS)).grid(row=fila, column=1, sticky="w")
        ttk.Label(formulario, style="Pista.TLabel",
                  text="exFAT es lo más portable entre Windows, Linux y macOS").grid(
            row=fila, column=2, sticky="w", padx=(theme.E3, 0))
        fila += 1

        ttk.Checkbutton(
            formulario, variable=dinamico,
            state="normal" if dispersos and IS_WIN else "disabled",
            text="Contenedor dinámico: solo ocupa lo que guardes").grid(
            row=fila, column=0, columnspan=2, sticky="w", pady=(theme.E2, 0))
        ttk.Label(formulario, style="Pista.TLabel", justify="left",
                  wraplength=theme.medida(360), text=(
            "sin negación plausible, y si la unidad se llena el volumen da "
            "errores de E/S" if dispersos else
            "depende de la versión de VeraCrypt: con la 1.26.29 o posterior solo "
            "ocupa lo que guardes; con una anterior se escribe entero"
            if disperso is None else
            f"esta unidad ({fs or 'sin identificar'}) no admite ficheros "
            "dispersos: el contenedor hay que escribirlo entero")).grid(
            row=fila, column=2, sticky="w", padx=(theme.E3, 0), pady=(theme.E2, 0))
        fila += 1
        espera.grid(row=fila, column=0, columnspan=3, sticky="w", pady=(theme.E2, 0))
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

    ttk.Label(formulario, style="Peligro.TLabel", justify="left",
              wraplength=theme.medida(560), text=(
        "Esta contraseña no se guarda en ningún sitio. Si la pierdes, el "
        "contenedor no se recupera: apúntala en tu gestor de contraseñas ANTES "
        "de seguir.")).grid(row=fila, column=0, columnspan=3, sticky="w", pady=(theme.E2, 0))
    fila += 1

    # La sonda corre en otro hilo y la recoge este sondeo, que cuelga del
    # formulario y no del panel: cambiar de forma de cifrar destruye lo de
    # dentro del panel, y con ello esta espera, pero no el panel.
    sondeo = Sondeo(formulario)
    tope_sonda = {"id": None}

    def poner_boton() -> None:
        """Apaga «Crear y montar» mientras la sonda escribe al lado del contenedor."""
        montar.configure(
            state="disabled" if lecturas_asistente.midiendo(estado) else "normal")

    def soltar_tope() -> None:
        """Quita la espera del tope: la sonda ya ha contestado."""
        if tope_sonda["id"] is not None:
            try:
                formulario.after_cancel(tope_sonda["id"])
            except Exception:                        # noqa: BLE001 — ya no está
                pass
            tope_sonda["id"] = None

    def vigilar_sonda() -> None:
        """Espera a la sonda de este volumen si sigue escribiendo, y a su tope."""
        sonda = estado.sondas.get(Path(estado.device))
        if sonda is None or sonda.encargo.hecho:
            soltar_tope()
            return
        if not sondeo.esperando:
            sondeo.esperar(sonda.encargo, actualizar)
        if tope_sonda["id"] is None and lecturas_asistente.midiendo(estado):
            resto = lecturas_asistente.quedan_s(sonda)
            tope_sonda["id"] = formulario.after(max(1, int(resto * 1000) + 1),
                                                vencer_tope)

    def vencer_tope() -> None:
        """Pasado el tope de la sonda, deja crear sin su medida.

        Si el reloj de Tk se adelanta al de `midiendo()`, `vigilar_sonda` lo
        vuelve a armar por lo que falte; pasado el tope ya no se arma.
        """
        tope_sonda["id"] = None
        actualizar()

    def actualizar(*_) -> None:
        """Rehace la espera y el botón cuando la sonda contesta o pasa su tope."""
        if existe:
            vigilar_sonda()
            poner_boton()
        else:
            refrescar_espera()

    def refrescar_espera(*_) -> None:
        """Dice cuánto va a tardar la creación, medido y no adivinado.

        La medida escribe en la unidad, así que se hace UNA vez por volumen, en
        otro hilo, y se guarda en el estado (`texto_espera`); lo que se
        recalcula al cambiar el tamaño es la división.
        """
        estado.dinamico = bool(dinamico.get())
        try:
            bytes_ = None if estado.dinamico else crypto.size_to_bytes(
                tam.get(), libre, tope, viajero=bool(traveler.get()))
            error = None
        except InstallError as e:
            bytes_, error = None, str(e)
        if bytes_ is not None:
            # Que la sonda exista antes de mirarla: sin ella no se arma el sondeo.
            lecturas_asistente.sonda_de(estado)
        # Se vigila antes de pintar: si la sonda acaba entre las dos lecturas,
        # ya la espera el sondeo, que vuelve a pintar.
        vigilar_sonda()
        if estado.dinamico:
            espera.configure(text="Creación prácticamente inmediata.")
        elif error is not None:
            espera.configure(text=error)
        else:
            espera.configure(text=lecturas_asistente.texto_espera(estado, bytes_))
        poner_boton()

    def al_cambiar_dinamico(*_) -> None:
        """Propone el tamaño que toca al marcar o desmarcar el contenedor dinámico."""
        tam.set(crypto.suggested_size(libre, bool(dinamico.get()), tope))
        refrescar_espera()

    if IS_WIN:
        ttk.Checkbutton(
            panel, variable=traveler,
            text="Dejar VeraCrypt en el dispositivo (el portable oficial, x64 y "
                 "ARM64), para montarlo en equipos que no lo tengan").grid(
            row=3, column=0, sticky="w", pady=(theme.E3, 0))

    bloque_aviso(panel, AVISO_AUTOARRANQUE, tono="Azul.", ancho=640).grid(
        row=4, column=0, sticky="ew", pady=(theme.E3, 0))

    def crear_y_montar() -> None:
        """Comprueba la contraseña, crea el contenedor si hace falta y lo monta."""
        if lecturas_asistente.midiendo(estado):
            return                  # la sonda escribe donde iría el contenedor
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
                bytes_ = crypto.size_to_bytes(tam.get(), libre, tope,
                                              viajero=estado.traveler and IS_WIN)
                # Sin dispersos se escribe el contenedor entero, y eso son
                # minutos u horas: el avance se mide en la unidad mientras
                # tanto. Con `/dynamic` son segundos y no hay nada que medir.
                seguimiento = None if estado.dinamico else crypto.Seguimiento()
                ok, res = working(
                    wiz.root, "creando el contenedor",
                    lambda: crypto.create_container(
                        estado.veracrypt, contenedor, bytes_, password,
                        sistema.get(), estado.dinamico, seguimiento=seguimiento),
                    f"Creando {contenedor} ({bytes_ / 1024**3:.1f} GiB).\n"
                    + ("Es un contenedor dinámico: esto va a ser rápido."
                       if estado.dinamico else espera.cget("text")),
                    progreso=None if seguimiento is None else seguimiento.progreso)
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
    botones.grid(row=5, column=0, sticky="w", pady=(theme.E3, 0))
    montar = ttk.Button(botones, text="Montar" if existe else "Crear y montar",
                        style="Primary.TButton", command=crear_y_montar)
    theme.boton_icono(montar, "candado", theme.SOBRE_ACENTO)
    montar.grid(row=0, column=0)
    if estado.device_root and estado.mounted_by_us:
        theme.chip(botones, f"montado en {estado.device_root}", "Ok.").grid(
            row=0, column=1, padx=(theme.E3, 0))

    if not existe:
        dinamico.trace_add("write", al_cambiar_dinamico)
        tam.trace_add("write", refrescar_espera)
    actualizar()


def _llevar_veracrypt(wiz) -> None:
    """Copia VeraCrypt al volumen; es de mejor esfuerzo.

    No puede tumbar la instalación. Va a la raíz FÍSICA, fuera del contenedor
    (dentro haría falta VeraCrypt para llegar a VeraCrypt), y es lo único de
    este paso que puede fallar sin que importe: sin traveler disk el
    dispositivo funciona igual en cualquier equipo que tenga VeraCrypt
    instalado. Va por `working()`: puede tener que bajar el VeraCrypt Portable
    (≈39 MB) y comprobarlo.
    """
    from install import traveler

    estado = wiz.state
    ok, res = working(wiz.root, "llevando VeraCrypt",
                      lambda: traveler.llevar(estado.veracrypt, estado.device),
                      "Dejando VeraCrypt en la unidad, fuera del contenedor.")
    if not ok:
        wiz.aviso("El dispositivo ha quedado montado, pero no he podido dejar "
                  f"VeraCrypt dentro:\n\n{res}\n\nSe puede reintentar desde el "
                  "último paso.")
    elif res.aviso:
        wiz.aviso(res.aviso)


def _panel_bitlocker(panel, wiz, hecho) -> None:
    """Pinta el panel de BitLocker.

    Abre el asistente de Windows y comprueba cómo quedó.
    """
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
    marca.grid(row=1, column=0, sticky="w", pady=(theme.E3, 0))

    def pintar_estado(st) -> None:
        """Dice el estado de BitLocker, en verde solo si está protegido."""
        color = theme.OK if (st.known and st.protected) else theme.AVISO
        marca.configure(text=f"Estado de {letra}: {st.resumen}", foreground=color)

    pintar_estado(crypto.BitLockerStatus(False, detail="sin comprobar todavía"))

    def abrir() -> None:
        """Abre el asistente de BitLocker de Windows."""
        try:
            crypto.open_bitlocker_setup(letra)
        except InstallError as e:
            messagebox.showerror(TITLE, str(e), parent=wiz.root)

    def comprobar() -> None:
        """Comprueba el estado y, si está protegido, da por bueno el volumen."""
        res = crypto.bitlocker_status(letra)
        pintar_estado(res)
        if res.known and res.protected:
            estado.device_root = estado.device
            hecho()

    def seguir_igual() -> None:
        """Sigue sin haber comprobado el cifrado, tras pedir confirmación."""
        if not messagebox.askokcancel(TITLE, (
                "Vas a seguir sin haber comprobado que el volumen quedó "
                "cifrado.\n\nDentro va la clave privada de tu remoto."),
                parent=wiz.root):
            return
        estado.device_root = estado.device
        hecho()

    botones = ttk.Frame(panel)
    botones.grid(row=2, column=0, sticky="w", pady=(theme.E3, 0))
    for i, (texto, accion) in enumerate((
            ("Abrir el asistente de Windows", abrir),
            ("Comprobar cómo quedó", comprobar),
            ("Seguir de todas formas", seguir_igual))):
        ttk.Button(botones, text=texto, command=accion).grid(row=0, column=i, padx=(0, theme.E2))
