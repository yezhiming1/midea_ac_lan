"""Select for Midea Lan."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast

from homeassistant.components.select import SelectEntity
from homeassistant.const import CONF_DEVICE_ID, CONF_SWITCHES, Platform
from homeassistant.core import callback
from homeassistant.helpers.restore_state import RestoreEntity
from midealan.devices.ac import (
    DeviceAttributes as ACAttributes,
)

from .const import (
    DEVICES,
    DOMAIN,
    PERSON_AIRFLOW_AVOID,
    PERSON_AIRFLOW_MODE,
    PERSON_AIRFLOW_MODES,
    PERSON_AIRFLOW_OFF,
    PERSON_AIRFLOW_TOWARD,
    supports_model,
)
from .midea_devices import MIDEA_DEVICES
from .midea_entity import MideaEntity

if TYPE_CHECKING:
    from asyncio import TimerHandle

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from midealan.device import MideaDevice
    from midealan.devices.ac import MideaACDevice
    from midealan.devices.e1 import MideaE1Device


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up selects for device."""
    device_id = config_entry.data.get(CONF_DEVICE_ID)
    device = hass.data[DOMAIN][DEVICES].get(device_id)
    extra_switches = config_entry.options.get(CONF_SWITCHES, [])
    selects = []
    for entity_key, config in cast(
        "dict",
        MIDEA_DEVICES[device.device_type]["entities"],
    ).items():
        if (
            config["type"] != Platform.SELECT
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
        if entity_key == PERSON_AIRFLOW_MODE:
            dev = MideaPersonAirflowSelect(device, entity_key)
        else:
            dev = MideaSelect(device, entity_key)
        selects.append(dev)
    async_add_entities(selects)


class MideaSelect(MideaEntity, SelectEntity):
    """Represent a Midea select."""

    def __init__(self, device: MideaDevice, entity_key: str) -> None:
        """Midea select init."""
        super().__init__(device, entity_key)
        self._attribute_key = self._config.get("attribute", entity_key)
        self._options_name = self._config.get("options")
        self._options_dict_name = self._config.get("options_dict")
        self._options_static = self._config.get("options_static")

    @property
    def options(self) -> list[str]:
        """Available options for the entity."""
        if self._options_static:
            return cast("list[str]", self._options_static)
        if self._options_dict_name:
            options = self._get_options_dict()
            codes_by_model = self._config.get("options_codes_by_model", {})
            codes = codes_by_model.get(str(self._device.model)) or self._config.get(
                "options_codes",
            )
            if codes:
                return [options[code] for code in codes if code in options]
            return list(options.values())
        return cast("list", getattr(self._device, self._options_name))

    @property
    def current_option(self) -> str | None:
        """Currently selected option."""
        option = cast("str | None", self._device.get_attribute(self._attribute_key))
        return option if option in self.options else None

    @property
    def available(self) -> bool:
        """Whether the entity is available."""
        if not super().available:
            return False
        power_attribute = self._config.get("available_power_attribute")
        return not power_attribute or bool(self._device.get_attribute(power_attribute))

    def select_option(self, option: str) -> None:
        """Select entity option."""
        if self._config.get("set_message") == "e1_work_mode":
            self._select_e1_work_mode(option)
            return
        self._device.set_attribute(self._attribute_key, option)

    def _get_options_dict(self) -> dict[int, str]:
        """Return option dict from the backing midea-lan device.

        Returns
        -------
        Option labels keyed by the raw mode code.

        """
        return cast("dict[int, str]", getattr(self._device, self._options_dict_name))

    def _select_e1_work_mode(self, option: str) -> None:
        """Set dishwasher work mode via midea-lan's public E1 API.

        Raises
        ------
        ValueError
            If the requested option is not a supported work mode.

        """
        mode = self._get_dict_key_by_value(self._get_options_dict(), option)
        if mode is None:
            raise ValueError(f"Unsupported dishwasher mode: {option}")
        cast("MideaE1Device", self._device).set_work_mode(mode)

    @callback
    def update_state(self, status: Any) -> None:  # ruff:ignore[any-type]
        """Update entity state."""
        super().update_state(status)
        power_attribute = self._config.get("available_power_attribute")
        if (
            power_attribute
            and self.hass
            and (self._attribute_key in status or power_attribute in status)
        ):
            self.schedule_update_if_running()

    @staticmethod
    def _get_dict_key_by_value(source: dict[int, str], value: str) -> int | None:
        for key, item in source.items():
            if item == value:
                return key
        return None


class MideaPersonAirflowSelect(MideaSelect, RestoreEntity):
    """Persist and restore the mutually exclusive person-airflow preference."""

    _RESTORE_DELAY_SECONDS = 2.0
    _WRITE_SETTLE_SECONDS = 15.0

    def __init__(self, device: MideaDevice, entity_key: str) -> None:
        """Initialize the desired mode independently of the device's boot reset."""
        super().__init__(device, entity_key)
        self._desired_option: str = PERSON_AIRFLOW_OFF
        self._last_power: bool | None = None
        self._pending_until = 0.0
        self._restore_handle: TimerHandle | None = None

    @property
    def current_option(self) -> str:
        """The remembered preference, not the temporary boot-reset value."""
        return self._desired_option

    async def async_added_to_hass(self) -> None:
        """Restore the last HA preference and reapply it if the unit is already on."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in PERSON_AIRFLOW_MODES:
            self._desired_option = last_state.state
        else:
            self._desired_option = self._actual_option()
        self._last_power = bool(self._device.get_attribute(ACAttributes.power))
        if self._last_power and self._desired_option != PERSON_AIRFLOW_OFF:
            self._schedule_restore()
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Cancel a delayed boot restore before removing the entity."""
        if self._restore_handle is not None:
            self._restore_handle.cancel()
            self._restore_handle = None
        await super().async_will_remove_from_hass()

    def select_option(self, option: str) -> None:
        """Remember a preference and apply it immediately while powered on.

        Raises:
            ValueError: If the option is not a supported person-airflow mode.

        """
        if option not in PERSON_AIRFLOW_MODES:
            raise ValueError(f"Unsupported person-airflow mode: {option}")
        if self._restore_handle is not None:
            self._restore_handle.cancel()
            self._restore_handle = None
        self._desired_option = option
        if bool(self._device.get_attribute(ACAttributes.power)):
            self._apply_desired_option()
        self.async_write_ha_state()

    @callback
    def update_state(self, status: Any) -> None:  # ruff:ignore[any-type]
        """Track external changes without forgetting the preference while off."""
        if not self.hass:
            return
        relevant = {
            ACAttributes.power.value,
            ACAttributes.wind_straight.value,
            ACAttributes.wind_avoid.value,
            "available",
        }
        if not relevant.intersection(status):
            return

        power = bool(self._device.get_attribute(ACAttributes.power))
        power_just_enabled = power and self._last_power is False
        self._last_power = power
        if power_just_enabled and self._desired_option != PERSON_AIRFLOW_OFF:
            self.hass.loop.call_soon_threadsafe(self._schedule_restore)
        elif power and {
            ACAttributes.wind_straight.value,
            ACAttributes.wind_avoid.value,
        }.intersection(status):
            actual = self._actual_option()
            # During the short power-on boot window the firmware reports both
            # flags as off before the delayed restore is sent.  Treat that as a
            # transient while a restore callback is pending, otherwise the
            # remembered preference is overwritten before it can be reapplied.
            if self._restore_handle is None and (
                actual != PERSON_AIRFLOW_OFF or time.monotonic() >= self._pending_until
            ):
                self._desired_option = actual
                self._pending_until = 0.0

        self.schedule_update_if_running()

    @callback
    def _schedule_restore(self) -> None:
        """Schedule one post-power-on restore after firmware boot state settles."""
        if self._restore_handle is not None:
            self._restore_handle.cancel()
        self._restore_handle = self.hass.loop.call_later(
            self._RESTORE_DELAY_SECONDS,
            self._restore_after_power_on,
        )

    @callback
    def _restore_after_power_on(self) -> None:
        """Apply the remembered mode only if the device is still powered on."""
        self._restore_handle = None
        if (
            self.hass
            and not self.hass.is_stopping
            and bool(self._device.get_attribute(ACAttributes.power))
            and self._desired_option != PERSON_AIRFLOW_OFF
        ):
            self._apply_desired_option()

    def _apply_desired_option(self) -> None:
        """Send one atomic mode command and start a response-settle window."""
        cast("MideaACDevice", self._device).set_person_airflow_mode(
            self._desired_option,
        )
        self._pending_until = time.monotonic() + self._WRITE_SETTLE_SECONDS

    def _actual_option(self) -> str:
        """Translate the two reported flags into one mutually exclusive mode.

        Returns
        -------
        The mode currently reported by the appliance.

        """
        if self._device.get_attribute(ACAttributes.wind_avoid):
            return PERSON_AIRFLOW_AVOID
        if self._device.get_attribute(ACAttributes.wind_straight):
            return PERSON_AIRFLOW_TOWARD
        return PERSON_AIRFLOW_OFF
