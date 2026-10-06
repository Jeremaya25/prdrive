---
name: real-machine-tests
description: Use when something in prdrive must be checked on a real Windows or Linux machine instead of with fakes - a row of docs/superpowers/pruebas/*pendiente-en-real.md, filesystems (NTFS, exFAT, FAT32, ext4), mounting or ejecting a drive, VeraCrypt, network folders, OS notifications, ctypes calls into the OS - or when asked to run, add or record such a test in the cloud (GitHub Actions).
---

# Real-machine tests in the cloud

Checklist rows that need an operating system, not a person, run on throwaway GitHub Actions VMs (admin/root) from `tests/maquina/`, workflow `.github/workflows/maquina-real.yml`. The unit suite covers the logic with fakes; the cloud checks only the **OS boundary**: real filesystems on virtual disks, real drivers, real device events.

## 1. Find (cheap)

- `ls tests/maquina/`: files are `fNN_<topic>_<linux|windows>.py`; `python tests/maquina/correr.py --lista` gives one line per row.
- One row's text: `grep -n '^| F14 ' docs/superpowers/pruebas/2026-09-25-equipo-pendiente-en-real.md`. Never read that file, specs or old results whole.

## 2. Run

The cloud runs what is pushed: commit and push first.

| Situation | Trigger |
|---|---|
| `maquina-real.yml` is on `main` | `mcp__github__actions_run_trigger` `method: run_workflow`, `workflow_id: maquina-real.yml`, `ref: <branch>`, `inputs: {"pruebas": "F14 F9"}` |
| Not on `main`, or you changed a test | A push to a non-`main` branch touching `tests/maquina/**` runs `todas` |
| Open PR touching the code under test | Runs `todas` by itself |

Run id: `mcp__github__actions_list` `method: list_workflow_runs`, `resource_id: maquina-real.yml`, `workflow_runs_filter: {branch, event}`, `perPage: 1`; its `head_sha` must be your commit.

Wait without polling (Linux ~1 min, Windows 3-15 min): Bash `sleep 300` with `run_in_background: true`, do other work, check once when it fires.

## 3. Read (cheapest first)

1. `list_workflow_jobs` (run id): conclusion and id per OS.
2. Per job: `mcp__github__get_job_logs` `job_id`, `return_content: true`, `tail_lines: 45` (~20 cleanup lines follow the results). Keep only `RESULTADO` lines:
   - `RESULTADO F14 W ok 30/30 · <notes>`
   - `RESULTADO F9 L parcial 13/13 · sin exfat: <why>` (some case could not run)
   - `RESULTADO F15 W fallo 3/5 · <first failing check>`
   - `RESULTADO F18 W saltada · <why the VM could not>`
3. Only for a `fallo`: `tail_lines: 200` on that job for its `FALLO` block.

## 4. Record

- One row per result in `docs/superpowers/pruebas/maquina-real-resultados.md`: `| F14 | W | <date> | [run](<html_url>) | ok 30/30 | <notes> |`.
- `ok`: mark the checklist row and keep it (a virtual disk is not a USB stick): `sed -i 's/^| F14 | /| F14 · nube: ok | /' docs/superpowers/pruebas/2026-09-25-equipo-pendiente-en-real.md`.
- `fallo`: a bug. Fix code or test, push, rerun. `parcial`/`saltada`: not a pass; leave the row, the reason goes in the results row.
- When reporting, say the cloud `ok` covers the OS boundary; agent behaviour in the row (log lines, timings) is the unit suite's.

## 5. Add a test for a row

Copy a `tests/maquina/fNN_*.py` (≈40 lines): `CODIGO`, `SISTEMA` (`"W"`/`"L"`), `QUE` (one line), `probar(p)`. Checks `p.ver(label, got, want)`; findings `p.nota(text)`; VM cannot do it: `raise comun.Saltada(why)`; several cases (filesystems): `comun.por_cada(p, cases, fn)`, which gives `parcial`. Helpers in `comun.py`: `volumen_linux(tipo)`, `volumen_windows(tipo, letra)`, `bandeja_windows()`, `apt()`, `diskpart()`, `ejecutar()`, `avisos(motor)`, `quieto(motor)`.

VM limits seen so far: the Windows VM has no interactive desktop, so windows get no `WM_DEVICECHANGE` (check for it and `Saltada`, as F15 does); let `volumen_windows()` pick the letter (a just-freed one fails); the Linux kernel loads exFAT from `linux-modules-extra` (`volumen_linux` does it).

Test the boundary only: never deploy a device, fetch rclone or run the whole agent. Before pushing: `python -m py_compile tests/maquina/*.py`; a Linux row without FAT/exFAT runs here as root: `python tests/maquina/correr.py F12 --de-verdad`.

## Common mistakes

| Mistake | Instead |
|---|---|
| Reading the whole checklist, spec or old results | `ls tests/maquina/`, grep one row |
| An end-to-end harness (device, rclone, agent) | One `fNN` module against the OS |
| Polling, or reading whole logs | One timer, `tail_lines: 45`, `RESULTADO` lines |
| `gh` CLI or raw GitHub API | `mcp__github__*` tools |
| Deleting the row after a cloud `ok` | Mark `· nube: ok`, keep it |
