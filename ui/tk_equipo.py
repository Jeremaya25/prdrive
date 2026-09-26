#!/usr/bin/env python3
"""
tk_equipo.py — Los pasos del asistente «En este equipo».

Solo dibuja. Lo que decide y lo que toca el disco está en `install/agente.py` y
`install/raiz_equipo.py`, igual que el resto del asistente con `install/`. Dos
recorridos, que elige el paso «Carpeta» (ver `tk_install.PASOS_EQUIPO`):

    Carpeta        la raíz de este equipo: carpeta propia, la personal, o ninguna
    Cifrado        sin cifrar, o en un contenedor VeraCrypt (solo la carpeta propia,
                   solo con VeraCrypt instalado): lo crea, lo monta y lo deja abierto
    Conexión, Comprobaciones        los del recorrido de una unidad, tal cual
    Instalación    .prdrive/ + rclone en la raíz; el agente y su Python en el equipo
    Parejas        las del catálogo, con la ruta de cada una EN ESTE equipo
    Inicialización el de siempre, con el Python del agente
    Unidades       qué unidades atiende ya y cómo, y el plazo de «unidad nueva»
    Arranque       que arranque al iniciar sesión; penwatch fuera
    Verificación   lo que de verdad quedó puesto

Con «Ninguna: solo atender unidades» sobran conexión, catálogo y parejas: cada
unidad trae los suyos, y es la instalación «solo agente» de la fase 1.

Lo que el asistente va sabiendo vive en el propio `Wizard` (`agente_*`,
`equipo_*`), no en los widgets: `repintar()` los destruye al cambiar de paso.
"""

from __future__ import annotations

from pathlib import Path

from . import theme
from .tk import working

ANCHO = 780

# En la lista de «Unidades», además de los modos del agente: no meterla en su
# lista, y que pregunte al enchufarla. Es lo que se propone para las que salen de
# la flota: nunca se sincroniza una unidad sin que se haya dicho que sí.
PREGUNTAR = "preguntar"
TEXTO_PREGUNTAR = "preguntar al enchufarla"


def _texto(cuerpo, texto: str, fila: int, **kw) -> None:
    from tkinter import ttk
    ttk.Label(cuerpo, justify="left", wraplength=theme.medida(ANCHO), text=texto,
              **kw).grid(row=fila, column=0, sticky="w", pady=(0, 10))


def _ambar(cuerpo, texto: str, fila: int) -> None:
    from tkinter import ttk
    caja = ttk.Frame(cuerpo, style="Ambar.TFrame", padding=(11, 9))
    caja.grid(row=fila, column=0, sticky="ew", pady=(0, 10))
    ttk.Label(caja, style="Ambar.TLabel", justify="left", text=texto,
              wraplength=theme.medida(ANCHO - 40)).grid(row=0, column=0, sticky="w")


def al_cambiar(entrada, funcion) -> None:
    """Llama a `funcion(texto)` con cada cambio de la caja, tecleado o no.

    Con `validatecommand` y no con un `trace` de la variable: el comando se
    registra en la propia caja y muere con ella (`Misc.destroy()` borra sus
    `_tclCommands`), mientras que el de un trace sobrevive al widget y retiene la
    ventana entera (AGENTS.md, la ventana principal). Se llama ANTES de que el
    texto cambie, por eso recibe el nuevo; y devuelve siempre True, porque si
    no, Tk apagaría la validación de la caja para siempre."""
    def validar(nuevo: str) -> bool:
        try:
            funcion(nuevo)
        finally:
            return True                                 # noqa: B012
    entrada.configure(validate="key",
                      validatecommand=(entrada.register(validar), "%P"))


def con_raiz(wiz) -> bool:
    """¿Este recorrido pone una raíz en el equipo, o es «solo agente»?"""
    from install import raiz_equipo
    return wiz.equipo_forma != raiz_equipo.NINGUNA


def raiz(wiz) -> Path | None:
    return wiz.state.device_root if con_raiz(wiz) else None


# ---------------------------------------------------------------------------
# Carpeta
# ---------------------------------------------------------------------------

