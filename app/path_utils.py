"""Platform-portable path helpers for ME4-YouTube response contracts.

Background
----------
The YouTube service runs on a Linux/WSL backend while the Baustein UI
(ME4-UI) runs in the user's Windows browser.  The service emits absolute
POSIX paths like::

    /mnt/d/DEV/wt-me4-yt-paths-open/data/sessions/<sid>/results/\
        <sid>.<NN>result.html

The Windows-UI cannot open those paths directly: it expects them in the
``D:\\...`` form (or as ``file:///D:/...``).  This module provides
the platform-aware translation so the same response contract works for
both clients.

Settings
--------
* ``settings.windows_path_translation`` (default: ``False``) controls
  whether ``to_platform_path`` rewrites ``/mnt/<drive>/...`` to
  ``<drive>:\\...`` automatically.  Override via env var
  ``WINDOWS_PATH_TRANSLATION=true`` or via ``.env``.

Translation rules
-----------------
1. ``/mnt/<drive>/<rest>``  with ``windows=True`` (or the setting on) ->
   ``<DRIVE>:\\<rest-with-backslashes>``.
2. Anything else (including ``/tmp/...`` when the setting is on, or any
   non-WSL POSIX path) -> ``Path.as_posix()`` (POSIX form).  We do NOT
   try to translate ``/tmp`` or other Linux paths because the Windows
   UI cannot open them anyway; showing the same string twice would
   just confuse the user.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.config import settings

# Anchor: leading ``/mnt/<drive-letter>/`` where <drive> is exactly one
# ASCII letter.  Followed by the rest of the path (no leading slash).
_WSL_MOUNT_RE = re.compile(r"^/mnt/([a-zA-Z])/(.*)$")


def to_platform_path(
    p: Path | str,
    *,
    windows: bool | None = None,
) -> str:
    """Return a UI-friendly string for the given filesystem path.

    Resolution order:
      1. If ``windows`` is not ``None`` it takes precedence.
      2. Otherwise the effective value is
         ``settings.windows_path_translation``.
      3. If the effective value is truthy AND the absolute POSIX path
         begins with ``/mnt/<drive>/``, the result is the Windows
         equivalent ``<DRIVE>:\\<rest-with-backslashes>``.
      4. Otherwise the result is ``Path(p).resolve().as_posix()``.

    Args:
        p: Any path-like value (Path, str, bytes are coerced via Path).
        windows: Optional override for the translation flag.  ``None``
            (default) means "use the global setting".

    Returns:
        The platform-appropriate string.  Always absolute; uses forward
        slashes (POSIX form) or backslashes (Windows form) depending on
        the resolved mode.

    Examples:
        >>> to_platform_path("/mnt/d/DEV/foo/x.json")
        '/mnt/d/DEV/foo/x.json'                 # Linux, setting off
        >>> to_platform_path("/mnt/d/DEV/foo/x.json", windows=True)
        'D:\\\\DEV\\\\foo\\\\x.json'            # backslashes
        >>> to_platform_path("/tmp/foo/x.json", windows=True)
        '/tmp/foo/x.json'                       # non-WSL -> POSIX fallback
    """
    abs_path = Path(p).resolve()
    posix = abs_path.as_posix()

    if windows is None:
        effective = bool(settings.windows_path_translation)
    else:
        effective = bool(windows)

    if effective:
        m = _WSL_MOUNT_RE.match(posix)
        if m:
            drive = m.group(1).upper()
            rest = m.group(2).replace("/", "\\")
            return f"{drive}:\\{rest}"
    return posix


def to_file_uri(path_str: str) -> str:
    """Convert a (possibly Windows-form) path-string to a ``file://`` URI.

    Rules:
      * Backslashes are converted to forward-slashes.
      * If the path begins with a Windows drive letter ``<D>:\\...`` (or
        its forward-slash form ``<D>:/...``), the result uses the
        three-slash ``file:///`` scheme: ``file:///D:/...``.
      * Otherwise an absolute POSIX path gets the standard two-slash
        scheme: ``file:///tmp/...``.

    Args:
        path_str: Any path-string.  Empty / non-string values raise
            ``TypeError``.

    Returns:
        A valid ``file://`` URI string suitable for ``<a href>`` in the
        browser.

    Examples:
        >>> to_file_uri("D:\\\\DEV\\\\foo\\\\x.html")
        'file:///D:/DEV/foo/x.html'
        >>> to_file_uri("/tmp/foo/x.json")
        'file:///tmp/foo/x.json'
    """
    if not isinstance(path_str, str):
        raise TypeError(f"to_file_uri expected str, got {type(path_str).__name__}")
    # Normalize backslashes -> forward-slashes.
    normalized = path_str.replace("\\", "/")
    # Windows drive letter: 'D:/...' or 'D:' alone.
    if (
        len(normalized) >= 3
        and normalized[1] == ":"
        and normalized[0].isalpha()
    ):
        # file:///D:/...   (three slashes so the URI is absolute)
        return f"file:///{normalized}"
    if normalized.startswith("/"):
        return f"file://{normalized}"
    return f"file://{normalized}"
