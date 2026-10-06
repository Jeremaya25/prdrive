---
name: real-machine-tests
description: Use when something in prdrive must be checked on a real Windows or Linux machine instead of with fakes - a row of docs/superpowers/pruebas/*pendiente-en-real.md, filesystems (NTFS, exFAT, FAT32, ext4), mounting or ejecting a drive, VeraCrypt, network folders, OS notifications, ctypes calls into the OS - or when asked to run, add or record such a test in the cloud (GitHub Actions).
---

# Real-machine tests in the cloud

Checklist rows that need an operating system (not a person) run on throwaway GitHub Actions VMs, as admin/root, from `tests/maquina/` (workflow `.github/workflows/maquina-real.yml`). The unit suite already covers the logic with fakes; the cloud only checks the **OS boundary**: real filesystems on virtual disks, real drivers, real device events.

## 1. Find the tests (cheap)

- Index: `ls tests/maquina/` (files are `fNN_<topic>_<linux|windows>.py`), or `python tests/maquina/correr.py --lista` for one line per row.
- One row's text, if you need it: `grep -n '^| F14 ' docs/superpowers/pruebas/2026-09-25-equipo-pendiente-en-real.md`. Do not read that file, the specs or old results whole.

## 2. Run

The cloud runs what is pushed: commit and push your changes first.

| Situation | Trigger |
|---|---|
| `maquina-real.yml` is on `main` | `mcp__github__actions_run_trigger` `method: run_workflow`, `workflow_id: maquina-real.yml`, `ref: <branch>`, `inputs: {"pruebas": "F14 F9"}` |
| Not on `main` yet, or you changed a test | Push to a non-`main` branch that touches `tests/maquina/**`: runs `todas` |
| Open PR touching the code under test | Runs `todas` by itself |

Run id: `mcp__github__actions_list` `method: list_workflow_runs`, `resource_id: maquina-real.yml`, `workflow_runs_filter: {branch, event}` (`push` or `workflow_dispatch`), `perPage: 1`; check its `head_sha` is your commit.

Wait without polling: Linux takes 2-4 min, Windows 5-15 min (VeraCrypt installs). Start `sleep 420` with Bash `run_in_background: true`, do other work, check once when it fires.

## 3. Read results (cheapest first)

1. `list_workflow_jobs` (run id): one conclusion per OS, and the job ids.
2. Per job: `mcp__github__get_job_logs` `job_id`, `return_content: true`, `tail_lines: 45` (about 20 cleanup lines follow the results). Keep only the lines containing `RESULTADO`:
   - `RESULTADO F14 W ok 12/12 · <notes>`
   - `RESULTADO F9 L parcial 13/13 · sin exfat: <why> · <notes>` (some case could not run)
   - `RESULTADO F15 W fallo 3/5 · <first failing check>`
   - `RESULTADO F18 W saltada · <why it could not run here>`
3. Only for a `fallo`: the same call with `tail_lines: 200` on that job, to see its `FALLO` block.

## 4. Record

- Append one row per result to `docs/superpowers/pruebas/maquina-real-resultados.md`: `| F14 | W | <date> | [run](<html_url>) | ok 12/12 | <notes> |`.
- `ok` → mark the checklist row, keep it (a virtual disk is not a USB stick): `sed -i 's/^| F14 | /| F14 · nube: ok | /' docs/superpowers/pruebas/2026-09-25-equipo-pendiente-en-real.md`.
- `fallo` → it is a bug: fix the code or the test, push, rerun. `parcial` and `saltada` are not a pass: leave the row alone; the reason goes in the results row.
- A cloud `ok` covers the OS boundary only; the rest of the row (agent log lines, timings) is the unit suite's. Say so when you report.

## 5. Add a test for a new row

Copy an existing `tests/maquina/fNN_*.py` (≈40 lines): `CODIGO = "F20"`, `SISTEMA = "W"` or `"L"`, `QUE = "<one line>"`, `def probar(p)`. Use `p.ver(label, got, want)` for checks, `p.nota(text)` for findings, `raise comun.Saltada(reason)` when the VM cannot do it. Helpers in `comun.py`: `volumen_linux(tipo)`, `volumen_windows(tipo, letra)`, `bandeja_windows()`, `apt()`, `diskpart()`, `ejecutar()`, `avisos(motor)`, `quieto(motor)`, `arbol()`.

Test the boundary only: the engine or module against the real OS. Do not deploy a device, download rclone or run the whole agent.

Before pushing: `python -m py_compile tests/maquina/*.py`. Linux tests that need no FAT/exFAT can run in this container as root: `python tests/maquina/correr.py F12 --de-verdad`.

## Common mistakes

| Mistake | Instead |
|---|---|
| Reading the whole checklist, spec or old results | `--lista` and grep one row |
| Building an end-to-end harness (device, rclone, agent) | One `fNN` module against the OS |
| Polling the run, or reading full logs | One timer; `tail_lines: 45`; only `RESULTADO` lines |
| Expecting the cloud to run unpushed edits | Commit and push first |
| `gh` CLI or raw GitHub API | The `mcp__github__*` tools |
| Deleting a checklist row after a cloud `ok` | Mark it `· nube: ok` and keep it |
