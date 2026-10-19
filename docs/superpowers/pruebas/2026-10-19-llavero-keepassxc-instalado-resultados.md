# El llavero en un equipo con KeePassXC instalado — resultados

Fecha: 19/10/2026, de 13:30 a 14:30. Lo hizo Claude solo (Pere preparó el equipo y se fue a los 30 min).
Código probado: el de la unidad, prdrive **0.7.7** (el mismo `VERSION` que `main` en `4bcda9b`). Filas de
`2026-09-25-equipo-pendiente-en-real.md` que toca: **KP3** entera, **KP2** (la mitad exFAT) y media **KR1**;
del plan del portátil (`2026-10-04-keepassxc-portatil.md`), la **B5** que quedó «parcial: no hay equipo con el MSI».

## 1. Entorno

- Windows 11 IoT Enterprise LTSC 10.0.26100, sobremesa. Sin elevar. A media prueba la pantalla pasó de dos monitores 1920×1080 a uno de 1024×768.
- **La unidad**: pendrive `F:`, **exFAT con BitLocker**, prdrive 0.7.7, llavero **sin contraseña**
  (`llave_interna = true`, `.keychain/llave.keyx`), atendido por el agente (modo `daemon`, 10 min), contra un remoto de rclone propio.
- **KeePassXC 2.7.12 instalado** (MSI, `C:\Program Files\KeePassXC`) con otra base de pruebas, aquí `otra.kdbx`, en una carpeta
  del usuario (una copia, sin contraseña, con su fichero llave al lado). Sin integración con navegadores al empezar.
- KeePass 2.61.1 instalado. Firefox con KeePassXC-Browser.
- Antes de tocar nada se copiaron: `.keychain/`, `.prdrive/state/`, la configuración y los tres ejecutables del KeePassXC de la unidad,
  `sync_config.toml`, la carpeta de la otra base, las dos configuraciones del KeePassXC instalado, las seis claves `NativeMessagingHosts`,
  `llavero-navegador.json` y `keychain/` del remoto.

Cómo se manejó: los avisos de prdrive (Tk) con clics; **KeePassXC no sale en las capturas** (se protege de ellas), así que se leyó y
manejó con UI Automation (sus controles llevan nombre y `AutomationId`). La bandeja se sustituyó por su petición al agente
(`equipo.pedir({"pide": "llavero", "id": …})`, lo mismo que manda el menú). Para el «otro dispositivo» se subió al remoto, con el
rclone de la unidad, otra versión válida de la base con hora más nueva.

## 2. Resultados

