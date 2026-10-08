"""tk-lean-flat: widgets ordinarios con estilos planos de clam, SIN elementos de imagen.

Qué es: el mismo sistema de diseño (paleta, Noto Sans, escala de espacios, alturas de control) con los widgets
de siempre y los mapas de estado de ttk: ttk.Button / ttk.Entry / ttk.Radiobutton(Toolbutton) con la hoja de
estilos plana de clam (borde de 1 px, bordercolor = lightcolor = darkcolor), y `tk.Label` / `tk.Frame` /
`tk.Checkbutton` clásicos donde ttk no aporta nada (rótulos, filas, chips). Chips = UN `tk.Label` con borde
`highlightthickness` y el disco horneado como imagen compartida; casilla = `tk.Checkbutton` con dos PNG.
Esquinas cuadradas (no hay ni una pieza 9-slice), sin AA que perder. Sin `theme.apply()`: ~12 estilos.

Posición: `place` con las medidas de la captura de 0.7.1 (a U_REF), igual que el prototipo de lienzo, para que
la comparación de tiempo sea sólo «widgets vs lienzo» y no «grid vs coordenadas».
"""
from core import Ctx, TONO_DE, rotulo, tk

from tkinter import ttk

U_REF = 1.0427


class Plano:
    def __init__(self, ctx: Ctx, master, w, h):
        self.ctx, self.th = ctx, ctx.th
        self.R = lambda v: int(round(v * ctx.u / U_REF))
        # Un visor mínimo (como el `Visor` de 0.7.1): `vp` es la ventana de lo que se ve y `raiz` el contenido entero,
        # hijo suyo (por eso se recorta) y colocado con `place`; si no cabe, `encajar()` lo desplaza.
        self.W, self.H = self.R(w), self.R(h)
        self.vp = tk.Frame(master, width=self.W, height=self.H, bg=self.th.PAPEL, bd=0, highlightthickness=0)
        self.vp.pack(side="left")
        self.vp.pack_propagate(False)
        self.raiz = tk.Frame(self.vp, width=self.W, height=self.H, bg=self.th.PAPEL, bd=0, highlightthickness=0)
        self.raiz.place(x=0, y=0)

    # ------------------------------------------------------------------ primitivas
    def etiqueta(self, x, y, texto="", rol="texto", color=None, bg=None, anchor="w", imagen=None, padre=None,
                 wraplength=0, justify="left", margen=8):
        th = self.th
        e = tk.Label(padre or self.raiz, text=texto, font=self.ctx.fuentes[rol], fg=color or th.TINTA,
                     bg=bg or th.PAPEL, bd=0, padx=0, pady=0, highlightthickness=0, anchor=anchor, justify=justify)
        if imagen:
            img = self.ctx.icono(imagen, margen if texto else 0)
            if img is not None:
                e.configure(image=img, compound="left")
                e.image = img
        e.place(x=self.R(x), y=self.R(y), anchor=anchor if anchor in ("w", "e", "nw", "ne") else "w")
        return e

    def linea(self, x1, y, x2, color, padre=None):
        f = tk.Frame(padre or self.raiz, bg=color, bd=0, highlightthickness=0)
        f.place(x=self.R(x1), y=self.R(y), width=self.R(x2) - self.R(x1), height=1)
        return f

    def caja(self, x1, y1, x2, y2, relleno, borde, padre=None):
        """Un marco plano: relleno + borde de 1 px (el `highlight`), esquinas cuadradas."""
        f = tk.Frame(padre or self.raiz, bg=relleno, highlightthickness=1, highlightbackground=borde,
                     highlightcolor=borde, bd=0)
        f.place(x=self.R(x1), y=self.R(y1), width=self.R(x2) - self.R(x1), height=self.R(y2) - self.R(y1))
        return f

    def chip(self, x, y, texto, disco=None, icono=None, h=24, derecha=False, padre=None, bg=None):
        th = self.th
        e = tk.Label(padre or self.raiz, text=texto, font=self.ctx.fuentes["pista"], fg=th.TINTA, bg=th.GRIS_FONDO,
                     bd=0, highlightthickness=1, highlightbackground=th.LINEA, highlightcolor=th.LINEA,
                     padx=self.R(5), pady=0, compound="left")
        img = self.ctx.icono(disco or icono, 4) if (disco or icono) else None
        if img is not None:
            e.configure(image=img)
            e.image = img
        e.place(x=self.R(x), y=self.R(y), height=self.R(h), anchor="e" if derecha else "w")
        return e

    def casilla(self, x, y, texto, valor, cmd=None, rol="texto", color=None, bg=None, padre=None):
        th = self.th
        bg = bg or th.SUPERFICIE
        var = tk.BooleanVar(self.raiz, value=valor)
        on, off = self.ctx.icono("chk-on", 8), self.ctx.icono("chk-off", 8)
        b = tk.Checkbutton(padre or self.raiz, text=texto, variable=var, indicatoron=False, image=off, selectimage=on,
                           compound="left", font=self.ctx.fuentes[rol], fg=color or th.TINTA, bg=bg,
                           activebackground=bg, activeforeground=color or th.TINTA, selectcolor=bg, bd=0,
                           relief="flat", offrelief="flat", overrelief="flat", highlightthickness=1,
                           highlightbackground=bg, highlightcolor=th.ACENTO, anchor="w", padx=0, pady=0)
        b._v = var
        if cmd:
            b.configure(command=lambda: cmd(var.get()))
        b.place(x=self.R(x), y=self.R(y), anchor="w")
        return b

    def boton(self, x, y, texto, estilo="TButton", icono=None, h=34, w=None, derecha=False, cmd=None, activo=True,
              padre=None):
        th = self.th
        b = ttk.Button(padre or self.raiz, text=texto, style=estilo, command=cmd)
        if icono:
            img = self.ctx.icono(icono)
            if img is not None:
                off = self.ctx.icono(icono + "-off") if icono in ("plus", "back") else img
                b.configure(image=(img, "disabled", off), compound="left")
                b.image = (img, off)
        if not activo:
            b.state(["disabled"])
        if w is None:
            fuente = "texto" if estilo.endswith("Quiet.TButton") else "fuerte"
            w = (self.ctx.medir(fuente, texto) / self.ctx.u * U_REF) + (23 if icono else 0) + \
                (34 if estilo.endswith("Quiet.TButton") else 40)
        b.place(x=self.R(x), y=self.R(y), width=self.R(w), height=self.R(h), anchor="ne" if derecha else "nw")
        return b

    def campo(self, x, y, w, h, valor="", mono=False, placeholder=None):
        e = ttk.Entry(self.raiz, style="Mono.TEntry" if mono else "TEntry", font=self.ctx.fuentes["mono" if mono else "texto"])
        if placeholder:
            try:
                e.configure(placeholder=placeholder)
            except tk.TclError:
                pass
        e.insert(0, valor)
        e.place(x=self.R(x), y=self.R(y), width=self.R(w), height=self.R(h))
        return e

    def segmentos(self, x, y, opciones, var, h=34, cmd=None):
        cx = x
        out = []
        for clave, texto, ico in opciones:
            tw = self.ctx.medir("fuerte", texto) / self.ctx.u * U_REF
            w = round(32 + (23 if ico else 0) + tw + 1)
            b = ttk.Radiobutton(self.raiz, text=texto, value=clave, variable=var, style="Segmento.Toolbutton", command=cmd)
            if ico:
                a, s = self.ctx.icono(ico), self.ctx.icono(ico + "-sel")
                b.configure(image=(a, "selected", s), compound="left")
                b.image = (a, s)
            b.place(x=self.R(cx), y=self.R(y), width=self.R(w), height=self.R(h))
            out.append(b)
            cx += w - 1
        return out


