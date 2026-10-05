#!/usr/bin/env python3
"""PostToolUse (Edit|Write): comprueba lo que se acaba de tocar.

- Un `.py` se compila (sin escribir `__pycache__`): un error de sintaxis se ve
  al momento, no cuando falla un test lejano.
- AGENTS.md, un doc de `docs/agents/reference/` o una regla de `.claude/rules/`
  lanzan `tests/test_reglas_claude.py`, que vigila que docs, reglas y tabla
  sigan en sintonía.

Sale con 2 y el motivo por stderr cuando algo falla, para que Claude lo vea.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCS = re.compile(r"(^|/)(AGENTS\.md|docs/agents/reference/[^/]+\.md|\.claude/rules/[^/]+\.md)$")


def main() -> int:
    ruta = (json.load(sys.stdin).get("tool_input") or {}).get("file_path") or ""
    if not ruta:
        return 0
    p = Path(ruta).resolve()
    try:
        rel = p.relative_to(REPO).as_posix()
    except ValueError:
        return 0
    if p.suffix == ".py" and p.is_file():
        try:
            compile(p.read_text(encoding="utf-8"), rel, "exec")
        except SyntaxError as e:
            print(f"Error de sintaxis en {rel}:{e.lineno}: {e.msg}", file=sys.stderr)
            return 2
    elif DOCS.search(rel):
        r = subprocess.run([sys.executable, str(REPO / "tests" / "test_reglas_claude.py")],
                           cwd=REPO / "tests", capture_output=True, text=True)
        if r.returncode != 0:
            print("tests/test_reglas_claude.py falla tras editar " + rel + ":\n"
                  + (r.stdout + r.stderr)[-1500:], file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
