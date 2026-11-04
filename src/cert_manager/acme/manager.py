"""ACME certificate management via certbot CLI wrapper."""

import datetime
import glob as glob_module
import logging
import os
import shutil
import subprocess
import tempfile
from typing import Callable

logger = logging.getLogger("cert_manager.acme")

# DNS providers supported with their certbot plugin configurations
DNS_PROVIDERS = {
    "cloudflare": {
        "plugin": "dns-cloudflare",
        "credentials_ini_template": "dns_cloudflare_api_token = {api_token}\n",
        "propagation_flag": "--dns-cloudflare-propagation-seconds",
        "default_propagation": 60,
    },
    "route53": {
        "plugin": "dns-route53",
        "credentials_ini_template": None,
        "env_vars": {
            "AWS_ACCESS_KEY_ID": "{aws_access_key_id}",
            "AWS_SECRET_ACCESS_KEY": "{aws_secret_access_key}",
        },
    },
    "digitalocean": {
        "plugin": "dns-digitalocean",
        "credentials_ini_template": "dns_digitalocean_token = {api_token}\n",
        "propagation_flag": "--dns-digitalocean-propagation-seconds",
        "default_propagation": 60,
    },
    "google": {
        "plugin": "dns-google",
        "credentials_ini_template": None,
    },
    "ovh": {
        "plugin": "dns-ovh",
        "credentials_ini_template": (
            "dns_ovh_endpoint = {endpoint}\n"
            "dns_ovh_application_key = {application_key}\n"
            "dns_ovh_application_secret = {application_secret}\n"
            "dns_ovh_consumer_key = {consumer_key}\n"
        ),
        "propagation_flag": "--dns-ovh-propagation-seconds",
        "default_propagation": 60,
    },
    "duckdns": {
        "plugin": "dns-duckdns",
        "credentials_ini_template": "dns_duckdns_token = {token}\n",
        "propagation_flag": "--dns-duckdns-propagation-seconds",
        "default_propagation": 60,
    },
}

# HTTP/TLS challenge providers
HTTP_PROVIDERS = {
    "standalone": {"plugin": "standalone"},
    "webroot": {"plugin": "webroot"},
    "nginx": {"plugin": "nginx"},
    "apache": {"plugin": "apache"},
}


