#!/usr/bin/env python3
"""PreToolUse (Bash): frena las ejecuciones de `sync.py` que AGENTS.md prohíbe.

- `--resync` pide confirmación: reescribe la línea base de bisync.
- Una pasada sin `--dry-run` que alcance una pareja `*-mirror` se deniega: el
  espejo borra en el lado lejano y la simulación es obligatoria antes. Si hay un
  `sync_config.toml`, se miran las parejas nombradas (o todas, si no se nombra
  ninguna); sin config, se deniega cualquier pasada real que diga `mirror`.
- `--list`, `--doctor`, `--dry-run` y `-h` pasan siempre.
"""

import json
import re
import shlex
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOLO_LECTURA = {"--dry-run", "--list", "--doctor", "-h", "--help"}


def decidir(orden: str):
    """Devuelve `(decision, motivo)` o `None` si la orden no es de las vigiladas."""
    try:
        tokens = shlex.split(orden)
    except ValueError:
        return None
    for i, t in enumerate(tokens):
        if Path(t).name != "sync.py":
            continue
        args = []
        for a in tokens[i + 1:]:
            if re.fullmatch(r"[;&|]+|&&|\|\|", a):
                break
            args.append(a)
        if "--resync" in args:
            return "ask", "--resync reescribe la línea base de bisync (AGENTS.md: Safety invariants)."
        if SOLO_LECTURA & set(args):
            return None
        nombres = [a for a in args if not a.startswith("-")]
        cfg = REPO / "sync_config.toml"
        if cfg.is_file():
            try:
                parejas = tomllib.loads(cfg.read_text(encoding="utf-8")).get("pair", [])
            except (tomllib.TOMLDecodeError, OSError):
                parejas = []
            espejos = {p.get("name") for p in parejas if str(p.get("mode", "")).endswith("-mirror")}
            tocadas = espejos & set(nombres) if nombres else espejos
            if tocadas:
                return "deny", ("Pareja *-mirror sin --dry-run: " + ", ".join(sorted(tocadas))
                                + ". Simula primero con `python sync.py --dry-run`.")
        elif "mirror" in orden:
            return "deny", "Pareja *-mirror sin --dry-run: simula primero con `python sync.py --dry-run`."
    return None


def main() -> int:
    orden = (json.load(sys.stdin).get("tool_input") or {}).get("command") or ""
    r = decidir(orden)
    if r:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": r[0],
            "permissionDecisionReason": r[1]}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
