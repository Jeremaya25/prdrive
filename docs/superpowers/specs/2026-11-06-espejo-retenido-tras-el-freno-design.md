# Un espejo que se para en el freno se queda retenido — diseño

Fecha: 06/11/2026. Es la decisión D2 (a) de la auditoría externa, «hold after the brake»
(`docs/superpowers/plans/2026-10-08-correcciones-auditoria.md`, «Decisions for the user»;
hallazgo S6 de `docs/superpowers/specs/2026-10-08-auditoria-externa.md`). Se decidió el
08/10/2026 y solo quedó un esbozo («After the decisions»). Estado: **implementada** (spec aprobada por el
dueño el 07/11/2026); el plan es `docs/superpowers/plans/2026-11-07-espejo-retenido-tras-el-freno.md`.

Decidido con el dueño el 06/11/2026:
- **La ventana pregunta y lanza.** Si se marca un espejo retenido y se pulsa «Sincronizar
  ahora», una pregunta dice cuánto borró y cuánto puede borrar aún; «Lanzarla» hace una
  pasada normal. Descartados: «solo desde Reparación» y «lanzar sin preguntar».
- **La regla vive en `sync.py`** (enfoque A, abajo), no en el planificador ni en `runsync`.

## Qué se quiere

`rclone sync --max-delete N` borra exactamente N ficheros, sale con 7 y deja el resto
(`StatsInfo.DeleteFile()`, `fs/accounting/stats.go`). Lo borrado se queda borrado. Hoy el
servicio, `--auto --once` y el agente vuelven a lanzar ese espejo a su hora, y cada pasada
borra otros N: con el origen desmontado o vacío, un `down-mirror` vacía la unidad (o un
`up-mirror` el remoto) de 50 en 50, sin que nadie lo apruebe. bisync no tiene el problema:
su freno para la pasada entera antes de propagar nada (`excessDeletes()`,
`cmd/bisync/deltas.go`).

Después del cambio, un espejo que se para en su freno de borrados **queda retenido**: ningún
camino desatendido lo vuelve a lanzar hasta que una persona apruebe una pasada, y la
retención se suelta cuando una pasada de esa pareja acaba bien.

No se quiere, y manda sobre lo anterior:
- cambiar nada de una pareja sana: un espejo que nunca se para en el freno no nota nada;
- tocar los frenos (`max-delete` 50 en los espejos, 25 % en bisync) ni lo que hace `--force`;
- que un registro ilegible, un log que falta o un `sync.py` antiguo impidan sincronizar una
  pareja que no está retenida.

## Lo que hay hoy (y se aprovecha)

- **El freno ya se reconoce.** `frenos.detectar(texto, pair)` / `frenos.detectar_en(log, pair)`
  dan un `Freno` de tipo `ESPEJO` con `borrados` (los que ya borró) y `pendientes` (los que se
  quedó sin borrar). `revision._fallos()` lo convierte en el hallazgo `freno`, con «Forzar
  sincronización…», «Ver qué se borraría» y «Ver el log» (`repair.md`).
- **«Saltada» ya significa «espera a una persona».** Una pareja que pide un `--resync` sin
  aprobar sale con `SKIPPED` (-1), no se apunta en `last_run.json` y escribe un parte con
  `rc: -1`. El agente la cuenta como `SALTADA` (`pl.SALTADA`: espera `espera_saltada`, 1 h, y
  `pl.despierta()` la libera al volver de la ventana); `runsync.daemon_cycle()` busca
  «saltada» en la salida. Los dos ya existen en todas las versiones en uso.
- **Lo que aprueba una persona va por argumentos.** La ventana pregunta antes de un resync y
  añade `--yes` (`ui.manual_args()`); «Reparación» lanza `[pareja, "--force"]` tras su plan.
  Ningún lanzador desatendido pasa `--yes` ni `--force` (`tests/test_forzar_desatendido.py`,
  `tests/test_resync_desatendido.py`).
- **`last_run.json` está en la unidad** (`state/`): lo que se apunte ahí viaja con ella a
  cualquier equipo.

## Enfoques

- **A, la regla en `sync.py` (elegido).** `sync.py` apunta la retención al acabar la pasada
  frenada y, al empezar, se niega a lanzar un espejo retenido sin aprobación, contestando
  «saltada». Cubre a la vez el servicio de la ventana, `--auto --once`, el vigilante y el
  agente, **también un agente de una versión anterior**, porque todos lanzan el `sync.py` de
  la unidad.
