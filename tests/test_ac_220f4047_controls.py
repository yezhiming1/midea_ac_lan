"""Tests for the model-gated 220F4047 controls and reversible entity filtering."""

# unittest is intentional because this integration does not depend on pytest.
# The custom component import must run before midealan so its verified wheel is
# added to sys.path. Preserve that intentional order.
# ruff: file-ignore[import-private-name, pytest-unittest-assertion, pytest-unittest-raises-assertion, private-member-access, unsorted-imports, module-import-not-at-top-of-file]

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock, patch

if TYPE_CHECKING:
    from asyncio import TimerHandle
    from collections.abc import Callable

    from midealan.device import MideaDevice

CUSTOM_COMPONENTS_ROOT = Path(__file__).parents[1] / "custom_components"
sys.path.insert(0, str(CUSTOM_COMPONENTS_ROOT))

from homeassistant.const import CONF_SENSORS, CONF_SWITCHES
from homeassistant.helpers import entity_registry as er

from midea_ac_lan import _reconcile_optional_entity_registry
from midealan.devices.ac import (
    DeviceAttributes as ACAttributes,
)

from midea_ac_lan.const import (
    LIGHT_SENSITIVE_CONTROL,
    PERSON_AIRFLOW_AVOID,
    PERSON_AIRFLOW_MODE,
    PERSON_AIRFLOW_OFF,
    PERSON_AIRFLOW_TOWARD,
    supports_model,
)
from midea_ac_lan.select import MideaPersonAirflowSelect
from midea_ac_lan.switch import MideaLightSensitiveSwitch


class FakeACDevice:
    """Small AC device double covering the entity-facing public surface."""

    device_type = 0xAC
    device_id = 123
    name = "Test AC"
    model = "220F4047"
    subtype = 8
    mac = None
    serial_number = None
    available = True

    def __init__(self, *, power: bool) -> None:
        """Initialize a device double with an explicit power state."""
        self.values = {
            ACAttributes.power.value: power,
            ACAttributes.wind_straight.value: False,
            ACAttributes.wind_avoid.value: False,
            ACAttributes.light_sensitive.value: 3,
        }
        self.attributes = {
            ACAttributes.power: power,
            ACAttributes.wind_straight: False,
            ACAttributes.wind_avoid: False,
            ACAttributes.light_sensitive: 3,
        }
        self.person_airflow_calls: list[str] = []
        self.light_sensitive_calls: list[bool] = []

    def get_attribute(self, attribute: object) -> bool | int | None:
        """Return an attribute by enum or string key.

        Returns
        -------
        The stored test value, or ``None`` when absent.

        """
        key = attribute.value if hasattr(attribute, "value") else str(attribute)
        return self.values.get(key)

    def set_person_airflow_mode(self, mode: str) -> None:
        """Record a person-airflow command."""
        self.person_airflow_calls.append(mode)

    def set_light_sensitive(self, enabled: bool) -> None:
        """Record a smart-light command."""
        self.light_sensitive_calls.append(enabled)

    def register_update(self, _update: object) -> None:
        """Satisfy MideaEntity's callback surface."""

    def unregister_update(self, _update: object) -> None:
        """Satisfy MideaEntity's callback surface."""


class FakeTimerHandle:
    """Minimal cancellable timer handle."""

    def __init__(self) -> None:
        """Initialize an active handle."""
        self.cancelled = False

    def cancel(self) -> None:
        """Record cancellation."""
        self.cancelled = True


class FakeLoop:
    """Run thread-safe callbacks now and delayed callbacks on demand."""

    def __init__(self) -> None:
        """Initialize without a delayed callback."""
        self.delayed_callback: Callable[[], None] | None = None
        self.handle = FakeTimerHandle()

    @staticmethod
    def call_soon_threadsafe(callback: Callable[[], None]) -> None:
        """Execute the callback synchronously for this unit test."""
        callback()

    def call_later(
        self,
        _delay: float,
        callback: Callable[[], None],
    ) -> FakeTimerHandle:
        """Store the delayed callback for explicit execution.

        Returns
        -------
        The cancellable fake timer handle.

        """
        self.delayed_callback = callback
        return self.handle

    def run_delayed(self) -> None:
        """Run the stored delayed callback.

        Raises
        ------
        AssertionError
            If no delayed callback was scheduled.

        """
        if self.delayed_callback is None:
            raise AssertionError("No delayed callback was scheduled")
        self.delayed_callback()


def as_midea_device(device: FakeACDevice) -> MideaDevice:
    """Type a deliberately small test double as the public device base class.

    Returns
    -------
    The same object, narrowed only for static analysis.

    """
    return cast("MideaDevice", device)


