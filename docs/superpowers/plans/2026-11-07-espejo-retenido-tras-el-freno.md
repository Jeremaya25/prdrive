# Espejo retenido tras el freno: plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un `*-mirror` que se para en su `--max-delete` queda retenido: ningún camino desatendido lo vuelve a lanzar hasta que una persona apruebe una pasada y una acabe bien.

**Architecture:** `sync.py` apunta la retención en `state/last_run.json` (clave `retenida`) al acabar una pasada frenada y, al empezar, salta con «Saltada» un espejo retenido que nadie ha aprobado (`--resume`, `--force` o un «sí» en la terminal). `common/revision.py` es lo único que decide si una pareja está retenida y escribe sus textos; la ventana, la consola, «Reparación», el agente, el servicio y la bandeja los leen de ahí o del parte (`"retenida": true`).

**Tech Stack:** Python 3.11+ solo stdlib, Tk 9 para las ventanas, tests como scripts sueltos con `tests/_harness.py`.

**Spec:** `docs/superpowers/specs/2026-11-06-espejo-retenido-tras-el-freno-design.md` (léela entera antes de empezar; el plan la concreta y cita sus apartados como §1…§8).

## Global Constraints

- Python 3.11+ y solo la biblioteca estándar; nada nuevo que instalar.
- Comentarios, docstrings y todo lo que ve la persona, en español; `docs/agents/` en inglés.
- `import tkinter` solo dentro de funciones; los `tk_*` solo dibujan; en `ui/__init__.py`, `ui/tk.py` y `runsync.py` los módulos de `common` (`revision`, `parte`) se importan dentro de la función que los usa. `sync.py` no importa `ui/`. `revision` no escribe nada.
- Los frenos no cambian: `max-delete` 50 (una cuenta) en los espejos y 25 (%) en bisync. `--force` hace lo mismo que hoy.
- `--resume` solo lo pasa una persona: la ventana tras «Lanzarla», «Reparación» tras confirmar su plan, o quien lo escribe en una terminal. Nunca `runsync.py` (servicio, `--auto`, `--auto --once`), `agente.py`, `penwatch.py` ni el TOML.
- Formatos: `last_run.json` gana una clave que los lectores de antes no miran; el parte lleva `"retenida": true` solo cuando es verdad, y sin ella sale igual byte a byte que hoy.
- Un `last_run.json` ilegible, un log que falta o un `sync.py` anterior nunca impiden sincronizar una pareja que no está retenida.
- Las PR no suben `VERSION`. El título de la PR va en español, para quien usa el dispositivo.
- Tests: scripts con `Checks` (`c(descripción, obtenido, esperado)`, `c.contains(descripción, texto, aguja)`). En este Windows se lanzan desde PowerShell con `$env:TCL_LIBRARY = "C:\no-existe"` en la misma orden, para que ninguna ventana salga encima del trabajo del dueño. Los tests de ventanas (`test_tk_*.py`) imprimen entonces `(saltado)`: o se corren en un escritorio aparte (`CreateDesktopW`), o se dejan al CI, y se dice en la PR.
- Los textos de cada tarea son exactos: se copian tal cual.

## Review Focus

1. **«Saltarla» con otras parejas marcadas en el mismo clic:** las otras se sincronizan en esa misma pasada; solo la retenida vuelve «Saltada» y `sync.py` sale con 0. Test en la tarea 3 (`sync.py`) y en la 5 (`manual_args` conserva los nombres).
2. **Basura en `retenida` (un número, `""`, una lista) o un `last_run.json` ilegible:** nada lanza, ninguna pareja queda retenida por eso y todas se sincronizan. Un texto que no es un sello válido sí retiene, sin fecha. Tests en las tareas 1 y 2.
3. **El log del freno ya no está (lo podó `podar_logs()`) o pesa más de 4 MiB:** la retención sigue y el texto sale sin cifras, nunca con una cuenta parcial. Test en la tarea 2.
4. **Varias retenidas en una ejecución con terminal:** una sola pregunta para todas. Un «no» salta todas las retenidas y deja pasar las demás. Test en la tarea 3.
5. **El motivo de una saltada cambia (resync ↔ retenida), o llega un parte de un `sync.py` anterior sin la clave:** el agente vuelve a avisar con el motivo nuevo, y el parte antiguo conserva el texto del resync. Test en la tarea 4.

---

### Paso previo: dejar la spec y el plan en el repositorio

- [ ] **Commit de los dos documentos**

```bash
git add docs/superpowers/specs/2026-11-06-espejo-retenido-tras-el-freno-design.md docs/superpowers/plans/2026-11-07-espejo-retenido-tras-el-freno.md
git commit -m "Espejo retenido tras el freno: spec y plan (D2)"
```

---

### Task 1: `results`, la clave `retenida`

**Files:**
- Modify: `common/results.py`
- Test: `tests/test_results.py`

**Interfaces:**
- Consumes: nada nuevo.
- Produces:
  - `results.apuntar(nombre: str, codigo: int, log: Path | None, *, freno: bool = False) -> None`: escribe también `retenida`.
    - Con `codigo == 0`, `None`, aunque llegue `freno`.
    - Con `freno`, el mismo sello que `cuando`.
    - Si no, el valor `retenida` de la entrada anterior, o `None` si no lo tenía o no había entrada.
  - `results.Apunte(NamedTuple)`, con los campos `cuando: str`, `codigo: int`, `log: Path | None`, `retenida: str | None` y `sabida: bool`.
    - `log`: en `logs/`, si sigue ahí; se resuelve igual que en `fallos_de()`, con un `_log(dato) -> Path | None` común a los dos.
    - `retenida`: el valor si es un `str` no vacío; si no, `None`.
    - `sabida`: `"retenida" in dato`.
  - `results.apuntes(nombres: Iterable[str]) -> dict[str, Apunte]`: una sola lectura de `last_run.json`.
    - No salen las parejas que no constan, las que no son un dict ni las que tienen un `codigo` que no es un número.
    - Con el fichero ilegible, `{}`.
  - `results.fijar_retenciones(valores: Mapping[str, str | None]) -> None`: escribe el valor solo en las entradas que existen y no tienen la clave.
    - Nunca crea entradas.
    - Escribe una vez, y solo si ha cambiado algo.
    - Nunca lanza.

- [ ] **Step 1: Escribir el test que falla** (al final de `tests/test_results.py`, antes de `sys.exit(c.report())`; `import json` arriba)

