"""Punto de entrada común de los procesos hijos del banco (temporal, ver `banco/LEEME.md`).

Uso: python entrada.py <módulo> [argumentos...]

Importa el módulo (que se queda en `__pycache__`, como el código de una
instalación) y, si tiene `main()`, lo llama. Existe para que lo único que se
compile en cada arranque sea esto, que es una línea, y no el script grande: así
un candidato pequeño no sale favorecido por compilar menos.
"""
import importlib
import sys

sys.argv = sys.argv[1:]
_modulo = importlib.import_module(sys.argv[0])
if hasattr(_modulo, "main"):
    _modulo.main()
