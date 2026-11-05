"""Live checks for a DigitalOcean API token.

Certbot's DNS plugin is what creates the challenge record. This module
only lists domains the token can see, so a bad token is reported before
Certbot runs. It does not create DNS records.
"""

import requests

DOMAINS_URL = "https://api.digitalocean.com/v2/domains"


def test_digitalocean_token(api_token: str) -> dict:
    """Checks a DigitalOcean token without creating DNS records.

    Returns a dict with success, message, and data. data lists domain
    names from the first page of the account. Write access is not proven
    here; issuance does that.
    """
    token = (api_token or "").strip()
    if not token:
        return {"success": False, "message": "DigitalOcean credential has no api_token."}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.get(DOMAINS_URL, headers=headers, timeout=10)
    except requests.Timeout:
        return {"success": False, "message": "Timed out contacting the DigitalOcean API."}
    except requests.RequestException as e:
        return {"success": False, "message": f"Could not reach the DigitalOcean API: {e}"}

    if response.status_code == 401:
        return {"success": False, "message": "DigitalOcean rejected the API token."}
    if response.status_code == 403:
        return {
            "success": False,
            "message": (
                "DigitalOcean refused to list domains. "
                "The token needs permission to read the domain that owns the certificate name."
            ),
        }

    body = _json_body(response)
    if response.status_code != 200 or body is None:
        detail = _error_detail(body, response.text)
        return {
            "success": False,
            "message": f"DigitalOcean token check failed ({response.status_code}): {detail}",
        }

    names, total = _domain_names(body)
    if total == 0:
        return {
            "success": True,
            "message": (
                "DigitalOcean accepted the token, and it cannot see any domains. "
                "Issuance needs a token that can edit the domain that owns the certificate name."
            ),
            "data": {"domains": []},
        }

    return {
        "success": True,
        "message": (
            f"DigitalOcean accepted the token. It can see {total} domain(s): {_join_names(names)}. "
            "Issuance needs permission to edit the domain that owns the certificate name."
        ),
        "data": {"domains": names},
    }


def _domain_names(body: dict) -> tuple[list[str], int]:
    """Returns domain names from this page and the reported total."""
    names = []
    for item in body.get("domains") or []:
        if isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))
    meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
    total = meta.get("total")
    if not isinstance(total, int) or total < len(names):
        total = len(names)
    return names, total


def _join_names(names: list[str]) -> str:
    """Joins domain names, capping the list so the message stays readable."""
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
    """Pulls a short DigitalOcean error string from a response."""
    if body:
        message = body.get("message")
        if message:
            return str(message)
    text = " ".join((raw_text or "").split())
    if not text:
        return "no response body"
    if len(text) > 300:
        return text[:300] + "..."
    return text
