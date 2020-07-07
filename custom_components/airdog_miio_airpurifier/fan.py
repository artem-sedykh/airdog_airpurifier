"""
Support for Airdog Mi Air Purifier.

For more details about this platform, please refer to the documentation
https://home-assistant.io/components/fan.xiaomi_miio/
"""
import asyncio
from .airdogpurifier import AirDogPurifier
from .airdogpurifier import OperationMode as AirDogOperationMode
from enum import Enum
from functools import partial
import logging

import voluptuous as vol

from homeassistant.components.fan import (
    DOMAIN,
    PLATFORM_SCHEMA,
    SUPPORT_SET_SPEED,
    FanEntity,
)
from homeassistant.const import ATTR_ENTITY_ID, CONF_HOST, CONF_NAME, CONF_TOKEN
from homeassistant.exceptions import PlatformNotReady
import homeassistant.helpers.config_validation as cv
from miio import (DeviceException, Device)

from .const import (
    DOMAIN,
    CONF_MODEL,
    SERVICE_SET_CHILD_LOCK_OFF,
    SERVICE_SET_CHILD_LOCK_ON,
    SERVICE_SET_MODE,
    SERVICE_RESET,
    ATTR_MODEL,
    ATTR_MODE,
    ATTR_SPEED,
    ATTR_MODE_LIST,
    ATTR_FIRMWARE_VERSION,
    AVAILABLE_ATTRIBUTES_AIRDOG_AIRPURIFIER_X5,
    SUCCESS,
    CONF_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "Xiaomi Miio Device"
DATA_KEY = "fan.xiaomi_miio_airpurifier"

MODEL_AIRPURIFIER_AIRDOG_X5 = "airdog.airpurifier.x5"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_TOKEN): vol.All(cv.string, vol.Length(min=32, max=32)),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_TIMEOUT, default=500): cv.positive_int,
        vol.Optional(CONF_MODEL): vol.In(
            [
                MODEL_AIRPURIFIER_AIRDOG_X5,
            ]
        )
    }
)


AIRPURIFIER_SERVICE_SCHEMA = vol.Schema({vol.Optional(ATTR_ENTITY_ID): cv.entity_ids})

SERVICE_SCHEMA_SET_MODE = AIRPURIFIER_SERVICE_SCHEMA.extend(
    {
        vol.Required(ATTR_MODE): vol.In([
            AirDogOperationMode.Auto.value,
            AirDogOperationMode.Sleep.value,
            AirDogOperationMode.Manual.value,
        ]),
        vol.Optional(ATTR_SPEED): vol.All(vol.Coerce(int), vol.Clamp(min=1, max=4))
    }
)