class AcmeManager:
    """Manages Let's Encrypt certificate requests and renewals via certbot."""

    def __init__(
        self,
        config_manager,
        cert_store,
        letsencrypt_dir: str,
    ) -> None:
        self.config_mgr = config_manager
        self.cert_store = cert_store
        self.le_dir = letsencrypt_dir

    def request_certificate(
        self,
        pack_name: str,
        domains: list[str],
        provider: str,
        credential_id: str,
        email: str,
        challenge_type: str = "dns-01",
        key_type: str = "ecdsa",
        is_edge: bool = False,
        progress_callback: Callable[[str], None] | None = None,
    ) -> dict:
        """Requests a new certificate from Let's Encrypt.

        Args:
            pack_name: Name for the cert pack.
            domains: List of domain names.
            provider: Provider name (e.g., 'cloudflare', 'standalone').
            credential_id: Credential ID from config.
            email: ACME account email.
            challenge_type: ACME challenge type ('dns-01', 'http-01', 'tls-alpn-01').
            key_type: 'rsa' or 'ecdsa'.
            is_edge: If True, saves to ssl/live/ and updates edge domain symlink.
            progress_callback: Optional callback for progress updates.

        Returns:
            Dict with success, message, and pack_name keys.
        """

        def progress(msg: str) -> None:
            if progress_callback:
                progress_callback(msg)
            logger.info(msg)

        if not domains:
            return {"success": False, "message": "At least one domain is required."}
        if not email:
            return {"success": False, "message": "Email is required for ACME registration."}

        # Save metadata immediately so the scheduler can retry on failure.
        existing_meta = self.config_mgr.get_cert_pack_meta(pack_name)
        retry_count = existing_meta.get("retry_count", 0) if existing_meta else 0
        pending_meta = {
            "source": "acme",
            "domains": domains,
            "challenge_type": challenge_type,
            "provider": provider,
            "credential_id": credential_id,
            "acme_email": email,
            "key_type": key_type,
            "is_edge": is_edge,
            "auto_renew": True,
            "renew_days_before": 30,
            "last_renewal_status": "PENDING",
            "retry_count": retry_count,
        }
        self.config_mgr.set_cert_pack_meta(pack_name, pending_meta)

        progress(f"Loading credentials for {provider}...")

        # Fetch credentials from built-in config
        credentials = {}
        if credential_id:
            try:
                credential = self.config_mgr.get_acme_credential(credential_id)
                if not credential:
                    raise ValueError(f"ACME credential not found: {credential_id}")

                # Verify provider matches
                if credential.get("provider") != provider:
                    raise ValueError(
                        f"Credential provider mismatch: expected {provider}, "
                        f"got {credential.get('provider')}"
                    )

                # Build credentials dict based on provider
                if provider == "cloudflare":
                    credentials = {"api_token": credential.get("api_token")}
                    if credential.get("email"):
                        credentials["email"] = credential.get("email")

                elif provider == "route53":
                    credentials = {
                        "aws_access_key_id": credential.get("access_key_id"),
                        "aws_secret_access_key": credential.get("secret_access_key"),
                    }
                    if credential.get("region"):
                        credentials["region"] = credential.get("region")

                elif provider == "digitalocean":
                    credentials = {"api_token": credential.get("api_token")}

            except Exception as e:
                logger.error(f"Failed to fetch credential {credential_id}: {e}")
                pending_meta["last_renewal_status"] = "FAILED"
                pending_meta["retry_count"] = retry_count + 1
                self.config_mgr.set_cert_pack_meta(pack_name, pending_meta)
                return {
                    "success": False,
                    "message": f"Failed to fetch credentials: {e}",
                }

        try:
            progress("Building certbot command...")
            cmd, env, temp_files = self._build_certbot_cmd(
                domains,
                challenge_type,
                provider,
                credentials,
                email,
                pack_name,
                key_type,
            )

            logger.info(f"Requesting certificate for {domains} via {challenge_type}/{provider}")
            progress(f"Requesting certificate for {', '.join(domains)} via {challenge_type}...")

            output_lines = self._run_certbot(cmd, env, progress)

            if output_lines is None:
                pending_meta["last_renewal_status"] = "FAILED"
                pending_meta["retry_count"] = retry_count + 1
                self.config_mgr.set_cert_pack_meta(pack_name, pending_meta)
                return {"success": False, "message": "Certbot timed out after 5 minutes."}

        except Exception as e:
            pending_meta["last_renewal_status"] = "FAILED"
            pending_meta["retry_count"] = retry_count + 1
            self.config_mgr.set_cert_pack_meta(pack_name, pending_meta)
            return {"success": False, "message": str(e)}
        finally:
            for tf in temp_files:
                try:
                    os.remove(tf)
                except Exception:
                    pass

        progress("Certificate obtained. Importing into certificate store...")
        if not self._import_certbot_result(domains[0], pack_name, is_edge=is_edge):
            pending_meta["last_renewal_status"] = "FAILED"
            pending_meta["retry_count"] = retry_count + 1
            self.config_mgr.set_cert_pack_meta(pack_name, pending_meta)
            return {
                "success": False,
                "message": "Certificate obtained but failed to import into cert pack.",
            }

        progress("Saving certificate metadata...")
        pending_meta["last_acme_renewal"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        pending_meta["last_renewal_status"] = "SUCCESS"
        pending_meta["retry_count"] = 0
        self.config_mgr.set_cert_pack_meta(pack_name, pending_meta)

        return {
            "success": True,
            "message": f"Certificate obtained and saved as '{pack_name}'.",
            "pack_name": pack_name,
        }

    def _clear_stale_locks(self) -> int:
        """Removes stale certbot lock files from the letsencrypt directory."""
        pattern = os.path.join(self.le_dir, "**", ".certbot.lock")
        locks = glob_module.glob(pattern, recursive=True)
        for lock in locks:
            try:
                os.remove(lock)
                logger.info(f"Removed stale certbot lock: {lock}")
            except OSError as e:
                logger.warning(f"Failed to remove lock {lock}: {e}")
        return len(locks)

    def _run_certbot(
        self,
        cmd: list[str],
        env: dict,
        progress: Callable[[str], None],
    ) -> list[str] | None:
        """Runs certbot and streams output, returning captured lines or None on timeout."""
        self._clear_stale_locks()
        return self._exec_certbot(cmd, env, progress, retried=False)

    def _exec_certbot(
        self,
        cmd: list[str],
        env: dict,
        progress: Callable[[str], None],
        retried: bool = False,
    ) -> list[str] | None:
        """Executes certbot with optional lock-retry logic."""
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        lines: list[str] = []
        progress_keywords = (
            "waiting",
            "challeng",
            "verif",
            "clean",
            "deploy",
            "obtain",
            "generat",
            "request",
            "creat",
            "success",
            "congratulations",
            "saving",
            "renewal",
            "propagat",
        )

        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                logger.info(f"certbot: {line}")
                if any(kw in line.lower() for kw in progress_keywords):
                    progress(line)
                lines.append(line)
            proc.wait(timeout=300)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return None

        if proc.returncode != 0:
            error_text = "\n".join(lines[-5:]) if lines else ""

            # Retry once after clearing stale locks
            if "already running" in error_text.lower() and not retried:
                logger.warning("Certbot lock detected - clearing and retrying.")
                progress("Clearing stale lock and retrying...")
                self._clear_stale_locks()
                return self._exec_certbot(cmd, env, progress, retried=True)

            raise RuntimeError(f"Certbot error: {error_text or 'Unknown error'}")

        return lines

    def renew_certificate(
        self,
        pack_name: str,
        progress_callback: Callable[[str], None] | None = None,
    ) -> dict:
        """Renews an existing ACME certificate by re-requesting it."""
        meta = self.config_mgr.get_cert_pack_meta(pack_name)
        if not meta or meta.get("source") != "acme":
            return {"success": False, "message": f"Pack '{pack_name}' is not an ACME certificate."}

        return self.request_certificate(
            pack_name=pack_name,
            domains=meta.get("domains", []),
            provider=meta.get("provider", ""),
            credential_id=meta.get("credential_id", ""),
            email=meta.get("acme_email", ""),
            challenge_type=meta.get("challenge_type", "dns-01"),
            key_type=meta.get("key_type", "ecdsa"),
            is_edge=meta.get("is_edge", False),
            progress_callback=progress_callback,
        )

    def check_renewal_needed(self, pack_name: str) -> bool:
        """Checks if a cert pack is within its renewal window."""
        meta = self.config_mgr.get_cert_pack_meta(pack_name)
        if not meta or meta.get("source") != "acme" or not meta.get("auto_renew"):
            return False

        renew_before = meta.get("renew_days_before", 30)
        pack_info = self.cert_store.get_pack(pack_name, self.config_mgr.get_cert_packs_meta())
        if not pack_info:
            return False

        days_remaining = pack_info.get("days_remaining")
        return days_remaining is not None and days_remaining <= renew_before

    def get_renewable_packs(self) -> list[str]:
        """Returns pack names that are due for renewal."""
        all_meta = self.config_mgr.get_cert_packs_meta()
        renewable = []
        for pack_id, meta in all_meta.items():
            if meta.get("source") == "acme" and meta.get("auto_renew"):
                if self.check_renewal_needed(pack_id):
                    renewable.append(pack_id)
        return renewable

    def get_pending_packs(self, max_retries: int = 5) -> list[str]:
        """Returns ACME pack names that failed or are pending and eligible for retry."""
        all_meta = self.config_mgr.get_cert_packs_meta()
        pending = []
        for pack_id, meta in all_meta.items():
            if meta.get("source") != "acme":
                continue
            status = meta.get("last_renewal_status", "")
            if status in ("PENDING", "FAILED"):
                if meta.get("retry_count", 0) < max_retries:
                    pending.append(pack_id)
                elif status != "MAX_RETRIES":
                    meta["last_renewal_status"] = "MAX_RETRIES"
                    self.config_mgr.set_cert_pack_meta(pack_id, meta)
                    logger.warning(
                        f"Pack '{pack_id}' exceeded max retries ({max_retries}). "
                        "Giving up - manual intervention required."
                    )
        return pending

    def _purge_certbot_state(self, cert_name: str) -> None:
        """Removes all certbot state for a cert name so it creates a clean directory."""
        patterns = [cert_name, f"{cert_name}-[0-9]*"]

        for pattern in patterns:
            for conf in glob_module.glob(os.path.join(self.le_dir, "renewal", f"{pattern}.conf")):
                logger.info(f"Removing stale renewal config: {conf}")
                os.remove(conf)

            for live in glob_module.glob(os.path.join(self.le_dir, "live", pattern)):
                if os.path.isdir(live):
                    logger.info(f"Removing stale live dir: {live}")
                    shutil.rmtree(live)

            for archive in glob_module.glob(os.path.join(self.le_dir, "archive", pattern)):
                if os.path.isdir(archive):
                    logger.info(f"Removing stale archive dir: {archive}")
                    shutil.rmtree(archive)

    def _build_certbot_cmd(
        self,
        domains: list[str],
        challenge_type: str,
        provider: str,
        credentials: dict,
        email: str,
        cert_name: str,
        key_type: str = "ecdsa",
    ) -> tuple[list[str], dict, list[str]]:
        """Builds the certbot CLI command."""
        self._purge_certbot_state(cert_name)

        cmd = [
            "certbot",
            "certonly",
            "--non-interactive",
            "--agree-tos",
            "--email",
            email,
            "--cert-name",
            cert_name,
            "--config-dir",
            self.le_dir,
            "--work-dir",
            os.path.join(self.le_dir, "work"),
            "--logs-dir",
            os.path.join(self.le_dir, "logs"),
            "--key-type",
            key_type if key_type in ("rsa", "ecdsa") else "ecdsa",
        ]

        for domain in domains:
            cmd.extend(["-d", domain])

        env = dict(os.environ)
        temp_files: list[str] = []

        if challenge_type == "dns-01" and provider in DNS_PROVIDERS:
            prov = DNS_PROVIDERS[provider]
            cmd.append(f"--{prov['plugin']}")

            if prov.get("credentials_ini_template"):
                ini_content = prov["credentials_ini_template"].format(**credentials)
                fd, creds_path = tempfile.mkstemp(suffix=".ini")
                with os.fdopen(fd, "w") as f:
                    f.write(ini_content)
                os.chmod(creds_path, 0o600)
                temp_files.append(creds_path)
                cmd.extend([f"--{prov['plugin']}-credentials", creds_path])
            elif prov.get("env_vars"):
                for env_key, template in prov["env_vars"].items():
                    env[env_key] = template.format(**credentials)
            elif provider == "google" and credentials.get("service_account_json"):
                fd, sa_path = tempfile.mkstemp(suffix=".json")
                with os.fdopen(fd, "w") as f:
                    f.write(credentials["service_account_json"])
                os.chmod(sa_path, 0o600)
                temp_files.append(sa_path)
                cmd.extend(["--dns-google-credentials", sa_path])

            if prov.get("propagation_flag"):
                cmd.extend([prov["propagation_flag"], str(prov.get("default_propagation", 60))])

        elif challenge_type in ("http-01", "tls-alpn-01") and provider in HTTP_PROVIDERS:
            if provider == "standalone":
                cmd.append("--standalone")
                if challenge_type == "tls-alpn-01":
                    cmd.extend(["--preferred-challenges", "tls-alpn-01"])
            elif provider == "webroot":
                cmd.append("--webroot")
                webroot_path = credentials.get("webroot_path", "/var/www/html")
                cmd.extend(["--webroot-path", webroot_path])
            elif provider == "nginx":
                cmd.append("--nginx")
            elif provider == "apache":
                cmd.append("--apache")
        else:
            raise ValueError(
                f"Unsupported challenge/provider combination: {challenge_type}/{provider}"
            )

        return cmd, env, temp_files

    def _import_certbot_result(
        self,
        primary_domain: str,
        pack_name: str,
        is_edge: bool = False,
    ) -> bool:
        """Reads certbot output and imports into a cert pack."""
        live_dir = os.path.join(self.le_dir, "live", pack_name)
        if not os.path.exists(live_dir):
            logger.error(f"Certbot live directory not found: {live_dir}")
            return False

        fullchain_path = os.path.join(live_dir, "fullchain.pem")
        privkey_path = os.path.join(live_dir, "privkey.pem")

        if not os.path.exists(fullchain_path) or not os.path.exists(privkey_path):
            logger.error(f"Certificate files missing in {live_dir}")
            return False

        try:
            with open(fullchain_path, "rb") as f:
                cert_content = f.read()
            with open(privkey_path, "rb") as f:
                key_content = f.read()

            self.cert_store.save_pack(pack_name, cert_content, key_content, is_edge=is_edge)
            logger.info(f"Imported certbot certificate into pack '{pack_name}'.")

            if is_edge:
                os.chmod(privkey_path, 0o644)
                archive_dir = os.path.join(self.le_dir, "archive")
                archive_pack_dir = os.path.join(archive_dir, pack_name)
                if os.path.isdir(archive_dir):
                    os.chmod(archive_dir, 0o755)
                if os.path.isdir(archive_pack_dir):
                    os.chmod(archive_pack_dir, 0o755)
                    for fname in os.listdir(archive_pack_dir):
                        fpath = os.path.join(archive_pack_dir, fname)
                        if os.path.isfile(fpath):
                            os.chmod(fpath, 0o644)
                logger.debug(f"Set nginx-readable permissions on {privkey_path} and archive")

            return True
        except Exception as e:
            logger.error(f"Failed to import certbot result: {e}")
            return False