def estilos(ctx: Ctx):
    """La hoja de estilos plana de clam: lo mismo que 0.7.1 configura, sin `_controles()` (sin imágenes).

    clam pinta el borde en DOS anillos (`bordercolor` por fuera, `lightcolor`/`darkcolor` por dentro): con los
    tres del color del borde sale de 2 px. Para 1 px, el anillo interior sigue al fondo del estado; el anillo de
    foco (2 px de acento) pone los tres en acento, que es justo el del diseño."""
    th, R = ctx.th, lambda v: int(round(v * ctx.u / U_REF))
    s = ttk.Style(ctx.raiz)
    s.theme_use("clam")

    def pad(rol, lados):
        # `place` fija el alto del botón; el relleno vertical sólo tiene que dejar sitio al texto (y a los
        # bordes de clam), no repartir el alto: si pide más que el alto fijado, la letra se recorta.
        return (R(lados), 1)

    def caja(nombre, n, h, p, o, foco, lados=16, fuente="fuerte", base=None, **extra):
        """n/h/p/o = (fondo, letra, borde) normal / encima / pulsado / desactivado; foco = color del anillo."""
        s.configure(nombre, background=n[0], foreground=n[1], bordercolor=n[2], lightcolor=n[0], darkcolor=n[0],
                    relief="raised", borderwidth=1, padding=pad(fuente, lados), font=ctx.fuentes[fuente],
                    focuscolor=n[0], anchor="center", **extra)
        estados = lambda k: [("disabled", o[k]), ("pressed", p[k]), ("focus", foco if k == 2 else h[k]), ("active", h[k])]
        s.map(nombre, background=[("disabled", o[0]), ("pressed", p[0]), ("active", h[0])],
              foreground=[("disabled", o[1])],
              bordercolor=estados(2),
              lightcolor=[("disabled", o[0]), ("pressed", p[0]), ("focus", foco), ("active", h[0])],
              darkcolor=[("disabled", o[0]), ("pressed", p[0]), ("focus", foco), ("active", h[0])])

    s.configure(".", background=th.PAPEL, foreground=th.TINTA, font=ctx.fuentes["texto"])
    off = (th.APAGADO_FONDO, th.APAGADO, th.LINEA)
    caja("TButton", (th.SUPERFICIE, th.TINTA, th.BORDE), (th.GRIS_FONDO, th.TINTA, th.TINTA2),
         (th.LINEA, th.TINTA, th.TINTA2), off, th.ACENTO)
    caja("Primary.TButton", (th.ACENTO, th.SOBRE_ACENTO, th.ACENTO), (th.ACENTO_OSCURO, th.SOBRE_ACENTO, th.ACENTO_OSCURO),
         (th.ACENTO_OSCURO, th.SOBRE_ACENTO, th.ACENTO_OSCURO), off, th.SOBRE_ACENTO)
    caja("Danger.TButton", (th.SUPERFICIE, th.PELIGRO, th.PELIGRO), (th.PELIGRO_FONDO, th.PELIGRO, th.PELIGRO),
         (th.PELIGRO_FONDO, th.PELIGRO, th.PELIGRO), off, th.PELIGRO)
    s.configure("Grande.TButton", padding=pad("fuerte", 16))
    s.configure("Grande.Primary.TButton", padding=pad("fuerte", 16))
    for nombre, fondo in (("Quiet.TButton", th.PAPEL), ("CardQuiet.TButton", th.SUPERFICIE), ("GrisQuiet.TButton", th.GRIS_FONDO)):
        caja(nombre, (fondo, th.ACENTO, fondo), (th.ACENTO_SUAVE, th.ACENTO, th.ACENTO_SUAVE),
             (th.ACENTO_SUAVE, th.ACENTO, th.ACENTO_SUAVE), (fondo, th.APAGADO, fondo), th.ACENTO, lados=12,
             fuente="texto")
    caja("Segmento.Toolbutton", (th.SUPERFICIE, th.TINTA, th.BORDE), (th.GRIS_FONDO, th.TINTA, th.TINTA2),
         (th.LINEA, th.TINTA, th.TINTA2), off, th.ACENTO)
    s.map("Segmento.Toolbutton",
          background=[("selected", th.ACENTO_SUAVE), ("pressed", th.LINEA), ("active", th.GRIS_FONDO)],
          foreground=[("selected", th.ACENTO_OSCURO)],
          bordercolor=[("selected", th.ACENTO), ("active", th.TINTA2)],
          lightcolor=[("selected", th.ACENTO_SUAVE), ("pressed", th.LINEA), ("active", th.GRIS_FONDO)],
          darkcolor=[("selected", th.ACENTO_SUAVE), ("pressed", th.LINEA), ("active", th.GRIS_FONDO)])
    for nombre, fuente in (("TEntry", "texto"), ("Mono.TEntry", "mono")):
        s.configure(nombre, fieldbackground=th.SUPERFICIE, background=th.SUPERFICIE, foreground=th.TINTA,
                    insertcolor=th.TINTA, padding=pad(fuente, 12), selectbackground=th.ACENTO_SUAVE,
                    selectforeground=th.TINTA, placeholderforeground=th.TINTA3, bordercolor=th.BORDE,
                    lightcolor=th.SUPERFICIE, darkcolor=th.SUPERFICIE)
        s.map(nombre, bordercolor=[("focus", th.ACENTO)], lightcolor=[("focus", th.ACENTO)],
              darkcolor=[("focus", th.ACENTO)], fieldbackground=[("disabled", th.APAGADO_FONDO)])


