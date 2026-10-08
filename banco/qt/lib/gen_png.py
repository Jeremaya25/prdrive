#!/usr/bin/env python3
"""Pinta con Qt (offscreen) las flechas del spinbox como PNG (1x y @2x) para la hoja QSS.

Es del banco de la interfaz (temporal, ver `banco/LEEME.md`). Ya esta hecho (`app/style/*.png`).
Uso: python gen_png.py <carpeta con PySide6/ y shiboken6/>
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__)); APP = os.path.join(os.path.dirname(HERE), "app")
sys.path.insert(0, APP); sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
import tokens, widgets, estilo
app = QGuiApplication([])
for tema, tk in (("claro", tokens.CLARO), ("oscuro", tokens.OSCURO)):
    for nombre, glifo in (("arriba", "arriba"), ("abajo", "abajo")):
        for esc, suf in ((1, ""), (2, "@2x")):
            lado = 10 * esc
            im = QImage(lado, lado, QImage.Format.Format_ARGB32_Premultiplied); im.fill(0)
            p = QPainter(im)
            widgets.pintar_glifo(p, glifo, QRectF(-0.8 * esc, -0.8 * esc, 11.6 * esc, 11.6 * esc), QColor(tk["TINTA2"]), 1.8)
            p.end()
            im.save(os.path.join(APP, "style", f"flecha-{nombre}-{tema}{suf}.png"))
print("ok")
