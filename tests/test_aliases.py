"""Test generating the alias config section."""

try:
    import tomllib  # type: ignore[import,unused-ignore]
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[import,no-redef,unused-ignore]

import pytest

from hue2mqtt.aliases import render_aliases, sanitise_alias
from hue2mqtt.config import AliasInfo

LIGHTS = [
    ("Ceiling", "00:17:88:01:00:00:00:01-0b"),
    ("Bath1", "00:17:88:01:00:00:00:02-0b"),
    ("Bath1", "00:17:88:01:00:00:00:03-0b"),
    ("Küche Fenster", "00:17:88:01:00:00:00:04-0b"),
]

GROUPS = [
    ("Living Room", "1", "Room"),
    ("Custom group for $lights", "6", "LightGroup"),
    ("Upstairs", "7", "Zone"),
]


@pytest.mark.parametrize(
    ("name", "alias"),
    [
        ("Ceiling", "Ceiling"),
        ("Ricis Zimmer", "Ricis_Zimmer"),
        (" Group group51 ", "Group_group51"),
        ("a/b+c#d", "a_b_c_d"),
        ("$lights", "lights"),
        ("Küche", "Küche"),
    ],
)
def test_sanitise_alias(name: str, alias: str) -> None:
    """Test that names become valid topic levels."""
    assert sanitise_alias(name) == alias


def test_render_aliases() -> None:
    """Test the rendered config section."""
    assert render_aliases(LIGHTS, GROUPS).splitlines() == [
        "[alias.light]",
        'Ceiling = "00:17:88:01:00:00:00:01-0b"',
        '# Bath1 = "00:17:88:01:00:00:00:02-0b"'
        "  # duplicate name, choose distinct aliases",
        '# Bath1 = "00:17:88:01:00:00:00:03-0b"'
        "  # duplicate name, choose distinct aliases",
        '"Küche_Fenster" = "00:17:88:01:00:00:00:04-0b"',
        "",
        "[alias.group]",
        "Living_Room = 1",
        "# Custom_group_for_lights = 6  # group of type LightGroup",
        "Upstairs = 7",
    ]


def test_render_aliases_is_valid_config() -> None:
    """Test that the rendered section can be loaded as config."""
    data = tomllib.loads(render_aliases(LIGHTS, GROUPS))
    alias = AliasInfo(**data["alias"])
    assert alias.light == {
        "Ceiling": "00:17:88:01:00:00:00:01-0b",
        "Küche_Fenster": "00:17:88:01:00:00:00:04-0b",
    }
    assert alias.group == {"Living_Room": "1", "Upstairs": "7"}


def test_render_aliases_unusable_name() -> None:
    """Test that a light without a usable name is commented out."""
    lines = render_aliases([("  ", "00:17:88:01:00:00:00:01-0b")], []).splitlines()
    assert lines[1].startswith("# ")
    assert lines[1].endswith("# no usable name")
