"""Test topic handling and the watchdog of the bridge."""

import asyncio
import re
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Match, Tuple

import pytest
from pydantic import BaseModel

from hue2mqtt.hue2mqtt import Hue2MQTT
from hue2mqtt.schema import GroupInfo, LightInfo, SensorInfo

DATA_DIR = Path(__file__).resolve().parent.joinpath("data/configs")

CEILING = "00:17:88:01:00:00:00:01-0b"
UNALIASED = "00:17:88:01:00:00:00:09-0b"


class FakeMQTT:
    """Records published messages instead of sending them."""

    def __init__(self) -> None:
        self.is_connected = True
        self.published: List[Tuple[str, bool]] = []

    def publish(self, topic: str, payload: BaseModel, *, retain: bool = False) -> None:
        """Record a message."""
        self.published.append((topic, retain))

    @property
    def topics(self) -> List[str]:
        """The topics that have been published to."""
        return [topic for topic, _ in self.published]


class FakeItem:
    """A light or group on the fake bridge."""

    def __init__(self, name: str, uniqueid: str = "") -> None:
        self.name = name
        self.uniqueid = uniqueid
        self.calls: List[Dict[str, Any]] = []

    async def set_state(self, **kwargs: Any) -> None:
        """Record a state change of a light."""
        self.calls.append(kwargs)

    async def set_action(self, **kwargs: Any) -> None:
        """Record a state change of a group."""
        self.calls.append(kwargs)


class FakeBridge:
    """A bridge with two lights and one group."""

    def __init__(self) -> None:
        self.lights = {
            "4": FakeItem("Ceiling", CEILING),
            "5": FakeItem("Other", UNALIASED),
        }
        self.groups = {"1": FakeItem("Living Room")}


class App(Hue2MQTT):
    """The app without signal handlers, which need the module level event loop."""

    def _setup_event_loop(self) -> None:
        pass


CONFIG_FILE = str(DATA_DIR.joinpath("alias.toml"))


def make_app(*, publish_ids: bool = True) -> Tuple[Hue2MQTT, FakeMQTT, FakeBridge]:
    """Create the app with a fake broker and bridge."""
    app = App(verbose=False, config_file=CONFIG_FILE, welcome_message=False)
    app.config.mqtt.publish_ids = publish_ids
    mqtt = FakeMQTT()
    bridge = FakeBridge()
    app._mqtt = mqtt  # type: ignore[assignment]
    app._bridge = bridge
    return app, mqtt, bridge


def make_light(uniqueid: str) -> LightInfo:
    """Create a light as published to MQTT."""
    return LightInfo.parse_obj(
        {
            "id": 4,
            "name": "Ceiling",
            "uniqueid": uniqueid,
            "state": {"on": True},
            "manufacturername": "Signify",
            "modelid": "LWB010",
            "productname": "Hue white lamp",
            "type": "Dimmable light",
            "swversion": "1.0",
        },
    )


def make_group(group_id: int) -> GroupInfo:
    """Create a group as published to MQTT."""
    return GroupInfo.parse_obj(
        {
            "id": group_id,
            "name": "Living Room",
            "lights": [4],
            "sensors": [],
            "type": "Room",
            "state": {"all_on": False, "any_on": True},
            "action": {"on": True},
        },
    )


def match(name: str) -> Match[str]:
    """Create a match as passed to the set handlers."""
    result = re.match("^(.+)$", name)
    assert result is not None
    return result


def test_client_id_from_config() -> None:
    """Test that the MQTT client id is taken from the config."""
    app = App(verbose=False, config_file=CONFIG_FILE, welcome_message=False)
    assert app._mqtt._client._client_id == "hue2mqtt-test"


def test_publish_light_alias_and_id() -> None:
    """Test that an aliased light is published on both topics."""
    app, mqtt, _ = make_app()
    app.publish_light(make_light(CEILING))
    assert mqtt.published == [("light/Ceiling", True), (f"light/{CEILING}", True)]


def test_publish_light_alias_only() -> None:
    """Test that the id topic can be turned off."""
    app, mqtt, _ = make_app(publish_ids=False)
    app.publish_light(make_light(CEILING))
    assert mqtt.topics == ["light/Ceiling"]


@pytest.mark.parametrize("publish_ids", [True, False])
def test_publish_light_without_alias(publish_ids: bool) -> None:
    """Test that a light without an alias is always published by its id."""
    app, mqtt, _ = make_app(publish_ids=publish_ids)
    app.publish_light(make_light(UNALIASED))
    assert mqtt.topics == [f"light/{UNALIASED}"]


def test_publish_group() -> None:
    """Test the topics of groups with and without an alias."""
    app, mqtt, _ = make_app()
    app.publish_group(make_group(1))
    app.publish_group(make_group(2))
    assert mqtt.topics == ["group/LivingRoom", "group/1", "group/2"]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["Ceiling", CEILING])
async def test_set_light(name: str) -> None:
    """Test that a light can be set by alias and by uniqueid."""
    app, _, bridge = make_app()
    await app.handle_set_light(match(name), '{"on": true, "bri": 100}')
    assert len(bridge.lights["4"].calls) == 1
    assert bridge.lights["4"].calls[0]["on"] is True
    assert bridge.lights["4"].calls[0]["bri"] == 100
    assert bridge.lights["5"].calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["LivingRoom", "1"])
