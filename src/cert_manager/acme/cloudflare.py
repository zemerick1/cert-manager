"""Live checks for a Cloudflare API token.

Certbot's DNS plugin is what creates the challenge record. This module
only asks Cloudflare whether the token is active and can see zone DNS,
so a bad token is reported before Certbot runs.
"""

import logging

import requests

logger = logging.getLogger("cert_manager.acme.cloudflare")

VERIFY_URL = "https://api.cloudflare.com/client/v4/user/tokens/verify"
ZONES_URL = "https://api.cloudflare.com/client/v4/zones"


def test_cloudflare_token(api_token: str) -> dict:
    """Checks a Cloudflare API token without creating DNS records.

    Returns a dict with success, message, and data. data lists the zones
    the token can see. DNS Edit is not proven here; issuance does that.
    """
    token = (api_token or "").strip()
    if not token:
        return {"success": False, "message": "Cloudflare credential has no api_token."}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        verify = requests.get(VERIFY_URL, headers=headers, timeout=10)
    except requests.Timeout:
        return {"success": False, "message": "Timed out contacting the Cloudflare API."}
    except requests.RequestException as e:
        return {"success": False, "message": f"Could not reach the Cloudflare API: {e}"}

    if verify.status_code == 401:
        return {"success": False, "message": "Cloudflare rejected the API token."}

    body = _json_body(verify)
    if verify.status_code != 200 or not body or not body.get("success"):
        detail = _error_detail(body, verify.text)
        return {
            "success": False,
            "message": f"Cloudflare token check failed ({verify.status_code}): {detail}",
        }

    status = ((body.get("result") or {}) if isinstance(body.get("result"), dict) else {}).get(
        "status"
    )
    if status != "active":
        shown = status or "unknown"
        return {
            "success": False,
            "message": f"Cloudflare token status is '{shown}'.",
            "data": {"token_status": shown, "zones": [], "dns_read": False},
        }

    zones, zone_error = _list_zones(headers)
    if zone_error:
        return {
            "success": False,
            "message": f"Token is active, but {zone_error}",
            "data": {"token_status": status, "zones": [], "dns_read": False},
        }

    names = [zone["name"] for zone in zones]
    if not names:
        return {
            "success": False,
            "message": (
                "Token is active, but it cannot see any zones. "
                "Include the certificate's zone in the token's zone resources."
            ),
            "data": {"token_status": status, "zones": [], "dns_read": False},
        }

    dns_read, dns_error = _probe_dns(headers, zones[0])
    shown = _join_names(names)
    if not dns_read:
        return {
            "success": False,
            "message": (
                f"Token is active and can see {shown}. "
                f"It cannot read DNS in {names[0]} ({dns_error}). "
                "Add Zone:DNS:Edit on this zone."
            ),
            "data": {"token_status": status, "zones": names, "dns_read": False},
        }

    return {
        "success": True,
        "message": (
            f"Cloudflare token is active. It can see {len(names)} zone(s): {shown}. "
            f"DNS read succeeded on {names[0]}. "
            "Certificate issuance also needs Zone:DNS:Edit on that zone."
        ),
        "data": {"token_status": status, "zones": names, "dns_read": True},
    }


def _list_zones(headers: dict) -> tuple[list[dict], str | None]:
    """Returns visible zones, or an error phrase that follows 'but'."""
    try:
        response = requests.get(ZONES_URL, headers=headers, params={"per_page": 50}, timeout=10)
    except requests.RequestException as e:
        return [], f"could not list zones: {e}"

    body = _json_body(response)
    if response.status_code in (401, 403):
        return [], (
            "it cannot list zones "
            f"(Cloudflare returned {response.status_code}). Add Zone:Zone:Read."
        )
    if response.status_code != 200 or not body or not body.get("success"):
        detail = _error_detail(body, response.text)
        return [], f"zone list failed ({response.status_code}): {detail}"

    zones = []
    for item in body.get("result") or []:
        if isinstance(item, dict) and item.get("id") and item.get("name"):
            zones.append({"id": item["id"], "name": item["name"]})
    return zones, None


def _probe_dns(headers: dict, zone: dict) -> tuple[bool, str]:
    """Reads one DNS record to see whether the token can see the zone's DNS."""
    url = f"{ZONES_URL}/{zone['id']}/dns_records"
    try:
        response = requests.get(url, headers=headers, params={"per_page": 1}, timeout=10)
    except requests.RequestException as e:
        return False, str(e)
    if response.status_code == 200:
        return True, ""
    return False, f"Cloudflare returned {response.status_code}"


def _join_names(names: list[str]) -> str:
    """Joins zone names, capping the list so the message stays readable."""
    shown = ", ".join(names[:5])
    extra = len(names) - 5
    if extra > 0:
        shown += f", and {extra} more"
    return shown


def _json_body(response: requests.Response) -> dict | None:
    """Returns the JSON object body, or None when the body is not an object."""
    try:
        body = response.json()
    except Exception:
        return None
    if isinstance(body, dict):
        return body
    return None


def _error_detail(body: dict | None, raw_text: str) -> str:
    """Pulls a short Cloudflare error string from a response."""
    if body:
        errors = body.get("errors") or []
        if errors and isinstance(errors[0], dict) and errors[0].get("message"):
            return str(errors[0]["message"])
    text = " ".join((raw_text or "").split())
    if not text:
        return "no response body"
    if len(text) > 300:
        return text[:300] + "..."
    return text
