"""Test that we can load config files."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from hue2mqtt.config import AliasInfo, Hue2MQTTConfig, WatchdogInfo

LIGHT = "00:17:88:01:00:00:00:01-0b"
DATA_DIR = Path(__file__).resolve().parent.joinpath("data/configs")


def test_valid_config() -> None:
    """Test that we can load a valid config from a file."""
    with DATA_DIR.joinpath("valid.toml").open("rb") as fh:
        config = Hue2MQTTConfig.load_from_file(fh)
    assert config is not None


def test_defaults_without_alias() -> None:
    """Test that alias and watchdog sections are optional."""
    with DATA_DIR.joinpath("valid.toml").open("rb") as fh:
        config = Hue2MQTTConfig.load_from_file(fh)
    assert config.alias.light == {}
    assert config.alias.group == {}
    assert config.mqtt.client_id == "hue2mqtt"
    assert config.mqtt.publish_ids
    assert config.watchdog.max_runtime_hours is None
    assert config.watchdog.mqtt_disconnect_timeout == 60


def test_alias_config() -> None:
    """Test that we can load a config with aliases."""
    with DATA_DIR.joinpath("alias.toml").open("rb") as fh:
        config = Hue2MQTTConfig.load_from_file(fh)
    assert config.alias.light["Ceiling"] == "00:17:88:01:00:00:00:01-0b"
    # Group ids may be given as integers or strings
    assert config.alias.group == {"LivingRoom": "1", "Bath": "10"}
    assert config.alias.sensor == {"Switch": "00:17:88:01:00:00:00:07-02-fc00"}
    assert config.mqtt.client_id == "hue2mqtt-test"
    assert config.watchdog.max_runtime_hours == 48


@pytest.mark.parametrize("alias", ["", "a/b", "a b", "a+", "#", "$SYS"])
def test_alias_invalid_name(alias: str) -> None:
    """Test that aliases have to be valid topic levels."""
    with pytest.raises(ValidationError):
        AliasInfo(light={alias: LIGHT})
    with pytest.raises(ValidationError):
        AliasInfo.parse_obj({"group": {alias: 1}})


def test_alias_duplicate_target() -> None:
    """Test that a light or group can only have one alias."""
    with pytest.raises(ValidationError):
        AliasInfo(light={"a": LIGHT, "b": LIGHT})
    with pytest.raises(ValidationError):
        AliasInfo.parse_obj({"group": {"a": 1, "b": "1"}})


def test_alias_clashes_with_id() -> None:
    """Test that an alias cannot shadow the id of another group."""
    with pytest.raises(ValidationError):
        AliasInfo.parse_obj({"group": {"2": 1, "Bath": 2}})


@pytest.mark.parametrize("field", ["max_runtime_hours", "mqtt_disconnect_timeout"])
def test_watchdog_requires_positive(field: str) -> None:
    """Test that watchdog limits have to be greater than zero."""
    with pytest.raises(ValidationError):
        WatchdogInfo(**{field: 0})
