"""Tests for the model-gated 310A2111 refrigerator flex-zone mode."""

# unittest is intentional because this integration does not depend on pytest.
# ruff: file-ignore[import-private-name, pytest-unittest-assertion, unsorted-imports, module-import-not-at-top-of-file]

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from midealan.device import MideaDevice

CUSTOM_COMPONENTS_ROOT = Path(__file__).parents[1] / "custom_components"
sys.path.insert(0, str(CUSTOM_COMPONENTS_ROOT))

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import Platform

from midealan.devices.ca import DeviceAttributes as CAAttributes

from midea_ac_lan.sensor import (
    FLEX_ZONE_MODE_BY_TEMPERATURE,
    MideaCA310A2111FlexZoneModeSensor,
    MideaSensor,
    _create_sensor,
)
from midea_ac_lan.const import supports_model
from midea_ac_lan.midea_devices import MIDEA_DEVICES


PROTOCOL_DIAGNOSTIC_ATTRIBUTES = (
    CAAttributes.code_mode,
    CAAttributes.freezing_mode,
    CAAttributes.smart_mode,
    CAAttributes.energy_saving_mode,
    CAAttributes.holiday_mode,
    CAAttributes.moisturize_mode,
    CAAttributes.preservation_mode,
    CAAttributes.acme_freezing_mode,
    CAAttributes.flood_light,
    CAAttributes.freezing_ice_machine_power,
)


class FakeRefrigeratorDevice:
    """Small refrigerator double covering the sensor-facing public surface."""

    device_type = 0xCA
    device_id = 456
    name = "Test Refrigerator"
    model = "310A2111"
    subtype = 56
    mac = None
    serial_number = None
    available = True

    def __init__(self, temperature: float | None = 2.0) -> None:
        """Initialize with an explicit flex-zone setting temperature."""
        self.temperature = temperature

    def get_attribute(self, attribute: object) -> float | str | None:
        """Return the flex-zone attributes used by the entity.

        Returns
        -------
        The stored temperature, generic raw mode, or ``None``.

        """
        if attribute == CAAttributes.flex_zone_setting_temp:
            return self.temperature
        if attribute == CAAttributes.variable_mode:
            return "none"
        return None

    def register_update(self, _update: object) -> None:
        """Satisfy MideaEntity's callback surface."""

    def unregister_update(self, _update: object) -> None:
        """Satisfy MideaEntity's callback surface."""


def as_midea_device(device: FakeRefrigeratorDevice) -> MideaDevice:
    """Type the deliberately small double as the public device base class.

    Returns
    -------
    The unchanged refrigerator double narrowed for static analysis.

    """
    return cast("MideaDevice", device)