class ModelControlTests(unittest.TestCase):
    """Verify model gates and entity command behavior."""

    def test_supports_model_and_subtype(self) -> None:
        """Both identifiers must match for a risky model-specific control."""
        config = {"models": ["220F4047"], "subtypes": [8]}

        self.assertTrue(supports_model("220F4047", config, 8))
        self.assertFalse(supports_model("220F4047", config, 1))
        self.assertFalse(supports_model("other", config, 8))

    def test_person_airflow_select_applies_only_while_powered(self) -> None:
        """Off-device choices persist without writing; powered choices write once."""
        device = FakeACDevice(power=False)
        entity = MideaPersonAirflowSelect(as_midea_device(device), PERSON_AIRFLOW_MODE)

        with patch.object(entity, "schedule_update_ha_state"):
            entity.select_option(PERSON_AIRFLOW_AVOID)
        self.assertEqual(entity.current_option, PERSON_AIRFLOW_AVOID)
        self.assertEqual(device.person_airflow_calls, [])

        device.values[ACAttributes.power.value] = True
        with patch.object(entity, "schedule_update_ha_state"):
            entity.select_option(PERSON_AIRFLOW_TOWARD)
        self.assertEqual(device.person_airflow_calls, [PERSON_AIRFLOW_TOWARD])

        with (
            patch.object(entity, "schedule_update_ha_state"),
            self.assertRaisesRegex(ValueError, "Unsupported person-airflow mode"),
        ):
            entity.select_option("sideways")

    def test_person_airflow_preference_restores_after_power_on(self) -> None:
        """A powered-off preference is reapplied after the boot-settle delay."""
        device = FakeACDevice(power=False)
        entity = MideaPersonAirflowSelect(as_midea_device(device), PERSON_AIRFLOW_MODE)
        loop = FakeLoop()
        entity.hass = SimpleNamespace(loop=loop, is_stopping=False)
        entity._last_power = False

        with patch.object(entity, "schedule_update_ha_state"):
            entity.select_option(PERSON_AIRFLOW_TOWARD)
        device.values[ACAttributes.power.value] = True
        with patch.object(entity, "schedule_update_if_running"):
            entity.update_state({ACAttributes.power.value: True})

        self.assertIsNotNone(loop.delayed_callback)
        loop.run_delayed()
        self.assertEqual(device.person_airflow_calls, [PERSON_AIRFLOW_TOWARD])

    def test_boot_reset_status_does_not_erase_pending_preference(self) -> None:
        """Boot-time off flags must not win before the delayed restore runs."""
        device = FakeACDevice(power=False)
        entity = MideaPersonAirflowSelect(as_midea_device(device), PERSON_AIRFLOW_MODE)
        loop = FakeLoop()
        entity.hass = SimpleNamespace(loop=loop, is_stopping=False)
        entity._last_power = False

        with patch.object(entity, "schedule_update_ha_state"):
            entity.select_option(PERSON_AIRFLOW_TOWARD)
        device.values[ACAttributes.power.value] = True
        with patch.object(entity, "schedule_update_if_running"):
            entity.update_state({ACAttributes.power.value: True})
            entity.update_state(
                {
                    ACAttributes.wind_straight.value: False,
                    ACAttributes.wind_avoid.value: False,
                },
            )

        self.assertEqual(entity.current_option, PERSON_AIRFLOW_TOWARD)
        loop.run_delayed()
        self.assertEqual(device.person_airflow_calls, [PERSON_AIRFLOW_TOWARD])

    def test_reconnect_restores_preference_after_boot_reset_status(self) -> None:
        """An unavailable/available cycle restores even without a power edge."""
        device = FakeACDevice(power=True)
        entity = MideaPersonAirflowSelect(as_midea_device(device), PERSON_AIRFLOW_MODE)
        loop = FakeLoop()
        entity.hass = SimpleNamespace(loop=loop, is_stopping=False)
        entity._last_power = True
        entity._last_available = True

        with patch.object(entity, "schedule_update_ha_state"):
            entity.select_option(PERSON_AIRFLOW_TOWARD)
        device.person_airflow_calls.clear()

        device.available = False
        with patch.object(entity, "schedule_update_if_running"):
            entity.update_state({"available": False})
            entity.update_state(
                {
                    ACAttributes.wind_straight.value: False,
                    ACAttributes.wind_avoid.value: False,
                },
            )
        self.assertEqual(entity.current_option, PERSON_AIRFLOW_TOWARD)

        device.available = True
        with patch.object(entity, "schedule_update_if_running"):
            entity.update_state({"available": True})

        self.assertIsNotNone(loop.delayed_callback)
        loop.run_delayed()
        self.assertEqual(device.person_airflow_calls, [PERSON_AIRFLOW_TOWARD])

    def test_unavailable_selection_waits_for_reconnect(self) -> None:
        """A selection made offline is remembered without a doomed socket write."""
        device = FakeACDevice(power=True)
        device.available = False
        entity = MideaPersonAirflowSelect(as_midea_device(device), PERSON_AIRFLOW_MODE)

        with patch.object(entity, "schedule_update_ha_state"):
            entity.select_option(PERSON_AIRFLOW_AVOID)

        self.assertEqual(entity.current_option, PERSON_AIRFLOW_AVOID)
        self.assertEqual(device.person_airflow_calls, [])

    def test_manual_selection_cancels_pending_power_on_restore(self) -> None:
        """A user command wins over an earlier delayed restore."""
        device = FakeACDevice(power=True)
        entity = MideaPersonAirflowSelect(as_midea_device(device), PERSON_AIRFLOW_MODE)
        pending = FakeTimerHandle()
        entity._restore_handle = cast("TimerHandle", pending)

        with patch.object(entity, "schedule_update_ha_state"):
            entity.select_option(PERSON_AIRFLOW_AVOID)

        self.assertTrue(pending.cancelled)
        self.assertIsNone(entity._restore_handle)
        self.assertEqual(device.person_airflow_calls, [PERSON_AIRFLOW_AVOID])

    def test_manual_off_ignores_stale_active_readback_during_settle(self) -> None:
        """An old device response must not undo a just-requested off state."""
        device = FakeACDevice(power=True)
        device.values[ACAttributes.wind_avoid.value] = True
        entity = MideaPersonAirflowSelect(as_midea_device(device), PERSON_AIRFLOW_MODE)
        entity.hass = SimpleNamespace()

        with (
            patch.object(entity, "schedule_update_ha_state"),
            patch.object(entity, "schedule_update_if_running"),
        ):
            entity.select_option(PERSON_AIRFLOW_OFF)
            entity.update_state({ACAttributes.wind_avoid.value: True})

        self.assertEqual(entity.current_option, PERSON_AIRFLOW_OFF)
        self.assertEqual(device.person_airflow_calls, [PERSON_AIRFLOW_OFF])

        entity._pending_until = 0.0
        with patch.object(entity, "schedule_update_if_running"):
            entity.update_state({ACAttributes.wind_avoid.value: True})
        self.assertEqual(entity.current_option, PERSON_AIRFLOW_AVOID)

    def test_smart_light_switch_uses_model_specific_api(self) -> None:
        """The synthetic switch reads the raw sensor and calls the safe API."""
        device = FakeACDevice(power=False)
        entity = MideaLightSensitiveSwitch(
            as_midea_device(device),
            LIGHT_SENSITIVE_CONTROL,
        )

        self.assertTrue(entity.is_on)
        entity.turn_off()
        entity.turn_on()
        self.assertEqual(device.light_sensitive_calls, [False, True])

    def test_actual_person_airflow_mapping(self) -> None:
        """Avoid wins if a malformed response reports both mutually exclusive flags."""
        device = FakeACDevice(power=True)
        entity = MideaPersonAirflowSelect(as_midea_device(device), PERSON_AIRFLOW_MODE)

        self.assertEqual(entity._actual_option(), PERSON_AIRFLOW_OFF)
        device.values[ACAttributes.wind_straight.value] = True
        self.assertEqual(entity._actual_option(), PERSON_AIRFLOW_TOWARD)
        device.values[ACAttributes.wind_avoid.value] = True
        self.assertEqual(entity._actual_option(), PERSON_AIRFLOW_AVOID)


