"""ClearPass CA trust list management.

Extracts CA certificates from fullchain PEM files, resolves missing
parent CAs via AIA extensions, and uploads them to the ClearPass
certificate trust list.
"""

import json
import logging
import os

import requests
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import AuthorityInformationAccessOID

# OID-to-name mapping for building ClearPass-compatible subject_DN strings
_OID_NAME_MAP = {
    x509.oid.NameOID.EMAIL_ADDRESS: "emailAddress",
    x509.oid.NameOID.COMMON_NAME: "CN",
    x509.oid.NameOID.ORGANIZATIONAL_UNIT_NAME: "OU",
    x509.oid.NameOID.ORGANIZATION_NAME: "O",
    x509.oid.NameOID.LOCALITY_NAME: "L",
    x509.oid.NameOID.STATE_OR_PROVINCE_NAME: "ST",
    x509.oid.NameOID.COUNTRY_NAME: "C",
}


def ensure_ca_trust(
    host: str,
    headers: dict,
    cert_path: str,
    log: logging.Logger,
    ca_usages: list[str] | None = None,
) -> list[str]:
    """Ensures CA certificates from the chain are in ClearPass trust list.

    Returns error strings for trust-list updates that failed. An empty
    list means every CA was already trusted or was uploaded. Lookup misses
    are not errors; the missing CA is uploaded instead.
    """
    if not cert_path or not os.path.exists(cert_path):
        return []

    if ca_usages is None:
        ca_usages = ["Others"]

    ca_certs = _extract_ca_certs(cert_path, log)
    if not ca_certs:
        return []

    errors: list[str] = []
    for ca_cert in ca_certs:
        cn = _get_cert_cn(ca_cert)
        display_name = cn or ca_cert.subject.rfc4514_string()
        subject_dn = _build_subject_dn(ca_cert)

        existing = _lookup_trust_entry(host, headers, subject_dn, log)
        if existing:
            error = _ensure_usage_types(
                host,
                headers,
                existing,
                ca_usages,
                display_name,
                log,
            )
        else:
            error = _upload_ca_cert(host, headers, ca_cert, display_name, log, ca_usages)
        if error:
            errors.append(error)
    return errors


def _build_subject_dn(cert: x509.Certificate) -> str:
    """Builds a ClearPass-compatible subject_DN string from a certificate."""
    parts = []
    for oid, name in _OID_NAME_MAP.items():
        for attr in cert.subject:
            if attr.oid == oid:
                parts.append(f"{name}={attr.value}")
    return ",".join(parts)


def _lookup_trust_entry(
    host: str,
    headers: dict,
    subject_dn: str,
    log: logging.Logger,
) -> dict | None:
    """Looks up a CA certificate in ClearPass trust list by subject_DN."""
    try:
        filter_param = json.dumps({"subject_DN": subject_dn})
        r = requests.get(
            f"{host}/api/cert-trust-list-details",
            headers=headers,
            params={"filter": filter_param},
            verify=False,
            timeout=10,
        )
        if r.status_code != 200:
            log.warning(f"Trust list lookup failed [{r.status_code}]: {r.text}")
            return None

        items = r.json().get("_embedded", {}).get("items", [])
        if not items:
            log.info(f"CA not found in trust list: {subject_dn}")
            return None

        item = items[0]
        return {
            "id": item.get("id"),
            "cert_usage": item.get("cert_usage", []),
        }
    except Exception as e:
        log.warning(f"Trust list lookup failed for {subject_dn}: {e}")
        return None


def _extract_ca_certs(cert_path: str, log: logging.Logger) -> list[x509.Certificate]:
    """Extracts CA certs from a fullchain PEM, following AIA for missing parents."""
    try:
        with open(cert_path, "rb") as f:
            pem_data = f.read()

        certs = []
        pem_marker = b"-----BEGIN CERTIFICATE-----"
        parts = pem_data.split(pem_marker)
        for part in parts[1:]:
            try:
                certs.append(x509.load_pem_x509_certificate(pem_marker + part))
            except Exception:
                continue

        if len(certs) <= 1:
            return []

        ca_certs = list(certs[1:])
        last_cert = ca_certs[-1]
        _resolve_aia_chain(last_cert, ca_certs, log)
        return ca_certs
    except Exception as e:
        log.error(f"Failed to parse certificate chain: {e}")
        return []


