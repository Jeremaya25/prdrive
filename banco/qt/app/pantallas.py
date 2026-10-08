"""Las tres pantallas del prototipo, en el diseno 0.7.1: ventana principal, «Parejas» y «Ajustes».

Es del banco de la interfaz (temporal, ver `banco/LEEME.md`): port del prototipo Qt.

Cada pantalla recibe el dict de `datos.py` (sale de los modulos headless del dispositivo); aqui solo se dibuja:
las decisiones siguen en `ui/pair_editor.py` & co. Cada ventana cuenta sus `paintEvent` del nivel superior
(`pintados`): es lo que usa `qtmain.py` para saber cuando esta «completamente pintada».
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLineEdit, QScrollArea, QSpinBox,
                               QStackedWidget, QVBoxLayout, QWidget)

from widgets import (Aviso, Casilla, Chip, Glifo, Indicador, Segmentos, boton, etiqueta, hairline, rotulo,
                     tarjeta)


class Ventana(QWidget):
    """Base de las ventanas de nivel superior: fondo de papel y cuenta de pintados."""

    def __init__(self, titulo: str, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setObjectName("raiz")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Al cerrarla se borra: una ventana que sigue referenciada al terminar el
        # intérprete hace caer a PySide (QWidget::destroy, exit 139 en Linux).
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(titulo)
        self.pintados = 0

    def paintEvent(self, e) -> None:
        self.pintados += 1

    def centrar(self) -> None:
        pantalla = (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        g = self.frameGeometry()
        g.moveCenter(pantalla.center())
        self.move(g.topLeft())


def _vbox(parent=None, margenes=(0, 0, 0, 0), sep=0) -> QVBoxLayout:
    lay = QVBoxLayout(parent) if parent is not None else QVBoxLayout()
    lay.setContentsMargins(*margenes)
    lay.setSpacing(sep)
    return lay


def _hbox(parent=None, margenes=(0, 0, 0, 0), sep=0) -> QHBoxLayout:
    lay = QHBoxLayout(parent) if parent is not None else QHBoxLayout()
    lay.setContentsMargins(*margenes)
    lay.setSpacing(sep)
    return lay


# ------------------------------------------------------------------------------------ ventana principal
class VentanaPrincipal(Ventana):
    pide_parejas = Signal()
    pide_ajustes = Signal()

    def __init__(self, st: dict) -> None:
        super().__init__("prdrive")
        self.st = st
        raiz = _vbox(self, (26, 26, 26, 31))
        # cabecera: titulo + chip de estado
        fila = _hbox(sep=8)
        fila.addWidget(etiqueta("Sincronizar", "titulo"))
        fila.addStretch(1)
        tipo, texto = st["estado"]
        fila.addWidget(Chip(texto, tipo), 0, Qt.AlignmentFlag.AlignTop)
        raiz.addLayout(fila)
        # subtitulo: ruta del dispositivo · remoto
        sub = _hbox(sep=6)
        sub.setContentsMargins(0, 13, 0, 0)
        sub.addWidget(Glifo("dispositivo", "TINTA3", 14))
        sub.addWidget(etiqueta(st["raiz"], "monopista"))
        sub.addWidget(etiqueta("·", "pista"))
        sub.addWidget(Glifo("nas", "TINTA3", 14))
        sub.addWidget(etiqueta(", ".join(st["remotos"]), "monopista"))
        sub.addStretch(1)
        raiz.addLayout(sub)
        raiz.addSpacing(28)
        # cabecera de la lista
        cab = _hbox(sep=14)
        cab.addWidget(rotulo("Parejas"))
        self.marcar_todas = boton("Marcar todas", "callado", tam="pequeno")
        cab.addWidget(self.marcar_todas)
        cab.addStretch(1)
        marcadas = sum(1 for p in st["pares"] if p["marcada"])
        self.cuenta = etiqueta(f"{marcadas} de {len(st['pares'])} · última pasada {st['ultima']}", "campo")
        self.cuenta.setProperty("rol", "pistacampo")
        cab.addWidget(self.cuenta)
        raiz.addLayout(cab)
        raiz.addSpacing(10)
        # lista: una tarjeta con una fila por pareja
        card = tarjeta()
        g = QGridLayout(card)
        g.setContentsMargins(10, 4, 10, 4)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(0)
        g.setColumnStretch(1, 1)
        self.casillas = []
        for i, par in enumerate(st["pares"]):
            r = i * 2
            c = Casilla(par["nombre"], fuerte=True)
            c.setChecked(par["marcada"])
            c.setMinimumHeight(43)
            self.casillas.append(c)
            g.addWidget(c, r, 0)
            g.addWidget(etiqueta(par["modo"], "pista"), r, 1)
            g.addWidget(etiqueta(par["hora"], "monopista"), r, 2, Qt.AlignmentFlag.AlignRight)
            if i < len(st["pares"]) - 1:
                g.addWidget(hairline(True), r + 1, 0, 1, 3)
        g.setColumnMinimumWidth(0, 130)
        raiz.addWidget(card)
        raiz.addSpacing(12)
        # acciones de pantalla
        acc = _hbox(sep=8)
        acc.setContentsMargins(16, 0, 16, 0)
        self.b_parejas = boton("Parejas…", "callado", "parejas")
        self.b_ajustes = boton("Ajustes…", "callado", "gear")
        self.b_parejas.clicked.connect(self.pide_parejas)
        self.b_ajustes.clicked.connect(self.pide_ajustes)
        acc.addWidget(self.b_parejas)
        acc.addStretch(1)
        acc.addWidget(self.b_ajustes)
        raiz.addLayout(acc)
        raiz.addSpacing(15)
        raiz.addWidget(hairline())
        # linea de estado del vigilante
        vig = st["vigilante"]
        if vig:
            lin = _hbox(margenes=(14, 6, 8, 6), sep=12)
            lin.addWidget(Glifo("arranque", "TINTA3", 16))
            lin.addWidget(etiqueta(vig["texto"], "campo"), 1)
            if vig["boton"]:
                lin.addWidget(boton(vig["boton"], "callado", tam="pequeno"))
            raiz.addLayout(lin)
        raiz.addSpacing(24)
        # pie: sincronizar / servicio
        pie = _hbox(sep=8)
        self.b_sync = boton("Sincronizar ahora", "primario", "sync", "grande")
        self.b_serv = boton("Iniciar servicio", "", None, "grande")
        pie.addWidget(self.b_sync, 3)
        pie.addWidget(self.b_serv, 2)
        raiz.addLayout(pie)
        self.setFixedWidth(531)


# ------------------------------------------------------------------------------------------ «Parejas»
class VentanaParejas(Ventana):
    def __init__(self, dp: dict, st: dict, parent=None) -> None:
        super().__init__("Parejas", parent)
        self.dp = dp
        marco = _vbox(self)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        marco.addWidget(sc)
        self.scroll = sc
        cont = QWidget()
        cont.setObjectName("raiz")
        cont.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sc.setWidget(cont)
        self.contenido = cont
        raiz = _vbox(cont, (26, 28, 26, 24))

        # --- cabecera
        cab = QGridLayout()
        cab.setHorizontalSpacing(12)
        cab.setVerticalSpacing(4)
        cab.addWidget(etiqueta("Parejas", "dialogo"), 0, 0)
        cab.addWidget(etiqueta("Una pareja se crea o se borra en el catálogo; cada dispositivo elige cuáles usa.",
                               "pistacampo"), 1, 0)
        cab.addWidget(Chip(f"copia local · {dp['sello']}", "Apagado", "clock"), 0, 1, Qt.AlignmentFlag.AlignRight)
        cab.addWidget(etiqueta(dp["endpoint"], "monopista"), 1, 1, Qt.AlignmentFlag.AlignRight)
        cab.setColumnStretch(0, 1)
        raiz.addLayout(cab)
        raiz.addSpacing(10)
        ind = _hbox(sep=12)
        ind.addWidget(Indicador())
        ind.addWidget(etiqueta(f"Leyendo el catálogo del remoto. Mientras llega se enseña la copia local del "
                               f"{dp['sello']}, que no se puede editar.", "pistacampo"), 1)
        raiz.addLayout(ind)
        raiz.addSpacing(18)
        # --- que estas editando
        raiz.addWidget(rotulo("Qué estás editando"))
        raiz.addSpacing(8)
        fila = _hbox(sep=14)
        fila.addWidget(Segmentos([("Este dispositivo", "dev", "dispositivo"), ("Catálogo", "cat", "nas")], 0))
        fila.addStretch(1)
        raiz.addLayout(fila)
        raiz.addSpacing(14)
        # --- defaults
        fr = QFrame()
        fr.setObjectName("franja")
        fl = _hbox(fr, (14, 10, 14, 10), 10)
        lb = etiqueta("[DEFAULTS]", "monopista")
        f = lb.font()
        f.setWeight(QFont.Weight.Bold)
        lb.setFont(f)
        fl.addWidget(lb)
        fl.addWidget(Chip("catálogo", "Ok"))
        fl.addWidget(etiqueta(f"remote {dp['remote']} · sin device_remote · sin flags comunes", "pistacampo"))
        fl.addStretch(1)
        fl.addWidget(boton("Ajustes de este dispositivo…", "callado", tam="pequeno"))
        fl.addWidget(boton("Volver a los del catálogo", "callado", tam="pequeno"))
        raiz.addWidget(fr)
        raiz.addSpacing(16)
        # --- tabla
        card = tarjeta()
        g = QGridLayout(card)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(0)
        g.setVerticalSpacing(0)
        g.setColumnStretch(2, 1)
        cabeceras = ["Pareja", "Local ↔ remoto", "Modo", "Estado"]
        # cabecera de la tabla
        g.setColumnMinimumWidth(0, 135)
        for c, (col, txt) in enumerate(zip((0, 2, 3, 4), cabeceras)):
            lbl = rotulo(txt)
            g.addWidget(lbl, 0, col, Qt.AlignmentFlag.AlignVCenter)
            lbl.setContentsMargins(0 if c else 43, 0, 0, 0)
            lbl.setMinimumHeight(30)
        g.addWidget(hairline(), 1, 0, 1, 5)
        self.filas = []
        r = 2
        for i, f in enumerate(dp["filas"]):
            sel = i == 0
            usada = f["en_pen"]
            if sel:
                fondo = QFrame()
                fondo.setObjectName("filaSel")
                g.addWidget(fondo, r, 0, 1, 5)
            cas = Casilla(f["nombre"], fuerte=usada)
            cas.setChecked(usada)
            cas.setContentsMargins(14, 0, 0, 0)
            cas.setMinimumHeight(40)
            cas.setStyleSheet("")
            g.addWidget(cas, r, 0, 1, 2)
            local = etiqueta(f"{f['local']} ↔ {f['remoto']}", "mono")
            if not usada:
                local.setProperty("rol", "monopista")
            g.addWidget(local, r, 2)
            g.addWidget(Chip(f["modo"], "", {"bisync": "both", "up": "up", "down": "down", "up-mirror": "up",
                                              "down-mirror": "down"}.get(f["modo"])), r, 3)
            tono = {"ok": "Ok", "apagado": "Apagado", "aviso": "Aviso", "peligro": "Peligro"}.get(f["tono"], "Ok")
            g.addWidget(Chip(f["estado"], tono), r, 4)
            g.setColumnMinimumWidth(3, 90)
            g.setColumnMinimumWidth(4, 132)
            r += 1
            if i < len(dp["filas"]) - 1:
                g.addWidget(hairline(True), r, 0, 1, 5)
                r += 1
        raiz.addWidget(card)
        raiz.addSpacing(22)
        # --- pareja elegida
        raiz.addWidget(rotulo("Pareja elegida · documentos"))
        raiz.addSpacing(10)
        form = tarjeta()
        fg = QGridLayout(form)
        fg.setContentsMargins(24, 16, 24, 16)
        fg.setHorizontalSpacing(24)
        fg.setVerticalSpacing(0)
        izq = _vbox(sep=0)
        izq.addWidget(etiqueta("Nombre", "fuerte"))
        izq.addSpacing(4)
        izq.addWidget(self._campo("documentos"))
        izq.addSpacing(4)
        izq.addWidget(etiqueta("Nombra también su carpeta en state/. Catálogo: documentos", "pistacampo"))
        izq.addSpacing(14)
        izq.addWidget(etiqueta("Ruta local", "fuerte"))
        izq.addSpacing(4)
        fl2 = _hbox(sep=14)
        fl2.addWidget(self._campo("sync-data/documentos"), 1)
        fl2.addWidget(boton("Examinar…", "callado", "carpeta"))
        izq.addLayout(fl2)
        izq.addSpacing(4)
        izq.addWidget(etiqueta("Relativa a la raíz del dispositivo. Catálogo: sync-data/documentos", "pistacampo"))
        izq.addSpacing(14)
        izq.addWidget(etiqueta("Ruta remota", "fuerte"))
        izq.addSpacing(4)
        fl3 = _hbox(sep=14)
        fl3.addWidget(self._campo("/datos/documentos"), 1)
        b = boton("Examinar…", "callado", "nas")
        b.setEnabled(False)
        fl3.addWidget(b)
        izq.addLayout(fl3)
        fg.addLayout(izq, 0, 0)
        der = _vbox(sep=0)
        der.addWidget(etiqueta("Modo", "fuerte"))
        der.addSpacing(4)
        ic = {"bisync": "both", "up": "up", "down": "down", "up-mirror": "up", "down-mirror": "down"}
        seg = Segmentos([(m, m, ic[m]) for m in dp["modos"]], 0)
        der.addWidget(seg, 0, Qt.AlignmentFlag.AlignLeft)
        der.addSpacing(4)
        der.addWidget(etiqueta("Catálogo: bisync", "pistacampo"))
        der.addSpacing(18)
        for txt, hint in (("Guardar en .prversions/ lo que se sobrescriba o se borre",
                           "Dentro de la pareja, en los dos lados. También el perdedor de un conflicto, en vez de dejarlo suelto."),
                          ("Sincronizar cuando cambien los ficheros locales",
                           "Solo con el agente residente. Lo remoto espera al intervalo.")):
            der.addWidget(Casilla(txt))
            h = etiqueta(hint, "pistacampo", 440)
            h.setContentsMargins(26, 0, 0, 0)
            der.addWidget(h)
            der.addSpacing(12)
        der.addStretch(1)
        fg.addLayout(der, 0, 1)
        fg.setColumnStretch(0, 1)
        fg.setColumnStretch(1, 1)
        raiz.addWidget(form)
        raiz.addSpacing(16)
        # --- pie
        pie = _hbox(sep=8)
        b1 = boton("Usar aquí", "", "plus")
        b1.setEnabled(False)
        pie.addWidget(b1)
        pie.addWidget(boton("Simular", "", "eye"))
        pie.addWidget(boton("Volver al catálogo", "", "back"))
        pie.addWidget(boton("Quitar…", "peligro", "trash"))
        pie.addStretch(1)
        pie.addWidget(boton("Descartar", ""))
        pie.addWidget(boton("Guardar aquí…", "primario"))
        raiz.addLayout(pie)
        self.resize(1092, 900)

    @staticmethod
    def _campo(texto: str) -> QLineEdit:
        e = QLineEdit(texto)
        return e

    def ajustar_a_pantalla(self) -> None:
        """Alto = lo que pide el contenido, o lo que cabe en la pantalla (entonces el Visor desplaza)."""
        pant = (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        cont = self.contenido.sizeHint()
        self.resize(1092, min(cont.height() + 2, pant.height() - 60))


# -------------------------------------------------------------------------------------------- «Ajustes»
GRUPOS = [
    ("Esta unidad", [("nombre", "Nombre e icono", "edit"), ("config", "Configuración", "gear"),
                     ("llavero", "Llavero", "llave"), ("versiones", "Versiones", "file")]),
    ("Este equipo", [("arranque", "Arranque automático", "arranque")]),
    ("Conexión", [("movil", "Emparejar un móvil", "dispositivo")]),
    ("Mantenimiento", [("reparacion", "Reparación", "doctor"), ("actualizaciones", "Actualizaciones", "reload")]),
]


class VentanaAjustes(Ventana):
    def __init__(self, st: dict, datos_mod, parent=None) -> None:
        super().__init__("Ajustes", parent)
        self.st, self.datos = st, datos_mod
        self.paneles: dict[str, QWidget] = {}
        raiz = _vbox(self, (26, 24, 26, 24), 0)
        cab = _hbox(sep=12)
        cab.addWidget(etiqueta("Ajustes", "dialogo"))
        cab.addStretch(1)
        self.buscar = QLineEdit()
        self.buscar.setPlaceholderText("Buscar un ajuste…")
        self.buscar.setFixedWidth(332)
        cab.addWidget(self.buscar)
        raiz.addLayout(cab)
        raiz.addSpacing(8)
        cuerpo = _hbox(sep=24)
        # barra lateral
        lat = QWidget()
        lat.setFixedWidth(250)
        lv = _vbox(lat, (0, 0, 0, 0), 2)
        self.botones: dict[str, object] = {}
        grupo = QButtonGroup(self)
        grupo.setExclusive(True)
        self.grupo = grupo
        self.rotulos = []
        for k, (titulo, items) in enumerate(GRUPOS):
            r = rotulo(titulo)
            r.setContentsMargins(14, 12 if k else 6, 0, 4)
            lv.addWidget(r)
            for clave, rot, ic in items:
                b = boton(rot, "lateral", ic, color_icono="TINTA2")
                b.setCheckable(True)
                b.setProperty("clave", clave)
                grupo.addButton(b)
                b.clicked.connect(lambda _=False, c=clave: self.mostrar(c))
                self.botones[clave] = b
                lv.addWidget(b)
        lv.addStretch(1)
        lv.addWidget(etiqueta(f"prdrive {st['version']} · {st['nombre']}", "pista"))
        lv.setContentsMargins(0, 0, 0, 6)
        cuerpo.addWidget(lat)
        # area del apartado
        self.pila = QStackedWidget()
        self.pila.setMinimumSize(640, 420)
        cuerpo.addWidget(self.pila, 1)
        raiz.addLayout(cuerpo, 1)
        self.buscar.textChanged.connect(self.filtrar)
        self.resize(976, 593)

    # --- busqueda: cada palabra tecleada debe empezar una palabra del rotulo (sin tildes ni mayusculas)
    def filtrar(self, texto: str) -> None:
        import unicodedata

        def norm(s):
            return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")
        palabras = norm(texto).split()
        for clave, b in self.botones.items():
            rot = norm(b.text()).split()
            b.setVisible(all(any(w.startswith(p) for w in rot) for p in palabras))

    def mostrar(self, clave: str) -> None:
        if clave not in self.paneles:
            p = self._construir(clave)
            self.paneles[clave] = p
            self.pila.addWidget(p)
        self.botones[clave].setChecked(True)
        self.pila.setCurrentWidget(self.paneles[clave])

    # --- paneles
    def _construir(self, clave: str) -> QWidget:
        w = QWidget()
        v = _vbox(w, (0, 0, 0, 0), 0)
        titulo = {k: r for g in GRUPOS for k, r, _i in g[1]}[clave]
        v.addWidget(etiqueta(titulo, "seccion"))
        v.addSpacing(4)
        if clave == "config":
            v.addWidget(etiqueta("Cómo trabaja el servicio de este dispositivo. Nada cambia hasta pulsar «Guardar».",
                                 "pistacampo"))
            v.addSpacing(14)
            card = tarjeta()
            cl = _vbox(card, (16, 10, 16, 12), 8)
            fila = _hbox(sep=12)
            fila.addWidget(Glifo("clock", "TINTA3", 16))
            fila.addWidget(etiqueta("El servicio repite cada", "campo"))
            sp = QSpinBox()
            sp.setRange(1, 1440)
            sp.setValue(int(self.st["minutos"]))
            sp.setFixedWidth(84)
            fila.addWidget(sp)
            fila.addWidget(etiqueta("minutos, mientras el dispositivo siga puesto", "pistacampo"))
            fila.addStretch(1)
            cl.addLayout(fila)
            h = etiqueta("Lo usa el servicio se arranque como se arranque (con «Iniciar servicio», al enchufarlo o el "
                         "agente de este equipo) y viaja con el dispositivo. Vale desde la próxima vez que se ponga en "
                         "marcha; «Sincronizar ahora» no lo usa.", "pistacampo", 520)
            h.setContentsMargins(28, 0, 0, 0)
            cl.addWidget(h)
            v.addWidget(card)
            v.addStretch(1)
            v.addWidget(hairline())
            v.addSpacing(10)
            pie = _hbox(sep=8)
            pie.addStretch(1)
            pie.addWidget(boton("Cancelar", ""))
            pie.addWidget(boton("Guardar", "primario"))
            v.addLayout(pie)
        elif clave == "reparacion":
            v.addWidget(etiqueta("Lo que está mal en este dispositivo, y lo que se puede hacer con ello. Nada se toca "
                                 "sin que lo confirmes antes.", "pistacampo", 560))
            v.addSpacing(14)
            hall = self.datos.reparacion()
            if not hall:
                card = tarjeta()
                cl = _vbox(card, (16, 14, 16, 14))
                cl.addWidget(etiqueta("No hay nada que revisar: las parejas tienen su baseline, no hay conflictos y la "
                                      "última pasada de cada una fue bien.", "", 500))
                v.addWidget(card)
            else:
                for h in hall:
                    v.addWidget(Aviso(h["titulo"], h["detalle"], "ambar", 520))
            v.addSpacing(10)
            v.addStretch(1)
            v.addWidget(hairline())
            v.addSpacing(10)
            pie = _hbox(sep=8)
            pie.addWidget(boton("Simular una pasada…", "callado", "eye"))
            pie.addWidget(boton("Ver el informe completo", "callado", "doctor"))
            pie.addStretch(1)
            pie.addWidget(boton("Cerrar", ""))
            v.addLayout(pie)
        elif clave == "actualizaciones":
            v.addWidget(etiqueta("La versión instalada y las que hay en el remoto.", "pistacampo"))
            v.addSpacing(14)
            av = Aviso("Hay una versión nueva: prdrive 0.7.2",
                       "Instalada: " + self.st["version"] + ". Se descarga en la unidad y se aplica al cerrar la ventana.",
                       "azul", 520)
            av.poner_accion(boton("Ver novedades", "callado", tam="pequeno"))
            v.addWidget(av)
            v.addSpacing(10)
            av2 = Aviso("Un espejo borra en el otro lado", "up-mirror: lo que no esté aquí se borra en el remoto. "
                        "Simula antes con --dry-run.", "ambar", 520)
            v.addWidget(av2)
            v.addStretch(1)
            v.addWidget(hairline())
            v.addSpacing(10)
            pie = _hbox(sep=8)
            pie.addStretch(1)
            pie.addWidget(boton("Cerrar", ""))
            pie.addWidget(boton("Actualizar", "primario", "reload"))
            v.addLayout(pie)
        else:
            v.addWidget(etiqueta("(Panel no incluido en el prototipo.)", "pistacampo"))
            v.addStretch(1)
        return w
