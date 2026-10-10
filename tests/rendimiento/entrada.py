"""Punto de entrada común de los procesos hijos de la comprobación de tiempos.

Uso: python entrada.py <módulo> [argumentos...]

Importa el módulo (que se queda en `__pycache__`, como el código de una
instalación) y, si tiene `main()`, lo llama. Existe para que lo único que se
compile en cada arranque sea esto, que es una línea, y no el script grande.
"""
import sys

sys.argv = sys.argv[1:]
_modulo = __import__(sys.argv[0])
if hasattr(_modulo, "main"):
    _modulo.main()
