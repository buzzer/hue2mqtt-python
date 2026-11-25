"""Application entrypoint."""
import asyncio
import sys
from typing import Optional

import click

from .discovery import discover_bridge
from .hue2mqtt import Hue2MQTT


async def _print_aliases(verbose: bool, config_file: Optional[str]) -> None:
    hue2mqtt = Hue2MQTT(verbose, config_file, welcome_message=False)
    await hue2mqtt.print_aliases()


async def _run(verbose: bool, config_file: Optional[str]) -> int:
    # Created in the running loop, as the MQTT client binds to it
    hue2mqtt = Hue2MQTT(verbose, config_file)
    await hue2mqtt.run()
    return hue2mqtt.exit_code


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
        asyncio.run(discover_bridge())
    elif print_aliases:
        asyncio.run(_print_aliases(verbose, config_file))
    else:
        sys.exit(asyncio.run(_run(verbose, config_file)))


if __name__ == "__main__":
    app()