# =====================================================================================================
def principal(ctx: Ctx, master, datos, abrir_parejas=None):
    th = ctx.th
    estilos(ctx)
    W, H = 558, 657
    P = Plano(ctx, master, W, H)
    R = P.R
    P.etiqueta(25, 42, "Sincronizar", "titulo")
    P.chip(W - 25, 41, f"{datos.revisar} que revisar", disco="disc-aviso", derecha=True, h=25)
    ruta = datos.carpeta + "  ·"
    P.etiqueta(25, 79, ruta, "mono", th.TINTA3, imagen="sub-dispositivo")
    ancho_ruta = ctx.medir("mono", ruta) / ctx.u * U_REF + 19
    P.etiqueta(25 + ancho_ruta + 8, 79, datos.remoto, "mono", th.TINTA3, imagen="sub-nas")
    P.etiqueta(25, 124, f"Hay {datos.revisar} cosas que revisar.", "texto", imagen="aviso")
    P.boton(W - 25, 107, "Reparación…", "Quiet.TButton", "reparar", derecha=True)
    P.etiqueta(25, 183, rotulo("Parejas"), "rotulo", th.TINTA3)
    marcadas = {p.name: p.name in datos.en_servicio for p in datos.parejas}
    cuenta = P.etiqueta(W - 25, 183, "", "pista", th.TINTA3, anchor="e")
    btn = P.boton(100, 166, "Marcar todas", "Quiet.TButton")
    n = len(datos.parejas)

    def refrescar():
        cuenta.configure(text=f"{sum(marcadas.values())} de {len(marcadas)}")
        btn.configure(text="Desmarcar todas" if all(marcadas.values()) else "Marcar todas")
    refrescar()
    tarjeta = P.caja(25, 208, 533, 208 + 7 + n * 45, th.SUPERFICIE, th.LINEA)
    cks = []
    for i, p in enumerate(datos.parejas):
        cy = 234 + i * 45 - 208

        def cambio(v, nombre=p.name):
            marcadas[nombre] = v
            refrescar()
        ck = P.casilla(14, cy, p.name, marcadas[p.name], cambio, "fuerte", padre=tarjeta)
        cks.append(ck)
        P.etiqueta(162 - 25, cy, p.mode, "pista", th.TINTA3, bg=th.SUPERFICIE, padre=tarjeta)
        P.etiqueta(506 - 25, cy, "–", "mono", th.TINTA3, bg=th.SUPERFICIE, anchor="e", padre=tarjeta)
        if i < n - 1:
            P.linea(13, cy + 22, 495, th.LINEA_SUAVE, padre=tarjeta)

    def todas():
        v = not all(marcadas.values())
        for ck, p in zip(cks, datos.parejas):
            marcadas[p.name] = v
            ck._v.set(v)
        refrescar()
    btn.configure(command=todas)
    P.boton(25, 453, "Parejas…", "Quiet.TButton", "parejas", w=136, cmd=abrir_parejas)
    P.boton(W - 25, 453, "Ajustes…", "Quiet.TButton", "ajustes", w=136, derecha=True)
    P.linea(25, 504, 533, th.LINEA)
    P.etiqueta(38, 525, "Al enchufarlo en este equipo: arranca el servicio.", "texto", th.TINTA2, imagen="arranque")
    P.boton(W - 29, 508, "Cambiar…", "Quiet.TButton", derecha=True)
    P.etiqueta(25, 560, "En pausa mientras esta ventana esté abierta.", "pista", th.TINTA3)
    P.boton(25, 596, "Sincronizar ahora", "Grande.Primary.TButton", "sync", h=44, w=348)
    P.boton(381, 596, "Iniciar servicio", "Grande.TButton", None, h=44, w=152)
    return P