| Prueba | Resultado | Lo visto |
|---|---|---|
| **A1** El instalado abierto → «Abrir llavero» (`Llavero.bat` y bandeja) | **bien** | «Hay otro KeePassXC abierto en este equipo, que no es el del dispositivo…». No se escribe la configuración ni el registro; no pasa la base. Desde la bandeja, el diario dice «abriendo su llavero» y nada más (sin pausa no encola pasada). |
| **A2** El llavero abierto → se lanza el instalado | **instancia única confirmada; hallazgo 2** | El instalado no se queda (el tubo es `keepassxc-<usuario>.socket`: uno por usuario). Con `otra.kdbx` de argumento, la otra base se abre **dentro del KeePassXC de la unidad**, y su ruta entra al momento en `LastDatabases` de `.prdrive/keepassxc/config/windows/keepassxc_local.ini` (sin desbloquearla). `LastKeyFiles` no se guarda (bien). |
| A2 · cerrar con dos bases abiertas (`--cerrar-llavero`) | **bien, con hallazgo 2** | Cierra KeePassXC (las dos), termina el `keepassxc-proxy.exe` de Firefox, borra las cuatro claves del navegador (no había JSON del instalado) y la `NativeMessagingHosts` de Mozilla, que la nota decía creada por prdrive. Pero el pendrive se queda con `LastOpenedDatabases=…Database.kdbx, …otra.kdbx` y `LastActiveDatabase=…otra.kdbx`: **el siguiente «Abrir llavero» vuelve a abrir la otra base**. |
| Llavero sin contraseña: abrir | **bien** | Se abre ya desbloqueado, sin preguntar nada (`--keyfile` con la contraseña vacía). Es la prueba a mano que quedaba de `2026-10-06-llavero-sin-contrasena-plan.md`. |
| **B** Conflicto: entrada local + otra versión en el remoto, con el agente en pausa; «Reanudar» | **bien** | `Database.conflicto-dispositivo1.kdbx` (gana la más nueva) y el aviso del agente «el llavero tiene dos versiones… «Abrir llavero» ofrece combinarlas antes de abrir». |
| B · «Abrir llavero» → «Combinar» (KP2, exFAT) | **bien; hallazgo 5** | El plan dice «no pide contraseña». La consola combina sin preguntar; la copia pasa a `.keychain/.prversions/…conflicto-dispositivo1~20261019-135600.kdbx`; la entrada local está en la base; en el remoto la copia se borra (a su `.prversions/`) y la pasada acaba con rc 0. Que el freno de borrados saltara y se repitiera no se ve: la repetición tira su log. |
| **KR1** (mitad, un solo dispositivo): pausa de la bandeja, cambio en el remoto, «Abrir llavero» por la bandeja | **bien 1 de 2; hallazgo 1** | El diario: «se trae lo último de su llavero aunque no se sincroniza (en pausa)» y una pasada «(a petición)» que trae la entrada del remoto. **La primera vez prdrive no abrió KeePassXC** («El fichero llave de este dispositivo no abre la base del llavero…»); la segunda, sí, con la entrada. |
| **A4 / B5** El navegador con el instalado integrado (Firefox) | **bien** | Instalado → su JSON en `%LOCALAPPDATA%\KeePassXC`. «Abrir llavero» → las cuatro claves a `F:\.prdrive\keepassxc\…`. Cerrar → Mozilla vuelve al JSON del instalado (`…_firefox.json`); Chrome, Edge y Chromium se borran (el instalado no tenía JSON para ellos). |
| A4 · variante: cerrar el llavero a mano, arrancar el instalado, «Expulsar» | **bien** | El instalado, al arrancar, se queda con las cuatro claves (también las de navegadores que no tenía activados). «Expulsar» no las toca ni dice nada. |
| **A3** La base del llavero en el **KeePassXC instalado** | **bien; hallazgos 3 y 4** | Se abre solo con `llave.keyx` (contraseña vacía), tras el aviso «Formato de archivo de clave antiguo». Una entrada nueva se sube a los 22 s (`keychain (han cambiado sus ficheros)`). No aparece ningún `.old.kdbx`. Sin la traída cada 5 min (solo cuenta el KeePassXC de la unidad). «Abrir llavero» lo trata como «otro KeePassXC». |
| A3 · «Expulsar» con el instalado teniendo abierta la base de `F:` | **hallazgo 3** | `--cerrar-llavero` sale con 0 sin decir nada. |
| A3 · la base en **KeePass 2.61** | **no hecha** | No cogió `-keyfile:` de la orden y su diálogo no respondía a la herramienta. Se canceló sin tocar nada. |
| **KP3** Un byte de `keepassxc-proxy.exe` | **bien; hallazgo 6** | «No se ha podido abrir KeePassXC: El KeePassXC de la unidad no es el oficial (keepassxc-proxy.exe no es el de la versión 2.7.12), así que no se ha lanzado nada de él. Pulsa «Actualizar…»…». Ni configuración ni registro tocados; `state/keepassxc-no-oficial.json` con el fichero. La ventana: «KeePassXC del llavero: lleva 2.7.12 (con ficheros que no cuadran), toca 2.7.12». «Actualizar…» repone el paquete desde la caché del instalador, comprobado, en 125 s, y borra el apunte. |
| KP3 · un byte de `KeePassXC.exe`, devuelto a mano | **bien** | El mismo aviso y apunte. Devuelto el fichero a mano sigue pendiente (como dice `llavero.md`); «Actualizar…» dice «KeePassXC 2.7.12 ya está en la unidad», no copia nada (2 s) y se apaga el aviso. |
| «Abrir llavero» desde la ventana | **bien** | La ventana deja al agente en pausa («runsync ha pedido parar el servicio») y el llavero lo atiende el vigilante: «[llavero] vigilante iniciado», «OK (lo de otro dispositivo, con KeePassXC abierto, 5s)». Al cerrar la ventana: «sin ventana de runsync; vuelvo a atenderla». |

## 3. Hallazgos

