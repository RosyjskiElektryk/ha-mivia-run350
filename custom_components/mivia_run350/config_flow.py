"""Config flow for MiVia Run 350."""

from __future__ import annotations

import re
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_ADDRESS

from .const import DOMAIN


class MiViaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MiVia Run 350."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Ask for the BLE address."""
        errors = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", address):
                errors[CONF_ADDRESS] = "invalid_address"
            else:
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="MiVia Run 350",
                    data={CONF_ADDRESS: address},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): str}
            ),
            errors=errors,
        )