TONOS_FILA = {"ok": ("SUPERFICIE", "disc-ok"), "aviso": ("AVISO_FONDO", "disc-aviso"),
              "peligro": ("PELIGRO_FONDO", "disc-peligro")}
ICONO_MODO = {"bisync": "chip-both", "up": "chip-up", "down": "chip-down"}


def parejas(ctx: Ctx, master, datos):
    th = ctx.th
    estilos(ctx)
    W, H = 1119, 1180
    P = Plano(ctx, master, W, H)
    R = P.R
    P.etiqueta(25, 42, "Parejas", "titulo")
    P.etiqueta(25, 75, "Una pareja se crea o se borra en el catálogo; cada dispositivo elige cuáles usa.", "pista", th.TINTA3)
    P.chip(1094, 37, datos.catalogo, disco="disc-acento", derecha=True, h=25)
    P.etiqueta(1094, 68, datos.endpoint, "mono", th.TINTA3, anchor="e")
    P.etiqueta(25, 113, rotulo("Qué estás editando"), "rotulo", th.TINTA3)
    vista = tk.StringVar(P.raiz, value="dispositivo")
    P.segmentos(25, 127, [("dispositivo", "Este dispositivo", "seg-dispositivo"), ("catalogo", "Catálogo", "seg-nas")], vista)
    # [defaults]
    franja = P.caja(25, 178, 1094, 228, th.GRIS_FONDO, th.LINEA)
    P.etiqueta(38 - 25, 203 - 178, rotulo("[defaults]"), "rotulo", th.TINTA3, bg=th.GRIS_FONDO, padre=franja)
    P.chip(134 - 25, 203 - 178, "catálogo", disco="disc-ok", h=25, padre=franja)
    P.etiqueta(229 - 25, 203 - 178,
               f"remote {datos.remoto} · device_remote {datos.cfg['defaults']['device_remote']} · sin flags comunes",
               "pista", th.TINTA3, bg=th.GRIS_FONDO, padre=franja)
    P.boton(887, 186, "Ajustes de este dispositivo…", "GrisQuiet.TButton", derecha=True)
    P.boton(1081, 186, "Volver a los del catálogo", "GrisQuiet.TButton", derecha=True)
    # lista
    n = len(datos.parejas)
    alto_fila = 42
    lista = P.caja(25, 245, 1094, 245 + 1 + 30 + n * alto_fila, th.SUPERFICIE, th.LINEA)
    for x, t in ((68, "Pareja"), (166, "Local ↔ remoto"), (853, "Modo"), (954, "Estado")):
        P.etiqueta(x - 25, 260 - 245, rotulo(t), "rotulo", th.TINTA3, bg=th.SUPERFICIE, padre=lista)
    P.linea(1, 275 - 245, 1067, th.LINEA, padre=lista)
    filas = {}
    editor = {}
    estado = {"elegida": None}

    def tono_de(p):
        return TONO_DE.get(p.estado, "ok")

    def color_fila(p):
        return getattr(th, TONOS_FILA[tono_de(p)][0])

    def pintar_fila(nombre):
        f = filas[nombre]
        bg = th.ACENTO_SUAVE if nombre == estado["elegida"] else color_fila(f["p"])
        for w in f["pintables"]:
            w.configure(bg=bg)

    def elegir(nombre):
        ant, estado["elegida"] = estado["elegida"], nombre
        if ant:
            pintar_fila(ant)
        pintar_fila(nombre)
        p = filas[nombre]["p"]
        editor["eyebrow"].configure(text=rotulo(f"Pareja elegida · {p.name}"))
        for clave, valor in (("nombre", p.name), ("local", p.local), ("remota", p.remote_path), ("remoto", "")):
            editor[clave].delete(0, "end")
            editor[clave].insert(0, valor)
        editor["modo"].set(p.mode)
        editor["hint_modo"].configure(text=f"Catálogo: {p.mode}")
        editor["hint_nombre"].configure(text=f"Nombra también su carpeta en state/. Catálogo: {p.name}")
        editor["hint_local"].configure(text=f"Relativa a la raíz del dispositivo. Catálogo: {p.local}")
        editor["hint_remota"].configure(text=f"En el remoto, p. ej. /datos/notas. Catálogo: {p.remote_path}")

    for i, p in enumerate(datos.parejas):
        y0 = 276 - 245 + i * alto_fila
        cy = 20
        fila = tk.Frame(lista, bd=0, highlightthickness=0, bg=color_fila(p))
        fila.place(x=1, y=R(y0), width=R(1067), height=R(alto_fila - 1))
        chk = P.etiqueta(14, cy, "", imagen="chk-on" if p.en_pen else "chk-off", bg=color_fila(p), padre=fila)
        peligro = tono_de(p) == "peligro"
        nom = P.etiqueta(68 - 26, cy, p.name, "fuerte", th.PELIGRO if peligro else th.TINTA, bg=color_fila(p), padre=fila)
        rut = P.etiqueta(166 - 26, cy, f"{p.local} ↔ nas:{p.remote_path}", "mono", th.PELIGRO if peligro else th.TINTA2,
                         bg=color_fila(p), padre=fila)
        espejo = p.mode.endswith("mirror")
        c1 = P.chip(853 - 26, cy, p.mode, icono=ICONO_MODO.get(p.mode), disco="disc-peligro-up" if espejo else None, h=24, padre=fila)
        c2 = P.chip(954 - 26, cy, p.estado, disco=TONOS_FILA[tono_de(p)][1], h=25, padre=fila)
        for w in (fila, chk, nom, rut, c1, c2):
            w.bind("<Button-1>", lambda e, nombre=p.name: elegir(nombre))
        filas[p.name] = dict(p=p, pintables=(fila, chk, nom, rut))
        if i < n - 1:
            P.linea(1, y0 + alto_fila - 1, 1067, th.LINEA_SUAVE, padre=lista)
    # editor
    editor["eyebrow"] = P.etiqueta(25, 513, "", "rotulo", th.TINTA3)
    tarj = P.caja(25, 531, 1094, 1043, th.SUPERFICIE, th.LINEA)
    X, Y = 25, 531          # origen de la tarjeta: el editor se coloca en la raíz con coordenadas absolutas
    sup = th.SUPERFICIE
    P.etiqueta(50, 560, "Nombre", "fuerte", bg=sup)
    editor["nombre"] = P.campo(50, 576, 460, 32)
    editor["hint_nombre"] = P.etiqueta(50, 623, "", "pista", th.TINTA3, bg=sup)
    P.etiqueta(50, 663, "Ruta local", "fuerte", bg=sup)
    editor["local"] = P.campo(50, 679, 316, 34, mono=True)
    P.boton(510, 679, "Examinar…", "CardQuiet.TButton", "carpeta", derecha=True, w=136)
    editor["hint_local"] = P.etiqueta(50, 728, "", "pista", th.TINTA3, bg=sup)
    P.etiqueta(50, 768, "Ruta remota", "fuerte", bg=sup)
    editor["remota"] = P.campo(50, 784, 316, 34, mono=True)
    P.boton(510, 784, "Examinar…", "CardQuiet.TButton", "nas-acento", derecha=True, w=136)
    editor["hint_remota"] = P.etiqueta(50, 833, "", "pista", th.TINTA3, bg=sup)
    P.etiqueta(50, 873, "Remoto", "fuerte", bg=sup)
    editor["remoto"] = P.campo(50, 889, 460, 34, mono=True, placeholder="vacío = el de [defaults]")
    P.etiqueta(50, 938, f"Vacío = el de [defaults] ({datos.remoto}). Catálogo: —", "pista", th.TINTA3, bg=sup)
    P.etiqueta(535, 560, "Modo", "fuerte", bg=sup)
    modo = tk.StringVar(P.raiz, value="bisync")
    editor["modo"] = modo
    P.segmentos(535, 580, [("bisync", "bisync", "seg-both"), ("up", "up", "seg-up"), ("down", "down", "seg-down"),
                           ("up-mirror", "up-mirror", "seg-up"), ("down-mirror", "down-mirror", "seg-down")], modo)
    editor["hint_modo"] = P.etiqueta(540, 633, "", "pista", th.TINTA3, bg=sup)
    P.casilla(536, 672, "Guardar en .prversions/ lo que se sobrescriba o se borre", False)
    P.etiqueta(560, 697, "Dentro de la pareja, en los dos lados. También el perdedor de un conflicto, en", "pista", th.TINTA3, bg=sup)
    P.etiqueta(560, 716, "vez de dejarlo suelto.", "pista", th.TINTA3, bg=sup)
    P.casilla(536, 753, "Sincronizar cuando cambien los ficheros locales", False)
    P.etiqueta(560, 778, "Solo con el agente residente. Lo del remoto espera al intervalo.", "pista", th.TINTA3, bg=sup)
    P.linea(50, 966, 1069, th.LINEA_SUAVE)
    P.etiqueta(50, 992, "Avanzado", "fuerte", bg=sup, imagen="flag")
    P.etiqueta(84, 1015, "Incluir, excluir y flags de rclone · ninguno propio", "pista", th.TINTA3, bg=sup)
    P.boton(1069, 986, "Mostrar", "CardQuiet.TButton", derecha=True, w=116)
    P.boton(25, 1060, "Usar aquí", "TButton", "plus", w=144, activo=False)
    b_simular = P.boton(177, 1060, "Simular", "TButton", "eye", w=144)
    P.boton(329, 1060, "Volver al catálogo", "TButton", "back", w=180, activo=False)
    P.boton(517, 1060, "Quitar…", "Danger.TButton", "trash", w=144)
    P.boton(948, 1060, "Descartar", "TButton", derecha=True, w=124)
    b_guardar = P.boton(1094, 1060, "Guardar aquí…", "Primary.TButton", derecha=True, w=138)
    P.linea(25, 1111, 1094, th.LINEA)
    P.etiqueta(25, 1146, "Antes de guardar se enseña qué va a pasar. Se guardará copia en sync_config.toml.bak", "mono", th.TINTA3)
    P.boton(962, 1129, "Dispositivos…", "Quiet.TButton", "dispositivos", derecha=True, w=139)
    P.boton(1094, 1129, "Cerrar", "TButton", derecha=True, w=124)
    elegir(datos.parejas[0].name)
    P.demo = dict(local=editor["local"], simular=b_simular, guardar=b_guardar, elegir=elegir, modo=editor["modo"])
    return P


