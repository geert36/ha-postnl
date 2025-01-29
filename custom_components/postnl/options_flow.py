from homeassistant import config_entries
import voluptuous as vol
from .const import DOMAIN

class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for the integration."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        
        # Default values
        update_interval = self.config_entry.options.get('update_interval', 90)
        
        options_schema = vol.Schema({
            vol.Optional('update_interval', default=update_interval): vol.All(vol.Coerce(int), vol.Range(min=30))
        })
        
        return self.async_show_form(step_id="init", data_schema=options_schema)
