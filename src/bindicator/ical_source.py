"""Validation for read-only external HTTPS iCalendar feed sources."""
from urllib.parse import urlsplit
import ipaddress
import re
import socket

# Established calendar providers can be validated without DNS in offline tests.
TRUSTED_DOMAINS = (
    "zoho.com", "zoho.eu", "zoho.in", "zoho.com.au",
    "zoho.jp", "zoho.ca", "zoho.com.cn",
    "google.com", "googleusercontent.com", "icloud.com",
    "outlook.com", "office365.com", "microsoft.com", "live.com",
)


def validate_public_ical_url(url: str) -> str:
    """Reject local/private network targets and unsupported URL syntax.

    The web interface is LAN-only, but URLs remain untrusted input. Redirects
    are disabled at the HTTP request site.
    """
    if not isinstance(url, str) or not 10 <= len(url) <= 2048:
        raise ValueError("Enter a valid HTTPS iCalendar feed URL.")
    if any(c.isspace() or ord(c) < 32 for c in url):
        raise ValueError("Invalid characters in iCalendar URL.")
    p = urlsplit(url)
    hostname = (p.hostname or "").lower().rstrip(".")
    if (p.scheme != "https" or not hostname or p.username or p.password
            or p.port not in (None, 443) or p.fragment
            or not re.fullmatch(r"[a-z0-9.-]+", hostname)
            or "." not in hostname or ".." in hostname
            or hostname.endswith((".local", ".internal", ".localhost", ".home", ".lan"))
            or any(c in url for c in ("'", '"', "\\", "#"))):
        raise ValueError("Only public HTTPS iCalendar URLs are supported.")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ValueError("iCalendar URLs must use a public DNS hostname.")
    trusted = any(hostname == domain or hostname.endswith("." + domain)
                  for domain in TRUSTED_DOMAINS)
    if not trusted:
        try:
            addresses = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise ValueError("The iCalendar hostname could not be resolved.") from exc
        if not addresses or any(not ipaddress.ip_address(addr[4][0]).is_global
                                for addr in addresses):
            raise ValueError("iCalendar feeds must not resolve to private network addresses.")
    return url
