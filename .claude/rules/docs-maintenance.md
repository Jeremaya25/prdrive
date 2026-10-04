---
paths:
  - "AGENTS.md"
  - "README.md"
  - "docs/agents/reference/*.md"
  - "docs/guia/*.md"
---
Documentation rules for this repo:
- `AGENTS.md` loads every session, so keep it small: area detail goes in `docs/agents/reference/<area>.md`. A new area doc also needs a row in the `AGENTS.md` table and its own `.claude/rules/<area>.md`; `tests/test_reglas_claude.py` checks both.
- Never write a bare `@path` in `AGENTS.md`: `@` imports are expanded at session start. Wrap paths in backticks.
- Area docs are English: they name the files they cover at the top and carry a «Formerly» line with the old `AGENTS.md` section titles. `README.md` and `docs/guia/` are Spanish and written for the user: no internals in the README.