SERVICE_TO_METHOD = {
    SERVICE_SET_CHILD_LOCK_ON: {"method": "async_set_child_lock_on"},
    SERVICE_SET_CHILD_LOCK_OFF: {"method": "async_set_child_lock_off"},
    SERVICE_RESET: {"method": "async_clean"},
    SERVICE_SET_MODE: {
        "method": "async_set_mode",
        "schema": SERVICE_SCHEMA_SET_MODE,
    },
}


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the miio fan device from config."""
    if DATA_KEY not in hass.data:
        hass.data[DATA_KEY] = {}

    host = config[CONF_HOST]
    token = config[CONF_TOKEN]
    name = config[CONF_NAME]
    model = config.get(CONF_MODEL)
    timeout = config[CONF_TIMEOUT]/1000

    _LOGGER.info("Initializing with host %s (token %s...)", host, token[:5])
    unique_id = None
    firmware_version = None

    if model is None:
        try:
            miio_device = Device(host, token)
            device_info = await hass.async_add_executor_job(miio_device.info)
            model = device_info.model
            firmware_version = device_info.firmware_version
            unique_id = f"{model}-{device_info.mac_address}"
            _LOGGER.info(
                "%s %s %s detected",
                model,
                device_info.firmware_version,
                device_info.hardware_version,
            )
        except DeviceException:
            raise PlatformNotReady

    if model.startswith("airdog.airpurifier.x5"):
        air_purifier = AirDogPurifier(host, token, timeout)
        device = AirDogAirPurifier(name, air_purifier, model, unique_id, firmware_version)
    else:
        _LOGGER.error(
            "Unsupported device found! Please create an issue at "
            "https://github.com/syssi/xiaomi_airpurifier/issues "
            "and provide the following data: %s",
            model,
        )
        return False

    hass.data[DATA_KEY][host] = device
    async_add_entities([device], update_before_add=True)

    async def async_service_handler(service):
        """Map services to methods on XiaomiAirPurifier."""
        method = SERVICE_TO_METHOD.get(service.service)
        params = {
            key: value for key, value in service.data.items() if key != ATTR_ENTITY_ID
        }
        entity_ids = service.data.get(ATTR_ENTITY_ID)
        if entity_ids:
            devices = [
                device
                for device in hass.data[DATA_KEY].values()
                if device.entity_id in entity_ids
            ]
        else:
            devices = hass.data[DATA_KEY].values()

        update_tasks = []
        for device in devices:
            if not hasattr(device, method["method"]):
                continue
            await getattr(device, method["method"])(**params)
            update_tasks.append(device.async_update_ha_state(True))

        if update_tasks:
            await asyncio.wait(update_tasks, loop=hass.loop)

    for air_purifier_service in SERVICE_TO_METHOD:
        schema = SERVICE_TO_METHOD[air_purifier_service].get(
            "schema", AIRPURIFIER_SERVICE_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, air_purifier_service, async_service_handler, schema=schema
        )


class AirDogAirPurifier(FanEntity):
    """Representation of a Xiaomi Air Purifier."""

    def __init__(self, name, device, model, unique_id, firmware_version):
        self._name = name
        self._device = device
        self._model = model
        self._firmware_version = firmware_version
        self._unique_id = unique_id

        self._available = False
        self._state = None
        self._skip_update = False

        self._speed_list = ['1', '2', '3', '4']
        self._mode_list = [
            AirDogOperationMode.Auto.value,
            AirDogOperationMode.Sleep.value,
            AirDogOperationMode.Manual.value,
        ]

        self._state_attrs = {
            ATTR_MODEL: self._model,
            ATTR_FIRMWARE_VERSION: self._firmware_version,
            ATTR_MODE_LIST: self._mode_list,
        }
        self._available_attributes = AVAILABLE_ATTRIBUTES_AIRDOG_AIRPURIFIER_X5
        self._state_attrs.update({attribute: None for attribute in self._available_attributes})

    @property
    def supported_features(self):
        """Flag supported features."""
        return SUPPORT_SET_SPEED

    @property
    def should_poll(self):
        """Poll the device."""
        return True

    @property
    def unique_id(self):
        """Return an unique ID."""
        return self._unique_id

    @property
    def name(self):
        """Return the name of the device if any."""
        return self._name

    @property
    def available(self):
        """Return true when state is known."""
        return self._available

    @property
    def device_state_attributes(self):
        """Return the state attributes of the device."""
        return self._state_attrs

    @property
    def is_on(self):
        """Return true if device is on."""
        return self._state

    @staticmethod
    def _extract_value_from_attribute(state, attribute):
        value = getattr(state, attribute)
        if isinstance(value, Enum):
            return value.value

        return value

    async def _try_command(self, mask_error, func, *args, **kwargs):
        """Call a miio device command handling error messages."""
        try:
            result = await self.hass.async_add_executor_job(
                partial(func, *args, **kwargs)
            )

            _LOGGER.debug("Response received from miio device: %s", result)

            return result == SUCCESS
        except DeviceException as exc:
            _LOGGER.error(mask_error, exc)
            self._available = False
            return False

    async def async_turn_on(self, speed: str = None, **kwargs) -> None:
        """Turn the device on."""
        if speed:
            # If operation mode was set the device must not be turned on.
            result = await self.async_set_speed(speed)
        else:
            result = await self._try_command(
                "Turning the miio device on failed.", self._device.on
            )

        if result:
            self._state = True
            self._skip_update = True

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the device off."""
        result = await self._try_command(
            "Turning the miio device off failed.", self._device.off
        )

        if result:
            self._state = False
            self._skip_update = True

    async def async_update(self):
        """Fetch state from the device."""
        # On state change the device doesn't provide the new state immediately.
        if self._skip_update:
            self._skip_update = False
            return

        try:
            state = await self.hass.async_add_executor_job(self._device.status)
            _LOGGER.debug("Got new state: %s", state)

            self._available = True
            self._state = state.is_on
            self._state_attrs.update(
                {
                    key: self._extract_value_from_attribute(state, value)
                    for key, value in self._available_attributes.items()
                }
            )

        except DeviceException as ex:
            self._available = False
            _LOGGER.error("Got exception while fetching the state: %s", ex)

    @property
    def speed_list(self) -> list:
        """Get the list of available speeds."""
        return self._speed_list

    @property
    def mode_list(self) -> list:
        """Get the list of available modes."""
        return self._mode_list

    @property
    def speed(self):
        """Return the current speed."""
        return self._state_attrs[ATTR_SPEED]

    async def async_set_speed(self, speed: str) -> None:
        _LOGGER.debug("Setting the operation mode to: %s", speed)
        await self._try_command(
            "Setting speed failed.",
            self._device.set_speed,
            int(speed),
        )

    async def async_clean(self):
        await self._try_command("Reset failed.", self._device.clean)

    async def async_set_mode(self, mode: str, speed: str = '1'):
        data = 1
        if speed is not None:
            data = int(speed)

        await self._try_command(
            "Setting mode miio device failed.",
            self._device.set_mode,
            AirDogOperationMode(mode),
            data,
        )

    async def async_set_child_lock_on(self):
        await self._try_command(
            "Turning the child lock of the miio device on failed.",
            self._device.set_child_lock,
            True,
        )

    async def async_set_child_lock_off(self):
        await self._try_command(
            "Turning the child lock of the miio device off failed.",
            self._device.set_child_lock,
            False,
        )
