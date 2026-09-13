# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-09-14

### Added

- Config flow with zeroconf/DHCP discovery, one-button claim with automatic detection of the
  account to copy rooms and names from (`admin`, then `installer`), reauth, reconfigure and
  options.
- Websocket push updates with automatic reconnect and REST reconciliation polling.
- Cover platform for motor loads with smart relative tilt (single tilt-step commands,
  verification and correction), number entity for the raw tilt step, services
  `set_tilt_steps`, `set_target_state`, `load_ctrl`, `refresh_structure`.
- Light (on/off, dim, DALI tunable white, RGBW), switch (loads and system flags), scene,
  sensor, binary sensor, climate, event (wall buttons) and button platforms; device triggers
  for wall buttons.
- Gateway device with diagnostic sensors, repairs, diagnostics download, German and English
  translations.
- Fake µGateway simulator for tests and local development.