1. **«Abrir llavero» desde la bandeja con las pasadas retenidas puede decir que la llave no vale** (llavero sin contraseña). `Agente._lanzar_llavero()` lanza `runsync.py --llavero` y en el mismo momento encola la pasada urgente (`_traer_al_abrir()`). `--llavero` prueba la llave (`keepassxc.llave_vale()`: `keepassxc-cli ls --no-password --key-file`) mientras esa pasada aparta la base a `.prversions/` para bajar la del remoto (`Database~20261019-135817.kdbx`, el mismo segundo que «abriendo su llavero»). `llave_vale()` toma **cualquier** código distinto de 0 como `False`, también «no encuentro el fichero», y `mirar_apertura()` para con `LLAVE_NO_VALE`. Salió 1 de 2 veces (la pasada que falló tardó 11 s; la otra, 4 s). Repetida la sonda a mano después, abre. Arreglos posibles: que `--llavero` espere al candado de bisync de la pareja antes de probar; que `llave_vale()` dé `None` si la base no está o no está entera (`kdbx.comprobar()`) o lo reintente tras `ESPERA_ENTERA`; o que el agente haga la pasada antes de lanzar.
2. **Una base ajena se queda en la configuración del pendrive.** Por la instancia única, abrir el KeePassXC instalado con el llavero abierto mete la otra base en el de la unidad. Su ruta queda en `keepassxc_local.ini` (`LastDatabases`, `LastOpenedDatabases`, `LastActiveDatabase`), **viaja con el pendrive** (una ruta del equipo, no su contenido) y **se reabre** en cada «Abrir llavero». `mover_raiz()` solo cambia las rutas de la raíz anterior. Arreglos posibles: que `ajustar_config()` deje en esas listas solo bases de `.keychain/`, o `RememberLastDatabases`/`OpenPreviousDatabasesOnStartup` a `false` (la base ya se pasa como argumento).
3. **«Expulsar» no ve otro programa con la base del llavero abierta.** `procesos_de_la_unidad()` solo mira el KeePassXC de la unidad; con el instalado (o KeePass) teniendo `F:\.keychain\Database.kdbx` abierta, `--cerrar-llavero` sale con 0 y la ventana diría «Ya puedes quitarla». Como mínimo, avisar si `otro_abierto()`.
4. **La llave del llavero sin contraseña es de «formato antiguo» para KeePassXC 2.7.12.** `generar_llave()` escribe 64 caracteres hex: `keepassxc-cli` lo avisa en cada uso («ATENCIÓN: Está usando un archivo llave con un formato antiguo…», también en la consola de «Combinar») y la ventana una vez por configuración («Formato de archivo de clave antiguo», con «No mostrar nuevamente»; el pendrive no lo enseña porque su `keepassxc.ini` ya tiene `NoLegacyKeyFileWarning=true`, que prdrive no pone). El formato XML 2.0 de KeePassXC (que KeePass 2 también lee) guarda los mismos 32 bytes, así que convertirlo no cambiaría la clave de la base (**a comprobar** antes de tocar nada).
5. **Texto:** la espera de «Combinar» dice «escribe allí la contraseña de la base» (`conflict_editor.ESPERANDO_CONSOLA`) también sin contraseña, justo después de un plan que dice «no pide contraseña».
6. **Texto:** el recuadro de la ventana («Lo que lleva el dispositivo de fuera (rclone, Python, VeraCrypt)…») y el diálogo «Los componentes del dispositivo están anticuados» (rclone.org, python-build-standalone, IDRIX) no nombran KeePassXC, que es lo único que se repone, y llaman «anticuado» a un fichero que no cuadra.
7. **Diario:** con la bandeja en pausa, la pasada urgente apunta «se vuelve a sincronizar» y en seguida «no se lanza nada: en pausa».

No son de prdrive: KeePassXC se protege de las capturas de pantalla (para probar con capturas hay que usar UI Automation); los clics
rápidos de la herramienta no llegaban a los botones de Tk ni de KeePass (con pulsar y soltar despacio, sí); y una ventana que salió
minimizada al abrir con `Start-Process` desde una consola oculta no se repitió por la bandeja.

## 4. Lo que no se hizo

- **La passkey en el navegador** (webauthn.io con Firefox): la herramienta solo puede mirar los navegadores, no pulsar en ellos. Se
  comprobó todo hasta la extensión: claves, manifiestos, el tubo `org.keepassxc.KeePassXC.BrowserServer_<usuario>` y el proxy.
- KeePass 2 (A3), **KP1** (hay que desenchufar y volver a enchufar), la mitad NTFS de **KP2**, y de KR1 desbloquear antes de que acabe
  la pasada (sin contraseña se desbloquea al instante: es el hallazgo 1).

## 5. Cómo queda el equipo

- La base del llavero es **la original**, byte a byte, en la unidad y en el remoto (SHA-256 `07a56b28…`, subida a las 14:26). Las
  versiones de las pruebas, con las entradas `prdrive-prueba-B-local`, `-KR1-remoto` y `-A3-instalado`, quedan en los `.prversions/`:
  en el remoto `…conflicto-dispositivo1~20261019-135612`, `Database~20261019-135612`, `~140744` y `~142605`; en la unidad
  `…conflicto-dispositivo1~20261019-135600`, `Database~20261019-135817` y `~135941`.
- Devueltas a su estado del principio: la configuración del KeePassXC de la unidad, las del instalado (fuera los siete JSON del
  navegador que creó al activarlo), las claves del navegador y `llavero-navegador.json`. La otra base no ha cambiado.
- El agente atiende la unidad, sin pausa. El paquete KeePassXC de la unidad es el oficial (repuesto por «Actualizar…»).
- El portapapeles tiene una ruta (la herramienta escribe por él) y una ventana del Explorador quedó minimizada.
- La copia de seguridad de las pruebas sigue en el scratchpad de la sesión, **sin `llave.keyx`**.
