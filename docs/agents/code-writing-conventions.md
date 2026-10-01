# Code Writing Convention

This convention applies when creating or modifying Python code.

Internal documentation explains the current contract and intent of the code; it does not narrate its history.

This document is written in English, but code comments, docstrings, and
user-facing output remain in Spanish, as required by the repository convention.

## Docstrings

Use triple double quotes and the Google style. Write code docstrings in Spanish,
with a clear summary on the first line and a blank line before the sections.

Document the contract a reader or caller needs to know:

- `Args:`: each relevant argument, including its effects or constraints.
- `Returns:`: the returned value and the meaning of special cases such as
  `None` or an empty collection.
- `Yields:`: the value produced on each iteration of a generator.
- `Raises:`: exceptions that are part of the function's contract.
- `Attributes:`: public class attributes that are not constructor arguments.

Do not repeat a type that is already clear from the signature annotation unless
the docstring needs to explain its meaning. Do not include empty sections or
document internal exceptions that callers cannot reasonably handle.

```python
def leer_nota(ruta: Path, *, estricto: bool = False) -> Nota | None:
    """Lee una nota guardada en JSON.

    Args:
        ruta: Fichero que contiene la nota.
        estricto: Si se da, un fichero incompleto produce un error.

    Returns:
        La nota leída, o `None` si el fichero no existe y no se exige el modo
        estricto.

    Raises:
        OSError: Si no se puede leer el fichero.
        ValueError: Si el contenido no es una nota válida en modo estricto.
    """
```

The summary must describe what the symbol does now. If a function has effects
on disk, the network, processes, windows, or shared state, describe them when
they are not obvious from the signature.

Simple functions and methods do not need a docstring that merely repeats their
name. Modules, classes, entry points, functions with a non-trivial contract,
and test-replaceable indirection points do need one.

## Data Classes

The class docstring explains what the class represents. For a data class whose
fields are constructor arguments, describe them in an `Args:` block beside the
class:

```python
class Preparado:
    """Datos preparados para arrancar el agente.

    Args:
        codigo: La carpeta `agente/<versión>/` con el código.
        python: El intérprete sin consola del runtime.
        sello: El sello del runtime (de qué archivo salió).
        rclone: El binario `rclone` si hace falta (rclone/<versión fijada>/rclone).
        veracrypt: El binario `veracrypt` si hace falta (veracrypt/<versión fijada>/).
    """

    codigo: Path
    python: Path
    sello: str
    rclone: Path | None = None
    veracrypt: Path | None = None
```

Do not distribute that contract among comments beside each attribute:

```python
class Preparado:
    codigo: Path                 # agente/<versión>/
    python: Path                 # el intérprete sin consola del runtime
    sello: str                   # el sello del runtime (de qué archivo salió)
    rclone: Path | None = None   # rclone/<versión fijada>/rclone: el que pasa a sus hijos
    veracrypt: Path | None = None  # veracrypt/<versión fijada>/: el suyo, si hace falta
```

Attribute comments fragment the explanation and usually repeat information
that belongs in the class docstring.

## Variables and Constants

Put a docstring immediately after an assignment when the variable represents a
feature, policy, or contract that is not clear from its name and value alone:

```python
NO_COPIAR = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
"""Patrones de ficheros que se ignoran al copiar el código."""
```

This is especially useful for module constants, tables, and configuration
values reused by other functions. Do not replace that explanation with a `#`
comment.

A short comment is enough for a local indication such as a unit:

```python
PARAR_ESPERA = 12.0  # segundos
```

If the policy needs more explanation than the unit, keep the short comment and
add the variable docstring on the following line.

## Comments

Use `#` for a brief, local note: units, a platform condition, an immediate
constraint, or the reason for a non-obvious line. The comment should make the
code easier to read without duplicating it.

A multi-line comment should preserve only a stable rationale that cannot be
expressed better with names, types, or a docstring. In code that mirrors rclone,
VeraCrypt, the kernel, or a specification, preserve the technical citations
required by the module.

Prefer this form:

```python
# Instalador contiene el código que irá en el dispositivo.
```

Avoid long explanations, details of an earlier implementation, and change
narratives. If a comment needs a story to be understood, move the relevant
information into the symbol's docstring or improve the code's names.

## Review

Before finishing a Python change, check that:

- Code documentation is in Spanish.
- Every non-trivial contract has a summary and the Google sections it needs.
- `Args`, `Returns`, `Yields`, and `Raises` describe meaning, not repeated types
  or empty sections.
- Constants with implicit functionality have their docstring immediately after
  the assignment.
- `#` comments are short, local, and do not describe obsolete functionality.
- Existing technical citations have been preserved.
