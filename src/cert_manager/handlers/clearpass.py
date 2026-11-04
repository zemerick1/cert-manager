"""Aruba ClearPass certificate deployment handler.

Handles OAuth2 authentication, PFX generation, CA chain trust management,
and multi-node cluster certificate deployment.
"""

import datetime
import logging
import os
import secrets as secrets_module
import socket
import ssl
import string
import subprocess
import uuid

import requests
from cryptography import x509

from cert_manager.handlers.base import CertificateHandler
from cert_manager.handlers.clearpass_ca_trust import ensure_ca_trust

logger = logging.getLogger("cert_manager.handler.clearpass")

# Usage string mapping for ClearPass API
USAGE_MAP = {
    "https(rsa)": "HTTPS(RSA)",
    "https(ecc)": "HTTPS(ECC)",
    "radius": "RADIUS",
    "radsec": "RadSec",
    "database": "Database",
}

# CA trust list usage types required per certificate usage
CA_TRUST_USAGE_MAP = {
    "https(rsa)": ["Others"],
    "https(ecc)": ["Others"],
    "radius": ["EAP"],
    "radsec": ["RadSec"],
    "database": ["Database"],
}

# Server-certificate usages read after a successful login test.
# Labels are what the setup page shows. Order matches the usage picker.
INSTALLED_USAGES = (
    ("HTTPS(RSA)", "HTTPS (RSA)"),
    ("HTTPS(ECC)", "HTTPS (ECC)"),
    ("RADIUS", "RADIUS / EAP"),
    ("RadSec", "RadSec"),
    ("Database", "Database"),
)

# Module-level temp file registry for PFX downloads
_download_registry: dict[str, dict] = {}


def get_callback_base() -> str:
    """Returns the URL prefix ClearPass uses to download a certificate.

    Deploy tells each node to fetch ``http://{EDGE_DOMAIN}/download/...``
    with no port, so that name must answer on port 80. A blank EDGE_DOMAIN
    is treated as localhost.
    """
    edge_domain = (os.environ.get("EDGE_DOMAIN") or "").strip() or "localhost"
    return f"http://{edge_domain}"


def register_download(file_path: str, base_url: str) -> str | None:
    """Registers a PFX file for one-time download by ClearPass."""
    import time

    token = str(uuid.uuid4())
    _download_registry[token] = {
        "path": file_path,
        "expires": time.time() + 600,
    }
    return f"{base_url}/download/{token}/clearpass.pfx"


def get_download_path(token: str) -> str | None:
    """Retrieves and removes a registered download path (one-time use)."""
    import time

    entry = _download_registry.pop(token, None)
    if not entry:
        return None
    if time.time() > entry["expires"]:
        return None
    return entry["path"]


