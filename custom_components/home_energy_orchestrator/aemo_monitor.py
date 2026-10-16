"""Independent, read-only AEMO observation extension with no control authority.

This is new observer functionality, not a port of the pilot's controllers.
A wholesale-price candidate does not establish a retailer/VPP event or payment.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import re
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta, timezone
from math import isfinite

from aiohttp import ClientError, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .configuration import AemoMonitorConfiguration
from .const import AEMO_REGIONS, DOMAIN
from .persistence import create_typed_value_repository

_LOGGER = logging.getLogger(__name__)
AEMO_DATA_SOURCE = "https://nemweb.com.au/Reports/Current/DispatchIS_Reports/"
AEMO_SUMMARY_SOURCE = "https://visualisations.aemo.com.au/aemo/apps/api/report/ELEC_NEM_SUMMARY"
EVENT_MARKET_OPPORTUNITY = f"{DOMAIN}_market_opportunity"
AEMO_POLL_INTERVAL = timedelta(seconds=30)
AEMO_REQUEST_TIMEOUT = 15
AEMO_HISTORY_LIMIT = 48
_INTERVAL = timedelta(minutes=5)
_AEST = timezone(timedelta(hours=10), "AEST")
_CANDIDATES = frozenset({"possible_export_event", "possible_import_event"})
_INDEX_LIMIT = 2 * 1024 * 1024
_ZIP_LIMIT = 2 * 1024 * 1024
_CSV_LIMIT = 8 * 1024 * 1024
_ROW_LIMIT = 20_000
_REPORT_NAME = re.compile(r"PUBLIC_DISPATCHIS_(\d{12})_(\d{16})\.zip")
_PRICE_FIELDS = frozenset(
    {
        "SETTLEMENTDATE",
        "RUNNO",
        "REGIONID",
        "INTERVENTION",
        "RRP",
        "APCFLAG",
        "MARKETSUSPENDEDFLAG",
        "PRICE_STATUS",
    }
)


class _FeedUnavailable(ValueError):
    def __init__(self, status: str):
        self.status = status
        super().__init__(status)


@dataclass(frozen=True, slots=True)
class _DispatchReport:
    body: bytes
    source_url: str


def _number(value: object) -> float | None:
    """Accept finite JSON numbers, never booleans or coercible strings."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        numeric = float(value)
    except (OverflowError, ValueError):
        return None
    return numeric if isfinite(numeric) else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass(frozen=True, slots=True)
class AemoMonitorResult:
    """Observed current-interval evidence; all confirmation claims are false."""

    status: str
    region: str | None
    export_threshold_per_kwh: float
    import_threshold_per_kwh: float | None
    price_per_mwh: float | None = None
    price_per_kwh: float | None = None
    interval_start: datetime | None = None
    interval_end: datetime | None = None
    first_seen_at: datetime | None = None
    successful_fetch_at: datetime | None = None
    latency_seconds: float | None = None
    price_status: str | None = None
    apc_flag: int | None = None
    market_suspended_flag: int | None = None
    error: str | None = None
    intervention: int | None = None
    source_kind: str = "unverified"
    source_url: str = AEMO_DATA_SOURCE

    @property
    def control_authority(self) -> bool:
        return False

    @property
    def declared_event_confirmed(self) -> bool:
        return False

    @property
    def payment_confirmed(self) -> bool:
        return False

    @property
    def data_source(self) -> str:
        return self.source_url

    @property
    def source_fresh(self) -> bool:
        return (
            self.price_per_mwh is not None
            and self.interval_start is not None
            and self.interval_end is not None
            and self.interval_start <= dt_util.utcnow() < self.interval_end
        )

    @property
    def price_trigger_valid(self) -> bool:
        """Current actual-price evidence; policy/ownership remain external gates."""
        return (
            self.source_fresh
            and self.source_kind == "dispatchis"
            and self.intervention == 0
            and self.price_status == "FIRM"
            and self.apc_flag == 0
            and self.market_suspended_flag == 0
            and self.status in {"watching", *_CANDIDATES}
        )

    @property
    def is_candidate(self) -> bool:
        return self.status in _CANDIDATES

    def attributes(self) -> dict[str, object]:
        """Return JSON-safe provenance for entities and automation events."""
        return {
            "status": self.status,
            "region": self.region,
            "price_per_mwh": self.price_per_mwh,
            "price_per_kwh": self.price_per_kwh,
            "interval_start": _iso(self.interval_start),
            "interval_end": _iso(self.interval_end),
            "first_seen_at": _iso(self.first_seen_at),
            "successful_fetch_at": _iso(self.successful_fetch_at),
            "latency_seconds": self.latency_seconds,
            "latency_basis": "first_observation_after_interval_start",
            "price_status": self.price_status,
            "apc_flag": self.apc_flag,
            "market_suspended_flag": self.market_suspended_flag,
            "export_threshold_per_kwh": self.export_threshold_per_kwh,
            "import_threshold_per_kwh": self.import_threshold_per_kwh,
            "data_source": self.data_source,
            "source_url": self.source_url,
            "source_kind": self.source_kind,
            "intervention": self.intervention,
            "source_fresh": self.source_fresh,
            "price_trigger_valid": self.price_trigger_valid,
            "price_unit": "AUD/kWh",
            "declared_event_confirmed": False,
            "payment_confirmed": False,
            "control_authority": False,
            "error": self.error,
        }

    def observation_signature(self) -> str:
        """Identify a region, interval and correction independently of poll time."""
        return "|".join(
            str(value)
            for value in (
                self.region,
                _iso(self.interval_end),
                self.status,
                self.price_per_mwh,
                self.price_status,
                self.apc_flag,
                self.market_suspended_flag,
                self.source_kind,
                self.intervention,
                float(self.export_threshold_per_kwh),
                (
                    float(self.import_threshold_per_kwh)
                    if self.import_threshold_per_kwh is not None
                    else None
                ),
            )
        )


