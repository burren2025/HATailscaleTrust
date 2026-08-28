# Tailscale Trust for Home Assistant

Tailscale Trust is a Home Assistant custom integration that monitors every device
in a Tailscale tailnet with a long-lived OAuth trust credential. It replaces the
manually rotated, fully permitted API access token used by Home Assistant's
built-in Tailscale integration with the narrow `devices:core:read` and
`devices:routes:read` scopes.

The integration never asks for or uses a write scope. Its one-hour access tokens
are cached only in memory, refreshed before expiry, and recreated automatically.

## Entities

Each Tailscale device gets:

| Platform | Entity | Built-in equivalent |
| --- | --- | --- |
| Binary sensor | Online | New |
| Sensor | Last seen | Yes |
| Sensor | Tailscale IP | Yes |
| Sensor | Key expiration | Yes |
| Binary sensor | Client update available | Yes |
| Binary sensor | Key expiry disabled | Yes |
| Binary sensor | Client supports IPv6 | Yes |
| Binary sensor | Client supports PCP | Yes |
| Binary sensor | Client supports PMP | Yes |
| Binary sensor | Client supports UDP | Yes |
| Binary sensor | Client supports UPnP | Yes |
| Sensor | Advertised routes (count plus exact CIDRs) | New |
| Sensor | Enabled routes (count plus exact CIDRs) | New |
| Binary sensor | Exit node advertised | New |
| Binary sensor | Exit node enabled | New |
| Binary sensor | Subnet routes advertised | New |
| Binary sensor | Route approval required | New |

Unique IDs use Tailscale's immutable `nodeId`, not a device name. Renaming a
device therefore updates its displayed device name without duplicating its
entities. A device re-enrolled as a genuinely new Tailscale node receives new
entities. If an older API response omits `nodeId`, the legacy numeric `id` is the
compatibility fallback.

### Online state

The integration requests `fields=all` and uses the Devices API's
`connectedToControl` boolean when present. Tailscale defines `lastSeen` as absent
while a device is connected to the control plane, making
`connectedToControl` the authoritative API connectivity signal available to a
remote Home Assistant instance.

For compatibility with an API response that omits that field, the fallback is:

- online when `lastSeen` is no more than five minutes old;
- offline when it is older than five minutes;
- unavailable when neither value is present.

Diagnostics report `online_source` as `connected_to_control`,
`recent_last_seen_fallback`, or `unknown`, so the semantics are auditable. If a
previously known device disappears from a successful device-list response, its
online sensor remains available and reports off. Its other sensors become
unavailable. The registry record is retained so a temporary absence or later
return cannot create duplicates.

### Route state

For every device, the integration reads Tailscale's dedicated route-settings
endpoint. The advertised and enabled route sensors use a numeric count for
automation-friendly states and expose the exact CIDRs in their `routes`
attribute. Exit-node routes are the IPv4 and IPv6 default routes
(`0.0.0.0/0` and `::/0`). The **Route approval required** problem sensor turns
on whenever a device advertises a route that is not enabled in the tailnet.

Route state is control-plane configuration. It does not prove that IP
forwarding or a routed destination is reachable end to end.

## Create the least-privilege trust credential

Never paste a real client secret into a source file, issue, test, log, or chat.
Enter it only in Home Assistant's masked setup form.