class FakeRegistry:
    """Entity registry double exposing only two pre-existing AC entities."""

    def __init__(self) -> None:
        """Initialize two registry entries with opposite disabled states."""
        self.entries = {
            "switch.123_sound": SimpleNamespace(
                disabled_by=er.RegistryEntryDisabler.INTEGRATION,
            ),
            "switch.123_prompt_tone": SimpleNamespace(disabled_by=None),
        }
        self.updated: dict[str, er.RegistryEntryDisabler | None] = {}

    def async_get_entity_id(
        self,
        domain: str,
        _platform: str,
        unique_id: str,
    ) -> str | None:
        """Map known unique IDs to registry entity IDs.

        Returns
        -------
        The matching entity ID, if the fake registry contains it.

        """
        key = unique_id.split("123_", maxsplit=1)[-1]
        entity_id = f"{domain}.123_{key}"
        return entity_id if entity_id in self.entries else None

    def async_get(self, entity_id: str) -> SimpleNamespace | None:
        """Return one fake registry entry.

        Returns
        -------
        The matching registry entry, if present.

        """
        return self.entries.get(entity_id)

    def async_update_entity(
        self,
        entity_id: str,
        *,
        disabled_by: er.RegistryEntryDisabler | None,
    ) -> None:
        """Record the registry transition."""
        self.updated[entity_id] = disabled_by


class RegistryReconciliationTests(unittest.TestCase):
    """Verify optional entities are hidden without deleting their registry rows."""

    def test_selected_entity_reenables_and_unselected_entity_disables(self) -> None:
        """Only integration-managed disables are reversed."""
        registry = FakeRegistry()
        config_entry = SimpleNamespace(
            options={CONF_SENSORS: [], CONF_SWITCHES: [ACAttributes.sound.value]},
        )
        device = FakeACDevice(power=False)

        with patch(
            "midea_ac_lan.er.async_get",
            return_value=registry,
        ):
            _reconcile_optional_entity_registry(
                Mock(),
                config_entry,
                as_midea_device(device),
            )

        self.assertEqual(
            registry.updated,
            {
                "switch.123_sound": None,
                "switch.123_prompt_tone": er.RegistryEntryDisabler.INTEGRATION,
            },
        )


if __name__ == "__main__":
    unittest.main()