```python
# ---- La retención de un espejo parado en su freno (D2) -------------------------------------
real_stamp = store.stamp
with sandbox():
    log = model.LOG_DIR / "fotos_20261105_182000.log"
    log.write_text("x\n", encoding="utf-8")
    try:
        store.stamp = lambda: "2026-11-05 18:20:00"
        results.apuntar("fotos", 7, log, freno=True)
        a = results.apuntes(["fotos"])["fotos"]
        c("el freno de un espejo la retiene desde esa pasada",
          (a.retenida, a.sabida, a.codigo, a.log), ("2026-11-05 18:20:00", True, 7, log))
        store.stamp = lambda: "2026-11-05 19:00:00"
        results.apuntar("fotos", 1, log)
        c("  otro fallo no la suelta", results.apuntes(["fotos"])["fotos"].retenida,
          "2026-11-05 18:20:00")
        store.stamp = lambda: "2026-11-06 09:00:00"
        results.apuntar("fotos", 7, log, freno=True)
        c("  otra parada la renueva", results.apuntes(["fotos"])["fotos"].retenida,
          "2026-11-06 09:00:00")
        results.apuntar("fotos", 0, None)
        c("  una pasada buena la suelta", results.apuntes(["fotos"])["fotos"].retenida, None)
        crudo = json.loads(results.ruta_estado().read_text(encoding="utf-8"))["parejas"]
        c("  y la clave queda escrita, `null`", ("retenida" in crudo["fotos"],
                                                 crudo["fotos"]["retenida"]), (True, None))
        results.apuntar("nueva", 1, None)
        c("una pareja sin nada antes que falla por otra cosa no queda retenida",
          results.apuntes(["nueva"])["nueva"][3:], (None, True))
        results.apuntar("cero", 0, None, freno=True)
        c("  con código 0 manda el código", results.apuntes(["cero"])["cero"].retenida, None)
    finally:
        store.stamp = real_stamp

with sandbox():
    # Lo que escribió un sync.py de antes (sin la clave) y basura en ella.
    store.write_json(results.ruta_estado(), {"parejas": {
        "fotos": {"cuando": "2026-11-01 10:00:00", "codigo": 7, "log": None, "buena": None},
        "raro1": {"cuando": "x", "codigo": 7, "retenida": 5},
        "raro2": {"cuando": "x", "codigo": 7, "retenida": ""},
        "raro3": {"cuando": "x", "codigo": 7, "retenida": ["a"]}}})
    a = results.apuntes(["fotos", "raro1", "raro2", "raro3", "nadie"])
    c("sin la clave, no se sabe", (a["fotos"].sabida, a["fotos"].retenida), (False, None))
    c("  lo que no es un texto con algo no retiene",
      [a[n].retenida for n in ("raro1", "raro2", "raro3")], [None, None, None])
    c("  y lo que no consta no sale", "nadie" in a, False)
    results.fijar_retenciones({"fotos": "2026-11-01 10:00:00", "nadie": None})
    datos = json.loads(results.ruta_estado().read_text(encoding="utf-8"))["parejas"]
    c("fijar apunta la decisión donde falta", datos["fotos"]["retenida"], "2026-11-01 10:00:00")
    c("  sin crear parejas que no constan", "nadie" in datos, False)
    results.fijar_retenciones({"fotos": None})
    c("  y no pisa lo que ya está",
      results.apuntes(["fotos"])["fotos"].retenida, "2026-11-01 10:00:00")
    c("fallos_de() no cambia con la clave nueva",
      [f.pareja for f in results.fallos_de(["fotos"])], ["fotos"])

with sandbox():
    results.ruta_estado().write_text("{roto", encoding="utf-8")
    c("un registro ilegible no da retenciones", results.apuntes(["fotos"]), {})
    results.fijar_retenciones({"fotos": "2026-11-01 10:00:00"})
    c("  y fijar no lanza ni escribe nada", results.ruta_estado().read_text(encoding="utf-8"),
      "{roto")
```

- [ ] **Step 2: Ver que falla**

Run: `$env:TCL_LIBRARY = "C:\no-existe"; python tests/test_results.py`
Expected: `TypeError: apuntar() got an unexpected keyword argument 'freno'`.

- [ ] **Step 3: Implementar `apuntar(…, freno=)`, `Apunte`, `apuntes()` y `fijar_retenciones()` en `common/results.py`**

En el docstring del módulo, un párrafo sobre `retenida` que remita a la spec (§1, §4). `fallos_de()` pasa a usar `_log()`.

- [ ] **Step 4: Ver que pasa**

Run: `$env:TCL_LIBRARY = "C:\no-existe"; python tests/test_results.py`
Expected: `--- última pasada de cada pareja (common/results.py): N comprobaciones OK` y código 0.

- [ ] **Step 5: Commit**

```bash
git add common/results.py tests/test_results.py
git commit -m "Retención: last_run.json apunta si un espejo se paró en su freno"
```

---

### Task 2: `revision`, la decisión y sus textos

**Files:**
- Modify: `common/revision.py`
- Test: `tests/test_revision.py`

**Interfaces:**
- Consumes: `results.apuntes()` / `results.Apunte` (tarea 1).
- Produces:
  - `@dataclass(frozen=True) class Retencion`, con `pareja: str`, `desde: str` (el sello) y `log: Path | None`.
  - `revision.puede_retenerse(pair: Pair) -> bool`: `frenos.tiene_freno(pair) and not pair.is_bisync`.
  - `revision.retenciones(pairs: Iterable[Pair]) -> dict[str, Retencion]`: una sola lectura de `results.apuntes()`, y nunca lanza (ante cualquier excepción, `{}`).
    - Solo mira las parejas que `puede_retenerse()`.
    - Con `sabida`, la pareja está retenida si tiene `retenida`, desde ese valor.
    - Sin `sabida` (§4), está retenida si `codigo != 0`, hay `log` y `_veredicto_de(log, pair).freno` es de tipo `ESPEJO` (un `OSError` cuenta como «no»). Entonces lo está desde `cuando`.
  - `revision.retencion(pair: Pair) -> Retencion | None`: `retenciones([pair]).get(pair.name)`.
  - `revision.linea_retenida(retencion: Retencion) -> str`: lo que imprime `sync.py` al saltarla.
  - `revision.texto_retencion(pair: Pair, retencion: Retencion) -> str`: el texto de §6.
  - `revision.frase_retenida(retencion: Retencion) -> str`: lo que se añade al `detalle` del hallazgo.
  - Hallazgos de una pareja retenida:
    - `freno`: `dato == (log, freno, retencion)`.
    - `fallo`: `dato == (log, causa, retencion)`.
    - El `detalle` acaba con `" " + frase_retenida(retencion)`.
    - Una pareja no retenida conserva su `dato` de dos elementos.

**Textos exactos.** La fecha sale de un `_cuando(sello) -> str` privado:
- `"el 05/11 a las 18:20"`, o `"el 05/11/2025 a las 18:20"` si es de otro año (la regla de `_dia()`);
- `""` si `desde` no es un sello de `store.FORMATO`.

En lo que sigue, `{cuando}` es `" " + _cuando(...)` o nada, y `{destino}` es `frenos.nombre_lado(pair.mode.dest)`.

- `linea_retenida`, con fecha:

  ```text
  Saltada: está retenida desde el 05/11 a las 18:20 porque se paró en el freno de borrados. Lánzala desde la ventana (te dirá cuánto puede borrar) o mira «Reparación».
  ```

  Sin fecha:

  ```text
  Saltada: está retenida porque se paró en el freno de borrados. Lánzala desde la ventana (te dirá cuánto puede borrar) o mira «Reparación».
  ```

- `frase_retenida`, con fecha y sin ella:

  ```text
  Retenida desde el 05/11 a las 18:20: ni el servicio ni el agente la lanzan solos hasta que una pasada acabe bien.
  ```

  ```text
  Retenida: ni el servicio ni el agente la lanzan solos hasta que una pasada acabe bien.
  ```

- `texto_retencion` son tres trozos seguidos, separados por un espacio:
  1. `«{pair.name}» se paró en el freno de borrados{cuando}{cifras}.` Las cifras salen de `_veredicto_de(retencion.log, pair)` solo si su freno es `ESPEJO`; si no, o sin log, o con `OSError`, no hay cifras. Con `b = borrados` y `q = pendientes`:
     - con `b` y `q`: `: borró {b} ficheros en {destino} y le quedaban {q}`;
     - solo `b`: `: borró {b} ficheros en {destino}`;
     - solo `q`: `: le quedaban {q} ficheros por borrar en {destino}`;
     - ninguna: nada.
  2. Según `tope = orden.max_delete_efectivo(pair)`:
     - `tope >= 0`: `Si la lanzas, puede borrar hasta {tope} más.`;
     - `tope < 0`: `Si la lanzas, ya no tiene tope de borrados: borrará todo lo que sobre.`;
     - `None`: `Si la lanzas, puede volver a borrar.`
  3. Siempre:

     ```text
     Si esos borrados son lo que querías, «Forzar sincronización…» en «Reparación» los hace todos de una vez; si no los esperabas, mira antes «Ver qué se borraría».
     ```

- [ ] **Step 1: Escribir el test que falla** (al final de `tests/test_revision.py`; importa `from _logs_frenos import ESPEJO_UP, ESPEJO_DOWN` y `from _logs_errores import RED_RECHAZADA`, y `results`, `frenos`, `store` de `common`)

