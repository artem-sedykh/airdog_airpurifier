import enum
import logging
from collections import defaultdict
from typing import Any, Dict
from miio import Device
from time import sleep
import click

from miio.click_common import EnumType, command, format_output

from miio import DeviceException

_LOGGER = logging.getLogger(__name__)


class AirDogPurifierException(DeviceException):
    pass


class OperationMode(enum.Enum):
    Auto = "auto"
    Manual = "manual"
    Sleep = "sleep"


class AirDogPurifierStatus:
    """Container for status reports from the air purifier."""

    def __init__(self, data: Dict[str, Any]) -> None:
        self.data = data

    @property
    def power(self) -> str:
        """Power state."""
        return self.data["power"]

    @property
    def is_on(self) -> bool:
        """Return True if device is on."""
        return self.power == "on"

    @property
    def aqi(self) -> int:
        """Air quality index."""
        return self.data["pm"]

    @property
    def mode(self) -> OperationMode:
        """Current operation mode."""
        return OperationMode(self.data["mode"])

    @property
    def child_lock(self) -> bool:
        """Return True if child lock is on."""
        return self.data["lock"] == "lock"

    @property
    def speed(self) -> int:
        return self.data["speed"]

    @property
    def clean(self) -> bool:
        return self.data["clean"] == "y"

    def __repr__(self) -> str:
        s = (
                "<AirPurifierStatus power=%s, "
                "aqi=%s, "
                "mode=%s, "
                "child_lock=%s, "
                "speed=%s, "
                "clean=%s>"
                % (
                    self.power,
                    self.aqi,
                    self.mode.value,
                    self.child_lock,
                    self.speed,
                    self.clean,
                )
        )
        return s

    def __json__(self):
        return self.data


class AirDogPurifier(Device):
    def __init__(
        self,
        ip: str = None,
        token: str = None,
        delay: float = 0,
        start_id: int = 0,
        debug: int = 0,
        lazy_discover: bool = True,
    ) -> None:
        super().__init__(ip, token, start_id, debug, lazy_discover)
        self.delay = delay

    @command(
        default_output=format_output(
            "",
            "Power: {result.power}\n"
            "AQI: {result.aqi} μg/m³\n"
            "Mode: {result.mode.value}\n"
            "Child lock: {result.child_lock}\n"
            "Speed: {result.speed}\n"
            "Clean: {result.clean}\n",
        )
    )
    def status(self) -> AirDogPurifierStatus:
        """Retrieve properties."""

        properties = [
            "power",
            "mode",
            "speed",
            "lock",
            "pm",
            "clean",
        ]

        values = self.get_properties(properties, max_properties=6)

        return AirDogPurifierStatus(defaultdict(lambda: None, zip(properties, values)))

    @command(default_output=format_output("Powering on"))
    def on(self):
        """Power on."""
        result = self.send("set_power", [1])
        sleep(self.delay)
        return result

    @command(default_output=format_output("Powering off"))
    def off(self):
        """Power off."""
        result = self.send("set_power", [0])
        sleep(self.delay)
        return result

    @command(
        click.argument("mode", type=EnumType(OperationMode, False)),
        click.argument("speed", type=int),
        default_output=format_output("Setting mode to '{mode.value}', speed '{speed}'"),
    )
    def set_mode(self, mode: OperationMode, speed: int = 1):
        """Set mode."""

        if mode.value == OperationMode.Auto.value:
            result = self.send("set_wind", [0, 1])
            sleep(self.delay)
            return result

        if mode.value == OperationMode.Sleep.value:
            result = self.send("set_wind", [2, 1])
            sleep(self.delay)
            return result

        if mode.value == OperationMode.Manual.value:
            if speed < 0 or speed > 4:
                raise AirDogPurifierException("Invalid speed: %s" % speed)
            result = self.send("set_wind", [1, speed])
            sleep(self.delay)
            return result

        raise AirDogPurifierException("not supported mode: %s" % mode.value)

    @command(
        click.argument("speed", type=int),
        default_output=format_output("Setting speed to {speed}"),
    )
    def set_speed(self, speed: int):
        """Set speed."""
        if speed < 0 or speed > 4:
            raise AirDogPurifierException("Invalid speed: %s" % speed)

        result = self.send("set_wind", [1, speed])  # 0 ... 4
        sleep(self.delay)
        return result

    @command(
        click.argument("lock", type=bool),
        default_output=format_output(
            lambda lock: "Turning on child lock" if lock else "Turning off child lock"
        ),
    )
    def set_child_lock(self, lock: bool):
        """Set child lock on/off."""
        if lock:
            result = self.send("set_lock", [1])
            sleep(self.delay)
            return result
        else:
            result = self.send("set_lock", [0])
            sleep(self.delay)
            return result

    @command(default_output=format_output("Resetting"))
    def clean(self):
        result = self.send("set_clean", [])
        sleep(self.delay)
        return result