def _resolve_aia_chain(
    current: x509.Certificate,
    ca_certs: list[x509.Certificate],
    log: logging.Logger,
    max_depth: int = 5,
) -> None:
    """Follows AIA CA Issuers to fetch missing parent CAs."""
    for _ in range(max_depth):
        if current.issuer == current.subject:
            break
        try:
            aia = current.extensions.get_extension_for_oid(
                x509.oid.ExtensionOID.AUTHORITY_INFORMATION_ACCESS
            )
            issuer_urls = [
                desc.access_location.value
                for desc in aia.value
                if desc.access_method == AuthorityInformationAccessOID.CA_ISSUERS
            ]
            if not issuer_urls:
                break

            r = requests.get(issuer_urls[0], timeout=10)
            if r.status_code != 200:
                break

            try:
                parent = x509.load_der_x509_certificate(r.content)
            except Exception:
                parent = x509.load_pem_x509_certificate(r.content)

            ca_certs.append(parent)
            log.info(f"Fetched parent CA via AIA: {parent.subject.rfc4514_string()}")
            current = parent
        except x509.ExtensionNotFound:
            break
        except Exception as e:
            log.warning(f"AIA chain resolution stopped: {e}")
            break


def _get_cert_cn(cert: x509.Certificate) -> str | None:
    """Extracts the Common Name from a certificate subject."""
    for attr in cert.subject:
        if attr.oid == x509.oid.NameOID.COMMON_NAME:
            return attr.value
    return None


def _ensure_usage_types(
    host: str,
    headers: dict,
    entry: dict,
    required_usages: list[str],
    display_name: str,
    log: logging.Logger,
) -> str | None:
    """Ensures an existing trust list entry has the required usage types.

    Returns an error string when the update fails, otherwise None.
    """
    current_usages = set(entry.get("cert_usage", []))
    missing = [u for u in required_usages if u not in current_usages]

    if not missing:
        log.info(f"CA already trusted with correct usage: {display_name}")
        return None

    entry_id = entry.get("id")
    if not entry_id:
        message = f"Cannot update CA trust entry (no id): {display_name}"
        log.error(message)
        return message

    updated_usages = list(current_usages | set(required_usages))
    payload = {"cert_usage": updated_usages}

    try:
        r = requests.patch(
            f"{host}/api/cert-trust-list/{entry_id}",
            headers=headers,
            json=payload,
            verify=False,
            timeout=15,
        )
        if r.status_code in (200, 201):
            log.info(
                f"Updated CA trust usage for {display_name}: "
                f"{list(current_usages)} -> {updated_usages}"
            )
            return None
        message = (
            f"Failed to update CA trust usage for {display_name} "
            f"[{r.status_code}]: {_short_text(r.text)}"
        )
        log.error(message)
        return message
    except Exception as e:
        message = f"Exception updating CA trust usage for {display_name}: {e}"
        log.error(message)
        return message


def _upload_ca_cert(
    host: str,
    headers: dict,
    ca_cert: x509.Certificate,
    display_name: str,
    log: logging.Logger,
    ca_usages: list[str] | None = None,
) -> str | None:
    """Uploads a CA certificate to ClearPass trust list.

    Returns an error string when the upload fails, otherwise None.
    """
    cert_pem = ca_cert.public_bytes(Encoding.PEM).decode("utf-8")
    payload = {
        "cert_file": cert_pem,
        "enabled": True,
        "cert_usage": ca_usages or ["Others"],
    }
    try:
        r = requests.post(
            f"{host}/api/cert-trust-list",
            headers=headers,
            json=payload,
            verify=False,
            timeout=15,
        )
        if r.status_code in (200, 201):
            log.info(f"Added CA to trust list: {display_name}")
            return None
        if r.status_code == 422 and "already exists" in r.text.lower():
            log.info(f"CA already in trust list: {display_name}")
            return None
        message = f"Failed to add CA {display_name} [{r.status_code}]: {_short_text(r.text)}"
        log.error(message)
        return message
    except Exception as e:
        message = f"Exception adding CA {display_name} to trust list: {e}"
        log.error(message)
        return message


def _short_text(text: str, limit: int = 300) -> str:
    """Collapses whitespace and caps length for an API error message."""
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit] + "..."
