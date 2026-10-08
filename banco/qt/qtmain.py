#!/usr/bin/env python3
"""Lanzador fino del candidato Qt: el código vive en `app/bench_app.py`, que sí se cachea como .pyc.

Es del banco de la interfaz (temporal, ver `banco/LEEME.md`); lo lanza `ronda.py`.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))
import bench_app  # noqa: E402

rc = bench_app.main()
if os.environ.get("BENCH_SALIDA") == "rapida":      # sin desmontar nada: para comparar con la salida normal
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)
sys.exit(rc)
