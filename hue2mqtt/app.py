"""Application entrypoint."""
import asyncio
import sys
from typing import Optional

import click

from .discovery import discover_bridge
from .hue2mqtt import Hue2MQTT

loop = asyncio.get_event_loop()


@click.command("hue2mqtt")
@click.option("-v", "--verbose", is_flag=True)
@click.option("-c", "--config-file", type=click.Path(exists=True))
@click.option("--discover", is_flag=True)
@click.option(
    "--print-aliases",
    is_flag=True,
    help="Print an alias config section with the names stored on the bridge.",
)
def app(
    *,
    verbose: bool,
    config_file: Optional[str],
    discover: bool,
    print_aliases: bool,
) -> None:
    """Main function for Hue2MQTT."""
    if discover:
        loop.run_until_complete(discover_bridge())
    elif print_aliases:
        hue2mqtt = Hue2MQTT(verbose, config_file, welcome_message=False)
        loop.run_until_complete(hue2mqtt.print_aliases())
    else:
        # Start application
        hue2mqtt = Hue2MQTT(verbose, config_file)
        loop.run_until_complete(hue2mqtt.run())
        sys.exit(hue2mqtt.exit_code)


if __name__ == "__main__":
    app()