1. Sign in to the Tailscale admin console and open
   [Trust credentials](https://console.tailscale.com/admin/settings/trust-credentials).
2. Select **Credential**, then **OAuth**.
3. In the operations list, expand **Devices**.
4. Under **Core**, select **Read** only (`devices:core:read`).
5. Under **Routes**, select **Read** only (`devices:routes:read`).
6. Leave every Write box and all other scopes unchecked. Do not select
   `all:read` or `all`.
7. Select **Generate credential**.
8. Copy the client ID and client secret to a password manager. Tailscale shows
   the secret only once.
9. Find the tailnet identifier on the admin console's **General** page. The `-`
   shorthand also works, but the explicit identifier gives the Home Assistant
   entry a clearer name.
10. In Home Assistant, open **Settings > Devices & services > Add integration**,
   search for **Tailscale Trust**, and enter the tailnet identifier, client ID,
   and client secret.

The setup validation exchanges the credential for an access token, calls
`GET /api/v2/tailnet/{tailnet}/devices?fields=all`, and reads
`GET /api/v2/device/{nodeId}/routes` for each returned device. It never writes
route settings.

## Installation

### Manual

1. Download this repository.
2. Copy `custom_components/tailscale_trust` into the Home Assistant config
   directory as `config/custom_components/tailscale_trust`.
3. Restart Home Assistant.
4. Add **Tailscale Trust** from **Settings > Devices & services**.

The final path must contain `manifest.json` directly under
`custom_components/tailscale_trust`.

### HACS custom repository

1. Open HACS, select the three-dot menu, then **Custom repositories**.
2. Paste `https://github.com/burren2025/HATailscaleTrust` and choose the
   **Integration** category.
3. Download **Tailscale Trust** and restart Home Assistant.
4. Add it from **Settings > Devices & services**.

The repository includes `hacs.json` and the standard custom-integration layout;
it does not require a separate Python package.

### Upgrades through HACS

Stable versions are published as GitHub releases with semantic tags such as
`v0.2.0`. HACS uses the latest published release tag as the remote version; a
tag without a published release is not sufficient. In HACS, open the Tailscale
Trust repository menu and select **Update information** to force an immediate
GitHub refresh if the update entity has not refreshed yet. Download the offered
version and restart Home Assistant.

## Safe migration from the built-in integration

This project intentionally uses the distinct `tailscale_trust` integration
domain. A custom component that shadows Home Assistant's built-in `tailscale`
domain would need to interpret the built-in API-key config entry, override code
shipped with Home Assistant, and remain synchronized with core internals. That is
not a supportable migration boundary. No `.storage` file should be edited.

Home Assistant's entity IDs live in platform-wide namespaces such as `sensor`
and `binary_sensor`, so side-by-side entities may initially receive a suffix such
as `_2`. Use this reversible UI-only procedure:

1. Back up Home Assistant and record the built-in Tailscale entity IDs and any
   custom display names. Do not copy credentials into the record.
2. Install Tailscale Trust while leaving the built-in integration enabled.
3. Verify its devices and online sensors, especially remote tablets, KVMs,
   subnet routers, and exit nodes, for at least several polling cycles.
4. For each old entity used by a dashboard or automation, rename the old entity
   ID in **Settings > Devices & services > Entities** by adding `_legacy`.
5. Rename the matching Tailscale Trust entity to the old entity's exact former
   ID. Existing references then resolve to the new entity without editing
   `.storage`.
6. Copy any custom display names to the new entities. Repeat for all referenced
   entities.
7. Disable the built-in integration for a validation period. Once satisfied,
   delete its config entry and revoke/delete the old API access token in
   Tailscale.

Changing an entity ID in the UI frees the old ID; Home Assistant does not
automatically transfer registry customizations between different integration
domains. Reusing the exact old ID preserves string-based dashboard and automation
references. Custom icons, areas, disabled/enabled state, and display names require
one-time copying. Once the new entity is established, all of those customizations
survive future Tailscale Trust upgrades and device renames because its unique ID
is stable.

### Entity mapping

| Built-in entity key | Tailscale Trust entity key |
| --- | --- |
| `expires` | `expires` |
| `ip` | `ip` |
| `last_seen` | `last_seen` |
| `update_available` | `update_available` |
| `key_expiry_disabled` | `key_expiry_disabled` |
| `client_supports_ipv6` | `client_supports_ipv6` |
| `client_supports_pcp` | `client_supports_pcp` |
| `client_supports_pmp` | `client_supports_pmp` |
| `client_supports_udp` | `client_supports_udp` |
| `client_supports_upnp` | `client_supports_upnp` |
| No equivalent | `online` |

Map by Tailscale device name and entity key, not by the integration's internal
unique ID: recent built-in releases may use the legacy numeric device ID, while
this integration deliberately prefers `nodeId`.

## Architecture and security

- Home Assistant stores the tailnet ID, OAuth client ID, and OAuth client secret
  in the config entry. Home Assistant administrators should protect backups and
  the config directory as they would any other integration credential.
- Diagnostics recursively redact both the client ID and client secret. API error
  bodies are never logged or included in exceptions.
- OAuth exchange uses the client-credentials grant at
  `https://api.tailscale.com/api/v2/oauth/token` and explicitly requests only
  `devices:core:read devices:routes:read`.
- Access tokens are held only in memory. The cache uses monotonic time and a
  60-second early-refresh margin to tolerate wall-clock skew.
- A device API 401 discards the token, exchanges the OAuth credential again, and
  retries once. A second 401, revoked client, or lost scope raises Home
  Assistant's config-entry authentication failure, preserving the config entry
  and opening its reauthentication repair flow.
- One coordinator polls once per minute and shares data across all entities.
- New devices are discovered after setup. Missing devices remain registered and
  offline; reappearance under the same `nodeId` reuses the same entities.

## Development

Use Python 3.13 or newer:

```shell
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements_test.txt
ruff check .
pytest
```

Tests cover setup and reauthentication flows, OAuth caching and refresh, 401
retries on both device and route reads, revoked credentials, missing scopes,
route parsing and entity state, coordinator reconciliation, authoritative and
fallback online state, stable unique IDs, entity coverage, and diagnostics
redaction. GitHub Actions also runs HACS's own integration repository validator.

## Known limitations

- The integration monitors the Tailscale control-plane connection, not whether a
  particular peer-to-peer path or advertised subnet is usable from Home
  Assistant. Tailscale does not expose the local CLI's peer `Online` field through
  the remote Devices API; `connectedToControl` is the best authoritative remote
  field currently available.
- Route reads add one API request per device per polling cycle. Requests run
  concurrently, but very large tailnets generate more API traffic than the
  device-only integration.
- The route API reports advertised and enabled control-plane routes. It does not
  confirm kernel IP forwarding, peer selection, or end-to-end reachability.
- Permanent device removal is indistinguishable from a temporary omission in a
  single poll. The integration keeps the registry entries offline rather than
  destructively deleting customizations. Users can remove permanently stale
  devices from Home Assistant's device registry after confirming removal.

## References

- [Tailscale trust credentials](https://tailscale.com/docs/reference/trust-credentials)
- [Tailscale OAuth clients](https://tailscale.com/docs/features/oauth-clients)
- [Home Assistant Tailscale integration](https://www.home-assistant.io/integrations/tailscale)
- [Home Assistant Tailscale source](https://github.com/home-assistant/core/tree/dev/homeassistant/components/tailscale)