```python
# ---- Espejos retenidos tras su freno (D2) ----------------------------------------------------
AÑO = datetime.now().year
SELLO = f"{AÑO}-11-05 18:20:00"
SUBIDA = {"name": "fotos", "mode": "up-mirror", "local": "sync-data/fotos", "remote_path": "/R/fotos"}
BAJADA = dict(SUBIDA, mode="down-mirror")
FIN = ("Si esos borrados son lo que querías, «Forzar sincronización…» en «Reparación» los hace "
       "todos de una vez; si no los esperabas, mira antes «Ver qué se borraría».")


def una(raw):
    """Devuelve `(config, pareja)` con solo esa pareja."""
    cfg = model.parse_config({"defaults": {"remote": "nas"}, "pair": [raw]})
    return cfg, cfg.pairs[0]


def retener(nombre, texto, *, freno=True, rc=7, sello=SELLO):
    """Apunta una pasada fallida de `nombre` con ese log; devuelve el log."""
    log = model.LOG_DIR / f"{nombre}_20261105_182000.log"
    log.write_text(texto, encoding="utf-8")
    real, store.stamp = store.stamp, (lambda: sello)
    try:
        results.apuntar(nombre, rc, log, freno=freno)
    finally:
        store.stamp = real
    return log


with sandbox():
    cfg, p = una(SUBIDA)
    log = retener("fotos", ESPEJO_UP)
    r = revision.retencion(p)
    c("un espejo con sello está retenido", r, revision.Retencion("fotos", SELLO, log))
    c("el texto, con las cifras del log y el tope de la pareja", revision.texto_retencion(p, r),
      "«fotos» se paró en el freno de borrados el 05/11 a las 18:20: borró 50 ficheros en el "
      "remoto y le quedaban 5. Si la lanzas, puede borrar hasta 50 más. " + FIN)
    c("la línea de la consola", revision.linea_retenida(r),
      "Saltada: está retenida desde el 05/11 a las 18:20 porque se paró en el freno de borrados. "
      "Lánzala desde la ventana (te dirá cuánto puede borrar) o mira «Reparación».")
    c("  y lleva la palabra que buscan el agente y el servicio",
      "saltada" in revision.linea_retenida(r).lower(), True)
    _, propio = una(dict(SUBIDA, flags={"max-delete": 7}))
    c.contains("el tope es el que recibirá rclone", revision.texto_retencion(propio, r),
               "puede borrar hasta 7 más.")
    _, abajo = una(BAJADA)
    c.contains("hacia abajo borra en el dispositivo",
               revision.texto_retencion(abajo, revision.Retencion("fotos", SELLO,
                                        retener("fotos", ESPEJO_DOWN))),
               "borró 50 ficheros en el dispositivo")
    log.unlink()
    c("sin log, sin cifras (y la retención sigue)",
      (revision.retencion(p) is not None,
       revision.texto_retencion(p, revision.Retencion("fotos", SELLO, None))),
      (True, "«fotos» se paró en el freno de borrados el 05/11 a las 18:20. Si la lanzas, "
             "puede borrar hasta 50 más. " + FIN))
    grande = retener("fotos", "x" * (frenos.TOPE_LECTURA + 1024) + "\n" + ESPEJO_UP)
    c.contains("un log de más de 4 MiB no da una cuenta parcial",
               revision.texto_retencion(p, revision.Retencion("fotos", SELLO, grande)),
               "se paró en el freno de borrados el 05/11 a las 18:20: le quedaban 5 ficheros "
               "por borrar en el remoto.")
    c("un sello que no se entiende retiene igual, sin fecha",
      revision.linea_retenida(revision.Retencion("fotos", "ayer", None)),
      "Saltada: está retenida porque se paró en el freno de borrados. Lánzala desde la "
      "ventana (te dirá cuánto puede borrar) o mira «Reparación».")

with sandbox():
    # Solo los espejos, y solo con sello.
    retener("fotos", ESPEJO_UP)
    for modo in ("bisync", "up", "down"):
        _, otra = una(dict(SUBIDA, mode=modo))
        c(f"una pareja {modo} no arrastra la retención", revision.retencion(otra), None)
    retener("fotos", ESPEJO_UP, rc=0, freno=False)
    c("una pasada buena la suelta", revision.retencion(una(SUBIDA)[1]), None)
    c("sin registro no hay retención", revision.retencion(una(dict(SUBIDA, name="otra"))[1]), None)
    results.ruta_estado().write_text("{roto", encoding="utf-8")
    c("un registro ilegible no retiene ni lanza", revision.retenciones([una(SUBIDA)[1]]), {})

with sandbox():
    # §4: un registro de un sync.py de antes, sin la clave.
    log = model.LOG_DIR / "fotos_20261101_100000.log"
    log.write_text(ESPEJO_UP, encoding="utf-8")
    store.write_json(results.ruta_estado(), {"parejas": {"fotos": {
        "cuando": SELLO, "codigo": 7, "log": log.name, "buena": None}}})
    p = una(SUBIDA)[1]
    revision.olvidar_frenos()
    lecturas, leer_real = [], frenos.leer
    frenos.leer = lambda *a, **k: lecturas.append(a) or leer_real(*a, **k)
    try:
        c("sin la clave se decide por su log", revision.retencion(p),
          revision.Retencion("fotos", SELLO, log))
        revision.retencion(p)
        c("  leyéndolo una vez por proceso", len(lecturas), 1)
    finally:
        frenos.leer = leer_real
    log.write_text(RED_RECHAZADA, encoding="utf-8")
    revision.olvidar_frenos()
    c("  un log que no es el freno no retiene", revision.retencion(p), None)
    log.unlink()
    c("  y sin log, tampoco", revision.retencion(p), None)

with sandbox():
    # El hallazgo dice que está retenida, y `--doctor` también.
    cfg, p = una(SUBIDA)
    p.local_abs.mkdir(parents=True, exist_ok=True)
    retener("fotos", ESPEJO_UP)
    freno = next(h for h in revision.revisar(cfg) if h.clave == "freno")
    c("el freno de una retenida lleva su retención", freno.dato[2],
      revision.Retencion("fotos", SELLO, freno.dato[0]))
    c.contains("  y lo dice", freno.detalle, "Retenida desde el 05/11 a las 18:20: ni el "
               "servicio ni el agente la lanzan solos hasta que una pasada acabe bien.")
    c.contains("  también en --doctor", "\n".join(revision.informe(cfg)), "Retenida desde el 05/11")
    retener("fotos", RED_RECHAZADA, freno=False, rc=1)   # la pasada aprobada falla por la red
    fallo = next(h for h in revision.revisar(cfg) if h.clave == "fallo")
    c("un fallo de una retenida también la lleva",
      (fallo.dato[2].desde, "Retenida desde" in fallo.detalle), (SELLO, True))

with sandbox():
    # Un freno apuntado sin retención (lo que deja un sync.py de antes que ya escribía la clave).
    cfg, p = una(SUBIDA)
    retener("fotos", ESPEJO_UP, freno=False)
    freno = next(h for h in revision.revisar(cfg) if h.clave == "freno")
    c("un freno sin retención conserva su dato de siempre", (len(freno.dato),
      "Retenida" in freno.detalle), (2, False))
```

- [ ] **Step 2: Ver que falla**

Run: `$env:TCL_LIBRARY = "C:\no-existe"; python tests/test_revision.py`
Expected: `AttributeError: module 'common.revision' has no attribute 'retencion'`.

- [ ] **Step 3: Implementar en `common/revision.py`**

Hay que añadir `Retencion`, `puede_retenerse()`, `retenciones()`, `retencion()`, `_cuando()`, `linea_retenida()`, `frase_retenida()` y `texto_retencion()`.

`_fallos()` calcula `retenciones(config.pairs)` una vez, antes del bucle. Le pasa la retención de cada pareja a `_hallazgo_freno(pair, freno, log, racha, retencion=None)` y a la construcción del `fallo`. El docstring de `Hallazgo.dato` dice que lleva el tercer elemento.

- [ ] **Step 4: Ver que pasa**

Run: `$env:TCL_LIBRARY = "C:\no-existe"; python tests/test_revision.py; python tests/test_frenos.py; python tests/test_repair.py`
Expected: los tres acaban en `N comprobaciones OK` y con código 0. Los dos últimos no cambian: el `dato` de dos elementos sigue igual.

- [ ] **Step 5: Commit**

```bash
git add common/revision.py tests/test_revision.py
git commit -m "Retención: revision decide si un espejo está retenido y lo explica"
```

---

