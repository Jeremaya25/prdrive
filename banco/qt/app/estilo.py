"""La hoja de estilo QSS y la paleta, generadas a partir de los tokens de theme.py (tokens.py).

Es del banco de la interfaz (temporal, ver `banco/LEEME.md`): port del prototipo Qt.

Una sola hoja para toda la aplicacion: los colores son los de `tokens.CLARO` / `tokens.OSCURO`, la escala de
espacios y las alturas de control las del diseno 0.7.1 (34 boton/campo, 28 pequeno, 42 grande, 32 fila lateral).
`T` es el tema puesto (un dict); los widgets pintados a mano (chip, casilla, segmentos) lo leen al pintar, asi que
cambiar de tema es `usar()` + `app.setStyleSheet(hoja())` + `update()`.
"""
from __future__ import annotations

from pathlib import Path

import tokens

RUTA = (Path(__file__).resolve().parent / "style").as_posix()   # PNG de las flechas del spinbox (lib/gen_png.py)
T: dict[str, str] = dict(tokens.CLARO)
TEMA = "claro"
MONO = "Noto Sans Mono"


def usar(tema: str) -> None:
    global TEMA
    T.clear()
    T.update(tokens.OSCURO if tema == "oscuro" else tokens.CLARO)
    TEMA = tema


