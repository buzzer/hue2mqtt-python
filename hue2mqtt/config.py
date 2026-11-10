"""
Configuration schema for Astoria.

Common to all components.
"""
import re
from pathlib import Path
from typing import IO, Dict, List, Optional

from pydantic import BaseModel, parse_obj_as, validator

# An alias becomes a single MQTT topic level, so separators, wildcards,
# the reserved "$" and whitespace are not allowed.
ALIAS_REGEX = re.compile(r"^[^/+#$\s]+$")

# Backwards compatibility for TOML in stdlib from Python 3.11
try:
    import tomllib  # type: ignore[import,unused-ignore]
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[import,no-redef,unused-ignore]


class HueBridgeInfo(BaseModel):
    """MQTT Broker Information."""

    ip: str
    username: str
    # Group types that are not published, e.g. "LightGroup" for the groups
    # that the bridge creates on its own. They can still be controlled.
    ignore_group_types: List[str] = []

    class Config:
        """Pydantic config."""

        extra = "forbid"


class MQTTBrokerInfo(BaseModel):
    """MQTT Broker Information."""

    host: str
    port: int
    enable_auth: bool = False
    username: str = ""
    password: str = ""
    enable_tls: bool = False
    topic_prefix: str = "hue2mqtt"
    force_protocol_version_3_1: bool = False
    client_id: str = "hue2mqtt"
    # Publish on the uniqueid / group id topics. Aliased topics are always published.
    publish_ids: bool = True

    class Config:
        """Pydantic config."""

        extra = "forbid"


def _check_aliases(aliases: Dict[str, str], kind: str) -> None:
    """Check that aliases are valid topic levels and point to distinct targets."""
    seen: Dict[str, str] = {}
    for alias, target in aliases.items():
        if not ALIAS_REGEX.match(alias):
            raise ValueError(
                f"Invalid {kind} alias {alias!r}: "
                "must not be empty or contain whitespace, '/', '+', '#' or '$'",
            )
        if target in seen:
            raise ValueError(
                f"{kind.capitalize()} {target} has more than one alias: "
                f"{seen[target]!r} and {alias!r}",
            )
        seen[target] = alias
    clashes = sorted(set(aliases) & set(seen))
    if clashes:
        raise ValueError(f"{kind.capitalize()} alias clashes with an id: {clashes[0]!r}")


class AliasInfo(BaseModel):
    """Human readable names for lights, groups and sensors, used in MQTT topics."""

    # alias -> light uniqueid
    light: Dict[str, str] = {}
    # alias -> group id
    group: Dict[str, str] = {}
    # alias -> sensor uniqueid
    sensor: Dict[str, str] = {}

    class Config:
        """Pydantic config."""

        extra = "forbid"

    @validator("group", pre=True)
    def _group_ids_as_str(cls, value: object) -> object:
        """Allow group ids to be written as integers in the config file."""
        if isinstance(value, dict):
            return {
                k: str(v) if isinstance(v, int) and not isinstance(v, bool) else v
                for k, v in value.items()
            }
        return value

    @validator("light")
    def _check_light(cls, value: Dict[str, str]) -> Dict[str, str]:
        _check_aliases(value, "light")
        return value

    @validator("group")
    def _check_group(cls, value: Dict[str, str]) -> Dict[str, str]:
        _check_aliases(value, "group")
        return value

    @validator("sensor")
    def _check_sensor(cls, value: Dict[str, str]) -> Dict[str, str]:
        _check_aliases(value, "sensor")
        return value


class WatchdogInfo(BaseModel):
    """
    Conditions on which Hue2MQTT exits, so that a supervisor can restart it.

    Restarting is more reliable than trying to recover a stale connection.
    """

    # Exit after this many hours. Disabled if not set.
    max_runtime_hours: Optional[float] = None
    # Exit if the MQTT broker has been unreachable for this many seconds.
    mqtt_disconnect_timeout: float = 60

    class Config:
        """Pydantic config."""

        extra = "forbid"

    @validator("max_runtime_hours", "mqtt_disconnect_timeout")
    def _check_positive(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and value <= 0:
            raise ValueError("must be greater than zero")
        return value


class Hue2MQTTConfig(BaseModel):
    """Config schema for Hue2MQTT."""

    mqtt: MQTTBrokerInfo
    hue: HueBridgeInfo
    alias: AliasInfo = AliasInfo()
    watchdog: WatchdogInfo = WatchdogInfo()

    class Config:
        """Pydantic config."""

        extra = "forbid"

    @classmethod
    def _get_config_path(cls, config_str: Optional[str] = None) -> Path:
        """Check for a config file or search the filesystem for one."""
        config_search_paths = [
            Path("hue2mqtt.toml"),
            Path("/etc/hue2mqtt.toml"),
        ]
        if config_str is None:
            for path in config_search_paths:
                if path.exists() and path.is_file():
                    return path
        else:
            path = Path(config_str)
            if path.exists() and path.is_file():
                return path
        raise FileNotFoundError("Unable to find config file.")

    @classmethod
    def load(cls, config_str: Optional[str] = None) -> "Hue2MQTTConfig":
        """Load the config."""
        config_path = cls._get_config_path(config_str)
        with config_path.open("rb") as fh:
            return cls.load_from_file(fh)

    @classmethod
    def load_from_file(cls, fh: IO[bytes]) -> "Hue2MQTTConfig":
        """Load the config from a file."""
        return parse_obj_as(cls, tomllib.load(fh))
