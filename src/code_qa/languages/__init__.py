"""Language-profile registry. Add a language = add a profile here."""

from __future__ import annotations

from pathlib import Path

from .base import LanguageProfile
from .java_profile import JavaProfile
from .python_profile import PythonProfile

_PROFILES: list[LanguageProfile] = [PythonProfile(), JavaProfile()]
_BY_EXT: dict[str, LanguageProfile] = {ext: p for p in _PROFILES for ext in p.extensions}


def profile_for(relpath: str) -> LanguageProfile | None:
    return _BY_EXT.get(Path(relpath).suffix.lower())


def supported_extensions() -> set[str]:
    return set(_BY_EXT)
