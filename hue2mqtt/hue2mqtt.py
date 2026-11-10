"""
Data Component base class.

A data component represents the common functionality between
State Managers and Consumers. It handles connecting to the broker
and managing the event loop.
"""
import asyncio
import json
import logging
import signal
import sys
import time
from signal import SIGHUP, SIGINT, SIGTERM
from types import FrameType
from typing import Any, Dict, List, Match, Optional, Tuple

import aiohue
from aiohttp.client import ClientSession
from pydantic import ValidationError, parse_obj_as

from hue2mqtt import __version__
from hue2mqtt.messages import BridgeInfo, Hue2MQTTStatus
from hue2mqtt.schema import (
    GroupInfo,
    GroupSetState,
    LightInfo,
    LightSetState,
    SensorInfo,
)

from .aliases import render_aliases
from .config import Hue2MQTTConfig
from .mqtt.wrapper import MQTTWrapper

LOGGER = logging.getLogger(__name__)

loop = asyncio.get_event_loop()


class Hue2MQTT:
    """Hue to MQTT Bridge."""

    config: Hue2MQTTConfig

    def __init__(
        self,
        verbose: bool,
        config_file: Optional[str],
        *,
        name: str = "hue2mqtt",
        welcome_message: bool = True,
    ) -> None:
        self.config = Hue2MQTTConfig.load(config_file)
        self.name = name
        self.exit_code = 0

        # Reverse lookup: uniqueid / group id -> alias
        self._light_alias = {v: k for k, v in self.config.alias.light.items()}
        self._group_alias = {v: k for k, v in self.config.alias.group.items()}

        self._setup_logging(verbose, welcome_message=welcome_message)
        self._setup_event_loop()
        self._setup_mqtt()

    def _setup_logging(self, verbose: bool, *, welcome_message: bool = True) -> None:
        if verbose:
            logging.basicConfig(
                level=logging.DEBUG,
                format=f"%(asctime)s {self.name} %(name)s %(levelname)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        else:
            logging.basicConfig(
                level=logging.INFO,
                format=f"%(asctime)s {self.name} %(levelname)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

            # Suppress INFO messages from gmqtt
            logging.getLogger("gmqtt").setLevel(logging.WARNING)

        if welcome_message:
            LOGGER.info(f"Hue2MQTT v{__version__} - {self.__doc__}")

    def _setup_event_loop(self) -> None:
        loop.add_signal_handler(SIGHUP, self.halt)
        loop.add_signal_handler(SIGINT, self.halt)
        loop.add_signal_handler(SIGTERM, self.halt)

    def _setup_mqtt(self) -> None:
        self._mqtt = MQTTWrapper(
            self.config.mqtt.client_id,
            self.config.mqtt,
            last_will=Hue2MQTTStatus(online=False),
        )

        self._mqtt.subscribe("light/+/set", self.handle_set_light)
        self._mqtt.subscribe("group/+/set", self.handle_set_group)

    def _exit(self, signals: signal.Signals, frame_type: FrameType) -> None:
        sys.exit(0)

    async def run(self) -> None:
        """Entrypoint for the data component."""
        await self._mqtt.connect()
        LOGGER.info("Connected to MQTT Broker")

        async with ClientSession() as websession:
            try:
                await self._setup_bridge(websession)
            except aiohue.errors.Unauthorized:
                LOGGER.error("Bridge rejected username. Please use --discover")
                self.halt()
                return
            await self._publish_bridge_status()
            await self.main(websession)

        if self._mqtt.is_connected:
            LOGGER.info("Disconnecting from MQTT Broker")
            await self._publish_bridge_status(online=False)
            await self._mqtt.disconnect()

    def halt(self) -> None:
        """Stop the component."""
        sys.exit(-1)

    async def _setup_bridge(self, websession: ClientSession) -> None:
        """Connect to the Hue Bridge."""
        self._bridge = aiohue.Bridge(
            self.config.hue.ip,
            websession,
            username=self.config.hue.username,
        )
        LOGGER.info(f"Connecting to Hue Bridge at {self.config.hue.ip}")
        await self._bridge.initialize()

    async def _publish_bridge_status(self, *, online: bool = True) -> None:
        """Publish info about the Hue Bridge."""
        if online:
            LOGGER.info(f"Bridge Name: {self._bridge.config.name}")
            LOGGER.info(f"Bridge MAC: {self._bridge.config.mac}")
            LOGGER.info(f"API Version: {self._bridge.config.apiversion}")

            info = BridgeInfo(
                name=self._bridge.config.name,
                mac_address=self._bridge.config.mac,
                api_version=self._bridge.config.apiversion,
            )
            message = Hue2MQTTStatus(online=online, bridge=info)
        else:
            message = Hue2MQTTStatus(online=online)

        self._mqtt.publish("status", message)

    def _topic_names(self, ident: str, aliases: Dict[str, str]) -> List[str]:
        """Get the topic levels that an object is published on."""
        names = []
        if ident in aliases:
            names.append(aliases[ident])
        if self.config.mqtt.publish_ids or not names:
            names.append(ident)
        return names

    def publish_light(self, light: LightInfo) -> None:
        """Publish information about a light to MQTT."""
        for name in self._topic_names(light.uniqueid, self._light_alias):
            self._mqtt.publish(f"light/{name}", light, retain=True)

    def publish_group(self, group: GroupInfo) -> None:
        """Publish information about a group to MQTT."""
        for name in self._topic_names(str(group.id), self._group_alias):
            self._mqtt.publish(f"group/{name}", group, retain=True)

    def publish_sensor(self, sensor: SensorInfo) -> None:
        """Publish information about a group to MQTT."""
        self._mqtt.publish(f"sensor/{sensor.uniqueid}", sensor, retain=True)

    async def handle_set_light(self, match: Match[str], payload: str) -> None:
        """Handle an update to a light."""
        name = match.group(1)
        uniqueid = self.config.alias.light.get(name, name)

        # Find the light with that uniqueid
        for light_id in self._bridge.lights:
            light = self._bridge.lights[light_id]
            if light.uniqueid == uniqueid:
                try:
                    state = parse_obj_as(LightSetState, json.loads(payload))
                    LOGGER.info(f"Updating {light.name}")
                    await light.set_state(**state.dict())
                except json.JSONDecodeError:
                    LOGGER.warning(f"Bad JSON on light request: {payload}")
                except TypeError:
                    LOGGER.warning(f"Expected dictionary, got: {payload}")
                except ValidationError as e:
                    LOGGER.warning(f"Invalid light state: {e}")
                return
        LOGGER.warning(f"Unknown light uniqueid: {uniqueid}")

    async def handle_set_group(self, match: Match[str], payload: str) -> None:
        """Handle an update to a group."""
        name = match.group(1)
        groupid = self.config.alias.group.get(name, name)

        try:
            group = self._bridge.groups[groupid]
            state = parse_obj_as(GroupSetState, json.loads(payload))
            LOGGER.info(f"Updating group {group.name}")
            await group.set_action(**state.dict())
        except (IndexError, KeyError):
            LOGGER.warning(f"Unknown group id: {groupid}")
        except json.JSONDecodeError:
            LOGGER.warning(f"Bad JSON on light request: {payload}")
        except TypeError:
            LOGGER.warning(f"Expected dictionary, got: {payload}")
        except ValidationError as e:
            LOGGER.warning(f"Invalid light state: {e}")

    async def main(self, websession: ClientSession) -> None:
        """Main method of the data component."""
        # Publish initial info about lights
        for idx, light_raw in self._bridge.lights._items.items():
            light = LightInfo(id=idx, **light_raw.raw)
            self.publish_light(light)

        # Publish initial info about groups
        for idx, group_raw in self._bridge.groups._items.items():
            group = GroupInfo(id=idx, **group_raw.raw)
            self.publish_group(group)

        # Publish initial info about sensors
        for idx, sensor_raw in self._bridge.sensors._items.items():
            if "uniqueid" in sensor_raw.raw and "productname" in sensor_raw.raw:
                sensor = SensorInfo(id=idx, **sensor_raw.raw)
                self.publish_sensor(sensor)
            else:
                LOGGER.debug(f"Ignoring virtual sensor: {sensor_raw.name}")

        # Publish updates until the event stream ends or the watchdog fires.
        # Either way we exit with an error, so that a supervisor restarts us.
        tasks = [
            asyncio.ensure_future(self._publish_updates()),
            asyncio.ensure_future(self._watchdog()),
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        self.exit_code = 1
        for task in done:
            task.result()

    async def _publish_updates(self) -> None:
        """Publish updates from the event stream of the bridge."""
        async for updated_object in self._bridge.listen_events():
            if isinstance(updated_object, aiohue.groups.Group):
                group = GroupInfo(id=updated_object.id, **updated_object.raw)
                self.publish_group(group)
            elif isinstance(updated_object, aiohue.lights.Light):
                light = LightInfo(id=updated_object.id, **updated_object.raw)
                self.publish_light(light)
            elif isinstance(updated_object, aiohue.sensors.GenericSensor):
                sensor = SensorInfo(id=updated_object.id, **updated_object.raw)
                self.publish_sensor(sensor)
            else:
                LOGGER.warning("Unknown object")
        LOGGER.error("Event stream of the Hue Bridge ended")

    async def _watchdog(self, *, interval: float = 5) -> None:
        """Return when Hue2MQTT should be restarted."""
        config = self.config.watchdog
        started = time.monotonic()
        disconnected_since: Optional[float] = None
        while True:
            await asyncio.sleep(interval)
            now = time.monotonic()

            if config.max_runtime_hours is not None:
                if now - started >= config.max_runtime_hours * 3600:
                    LOGGER.warning("Maximum runtime reached, exiting")
                    return

            if self._mqtt.is_connected:
                disconnected_since = None
            elif disconnected_since is None:
                LOGGER.warning("Lost connection to MQTT Broker")
                disconnected_since = now
            elif now - disconnected_since >= config.mqtt_disconnect_timeout:
                LOGGER.error("MQTT Broker unreachable, exiting")
                return

    async def print_aliases(self) -> None:
        """Print an alias config section with the names stored on the bridge."""
        async with ClientSession() as websession:
            await self._setup_bridge(websession)
            lights: List[Tuple[str, str]] = [
                (light.name, light.uniqueid) for light in self._iter(self._bridge.lights)
            ]
            groups: List[Tuple[str, str, str]] = [
                (group.name, str(group.id), str(group.raw.get("type", "")))
                for group in self._iter(self._bridge.groups)
            ]
        print(render_aliases(lights, groups), end="")  # noqa: T201

    @staticmethod
    def _iter(items: Any) -> List[Any]:
        """Get the objects of an aiohue collection, ordered by id."""
        return [items[key] for key in sorted(items._items, key=lambda k: int(k))]