def paso_carpeta(cuerpo, wiz) -> None:
    """Dónde vive la raíz de este equipo, o que no haya. Cambiar de respuesta
    cambia la lista de pasos (`tk_install.pasos_equipo`), como «¿Dónde?»."""
    import tkinter as tk
    from tkinter import filedialog, ttk

    from install import raiz_equipo as re_

    _texto(cuerpo, "¿Qué carpeta de este equipo sincroniza prdrive? Es su raíz: las "
                   "parejas son carpetas de dentro, y el programa va en .prdrive/.", 0)
    eleccion = tk.StringVar(value=wiz.equipo_forma)

    def elegir() -> None:
        forma = eleccion.get()
        if forma != wiz.equipo_forma:
            wiz.equipo_forma = forma
            por_defecto = re_.por_defecto(forma)
            wiz.equipo_ruta = str(por_defecto) if por_defecto else ""
        from .tk_install import pasos_equipo
        wiz.pasos = pasos_equipo(wiz)
        wiz.repintar()

    opciones = (
        (re_.PROPIA, "Una carpeta propia (recomendado)",
         f"{re_.carpeta_propia()}, o la que escribas: prdrive y tus parejas dentro, "
         "como la carpeta de Dropbox. Nada de fuera de ella se toca."),
        (re_.PERSONAL, "Tu carpeta personal",
         f"{re_.carpeta_personal()}: sincroniza carpetas que ya tienes, como "
         "Documentos/Obsidian, sin moverlas. A cambio, el límite es todo tu usuario."),
        (re_.NINGUNA, "Ninguna: solo atender unidades",
         "Sin conexión ni clave en este equipo: el agente sincroniza las unidades "
         "prdrive que enchufes, y cada una trae las suyas."),
    )
    for i, (valor, titulo, texto) in enumerate(opciones):
        tarjeta = ttk.Frame(cuerpo, style="Card.TFrame", padding=(14, 8))
        tarjeta.grid(row=1 + i, column=0, sticky="ew", pady=(0, 8))
        tarjeta.columnconfigure(0, weight=1)
        ttk.Radiobutton(tarjeta, text=titulo, value=valor, variable=eleccion,
                        style="Card.Fuerte.TRadiobutton", command=elegir).grid(
            row=0, column=0, sticky="w")
        ttk.Label(tarjeta, text=texto, style="Card.Pista.TLabel", justify="left",
                  wraplength=theme.medida(720)).grid(row=1, column=0, sticky="w",
                                                     pady=(3, 0))

    if not con_raiz(wiz):
        wiz.state.device_root = None
        return

    fila = ttk.Frame(cuerpo)
    fila.grid(row=4, column=0, sticky="ew", pady=(4, 0))
    fila.columnconfigure(1, weight=1)
    ttk.Label(fila, text="Carpeta:").grid(row=0, column=0, sticky="w")
    ruta = tk.StringVar(value=wiz.equipo_ruta)
    entrada = ttk.Entry(fila, textvariable=ruta, style="Mono.TEntry")
    entrada.grid(row=0, column=1, sticky="ew", padx=6)
    examen = ttk.Label(cuerpo, justify="left", wraplength=theme.medida(ANCHO))
    examen.grid(row=5, column=0, sticky="w", pady=(8, 0))
    _texto(cuerpo, "Se elige ahora y no se cambia después: mover la raíz deja cada "
                   "pareja sin su carpeta, y cambiarla es volver a instalar.", 6,
           style="Pista.TLabel")

    def revisar(texto: str | None = None) -> None:
        wiz.equipo_ruta = ruta.get() if texto is None else texto
        ex = re_.examinar(wiz.equipo_ruta, wiz.equipo_forma)
        wiz.equipo_examen = ex
        wiz.state.device_root = (Path(wiz.equipo_ruta.strip()).expanduser()
                                 if ex.vale else None)
        color = (theme.PELIGRO if not ex.vale else
                 theme.AVISO if ex.aviso else theme.TINTA3)
        examen.configure(text=ex.texto, foreground=color)
        wiz.revisar()

    def examinar_carpeta() -> None:
        elegida = filedialog.askdirectory(parent=wiz.root, mustexist=False,
                                          initialdir=str(Path.home()))
        if elegida:
            ruta.set(elegida)               # `set` no valida: se revisa a mano
            revisar(elegida)

    ttk.Button(fila, text="Examinar…", command=examinar_carpeta).grid(
        row=0, column=2, sticky="e")
    if wiz.equipo_forma == re_.PERSONAL:
        entrada.configure(state="readonly")     # la personal es la personal
    al_cambiar(entrada, revisar)
    revisar()


def ok_carpeta(wiz) -> bool:
    return not con_raiz(wiz) or wiz.state.device_root is not None


# ---------------------------------------------------------------------------
# Cifrado
# ---------------------------------------------------------------------------

def cifrada(wiz) -> bool:
    from install import raiz_equipo
    return con_raiz(wiz) and wiz.equipo_cifrado == raiz_equipo.VERACRYPT


def _existente(ruta: Path) -> Path:
    """La carpeta que ya existe más cerca de `ruta`: el disco del que se
    pregunta el sitio libre y si admite dispersos antes de crear nada."""
    for candidata in (ruta, *ruta.parents):
        try:
            if candidata.is_dir():
                return candidata
        except OSError:
            continue
    return ruta


