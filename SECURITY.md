# Security policy

## Supported versions

Security fixes are released for the latest published version. Upgrade through
HACS before reporting a problem that may already be fixed.

## Reporting a vulnerability

Please use this repository's private
[GitHub security advisory form](https://github.com/burren2025/HATailscaleTrust/security/advisories/new)
instead of a public issue. Include the affected version, impact, and safe
reproduction steps. Never include a real OAuth client secret, access token,
tailnet identifier, diagnostics file, or unredacted Home Assistant log.

Revoke a credential immediately in the Tailscale admin console if you believe it
was exposed. Create a replacement read-only trust credential and use Home
Assistant's reauthentication flow to update the existing config entry.

## Credential model

The integration requests only `devices:core:read devices:routes:read`. It stores
the OAuth client credential in Home Assistant's protected config-entry storage,
keeps short-lived access tokens in memory, redacts identifying topology from
diagnostics, and never logs API response bodies.
