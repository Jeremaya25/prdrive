---
name: new-area-doc
description: Scaffold a new area doc for prdrive — the English doc in docs/agents/reference/, its row in the AGENTS.md table and its path-scoped rule in .claude/rules/ — and verify them with tests/test_reglas_claude.py. Use when a new module or area needs its own agent doc.
---

# New area doc

An area needs three things kept in sync; `tests/test_reglas_claude.py` fails if any is missing. Ask for (or infer) the **area name** (kebab-case, e.g. `tray`) and the **files it covers** (exact paths or globs, including its tests).

## 1. The doc: `docs/agents/reference/<area>.md`

English. Start with:

```markdown
# <Title> (`file1.py`, `file2.py`)

Formerly AGENTS.md «<old section title>». <One line pointing at neighbouring area docs.>
```

If the area is brand new, keep the «Formerly» line and say there is none. Then short sections of rules and invariants — what the code *decides* and why, not a file tour. Cite specs in `docs/superpowers/{specs,pruebas}/` where they exist. Behaviour belongs here, not in `AGENTS.md`.

## 2. The row in `AGENTS.md`

Add `| \`<area>.md\` | \`file1.py\`, \`file2.py\`: <short purpose> |` to the table under «Area docs», next to related areas. Keep `AGENTS.md` small: no detail beyond that row. Never write a bare `@path` there (it is expanded at session start); wrap paths in backticks.

## 3. The rule: `.claude/rules/<area>.md`

Exactly this shape (header the YAML can read, patterns quoted, one list item per line):

```markdown
---
paths:
  - "ui/example.py"
  - "tests/test_example*.py"
---
Before changing these files, read `docs/agents/reference/<area>.md` (<what it covers>). If you already read it this session, skip it.
```

- Every pattern must match at least one existing file (a dead pattern fails the test).
- The body must name `docs/agents/reference/<area>.md` and stay ≤ 800 characters.
- A module already covered by another rule is fine to repeat only if it truly belongs to both areas.

## 4. Verify

```bash
python tests/test_reglas_claude.py
```

It checks: every doc has a rule and vice versa, headers parse, patterns match files, every project module (`*.py`, `common/`, `ui/`, `install/`) is covered by some rule, `AGENTS.md` lists every doc, and no bare `@path` exists. Fix and rerun until it passes; the PostToolUse hook runs it automatically after edits to these files.
