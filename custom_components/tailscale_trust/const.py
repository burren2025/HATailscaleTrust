"""Constants for the Tailscale Trust integration."""

import logging
from datetime import timedelta

DOMAIN = "tailscale_trust"

CONF_TAILNET = "tailnet"
CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"

OAUTH_SCOPE = "devices:core:read"
OAUTH_TOKEN_URL = "https://api.tailscale.com/api/v2/oauth/token"
API_BASE_URL = "https://api.tailscale.com/api/v2"

EXIT_NODE_ROUTES = frozenset({"0.0.0.0/0", "::/0"})

SCAN_INTERVAL = timedelta(minutes=1)
RATE_LIMIT_DEFAULT_RETRY = 300
RATE_LIMIT_MAX_RETRY = 3600
TOKEN_REFRESH_SKEW = 60
ONLINE_FALLBACK_WINDOW = timedelta(minutes=5)

LOGGER = logging.getLogger(__package__)