### Task 3: `sync.py`, apuntar, preguntar y saltar

**Files:**
- Modify: `sync.py`, `common/parte.py`, `.claude/rules/engine.md` (añade `tests/test_retenida.py` a `paths`)
- Create: `tests/test_retenida.py`
- Test: `tests/test_parte.py`

**Interfaces:**
- Consumes:
  - de la tarea 1, `results.apuntar(…, freno=)` y `results.fijar_retenciones()`;
  - de la tarea 2, `revision.Retencion`, `puede_retenerse()`, `retenciones()`, `linea_retenida()` y `texto_retencion()`.
- Produces:
  - `parte.RETENIDA = "retenida tras el freno"`: cómo se nombra en una línea, y lo usan el agente, el servicio, la ventana y la bandeja.
  - `parte.Parte` gana un último campo, `retenida: bool = False`.
    - `parte.linea()` lo quita del JSON cuando es `False`.
    - `parte.leer()` lo lee como `d.get("retenida") is True`.
  - `parte.Medida.retenida: bool = False`: lo pone `sync.py`, y `acabar()` lo pasa al `Parte`.
  - `sync.RunContext.retenidas: Mapping[str, revision.Retencion] = field(default_factory=dict)`: las retenidas que esta ejecución no lanza.
  - `sync.record_result(ctx, pair, rc, log, reloj=None, final=None, *, freno: bool = False)`: pasa `freno` a `results.apuntar()`.
  - `sync.paro_en_el_freno(pair: Pair, log: Path | None) -> bool`: es `True` cuando se cumple todo esto:
    - `revision.puede_retenerse(pair)`;
    - `log is not None`;
    - `frenos.detectar_en(log, pair)` es de tipo `ESPEJO`.

    Un `OSError` da `False`.
  - `sync.resolver_retenidas(selected: list[Pair], aprobadas: bool) -> dict[str, revision.Retencion]`: devuelve las retenidas que NO se lanzan. Va por orden:
    1. `retenciones = revision.retenciones(selected)`.
    2. `results.fijar_retenciones()` con cada pareja de `selected` que `puede_retenerse()`: `retenciones[n].desde` si está, y si no `None`.
    3. Sin retenidas, devuelve `{}`.
    4. Imprime `Espejos retenidos tras el freno de borrados:` y, por cada una, `  - ` y su `texto_retencion()`.
    5. Con `aprobadas`, imprime `--resume: se lanzarán con su tope de borrados.` y devuelve `{}`.
    6. Si no, pregunta una vez `ask_yes_no("¿Lanzarlas ahora? (una pasada normal, con su tope)")`.
    7. Con «sí», devuelve `{}`. Con «no», imprime `De acuerdo, se saltarán. (Lánzalas desde la ventana, o con --resume.)` y devuelve las retenidas.
  - `parse_args` añade `--resume` (`store_true`), con este help:

    ```text
    Lanza también los espejos retenidos tras su freno de borrados, en una pasada normal (con su tope). Lo pasa una persona: la ventana al decir «Lanzarla», o «Reparación».
    ```

    En el «Uso:» del docstring del módulo va esta línea:

    ```text
    python sync.py fotos --resume  # lanza un espejo retenido tras su freno (una pasada normal)
    ```
  - `main()`: tras `resolve_resync_approval()`, `retenidas = {} if args.dry_run else resolver_retenidas(selected, args.resume or args.force)`, y se pasa a `RunContext(…, retenidas=retenidas)`.
  - `_pasar_pareja()` cambia en dos sitios:
    - **Justo después del bloque de `problema_contencion()`:** si `pair.name in ctx.retenidas`, imprime `[{pair.name}] {revision.linea_retenida(...)}`, pone `medida.retenida = True` y devuelve `SKIPPED`. No apunta nada ni lanza rclone.
    - **Tras `dispose_log()`:** calcula `freno = not ctx.dry_run and rc != 0 and paro_en_el_freno(pair, saved)` y llama a `record_result(…, freno=freno)`.

- [ ] **Step 1: Escribir los tests que fallan**

En `tests/test_parte.py`, antes de `raise SystemExit(c.report())`:

```python
# --- la retención (D2): solo cuando es verdad, y sin cambiar los partes de siempre
c("una saltada de siempre sale igual que antes, byte a byte", parte.linea(parte.Parte("a", -1)),
  parte.MARCA + '{"pareja": "a", "rc": -1, "movio": null, "ordenes": 0, "escrito": 0}')
r = parte.Parte("a", -1, retenida=True)
c.contains("una retenida lo dice", parte.linea(r), '"retenida": true')
c("  y va y vuelve", parte.leer(parte.linea(r)), {"a": r})
c("  sin la palabra «saltada»", "saltada" in parte.linea(r).lower(), False)
c("un parte de un sync.py anterior no está retenido",
  parte.leer(parte.MARCA + '{"pareja": "a", "rc": -1}')["a"].retenida, False)
c("  y lo que no es `true` tampoco",
  parte.leer(parte.MARCA + '{"pareja": "a", "rc": -1, "retenida": "sí"}')["a"].retenida, False)
```

`tests/test_retenida.py` (nuevo). Su docstring lo resume: D2 en `sync.py`, la spec y qué se mira. Copia de `test_forzar.py` el patrón de `correr()`, que sustituye `sync.execute` y escribe el log, y el patrón de `main()`, que sustituye `sync.run_all` y `model.rclone_binary`. Lleva estas comprobaciones, cada una en su `with sandbox():`:

```python
from _logs_frenos import BISYNC_BORRADOS, ESPEJO_UP
from _logs_errores import RED_RECHAZADA
import sync
from common import model, parte, results, revision, store

SUBIDA = {"name": "fotos", "mode": "up-mirror", "local": "sync-data/fotos", "remote_path": "/R/fotos"}
NOTAS = {"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas"}   # bisync
COPIA = {"name": "copia", "mode": "up", "local": "sync-data/copia", "remote_path": "/R/copia"}

# correr(raw, rc=…, texto_log=…, **ctx) -> (rc, salida, órdenes) como en test_forzar.py
# lanzar_main(argv, toml=TOML, *, tty=None) -> (ctx_visto, salida): escribe CONFIG_FILE y
#   RCLONE_CONF ("[nas]\ntype = local\n"), sustituye run_all para quedarse con el ctx, y
#   sys.stdin por un io.StringIO (no es una terminal) o, con `tty=True/False`, sync.ask_yes_no
#   por uno que cuenta las preguntas y contesta eso.
# TOML: [defaults] remote = "nas" y las [[pair]] de SUBIDA (fotos), NOTAS y COPIA.
# TOML_FOTOS_BISYNC: el mismo, con fotos sin `mode` (bisync).
retenida = lambda: results.apuntes(["fotos"])["fotos"].retenida

# Apuntar
correr(SUBIDA, rc=7, texto_log=ESPEJO_UP)
c("el freno de un espejo lo retiene", retenida() is not None, True)
correr(SUBIDA, rc=1, texto_log=RED_RECHAZADA)
c("  un fallo que no es el freno no lo suelta", retenida() is not None, True)
correr(SUBIDA, rc=0)
c("  una pasada buena lo suelta", retenida(), None)
correr(NOTAS, rc=7, texto_log=BISYNC_BORRADOS)   # con baseline, como en test_forzar.py
correr(COPIA, rc=7, texto_log=ESPEJO_UP)
c("bisync y copy nunca se retienen", [results.apuntes([n])[n].retenida for n in ("notas", "copia")],
  [None, None])
# en un sandbox limpio:
correr(SUBIDA, rc=7, texto_log=ESPEJO_UP, dry_run=True)
c("un simulacro no apunta nada", results.apuntes(["fotos"]), {})

# Saltar (en un sandbox con fotos ya retenida por un `correr(SUBIDA, rc=7, texto_log=ESPEJO_UP)`)
r = revision.Retencion("fotos", "2026-11-05 18:20:00", None)
antes = results.ruta_estado().read_bytes()
rc, salida, ordenes = correr(SUBIDA, rc=0, retenidas={"fotos": r})
c("sin aprobar, se salta sin rclone", (rc, ordenes), (sync.SKIPPED, []))
c.contains("  diciendo por qué", salida, "[fotos] Saltada: está retenida")
c("  sin tocar last_run.json", results.ruta_estado().read_bytes(), antes)
c("  y su parte lo dice", parte.leer(salida)["fotos"], parte.Parte("fotos", -1, retenida=True))

# Quién la lanza (main), con fotos retenida en last_run.json
c("sin terminal ni flag, no", sorted(lanzar_main(["fotos"])[0].retenidas), ["fotos"])
c("con --resume, sí", dict(lanzar_main(["fotos", "--resume"])[0].retenidas), {})
c("con --force, sí", dict(lanzar_main(["fotos", "--force"])[0].retenidas), {})
c("una terminal que dice que sí, sí", dict(lanzar_main(["fotos"], tty=True)[0].retenidas), {})
c("--dry-run no la mira", dict(lanzar_main(["fotos", "--dry-run"])[0].retenidas), {})
c("--resume es de la línea de órdenes", (sync.parse_args(["--resume"]).resume,
                                          sync.parse_args([]).resume), (True, False))

# Review Focus 1: «Saltarla» con otras marcadas. Con el run_all de verdad y execute simulado,
# `sync.py fotos notas` sin terminal: fotos «Saltada» y notas pasa (1 orden), y main() da 0 con
# «1 saltada(s)» en el resumen.
# Review Focus 4: fotos y fotos2 retenidas, copia no: tty=False → una sola pregunta, las dos
# en ctx.retenidas y copia fuera; tty=True → una sola pregunta y ninguna.

# §4: last_run.json de un sync.py anterior (sin la clave, código 7, log ESPEJO_UP en logs/)
ctx, _ = lanzar_main(["fotos"])
c("una unidad que se actualiza a mitad de la racha queda retenida", sorted(ctx.retenidas), ["fotos"])
c("  y la decisión queda apuntada", results.apuntes(["fotos"])["fotos"].sabida, True)
# el mismo registro con --dry-run: no se apunta nada (sabida sigue False)

# Una pareja que deja de ser espejo: fotos retenida y el TOML la pone en bisync.
c("deja de ser espejo y no arrastra la retención",
  dict(lanzar_main(["fotos"], toml=TOML_FOTOS_BISYNC)[0].retenidas), {})
```