def paso_cifrado(cuerpo, wiz) -> None:
    """Sin cifrar (la carpeta de «Carpeta» es la raíz) o en un contenedor
    VeraCrypt: se crea al lado de esa carpeta, se monta en una letra fija
    (Windows) o en la propia carpeta (Linux), y ESE volumen es la raíz. La
    contraseña se pide aquí para crear y montar, una vez; a partir de ahí abrir y
    cerrar es del agente, con la ventana de VeraCrypt, y nada la guarda."""
    import shutil
    import tkinter as tk
    from tkinter import messagebox, ttk

    from common import vestibulo
    from install import IS_WIN, crypto, raiz_equipo as re_

    from .tk import TITLE

    vc = re_.veracrypt_instalado()
    personal = wiz.equipo_forma == re_.PERSONAL
    puede = vc is not None and not personal
    if not puede:
        wiz.equipo_cifrado = re_.SIN_CIFRAR
    eleccion = tk.StringVar(value=wiz.equipo_cifrado)

    def elegir() -> None:
        wiz.equipo_cifrado = eleccion.get()
        wiz.repintar()

    _texto(cuerpo, "¿Cifrar la raíz de este equipo?", 0)
    opciones = (
        (re_.SIN_CIFRAR, "Sin cifrar",
         f"{wiz.equipo_ruta} es la raíz, tal cual. La clave del remoto queda en claro "
         f"en el disco (el paso «Instalación» dice si el disco tiene BitLocker)."),
        (re_.VERACRYPT, "En un contenedor VeraCrypt",
         "La raíz vive dentro de un fichero cifrado: la clave, la configuración y "
         "las parejas. Cerrado, no hay nada que leer ni que sincronizar por error. "
         "Lo abre el agente al iniciar sesión (VeraCrypt pide la contraseña en su "
         "ventana) y lo cierras con «Bloquear»."))
    for i, (valor, titulo, texto) in enumerate(opciones):
        tarjeta = ttk.Frame(cuerpo, style="Card.TFrame", padding=(14, 8))
        tarjeta.grid(row=1 + i, column=0, sticky="ew", pady=(0, 8))
        tarjeta.columnconfigure(0, weight=1)
        radio = ttk.Radiobutton(tarjeta, text=titulo, value=valor, variable=eleccion,
                                style="Card.Fuerte.TRadiobutton", command=elegir)
        radio.grid(row=0, column=0, sticky="w")
        if valor == re_.VERACRYPT and not puede:
            radio.configure(state="disabled")
        ttk.Label(tarjeta, text=texto, style="Card.Pista.TLabel", justify="left",
                  wraplength=theme.medida(720)).grid(row=1, column=0, sticky="w",
                                                     pady=(3, 0))
    if not puede:
        _ambar(cuerpo, re_.examinar_contenedor("x", wiz.equipo_ruta, wiz.equipo_forma
                                               ).texto if personal else re_.COMO_INSTALAR,
               3)

    if wiz.equipo_cifrado != re_.VERACRYPT:
        wiz.state.encryption = None
        wiz.state.device_root = (Path(wiz.equipo_ruta.strip()).expanduser()
                                 if wiz.equipo_examen and wiz.equipo_examen.vale else None)
        return

    wiz.state.encryption = "veracrypt"
    wiz.state.veracrypt = vc
    wiz.state.device_root = wiz.equipo_montada
    if not wiz.equipo_fisica:
        wiz.equipo_fisica = str(re_.fisica_por_defecto(wiz.equipo_ruta))
    formulario = ttk.Frame(cuerpo)
    formulario.grid(row=4, column=0, sticky="ew")
    formulario.columnconfigure(1, weight=1)
    ttk.Label(formulario, text="Contenedor en:").grid(row=0, column=0, sticky="w")
    fisica = tk.StringVar(value=wiz.equipo_fisica)
    caja = ttk.Entry(formulario, textvariable=fisica, style="Mono.TEntry")
    caja.grid(row=0, column=1, columnspan=2, sticky="ew", padx=6)
    examen = ttk.Label(formulario, justify="left", wraplength=theme.medida(ANCHO - 60))
    examen.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 6))

    fila = 2
    letra = tk.StringVar(value=wiz.equipo_letra or re_.LETRA_PREFERIDA)
    if IS_WIN:
        libres = re_.letras_libres()
        if wiz.equipo_letra not in libres and libres:
            letra.set(libres[0])
        ttk.Label(formulario, text="Letra:").grid(row=fila, column=0, sticky="w")
        ttk.Combobox(formulario, textvariable=letra, state="readonly", width=4,
                     values=libres).grid(row=fila, column=1, sticky="w", padx=6)
        ttk.Label(formulario, style="Pista.TLabel", text=(
            "siempre la misma: los programas apuntarán a ella")).grid(
            row=fila, column=2, sticky="w")
    else:
        ttk.Label(formulario, text="Se monta en:").grid(row=fila, column=0, sticky="w")
        ttk.Label(formulario, style="MonoPista.TLabel",
                  text=re_.punto_de_montaje(wiz.equipo_ruta)).grid(
            row=fila, column=1, columnspan=2, sticky="w", padx=6)
    fila += 1

    base = _existente(Path(wiz.equipo_fisica).expanduser())
    try:
        libre = shutil.disk_usage(str(base)).free
    except OSError:
        libre = 0
    dinamico = crypto.soporta_dispersos(base) if IS_WIN else False
    tam = tk.StringVar(value=wiz.equipo_tamano or crypto.suggested_size(libre, dinamico))
    tam_fila = ttk.Frame(formulario)
    ttk.Label(formulario, text="Tamaño:").grid(row=fila, column=0, sticky="w")
    tam_fila.grid(row=fila, column=1, columnspan=2, sticky="w", padx=6)
    ttk.Entry(tam_fila, textvariable=tam, width=8).grid(row=0, column=0)
    ttk.Label(tam_fila, style="Pista.TLabel", text=(
        f"libre: {libre / 1024 ** 3:.1f} GiB — "
        + ("dinámico: solo ocupa lo que guardes" if dinamico else
           "se escribe entero al crearlo: elige con cabeza"))).grid(
        row=0, column=1, padx=(8, 0))
    fila += 1
    pw1, pw2 = tk.StringVar(), tk.StringVar()
    ttk.Label(formulario, text="Contraseña:").grid(row=fila, column=0, sticky="w")
    ttk.Entry(formulario, textvariable=pw1, show="•", width=32).grid(
        row=fila, column=1, columnspan=2, sticky="w", padx=6)
    fila += 1
    repite = ttk.Label(formulario, text="Repítela:")
    repite_caja = ttk.Entry(formulario, textvariable=pw2, show="•", width=32)
    repite.grid(row=fila, column=0, sticky="w")
    repite_caja.grid(row=fila, column=1, columnspan=2, sticky="w", padx=6)
    fila += 1
    pedir = tk.BooleanVar(value=wiz.equipo_pedir)
    ttk.Checkbutton(formulario, variable=pedir,
                    command=lambda: setattr(wiz, "equipo_pedir", bool(pedir.get())),
                    text="Pedir la contraseña al iniciar sesión").grid(
        row=fila, column=0, columnspan=3, sticky="w", pady=(6, 0))
    fila += 1
    ttk.Label(formulario, foreground=theme.PELIGRO, justify="left",
              wraplength=theme.medida(ANCHO - 60), text=(
        "La contraseña no se guarda en ningún sitio. Si la pierdes, el contenedor "
        "no se recupera: apúntala en tu gestor de contraseñas antes de seguir."
        + ("" if IS_WIN else " En Linux, VeraCrypt pide además la de "
           "administrador para montar."))).grid(
        row=fila, column=0, columnspan=3, sticky="w", pady=(6, 0))

    restos = re_.restos(wiz.equipo_ruta) if IS_WIN else []
    if restos:
        from .tk import bloque_aviso
        bloque_aviso(cuerpo, crypto.aviso_restos(restos), ancho=ANCHO - 40,
                     tipo="Rojo").grid(row=5, column=0, sticky="ew", pady=(8, 0))

    botones = ttk.Frame(cuerpo)
    botones.grid(row=6, column=0, sticky="w", pady=(10, 0))
    boton = ttk.Button(botones, style="Primary.TButton")
    boton.grid(row=0, column=0)
    hecho = ttk.Label(botones, foreground=theme.OK)
    hecho.grid(row=0, column=1, padx=(12, 0))
    estado = {"examen": None}

    def revisar(texto: str | None = None) -> None:
        wiz.equipo_fisica = fisica.get() if texto is None else texto
        ex = re_.examinar_contenedor(wiz.equipo_fisica, wiz.equipo_ruta,
                                     wiz.equipo_forma)
        estado["examen"] = ex
        examen.configure(text=ex.texto, foreground=theme.PELIGRO if not ex.vale
                         else theme.TINTA3)
        existe = ex.estado == re_.YA_EQUIPO
        for w in (repite, repite_caja):
            w.grid() if not existe else w.grid_remove()
        boton.configure(text="Abrir el contenedor" if existe else "Crear y montar",
                        state="normal" if ex.vale else "disabled")
        wiz.revisar()

    def crear() -> None:
        ex = estado["examen"]
        if ex is None or not ex.vale:
            return
        existe = ex.estado == re_.YA_EQUIPO
        password = pw1.get()
        error, aviso = (crypto.revisar_contrasena(password) if not existe
                        else (None if password else "Falta la contraseña.", None))
        if error:
            messagebox.showwarning(TITLE, error, parent=wiz.root)
            return
        if not existe and password != pw2.get():
            messagebox.showwarning(TITLE, "Las dos contraseñas no coinciden.",
                                   parent=wiz.root)
            return
        if aviso and not messagebox.askyesno(TITLE, aviso, default="no",
                                             icon="warning", parent=wiz.root):
            return
        wiz.equipo_letra = letra.get()
        wiz.equipo_tamano = tam.get()
        ok, res = working(wiz.root, "el contenedor",
                          lambda: re_.abrir_o_crear(vc, wiz.equipo_fisica, wiz.equipo_ruta,
                                                    wiz.equipo_letra, password,
                                                    wiz.equipo_tamano),
                          ("Abriendo" if existe else "Creando y montando")
                          + " el contenedor. VeraCrypt puede pedir permisos de "
                            "administrador: acepta el aviso.")
        if not ok:
            messagebox.showerror(TITLE, str(res) or "Falló.", parent=wiz.root)
            return
        montada = Path(res)
        wiz.equipo_montada = montada
        wiz.equipo_contenedor = str(Path(wiz.equipo_fisica).expanduser()
                                    / vestibulo.CONTENEDOR)
        wiz.equipo_examen = re_.examinar(montada)
        wiz.state.device_root = montada
        wiz.state.mounted_by_us = True
        wiz.repintar()

    boton.configure(command=crear)
    if wiz.equipo_montada is not None:
        hecho.configure(text=f"✔ abierto en {wiz.equipo_montada}")
    al_cambiar(caja, revisar)
    revisar()


