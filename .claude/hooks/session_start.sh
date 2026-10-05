#!/bin/bash
# SessionStart: prdrive es Python stdlib puro (3.11+, `tomllib`): no hay nada que
# instalar. Solo se avisa si el intérprete no sirve; Claude lo recibe como contexto.
set -u
if ! python3 -c 'import sys, tomllib; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
  echo "AVISO: prdrive necesita Python 3.11+ (tomllib); python3 no lo cumple: $(python3 --version 2>&1)"
  exit 0
fi
echo "prdrive: Python $(python3 -c 'import platform; print(platform.python_version())') OK. Verificación: python tests/run_all.py (sin linter ni CI local)."
