[← Guías](README.md)

# El llavero

Tus contraseñas y tus **passkeys** en una base de KeePassXC que viaja en la
unidad y se sincroniza sola con el remoto. Entras en GitHub (y en cualquier sitio
que acepte passkeys) desde cualquier equipo donde abras la unidad, sin instalar
nada.

> **Sin probar todavía en un equipo de verdad.** Está hecho a partir de pruebas
> con KeePassXC 2.7.12 en un Windows ARM, pero el llavero entero (abrirlo,
> combinar, expulsar, el navegador en un equipo nuevo) no se ha probado aún en
> hardware real. De momento **solo se abre en Windows** (x64, y ARM64 con el
> KeePassXC de x64); en Linux se sincroniza, pero no se abre.

## Qué es, en corto

- **KeePassXC viaja dentro de la unidad**, en `.prdrive/keepassxc/`. prdrive lo
  descarga, lo comprueba y lo pone al día como rclone.
- **La base vive en `.keychain/`**, en la raíz de la unidad, oculta. Una sola
  base, con el nombre que traiga.
- **Se sincroniza sola** con la carpeta `keychain/` que hay junto al catálogo, en
  el remoto. No es una pareja: no sale en «Parejas» y no hay nada que configurar.
- **La base la cifra KeePassXC**, con tu contraseña. prdrive no la ve nunca.

## Activarlo

**Al preparar la unidad**, el asistente tiene un paso «Llavero», después de las
parejas. Es opcional. **En una unidad que ya funciona**, en la ventana de
prdrive: **Ajustes → Llavero…**.

- **Usar una base propia** (en «Ajustes», **Usar esta base…**): eliges tu
  `.kdbx` y se **copia** a la unidad. La original se queda donde estaba, sin
  tocar, y **desde ahora la buena es la de la unidad**.
- **Traer el del remoto**: si otro dispositivo tuyo ya lo activó. La primera
  pasada baja la base.

Si el remoto ya tiene un llavero y das una base tuya, la tuya entra como **copia
de conflicto** de la del remoto, y al abrir el llavero se te ofrece
**combinarlas** (ver abajo): no se pierde nada de ninguna.

Si la unidad aún no lleva KeePassXC, la ventana lo dice con el recuadro naranja
de siempre: **Actualizar…** lo pone.

### El fichero llave

Si tu base se abre con contraseña **y** un fichero llave, dilo al activarlo.
prdrive **no copia, no lee ni guarda nada del fichero llave**: solo apunta
**dónde está en cada equipo**, y se lo pasa a KeePassXC para que no tengas que
buscarlo. En un equipo donde no se ha dicho, te lo pregunta la primera vez.

En una unidad sin cifrar, esa ruta se puede leer: dice dónde está tu fichero
llave en cada equipo, no qué tiene.

## Cada día

**Abrir llavero**, en la ventana de prdrive, o doble clic en **`Llavero.bat`**,
en la raíz de la unidad.

1. Si hace rato de la última pasada, trae lo último del remoto.
2. Abre KeePassXC con tu base (y el fichero llave ya puesto, si lo usas).
3. Escribes la contraseña, y los sitios piden la passkey y KeePassXC firma.

Lo que guardas **sube solo**, unos 20 segundos después del último cambio. Lo que
cambies en otro dispositivo llega en **5 minutos** como mucho mientras KeePassXC
esté abierto, y siempre al pulsar «Abrir llavero».

Si KeePassXC ya está abierto, «Abrir llavero» lo trae delante. Si en el equipo hay
**otro KeePassXC** abierto (uno instalado), te pide que lo cierres antes.

### El navegador

En cada navegador, **una vez por perfil**: instala la extensión
**KeePassXC-Browser**, pulsa «Conectar» y activa **«Enable Passkeys»**. La
conexión se guarda en la base, así que viaja con ella.

En un equipo nuevo no hay que configurar nada más: prdrive apunta el navegador al
KeePassXC de la unidad al abrirlo, y lo deja como estaba al expulsar (o vuelve a
apuntarlo al KeePassXC instalado del equipo, si lo hay).

### Si KeePassXC no arranca

Si dice que falta el **runtime de Visual C++**, es que el equipo no lo tiene y
KeePassXC no lo lleva consigo. Instalarlo pide un administrador; el instalador
oficial de Microsoft es
[vc_redist.x64.exe](https://aka.ms/vs/17/release/vc_redist.x64.exe) (el de x64
también en Windows ARM).

## Si dos dispositivos cambiaron la base

Si guardaste en dos dispositivos sin que sincronizaran en medio, se queda la más
nueva y la otra queda al lado como copia de conflicto. **No hay que elegir**:
«Abrir llavero» te ofrece **Combinar** antes de abrir, y también está en
**Reparación**.

Combinar abre una consola de KeePassXC que te pide la contraseña de la base
(prdrive no la ve) y junta lo de las dos. La copia combinada va a
`.keychain/.prversions/`, por si acaso, y deja de viajar. Si no se puede combinar,
no se toca nada y se explica cómo hacerlo desde KeePassXC («Base de datos →
Combinar desde base de datos…»).

## Expulsar

**Expulsar**, en la ventana (también en una unidad sin cifrar, si lleva el
llavero), o **Expulsar PRDRIVE** en la raíz si va con VeraCrypt.

Si KeePassXC está abierto, te pregunta si cerrarlo; se cierra como si lo cerraras
tú, así que si tienes algo sin guardar, KeePassXC te lo pregunta. Lo que quede por
subir sube entonces, sin decir nada (si no puede, una línea: «se subirá la
próxima vez»). Después ya puedes quitar la unidad.

Si tiras del cable sin expulsar, la base no se estropea (KeePassXC guarda de
forma atómica), pero lo último puede no haber subido: sube la próxima vez.

## Ten cuidado con

- **Las exportaciones en claro.** Si exportas la base (CSV, por ejemplo), el
  fichero cae en la raíz de la unidad, a la vista. No viaja, pero bórralo cuando
  acabes.
- **No toques `.keychain/` a mano.** El `LEEME.txt` de dentro está ahí a
  propósito: con una sola base, sin él la sincronización creería que «ha cambiado
  todo».
- **YubiKey no**: de momento solo contraseña y fichero llave.

## Desactivarlo

**Ajustes → Llavero… → Desactivar…** Deja de sincronizarse en esta unidad. La
carpeta `.keychain/` (con tu base) y el remoto **no se tocan**: tus otros
dispositivos siguen con él.
