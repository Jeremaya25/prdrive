#!/usr/bin/env python3
"""
El estado de BitLocker, y quién tiene derecho a pasar de la pantalla de cifrado.

Esto era una consulta elevada: `Get-BitLockerVolume` a través de un
`Start-Process -Verb RunAs -WindowStyle Hidden`, que sobre un .exe sin firmar
corriendo desde %TEMP% tiene la forma exacta de un bypass de UAC —Sophos lo
paraba con su mitigación 'Lockdown'—. Ahora se lee sin elevar la propiedad
`System.Volume.BitLockerProtection`, la misma con la que el Explorador pinta el
candado.

Lo que se comprueba aquí NO es la lectura —eso lo contesta Windows y no hay nada
que probar sin un volumen cifrado delante—, sino la decisión que se toma con lo
leído, que es la parte peligrosa: encima de ese volumen se deja la clave privada
del remoto. Por eso la sonda es una función de módulo, `_leer_estado_bitlocker`,
y se sustituye; ningún test toca un dispositivo.
"""

from _harness import Checks, tmpdir

from install import crypto, device

c = Checks("BitLocker: estado y permiso para seguir")


def estado(valor):
    """`bitlocker_status` como si Windows hubiera contestado `valor`."""
    crypto.IS_WIN = True
    crypto._leer_estado_bitlocker = lambda ruta: valor
    return crypto.bitlocker_status("E")


win_original = crypto.IS_WIN
sonda_original = crypto._leer_estado_bitlocker
try:
    # --- Solo 'On' autoriza a seguir ----------------------------------------
    #
    # Ésta es la comprobación que habría cazado el fallo anterior. El código de
    # antes daba por bueno «FullyEncrypted, o porcentaje > 0» e ignoraba el
    # ProtectionStatus que la propia consulta pedía. Un volumen en 'Waiting for
    # activation' está cifrado, se lee sin problemas y tiene su clave guardada
    # EN CLARO esperando un reinicio: pasaba, y encima se le dejaba la clave
    # privada del remoto.
    c("'On' es el único que protege", estado(crypto.BDE_ON).protected, True)
    c("sin cifrar no pasa", estado(crypto.BDE_OFF).protected, False)
    c("cifrándose todavía no pasa", estado(crypto.BDE_ENCRYPTING).protected, False)
    c("descifrándose no pasa", estado(crypto.BDE_DECRYPTING).protected, False)
    c("con la protección suspendida no pasa",
      estado(crypto.BDE_SUSPENDED).protected, False)
    c("bloqueado no pasa", estado(crypto.BDE_LOCKED).protected, False)
    c("no cifrable no pasa", estado(crypto.BDE_NOT_ENCRYPTABLE).protected, False)
    c("«activado pero con la clave en claro» NO pasa",
      estado(crypto.BDE_WAITING).protected, False)

    # --- Todos los estados se saben decir en voz alta ------------------------
    for valor in sorted(crypto.BDE_TEXTOS):
        st = estado(valor)
        c(f"el estado {valor} se reconoce", st.known, True)
        c(f"y el {valor} tiene texto propio", st.resumen, crypto.BDE_TEXTOS[valor])

    # --- Lo que no se sabe se dice, no se supone ----------------------------
    #
    # `known=False` no es «no está cifrado»: es «no lo he mirado». La pantalla
    # solo deja avanzar con `protected`, así que cualquier fallo frena en vez de
    # dejar pasar, que es la dirección segura.
    desconocido = estado(99)
    c("un estado que Windows no documenta no se da por bueno", desconocido.known, False)
    c("y desde luego no protege", desconocido.protected, False)
    c.contains("y lo dice", desconocido.resumen, "sin comprobar")

    def revienta(ruta):
        raise OSError("IShellItem2::GetInt32: 0x80070490")

    crypto.IS_WIN = True
    crypto._leer_estado_bitlocker = revienta
    fallo = crypto.bitlocker_status("E")
    c("si la consulta falla, no se sabe", fallo.known, False)
    c("y no protege", fallo.protected, False)
    c.contains("con el motivo dentro", fallo.resumen, "0x80070490")

    crypto.IS_WIN = False
    fuera = crypto.bitlocker_status("E")
    c("fuera de Windows tampoco se inventa nada", fuera.known, False)
    c("ni protege", fuera.protected, False)
finally:
    crypto.IS_WIN = win_original
    crypto._leer_estado_bitlocker = sonda_original


# --- El tamaño de un volumen que Get-Volume devuelve a cero -----------------
#
# Un volumen BitLocker desbloqueado se lee perfectamente y aun así `Get-Volume`,
# sin elevar, lo devuelve con Size y SizeRemaining a cero: el dispositivo del
# propio usuario salía en la lista del asistente como «0 GB».
raiz = tmpdir("prdrive-vol-")
lleno = device._con_tamano(device.Volume(root=raiz, size=0, free=0))
c("un volumen a cero se completa mirando la ruta montada", lleno.size > 0, True)
c("y también su hueco libre", lleno.free > 0, True)

ya_tenia = device.Volume(root=raiz, size=123, free=45)
c("lo que ya venía con tamaño no se toca", device._con_tamano(ya_tenia), ya_tenia)

sin_medio = device.Volume(root=raiz / "no-existe", size=0, free=0)
c("una unidad sin medio dentro se queda a cero, no revienta",
  device._con_tamano(sin_medio).size, 0)

raise SystemExit(c.report())