def hoja() -> str:
    """Devuelve el QSS del tema puesto."""
    t = T
    return f"""
QWidget#raiz {{ background: {t['PAPEL']}; }}
QLabel {{ color: {t['TINTA']}; background: transparent; }}
QLabel[rol="titulo"]   {{ font-size: 16pt; font-weight: 600; }}
QLabel[rol="dialogo"]  {{ font-size: 14pt; font-weight: 600; }}
QLabel[rol="seccion"]  {{ font-size: 11pt; font-weight: 600; }}
QLabel[rol="fuerte"]   {{ font-weight: 600; }}
QLabel[rol="pista"]    {{ font-size: 9pt; color: {t['TINTA3']}; }}
QLabel[rol="campo"]    {{ color: {t['TINTA2']}; }}
QLabel[rol="pistacampo"] {{ font-size: 9pt; color: {t['TINTA2']}; }}
QLabel[rol="rotulo"]   {{ font-size: 8pt; font-weight: 700; color: {t['TINTA3']}; }}
QLabel[rol="mono"]     {{ font-family: "{MONO}"; font-size: 9pt; color: {t['TINTA2']}; }}
QLabel[rol="monopista"] {{ font-family: "{MONO}"; font-size: 8pt; color: {t['TINTA3']}; }}
QLabel[rol="apagado"]  {{ color: {t['TINTA3']}; }}
QLabel[rol="acento"]   {{ color: {t['ACENTO']}; }}

QFrame#tarjeta {{ background: {t['SUPERFICIE']}; border: 1px solid {t['LINEA']}; border-radius: 4px; }}
QFrame#franja  {{ background: {t['GRIS_FONDO']}; border: 1px solid {t['LINEA']}; border-radius: 4px; }}
QFrame#filaSel {{ background: {t['ACENTO_SUAVE']}; border: none; border-radius: 0; }}
QFrame#filete  {{ background: {t['LINEA']}; border: none; max-height: 1px; min-height: 1px; }}
QFrame#fileteSuave {{ background: {t['LINEA_SUAVE']}; border: none; max-height: 1px; min-height: 1px; }}
QFrame[aviso="ambar"] {{ background: {t['AVISO_FONDO']}; border: 1px solid {t['AVISO_BORDE']}; border-radius: 4px; }}
QFrame[aviso="rojo"]  {{ background: {t['PELIGRO_FONDO']}; border: 1px solid {t['PELIGRO_BORDE']}; border-radius: 4px; }}
QFrame[aviso="azul"]  {{ background: {t['ACENTO_SUAVE']}; border: 1px solid {t['ACENTO_BORDE']}; border-radius: 4px; }}
QFrame[aviso="verde"] {{ background: {t['OK_FONDO']}; border: 1px solid {t['OK_BORDE']}; border-radius: 4px; }}

QPushButton {{
  background: {t['SUPERFICIE']}; color: {t['TINTA']};
  border: 1px solid {t['BORDE']}; border-radius: 4px;
  padding: 0 15px; min-height: 32px; font-weight: 600;
}}
QPushButton:hover    {{ background: {t['GRIS_FONDO']}; }}
QPushButton:pressed  {{ background: {t['LINEA']}; }}
QPushButton:focus    {{ border: 2px solid {t['ACENTO']}; padding: 0 14px; }}
QPushButton:disabled {{ background: {t['APAGADO_FONDO']}; color: {t['APAGADO']}; border: 1px solid {t['LINEA']}; }}
QPushButton[tam="pequeno"] {{ min-height: 26px; padding: 0 11px; }}
QPushButton[tam="grande"]  {{ min-height: 38px; }}
QPushButton[tipo="primario"] {{ background: {t['ACENTO']}; color: {t['SOBRE_ACENTO']}; border: 1px solid {t['ACENTO']}; }}
QPushButton[tipo="primario"]:hover   {{ background: {t['ACENTO_OSCURO']}; border-color: {t['ACENTO_OSCURO']}; }}
QPushButton[tipo="primario"]:pressed {{ background: {t['ACENTO_OSCURO']}; }}
QPushButton[tipo="primario"]:focus   {{ border: 2px solid {t['SOBRE_ACENTO']}; padding: 0 14px; }}
QPushButton[tipo="primario"]:disabled {{ background: {t['APAGADO_FONDO']}; color: {t['APAGADO']}; border: 1px solid {t['LINEA']}; }}
QPushButton[tipo="callado"] {{ background: transparent; color: {t['ACENTO']}; border: 1px solid transparent; font-weight: 400; }}
QPushButton[tipo="callado"]:hover   {{ background: {t['ACENTO_SUAVE']}; }}
QPushButton[tipo="callado"]:pressed {{ background: {t['ACENTO_BORDE']}; }}
QPushButton[tipo="callado"]:disabled {{ background: transparent; color: {t['APAGADO']}; border: 1px solid transparent; }}
QPushButton[tipo="peligro"] {{ color: {t['PELIGRO']}; border: 1px solid {t['PELIGRO_BORDE']}; background: {t['SUPERFICIE']}; }}
QPushButton[tipo="peligro"]:hover {{ background: {t['PELIGRO_FONDO']}; }}
QPushButton[tipo="lateral"] {{
  background: transparent; color: {t['TINTA']}; border: 1px solid transparent; border-radius: 4px;
  min-height: 30px; padding: 0 10px; text-align: left; font-weight: 400;
}}
QPushButton[tipo="lateral"]:hover   {{ background: {t['GRIS_FONDO']}; }}
QPushButton[tipo="lateral"]:checked {{ background: {t['ACENTO_SUAVE']}; border: 1px solid {t['ACENTO_BORDE']}; }}

QLineEdit, QSpinBox {{
  background: {t['SUPERFICIE']}; color: {t['TINTA']};
  border: 1px solid {t['BORDE']}; border-radius: 4px; padding: 0 11px; min-height: 32px;
  selection-background-color: {t['ACENTO']}; selection-color: {t['SOBRE_ACENTO']};
}}
QLineEdit:focus, QSpinBox:focus {{ border: 2px solid {t['ACENTO']}; padding: 0 10px; }}
QLineEdit:disabled, QSpinBox:disabled {{ background: {t['APAGADO_FONDO']}; color: {t['APAGADO']}; border-color: {t['LINEA']}; }}
QSpinBox {{ padding-right: 24px; min-width: 56px; }}
QSpinBox::up-button, QSpinBox::down-button {{ subcontrol-origin: padding; width: 20px; border: none; background: transparent; }}
QSpinBox::up-button   {{ subcontrol-position: top right; margin-top: 3px; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; margin-bottom: 3px; }}
QSpinBox::up-arrow   {{ image: url("{RUTA}/flecha-arriba-{TEMA}.png"); width: 10px; height: 10px; }}
QSpinBox::down-arrow {{ image: url("{RUTA}/flecha-abajo-{TEMA}.png");  width: 10px; height: 10px; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: {t['GRIS_FONDO']}; width: 12px; margin: 0; border: none; }}
QScrollBar::handle:vertical {{ background: {t['LINEA']}; border-radius: 4px; min-height: 28px; margin: 2px; }}
QScrollBar::handle:vertical:hover {{ background: {t['APAGADO']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; width: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QToolTip {{ background: {t['SUPERFICIE']}; color: {t['TINTA']}; border: 1px solid {t['BORDE']}; }}
"""


def paleta():
    """Devuelve una QPalette con los colores del tema (lo que no cubre la hoja: dialogos nativos, tooltips...)."""
    from PySide6.QtGui import QColor, QPalette
    t = T
    p = QPalette()
    R = QPalette.ColorRole
    for rol, clave in ((R.Window, "PAPEL"), (R.WindowText, "TINTA"), (R.Base, "SUPERFICIE"),
                       (R.AlternateBase, "GRIS_FONDO"), (R.Text, "TINTA"), (R.Button, "SUPERFICIE"),
                       (R.ButtonText, "TINTA"), (R.Highlight, "ACENTO"), (R.HighlightedText, "SOBRE_ACENTO"),
                       (R.PlaceholderText, "TINTA3"), (R.ToolTipBase, "SUPERFICIE"), (R.ToolTipText, "TINTA"),
                       (R.Link, "ACENTO")):
        p.setColor(rol, QColor(t[clave]))
    return p