def _empty(configuration: AemoMonitorConfiguration, status: str) -> AemoMonitorResult:
    return AemoMonitorResult(
        status=status,
        region=configuration.region,
        export_threshold_per_kwh=configuration.export_threshold_per_kwh,
        import_threshold_per_kwh=configuration.import_threshold_per_kwh,
    )


def _configuration_status(configuration: AemoMonitorConfiguration) -> str | None:
    if not configuration.enabled:
        return "disabled"
    if configuration.region is None:
        return "unconfigured"
    export = _number(configuration.export_threshold_per_kwh)
    import_price = _number(configuration.import_threshold_per_kwh)
    if (
        configuration.region not in AEMO_REGIONS
        or export is None
        or export <= 0
        or (
            configuration.import_threshold_per_kwh is not None
            and (import_price is None or import_price >= export)
        )
    ):
        return "invalid_configuration"
    return None


def parse_aemo_summary(
    payload: object, configuration: AemoMonitorConfiguration, now: datetime
) -> AemoMonitorResult:
    """Read one exact regional interval from the AEMO summary, failing closed.

    SETTLEMENTDATE is the interval END in fixed NEM AEST (UTC+10), including
    when a site's civil time observes daylight saving. No forecast is used.
    """
    result = replace(
        _empty(configuration, _configuration_status(configuration) or "watching"),
        source_kind="summary",
        source_url=AEMO_SUMMARY_SOURCE,
    )
    if _configuration_status(configuration):
        return result
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        return replace(result, status="invalid_clock")
    if not isinstance(payload, dict) or not isinstance(payload.get("ELEC_NEM_SUMMARY"), list):
        return replace(result, status="invalid_payload")
    records = payload["ELEC_NEM_SUMMARY"]
    if any(not isinstance(record, dict) for record in records):
        return replace(result, status="invalid_payload")
    matching = [record for record in records if record.get("REGIONID") == configuration.region]
    if not matching:
        return replace(result, status="missing_region")
    if len(matching) != 1:
        return replace(result, status="duplicate_region")
    record = matching[0]
    value = record.get("SETTLEMENTDATE")
    try:
        if not isinstance(value, str):
            raise ValueError
        interval_end = datetime.fromisoformat(value)
        if (
            interval_end.tzinfo is not None
            or interval_end.minute % 5
            or interval_end.second
            or interval_end.microsecond
        ):
            raise ValueError
        interval_end = interval_end.replace(tzinfo=_AEST).astimezone(UTC)
        interval_start = interval_end - _INTERVAL
    except (OverflowError, TypeError, ValueError):
        return replace(result, status="invalid_interval")
    result = replace(result, interval_start=interval_start, interval_end=interval_end)
    if now < interval_start:
        return replace(result, status="future")
    if now >= interval_end:
        return replace(result, status="stale")
    price = _number(record.get("PRICE"))
    if price is None:
        return replace(result, status="invalid_price")
    price_status = record.get("PRICE_STATUS")
    result = replace(result, price_status=price_status if isinstance(price_status, str) else None)
    if price_status != "FIRM":
        return replace(result, status="unknown_price_status")
    apc = _number(record.get("APCFLAG"))
    suspended = _number(record.get("MARKETSUSPENDEDFLAG"))
    if apc not in (0.0, 1.0) or suspended not in (0.0, 1.0):
        return replace(result, status="invalid_market_flags")
    result = replace(
        result,
        apc_flag=int(apc),
        market_suspended_flag=int(suspended),
        price_per_mwh=price,
        price_per_kwh=price / 1000,
        first_seen_at=now,
        successful_fetch_at=now,
        latency_seconds=(now - interval_start).total_seconds(),
    )
    if suspended:
        return replace(result, status="market_suspended")
    if apc:
        return replace(result, status="administered_pricing")
    if price / 1000 >= configuration.export_threshold_per_kwh:
        return replace(result, status="possible_export_event")
    if (
        configuration.import_threshold_per_kwh is not None
        and price / 1000 < configuration.import_threshold_per_kwh
    ):
        return replace(result, status="possible_import_event")
    return result


