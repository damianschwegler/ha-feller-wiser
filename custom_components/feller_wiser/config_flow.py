"""Config flow: discovery, one-button claim with source detection, reauth, options."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
import voluptuous as vol

from .api import (
    DEFAULT_API_USER,
    ApiLockedError,
    ClaimResult,
    ClaimTimeoutError,
    NoSiteInfoError,
    NotAWiserGatewayError,
    SourceNotFoundError,
    UnauthorizedError,
    WiserApiError,
    WiserClient,
    WiserConnectionError,
    claim_with_source_detection,
    normalize_host,
)
from .const import (
    CONF_SERIAL,
    CONF_SOURCE,
    CONF_TOKEN,
    CONF_USERNAME,
    DEFAULT_CLICK_MARGIN_MS,
    DEFAULT_FALLBACK_CLICK_PAUSE_MS,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_READ_MOTOR_CONFIG,
    DEFAULT_REGISTER_BUTTONS,
    DEFAULT_ROOMS_AS_AREAS,
    DEFAULT_TILT_FALLBACK_REFERENCE,
    DEFAULT_TILT_MAX_ROUNDS,
    DEFAULT_TILT_MODE,
    DEFAULT_TILT_SETTLE_MS,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    OPT_CLICK_MARGIN_MS,
    OPT_FALLBACK_CLICK_PAUSE_MS,
    OPT_POLL_INTERVAL,
    OPT_READ_MOTOR_CONFIG,
    OPT_REGISTER_BUTTONS,
    OPT_ROOMS_AS_AREAS,
    OPT_TILT_FALLBACK_REFERENCE,
    OPT_TILT_MAX_ROUNDS,
    OPT_TILT_MODE,
    OPT_TILT_SETTLE_MS,
    TILT_MODES,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})
STEP_USER_ADVANCED_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_USERNAME, default=DEFAULT_API_USER): str,
    }
)


class WiserConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the setup of one µGateway."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Flow state."""
        self._host: str = ""
        self._sn: str = ""
        self._name: str = ""
        self._username: str = DEFAULT_API_USER
        self._claim_task: asyncio.Task[ClaimResult] | None = None
        self._claim_result: ClaimResult | None = None
        self._claim_error: str | None = None
        self._claim_attempt: str | None = None

    # ------------------------------------------------------------------ helpers
    def _client(self, host: str) -> WiserClient:
        return WiserClient(host, async_get_clientsession(self.hass))

    async def _async_probe(self, host: str) -> str | None:
        """Return an error key or ``None`` and remember sn/name."""
        client = self._client(host)
        try:
            info = await client.get_info()
        except NotAWiserGatewayError:
            return "not_wiser_gateway"
        except WiserConnectionError:
            return "cannot_connect"
        except WiserApiError:
            return "not_wiser_gateway"
        try:
            site = await client.get_site()
            self._name = site.name
        except WiserApiError, WiserConnectionError:
            self._name = ""
        self._host = client.host
        self._sn = info.sn
        if not self._name:
            self._name = f"Wiser {info.sn}"
        return None

    @property
    def _placeholders(self) -> dict[str, str]:
        return {"name": self._name, "sn": self._sn, "host": self._host, "timeout": "30"}

    # ------------------------------------------------------------------ user
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manual entry of the host."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._username = user_input.get(CONF_USERNAME, DEFAULT_API_USER) or DEFAULT_API_USER
            error = await self._async_probe(normalize_host(user_input[CONF_HOST]))
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(self._sn)
                self._abort_if_unique_id_configured(updates={CONF_HOST: self._host})
                return await self.async_step_claim()
        schema = STEP_USER_ADVANCED_SCHEMA if self.show_advanced_options else STEP_USER_SCHEMA
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                schema, user_input or {CONF_HOST: self._host}
            ),
            errors=errors,
        )

    # ------------------------------------------------------------------ discovery
    async def _async_handle_discovery(self, host: str) -> ConfigFlowResult:
        error = await self._async_probe(host)
        if error:
            return self.async_abort(reason=error)
        await self.async_set_unique_id(self._sn)
        self._abort_if_unique_id_configured(updates={CONF_HOST: self._host})
        self.context["title_placeholders"] = {"name": self._name, "sn": self._sn}
        return await self.async_step_discovery_confirm()

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> ConfigFlowResult:
        """mDNS: ``wiser-<sn>._http._tcp.local.``."""
        host = discovery_info.host
        if discovery_info.port and discovery_info.port != 80:
            host = f"{host}:{discovery_info.port}"
        return await self._async_handle_discovery(host)

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        """DHCP: hostname ``wiser-*``."""
        return await self._async_handle_discovery(discovery_info.ip)

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask before claiming a discovered gateway."""
        if user_input is not None:
            return await self.async_step_claim()
        return self.async_show_form(
            step_id="discovery_confirm", description_placeholders=self._placeholders
        )

    # ------------------------------------------------------------------ claim
    async def _async_claim(self) -> ClaimResult:
        client = self._client(self._host)

        def _attempt(source: str | None) -> None:
            self._claim_attempt = source

        return await claim_with_source_detection(client, self._username, on_attempt=_attempt)

    async def async_step_claim(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Progress step: the user presses a button on the gateway within 30 s."""
        if self._claim_task is None:
            self._claim_result = None
            self._claim_error = None
            self._claim_task = self.hass.async_create_task(self._async_claim())
        if not self._claim_task.done():
            return self.async_show_progress(
                step_id="claim",
                progress_action="claim_press_button",
                progress_task=self._claim_task,
                description_placeholders=self._placeholders,
            )
        try:
            self._claim_result = self._claim_task.result()
        except ClaimTimeoutError:
            self._claim_error = "claim_timeout"
        except ApiLockedError:
            self._claim_error = "api_locked"
        except NoSiteInfoError:
            self._claim_error = "no_site_info"
        except SourceNotFoundError:
            self._claim_error = "invalid_source"
        except WiserConnectionError:
            self._claim_error = "cannot_connect"
        except WiserApiError as err:
            _LOGGER.warning("Claim failed: %s", err)
            self._claim_error = "unknown"
        finally:
            self._claim_task = None
        if self._claim_error:
            return self.async_show_progress_done(next_step_id="claim_failed")
        return self.async_show_progress_done(next_step_id="claim_done")

    async def async_step_claim_failed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the error and offer to try again."""
        if user_input is not None:
            return await self.async_step_claim()
        return self.async_show_form(
            step_id="claim_failed",
            errors={"base": self._claim_error or "unknown"},
            description_placeholders=self._placeholders,
        )

    async def async_step_claim_done(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create or update the entry."""
        result = self._claim_result
        if result is None:
            return self.async_abort(reason="unknown")
        data = {
            CONF_HOST: self._host,
            CONF_TOKEN: result.secret,
            CONF_USERNAME: self._username,
            CONF_SOURCE: result.source,
            CONF_SERIAL: self._sn,
        }
        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data_updates=data)
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(), data_updates=data
            )
        return self.async_create_entry(title=self._name, data=data)

    # ------------------------------------------------------------------ reauth
    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Token was rejected: claim again."""
        entry = self._get_reauth_entry()
        self._host = entry.data[CONF_HOST]
        self._username = entry.data.get(CONF_USERNAME, DEFAULT_API_USER)
        self._sn = entry.unique_id or entry.data.get(CONF_SERIAL, "")
        self._name = entry.title
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Explain that a button press is needed."""
        if user_input is not None:
            error = await self._async_probe(self._host)
            if error:
                return self.async_show_form(
                    step_id="reauth_confirm",
                    errors={"base": error},
                    description_placeholders=self._placeholders,
                )
            return await self.async_step_claim()
        return self.async_show_form(
            step_id="reauth_confirm", description_placeholders=self._placeholders
        )

    # ------------------------------------------------------------------ reconfigure
    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the host; keep the token if it still works."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = normalize_host(user_input[CONF_HOST])
            error = await self._async_probe(host)
            if error:
                errors["base"] = error
            elif self._sn != entry.unique_id:
                return self.async_abort(reason="wrong_device")
            else:
                client = WiserClient(
                    host, async_get_clientsession(self.hass), token=entry.data[CONF_TOKEN]
                )
                try:
                    await client.get_account()
                except UnauthorizedError:
                    self._username = entry.data.get(CONF_USERNAME, DEFAULT_API_USER)
                    return await self.async_step_claim()
                except WiserApiError, WiserConnectionError:
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_update_reload_and_abort(entry, data_updates={CONF_HOST: host})
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input or {CONF_HOST: entry.data[CONF_HOST]}
            ),
            errors=errors,
        )

    # ------------------------------------------------------------------ options
    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> WiserOptionsFlow:
        """Options."""
        return WiserOptionsFlow()


