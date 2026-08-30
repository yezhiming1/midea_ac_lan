"""Switch for Midea Lan."""

from typing import Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DEVICE_ID, CONF_SWITCHES, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import ToggleEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from midealan.devices.ac import DeviceAttributes as ACAttributes
from midealan.devices.ac import MideaACDevice

from .const import DEVICES, DOMAIN, LIGHT_SENSITIVE_CONTROL, supports_model
from .midea_devices import MIDEA_DEVICES
from .midea_entity import MideaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switches for device."""
    device_id = config_entry.data.get(CONF_DEVICE_ID)
    device = hass.data[DOMAIN][DEVICES].get(device_id)
    extra_switches = config_entry.options.get(CONF_SWITCHES, [])
    switches = []
    for entity_key, config in cast(
        "dict",
        MIDEA_DEVICES[device.device_type]["entities"],
    ).items():
        if (
            config["type"] != Platform.SWITCH
            or not supports_model(device.model, config, device.subtype)
            or (not config.get("default") and entity_key not in extra_switches)
        ):
            continue
        required_attribute = config.get("required_attribute")
        if (
            required_attribute is not None
            and required_attribute not in device.attributes
        ):
            continue
        if entity_key == LIGHT_SENSITIVE_CONTROL:
            switches.append(MideaLightSensitiveSwitch(device, entity_key))
        else:
            switches.append(MideaSwitch(device, entity_key))
    async_add_entities(switches)


class MideaSwitch(MideaEntity, ToggleEntity):
    """Represent a Midea switch."""

    @property
    def is_on(self) -> bool:
        """Whether the switch is on."""
        return cast("bool", self._device.get_attribute(self._entity_key))

    def turn_on(self, **kwargs: Any) -> None:  # ruff:ignore[any-type, unused-method-argument]
        """Turn on switch."""
        self._device.set_attribute(attr=self._entity_key, value=True)

    def turn_off(self, **kwargs: Any) -> None:  # ruff:ignore[any-type, unused-method-argument]
        """Turn off switch."""
        self._device.set_attribute(attr=self._entity_key, value=False)


class MideaLightSensitiveSwitch(MideaSwitch):
    """Control the 220F4047 smart-light preference with verified raw values."""

    @property
    def is_on(self) -> bool:
        """Whether smart-light sensing is enabled at any sensitivity level."""
        return bool(self._device.get_attribute(ACAttributes.light_sensitive))

    def update_state(self, status: Any) -> None:  # ruff:ignore[any-type]
        """Refresh when the backing raw sensor changes."""
        raw_key = ACAttributes.light_sensitive.value
        if raw_key in status and self._entity_key not in status:
            status = {**status, self._entity_key: status[raw_key]}
        super().update_state(status)

    def turn_on(self, **kwargs: Any) -> None:  # ruff:ignore[any-type, unused-method-argument]
        """Enable smart-light sensing at the App's high/on value."""
        cast("MideaACDevice", self._device).set_light_sensitive(True)

    def turn_off(self, **kwargs: Any) -> None:  # ruff:ignore[any-type, unused-method-argument]
        """Disable smart-light sensing."""
        cast("MideaACDevice", self._device).set_light_sensitive(False)
