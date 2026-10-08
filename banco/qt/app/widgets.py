"""Los widgets del diseno 0.7.1 que QSS no puede dibujar solo: glifos vectoriales, chips con disco, casillas,
segmentos, baldosa de aviso.

Es del banco de la interfaz (temporal, ver `banco/LEEME.md`): port del prototipo Qt.

Todo se pinta con QPainter en el DPI real del widget (vectorial: nitido al 100 %, 150 %, 200 % y al cambiar de monitor),
con los colores del tema puesto (`estilo.T`) leidos AL PINTAR. Los glifos son la tabla `GLIFOS` de ui/icons.py
(primitivas sobre rejilla de 16, extremos cuadrados e ingletes: lo mismo que rasteriza icons.py a mano).
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QIcon, QIconEngine, QPainter, QPainterPath, QPen,
                           QPixmap)
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

import estilo
from glifos import GLIFOS, TRAZO, VISTO

AA = QPainter.RenderHint.Antialiasing


def color(clave: str) -> QColor:
    return QColor(estilo.T[clave])


# --------------------------------------------------------------------------------------------- glifos
def pintar_glifo(p: QPainter, nombre: str, rect: QRectF, col, trazo: float = TRAZO, prims=None) -> None:
    """Pinta un glifo de la rejilla de 16 dentro de `rect` (cuadrado)."""
    p.save()
    p.setRenderHint(AA, True)
    p.translate(rect.x(), rect.y())
    k = rect.width() / 16.0
    p.scale(k, k)
    col = QColor(col)
    pen = QPen(col, trazo)
    pen.setCapStyle(Qt.PenCapStyle.SquareCap)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for prim in (prims if prims is not None else GLIFOS[nombre]):
        c = prim[0]
        if c == "l":
            p.drawLine(QPointF(prim[1], prim[2]), QPointF(prim[3], prim[4]))
        elif c == "p":
            pts = prim[1]
            path = QPainterPath(QPointF(*pts[0]))
            for q in pts[1:]:
                path.lineTo(QPointF(*q))
            p.drawPath(path)
        elif c == "a":
            _, cx, cy, r, a0, a1 = prim
            p.drawArc(QRectF(cx - r, cy - r, 2 * r, 2 * r), int(round(-a0 * 16)), int(round(-(a1 - a0) * 16)))
        elif c == "c":
            p.drawEllipse(QPointF(prim[1], prim[2]), prim[3], prim[3])
        elif c == "d":
            p.drawPoint(QPointF(prim[1], prim[2]))
        elif c == "r":
            p.drawRect(QRectF(*prim[1:5]))
        elif c == "fr":
            p.fillRect(QRectF(*prim[1:5]), col)
        elif c == "rr":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(*prim[1:5]), prim[5], prim[5])
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
    p.restore()


class MotorGlifo(QIconEngine):
    """QIcon vectorial: lo pinta Qt al tamano y la densidad que pida el boton (nada de PNG cacheados)."""

    def __init__(self, nombre: str, clave: str = "TINTA2", apagado: str = "APAGADO") -> None:
        super().__init__()
        self.nombre, self.clave, self.apagado = nombre, clave, apagado

    def paint(self, painter, rect, mode, state) -> None:
        clave = self.apagado if mode == QIcon.Mode.Disabled else self.clave
        lado = min(rect.width(), rect.height())
        r = QRectF(rect.x() + (rect.width() - lado) / 2, rect.y() + (rect.height() - lado) / 2, lado, lado)
        pintar_glifo(painter, self.nombre, r, color(clave))

    def pixmap(self, size, mode, state) -> QPixmap:
        pm = QPixmap(size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        self.paint(p, QRect(QPoint(0, 0), size), mode, state)
        p.end()
        return pm

    def clone(self):
        return MotorGlifo(self.nombre, self.clave, self.apagado)


def icono(nombre: str, clave: str = "TINTA2", apagado: str = "APAGADO") -> QIcon:
    return QIcon(MotorGlifo(nombre, clave, apagado))


class Glifo(QWidget):
    """Un glifo suelto (para ponerlo al lado de un texto)."""

    def __init__(self, nombre: str, clave: str = "TINTA3", lado: int = 16, parent=None) -> None:
        super().__init__(parent)
        self.nombre, self.clave, self.lado = nombre, clave, lado
        self.setFixedSize(lado, lado)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        pintar_glifo(p, self.nombre, QRectF(0, 0, self.lado, self.lado), color(self.clave))


# ----------------------------------------------------------------------------------------- etiquetas
class Parrafo(QLabel):
    """Etiqueta con ajuste de linea cuyo ancho preferido es el del diseno (el `wraplength` de Tk).

    QLabel sola propone un ancho «cuadrado» para un texto largo y la caja lo respeta; aqui el preferido es `ancho`
    y puede encogerse (minimo 0) si la ventana es mas estrecha: el alto sale de `heightForWidth`.
    """

    def __init__(self, texto: str, ancho: int, parent=None) -> None:
        super().__init__(texto, parent)
        self.ancho = ancho
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

    def sizeHint(self) -> QSize:
        return QSize(self.ancho, self.heightForWidth(self.ancho))

    def minimumSizeHint(self) -> QSize:
        return QSize(0, self.heightForWidth(max(self.width(), 120)))


def etiqueta(texto: str = "", rol: str = "", ancho_max: int | None = None, parent=None) -> QLabel:
    lb = Parrafo(texto, ancho_max, parent) if ancho_max else QLabel(texto, parent)
    if rol:
        lb.setProperty("rol", rol)
    return lb


def rotulo(texto: str, parent=None) -> QLabel:
    """El «eyebrow» del diseno: mayusculas, 8 pt negrita, letras separadas."""
    lb = QLabel(texto.upper(), parent)
    lb.setProperty("rol", "rotulo")
    f = lb.font()
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.8)
    lb.setFont(f)
    return lb


def boton(texto: str, tipo: str = "", icono_: str | None = None, tam: str = "", color_icono: str | None = None,
          parent=None) -> QPushButton:
    b = QPushButton(texto, parent)
    if tipo:
        b.setProperty("tipo", tipo)
    if tam:
        b.setProperty("tam", tam)
    b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if icono_:
        clave = color_icono or {"primario": "SOBRE_ACENTO", "callado": "ACENTO", "peligro": "PELIGRO"}.get(tipo, "TINTA2")
        b.setIcon(icono(icono_, clave))
        b.setIconSize(QSize(16, 16))
    return b


def hairline(suave: bool = False) -> QFrame:
    f = QFrame()
    f.setObjectName("fileteSuave" if suave else "filete")
    f.setFixedHeight(1)
    return f


def tarjeta(nombre: str = "tarjeta") -> QFrame:
    f = QFrame()
    f.setObjectName(nombre)
    return f


# ------------------------------------------------------------------------------------------------ chip
_TONOS_CHIP = {  # tipo -> (clave del disco o None, glifo por defecto)
    "": (None, None), "Ok": ("OK", "ok"), "Aviso": ("AVISO", "alert"), "Peligro": ("PELIGRO", "close"),
    "Acento": ("ACENTO", "sync"), "Apagado": ("TINTA3", "clock"),
}
_SOBRE = {"OK": "SOBRE_OK", "AVISO": "SOBRE_AVISO", "PELIGRO": "SOBRE_PELIGRO", "ACENTO": "SOBRE_ACENTO",
          "TINTA3": "PAPEL"}


class Chip(QWidget):
    """Pastilla de estado: disco de color con su glifo + palabra en tinta. Neutro: icono pequeno + palabra."""

    def __init__(self, texto: str, tipo: str = "", icono_: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.texto, self.tipo = texto, tipo
        disco, defecto = _TONOS_CHIP[tipo]
        self.disco = disco
        self.glifo = ("alert" if icono_ == "warn" else icono_) or defecto
        f = QFont(self.font())
        f.setPointSizeF(9)
        self.setFont(f)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._ancho = None

    def sizeHint(self) -> QSize:
        fm = QFontMetricsF(self.font())
        w = fm.horizontalAdvance(self.texto)
        if self.disco:
            return QSize(int(3 + 18 + 5 + w + 10), 24)
        if self.glifo:
            return QSize(int(9 + 12 + 5 + w + 10), 24)
        return QSize(int(10 + w + 10), 24)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(AA, True)
        t = estilo.T
        apagado = self.tipo == "Apagado"
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(QColor(t["PAPEL"] if apagado else t["GRIS_FONDO"]))
        p.setPen(QPen(QColor(t["BORDE"] if apagado else t["LINEA"]), 1))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        x = 3.0
        if self.disco:
            c = QColor(t[self.disco])
            cx, cy = x + 9, self.height() / 2
            if apagado:                      # disco hueco
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(c, 1.1))
                p.drawEllipse(QPointF(cx, cy), 8.45, 8.45)
                pintar_glifo(p, self.glifo, QRectF(cx - 6, cy - 6, 12, 12), c, 2.0)
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(c)
                p.drawEllipse(QPointF(cx, cy), 9, 9)
                pintar_glifo(p, self.glifo, QRectF(cx - 6, cy - 6, 12, 12), QColor(t[_SOBRE[self.disco]]), 2.0)
            x += 18 + 5
        elif self.glifo:
            pintar_glifo(p, self.glifo, QRectF(9, self.height() / 2 - 6, 12, 12), QColor(t["TINTA2"]))
            x = 9 + 12 + 5
        else:
            x = 10
        p.setPen(QColor(t["TINTA3"] if apagado else t["TINTA"]))
        p.setFont(self.font())
        p.drawText(QRectF(x, 0, self.width() - x, self.height()),
                   int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.texto)


# --------------------------------------------------------------------------------------------- casilla
class Casilla(QCheckBox):
    """Casilla del diseno: 16 px, borde de 1 px, esquinas de 3, visto en trazo de 2,4."""

    LADO = 16

    def __init__(self, texto: str = "", fuerte: bool = False, parent=None) -> None:
        super().__init__(texto, parent)
        self.fuerte = fuerte
        if fuerte:
            f = self.font()
            f.setWeight(QFont.Weight.DemiBold)
            self.setFont(f)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        w = self.LADO + (8 + fm.horizontalAdvance(self.text()) if self.text() else 0)
        m = self.contentsMargins()
        return QSize(w + 2 + m.left() + m.right(), max(self.LADO + 4, fm.height() + 2))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(AA, True)
        t = estilo.T
        on, ok = self.isChecked(), self.isEnabled()
        cr = self.contentsRect()
        y = cr.y() + (cr.height() - self.LADO) / 2
        r = QRectF(cr.x() + 1, y, self.LADO, self.LADO)
        if on:
            fondo, borde = (t["ACENTO"], t["ACENTO"]) if ok else (t["APAGADO"], t["APAGADO"])
        else:
            fondo, borde = (t["SUPERFICIE"], t["BORDE"]) if ok else (t["APAGADO_FONDO"], t["LINEA"])
        p.setBrush(QColor(fondo))
        p.setPen(QPen(QColor(borde), 1))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 2.5, 2.5)
        if on:
            pintar_glifo(p, "", r, QColor(t["SOBRE_ACENTO"]), 2.4, VISTO)
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(t["ACENTO"]), 2))
            p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), 3.5, 3.5)
        if self.text():
            p.setFont(self.font())
            p.setPen(QColor(t["TINTA"] if ok else t["APAGADO"]))
            p.drawText(QRectF(cr.x() + 1 + self.LADO + 8, 0, self.width(), self.height()),
                       int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.text())


# ------------------------------------------------------------------------------------------- segmentos
class Segmentos(QWidget):
    """El ButtonGroup del diseno: botones pegados, uno elegido (ACENTO_SUAVE con borde de acento)."""

    cambiado = Signal(int)

    def __init__(self, opciones, actual: int = 0, parent=None) -> None:
        super().__init__(parent)
        self.opciones = list(opciones)           # (rotulo, valor, icono|None)
        self.actual = actual
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        f = self.font()
        f.setWeight(QFont.Weight.DemiBold)
        self.setFont(f)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._anchos = None

    def _medir(self):
        if self._anchos is None:
            fm = QFontMetricsF(self.font())
            self._anchos = [int(16 + (12 + 6 if ic else 0) + fm.horizontalAdvance(r) + 16 - 0.01)
                            for r, _v, ic in self.opciones]
        return self._anchos

    def sizeHint(self) -> QSize:
        return QSize(sum(self._medir()), 34)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _segmento_en(self, x: float) -> int:
        acc = 0
        for i, w in enumerate(self._medir()):
            acc += w
            if x < acc:
                return i
        return len(self.opciones) - 1

    def mousePressEvent(self, e) -> None:
        i = self._segmento_en(e.position().x())
        if i != self.actual:
            self.actual = i
            self.update()
            self.cambiado.emit(i)

    def keyPressEvent(self, e) -> None:
        d = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1}.get(e.key())
        if d is None:
            return super().keyPressEvent(e)
        i = max(0, min(len(self.opciones) - 1, self.actual + d))
        if i != self.actual:
            self.actual = i
            self.update()
            self.cambiado.emit(i)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(AA, True)
        t = estilo.T
        h = self.height()
        outer = QRectF(0.5, 0.5, self.width() - 1, h - 1)
        p.setBrush(QColor(t["SUPERFICIE"]))
        p.setPen(QPen(QColor(t["BORDE"]), 1))
        p.drawRoundedRect(outer, 4, 4)
        x = 0
        p.setFont(self.font())
        for i, (rot, _v, ic) in enumerate(self.opciones):
            w = self._medir()[i]
            sel = i == self.actual
            seg = QRectF(x + 0.5, 0.5, w - 1, h - 1)
            if sel:
                p.setBrush(QColor(t["ACENTO_SUAVE"]))
                p.setPen(QPen(QColor(t["ACENTO"]), 1))
                p.drawRoundedRect(seg, 4, 4)
            elif i:
                p.setPen(QPen(QColor(t["BORDE"]), 1))
                p.drawLine(QPointF(x + 0.5, 1), QPointF(x + 0.5, h - 1))
            tx = x + 16
            if ic:
                pintar_glifo(p, ic, QRectF(tx, h / 2 - 6, 12, 12), QColor(t["ACENTO_OSCURO"] if sel else t["TINTA2"]))
                tx += 12 + 6
            p.setPen(QColor(t["ACENTO_OSCURO"] if sel else t["TINTA"]))
            p.drawText(QRectF(tx, 0, w, h), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), rot)
            x += w
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(t["ACENTO"]), 2))
            p.drawRoundedRect(QRectF(1, 1, self.width() - 2, h - 2), 3.5, 3.5)


# ---------------------------------------------------------------------------------------------- aviso
class Baldosa(QWidget):
    """La baldosa solida de un aviso: cuadrado de 32 con esquinas de 4 y el glifo a 18."""

    def __init__(self, glifo: str, tono: str, parent=None) -> None:
        super().__init__(parent)
        self.glifo, self.tono = glifo, tono
        self.setFixedSize(32, 32)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(AA, True)
        t = estilo.T
        col, sobre = {"ambar": ("AVISO", "SOBRE_AVISO"), "rojo": ("PELIGRO", "SOBRE_PELIGRO"),
                      "azul": ("ACENTO", "SOBRE_ACENTO"), "verde": ("OK", "SOBRE_OK")}[self.tono]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t[col]))
        p.drawRoundedRect(QRectF(0, 0, 32, 32), 4, 4)
        pintar_glifo(p, self.glifo, QRectF(7, 7, 18, 18), QColor(t[sobre]), 1.8)


_GLIFO_AVISO = {"ambar": "alert", "rojo": "close", "azul": "doctor", "verde": "ok"}


class Aviso(QFrame):
    """Aviso del diseno: baldosa solida + titulo en seminegrita + cuerpo en tinta suave, sobre el fondo suave del tono."""

    def __init__(self, titulo: str, cuerpo: str = "", tono: str = "ambar", ancho: int = 480, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("aviso", tono)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(12)
        lay.addWidget(Baldosa(_GLIFO_AVISO[tono], tono), 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(4)
        if titulo:
            col.addWidget(etiqueta(titulo, "fuerte", ancho))
        if cuerpo:
            col.addWidget(etiqueta(cuerpo, "campo" if titulo else "", ancho))
        self.columna = col
        self.acciones = None                      # la fila de botones se crea al poner el primero
        lay.addLayout(col, 1)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)


def _poner_accion(aviso: "Aviso", boton_) -> None:
    if aviso.acciones is None:
        aviso.acciones = QHBoxLayout()
        aviso.acciones.setContentsMargins(0, 0, 0, 0)
        aviso.acciones.addStretch(1)
        aviso.columna.addLayout(aviso.acciones)
    aviso.acciones.insertWidget(aviso.acciones.count() - 1, boton_)


Aviso.poner_accion = _poner_accion


class Indicador(QWidget):
    """La barra indeterminada de «leyendo el catalogo…» (aqui estatica: la real animaria un QVariantAnimation)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(90, 8)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(AA, True)
        t = estilo.T
        p.setPen(QPen(QColor(t["LINEA"]), 1))
        p.setBrush(QColor(t["GRIS_FONDO"]))
        p.drawRoundedRect(QRectF(0.5, 0.5, 89, 7), 3.5, 3.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t["ACENTO"]))
        p.drawRoundedRect(QRectF(1.5, 1.5, 22, 5), 2.5, 2.5)
