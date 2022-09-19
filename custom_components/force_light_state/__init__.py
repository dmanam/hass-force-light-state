import base64
import datetime
import logging
from typing import Any

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    Context,
    Event,
)
from homeassistant.helpers.event import async_track_time_interval
import homeassistant.helpers.config_validation as cv
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_BRIGHTNESS_PCT,
    ATTR_BRIGHTNESS_STEP,
    ATTR_BRIGHTNESS_STEP_PCT,
    ATTR_COLOR_NAME,
    ATTR_COLOR_TEMP,
    ATTR_HS_COLOR,
    ATTR_KELVIN,
    ATTR_RGB_COLOR,
    ATTR_SUPPORTED_COLOR_MODES,
    ATTR_TRANSITION,
    ATTR_XY_COLOR,
    COLOR_MODE_BRIGHTNESS,
    COLOR_MODE_COLOR_TEMP,
    COLOR_MODE_HS,
    COLOR_MODE_RGB,
    COLOR_MODE_RGBW,
    COLOR_MODE_XY,
)
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import (
    ATTR_AREA_ID,
    ATTR_DOMAIN,
    ATTR_ENTITY_ID,
    ATTR_SERVICE,
    ATTR_SERVICE_DATA,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    EVENT_CALL_SERVICE,
)

import voluptuous as vol

from .const import *

# large portions of this taken from adaptive_lighting

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: list},
    extra=vol.ALLOW_EXTRA
)
def _int_to_bytes(i: int, signed: bool = False) -> bytes:
    bits = i.bit_length()
    if signed:
        # Make room for the sign bit.
        bits += 1
    return i.to_bytes((bits + 7) // 8, "little", signed=signed)

class Forcer:
    def __init__(self, hass, lights):
        self.hass = hass
        self.lights = {light: {} for light in lights}
        self._context_cnt = 0

    async def call_service_listener(self, event: Event) -> None:
        domain = event.data.get(ATTR_DOMAIN)
        if domain != LIGHT_DOMAIN:
            return

        service = event.data[ATTR_SERVICE]
        service_data = event.data[ATTR_SERVICE_DATA]
        if ATTR_ENTITY_ID in service_data:
            entity_ids = cv.ensure_list_csv(service_data[ATTR_ENTITY_ID])
        elif ATTR_AREA_ID in service_data:
            area_ids = cv.ensure_list_csv(service_data[ATTR_AREA_ID])
            entity_ids = []
            for area_id in area_ids:
                area_entity_ids = area_entities(self.hass, area_id)
                for entity_id in area_entity_ids:
                    if entity_id.startswith(LIGHT_DOMAIN):
                        entity_ids.append(entity_id)
                _LOGGER.debug(
                    "Found entity_ids '%s' for area_id '%s'", entity_ids, area_id
                )
        else:
            _LOGGER.debug(
                "No entity_ids or area_ids found in service_data: %s", service_data
            )
            return

        if not any(eid in self.lights for eid in entity_ids):
            return

        if service == SERVICE_TURN_OFF:
            _LOGGER.debug(
                "Detected an 'light.turn_off('%s')' event with context.id='%s'",
                entity_ids,
                event.context.id,
            )
            for eid in entity_ids:
                self.lights[eid] = {"state": "off"}
        elif service == SERVICE_TURN_ON:
            _LOGGER.debug(
                "Detected an 'light.turn_on('%s')' event with context.id='%s'",
                entity_ids,
                event.context.id,
            )
            for eid in entity_ids:
                self.lights[eid]["state"] = "on"
                sdata = event.data[ATTR_SERVICE_DATA]
                for attr in [ATTR_BRIGHTNESS, ATTR_COLOR_TEMP]:
                    if attr in sdata:
                        self.lights[eid][attr] = sdata[attr]

    def create_context(self):
        cnt_packed = base64.b85encode(_int_to_bytes(self._context_cnt, signed=False))
        self._context_cnt += 1
        cid = f"{ADAPTIVE_DOMAIN_SHORT}:forcer:{cnt_packed}"[:36]
        return Context(id=cid)

    async def time_interval_listener(self, now=None) -> None:
        for light, saved in self.lights.items():
            if "state" not in saved:
                continue
            curr = self.hass.states.get(light)
            do_fix = False
            service_data = {ATTR_ENTITY_ID: light}
            if curr.state != saved["state"]:
                if saved["state"] == "off":
                    _LOGGER.debug(
                        "Turning off '%s'",
                        light,
                    )
                    await self.hass.services.async_call(LIGHT_DOMAIN, SERVICE_TURN_OFF, service_data)
                    return
                else:
                    do_fix = True
            attrs = [ATTR_BRIGHTNESS, ATTR_COLOR_TEMP]
            for attr in attrs:
                if attr in saved and attr in curr.attributes:
                    diff = curr.attributes[attr] - saved[attr]
                    if diff > 10 or diff < -10:
                        do_fix = True
            if not do_fix:
                continue
            for attr in attrs:
                if attr in saved:
                    service_data[attr] = saved[attr]
            context = self.create_context()
            _LOGGER.debug(
                "Scheduling 'light.turn_on' with the following 'service_data': %s"
                " with context.id='%s'",
                service_data,
                context.id,
            )
            await self.hass.services.async_call(LIGHT_DOMAIN, SERVICE_TURN_ON, service_data, context=context)

async def async_setup(hass: HomeAssistant, config: dict[str, list]):
    """Import integration from config."""

    if DOMAIN in config:
        data = hass.data.setdefault(DOMAIN, {})
        data["forcer"] = Forcer(hass, config[DOMAIN])
        hass.bus.async_listen(EVENT_CALL_SERVICE, data["forcer"].call_service_listener)
        async_track_time_interval(hass, data["forcer"].time_interval_listener, datetime.timedelta(milliseconds=CHECK_INTERVAL))

    return True

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    return True


async def async_update_options(hass, config_entry: ConfigEntry):
    """Update options."""
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_unload_entry(hass, config_entry: ConfigEntry) -> bool:
    return True
