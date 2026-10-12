"""F24: quien pide el volumen en exclusiva lo consigue con la carpeta vigilada, y después se vuelve a oír (fila C4)."""

import time

import comun
from common import avisos_carpeta as ac
from common import expulsar

CODIGO = "F24"
SISTEMA = "W"
QUE = ("pedir el volumen en exclusiva (FSCTL_LOCK_VOLUME, chkdsk /f) con la vigilancia puesta: "
       "sale a la primera y la pareja vuelve a oírse (C4)")
K = ("u" * 32, "docs")
LECTURA_Y_ESCRITURA = 0xC0000000
FSCTL_UNLOCK_VOLUME = 0x0009001C
INTENTOS = 4
"""Los de `expulsar._expulsar_windows()`."""
NOMBRES = {ac.GUID_IO_VOLUME_LOCK: "LOCK", ac.GUID_IO_VOLUME_LOCK_FAILED: "LOCK_FAILED",
           ac.GUID_IO_VOLUME_UNLOCK: "UNLOCK", ac.GUID_IO_VOLUME_DISMOUNT: "DISMOUNT",
           ac.GUID_IO_VOLUME_MOUNT: "MOUNT"}


def bloquear(letra: str) -> tuple[int, float, tuple] | None:
    """Pide el volumen en exclusiva; devuelve en qué intento salió, lo que tardó y con qué soltarlo."""
    k32 = expulsar._kernel32()
    h = expulsar._abrir_volumen(k32, f"{letra}:", LECTURA_Y_ESCRITURA)
    if h is None:
        return None
    for intento in range(1, INTENTOS + 1):
        t = time.monotonic()
        if expulsar._ioctl(k32, h, expulsar.FSCTL_LOCK_VOLUME) is not None:
            return intento, (time.monotonic() - t) * 1000, (k32, h)
        time.sleep(0.5)
    k32.CloseHandle(h)
    return None


def soltar(con: tuple) -> None:
    """Suelta el bloqueo de `bloquear()`."""
    k32, h = con
    expulsar._ioctl(k32, h, FSCTL_UNLOCK_VOLUME)
    k32.CloseHandle(h)


def probar(p: comun.Prueba) -> None:
    """Bloquea y comprueba el disco con la carpeta vigilada, sin atender el aviso y atendiéndolo."""
    with comun.bandeja_windows() as (bandeja, llegados), comun.volumen_windows("ntfs") as raiz:
        if not comun.esperar(lambda: any(a[0] == comun.DBT_DEVICEARRIVAL for a in llegados), 10):
            raise comun.Saltada("esta máquina no entrega avisos de dispositivo a las ventanas "
                                "(sin escritorio interactivo)")
        letra, datos = str(raiz)[0], raiz / "datos"
        datos.mkdir()
        motor = ac.abrir(hwnd=bandeja.hwnd)

        def vuelve() -> bool:
            """Espera a que la carpeta vuelva a estar abierta; tocar el disco lo vuelve a montar."""
            return comun.esperar(lambda: raiz.exists() and motor.vigilancias() == 1, 20, 0.2)

        def guids() -> str:
            """Los avisos del volumen que han llegado a la ventana, por orden y sin repetir seguidos."""
            nombres = [NOMBRES.get(a[3], "") for a in llegados if a[0] == ac.DBT_CUSTOMEVENT]
            return " ".join(n for i, n in enumerate(nombres) if n and nombres[i - 1:i] != [n])

        try:
            p.ver("se vigila", motor.vigilar(K, datos, ()), None)
            # Sin atender el aviso: la carpeta abierta estorba.
            con = bloquear(letra)
            p.ver("sin atender el aviso, el bloqueo falla los cuatro intentos", con, None)
            if con is not None:
                soltar(con[2])
            r = comun.ejecutar(["chkdsk", f"{letra}:", "/f"], entrada="n\nn\n", timeout=300)
            p.nota(f"sin atender el aviso, chkdsk /f sale con {r.returncode}")
            # Atendiéndolo.
            bandeja.dispositivo = motor.dispositivo
            llegados.clear()
            comun.asentar(motor, 10)
            con = bloquear(letra)
            p.ver("atendiéndolo, el bloqueo sale al primer intento", con and con[0], 1)
            if con is not None:
                p.nota(f"el bloqueo tarda {con[1]:.0f} ms")
                p.ver("  con la carpeta suelta mientras dura", motor.vigilancias(), 0)
                soltar(con[2])
            p.ver("  y al soltarlo la pareja vuelve a oírse", vuelve(), True)
            p.ver("  contando como un cambio", comun.avisos(motor), {K: ac.CAMBIO})
            p.nota(f"avisos del bloqueo: {guids()}")
            (datos / "tras-bloqueo.txt").write_text("b", encoding="utf-8")
            p.ver("  y oye lo de después", comun.avisos(motor), {K: ac.CAMBIO})
            comun.asentar(motor, 10)
            llegados.clear()
            r = comun.ejecutar(["chkdsk", f"{letra}:", "/f"], entrada="n\nn\n", timeout=300)
            p.ver("atendiéndolo, chkdsk /f comprueba el disco sin encontrarlo en uso",
                  r.returncode, 0)
            p.ver("  y después la pareja vuelve a oírse", vuelve(), True)
            p.nota(f"avisos de chkdsk /f: {guids()}")
            comun.asentar(motor, 10)
            (datos / "tras-chkdsk.txt").write_text("c", encoding="utf-8")
            p.ver("  y oye lo de después", comun.avisos(motor), {K: ac.CAMBIO})
        finally:
            motor.cerrar()
            bandeja.dispositivo = None