def _csv_number(value: str) -> float:
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", value):
        raise ValueError("invalid CSV number")
    parsed = float(value)
    if not isfinite(parsed):
        raise ValueError("non-finite CSV number")
    return parsed


def _dispatch_report_identity(source_url: str) -> tuple[datetime, int] | None:
    """Accept correction identities only from the fixed official report origin."""
    if not isinstance(source_url, str) or not source_url.startswith(AEMO_DATA_SOURCE):
        return None
    match = _REPORT_NAME.fullmatch(source_url[len(AEMO_DATA_SOURCE) :])
    if match is None:
        return None
    try:
        end = datetime.strptime(match.group(1), "%Y%m%d%H%M")
    except ValueError:
        return None
    return end.replace(tzinfo=_AEST).astimezone(UTC), int(match.group(2))


def parse_aemo_dispatch_csv(
    payload: bytes,
    configuration: AemoMonitorConfiguration,
    now: datetime,
    *,
    source_url: str = AEMO_DATA_SOURCE,
) -> AemoMonitorResult:
    """Read exactly one intervention-0 PRICE-v5 row; every field shares its interval."""
    empty = replace(
        _empty(configuration, "invalid_dispatch_report"),
        source_kind="dispatchis",
        source_url=source_url,
    )
    if _configuration_status(configuration):
        return replace(empty, status=_configuration_status(configuration))
    try:
        if not isinstance(payload, bytes) or len(payload) > _CSV_LIMIT:
            raise ValueError("CSV size limit")
        rows = csv.reader(io.StringIO(payload.decode("utf-8-sig")), strict=True)
        header = None
        matching = []
        for count, row in enumerate(rows):
            if count >= _ROW_LIMIT or len(row) > 256:
                raise ValueError("CSV row limit")
            if len(row) < 4 or row[1:3] != ["DISPATCH", "PRICE"]:
                continue
            if row[3] != "5":
                raise ValueError("unsupported PRICE version")
            if row[0] == "I":
                if header is not None or len(set(row[4:])) != len(row[4:]):
                    raise ValueError("duplicate PRICE header")
                header = row[4:]
                if not _PRICE_FIELDS <= set(header):
                    raise ValueError("incomplete PRICE header")
            elif row[0] == "D":
                if header is None or len(row) != len(header) + 4:
                    raise ValueError("incoherent PRICE row")
                record = dict(zip(header, row[4:], strict=True))
                if record["REGIONID"] == configuration.region:
                    matching.append(record)
            else:
                raise ValueError("unknown PRICE row")
        if header is None:
            raise ValueError("missing PRICE header")
        if not matching:
            return replace(empty, status="missing_region")
        if len(matching) != 1:
            return replace(empty, status="duplicate_region")
        record = matching[0]
        if _csv_number(record["INTERVENTION"]) != 0:
            return replace(empty, status="nonzero_intervention")
        if _csv_number(record["RUNNO"]) != 1:
            return replace(empty, status="invalid_dispatch_run")
        end = datetime.strptime(record["SETTLEMENTDATE"], "%Y/%m/%d %H:%M:%S")
        coherent = {
            "ELEC_NEM_SUMMARY": [
                {
                    "REGIONID": record["REGIONID"],
                    "SETTLEMENTDATE": end.isoformat(),
                    "PRICE": _csv_number(record["RRP"]),
                    "PRICE_STATUS": record["PRICE_STATUS"],
                    "APCFLAG": _csv_number(record["APCFLAG"]),
                    "MARKETSUSPENDEDFLAG": _csv_number(record["MARKETSUSPENDEDFLAG"]),
                }
            ]
        }
        return replace(
            parse_aemo_summary(coherent, configuration, now),
            intervention=0,
            source_kind="dispatchis",
            source_url=source_url,
        )
    except (csv.Error, UnicodeError, OverflowError, TypeError, ValueError):
        return empty


