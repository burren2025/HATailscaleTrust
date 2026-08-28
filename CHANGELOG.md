# Changelog

All notable changes to Tailscale Trust are documented here. Releases follow
[Semantic Versioning](https://semver.org/).

## 0.4.0 - 2026-08-28

### Least privilege and API efficiency

- Read advertised and enabled routes from the existing all-fields device-list
  response, eliminating every per-device route request.
- Reduce the requested OAuth access from two scopes to only
  `devices:core:read`; `devices:routes:read` is no longer required.
- Remove the route cache, batching, separate route cadence, and route-specific
  failure paths made unnecessary by the single-response design.

### Device lifecycle and compatibility

- Enable Home Assistant's device delete action for a retained device only after
  that device is absent from a successful Tailscale list response.
- Protect devices still present in Tailscale from accidental registry deletion.
- Test both the minimum supported Home Assistant 2025.12/Python 3.13 combination
  and the current Home Assistant/Python 3.14 combination in CI.
- Document current Home Assistant support for integration-local brand assets.

## 0.3.0 - 2026-08-27

### Security and privacy

- Remove tailnet identifiers, config-entry identity, node IDs, names, hostnames,
  IP addresses, and route CIDRs from downloaded diagnostics.
- Replace diagnostic device identity with per-download pseudonymous numbering.
- Handle `429 Too Many Requests`, honor sanitized `Retry-After` values, and use
  bounded exponential backoff with jitter when the server omits the header.
- Pin GitHub Actions and test dependencies, and enable Dependabot updates.

### Reliability and scale

- Continue one-minute device connectivity polling while refreshing route state
  every ten minutes.
- Limit route reads to batches of five concurrent requests and preserve the last
  successful route state during throttling or isolated route errors.
- Skip individual malformed device records without losing an otherwise valid
  update; reject a response when every device record is unusable.
- Avoid spending API quota on config-flow validation for an already configured
  tailnet.

### Home Assistant and HACS

- Add Hassfest validation, local light/dark brand assets, and translated entity
  icons.
- Disable the five verbose client-protocol capability entities by default for new
  installs without changing existing entity-registry choices.
- Enforce lint, formatting, dependency consistency, and 90% test coverage in CI.
- Raise the minimum Home Assistant version to 2025.12.0 for coordinator
  `retry_after` support.

## 0.2.0 - 2026-08-27

- Add read-only advertised/enabled route monitoring with
  `devices:routes:read`.
- Add exit-node, subnet-route, and route-approval entities.

## 0.1.0 - 2026-08-26

- Initial OAuth trust-credential integration with read-only device monitoring,
  stable node-based entity IDs, online state, reauthentication, and HACS-style
  installation.
