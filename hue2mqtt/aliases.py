"""Generate an alias config section from the names stored on the Hue Bridge."""
import re
from collections import Counter
from typing import Iterable, List, Tuple

from .config import ALIAS_REGEX

# Group types that are created by the user in the Hue app.
USER_GROUP_TYPES = ("Room", "Zone")

_FORBIDDEN = re.compile(r"[/+#$\s]+")
_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def sanitise_alias(name: str) -> str:
    """Turn a name from the Hue Bridge into a valid MQTT topic level."""
    return _FORBIDDEN.sub("_", name.strip()).strip("_")


def _toml_key(key: str) -> str:
    """Quote a TOML key if it cannot be written as a bare key."""
    if _BARE_KEY.match(key):
        return key
    escaped = key.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _section(
    header: str,
    entries: List[Tuple[str, str, str]],
) -> List[str]:
    """
    Render one TOML table.

    Each entry is the alias, the TOML value and a reason to skip the entry.
    Skipped entries are written as comments, so they can be fixed by hand.
    """
    counts = Counter(alias for alias, _, skip in entries if not skip)
    lines = [header]
    for alias, value, skip in entries:
        line = f"{_toml_key(alias)} = {value}"
        if not skip and not ALIAS_REGEX.match(alias):
            skip = "no usable name"
        if not skip and counts[alias] > 1:
            skip = "duplicate name, choose distinct aliases"
        lines.append(f"# {line}  # {skip}" if skip else line)
    return lines


def render_aliases(
    lights: Iterable[Tuple[str, str]],
    groups: Iterable[Tuple[str, str, str]],
) -> str:
    """
    Render the alias section of the config file.

    :param lights: name and uniqueid of every light.
    :param groups: name, id and type of every group.
    """
    light_entries = [
        (sanitise_alias(name), f'"{uniqueid}"', "") for name, uniqueid in lights
    ]
    group_entries = [
        (
            sanitise_alias(name),
            group_id if group_id.isdigit() else f'"{group_id}"',
            "" if group_type in USER_GROUP_TYPES else f"group of type {group_type}",
        )
        for name, group_id, group_type in groups
    ]
    lines = _section("[alias.light]", light_entries)
    lines.append("")
    lines.extend(_section("[alias.group]", group_entries))
    return "\n".join(lines) + "\n"