Los comentarios con «Review Focus» y el de §4 con `--dry-run` son comprobaciones que el implementador escribe con esos mismos helpers. El valor esperado es el que dice cada comentario.

En `.claude/rules/engine.md`, `- "tests/test_retenida.py"` va en `paths`, en orden alfabético entre los tests.

- [ ] **Step 2: Ver que fallan**

Run: `$env:TCL_LIBRARY = "C:\no-existe"; python tests/test_parte.py; python tests/test_retenida.py`
Expected:
- `test_parte.py`: `TypeError: Parte.__new__() got an unexpected keyword argument 'retenida'`.
- `test_retenida.py`: falla «el freno de un espejo lo retiene» (sale `False`, porque `sync.py` aún no pasa `freno`), y después `TypeError: RunContext.__init__() got an unexpected keyword argument 'retenidas'`.

- [ ] **Step 3: Implementar en `common/parte.py` y `sync.py`**

El campo, `linea()`, `leer()`, `Medida.retenida` y `RETENIDA` van en `parte.py`. El resto, en `sync.py`, según las interfaces de arriba. `from dataclasses import dataclass, field, replace`.

- [ ] **Step 4: Ver que pasan**

Run: `$env:TCL_LIBRARY = "C:\no-existe"; python tests/test_parte.py; python tests/test_retenida.py; python tests/test_forzar.py; python tests/test_run_pair.py; python tests/test_reglas_claude.py`
Expected: todos acaban en `N comprobaciones OK` y con código 0.

- [ ] **Step 5: Commit**

```bash
git add sync.py common/parte.py tests/test_parte.py tests/test_retenida.py .claude/rules/engine.md
git commit -m "Retención: sync.py no relanza un espejo retenido sin que una persona lo apruebe"
```

---

### Task 4: el agente, el servicio y la bandeja

**Files:**
- Modify: `agente.py`, `runsync.py` (`daemon_cycle()`), `ui/bandeja.py`
- Test: `tests/test_agente_contrato.py`, `tests/test_daemon_aviso.py`, `tests/test_bandeja.py`

**Interfaces:**
- Consumes: de la tarea 3, `parte.Parte.retenida` y `parte.RETENIDA`.
- Produces:
  - `agente.MOTIVO_RESYNC = "resync"` y `agente.MOTIVO_FRENO = "freno"`.
  - `Agente.saltadas` pasa a ser `dict[tuple[str, str], str]`, de `(raíz, pareja)` al motivo.
    - Donde hoy se filtra el conjunto (`self.saltadas = {k for …}`) pasa a un dict por comprensión; `.clear()` sigue valiendo.
    - El `discard(clave)` pasa a `pop(clave, None)`.
  - `ui/bandeja.py` importa `parte` de `common`, junto a `equipo`.
  - `agente.TEXTO_RETENIDA = "saltada: retenida tras el freno de borrados"`: el diario, en lugar de `TEXTO_RESULTADO[SALTADA]`.
  - `_fin_de_pareja()`: `motivo = MOTIVO_FRENO if dicho is not None and dicho.retenida else MOTIVO_RESYNC`. Con `como == SALTADA` y el motivo freno:
    - **`dlog`:** `[{pareja}] saltada: retenida tras el freno de borrados; lánzala desde la ventana`.
    - **Aviso:** solo si `self.saltadas.get(clave) != motivo`, así que se repite cuando el motivo cambia. Es `avisar(f"{pareja} se ha parado en el freno de borrados", f"{con.nombre}: no se sincroniza sola hasta que la lances desde la ventana. {self._donde_mirar(con)}", True)`.
    - **Lock:** `_apuntar_en_lock(…)` escribe `saltada (retenida tras el freno)`, y recibe el motivo por un argumento nuevo, `retenida: bool = False`.

    Con el motivo resync, todo sigue como hoy.
  - El resumen de cada unidad:
    - `"saltadas"` solo lleva las de `MOTIVO_RESYNC`;
    - una clave nueva, `"retenidas"`, lleva las de `MOTIVO_FRENO` (ordenadas, de esa unidad).
  - `ui/bandeja._avisos()`: cada nombre de `u.get("retenidas")` da la frase `f"{nombre}: {pareja} {parte.RETENIDA}"` y la entrada `f"{frase} · Abrir…"`, con el mismo `abrir` y `I_AVISO` que las saltadas.
  - `runsync.daemon_cycle()`, en la rama `"saltada"`, con `from common import parte` dentro de la función. Si `parte.leer(output).get(name)` está retenido:
    - en el lock, `results[name] = "saltada (retenida tras el freno)"`;
    - en el diario, `dlog(f"[{name}] saltada: retenida tras el freno (lánzala desde la ventana)")`.

    Si no, lo de hoy.

- [ ] **Step 1: Escribir los tests que fallan**

En `tests/test_agente_contrato.py`, tras el bloque de la pareja que pide `--resync` y antes de `raise SystemExit`:

```python
# Un espejo retenido tras su freno: también se salta, pero se dice por qué (D2).
from common import parte  # noqa: E402

E = "e" * 32
ag_r, RE = fresco(E, parejas=("fotos",))
F.AVISOS.clear()
RETENIDA = ("[fotos] Saltada: está retenida porque se paró en el freno de borrados.\n"
            + parte.linea(parte.Parte("fotos", -1, retenida=True)) + "\n")
F.acabar(F.pasadas(RE)[-1], 0, RETENIDA)
F.vueltas(ag_r, 1)
c("un espejo retenido avisa con su motivo", [a[0] for a in F.AVISOS],
  ["fotos se ha parado en el freno de borrados"])
c.contains("  diciendo que no va sola hasta lanzarla desde la ventana", F.AVISOS[0][1],
           "U: no se sincroniza sola hasta que la lances desde la ventana")
fila = next(u for u in ag_r.resumen()["unidades"] if u["id"] == E)
c("  la bandeja la lleva como retenida, no como resync",
  (fila["retenidas"], fila["saltadas"]), (["fotos"], []))
c("  el diario dice el motivo",
  any("fotos: saltada: retenida tras el freno de borrados" in l for l in F.DIARIO), True)
c("  y el lock también", F.lock(RE)["last_results"]["fotos"], "saltada (retenida tras el freno)")
F.pasar(3600); F.vueltas(ag_r, 1)
F.acabar(F.pasadas(RE)[-1], 0, RETENIDA); F.vueltas(ag_r, 1)
c("  la siguiente no vuelve a avisar", len(F.AVISOS), 1)
F.pasar(3600); F.vueltas(ag_r, 1)
F.acabar(F.pasadas(RE)[-1], 0, "fotos: Saltada: requiere --resync\n"); F.vueltas(ag_r, 1)
c("si cambia el motivo, avisa con el nuevo (un parte sin la clave es el de siempre)",
  [a[0] for a in F.AVISOS][-1], "fotos necesita --resync")
F.pasar(3600); F.vueltas(ag_r, 1)
F.acabar(F.pasadas(RE)[-1], 0, "fotos: OK\n"); F.vueltas(ag_r, 1)
fila = next(u for u in ag_r.resumen()["unidades"] if u["id"] == E)
c("una buena la quita de la bandeja", (fila["retenidas"], fila["saltadas"]), ([], []))
```

En `tests/test_daemon_aviso.py`, tras el último `ciclo(...)` del principio:

```python
from common import parte  # noqa: E402

RETENIDA_SALIDA = ("[fotos] Saltada: está retenida porque se paró en el freno de borrados.\n"
                   + parte.linea(parte.Parte("fotos", -1, retenida=True)) + "\n")
salidas = {"fotos": RETENIDA_SALIDA,
           "notas": "[notas] Saltada: requiere --resync y no está aprobado.\n"}
n = len(avisos)
runsync.run_pair_quiet = lambda name: (0, salidas[name])
runsync.daemon_cycle(["notas", "fotos"], lock)
runsync.run_pair_quiet = lambda name: (codigos.get(name, 0), "salida")
c("una retenida se apunta con su motivo",
  (lock["last_results"]["fotos"], lock["last_results"]["notas"]),
  ("saltada (retenida tras el freno)", "saltada (requiere --resync manual)"))
c("  en el diario, sin decir que pide un resync",
  [l for l in diario if l.startswith("[fotos]")][-1],
  "[fotos] saltada: retenida tras el freno (lánzala desde la ventana)")
c("  y no es un fallo: no abre el aviso", len(avisos), n)
```

En `tests/test_bandeja.py`, junto al caso de la pareja que pide `--resync`:

```python
retenida = {"unidades": [{"id": "u", "nombre": "PRDRIVE", "atendida": True,
                          "en_lista": True, "retenidas": ["Fotos"]}]}
c("un espejo retenido es un aviso", bandeja.avisos(retenida), ["PRDRIVE: Fotos retenida tras el freno"])
c("  con el icono de aviso", bandeja.estado(retenida)[0], icons.AVISO)
c("  y lleva a su ventana", (bandeja.vista(retenida).menu[0].texto,
                            bandeja.vista(retenida).menu[0].pide[0]["pide"]),
  ("PRDRIVE: Fotos retenida tras el freno · Abrir…", equipo.PIDE_ABRIR))
```

- [ ] **Step 2: Ver que fallan**

Run: `$env:TCL_LIBRARY = "C:\no-existe"; python tests/test_agente_contrato.py; python tests/test_daemon_aviso.py; python tests/test_bandeja.py`
Expected:
- el agente avisa `fotos necesita --resync` donde se espera el freno;
- el servicio escribe `saltada (requiere --resync manual)` para `fotos`;
- la bandeja no da ningún aviso para `retenidas`.

- [ ] **Step 3: Implementar en `agente.py`, `runsync.py` y `ui/bandeja.py`**

Se implementa según las interfaces. Docstrings que cambian:
- el de `Agente.saltadas`, que pasa a decir el motivo;
- el de `_fin_de_pareja()`;
- el de `_avisos()`, que añade la retenida.

- [ ] **Step 4: Ver que pasan**

Run: `$env:TCL_LIBRARY = "C:\no-existe"; python tests/test_agente_contrato.py; python tests/test_agente_lote.py; python tests/test_daemon_aviso.py; python tests/test_bandeja.py`
Expected: todos acaban en `N comprobaciones OK` y con código 0.

- [ ] **Step 5: Commit**

```bash
git add agente.py runsync.py ui/bandeja.py tests/test_agente_contrato.py tests/test_daemon_aviso.py tests/test_bandeja.py
git commit -m "Retención: el agente, el servicio y la bandeja dicen que un espejo está retenido"
```

---

### Task 5: la ventana principal y la consola

**Files:**
- Modify: `ui/__init__.py`, `ui/console.py`, `ui/tk.py`, `runsync.py` (la llamada de `ui_flow()` a `ui.manual_args`)
- Test: `tests/test_retenida.py` (apartado «La ventana»), `tests/test_tk_dialogos.py`

**Interfaces:**
- Consumes: `revision.retenciones()` y `revision.texto_retencion()` (tarea 2), y `parte.RETENIDA` (tarea 3).
- Produces:
  - `ui.NOTA_RESYNC = "requiere resync"`: la nota de hoy, ahora como constante.
  - `ui.pair_status_notes(config)`: añade `parte.RETENIDA` a las parejas que `revision.retenciones(config.pairs)` da por retenidas. Una excepción no deja nota y no impide abrir la ventana, como hoy.
  - `ui.retenidas_marcadas(config: Config, nombres) -> list[str]`: el `revision.texto_retencion()` de cada retenida entre `nombres`, en el orden del config. Ante una excepción, `[]`.
  - `ui.manual_args(config, pairs, approve, approve_held: Callable[[list[str]], bool] | None = None) -> list[str]`:
    - **Las del resync:** las que piden `--yes` pasan a ser las de nota `NOTA_RESYNC`, no cualquier nota.
    - **Las retenidas:** si `retenidas_marcadas(config, args)` no está vacía, `approve_held` no es `None` y `approve_held(textos)` dice que sí, se añade `--resume`.
  - `ui.Frontend.approve_held(self, textos: list[str]) -> bool`, en el protocolo.
  - `ConsoleFrontend.approve_held()` devuelve siempre `False`: `sync.py` hereda la terminal y pregunta él. El docstring lo dice, como el de `approve_resync()`.
  - `TkFrontend.approve_held()`: `root_oculto()` más `preguntar_retenidas()`, como `approve_resync()`.
  - `ui.tk.preguntar_retenidas(parent, textos: list[str]) -> bool` es `preguntar(parent, "Freno de borrados", "\n\n".join(textos) + cola, aceptar, cancelar)`:
    - con un texto: cola `"\n\n¿La lanzas ahora? Si no, se salta."` y botones `"Lanzarla"` / `"Saltarla"`;
    - con varios: cola `"\n\n¿Las lanzas ahora? Si no, se saltan."` y botones `"Lanzarlas"` / `"Saltarlas"`.
  - `VentanaPrincipal.continuar()` pasa `lambda textos: preguntar_retenidas(self.root, textos)`.
  - En `runsync.py`, el menú de consola pasa a llamar `ui.manual_args(config, choice.pairs, frontend.approve_resync, frontend.approve_held)`.

- [ ] **Step 1: Escribir los tests que fallan**

En `tests/test_retenida.py`, un apartado `# ---- La ventana y la consola`. El config es `cfg = model.parse_config(...)` con, por este orden:
- `fotos`: up-mirror, retenida con `ESPEJO_UP` en `logs/`, así que `cfg.pairs[0]`;
- `notas`: bisync sin baseline, que pide resync;
- `copia`.