class ArubaClearPassHandler(CertificateHandler):
    """Deploys certificates to Aruba ClearPass via OAuth2 REST API."""

    def deploy(self, cert_path: str, key_path: str) -> dict:
        """Deploys certificate to all ClearPass nodes.

        Returns a dict with success, message, stage, and per-node results.
        A partial cluster install is success=True, with the failed nodes named
        in the message. CA trust errors are attached to the node and do not
        hide an install failure.
        """
        host, client_id, client_secret = self._parse_config()
        if not all([host, client_id, client_secret]):
            message = "Missing ClearPass config (host, client_id, or client_secret)."
            self.logger.error(message)
            return _deploy_result(False, message, "config")

        pfx_password = self.config.get("pfx_password") or _generate_random_password()
        hosts = self._build_host_list(host)

        pfx_path, pfx_error = _create_pfx(cert_path, key_path, pfx_password)
        if not pfx_path:
            message = pfx_error or "PFX creation failed."
            return _deploy_result(False, message, "pfx")

        try:
            nodes = []
            for current_host in hosts:
                self.logger.info(f"--- Processing Node: {current_host} ---")
                nodes.append(
                    self._deploy_to_node(
                        current_host,
                        client_id,
                        client_secret,
                        pfx_path,
                        pfx_password,
                        cert_path,
                    )
                )
            return _summarize_nodes(nodes)
        finally:
            if os.path.exists(pfx_path):
                os.remove(pfx_path)

    def test_connection(self) -> dict:
        """Authenticates to ClearPass and lists cluster nodes.

        After the cluster lookup succeeds, reads the DNS name on each
        installed server certificate. A missing certificate does not fail
        the login. The access token is not included.
        """
        host, client_id, client_secret = self._parse_config()
        if not all([host, client_id, client_secret]):
            return {
                "success": False,
                "message": "Missing host, client_id, or client_secret.",
                "data": {"stage": "config"},
            }

        auth = _request_access_token(host, client_id, client_secret)
        if not auth["success"]:
            return {
                "success": False,
                "message": auth["message"],
                "data": {"stage": "oauth", "host": host},
            }

        headers = {
            "Authorization": f"Bearer {auth['token']}",
            "Content-Type": "application/json",
        }
        servers, error = _get_cluster_servers(host, headers, self.logger)
        if not servers:
            return {
                "success": False,
                "message": error or "No servers found in the ClearPass cluster.",
                "data": {"stage": "cluster", "host": host},
            }

        names = list(servers.keys())
        certificates = _installed_certificates(host, headers, servers, self.logger)
        return {
            "success": True,
            "message": (
                f"Authenticated to {host}. Found {len(names)} cluster node(s): {', '.join(names)}."
            ),
            "data": {
                "stage": "ok",
                "host": host,
                "servers": names,
                "certificates": certificates,
            },
        }

    def _deploy_to_node(
        self,
        host: str,
        client_id: str,
        client_secret: str,
        pfx_path: str,
        pfx_password: str,
        cert_path: str,
    ) -> dict:
        """Deploys certificate to a single ClearPass node."""
        try:
            auth = _request_access_token(host, client_id, client_secret)
            if not auth["success"]:
                return _node_result(host, False, "oauth", auth["message"])

            headers = {
                "Authorization": f"Bearer {auth['token']}",
                "Content-Type": "application/json",
            }

            cert_usage = self.config.get("cert_usage", "https(rsa)").lower()
            ca_usages = CA_TRUST_USAGE_MAP.get(cert_usage, ["Others"])
            ca_errors = ensure_ca_trust(host, headers, cert_path, self.logger, ca_usages)

            server_uuids, cluster_error = _get_cluster_servers(host, headers, self.logger)
            if not server_uuids:
                return _node_result(
                    host,
                    False,
                    "cluster",
                    cluster_error or "No servers found in the ClearPass cluster.",
                    ca_errors,
                )

            usage = USAGE_MAP.get(
                cert_usage,
                self.config.get("cert_usage", "HTTPS(RSA)"),
            )
            callback_base = get_callback_base()

            install = _install_cert_on_servers(
                host,
                headers,
                server_uuids,
                usage,
                pfx_path,
                pfx_password,
                callback_base,
                self.logger,
            )
            message = install["message"]
            if ca_errors:
                message = f"{message} CA trust: {'; '.join(ca_errors)}"
            return _node_result(
                host,
                install["success"],
                "install",
                message,
                ca_errors,
                callback_base,
                install.get("servers", []),
            )
        except Exception as e:
            self.logger.error(f"Exception processing {host}: {e}")
            return _node_result(host, False, "exception", str(e))

    def check_remote_expiry(self) -> dict:
        """Checks the certificate on the publisher and each additional node.

        A node that cannot be read does not hide a successful read of the
        others. Different serial numbers across the hosts that did answer
        are reported as a mismatch so the monitor installs the saved pack.
        """
        usage = self.config.get("cert_usage", "https(rsa)").lower()
        primary = self._parse_config()[0] or self.config.get("host", "")
        hosts = self._build_host_list(primary)
        results = []
        for host in hosts:
            if usage.startswith("https"):
                results.append(self._check_via_tls(usage, host))
            else:
                results.append(self._check_via_api(usage, host))
        return _combine_node_checks(results)

    def _check_via_tls(self, usage: str, host: str | None = None) -> dict:
        """Checks ClearPass HTTPS cert using TLS cipher selection."""
        host = host or self.config.get("host")
        if not host:
            return {"success": False, "message": "No host configured"}

        if "://" in host:
            host = host.split("://", 1)[1]
        host = host.split("/")[0]

        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.maximum_version = ssl.TLSVersion.TLSv1_2

        if "ecc" in usage:
            context.set_ciphers("ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES128-GCM-SHA256")
        else:
            context.set_ciphers(
                "ECDHE-RSA-AES256-GCM-SHA384:ECDHE-RSA-AES128-GCM-SHA256:AES256-SHA:AES128-SHA"
            )

        try:
            with socket.create_connection((host, 443), timeout=5) as sock:
                with context.wrap_socket(sock, server_hostname=host) as ssock:
                    cert = ssock.getpeercert(binary_form=True)
                    return _parse_cert_result(x509.load_der_x509_certificate(cert))
        except Exception as e:
            self.logger.error(f"ClearPass TLS check failed: {e}")
            return {"success": False, "message": str(e)}

    def _check_via_api(self, usage: str, host: str | None = None) -> dict:
        """Checks one ClearPass host for a non-HTTPS certificate.

        Every server returned by that host's cluster API is read. One
        missing certificate among readable servers is a cluster mismatch.
        """
        parsed_host, client_id, client_secret = self._parse_config()
        if host:
            if "://" not in host:
                host = f"https://{host}"
        else:
            host = parsed_host
        if not all([host, client_id, client_secret]):
            return {"success": False, "message": "Missing ClearPass credentials"}

        try:
            auth = _request_access_token(host, client_id, client_secret)
            if not auth["success"]:
                return {"success": False, "message": auth["message"]}

            headers = {
                "Authorization": f"Bearer {auth['token']}",
                "Content-Type": "application/json",
            }

            server_uuids, cluster_error = _get_cluster_servers(host, headers, self.logger)
            if not server_uuids:
                return {
                    "success": False,
                    "message": cluster_error or "No cluster servers found",
                }

            api_usage = USAGE_MAP.get(usage, self.config.get("cert_usage", "RADIUS"))
            checks = []
            for name, server_uuid in server_uuids.items():
                result = _get_cert_via_api(host, headers, server_uuid, api_usage, self.logger)
                message = result.get("message") or ""
                missing = (
                    message == "No certificate in API response" or "API returned 404" in message
                )
                if not result.get("success") and missing:
                    result = {
                        "success": True,
                        "serial_number": "cluster-mismatch",
                        "message": f"{name} has no readable {api_usage} certificate.",
                    }
                checks.append(result)
            return _combine_node_checks(checks)
        except Exception as e:
            self.logger.error(f"ClearPass API cert check failed: {e}")
            return {"success": False, "message": str(e)}

    def _parse_config(self) -> tuple[str, str, str]:
        """Extracts host, client_id, client_secret from config."""
        host = self.config.get("host", "")
        if host and "://" not in host:
            host = f"https://{host}"
        return (
            host,
            self.config.get("client_id", ""),
            self.config.get("client_secret", ""),
        )

    def _build_host_list(self, primary_host: str) -> list[str]:
        """Builds list of all hosts including additional nodes."""
        hosts = [primary_host]
        additional = self.config.get("additional_nodes")
        if additional:
            if isinstance(additional, str):
                extra = [h.strip() for h in additional.split(",") if h.strip()]
            else:
                extra = [h.strip() for h in additional if h.strip()]
            for h in extra:
                hosts.append(f"https://{h}" if "://" not in h else h)
        return hosts