def ok_cifrado(wiz) -> bool:
    if cifrada(wiz):
        return wiz.equipo_montada is not None
    return wiz.state.device_root is not None


# ---------------------------------------------------------------------------
# Instalación
# ---------------------------------------------------------------------------

def paso_instalar(cuerpo, wiz) -> None:
    from tkinter import ttk

    from common import equipo
    from install import agente, deploy, raiz_equipo

    donde = raiz(wiz)
    ya = agente.instalado()
    fila = 0
    if donde is not None:
        _texto(cuerpo, (
            f"En {deploy.app_dir(donde)}: el programa, rclone para este equipo, la "
            f"conexión y su clave. Sin Python propio ni lanzadores: la raíz la "
            f"sincroniza el agente, con el suyo, y su ventana se abre desde el menú "
            f"del sistema («{agente.APP_NAME}»)."), fila)
        fila += 1
        if cifrada(wiz):
            _texto(cuerpo, (
                f"Todo eso va DENTRO del contenedor ({wiz.equipo_contenedor}); fuera "
                f"solo queda su marca, con el mismo id, para reconocerlo cerrado."),
                fila, foreground=theme.TINTA3)
        else:
            avisos = [raiz_equipo.AVISO_CLAVE]
            disco = raiz_equipo.cifrado_del_disco(donde)
            if disco:
                avisos.append(disco)
            _ambar(cuerpo, "\n\n".join(avisos), fila)
        fila += 1
    _texto(cuerpo, (
        f"El agente se queda en este equipo, fuera de toda raíz, en {equipo.DIR}: su "
        "código y su propio Python —no depende de ningún Python instalado— y su "
        "configuración. Ahí no hay claves, ni rclone.conf, ni listados."), fila)
    fila += 1
    reusar = agente.misma_version()
    if reusar:
        _texto(cuerpo, (f"El agente de esta versión ({ya.get('version', '?')}) ya está "
                        "instalado y no se reinstala: lo que elijas a continuación se le "
                        "pide por su buzón, sin pararlo."), fila, foreground=theme.TINTA3)
        fila += 1
    elif ya:
        _texto(cuerpo, (f"Ya hay un agente instalado (versión {ya.get('version', '?')}). "
                        "Instalar pone esta versión al lado y la deja en su sitio; su "
                        "lista de unidades se conserva."), fila, foreground=theme.TINTA3)
        fila += 1

    boton = ttk.Button(cuerpo, text="Instalar", style="Primary.TButton")
    boton.grid(row=fila, column=0, sticky="w")
    resultado = ttk.Label(cuerpo, wraplength=theme.medida(ANCHO), justify="left")
    resultado.grid(row=fila + 1, column=0, sticky="w", pady=(12, 0))

    def pintar() -> None:
        lineas = []
        if donde is not None and wiz.state.deployed and wiz.equipo_id:
            lineas.append(f"✔ Programa en {deploy.app_dir(donde)} "
                          f"(id {wiz.equipo_id[:8]}…)")
        prep = wiz.agente_prep
        if prep is not None and wiz.agente_reusado:
            lineas.append(f"✔ El agente ya estaba: {prep.codigo}")
        elif prep is not None:
            lineas += [f"✔ Agente en {prep.codigo}", f"✔ Su Python: {prep.python}"]
        resultado.configure(text="\n".join(lineas), foreground=theme.OK)
        wiz.revisar()

    def instalar() -> None:
        def trabajo():
            ident = None
            if donde is not None:
                fisica = (Path(wiz.equipo_contenedor).parent if cifrada(wiz)
                          else None)
                _, ident = raiz_equipo.instalar(donde, wiz.perfil_final,
                                                fisica=fisica)
            if reusar:
                return ident, agente.instalado_prep()
            return ident, agente.preparar()

        ok, res = working(wiz.root, "instalando", trabajo,
                          "Copiando el programa, rclone y el Python del agente. La "
                          "primera vez hay que descargarlos.")
        if not ok:
            resultado.configure(text=str(res), foreground=theme.PELIGRO)
            wiz.revisar()
            wiz.visor.ver(resultado)
            return
        ident, wiz.agente_prep = res
        wiz.agente_reusado = reusar
        if ident:
            wiz.equipo_id = ident
            wiz.state.deployed = True
        pintar()

    boton.configure(command=instalar)
    pintar()