async def test_set_group(name: str) -> None:
    """Test that a group can be set by alias and by id."""
    app, _, bridge = make_app()
    await app.handle_set_group(match(name), '{"on": false}')
    assert len(bridge.groups["1"].calls) == 1
    assert bridge.groups["1"].calls[0]["on"] is False


@pytest.mark.asyncio
async def test_set_unknown() -> None:
    """Test that unknown names are ignored."""
    app, _, bridge = make_app()
    await app.handle_set_light(match("Nope"), '{"on": true}')
    await app.handle_set_group(match("Nope"), '{"on": true}')
    assert bridge.lights["4"].calls == []
    assert bridge.groups["1"].calls == []


@pytest.mark.asyncio
async def test_watchdog_mqtt_disconnect() -> None:
    """Test that the watchdog fires when the broker stays unreachable."""
    app, mqtt, _ = make_app()
    app.config.watchdog.max_runtime_hours = None
    app.config.watchdog.mqtt_disconnect_timeout = 0.05
    task = asyncio.ensure_future(app._watchdog(interval=0.01))
    await asyncio.sleep(0.1)
    assert not task.done()

    mqtt.is_connected = False
    await asyncio.wait_for(task, 1)


@pytest.mark.asyncio
async def test_watchdog_recovers() -> None:
    """Test that a short disconnect does not fire the watchdog."""
    app, mqtt, _ = make_app()
    app.config.watchdog.max_runtime_hours = None
    app.config.watchdog.mqtt_disconnect_timeout = 0.2
    task = asyncio.ensure_future(app._watchdog(interval=0.01))
    mqtt.is_connected = False
    await asyncio.sleep(0.05)
    mqtt.is_connected = True
    await asyncio.sleep(0.3)
    assert not task.done()
    task.cancel()


@pytest.mark.asyncio
async def test_watchdog_max_runtime() -> None:
    """Test that the watchdog fires after the maximum runtime."""
    app, _, _ = make_app()
    app.config.watchdog.max_runtime_hours = 0.05 / 3600
    await asyncio.wait_for(app._watchdog(interval=0.01), 1)


class FakeCollection:
    """An empty aiohue collection."""

    _items: Dict[str, Any] = {}


class FakeEventBridge:
    """A bridge without objects, whose event stream can be ended."""

    def __init__(self) -> None:
        self.lights = FakeCollection()
        self.groups = FakeCollection()
        self.sensors = FakeCollection()
        self.end = asyncio.Event()

    async def listen_events(self) -> AsyncIterator[Any]:
        """Wait until the stream is ended, without yielding events."""
        await self.end.wait()
        return
        yield


@pytest.mark.asyncio
async def test_main_exits_when_event_stream_ends() -> None:
    """Test that the main loop returns with an error if the stream ends."""
    app, _, _ = make_app()
    bridge = FakeEventBridge()
    app._bridge = bridge
    task = asyncio.ensure_future(app.main(None))  # type: ignore[arg-type]
    await asyncio.sleep(0.05)
    assert not task.done()
    assert app.exit_code == 0

    bridge.end.set()
    await asyncio.wait_for(task, 1)
    assert app.exit_code == 1


@pytest.mark.asyncio
async def test_main_exits_when_watchdog_fires() -> None:
    """Test that the main loop returns with an error if the broker is gone."""
    app, mqtt, _ = make_app()
    app._bridge = FakeEventBridge()
    app.config.watchdog.mqtt_disconnect_timeout = 0.01
    mqtt.is_connected = False
    original = app._watchdog

    async def fast_watchdog(*, interval: float = 0.01) -> None:
        await original(interval=interval)

    app._watchdog = fast_watchdog  # type: ignore[method-assign]
    await asyncio.wait_for(app.main(None), 1)  # type: ignore[arg-type]
    assert app.exit_code == 1


SWITCH = "00:17:88:01:00:00:00:07-02-fc00"


def make_sensor(uniqueid: str) -> SensorInfo:
    """Create a sensor as published to MQTT."""
    return SensorInfo.parse_obj(
        {
            "id": 7,
            "name": "Switch",
            "type": "ZLLSwitch",
            "modelid": "RWL021",
            "manufacturername": "Signify",
            "productname": "Hue dimmer switch",
            "uniqueid": uniqueid,
            "swversion": "1.0",
            "state": {"lastupdated": "none", "buttonevent": 4002},
            "capabilities": {},
        },
    )


def test_publish_sensor_alias_and_id() -> None:
    """Test that an aliased sensor is published on both topics."""
    app, mqtt, _ = make_app()
    app.publish_sensor(make_sensor(SWITCH))
    assert mqtt.published == [("sensor/Switch", True), (f"sensor/{SWITCH}", True)]


def test_publish_sensor_alias_only() -> None:
    """Test that the id topic of a sensor can be turned off."""
    app, mqtt, _ = make_app(publish_ids=False)
    app.publish_sensor(make_sensor(SWITCH))
    app.publish_sensor(make_sensor("00:17:88:01:00:00:00:08-02-fc00"))
    assert mqtt.topics == ["sensor/Switch", "sensor/00:17:88:01:00:00:00:08-02-fc00"]
