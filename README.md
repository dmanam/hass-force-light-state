This is a custom component for Home Assistant which forces lights to be at the last state HASS set them to. This is useful for low-quality Zigbee networks which end up with lights frequently missing commands or reverting to previous states.

To configure the component, just add a list of lights to be managed to a `force_light_state` section in your `configuration.yaml`.
