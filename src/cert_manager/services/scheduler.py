"""Background scheduler for certificate renewal and service health monitoring."""

import asyncio
import datetime
import logging

logger = logging.getLogger("cert_manager.scheduler")

# How often the service monitor runs (health checks + pending cert retries)
SERVICE_CHECK_INTERVAL_SECONDS = 300  # 5 minutes
MAX_CERT_RETRIES = 5


class RenewalScheduler:
    """Runs background tasks for certificate renewal and service monitoring.

    Two independent loops:
    - Renewal check: runs daily at a configured time to renew expiring certs.
    - Service monitor: runs every 5 minutes to health-check services and
      retry any pending/failed ACME certificate requests.
    """

    def __init__(
        self,
        acme_manager,
        config_manager,
        cert_store=None,
        deploy_callback=None,
        nginx_reload_callback=None,
        health_check_fn=None,
    ) -> None:
        self.acme = acme_manager
        self.config = config_manager
        self.cert_store = cert_store
        self.deploy_callback = deploy_callback
        self.nginx_reload_callback = nginx_reload_callback
        self.health_check_fn = health_check_fn
        self._renewal_task: asyncio.Task | None = None
        self._monitor_task: asyncio.Task | None = None
        self._running = False
        self.next_check: datetime.datetime | None = None

    @property
    def is_running(self) -> bool:
        """Returns True if the scheduler background tasks are active."""
        return self._running

    def start(self) -> None:
        """Starts both background tasks (renewal + service monitor)."""
        if self._running:
            return
        self._running = True
        self._renewal_task = asyncio.create_task(self._renewal_loop())
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("Scheduler started (renewal + service monitor).")

    def stop(self) -> None:
        """Stops all background tasks."""
        self._running = False
        for task in (self._renewal_task, self._monitor_task):
            if task and not task.done():
                task.cancel()
        logger.info("Scheduler stopped.")

    # --- Renewal Loop (daily) ---

    async def _renewal_loop(self) -> None:
        """Main renewal loop - checks renewal daily at configured time."""
        while self._running:
            try:
                wait_seconds = self._seconds_until_next_check()
                self.next_check = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
                    seconds=wait_seconds
                )
                logger.info(f"Next renewal check at {self.next_check.isoformat()}")

                await asyncio.sleep(wait_seconds)

                if self._running:
                    await self._perform_renewal_check()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Renewal loop error: {e}")
                await asyncio.sleep(3600)

    def _seconds_until_next_check(self) -> float:
        """Calculates seconds until the configured check time."""
        settings = self.config.get_app_settings()
        check_time_str = settings.get("scheduler_time", "00:30")

        try:
            hour, minute = map(int, check_time_str.split(":"))
        except (ValueError, AttributeError):
            hour, minute = 0, 30

        now = datetime.datetime.now(datetime.timezone.utc)
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        if target <= now:
            target += datetime.timedelta(days=1)

        return (target - now).total_seconds()

    async def _perform_renewal_check(self) -> None:
        """Checks all ACME packs and renews those within the renewal window."""
        logger.info("Starting scheduled renewal check...")

        renewable = self.acme.get_renewable_packs()
        if not renewable:
            logger.info("No certificates due for renewal.")
            return

        for pack_name in renewable:
            logger.info(f"Renewing certificate pack: {pack_name}")
            try:
                result = self.acme.renew_certificate(pack_name)
                if result.get("success"):
                    logger.info(f"Renewal succeeded for '{pack_name}'.")
                    meta = self.config.get_cert_pack_meta(pack_name)
                    if self.nginx_reload_callback and meta and meta.get("is_edge"):
                        await self.nginx_reload_callback()
                    if self.deploy_callback:
                        await self.deploy_callback(pack_name)
                else:
                    logger.error(f"Renewal failed for '{pack_name}': {result.get('message')}")
            except Exception as e:
                logger.error(f"Error renewing '{pack_name}': {e}")

        logger.info("Scheduled renewal check complete.")

    # --- Service Monitor Loop (every 5 minutes) ---

    async def _monitor_loop(self) -> None:
        """Runs health checks and pending cert retries on a fixed interval."""
        # Run immediately on startup
        if self._running:
            await self._perform_service_check()

        while self._running:
            try:
                await asyncio.sleep(SERVICE_CHECK_INTERVAL_SECONDS)
                if self._running:
                    await self._perform_service_check()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Service monitor error: {e}")
                await asyncio.sleep(60)

    async def _perform_service_check(self) -> None:
        """Health-checks all services and retries pending ACME requests."""
        logger.info("Starting service health check...")
        await self._health_check_all_services()
        await self._retry_pending_certs()
        logger.info("Service check complete.")

    async def _health_check_all_services(self) -> None:
        """Runs health check against all enabled services."""
        if not self.health_check_fn:
            return

        services = self.config.get_services()
        for service in services:
            if not service.get("enabled", True):
                continue
            try:
                status = await asyncio.to_thread(self.health_check_fn, service)
                if status == "Cert mismatch" and self.deploy_callback:
                    pack_name = service.get("cert_pack_id")
                    if pack_name:
                        logger.info(f"Cert mismatch on '{service['name']}' - auto-deploying")
                        await self.deploy_callback(pack_name)
                        # Re-check after deploy
                        await asyncio.to_thread(self.health_check_fn, service)
                else:
                    logger.debug(f"Health check OK for '{service['name']}'")
            except Exception as e:
                logger.warning(f"Health check failed for '{service['name']}': {e}")

    async def _retry_pending_certs(self) -> None:
        """Retries ACME cert requests that are pending or previously failed."""
        pending = self.acme.get_pending_packs(max_retries=MAX_CERT_RETRIES)
        if not pending:
            return

        for pack_name in pending:
            meta = self.config.get_cert_pack_meta(pack_name)
            retry_count = meta.get("retry_count", 0)
            logger.info(
                f"Retrying ACME request for '{pack_name}' "
                f"(attempt {retry_count + 1}/{MAX_CERT_RETRIES})"
            )
            try:
                result = self.acme.renew_certificate(pack_name)
                if result.get("success"):
                    logger.info(f"Retry succeeded for '{pack_name}'.")
                    meta = self.config.get_cert_pack_meta(pack_name)
                    if self.nginx_reload_callback and meta and meta.get("is_edge"):
                        await self.nginx_reload_callback()
                    if self.deploy_callback:
                        await self.deploy_callback(pack_name)
                else:
                    logger.warning(f"Retry failed for '{pack_name}': {result.get('message')}")
            except Exception as e:
                logger.error(f"Error retrying '{pack_name}': {e}")