- **B, la regla en los lanzadores** (el esbozo de octubre): el planificador y
  `runsync.daemon_cycle()` leen la retención y no lanzan la pareja. Ahorra arrancar un
  `sync.py`, pero son dos sitios que mantener iguales, un agente anterior seguiría borrando y
  penwatch quedaría fuera.
- **C, A y B.** Lo que ahorra B ya lo da `pl.SALTADA`: un intento por hora como mucho, que no
  llega a lanzar rclone.

## Diseño

### 1. La retención, en `last_run.json`

Cada entrada de `parejas` gana una clave, `retenida`:

| Valor | Significa |
|---|---|
| un sello (`store.stamp()`) | retenida desde entonces |
| `null` | no está retenida |
| la clave no está | la escribió un `sync.py` anterior: no se sabe (apartado 4) |

`results.apuntar(nombre, codigo, log, retenida=…)` la escribe siempre:
- **rc 0** → `null`: una pasada buena suelta la retención.
- **El freno de un espejo** → el sello de ahora (también si ya estaba retenida: otra parada la
  renueva).
- **Otro fallo** → la de la entrada anterior, como ya se hace con `buena`. Un fallo de red de
  una pasada aprobada no la suelta: la causa del freno sigue sin comprobarse.

Quién decide si es el freno: `_pasar_pareja()`, con el log ya guardado en `logs/`
(`dispose_log()`), solo si la pareja es un espejo (`frenos.tiene_freno(pair) and not
pair.is_bisync`), la pasada es de verdad y `rc != 0`: `frenos.detectar_en(saved, pair)` de tipo
`ESPEJO`. Un `OSError` al leerlo es «no es el freno». No se lee nada en las pasadas buenas.

### 2. La decisión, en un solo sitio: `revision.retencion(pair)`

`revision.retencion(pair) -> Retencion | None` (sin escribir nada) es lo único que dice si una
pareja está retenida, y lo preguntan `sync.py`, la ventana, la consola y «Reparación»:
- `None` si la pareja no es un espejo (una pareja que pasa de espejo a bisync no arrastra la
  retención), si la clave es `null`, o si no hay registro.
- Con un sello: `Retencion(pareja, desde, log)`.
- Sin la clave: el apartado 4.

Las cifras (`Freno.borrados`, `pendientes`, el lado) no se guardan: se sacan del log cuando
hay que enseñarlas (`revision._veredicto_de()`, que ya recuerda el veredicto por `(log, tamaño,
mtime, modo)`). Si el log ya no está, la retención sigue y el texto sale sin cifras.

### 3. `sync.py`: quién la puede lanzar

Al empezar, junto a `resolve_resync_approval()`, `resolver_retenidas(selected, aprobadas)`:
- No hace nada en un `--dry-run`: un simulacro no borra y es como se investiga.
- Lista cada retenida con su texto (apartado 6).
- Las da por aprobadas con `--resume` (flag nuevo; el nombre se puede cambiar) o con `--force`
  (necesita nombrar la pareja y solo lo pasa una persona: `test_forzar_desatendido.py`).
- Con terminal (`ask_yes_no()`), lo pregunta una vez para todas.
- Sin terminal y sin flag, no las aprueba.

Las no aprobadas van en `RunContext.retenidas` (de nombre a su `Retencion`, que lleva la fecha
que dice la línea). `_pasar_pareja()`, justo
después de `problema_contencion()` y antes del preflight, imprime

`[Fotos] Saltada: está retenida desde el 05/11 18:20 porque se paró en el freno de borrados.
Lánzala desde la ventana (te dirá cuánto puede borrar) o mira «Reparación».`

y devuelve `SKIPPED` **sin apuntar nada** (así la retención no se pierde) y sin lanzar rclone.
La palabra «saltada» es la que buscan el agente y `runsync` (apartado 7).

`--resume` es aparte de `--yes` a propósito: la ventana pregunta por los resyncs y por las
retenidas en dos preguntas, y aprobar un resync no puede aprobar borrados. Tampoco va en el
TOML: no es un flag de rclone ni se puede pedir desde el config.

### 4. Las unidades que ya están perdiendo ficheros al actualizar