# --- Module-level helper functions ---


def _dns_names(cert_obj: x509.Certificate) -> list[str]:
    """Returns DNS names from the SAN extension, or the common name."""
    try:
        ext = cert_obj.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        names = [name for name in ext.value.get_values_for_type(x509.DNSName) if name]
    except x509.ExtensionNotFound:
        names = []
    if names:
        return names
    for attr in cert_obj.subject:
        if attr.oid == x509.oid.NameOID.COMMON_NAME and attr.value:
            return [str(attr.value)]
    return []


def _parse_cert_result(cert_obj: x509.Certificate) -> dict:
    """Extracts expiry, subject, issuer, serial, and DNS names."""
    not_after = cert_obj.not_valid_after_utc
    now = datetime.datetime.now(datetime.timezone.utc)
    days_remaining = (not_after - now).days

    return {
        "success": True,
        "expiry": not_after.strftime("%Y-%m-%d"),
        "days_remaining": days_remaining,
        "subject": cert_obj.subject.rfc4514_string(),
        "issuer": cert_obj.issuer.rfc4514_string(),
        "serial_number": format(cert_obj.serial_number, "x").upper(),
        "names": _dns_names(cert_obj),
    }


def _get_cert_via_api(
    host: str,
    headers: dict,
    server_uuid: str,
    service_name: str,
    log: logging.Logger,
    *,
    missing_ok: bool = False,
) -> dict:
    """Retrieves a certificate from ClearPass API and parses it.

    ``missing_ok`` keeps a missing certificate out of the error log. The
    connection test uses it so an unused usage does not look like a failure.
    """
    url = f"{host}/api/server-cert/name/{server_uuid}/{service_name}"
    try:
        r = requests.get(url, headers=headers, verify=False, timeout=10)
        if r.status_code != 200:
            if not missing_ok:
                log.error(f"API cert lookup failed [{r.status_code}]: {r.text}")
            return {"success": False, "message": f"API returned {r.status_code}"}

        data = r.json()
        cert_pem = data.get("cert_file") or data.get("certificate")
        if not cert_pem:
            if not missing_ok:
                log.error(f"No cert_file in API response for {service_name}")
            return {"success": False, "message": "No certificate in API response"}

        if isinstance(cert_pem, str):
            cert_pem = cert_pem.encode()
        cert_obj = x509.load_pem_x509_certificate(cert_pem)
        return _parse_cert_result(cert_obj)
    except Exception as e:
        if not missing_ok:
            log.error(f"API cert check for {service_name} failed: {e}")
        return {"success": False, "message": str(e)}