def ok_instalar(wiz) -> bool:
    if con_raiz(wiz) and not wiz.state.deployed:
        return False
    return wiz.agente_prep is not None


# ---------------------------------------------------------------------------
# Parejas: las del catálogo, con la ruta de cada una en ESTE equipo
# ---------------------------------------------------------------------------

def paso_parejas(cuerpo, wiz) -> None:
    """Como el paso «Parejas» de una unidad, más una cosa: la ruta resuelta de
    cada pareja, que se puede cambiar solo en este equipo. Con la carpeta
    personal, una ruta pensada para una unidad (`sync-data/…`) caería suelta en
    `~`; y una carpeta que ya sincroniza otro programa se dice en ámbar."""
    import tkinter as tk
    from tkinter import ttk

    from install import InstallError, deploy, raiz_equipo

    donde = wiz.state.device_root
    _texto(cuerpo, (
        "Qué carpetas sincroniza este equipo, y dónde cae cada una. La ruta se puede "
        "cambiar aquí sin tocar el catálogo: la pareja queda como «modificada aquí»."
        ), 0)

    tabla = ttk.Frame(cuerpo)
    tabla.grid(row=1, column=0, sticky="ew")
    tabla.columnconfigure(1, weight=1)
    elegidas: dict[str, tk.BooleanVar] = {}
    cajas: dict[str, tk.StringVar] = {}
    notas: dict[str, object] = {}

    def revisar_fila(nombre: str, local: str | None = None) -> None:
        local = cajas[nombre].get() if local is None else local
        wiz.equipo_locales[nombre] = local
        info = raiz_equipo.revisar_local(donde, local)
        ruta_lbl, nota_lbl = notas[nombre]
        ruta_lbl.configure(text=str(info.ruta) if info.ruta else "")
        if info.error:
            nota_lbl.configure(text=info.error, foreground=theme.PELIGRO)
        else:
            nota_lbl.configure(text="; ".join(info.avisos), foreground=theme.AVISO)
        wiz.revisar()

    fila = 0
    for pareja in wiz.catalog.pairs:
        nombre = pareja.get("name", "")
        modo = pareja.get("mode", "bisync")
        var = tk.BooleanVar(value=nombre in wiz.state.selected or not wiz.state.selected)
        elegidas[nombre] = var
        ttk.Checkbutton(tabla, variable=var, text=f"{nombre}   [{modo}]").grid(
            row=fila, column=0, sticky="w", padx=(0, 12))
        cajas[nombre] = tk.StringVar(
            value=wiz.equipo_locales.get(nombre, str(pareja.get("local", ""))))
        caja = ttk.Entry(tabla, textvariable=cajas[nombre], style="Mono.TEntry",
                         width=30)
        caja.grid(row=fila, column=1, sticky="ew")
        al_cambiar(caja, lambda texto, n=nombre: revisar_fila(n, texto))
        ttk.Label(tabla, style="Pista.TLabel",
                  text=f"↔  {pareja.get('remote_path', '?')}").grid(
            row=fila, column=2, sticky="w", padx=(12, 0))
        debajo = ttk.Frame(tabla)
        debajo.grid(row=fila + 1, column=1, columnspan=2, sticky="w", pady=(1, 6))
        notas[nombre] = (
            ttk.Label(debajo, style="MonoPista.TLabel"),
            ttk.Label(debajo, style="Pista.TLabel", justify="left",
                      wraplength=theme.medida(560)))
        notas[nombre][0].grid(row=0, column=0, sticky="w")
        notas[nombre][1].grid(row=1, column=0, sticky="w")
        if modo in ("up-mirror", "down-mirror"):
            destino = "el remoto" if modo == "up-mirror" else "este equipo"
            ttk.Label(tabla, foreground=theme.PELIGRO, style="Pista.TLabel",
                      text=f"espejo: borra en {destino}").grid(
                row=fila + 1, column=0, sticky="nw")
        revisar_fila(nombre)
        fila += 2

    resultado = ttk.Label(cuerpo, wraplength=theme.medida(ANCHO), justify="left",
                          foreground=theme.TINTA3)
    resultado.grid(row=3, column=0, sticky="w", pady=(12, 0))

    def guardar() -> None:
        seleccion = [n for n, v in elegidas.items() if v.get()]
        malas = [n for n in seleccion
                 if raiz_equipo.revisar_local(donde, cajas[n].get()).error]
        if malas:
            resultado.configure(text="Arregla antes la ruta de: " + ", ".join(malas),
                                foreground=theme.PELIGRO)
            return
        locales = {n: raiz_equipo.revisar_local(donde, cajas[n].get()).local
                   for n in seleccion}
        try:
            destino = deploy.write_device_config(
                donde, wiz.catalog, seleccion, endpoint=wiz.perfil.endpoint_catalog,
                catalog_path=wiz.perfil.catalog_path, locales=locales)
            creadas = deploy.make_local_dirs(donde, wiz.catalog, seleccion, locales)
        except InstallError as e:
            wiz.error(str(e))
            return
        except Exception as e:                       # noqa: BLE001
            wiz.error(f"{type(e).__name__}: {e}")
            return
        wiz.state.selected = seleccion
        wiz.state.config_written = True
        nota = deploy.publish_fleet_note(wiz.rclone, donde, wiz.perfil.endpoint_catalog)
        detalle = f"Escrito {destino} con {len(seleccion)} pareja(s)."
        if creadas:
            detalle += "\nCarpetas creadas: " + ", ".join(str(p) for p in creadas)
        detalle += ("\nApuntado en la flota: " + nota if nota else
                    "\n(no se ha podido apuntar en la flota; se hará al sincronizar)")
        resultado.configure(text=detalle, foreground=theme.OK)
        wiz.revisar()

    ttk.Button(cuerpo, text="Guardar el config y crear las carpetas",
               command=guardar).grid(row=2, column=0, sticky="w", pady=(12, 0))