```python
import ui
from ui.console import ConsoleFrontend

c("la lista dice cuál está retenida y cuál pide resync", ui.pair_status_notes(cfg),
  {"fotos": "retenida tras el freno", "notas": "requiere resync"})
vistos = []
c("«Lanzarla» añade --resume",
  ui.manual_args(cfg, ["fotos"], lambda *a: vistos.append("resync") or True,
                 lambda textos: vistos.append(textos) or True), ["fotos", "--resume"])
c("  preguntando con el texto de revision, y sin preguntar por un resync que no hay", vistos,
  [[revision.texto_retencion(cfg.pairs[0], revision.retencion(cfg.pairs[0]))]])
c("«Saltarla» deja los nombres (y sync.py la salta)",
  ui.manual_args(cfg, ["fotos", "copia"], lambda *a: True, lambda t: False), ["fotos", "copia"])
c("aprobar el resync no aprueba borrados, ni al revés",
  (ui.manual_args(cfg, ["notas", "fotos"], lambda *a: True, lambda t: False),
   ui.manual_args(cfg, ["notas", "fotos"], lambda *a: False, lambda t: True)),
  (["notas", "fotos", "--yes"], ["notas", "fotos", "--resume"]))
c("quien no sabe preguntar por las retenidas no lanza ninguna",
  ui.manual_args(cfg, ["fotos"], lambda *a: True), ["fotos"])
c("la consola deja que pregunte sync.py", ConsoleFrontend().approve_held(["x"]), False)
results.ruta_estado().write_text("{roto", encoding="utf-8")
c("un registro ilegible no impide sincronizar",
  (ui.manual_args(cfg, ["fotos"], lambda *a: True, lambda t: True), "fotos" in ui.pair_status_notes(cfg)),
  (["fotos"], False))
```

En `tests/test_tk_dialogos.py`, junto a la comprobación de `preguntar_resync()` y con la misma grabadora de `preguntar`:

```python
llamadas.clear()
c("un espejo retenido pregunta con el diálogo del tema", uitk.preguntar_retenidas(raiz, ["Texto A"]), True)
_, padre_, titulo, texto, aceptar, cancelar = llamadas[0]
c("  con su texto y «Lanzarla» / «Saltarla»",
  (padre_ is raiz, titulo, texto.startswith("Texto A"), aceptar, cancelar),
  (True, "Freno de borrados", True, "Lanzarla", "Saltarla"))
llamadas.clear()
uitk.preguntar_retenidas(raiz, ["A", "B"])
c("  con varias, en plural", llamadas[0][4:], ("Lanzarlas", "Saltarlas"))
```

- [ ] **Step 2: Ver que fallan**

Run: `$env:TCL_LIBRARY = "C:\no-existe"; python tests/test_retenida.py`
Expected: `TypeError: manual_args() takes 3 positional arguments but 4 were given`.

`test_tk_dialogos.py` abre ventanas: se corre en un escritorio aparte o queda para el CI.

- [ ] **Step 3: Implementar en `ui/__init__.py`, `ui/console.py`, `ui/tk.py` y `runsync.py`**

Se implementa según las interfaces. Los imports de `common.revision` y `common.parte` van dentro de las funciones de `ui/__init__.py`.

- [ ] **Step 4: Ver que pasan**

Run: `$env:TCL_LIBRARY = "C:\no-existe"; python tests/test_retenida.py; python tests/test_forzar_desatendido.py; python tests/test_imports_perezosos.py; python tests/test_instantanea.py; python tests/test_llavero.py`
Expected: todos acaban en `N comprobaciones OK` y con código 0.

Si `test_imports_perezosos.py` nombra `common.revision` o `common.parte` como import que falta en la precarga, se añade a `ui.tk.PRECARGA` y se repite.

- [ ] **Step 5: Commit**

```bash
git add ui/__init__.py ui/console.py ui/tk.py runsync.py tests/test_retenida.py tests/test_tk_dialogos.py
git commit -m "Retención: «Sincronizar ahora» pregunta antes de lanzar un espejo retenido"
```

---

### Task 6: «Reparación», «Volver a intentar…»

**Files:**
- Modify: `ui/repair.py`, `ui/tk_repair.py`
- Test: `tests/test_repair.py`, `tests/test_tk_reparacion.py`, `tests/test_forzar_desatendido.py`, `tests/test_resync_desatendido.py`

**Interfaces:**
- Consumes:
  - `revision.Retencion` en `hallazgo.dato[2]` y `revision.texto_retencion()` (tarea 2);
  - `orden.max_delete_efectivo()`;
  - lo que ya tiene `repair` (`RepairPlan`, `_pareja()`, `_carpeta_vacia()`, `vigente()`).
- Produces:
  - `repair.ETIQUETA_VOLVER = "Volver a intentar…"`.
  - `repair.retencion_de(hallazgo: Hallazgo) -> Retencion | None`: la retención si `hallazgo.clave in ("freno", "fallo")` y `dato[2]` es una `Retencion`.
  - `repair.puede_volver(hallazgo) -> bool`: `retencion_de(hallazgo) is not None`.
  - `repair.args_volver(hallazgo) -> list[str]`: `[str(hallazgo.pareja), "--resume"]`.
  - `repair.aviso_volver(config: Config, hallazgo: Hallazgo) -> RepairPlan`, sin nada que ejecutar. Sin retención lanza `ReparacionImposible("Esta pareja ya no está retenida: lánzala como cualquier otra.")`; si no, devuelve un `RepairPlan` así:
    - **`titulo`:** `f"Volver a intentar «{pair.name}»"`.
    - **`consequences`:**
      1. `f"Se lanza UNA pasada normal de «{pair.name}», con su tope de borrados ({tope} ficheros)."` si `tope = orden.max_delete_efectivo(pair)` es `>= 0`; si no, `f"Se lanza UNA pasada normal de «{pair.name}»."`.
      2. `"Si acaba bien, deja de estar retenida: el servicio y el agente vuelven a lanzarla solos."`
      3. `"Si vuelve a pararse en el freno, sigue retenida."`
    - **`warnings`:** `[revision.texto_retencion(pair, retencion)]`. Se le añade una frase si el origen es local y su carpeta está vacía: la misma que hoy escribe `_forzar_espejo()`, que pasa a una constante `_LOCAL_VACIA` que comparten los dos.
  - `repair.arreglos_fallo()`: en un `fallo` retenido no sale nunca «Reintentar la pasada». Sale una sola vez `(ETIQUETA_VOLVER, "volver", hallazgo)`, delante de «Ver el log», tenga o no su causa `REINTENTAR`. En un `fallo` no retenido no cambia nada.
  - `repair.hallazgos_reparables()` cuenta también `puede_volver(h)`.
  - `tk_repair.construir()`:
    - **El manejador, `volver(hallazgo)`:** es como `forzar()`: `fresco()`, después `repair.aviso_volver()` (un `ReparacionImposible` da `showerror` y `repintar()`), después `tk_pairs.confirmar_plan()`. Al confirmar, `panel.devolver(True)` y `panel.cerrar(lambda: lanzar(f"Volver a intentar «{hallazgo.pareja}»", repair.args_volver(hallazgo)))`.
    - **`ARREGLOS`:** gana `"volver": volver`.
    - **`botones_debajo()` de un `freno`:** pone `(repair.ETIQUETA_VOLVER, volver, repair.puede_volver(h))` delante de «Forzar sincronización…».

- [ ] **Step 1: Escribir los tests que fallan**

En `tests/test_repair.py`, un apartado nuevo. Con `results.apuntar(..., freno=True)` deja `fotos` (up-mirror) retenida con `ESPEJO_UP` y saca el hallazgo de `revision.revisar(cfg)`:

```python
c("una retenida ofrece volver a intentarlo", repair.puede_volver(freno), True)
c("  con --resume y nada más", repair.args_volver(freno), ["fotos", "--resume"])
c("  sin --force, --yes ni --resync", set(repair.args_volver(freno)) & {"--force", "--yes", "--resync"}, set())
plan = repair.aviso_volver(cfg, freno)
c("  su plan se confirma con el texto de revision",
  (plan.titulo, plan.warnings[0], plan.execute()),
  ("Volver a intentar «fotos»", revision.texto_retencion(cfg.pairs[0], freno.dato[2]), []))
c.contains("  y dice el tope", plan.consequences[0], "con su tope de borrados (50 ficheros).")
c("  el texto nombra los botones de verdad",
  all(e in plan.warnings[0] for e in (repair.ETIQUETA_FORZAR, repair.ETIQUETA_SIMULAR)), True)
# fallo de red de la misma pareja, ya retenida:
c("en un fallo retenido, «Volver a intentar…» sustituye a «Reintentar»",
  [b[0] for b in repair.arreglos_fallo(fallo, hallazgos)], ["Volver a intentar…", "Ver el log"])
c("  y cuenta como reparable", fallo in repair.hallazgos_reparables(hallazgos), True)
# la misma pareja con el freno apuntado sin retención (freno=False):
c("sin retención no se ofrece", repair.puede_volver(freno_sin), False)
c("  y su plan se niega", motivo_de(lambda: repair.aviso_volver(cfg, freno_sin)),
  "Esta pareja ya no está retenida: lánzala como cualquier otra.")
c("  un fallo de red sin retención sigue con «Reintentar»",
  [b[0] for b in repair.arreglos_fallo(fallo_sin, hallazgos_sin)], ["Reintentar la pasada", "Ver el log"])
```

`motivo_de()` es un helper local: el mensaje del `ReparacionImposible`, o `None`.

En `tests/test_tk_reparacion.py`, con `con_freno(ESPEJO_UP, raw=<up-mirror>)` y a continuación `results.apuntar(pair.name, 7, log, freno=True)`:

```python
c("un espejo retenido trae «Volver a intentar…» junto a forzar",
  {"Volver a intentar…", "Forzar sincronización…"} <= set(visto["botones"]), True)
# pulsarlo con confirmar(True):
c("  confirma y lanza --resume", desde_reparacion, [("Volver a intentar «espejo»", ["espejo", "--resume"])])
# pulsarlo con confirmar(False): desde_reparacion == [] y la pantalla sigue viva (como el caso de forzar)
# un freno sin retención (sin el segundo results.apuntar): "Volver a intentar…" not in visto["botones"]
```

En `tests/test_forzar_desatendido.py`:
- un recorrido de fuentes igual que el de `--force`, para `"--resume"`, con `PERMITIDOS_RESUME = {"sync.py": "el argumento de la línea de órdenes", "ui/__init__.py": "manual_args(), tras el sí de quien eligió", "ui/repair.py": "args_volver(), tras confirmar su plan"}`;
- las dos comprobaciones de que no sobra ni falta ninguno;
- `{"runsync.py", "agente.py", "penwatch.py", "pregunta.py", "prdrive-install.py", "ui/tk.py", "ui/console.py", "common/llavero.py", "common/keepassxc.py"} & nombran == set()`;
- en el apartado del agente, `[p.args for p in lanzadas if "--resume" in p.args] == []`;
- el docstring del módulo nombra `--resume`.

En `tests/test_resync_desatendido.py`, el conjunto prohibido pasa a `{"--resync", "--yes", "--resume"}`.

- [ ] **Step 2: Ver que fallan**

Run: `$env:TCL_LIBRARY = "C:\no-existe"; python tests/test_repair.py; python tests/test_forzar_desatendido.py`
Expected: `AttributeError: module 'ui.repair' has no attribute 'puede_volver'`. En el segundo, «solo nombran --resume los módulos previstos» falla nombrando `ui/repair.py`, que se espera y aún no lo nombra.

- [ ] **Step 3: Implementar en `ui/repair.py` y `ui/tk_repair.py`**

Se implementa según las interfaces. El docstring de `tk_repair` nombra el botón nuevo junto a `FORZAR`.

- [ ] **Step 4: Ver que pasan**

Run: `$env:TCL_LIBRARY = "C:\no-existe"; python tests/test_repair.py; python tests/test_repair_forzar.py; python tests/test_forzar_desatendido.py; python tests/test_resync_desatendido.py`
Expected: todos acaban en `N comprobaciones OK` y con código 0.

`test_tk_reparacion.py` abre ventanas: se corre en un escritorio aparte o queda para el CI.

- [ ] **Step 5: Commit**

```bash
git add ui/repair.py ui/tk_repair.py tests/test_repair.py tests/test_tk_reparacion.py tests/test_forzar_desatendido.py tests/test_resync_desatendido.py
git commit -m "Retención: «Reparación» ofrece «Volver a intentar…» en un espejo retenido"
```

---

### Task 7: la documentación

**Files:**
- Modify:
  - `AGENTS.md`;
  - en `docs/agents/reference/`: `engine.md`, `repair.md`, `service.md`, `agent.md`, `tray.md`, `ui.md` y `commands-testing.md`;
  - `docs/guia/diagnostico.md` y `docs/guia/configuracion.md`;
  - `docs/superpowers/plans/2026-10-08-correcciones-auditoria.md`;
  - `docs/superpowers/specs/2026-11-06-espejo-retenido-tras-el-freno-design.md` (su línea de estado).
- Test: `tests/test_reglas_claude.py` y la tanda de los cambios.

**Interfaces:** ninguna; solo textos. Los `docs/agents/` van en inglés y `docs/guia/` en español, para el usuario y sin detalles internos.

- [ ] **Step 1: `AGENTS.md`, una línea en «Safety invariants»**, tras la de `max-delete`:

```markdown
- A `*-mirror` stopped by its `--max-delete` brake is **held** (`retenida` in `last_run.json`): `sync.py` skips it on every unattended path, old agents included, until a person approves a pass (`--resume` from the window or «Reparación», or `--force`) and one ends OK. Never pass `--resume` from an unattended launcher (`engine.md`).
```

- [ ] **Step 2: Los docs de área**

Cada uno con lo que le toca, en párrafos cortos:
- **`engine.md`:** un apartado nuevo, «Held mirrors (D2)». Explica:
  - los tres valores de `retenida`;
  - quién lo apunta (`_pasar_pareja()`, tras `dispose_log()`);
  - `resolver_retenidas()` y el salto con `SKIPPED` sin apuntar nada;
  - `--resume` frente a `--yes` y `--force`;
  - el caso de §4.

  En el apartado de `--force` hay que decir que también aprueba una retenida.
- **`repair.md`:** el botón «Volver a intentar…», `aviso_volver()`, la frase del `detalle` y el tercer elemento de `dato`.
- **`service.md`:** el texto de `daemon.log` y de `last_results`.
- **`agent.md`:** `Agente.saltadas` con su motivo, el aviso, el diario y el lock.
- **`tray.md`:** la clave `"retenidas"` del resumen y su aviso.
- **`ui.md`:** la nota «retenida tras el freno», `manual_args(…, approve_held)` y `preguntar_retenidas()`.
- **`commands-testing.md`:** `--resume` en la lista de órdenes de `sync.py`, y `tests/test_retenida.py`.

- [ ] **Step 3: Las guías del usuario**

- **`docs/guia/diagnostico.md`:** un apartado, «Un espejo retenido tras el freno». Explica:
  - qué pasa: el espejo borró hasta su tope y se paró, y ya no se sincroniza solo;
  - cómo se ve: la nota en la lista, el aviso del agente y «Reparación»;
  - qué hacer: «Ver qué se borraría», «Volver a intentar…» o «Forzar sincronización…» si los borrados eran a propósito.
- **`docs/guia/configuracion.md`:** en la tabla de modos, las filas de `up-mirror` y `down-mirror` dicen que, si se paran en su freno de borrados, quedan retenidos hasta lanzarlos desde la ventana.

- [ ] **Step 4: Cerrar D2 en los documentos de la auditoría**

En `2026-10-08-correcciones-auditoria.md`, junto a D2 en «After the decisions», va «Done (2026-11): see `docs/superpowers/specs/2026-11-06-espejo-retenido-tras-el-freno-design.md`». En la spec, el estado pasa a «implementada».

- [ ] **Step 5: Comprobar**

Run: `$env:TCL_LIBRARY = "C:\no-existe"; python tests/test_reglas_claude.py; python tests/run_all.py --cambios -j auto`
Expected: `test_reglas_claude.py` OK y la tanda sin fallos. Los tests de ventanas se listan como «Fuera, por abrir ventanas» y los corre el CI.

- [ ] **Step 6: Commit**

```bash
git add AGENTS.md docs/agents/reference docs/guia docs/superpowers
git commit -m "Retención: documentación del espejo retenido tras el freno"
```