def parse_aemo_dispatch_zip(
    payload: bytes,
    configuration: AemoMonitorConfiguration,
    now: datetime,
    *,
    source_url: str = AEMO_DATA_SOURCE,
) -> AemoMonitorResult:
    """Bound compressed/uncompressed data and read in memory; never extract a file."""
    empty = replace(
        _empty(configuration, "invalid_dispatch_archive"),
        source_kind="dispatchis",
        source_url=source_url,
    )
    try:
        if not isinstance(payload, bytes) or len(payload) > _ZIP_LIMIT:
            return empty
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            files = archive.infolist()
            if len(files) != 1:
                return empty
            info = files[0]
            if (
                not re.fullmatch(r"PUBLIC_DISPATCHIS_\d{12}_\d{16}\.CSV", info.filename)
                or info.flag_bits & 1
                or info.file_size > _CSV_LIMIT
                or info.compress_size > _ZIP_LIMIT
                or info.file_size > max(info.compress_size, 1) * 200
                or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
            ):
                return empty
            source_identity = _dispatch_report_identity(source_url)
            if source_identity is not None and (
                info.filename != source_url[len(AEMO_DATA_SOURCE) : -4] + ".CSV"
            ):
                return replace(empty, status="report_identity_mismatch")
            with archive.open(info) as file:
                contents = file.read(_CSV_LIMIT + 1)
            if len(contents) > _CSV_LIMIT:
                return empty
            result = parse_aemo_dispatch_csv(contents, configuration, now, source_url=source_url)
            report_end = datetime.strptime(info.filename[18:30], "%Y%m%d%H%M")
            if result.interval_end is not None and (
                result.interval_end != report_end.replace(tzinfo=_AEST).astimezone(UTC)
            ):
                return replace(empty, status="report_interval_mismatch")
            return result
    except (zipfile.BadZipFile, zlib.error, RuntimeError, OSError, EOFError, ValueError):
        return empty


def current_dispatch_report_url(index: str, now: datetime) -> str:
    """Only the interval covering now qualifies, including exactly at a boundary."""
    if not isinstance(index, str) or len(index.encode()) > _INDEX_LIMIT:
        raise _FeedUnavailable("invalid_dispatch_index")
    if now.tzinfo is None or now.utcoffset() is None:
        raise _FeedUnavailable("invalid_clock")
    market = now.astimezone(_AEST).replace(second=0, microsecond=0)
    end = market + timedelta(minutes=5 - market.minute % 5)
    stamp = end.strftime("%Y%m%d%H%M")
    matches = {match.group(0) for match in _REPORT_NAME.finditer(index) if match.group(1) == stamp}
    if not matches:
        raise _FeedUnavailable("awaiting_current_report")
    # A correction/re-run for the same interval supersedes its older report.
    return AEMO_DATA_SOURCE + max(matches)


@dataclass(slots=True)
class _MonitorState:
    observations: list[AemoMonitorResult] = field(default_factory=list)
    active_candidate: AemoMonitorResult | None = None
    last_notified_signature: str | None = None

    def payload(self) -> dict[str, object]:
        return {
            "observations": [record.attributes() for record in self.observations],
            "active_candidate": (
                self.active_candidate.attributes() if self.active_candidate else None
            ),
            "last_notified_signature": self.last_notified_signature,
        }