def ok_parejas(wiz) -> bool:
    return wiz.state.config_written


# ---------------------------------------------------------------------------
# Unidades
# ---------------------------------------------------------------------------

def paso_unidades(cuerpo, wiz) -> None:
    import tkinter as tk
    from tkinter import ttk

    from common import equipo
    from install import agente, raiz_equipo

    _texto(cuerpo, (
        "Qué unidades atiende el agente, y qué hace con cada una al enchufarla. "
        "Aquí salen las que se saben sin red —la que vigilaba penwatch en este "
        "equipo, las enchufadas ahora y las que el agente ya tenga— y, con "
        "conexión, las de la flota. Cualquier otra se pregunta la primera vez que "
        "se enchufe: nunca se sincroniza una unidad sin preguntar."), 0)

    if wiz.agente_unidades is None:
        ofrecidas = agente.candidatas()
        wiz.agente_unidades = {c.id: (c.modo, c.nombre) for c in ofrecidas}
        wiz.agente_origen = {c.id: c.origen for c in ofrecidas}

    tabla = ttk.Frame(cuerpo)
    tabla.grid(row=1, column=0, sticky="w")
    if not wiz.agente_unidades:
        ttk.Label(tabla, style="Pista.TLabel", text=(
            "Ninguna todavía. Enchufa una unidad prdrive y el agente preguntará si "
            "atenderla.")).grid(row=0, column=0, sticky="w")
    else:
        for col, rotulo in enumerate(("Unidad", "Qué hacer al enchufarla", "")):
            ttk.Label(tabla, text=theme.rotulo(rotulo), style="Rotulo.TLabel").grid(
                row=0, column=col, sticky="w", padx=(0, 18))
    etiquetas = {m: equipo.TEXTO_MODO[m] for m in equipo.MODOS}
    etiquetas[PREGUNTAR] = TEXTO_PREGUNTAR
    por_texto = {v: k for k, v in etiquetas.items()}
    for i, (uid, (modo, nombre)) in enumerate(sorted(wiz.agente_unidades.items()),
                                              start=1):
        ttk.Label(tabla, text=nombre or f"{uid[:8]}…").grid(
            row=i, column=0, sticky="w", padx=(0, 18), pady=2)
        var = tk.StringVar(value=etiquetas[modo])

        def cambiar(_evento=None, u=uid, v=var, n=nombre) -> None:
            wiz.agente_unidades[u] = (por_texto[v.get()], n)

        caja = ttk.Combobox(tabla, textvariable=var, state="readonly",
                            values=[etiquetas[m] for m in (*equipo.MODOS, PREGUNTAR)],
                            width=30)
        caja.bind("<<ComboboxSelected>>", cambiar)
        caja.grid(row=i, column=1, sticky="w", padx=(0, 18), pady=2)
        ttk.Label(tabla, text=wiz.agente_origen.get(uid, ""), style="Pista.TLabel").grid(
            row=i, column=2, sticky="w", pady=2)

    if wiz.rclone is not None and con_raiz(wiz):
        def de_la_flota() -> None:
            ok, flota = working(wiz.root, "leyendo la flota",
                                lambda: raiz_equipo.de_la_flota(
                                    wiz.rclone, wiz.perfil.endpoint_catalog),
                                "Leyendo las notas de la flota en el remoto.")
            if not ok:
                wiz.error(str(flota))
                return
            for disp in flota:
                if disp.id not in wiz.agente_unidades and disp.id != wiz.equipo_id:
                    wiz.agente_unidades[disp.id] = (PREGUNTAR, disp.nombre)
                    wiz.agente_origen[disp.id] = "en la flota"
            wiz.repintar()

        ttk.Button(cuerpo, text="Añadir las de la flota", command=de_la_flota).grid(
            row=2, column=0, sticky="w", pady=(10, 0))

    plazo = ttk.Frame(cuerpo)
    plazo.grid(row=3, column=0, sticky="w", pady=(16, 0))
    ttk.Label(plazo, text="Para contestar a una unidad nueva:").grid(row=0, column=0,
                                                                     sticky="w")
    segundos = tk.StringVar(value=f"{wiz.agente_espera:g}")

    def cambiar_plazo(*_) -> None:
        try:
            valor = float(segundos.get())
        except ValueError:
            return
        wiz.agente_espera = min(max(valor, equipo.ESPERA_MINIMA), equipo.ESPERA_MAXIMA)

    # Por los eventos de la caja y no con un `trace` de la variable: el comando
    # Tcl de un trace no muere con el widget (ver AGENTS.md, la ventana principal).
    caja_plazo = ttk.Spinbox(plazo, textvariable=segundos, from_=equipo.ESPERA_MINIMA,
                             to=equipo.ESPERA_MAXIMA, increment=30, width=6,
                             command=cambiar_plazo)
    caja_plazo.grid(row=0, column=1, padx=6)
    caja_plazo.bind("<KeyRelease>", cambiar_plazo)
    caja_plazo.bind("<FocusOut>", cambiar_plazo)
    ttk.Label(plazo, text="segundos. Sin respuesta, cuenta como «Ahora no» hasta "
                          "que se vuelva a enchufar.", style="Pista.TLabel").grid(
        row=0, column=2, sticky="w")


