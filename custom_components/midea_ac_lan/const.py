"""Const for Midea Lan."""

from enum import IntEnum
from typing import Any, Final, cast

from homeassistant.const import Platform

DOMAIN = "midea_ac_lan"
COMPONENT = "component"
DEVICES = "devices"

CONF_KEY = "key"
CONF_MODEL = "model"
CONF_SUBTYPE = "subtype"
CONF_ACCOUNT = "account"
CONF_SERVER = "server"
CONF_REFRESH_INTERVAL = "refresh_interval"
CONF_MAC = "mac"
CONF_SN = "sn"

LIGHT_SENSITIVE_CONTROL = "light_sensitive_control"
PERSON_AIRFLOW_MODE = "person_airflow_mode"
PERSON_AIRFLOW_OFF: Final = "off"
PERSON_AIRFLOW_TOWARD: Final = "toward"
PERSON_AIRFLOW_AVOID: Final = "avoid"
PERSON_AIRFLOW_MODES: Final = (
    PERSON_AIRFLOW_OFF,
    PERSON_AIRFLOW_TOWARD,
    PERSON_AIRFLOW_AVOID,
)
MODEL_220F4047: Final = "220F4047"
SUBTYPE_220F4047: Final = 8

EXTRA_SENSOR = [Platform.SENSOR, Platform.BINARY_SENSOR]
EXTRA_SWITCH = [
    Platform.SWITCH,
    Platform.LOCK,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.TIME,
]
EXTRA_CONTROL = [
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.WATER_HEATER,
    Platform.FAN,
    Platform.HUMIDIFIER,
    Platform.LIGHT,
    *EXTRA_SWITCH,
]
ALL_PLATFORM = EXTRA_SENSOR + EXTRA_CONTROL


def supports_model(
    model: object,
    config: dict[str, Any],
    subtype: object | None = None,
) -> bool:
    """Return if the entity config applies to the device model.

    Returns
    -------
    True if the entity is available for the device model.

    """
    models = config.get("models")
    if models and str(model) not in cast("list[str]", models):
        return False
    subtypes = config.get("subtypes")
    if subtypes and subtype not in cast("list[object]", subtypes):
        return False
    excluded_models = config.get("excluded_models")
    excluded_subtypes = config.get("excluded_subtypes")
    return not (
        excluded_models
        and str(model) in cast("list[str]", excluded_models)
        and (
            not excluded_subtypes or subtype in cast("list[object]", excluded_subtypes)
        )
    )


class FanSpeed(IntEnum):
    """FanSpeed reference values."""

    LOW = 20
    MEDIUM = 40
    HIGH = 60
    FULL_SPEED = 80
    AUTO = 100
