"""Certificate pack file management - read, write, list, delete cert packs."""

import logging
import os
import subprocess

from cert_manager.core import cert_validator

logger = logging.getLogger("cert_manager.store")

# Known ACME certificate authority issuer organization names.
_ACME_ISSUER_ORGS = (
    "Let's Encrypt",
    "ZeroSSL",
    "Buypass",
    "Google Trust Services",
)


def _detect_source_from_issuer(issuer: str | None) -> str:
    """Detects certificate source from the issuer string."""
    if not issuer:
        return "manual"
    for org in _ACME_ISSUER_ORGS:
        if org.lower() in issuer.lower():
            return "acme"
    return "manual"


class CertStore:
    """Manages certificate pack files on the filesystem.

    Cert packs are stored in two locations:
    - ssl/live/{domain}/ - edge certs (shared with nginx)
    - data/certs/{pack-name}/ - additional cert packs
    """

    def __init__(
        self,
        ssl_dir: str,
        certs_dir: str,
        edge_domain: str = "",
    ) -> None:
        self.ssl_dir = ssl_dir
        self.certs_dir = certs_dir
        self.edge_domain = edge_domain
        os.makedirs(self.certs_dir, exist_ok=True)

    def list_packs(self, config_meta: dict | None = None) -> list[dict]:
        """Lists all cert packs with their details."""
        packs = []
        config_meta = config_meta or {}

        # Scan ssl/live/ for edge certs (skip symlinks and placeholders)
        live_dir = os.path.join(self.ssl_dir, "live")
        if os.path.isdir(live_dir):
            for name in os.listdir(live_dir):
                pack_dir = os.path.join(live_dir, name)
                if os.path.islink(pack_dir):
                    continue
                if not os.path.isdir(pack_dir):
                    continue
                if os.path.isfile(os.path.join(pack_dir, ".placeholder")):
                    continue
                info = self._read_pack_info(name, pack_dir, config_meta.get(name, {}))
                if info:
                    packs.append(info)

        # Scan certs/ for additional packs (skip duplicates)
        seen = {p["name"] for p in packs}
        if os.path.isdir(self.certs_dir):
            for name in os.listdir(self.certs_dir):
                if name in seen:
                    continue
                pack_dir = os.path.join(self.certs_dir, name)
                if os.path.isdir(pack_dir):
                    info = self._read_pack_info(name, pack_dir, config_meta.get(name, {}))
                    if info:
                        packs.append(info)

        return packs

    def _read_pack_info(self, name: str, pack_dir: str, meta: dict) -> dict | None:
        """Reads certificate details from a pack directory."""
        fullchain_path = os.path.join(pack_dir, "fullchain.pem")
        if not os.path.isfile(fullchain_path):
            return None

        try:
            with open(fullchain_path, "rb") as f:
                cert_data = f.read()

            details = cert_validator.get_cert_details(cert_validator.load_cert(cert_data))
            if not details:
                return None

            source = meta.get("source")
            if not source:
                source = _detect_source_from_issuer(details.get("issuer"))

            return {
                "name": name,
                "path": pack_dir,
                "domains": details.get("sans", []),
                "source": source,
                "not_before": details.get("not_before"),
                "not_after": details.get("not_after"),
                "days_remaining": details.get("days_remaining"),
                "issuer": details.get("issuer"),
                "subject": details.get("subject"),
                "serial_number": details.get("serial_number"),
                "key_type": cert_validator.detect_key_type(cert_data),
                "auto_renew": meta.get("auto_renew", False),
                "is_edge": meta.get("is_edge", False),
                "provider": meta.get("provider"),
                "challenge_type": meta.get("challenge_type"),
                "credential_id": meta.get("credential_id"),
                "last_renewal": meta.get("last_acme_renewal"),
                "last_renewal_status": meta.get("last_renewal_status", "NEVER"),
            }
        except Exception as e:
            logger.error(f"Failed to read cert pack '{name}': {e}")
            return None

    def get_pack(self, name: str, config_meta: dict | None = None) -> dict | None:
        """Gets a single cert pack by name."""
        packs = self.list_packs(config_meta)
        return next((p for p in packs if p["name"] == name), None)

    def save_pack(
        self,
        name: str,
        fullchain: bytes,
        privkey: bytes,
        is_edge: bool = False,
    ) -> str:
        """Saves a certificate pack to the filesystem."""
        if is_edge:
            pack_dir = os.path.join(self.ssl_dir, "live", name)
        else:
            pack_dir = os.path.join(self.certs_dir, name)

        os.makedirs(pack_dir, exist_ok=True)

        fullchain_path = os.path.join(pack_dir, "fullchain.pem")
        privkey_path = os.path.join(pack_dir, "privkey.pem")

        with open(fullchain_path, "wb") as f:
            f.write(cert_validator.normalize_pem(fullchain))
        os.chmod(fullchain_path, 0o644)

        with open(privkey_path, "wb") as f:
            f.write(cert_validator.normalize_pem(privkey))
        os.chmod(privkey_path, 0o644 if is_edge else 0o600)

        if is_edge and self.edge_domain:
            self._remove_placeholder()
            if name != self.edge_domain:
                self._link_edge_domain(name)

        logger.info(f"Saved cert pack '{name}' to {pack_dir}")
        return pack_dir

    def _remove_placeholder(self) -> None:
        """Removes the self-signed placeholder cert directory."""
        edge_dir = os.path.join(self.ssl_dir, "live", self.edge_domain)
        marker = os.path.join(edge_dir, ".placeholder")
        if os.path.isfile(marker):
            import shutil

            shutil.rmtree(edge_dir)
            logger.info(f"Removed self-signed placeholder at {edge_dir}")

    def _link_edge_domain(self, pack_name: str) -> None:
        """Creates a symlink from the edge domain directory to the pack."""
        live_dir = os.path.join(self.ssl_dir, "live")
        link_path = os.path.join(live_dir, self.edge_domain)
        target = pack_name

        if os.path.islink(link_path):
            os.remove(link_path)
        elif os.path.isdir(link_path):
            import shutil

            shutil.rmtree(link_path)
            logger.info(f"Replaced edge domain directory with symlink: {link_path}")

        os.symlink(target, link_path)
        logger.info(f"Linked edge domain {self.edge_domain} -> {pack_name}")

    def delete_pack(self, name: str) -> bool:
        """Deletes a cert pack directory."""
        import shutil

        for base_dir in [os.path.join(self.ssl_dir, "live"), self.certs_dir]:
            pack_dir = os.path.join(base_dir, name)
            if os.path.isdir(pack_dir):
                shutil.rmtree(pack_dir)
                logger.info(f"Deleted cert pack '{name}' from {pack_dir}")
                self._cleanup_edge_symlink(name)
                return True
        return False

    def _cleanup_edge_symlink(self, deleted_name: str) -> None:
        """Removes a dangling edge symlink and regenerates a placeholder."""
        if not self.edge_domain:
            return

        live_dir = os.path.join(self.ssl_dir, "live")
        link_path = os.path.join(live_dir, self.edge_domain)

        if not os.path.islink(link_path):
            return

        target = os.readlink(link_path)
        target_name = os.path.basename(target)
        if target_name != deleted_name:
            return

        os.remove(link_path)
        logger.info(f"Removed dangling edge symlink: {link_path} -> {target}")
        self._generate_placeholder(link_path)

    def _generate_placeholder(self, cert_dir: str) -> None:
        """Generates a self-signed placeholder certificate for nginx."""
        os.makedirs(cert_dir, exist_ok=True)
        fullchain = os.path.join(cert_dir, "fullchain.pem")
        privkey = os.path.join(cert_dir, "privkey.pem")
        domain = self.edge_domain or "localhost"

        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-nodes",
                "-newkey",
                "rsa:2048",
                "-days",
                "1",
                "-keyout",
                privkey,
                "-out",
                fullchain,
                "-subj",
                f"/CN={domain}/O=Self-Signed",
            ],
            check=True,
            capture_output=True,
        )
        os.chmod(privkey, 0o644)

        marker = os.path.join(cert_dir, ".placeholder")
        with open(marker, "w") as f:
            f.write("self-signed placeholder for nginx startup\n")

        logger.info(f"Generated self-signed placeholder for {domain}.")

    def get_pack_paths(self, name: str) -> tuple[str, str] | None:
        """Returns (fullchain_path, privkey_path) for a cert pack."""
        for base_dir in [os.path.join(self.ssl_dir, "live"), self.certs_dir]:
            pack_dir = os.path.join(base_dir, name)
            fullchain = os.path.join(pack_dir, "fullchain.pem")
            privkey = os.path.join(pack_dir, "privkey.pem")
            if os.path.isfile(fullchain) and os.path.isfile(privkey):
                return (fullchain, privkey)
        return None