def elegidas(wiz) -> dict[str, tuple[str, str]]:
    """Las unidades que entran en la lista del agente: sin las de «preguntar»."""
    return {uid: (modo, nombre) for uid, (modo, nombre)
            in (wiz.agente_unidades or {}).items() if modo != PREGUNTAR}


# ---------------------------------------------------------------------------
# Arranque
# ---------------------------------------------------------------------------

def la_raiz(wiz):
    """La raíz de este equipo como entrada de la lista del agente, o None."""
    from common import equipo
    from install import raiz_equipo
    donde = raiz(wiz)
    if donde is None or not wiz.equipo_id:
        return None
    return equipo.Unidad(wiz.equipo_id, equipo.DAEMON, raiz_equipo.nombre(donde),
                         str(donde), wiz.equipo_contenedor if cifrada(wiz) else "")


def paso_arranque(cuerpo, wiz) -> None:
    from tkinter import ttk

    import penwatch
    from install import agente

    como = ("una tarea programada de tu usuario, que arranca al iniciar sesión"
            if agente.IS_WIN else
            "un autostart del escritorio (~/.config/autostart), porque los avisos y "
            "la pregunta por una unidad nueva necesitan la sesión gráfica")
    if wiz.agente_reusado:
        _texto(cuerpo, "El agente ya está registrado y en su sitio: no se toca. Lo "
                       "elegido se le pide por su buzón y lo aplica él, sin pararse "
                       "(si no está en marcha, se arranca).", 0)
    else:
        _texto(cuerpo, f"El agente se registra con {como}, y se arranca ya. Sin "
                       "administrador."
               + ("" if agente.IS_WIN else
                  f" Su icono va en la bandeja; donde no la hay, hace sus veces el "
                  f"acceso «{agente.APP_NAME}» del menú."), 0)
    if raiz(wiz) is not None:
        _texto(cuerpo, (
            f"Sincroniza {raiz(wiz)} en segundo plano, con las parejas y el intervalo "
            f"de su servicio, y deja en el menú del sistema un acceso «{agente.APP_NAME}» "
            "que abre su ventana."
            + (" El contenedor se queda abierto: el agente lo recibe así, y "
               + ("pedirá la contraseña al iniciar sesión." if wiz.equipo_pedir else
                  "no pedirá nada al iniciar sesión («python agente.py desbloquear» "
                  "lo abre).") + " Para cerrarlo, «Bloquear» en su ventana."
               if cifrada(wiz) else "")), 1)
    if penwatch.CONFIG_FILE.exists():
        _texto(cuerpo, (
            "penwatch está instalado en este equipo. El agente lo sustituye: lo que "
            "vigilaba ya está en su lista, y penwatch se desinstala al registrar el "
            "agente. Dos vigilantes a la vez se pisarían."), 2, foreground=theme.AVISO)
    _texto(cuerpo, (
        "Un cambio respecto a penwatch: con el agente, abrir la ventana de una "
        "unidad ya no apaga su servicio para siempre, lo pausa mientras está "
        "abierta. Para pararlo: «python agente.py pausa», o el modo «nada» de esa "
        "unidad."), 3, foreground=theme.TINTA3)

    resultado = ttk.Label(cuerpo, wraplength=theme.medida(ANCHO), justify="left")
    resultado.grid(row=5, column=0, sticky="w", pady=(12, 0))

    def activar() -> None:
        pedir = wiz.equipo_pedir if cifrada(wiz) else None
        if wiz.agente_reusado:
            ok, msgs = working(wiz.root, "pidiéndoselo al agente",
                               lambda: agente.anadir(elegidas(wiz), wiz.agente_espera,
                                                     raiz=la_raiz(wiz),
                                                     pedir_al_iniciar=pedir),
                               "Dejándole lo elegido en su buzón.")
        else:
            ok, msgs = working(wiz.root, "registrando el agente",
                               lambda: agente.activar(
                                   wiz.agente_prep, elegidas(wiz), wiz.agente_espera,
                                   raiz=la_raiz(wiz), pedir_al_iniciar=pedir),
                               "Registrando el agente y arrancándolo.")
        if not ok:
            resultado.configure(text=str(msgs), foreground=theme.PELIGRO)
            wiz.revisar()
            wiz.visor.ver(resultado)
            return
        wiz.agente_hecho = list(msgs)
        resultado.configure(text="\n".join(f"✔ {m}" for m in msgs), foreground=theme.OK)
        wiz.revisar()

    ttk.Button(cuerpo, text="Pedírselo al agente" if wiz.agente_reusado
               else "Registrar y arrancar", style="Primary.TButton",
               command=activar).grid(row=4, column=0, sticky="w")
    if wiz.agente_hecho:
        resultado.configure(text="\n".join(f"✔ {m}" for m in wiz.agente_hecho),
                            foreground=theme.OK)


def ok_arranque(wiz) -> bool:
    return bool(wiz.agente_hecho)


# ---------------------------------------------------------------------------
# Verificación
# ---------------------------------------------------------------------------