Una entrada sin la clave `retenida` la escribió un `sync.py` anterior. Si su último resultado
es un fallo con log y la pareja es un espejo, `revision.retencion()` mira ese log (una vez por
proceso, con la caché de `_veredicto_de()`): si es el freno, la pareja está retenida desde el
`cuando` de esa entrada. Así una unidad que se actualiza a mitad de una racha queda retenida en
la primera pasada, sin esperar a otros 50 borrados.

Para no volver a leer ese log en cada pasada, `sync.py` (no `revision`, que no escribe) apunta
la decisión con `results.fijar_retencion(nombre, valor)`, que solo escribe si la clave falta y
nunca falla. Lo hace al preguntar por las retenidas al empezar (apartado 3), y no en un
`--dry-run`, que no apunta nada.

### 5. La ventana principal

`ui.manual_args(config, pairs, approve, approve_held)` gana una segunda pregunta. Si alguna
pareja marcada está retenida (`revision.retencion()`), se le pregunta a quien eligió (en la
ventana, `tk.preguntar_retenidas()`, un diálogo como `preguntar_resync()`; en la consola,
`ConsoleFrontend.approve_held()`). «Lanzarla» añade `--resume`; «Saltarla» no añade nada y
`sync.py` la salta. El protocolo `ui.Frontend` gana `approve_held()`.

La nota de la lista de parejas (`ui.pair_status_notes()`, hoy «requiere resync») dice
«retenida tras el freno» en esas parejas. No se añade ningún botón a la ventana principal.

### 6. El texto, uno solo

`revision.texto_retencion(pair, retencion)` lo escriben la consola de `sync.py`, el diálogo de
la ventana y el plan de «Reparación», así que dicen lo mismo:

> «Fotos» se paró en el freno de borrados el 05/11 a las 18:20: borró 50 ficheros en el
> remoto y le quedaban 120. Si la lanzas, puede borrar hasta 50 más. Si esos borrados son lo
> que querías, «Forzar sincronización…» en «Reparación» los hace todos de una vez; si no los
> esperabas, mira antes «Ver qué se borraría».

El tope sale de `orden.max_delete_efectivo(pair)`, el que rclone recibirá de verdad. Sin
cifras (log que falta, o de más de 4 MiB, donde `borrados` es `None`) se dice sin ellas, nunca
con una cifra parcial.

El aviso de los borrados intencionados importa: quien borró 200 ficheros a propósito vería
el espejo pararse, aprobaría una pasada normal, se borrarían 50 y volvería a quedar retenido.
Para eso está forzar.

### 7. El agente y el servicio

- **El parte** (`common/parte.py`) de una pareja saltada por la retención lleva
  `"retenida": true`; solo entonces, para que los partes de siempre sigan saliendo igual
  byte a byte. `parte.leer()` de una versión anterior ya ignora las claves que no conoce.
- **El agente**, con ese campo y `como == SALTADA`:
  - escribe en los diarios «retenida tras el freno de borrados; lánzala desde la ventana»;
  - avisa una vez «Fotos se ha parado en el freno de borrados», con «no se sincroniza sola
    hasta que la lances desde la ventana», en lugar de «necesita --resync»;
  - lista la pareja en la bandeja como «retenida tras el freno».

  `Agente.saltadas` pasa de conjunto a dict `(raíz, pareja) → motivo`. El planificador no
  cambia: la trata como `SALTADA`.
- **`runsync.daemon_cycle()`** lee el parte y, si es una retenida, escribe en `daemon.log`
  «retenida tras el freno (lánzala desde la ventana)» en vez de «requiere --resync manual».
- **Un agente anterior** con una unidad nueva: la pareja queda retenida igual (lo hace
  `sync.py`); solo el texto de su aviso y de su bandeja dice «necesita --resync». «Reparación»
  dice lo correcto.

### 8. «Reparación» y `--doctor`

- **El hallazgo** de una pareja retenida (el `freno`, o el `fallo` si la última pasada
  aprobada falló por otra cosa) añade a su `detalle` «Retenida desde el …: ni el servicio ni el
  agente la lanzan solos hasta que una pasada acabe bien». `--doctor` lo imprime, porque sale
  del mismo `revisar()`.
