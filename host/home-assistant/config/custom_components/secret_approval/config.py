"""HA configuration and command schemas, with protection for sensitive route logs."""

import logging

from homeassistant.helpers import config_validation as cv
import voluptuous as vol

DOMAIN = "secret_approval"

# check_config loads this schema with stub secrets, so the length rule lives in async_setup.
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required("ask_url"): cv.string,
                vol.Required("answer_url"): cv.string,
                vol.Required("credential"): cv.string,
                vol.Required("operator"): cv.string,
                vol.Required("devices"): vol.All(cv.ensure_list, [cv.slug], vol.Length(min=1)),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


OPEN_COMMAND = {vol.Required("type"): "secret_approval/open"}

DECIDE_COMMAND = {
    vol.Required("type"): "secret_approval/decide",
    # The websocket envelope owns the name id.
    vol.Required("request"): cv.string,
    vol.Required("token"): cv.string,
    vol.Required("decision"): vol.In(("approved", "denied")),
}


def protect_logs(ask_id, answer_id, route):
    # Home Assistant names the webhook ID in its log when it refuses a method or a handler fails.
    logging.getLogger("homeassistant.components.webhook").addFilter(
        lambda record: ask_id not in record.getMessage() and answer_id not in record.getMessage()
    )
    # Home Assistant debug logs include page commands, question text and tokens.
    logging.getLogger("homeassistant.components.websocket_api.http.connection").addFilter(
        lambda record: (
            not any(question.token in record.getMessage() for question in route.questions.values())
        )
    )