def _installed_certificates(
    host: str,
    headers: dict,
    servers: dict[str, str],
    log: logging.Logger,
) -> list[dict]:
    """Reads the DNS name on each ClearPass server-certificate usage.

    A missing certificate is an empty name list. It does not fail the
    connection test. ``names`` is the unique list across the cluster.
    """
    rows = []
    for usage, label in INSTALLED_USAGES:
        per_server = []
        combined: list[str] = []
        for server, server_uuid in servers.items():
            result = _get_cert_via_api(
                host,
                headers,
                server_uuid,
                usage,
                log,
                missing_ok=True,
            )
            found = result.get("success")
            names = list(result.get("names") or []) if found else []
            per_server.append({"server": server, "names": names})
            for name in names:
                if name not in combined:
                    combined.append(name)
        rows.append(
            {
                "usage": usage,
                "label": label,
                "names": combined,
                "servers": per_server,
            }
        )
    return rows


def _generate_random_password() -> str:
    """Generates a 16-character alphanumeric password."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets_module.choice(alphabet) for _ in range(16))


def _create_pfx(cert_path: str, key_path: str, pfx_password: str) -> tuple[str | None, str | None]:
    """Creates a PKCS12/PFX bundle from cert and key files.

    Returns the file path and an error message. One of the two is None.
    """
    try:
        timestamp = uuid.uuid4().hex[:8]
        output_dir = os.path.dirname(cert_path)
        pfx_path = os.path.join(output_dir, f"clearpass_{timestamp}.pfx")

        cmd = [
            "openssl",
            "pkcs12",
            "-export",
            "-out",
            pfx_path,
            "-inkey",
            key_path,
            "-in",
            cert_path,
            "-passout",
            f"pass:{pfx_password}",
            "-legacy",
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return pfx_path, None
    except subprocess.CalledProcessError as e:
        detail = _short_text(e.stderr or e.stdout or str(e))
        message = f"PFX creation failed: {detail or 'openssl pkcs12 failed.'}"
        logger.error(message)
        return None, message
    except Exception as e:
        message = f"PFX creation failed: {e}"
        logger.error(message)
        return None, message


def _request_access_token(host: str, client_id: str, client_secret: str) -> dict:
    """Obtains an OAuth2 access token and returns the ClearPass error text."""
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    try:
        response = requests.post(f"{host}/api/oauth", json=payload, verify=False, timeout=10)
    except requests.Timeout:
        message = f"Timed out contacting ClearPass at {host}."
        logger.error(message)
        return {"success": False, "token": None, "message": message}
    except requests.RequestException as e:
        message = f"Could not reach ClearPass at {host}: {e}"
        logger.error(message)
        return {"success": False, "token": None, "message": message}

    if response.status_code == 200:
        body = _json_object(response)
        token = body.get("access_token") if body else None
        if token:
            return {"success": True, "token": token, "message": "Authenticated."}
        message = "ClearPass OAuth response did not include an access token."
        logger.error(message)
        return {"success": False, "token": None, "message": message}

    detail = _short_text(response.text) or "no response body"
    message = f"ClearPass authentication failed ({response.status_code}): {detail}"
    logger.error(message)
    return {"success": False, "token": None, "message": message}


def _get_cluster_servers(
    host: str,
    headers: dict,
    log: logging.Logger,
) -> tuple[dict[str, str], str | None]:
    """Fetches cluster server name->UUID mapping from ClearPass.

    Returns the mapping and an error message. The message is set when the
    mapping is empty.
    """
    try:
        response = requests.get(
            f"{host}/api/cluster/server",
            headers=headers,
            verify=False,
            timeout=10,
        )
        if response.status_code != 200:
            message = (
                f"Cluster lookup failed ({response.status_code}): {_short_text(response.text)}"
            )
            log.error(message)
            return {}, message

        items = response.json().get("_embedded", {}).get("items", [])
        servers = {}
        for item in items:
            name = item.get("name")
            uuid_val = item.get("server_uuid")
            if name and uuid_val:
                servers[name] = uuid_val
        if not servers:
            message = "No servers found in the ClearPass cluster."
            log.error(message)
            return {}, message
        return servers, None
    except Exception as e:
        message = f"Cluster lookup failed: {e}"
        log.error(message)
        return {}, message


def _install_cert_on_servers(
    host: str,
    headers: dict,
    server_uuids: dict[str, str],
    usage: str,
    pfx_path: str,
    pfx_password: str,
    callback_base: str,
    log: logging.Logger,
) -> dict:
    """Installs certificate on all cluster servers via download URL.

    Returns success, a message that includes the HTTP status and download
    URL when a node rejects the certificate, and per-server results.
    """
    results = []
    for name, uuid_val in server_uuids.items():
        download_url = register_download(pfx_path, callback_base)
        if not download_url:
            message = f"Failed to register the PFX download URL for {name}."
            log.error(message)
            results.append({"name": name, "success": False, "message": message})
            continue

        url = f"{host}/api/server-cert/name/{uuid_val}/{usage}"
        payload = {
            "pkcs12_file_url": download_url,
            "pkcs12_passphrase": pfx_password,
        }

        log.info(f"Updating {name} ({uuid_val}) usage {usage}, PFX URL: {download_url}")
        try:
            response = requests.put(url, json=payload, headers=headers, verify=False, timeout=30)
            if response.status_code == 200:
                log.info(f"Success for {name}")
                results.append(
                    {
                        "name": name,
                        "success": True,
                        "message": "Installed.",
                        "download_url": download_url,
                    }
                )
            else:
                detail = _short_text(response.text) or "no response body"
                message = (
                    f"ClearPass rejected the certificate for {name} "
                    f"({response.status_code}): {detail}. "
                    f"Download URL was {download_url}. "
                    "ClearPass must be able to fetch that URL from each node."
                )
                log.error(message)
                results.append(
                    {
                        "name": name,
                        "success": False,
                        "message": message,
                        "download_url": download_url,
                    }
                )
        except Exception as e:
            message = (
                f"Could not reach ClearPass to install on {name}: {e}. "
                f"Download URL was {download_url}."
            )
            log.error(message)
            results.append(
                {
                    "name": name,
                    "success": False,
                    "message": message,
                    "download_url": download_url,
                }
            )

    installed = [item for item in results if item["success"]]
    if installed and len(installed) == len(results):
        message = f"Installed on {len(installed)} server(s)."
    elif installed:
        failed = "; ".join(item["message"] for item in results if not item["success"])
        message = f"Installed on {len(installed)} of {len(results)} servers. {failed}"
    else:
        message = "; ".join(item["message"] for item in results) or "No cluster servers to update."
    return {"success": bool(installed), "message": message, "servers": results}


def _combine_node_checks(results: list[dict]) -> dict:
    """Folds per-node certificate reads into one health result.

    Connection failures are returned only when no node could be read.
    Serial numbers that disagree produce a mismatch the monitor redeploys.
    """
    ok = [item for item in results if item.get("success")]
    bad = [item for item in results if not item.get("success")]
    if not ok:
        if bad:
            return bad[0]
        return {"success": False, "message": "No ClearPass hosts to check"}

    serials = {item.get("serial_number") for item in ok}
    if len(serials) > 1 or "cluster-mismatch" in serials:
        return {
            "success": True,
            "serial_number": "cluster-mismatch",
            "message": "Cluster nodes do not have the same certificate.",
        }
    result = dict(ok[0])
    if bad:
        unread = "; ".join(item.get("message") or "unreadable" for item in bad)
        result["message"] = f"Some cluster nodes could not be read. {unread}"
    return result


def _deploy_result(success: bool, message: str, stage: str, nodes: list | None = None) -> dict:
    """Builds the dict returned by ArubaClearPassHandler.deploy."""
    return {
        "success": success,
        "message": message,
        "stage": stage,
        "nodes": nodes or [],
    }


def _node_result(
    host: str,
    success: bool,
    stage: str,
    message: str,
    ca_trust_errors: list | None = None,
    callback_base: str | None = None,
    servers: list | None = None,
) -> dict:
    """Builds one node entry inside a deploy result."""
    result = {
        "host": host,
        "success": success,
        "stage": stage,
        "message": message,
        "ca_trust_errors": ca_trust_errors or [],
    }
    if callback_base:
        result["callback_base"] = callback_base
    if servers is not None:
        result["servers"] = servers
    return result


def _summarize_nodes(nodes: list[dict]) -> dict:
    """Collapses per-node deploy results into one result dict."""
    ok = [node for node in nodes if node.get("success")]
    bad = [node for node in nodes if not node.get("success")]
    if ok and not bad:
        message = "Deployment successful."
        warnings: list[str] = []
        for node in ok:
            for error in node.get("ca_trust_errors") or []:
                if error not in warnings:
                    warnings.append(error)
        if warnings:
            message += " CA trust list needs attention: " + "; ".join(warnings)
        return _deploy_result(True, message, "install", nodes)
    if ok:
        details = "; ".join(f"{node.get('host')}: {node.get('message')}" for node in bad)
        message = f"Deployed to {len(ok)} of {len(nodes)} nodes. {details}"
        return _deploy_result(True, message, "install", nodes)

    messages: list[str] = []
    for node in bad:
        msg = node.get("message") or "Deployment failed."
        if msg not in messages:
            messages.append(msg)
    stage = bad[0].get("stage", "install") if bad else "install"
    return _deploy_result(False, " ".join(messages) or "Deployment failed.", stage, nodes)


def _json_object(response: requests.Response) -> dict | None:
    """Returns a JSON object body, or None."""
    try:
        body = response.json()
    except Exception:
        return None
    if isinstance(body, dict):
        return body
    return None


def _short_text(text: str, limit: int = 300) -> str:
    """Collapses whitespace and caps length for an API error message."""
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit] + "..."