class RefrigeratorFlexZoneModeTests(unittest.TestCase):
    """Verify exact model selection and the three real-device mode mappings."""

    def test_verified_temperature_presets_map_to_enum_states(self) -> None:
        """The three App presets map from their observed setting temperatures."""
        device = FakeRefrigeratorDevice()
        entity = MideaCA310A2111FlexZoneModeSensor(
            as_midea_device(device),
            CAAttributes.variable_mode,
        )

        for temperature, expected in FLEX_ZONE_MODE_BY_TEMPERATURE.items():
            with self.subTest(temperature=temperature):
                device.temperature = temperature
                self.assertEqual(entity.native_value, expected)

        self.assertEqual(entity.device_class, SensorDeviceClass.ENUM)
        self.assertEqual(entity.options, list(FLEX_ZONE_MODE_BY_TEMPERATURE.values()))

    def test_unknown_temperature_does_not_guess_a_mode(self) -> None:
        """An unverified setting remains unknown instead of being mislabeled."""
        device = FakeRefrigeratorDevice(temperature=3.0)
        entity = MideaCA310A2111FlexZoneModeSensor(
            as_midea_device(device),
            CAAttributes.variable_mode,
        )

        self.assertIsNone(entity.native_value)
        device.temperature = None
        self.assertIsNone(entity.native_value)

    def test_factory_selects_specialized_sensor_only_for_exact_device(self) -> None:
        """Other refrigerator models and subtypes retain the generic sensor."""
        config = {"type": Platform.SENSOR}
        target = FakeRefrigeratorDevice()
        target_entity = _create_sensor(
            as_midea_device(target),
            CAAttributes.variable_mode,
            config,
        )
        self.assertIsInstance(target_entity, MideaCA310A2111FlexZoneModeSensor)

        target.model = "other"
        other_model = _create_sensor(
            as_midea_device(target),
            CAAttributes.variable_mode,
            config,
        )
        self.assertIs(type(other_model), MideaSensor)

        target.model = "310A2111"
        target.subtype = 1
        other_subtype = _create_sensor(
            as_midea_device(target),
            CAAttributes.variable_mode,
            config,
        )
        self.assertIs(type(other_subtype), MideaSensor)

    def test_verified_modes_have_english_and_chinese_ui_labels(self) -> None:
        """Every emitted enum state has an English and Chinese translation."""
        translations_root = CUSTOM_COMPONENTS_ROOT / "midea_ac_lan" / "translations"
        expected = {
            "en.json": {
                "mother_infant": "Mother & Infant",
                "treasure": "Treasure",
                "zero_degree": "Zero Degree",
            },
            "zh-Hans.json": {
                "mother_infant": "母婴",
                "treasure": "珍品",
                "zero_degree": "零度",
            },
        }

        for filename, labels in expected.items():
            with self.subTest(filename=filename):
                document = json.loads(
                    (translations_root / filename).read_text(encoding="utf-8"),
                )
                states = document["entity"]["sensor"]["variable_mode"]["state"]
                self.assertEqual(states, labels)

    def test_diagnostics_and_right_zone_cleanup_are_exact_model_gated(self) -> None:
        """Only the target refrigerator gains probes and loses the invalid zone."""
        entities = cast("dict", MIDEA_DEVICES[0xCA]["entities"])

        for attribute in PROTOCOL_DIAGNOSTIC_ATTRIBUTES:
            with self.subTest(attribute=attribute):
                config = entities[attribute]
                self.assertEqual(config["type"], Platform.BINARY_SENSOR)
                self.assertTrue(config["default"])
                self.assertTrue(config["raw_value"])
                self.assertEqual(config["required_attribute"], attribute)
                self.assertNotIn("set_message", config)
                self.assertTrue(supports_model("310A2111", config, 56))
                self.assertFalse(supports_model("310A2111", config, 1))
                self.assertFalse(supports_model("other", config, 56))

        for attribute in (
            CAAttributes.right_flex_zone_actual_temp,
            CAAttributes.right_flex_zone_setting_temp,
        ):
            with self.subTest(attribute=attribute):
                config = entities[attribute]
                self.assertFalse(supports_model("310A2111", config, 56))
                self.assertTrue(supports_model("310A2111", config, 1))
                self.assertTrue(supports_model("other", config, 56))

    def test_diagnostic_probes_have_neutral_english_and_chinese_labels(self) -> None:
        """Probe labels expose protocol keys without claiming App semantics."""
        translations_root = CUSTOM_COMPONENTS_ROOT / "midea_ac_lan" / "translations"
        expected_prefixes = {
            "en.json": "Protocol bit: ",
            "zh-Hans.json": "协议位\uff1a",
        }

        for filename, prefix in expected_prefixes.items():
            with self.subTest(filename=filename):
                document = json.loads(
                    (translations_root / filename).read_text(encoding="utf-8"),
                )
                labels = document["entity"]["binary_sensor"]
                for attribute in PROTOCOL_DIAGNOSTIC_ATTRIBUTES:
                    key = f"ca_protocol_{attribute.value}"
                    self.assertEqual(labels[key]["name"], f"{prefix}{attribute.value}")


if __name__ == "__main__":
    unittest.main()