class AemoMarketMonitor(DataUpdateCoordinator[AemoMonitorResult]):
    """Poll public market evidence independently of energy/control coordinators."""

    def __init__(
        self, hass: HomeAssistant, entry_id: str, configuration: AemoMonitorConfiguration
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=None,
            name="AemoMarketMonitor",
            update_interval=(
                AEMO_POLL_INTERVAL if _configuration_status(configuration) is None else None
            ),
        )
        self.entry_id = entry_id
        self.configuration = configuration
        self._result = _empty(
            configuration, _configuration_status(configuration) or "awaiting_data"
        )
        self.data = self._result
        self._state = _MonitorState()
        self._lock = asyncio.Lock()
        self.settings_lock = asyncio.Lock()
        self._configuration_generation = 0
        self._configuration_refresh_task: asyncio.Task[None] | None = None
        self._saving_task: asyncio.Task[object] | None = None
        self._shutdown_registered = False
        self._keepalive_unsub: Callable[[], None] | None = None
        self._expiry_unsub: Callable[[], None] | None = None
        self._stopped = False
        self._persistence_status = "awaiting_load"
        self._repository = create_typed_value_repository(
            hass,
            storage_version=1,
            storage_key=f"{DOMAIN}.{entry_id}.aemo_monitor",
            decode=self._decode_state,
            encode=lambda state: state.payload(),
        )

    @property
    def current_result(self) -> AemoMonitorResult:
        """Never expose a current numeric price beyond its exact interval end."""
        return self._current_at(self._result, dt_util.utcnow())

    @staticmethod
    def _current_at(result: AemoMonitorResult, now: datetime) -> AemoMonitorResult:
        if result.price_per_mwh is not None and result.interval_end is not None:
            if now >= result.interval_end:
                return replace(result, status="stale", price_per_mwh=None, price_per_kwh=None)
            if result.interval_start is not None and now < result.interval_start:
                return replace(result, status="future", price_per_mwh=None, price_per_kwh=None)
        return result

    @property
    def recent_observations(self) -> list[dict[str, object]]:
        """Return bounded history for diagnostics, not recurring entity attributes."""
        return [record.attributes() for record in self._state.observations]

    @property
    def result_attributes(self) -> dict[str, object]:
        return {
            **self.current_result.attributes(),
            "recent_observation_count": len(self._state.observations),
            "persistence_status": self._persistence_status,
        }

    async def async_restore_history(self) -> None:
        """Restore bounded observation history and notification deduplication."""
        try:
            self._state = await self._repository.async_load()
            self._persistence_status = self._repository.last_restore_status
        except (OSError, HomeAssistantError, ValueError, TypeError):
            self._state = _MonitorState()
            self._persistence_status = "unavailable"
            _LOGGER.warning("Could not restore AEMO observation deduplication", exc_info=True)
        if (
            self._state.active_candidate is not None
            and _configuration_status(self.configuration) is None
        ):
            self._schedule_expiry(self._state.active_candidate.interval_end)

    async def async_start(self) -> None:
        """Fetch once without making feed availability an HEO setup requirement."""
        await self._async_ensure_polling()
        if not self._stopped:
            await self.async_refresh()

    async def _async_ensure_polling(self) -> None:
        if self._stopped or _configuration_status(self.configuration) is not None:
            return
        if self._keepalive_unsub is None:
            self._keepalive_unsub = self.async_add_listener(lambda: None)
        if not self._shutdown_registered:
            await self.async_register_shutdown()
            self._shutdown_registered = True

    async def async_update_configuration(self, configuration: AemoMonitorConfiguration) -> None:
        """Apply dashboard settings atomically, scheduling fresh evidence separately.

        settings_lock is available for the caller's config-entry transaction;
        this method uses only the independent observer's internal state lock.
        """
        async with self._lock:
            if self._stopped or configuration == self.configuration:
                return
            self._configuration_generation += 1
            generation = self._configuration_generation
            self.configuration = configuration
            configuration_status = _configuration_status(configuration)
            self.update_interval = AEMO_POLL_INTERVAL if configuration_status is None else None
            self._async_unsub_refresh()
            self._debounced_refresh.async_cancel()
            self._cancel_configuration_refresh()
            if configuration_status is not None and self._keepalive_unsub is not None:
                self._keepalive_unsub()
                self._keepalive_unsub = None
            await self._async_commit_result(
                _empty(configuration, configuration_status or "awaiting_data")
            )
            if self._stopped:
                return
            await self._async_ensure_polling()
            self.async_set_updated_data(self.current_result)
        if configuration_status is None and generation == self._configuration_generation:
            self._configuration_refresh_task = self.hass.async_create_background_task(
                self._async_refresh_configuration(generation),
                name="AemoMarketMonitor - settings refresh",
                eager_start=False,
            )

    async def _async_refresh_configuration(self, generation: int) -> None:
        try:
            if not self._stopped and generation == self._configuration_generation:
                await self.async_refresh()
        finally:
            if self._configuration_refresh_task is asyncio.current_task():
                self._configuration_refresh_task = None

    def _cancel_configuration_refresh(self) -> asyncio.Task[None] | None:
        task = self._configuration_refresh_task
        self._configuration_refresh_task = None
        if task is not None and task is not self._saving_task:
            task.cancel()
        return task

    async def async_stop(self) -> None:
        """Stop polling and exact-boundary listeners without clearing saved evidence."""
        self._stopped = True
        if self._expiry_unsub is not None:
            self._expiry_unsub()
            self._expiry_unsub = None
        if self._keepalive_unsub is not None:
            self._keepalive_unsub()
            self._keepalive_unsub = None
        await self.async_shutdown()
        async with self._lock:
            pass  # Finish an observation's ongoing Store save before reload.

    async def async_shutdown(self) -> None:
        """Cancel independent expiry when HA shuts down the coordinator."""
        self._stopped = True
        self._configuration_generation += 1
        pending_refresh = self._cancel_configuration_refresh()
        if self._expiry_unsub is not None:
            self._expiry_unsub()
            self._expiry_unsub = None
        await super().async_shutdown()
        if pending_refresh is not None and pending_refresh is not asyncio.current_task():
            try:
                await pending_refresh
            except asyncio.CancelledError:
                pass

    async def _async_fetch_summary(self) -> object:
        """Fetch the exact current DispatchIS report; historical method name retained."""
        session = async_get_clientsession(self.hass)
        timeout = ClientTimeout(total=AEMO_REQUEST_TIMEOUT)

        async def read(response, limit: int) -> bytes:
            content_length = getattr(response, "content_length", None)
            if content_length is not None and content_length > limit:
                raise _FeedUnavailable("response_size_limit")
            data = bytearray()
            async for block in response.content.iter_chunked(16 * 1024):
                data.extend(block)
                if len(data) > limit:
                    raise _FeedUnavailable("response_size_limit")
            return bytes(data)

        # The two network operations share one timeout, shorter than the poll interval.
        async with asyncio.timeout(AEMO_REQUEST_TIMEOUT):
            async with session.get(
                AEMO_DATA_SOURCE, timeout=timeout, headers={"Cache-Control": "no-cache"}
            ) as response:
                response.raise_for_status()
                index = (await read(response, _INDEX_LIMIT)).decode("utf-8")
            source = current_dispatch_report_url(index, dt_util.utcnow())
            async with session.get(
                source, timeout=timeout, headers={"Cache-Control": "no-cache"}
            ) as response:
                response.raise_for_status()
                body = await read(response, _ZIP_LIMIT)
        return _DispatchReport(body, source)

    async def _async_update_data(self) -> AemoMonitorResult:
        configuration = self.configuration
        generation = self._configuration_generation
        configuration_status = _configuration_status(configuration)
        if configuration_status is not None:
            result = _empty(configuration, configuration_status)
        else:
            try:
                payload = await self._async_fetch_summary()
                now = dt_util.utcnow()
                parsed = (
                    parse_aemo_dispatch_zip(
                        payload.body, configuration, now, source_url=payload.source_url
                    )
                    if isinstance(payload, _DispatchReport)
                    else parse_aemo_summary(payload, configuration, now)
                )
                result = replace(
                    parsed,
                    successful_fetch_at=now,
                )
            except _FeedUnavailable as error:
                result = replace(
                    _empty(configuration, error.status),
                    successful_fetch_at=self._result.successful_fetch_at,
                    error=error.status,
                )
            except (ClientError, TimeoutError, ValueError, TypeError) as error:
                result = replace(
                    _empty(configuration, "unavailable"),
                    successful_fetch_at=self._result.successful_fetch_at,
                    error=type(error).__name__,
                )
        await self._async_apply_result(result, configuration_generation=generation)
        return self.current_result

    async def _async_apply_result(
        self,
        result: AemoMonitorResult,
        *,
        expired_interval_end: datetime | None = None,
        configuration_generation: int | None = None,
    ) -> bool:
        async with self._lock:
            if self._stopped or (
                configuration_generation is not None
                and configuration_generation != self._configuration_generation
            ):
                return False
            if expired_interval_end is not None:
                source = (
                    self._result
                    if self._result.interval_end is not None
                    else self._state.active_candidate
                )
                if source is None or source.interval_end != expired_interval_end:
                    return False
                result = replace(source, status="stale", price_per_mwh=None, price_per_kwh=None)
            else:
                result = self._current_at(result, dt_util.utcnow())
            await self._async_commit_result(result)
            return True

    async def _async_commit_result(self, result: AemoMonitorResult) -> None:
        """Commit current evidence while the caller holds the state lock."""
        result = self._prevent_dispatch_replay(result)
        changed = False
        event: dict[str, object] | None = None
        if result.price_per_mwh is not None:
            prior = next(
                (
                    record
                    for record in self._state.observations
                    if record.region == result.region and record.interval_end == result.interval_end
                ),
                None,
            )
            if prior is not None:
                result = replace(
                    result,
                    first_seen_at=prior.first_seen_at,
                    latency_seconds=prior.latency_seconds,
                )
            signature = result.observation_signature()
            if (
                not self._state.observations
                or self._state.observations[-1].observation_signature() != signature
                or (
                    result.source_kind == "dispatchis"
                    and self._state.observations[-1].source_url != result.source_url
                )
            ):
                self._state.observations.append(result)
                self._state.observations = self._state.observations[-AEMO_HISTORY_LIMIT:]
                changed = True
        # No awaited I/O separates this eligibility check and event emission.
        result = self._current_at(result, dt_util.utcnow())
        previous = self._state.active_candidate
        if result.is_candidate:
            signature = result.observation_signature()
            if signature != self._state.last_notified_signature:
                event = {"phase": "update" if previous else "onset", **result.attributes()}
                self._state.last_notified_signature = signature
                changed = True
            self._state.active_candidate = result
        elif previous is not None:
            event = {
                "phase": "clear",
                **result.attributes(),
                "previous_status": previous.status,
                "previous_interval_start": _iso(previous.interval_start),
                "previous_interval_end": _iso(previous.interval_end),
                "previous_price_per_kwh": previous.price_per_kwh,
            }
            self._state.last_notified_signature = (
                f"clear|{previous.observation_signature()}|{result.status}"
            )
            self._state.active_candidate = None
            changed = True
        self._result = result
        self._schedule_expiry(result.interval_end if result.price_per_mwh is not None else None)
        if event is not None and not self._stopped:
            self.hass.bus.async_fire(EVENT_MARKET_OPPORTUNITY, {"entry_id": self.entry_id, **event})
        if changed:
            self._saving_task = asyncio.current_task()
            try:
                await self._repository.async_save(self._state)
                self._persistence_status = "available"
            except (OSError, HomeAssistantError, ValueError, TypeError):
                self._persistence_status = "unavailable"
                _LOGGER.warning("Could not save AEMO observation deduplication", exc_info=True)
            finally:
                self._saving_task = None

    def _prevent_dispatch_replay(self, result: AemoMonitorResult) -> AemoMonitorResult:
        """Never roll a current region/interval back to an older accepted correction."""
        identity = _dispatch_report_identity(result.source_url)
        if (
            result.source_kind != "dispatchis"
            or result.price_per_mwh is None
            or identity is None
            or identity[0] != result.interval_end
        ):
            return result
        accepted = []
        for record in self._state.observations:
            prior_identity = _dispatch_report_identity(record.source_url)
            if (
                record.region == result.region
                and record.interval_end == result.interval_end
                and record.source_kind == "dispatchis"
                and record.intervention == 0
                and record.price_status == "FIRM"
                and record.apc_flag in (0, 1)
                and record.market_suspended_flag in (0, 1)
                and record.price_per_mwh is not None
                and record.price_per_kwh is not None
                and prior_identity is not None
                and prior_identity[0] == record.interval_end
            ):
                accepted.append((prior_identity[1], record))
        if not accepted:
            return result
        serial, newest = max(accepted, key=lambda item: item[0])
        if serial <= identity[1]:
            return result
        # Preserve the accepted source/fetch timestamps. A new config may change
        # the observation threshold, but cannot turn an old fetch into new evidence.
        configuration = self.configuration
        status = "watching"
        if newest.market_suspended_flag:
            status = "market_suspended"
        elif newest.apc_flag:
            status = "administered_pricing"
        elif newest.price_per_kwh >= configuration.export_threshold_per_kwh:
            status = "possible_export_event"
        elif (
            configuration.import_threshold_per_kwh is not None
            and newest.price_per_kwh < configuration.import_threshold_per_kwh
        ):
            status = "possible_import_event"
        return replace(
            newest,
            status=status,
            export_threshold_per_kwh=configuration.export_threshold_per_kwh,
            import_threshold_per_kwh=configuration.import_threshold_per_kwh,
        )

    def _schedule_expiry(self, interval_end: datetime | None) -> None:
        if self._expiry_unsub is not None:
            self._expiry_unsub()
            self._expiry_unsub = None
        if interval_end is not None and not self._stopped:
            generation = self._configuration_generation

            async def expire(now: datetime) -> None:
                await self._async_expire(now, interval_end, generation)

            self._expiry_unsub = async_track_point_in_utc_time(self.hass, expire, interval_end)

    async def _async_expire(
        self,
        now: datetime,
        interval_end: datetime | None = None,
        configuration_generation: int | None = None,
    ) -> None:
        source = (
            self._result if self._result.interval_end is not None else self._state.active_candidate
        )
        if source is None:
            return
        expected_end = interval_end or source.interval_end
        if expected_end is None or now < expected_end:
            return
        applied = await self._async_apply_result(
            source,
            expired_interval_end=expected_end,
            configuration_generation=configuration_generation,
        )
        if applied and not self._stopped:
            self.async_set_updated_data(self.current_result)

    def _decode_state(self, payload: dict[str, object] | None) -> _MonitorState:
        state = _MonitorState()
        if payload is None:
            return state
        records = payload.get("observations")
        if isinstance(records, list):
            for record in records[-AEMO_HISTORY_LIMIT:]:
                restored = self._restore_observation(record)
                if restored is not None:
                    state.observations.append(restored)
        active = self._restore_observation(payload.get("active_candidate"))
        last_signature = payload.get("last_notified_signature")
        if isinstance(last_signature, str) and len(last_signature) <= 512:
            state.last_notified_signature = last_signature
        if active is not None and active.is_candidate:
            state.active_candidate = active
        return state

    def _restore_observation(self, payload: object) -> AemoMonitorResult | None:
        if not isinstance(payload, dict) or payload.get("region") not in AEMO_REGIONS:
            return None
        try:
            export_threshold = _number(payload["export_threshold_per_kwh"])
            import_threshold = _number(payload["import_threshold_per_kwh"])
            if export_threshold is None or (
                payload["import_threshold_per_kwh"] is not None and import_threshold is None
            ):
                return None
            historical_configuration = AemoMonitorConfiguration(
                True, payload["region"], export_threshold, import_threshold
            )
            first_seen = datetime.fromisoformat(str(payload["first_seen_at"]))
            successful_fetch = datetime.fromisoformat(str(payload["successful_fetch_at"]))
            interval_end = datetime.fromisoformat(str(payload["interval_end"]))
            if any(value.tzinfo is None for value in (first_seen, successful_fetch, interval_end)):
                return None
            raw = {
                "ELEC_NEM_SUMMARY": [
                    {
                        "REGIONID": payload["region"],
                        "PRICE": payload["price_per_mwh"],
                        "SETTLEMENTDATE": interval_end.astimezone(_AEST)
                        .replace(tzinfo=None)
                        .isoformat(),
                        "PRICE_STATUS": payload["price_status"],
                        "APCFLAG": payload["apc_flag"],
                        "MARKETSUSPENDEDFLAG": payload["market_suspended_flag"],
                    }
                ]
            }
            restored = parse_aemo_summary(raw, historical_configuration, first_seen)
            if (
                restored.price_per_mwh is None
                or successful_fetch < first_seen
                or successful_fetch >= interval_end
            ):
                return None
            return replace(
                restored,
                successful_fetch_at=successful_fetch,
                intervention=0 if payload.get("intervention") == 0 else None,
                source_kind="dispatchis"
                if payload.get("source_kind") == "dispatchis"
                else "summary",
                source_url=str(payload.get("data_source", AEMO_SUMMARY_SOURCE)),
            )
        except (KeyError, OverflowError, TypeError, ValueError):
            return None