class WiserOptionsFlow(OptionsFlow):
    """Polling, buttons, areas and tilt behaviour."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Single options form."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    OPT_POLL_INTERVAL, default=options.get(OPT_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_POLL_INTERVAL,
                        max=MAX_POLL_INTERVAL,
                        step=10,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
                vol.Optional(
                    OPT_REGISTER_BUTTONS,
                    default=options.get(OPT_REGISTER_BUTTONS, DEFAULT_REGISTER_BUTTONS),
                ): BooleanSelector(),
                vol.Optional(
                    OPT_ROOMS_AS_AREAS,
                    default=options.get(OPT_ROOMS_AS_AREAS, DEFAULT_ROOMS_AS_AREAS),
                ): BooleanSelector(),
                vol.Optional(
                    OPT_TILT_MODE, default=options.get(OPT_TILT_MODE, DEFAULT_TILT_MODE)
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=TILT_MODES,
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="tilt_mode",
                    )
                ),
                vol.Optional(
                    OPT_CLICK_MARGIN_MS,
                    default=options.get(OPT_CLICK_MARGIN_MS, DEFAULT_CLICK_MARGIN_MS),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=2000,
                        step=50,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="ms",
                    )
                ),
                vol.Optional(
                    OPT_FALLBACK_CLICK_PAUSE_MS,
                    default=options.get(
                        OPT_FALLBACK_CLICK_PAUSE_MS, DEFAULT_FALLBACK_CLICK_PAUSE_MS
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=100,
                        max=5000,
                        step=50,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="ms",
                    )
                ),
                vol.Optional(
                    OPT_TILT_SETTLE_MS,
                    default=options.get(OPT_TILT_SETTLE_MS, DEFAULT_TILT_SETTLE_MS),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=10000,
                        step=100,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="ms",
                    )
                ),
                vol.Optional(
                    OPT_TILT_MAX_ROUNDS,
                    default=options.get(OPT_TILT_MAX_ROUNDS, DEFAULT_TILT_MAX_ROUNDS),
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=5, step=1, mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    OPT_TILT_FALLBACK_REFERENCE,
                    default=options.get(
                        OPT_TILT_FALLBACK_REFERENCE, DEFAULT_TILT_FALLBACK_REFERENCE
                    ),
                ): BooleanSelector(),
                vol.Optional(
                    OPT_READ_MOTOR_CONFIG,
                    default=options.get(OPT_READ_MOTOR_CONFIG, DEFAULT_READ_MOTOR_CONFIG),
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