def comprobaciones(donde: Path | None = None, esperadas: list[str] | None = None,
                   clave: str | None = None, contenedor: str | None = None,
                   carpeta_clara: str | None = None) -> list[tuple[str, bool, str]]:
    """(qué, bien, detalle) de lo que quedó puesto. Sin Tk: lo mira el test.

    Con `donde`, primero la raíz de este equipo: lo que `device.verify_device()`
    pide a cualquier raíz, y que esté en la lista del agente con esa ruta."""
    import penwatch
    from common import equipo
    from install import agente, device, raiz_equipo

    filas = []
    if donde is not None:
        for chk in raiz_equipo.verificar(donde, esperadas, clave, contenedor):
            filas.append((chk.etiqueta, chk.ok, chk.detalle))
        if contenedor and carpeta_clara:
            # Pasar a cifrado deja la raíz en claro donde estaba, con la clave:
            # fila roja, y nada la borra.
            from install import crypto
            for chk in crypto.comprobar_restos(carpeta_clara):
                filas.append((chk.etiqueta, chk.ok, chk.detalle))
        uid = device.control_id(donde)
        en_lista = equipo.leer_ajustes().unidades.get(uid or "")
        pedida = en_lista is None and agente.raiz_pedida(uid)
        filas.append(("En la lista del agente",
                      bool(en_lista and en_lista.ruta == str(donde)
                           and en_lista.contenedor == (contenedor or "")) or pedida,
                      f"raíz de este equipo, modo {en_lista.modo}"
                      + (", cifrada" if en_lista.cifrada else "") if en_lista else
                      "pedido: el agente la añade al leer su buzón" if pedida else
                      "no está: registra y arranca el agente"))
    if agente.quiere_menu(donde is not None):
        menu = agente.acceso_menu()
        filas.append(("Acceso del menú", menu.exists(), str(menu) if menu.exists()
                      else "no está: «agente.py abrir» hace lo mismo"))
    inst = agente.instalado()
    filas.append(("Agente instalado", inst is not None,
                  f"versión {inst.get('version')}, en {inst.get('codigo')}" if inst
                  else "no hay instalacion.json con código"))
    if inst:
        filas.append(("Su Python", _existe(inst.get("python")), str(inst.get("python"))))
    registro = (agente.autostart_file().is_file() if not agente.IS_WIN
                else penwatch.run_quiet(["schtasks", "/Query", "/TN",
                                         agente.TAREA]).returncode == 0)
    filas.append(("Arranca al iniciar sesión", registro,
                  "registrado" if registro else "no está registrado"))
    vivo = equipo.agente_vivo()
    filas.append(("En marcha", vivo is not None,
                  f"pid {vivo.get('pid')}" if vivo else
                  "todavía no: puede tardar unos segundos en arrancar"))
    unidades = [u for u in equipo.leer_ajustes().unidades.values() if not u.es_raiz]
    filas.append(("Unidades en su lista", True,
                  ", ".join(u.nombre or u.id[:8] for u in unidades)
                  or "ninguna: preguntará por cada una al enchufarla"))
    filas.append(("penwatch", not penwatch.CONFIG_FILE.exists(),
                  "no está instalado: el agente hace su trabajo"
                  if not penwatch.CONFIG_FILE.exists()
                  else "sigue instalado: dos vigilantes se pisarían"))
    if not agente.IS_WIN:
        avisos, hay_bandeja = escritorio()
        filas.append(("Avisos del escritorio", avisos is not False,
                      {True: "el escritorio los enseña",
                       None: "no se ha podido preguntar al bus de sesión",
                       False: "nadie atiende org.freedesktop.Notifications: los avisos "
                              "quedarán solo en el diario"}[avisos]))
        filas.append(("Bandeja", hay_bandeja is not False,
                      {True: "el icono del agente va en la bandeja del escritorio",
                       None: "no se ha podido preguntar al bus de sesión",
                       False: SIN_BANDEJA}[hay_bandeja]))
    return filas


# Lo que dice «Verificación» en un escritorio sin StatusNotifierWatcher, con el
# nombre de la extensión que lo pone en GNOME (sección 5 del diseño).
EXTENSION_GNOME = "AppIndicator and KStatusNotifierItem Support"
SIN_BANDEJA = (f"este escritorio no tiene bandeja. En GNOME la pone la extensión "
               f"«{EXTENSION_GNOME}» (Ubuntu ya la trae); mientras, el acceso «prdrive» "
               f"del menú de aplicaciones hace sus veces")


def _existe(ruta) -> bool:
    try:
        return bool(ruta) and Path(ruta).is_file()
    except OSError:
        return False


def escritorio() -> tuple[bool | None, bool | None]:
    """(¿hay avisos?, ¿hay bandeja?) en el bus de sesión: quién atiende
    `org.freedesktop.Notifications` y `org.kde.StatusNotifierWatcher`. None,
    lo que no se ha podido preguntar. Punto de indirección para los tests."""
    try:
        from common import avisos, dbus
        from ui import bandeja_linux
        with dbus.Conexion.sesion() as bus:
            return (bus.tiene_dueno(avisos.NOTIFICACIONES),
                    bandeja_linux.hay_bandeja(bus))
    except Exception:                                   # noqa: BLE001
        return None, None


def paso_final(cuerpo, wiz) -> None:
    from tkinter import ttk

    _texto(cuerpo, "Lo que ha quedado puesto en este equipo.", 0)
    tabla = ttk.Frame(cuerpo)
    tabla.grid(row=1, column=0, sticky="w")

    def revisar() -> None:
        for hijo in tabla.winfo_children():
            hijo.destroy()
        perfil = wiz.perfil_final
        clave = perfil.key_name if con_raiz(wiz) and perfil.needs_key else None
        for i, (etiqueta, ok, detalle) in enumerate(
                comprobaciones(raiz(wiz), wiz.state.selected, clave,
                               wiz.equipo_contenedor if cifrada(wiz) else None,
                               wiz.equipo_ruta if cifrada(wiz) else None)):
            color = theme.OK if ok else theme.PELIGRO
            ttk.Label(tabla, text="✔" if ok else "✘", foreground=color,
                      width=3).grid(row=i, column=0, sticky="w")
            ttk.Label(tabla, text=etiqueta + ":").grid(row=i, column=1, sticky="w")
            ttk.Label(tabla, text=detalle, foreground=color, wraplength=theme.medida(520),
                      justify="left").grid(row=i, column=2, sticky="w", padx=(10, 0))
        wiz.revisar()

    ttk.Button(cuerpo, text="Volver a comprobar", command=revisar).grid(
        row=2, column=0, sticky="w", pady=(14, 0))
    revisar()