def estado_demo(ctx, win, estado):
    """Para las capturas de estados: otra fila elegida, foco en un campo, «hover» en dos botones, otro modo."""
    P = win.get("l") or win.get("p")
    d = P.demo
    d["elegir"]("claves")
    d["modo"].set("up-mirror")
    d["local"].focus_force()
    for b in (d["simular"], d["guardar"]):
        b.state(["active"])
    P.raiz.update()


def encajar(ctx, top, P, libre):
    """Más alta que la pantalla: el visor se queda en lo que cabe y el contenido se desplaza con
    `place(y=-desplazamiento)`: una sola llamada por paso aunque haya cien widgets dentro."""
    th, h = P.th, P.H
    sb = tk.Scrollbar(top, orient="vertical", troughcolor=th.PAPEL, bg=th.LINEA, activebackground=th.BORDE,
                      relief="flat", bd=0, highlightthickness=0, elementborderwidth=0, width=P.R(12))
    sb.pack(side="right", fill="y", before=P.vp)
    P.vp.configure(height=libre)
    desp = [0]

    def ir(y):
        desp[0] = max(0, min(h - libre, int(y)))
        P.raiz.place(x=0, y=-desp[0])
        sb.set(desp[0] / h, (desp[0] + libre) / h)

    def barra(*a):
        if a[0] == "moveto":
            ir(float(a[1]) * h)
        else:
            ir(desp[0] + int(a[1]) * (P.R(20) if a[2] == "units" else libre * 0.9))
    sb.configure(command=barra)
    ir(0)
    top.bind("<MouseWheel>", lambda e: ir(desp[0] + (-1 if e.delta > 0 else 1) * P.R(40)))
    top.bind("<Button-4>", lambda e: ir(desp[0] - P.R(40)))
    top.bind("<Button-5>", lambda e: ir(desp[0] + P.R(40)))
