"""Features (#120): everything beyond the core is a switch on one options page.

The core is always on: heat source, rooms, schedules. A feature that is off has
no options page, no entities and no card section, and the integration ignores
its settings (they are kept, so switching it back on remembers them).

Systems from before the Features page have no feature keys: a feature counts
as on when it was in use (a presence entity set, a room with window sensors,
the learning features on), so an upgrade changes nothing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Final

from .const import CONF_EXPERIMENTAL, CONF_PRESENCE, CONF_WINDOWS

FEATURE_PRESENCE: Final = "feature_presence"  # presence and away
FEATURE_WINDOWS: Final = "feature_windows"
FEATURE_GUEST: Final = "feature_guest_mode"
FEATURE_LEARNING: Final = CONF_EXPERIMENTAL  # the existing option key, kept as is
FEATURES: Final = (FEATURE_PRESENCE, FEATURE_WINDOWS, FEATURE_GUEST, FEATURE_LEARNING)


def feature_on(settings: Mapping[str, Any], rooms: Iterable[Mapping[str, Any]], key: str) -> bool:
    if key in settings and settings[key] is not None:
        return bool(settings[key])
    if key == FEATURE_PRESENCE:
        return bool(settings.get(CONF_PRESENCE))
    if key == FEATURE_WINDOWS:
        return any(room.get(CONF_WINDOWS) for room in rooms)
    return False