- **Botón nuevo, «Volver a intentar…»** (`repair.ETIQUETA_VOLVER`), en esa pareja.
  - `repair.aviso_volver(config, hallazgo)` es un `RepairPlan` sin nada que ejecutar, como
    `aviso_forzar()`, con el texto del apartado 6. Va por `confirmar_plan()` y, al confirmar,
    lanza `repair.args_volver()` = `[pareja, "--resume"]`.
  - En el `fallo` de una pareja retenida sustituye al «Reintentar» sin confirmación
    (`args_reintentar()` saldría «Saltada»).
  - Lo demás no cambia: «Forzar sincronización…» ya suelta la retención si acaba bien.
- **Como cualquier botón**, actúa sobre el hallazgo fresco de `repair.vigente()`.

## Qué pasa con los dispositivos en uso

- **Un espejo sano**: nada. La clave nueva vale `null` desde su primera pasada.
- **Un espejo cuya última pasada fue el freno**: queda retenido en la primera pasada tras
  actualizar (apartado 4) y lo dice el aviso del agente o «Reparación».
- **Una unidad sin actualizar**: sigue como hoy (sin retención) aunque el agente del equipo
  sea nuevo; el agente no decide nada por su cuenta.
- **Formato**: `last_run.json` gana una clave que los lectores anteriores no miran
  (`results.fallos_de()`, `_buena()`). El parte gana una clave opcional.

## Lo que no entra

| Idea | Motivo |
|---|---|
| Retener bisync | Su freno para la pasada entera y no borra a plazos: repetirla no cuesta datos. |
| El freno por tamaño (`--max-delete-size`) | `frenos` no lo reconoce y sigue siendo un `fallo`. Solo lo tiene quien lo ponga a mano; si se quiere, va aparte. |
| Que el planificador no lance la pareja (enfoque B) | `SALTADA` ya la limita a un intento por hora, que no lanza rclone. |
| Soltar la retención sin pasada («Reanudar») | Lo que la suelta es comprobar que la pareja vuelve a ir bien. |
| Retirar penwatch (D1) | Es otra decisión, con su propia PR. |

## Pruebas

- **`tests/test_retenida.py`** (nuevo; en los `paths` de la regla de su área,
  `commands-testing.md`), con los logs reales de `tests/_logs_frenos.py`:
  - el freno de un espejo retiene y una pasada buena suelta;
  - un fallo que no es el freno no suelta, y otra parada renueva la fecha;
  - sin aprobación sale «Saltada», rc -1, sin rclone y sin tocar `last_run.json`;
  - `--resume`, `--force` y una terminal la lanzan; `--dry-run` no la mira;
  - un registro sin la clave se decide por su log una vez y queda apuntado;
  - bisync y `copy` nunca se retienen;
  - una pareja que deja de ser espejo no arrastra la retención.
- **Tests que se amplían:**
  - `test_forzar_desatendido.py` y `test_resync_desatendido.py`: ningún lanzador desatendido
    pasa `--resume`.
  - `test_parte.py`: la clave, solo cuando es `true`.
  - `test_revision.py`: la frase y el texto.
  - `test_repair.py`: «Volver a intentar…», su plan y sus argumentos, y que sustituye a
    «Reintentar».
  - Los tests del agente que cubren `SALTADA`: el aviso, el diario y la bandeja con el motivo.
  - `test_daemon_aviso.py` (el que lleva `daemon_cycle()`): el texto de `daemon.log`.
  - `test_tk_dialogos.py`: el diálogo nuevo.

## Docs

- **`AGENTS.md`**, en las invariantes de seguridad, una línea: un `*-mirror` parado por su
  freno queda retenido; ningún camino desatendido lo relanza hasta que una persona apruebe
  una pasada (`--resume`, `--force`) y una acabe bien.
- **Docs de área:**
  - `engine.md`: el apartado de `--force` y uno nuevo de la retención.
  - `repair.md`: el botón y la frase.
  - `service.md`: `daemon.log`.
  - `agent.md` y `tray.md`: el aviso, el diario y la bandeja.
  - `ui.md`: la pregunta de la ventana.
  - `commands-testing.md`: la flag y el test nuevo.
- **Para el usuario:** `docs/guia/diagnostico.md` y `docs/guia/configuracion.md` (la tabla de
  modos dice qué pasa al pararse un espejo).
- **El plan de la auditoría**: D2 marcada como hecha, con el enlace a esta spec.
