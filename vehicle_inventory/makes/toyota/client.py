import json
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple
from uuid import uuid4

import requests


GRAPHQL_ENDPOINT = "https://api.search-inventory.toyota.com/graphql"


LOCATE_VEHICLES_QUERY = """
query LocateVehiclesByZip(
  $zipCode: String!,
  $brand: String!,
  $pageNo: Int!,
  $pageSize: Int!,
  $seriesCodes: String!,
  $distance: Int!,
  $leadid: String!,
  $interiorMedia: Boolean!
) {
  locateVehiclesByZip(
    zipCode: $zipCode,
    brand: $brand,
    pageNo: $pageNo,
    pageSize: $pageSize,
    seriesCodes: $seriesCodes,
    distance: $distance,
    leadid: $leadid,
    interiorMedia: $interiorMedia
  ) {
    pagination {
      pageNo
      pageSize
      totalPages
      totalRecords
    }
    vehicleSummary {
      vin
      stockNum
      brand
      marketingSeries
      grade
      dealerTrim
      year
      dealerCd
      dealerCategory
      inventoryStatus
      distributorCd
      isPreSold
      dealerMarketingName
      dealerWebsite
      vdpUrl
      isSmartPath
      distance
      isUnlockPriceDealer
      inventoryMileage
      transmission { transmissionType }
      price {
        advertizedPrice
        nonSpAdvertizedPrice
        totalMsrp
        sellingPrice
        dph
        dioTotalMsrp
        dioTotalDealerSellingPrice
        dealerCashApplied
        baseMsrp
      }
      options {
        optionCd
        marketingName
        marketingLongName
        optionType
        packageInd
      }
      mpg { city highway combined }
      model { modelCd marketingName marketingTitle }
      jelly { type href imageTag source }
      intColor { colorCd colorSwatch marketingName nvsName colorFamilies }
      extColor { colorCd colorSwatch marketingName colorHexCd nvsName colorFamilies }
      engine { engineCd name fuelType }
      fuelType { code name }
      drivetrain { code title bulletlist }
      family
      cab { code title bulletlist }
      bed { code title bulletlist }
      media { type size imageTag href source }
    }
  }
}
""".strip()


GET_MODELS_QUERY = """
query getModels(
  $zipCd: String!,
  $brand: String!,
  $imageProps: ImageProps!,
  $modelCode: [String!]
) {
  models(
    zipCd: $zipCd,
    brand: $brand,
    imageProps: $imageProps,
    modelCode: $modelCode
  ) {
    asShownDisclaimer
    asShown
    families {
      seqNo
      familyType
    }
    image
    modelCode
    msrp
    series
    title
    year
    mpgDisclaimerCode
    mpgeDisclaimerCode
    msrpDisclaimerCode
    topLabel {
      textField
    }
  }
}
""".strip()


@dataclass
class ToyotaModel:
    model_code: str
    series: str
    title: str
    year: str
    msrp: Optional[str] = None
    image: Optional[str] = None
    as_shown: Optional[str] = None
    top_label: Optional[str] = None


@dataclass
class ToyotaClientConfig:
    user_agent: str
    referer: str
    origin: str
    x_aws_waf_token: str
    x_api_key: str = "undefined"
    page_delay_sec: float = 0.5
    max_retries: int = 5
    retry_backoff_sec: float = 1.0
    waf_token_refresh: Optional[Callable[[], str]] = None
    max_waf_refreshes_per_request: int = 1
    waf_refresh_cooldown_sec: float = 30.0
    waf_post_refresh_delay_sec: float = 3.0
    rate_limit_backoff_sec: float = 20.0


@dataclass
class PageFetchProgress:
    page_no: int
    total_pages: int
    vehicles: List[Dict]
    raw_page: Dict

    @property
    def vehicle_count(self) -> int:
        return len(self.vehicles)


PageProgressCallback = Callable[["PageFetchProgress"], None]


@dataclass
class FetchResult:
    raw_pages: List[Dict]
    vehicles: List[Dict]
    total_pages: int
    last_page_fetched: int
    fetch_error: Optional[str] = None
    fetch_warnings: List[str] = field(default_factory=list)

    @property
    def partial(self) -> bool:
        return self.fetch_error is not None


def _truncate_json(value: object, limit: int = 1200) -> str:
    text = json.dumps(value, separators=(",", ":"), ensure_ascii=True)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... (truncated, {len(text)} chars total)"


def _describe_locate_failure(payload: Dict, page_no: int) -> str:
    data = payload.get("data")
    if not isinstance(data, dict):
        return f"page {page_no}: missing `data` object"

    locate = data.get("locateVehiclesByZip")
    if locate is None and "locateVehiclesByZip" in data:
        return (
            f"page {page_no}: `locateVehiclesByZip` is null "
            "(often rate limiting or WAF token fatigue after many requests)"
        )
    if locate is None:
        return f"page {page_no}: `locateVehiclesByZip` missing from response"

    data_keys = ", ".join(sorted(data.keys())) if data else "<empty>"
    return (
        f"page {page_no}: unrecognized vehicle payload under `data` "
        f"(keys: {data_keys})"
    )


def _log_fetch_failure(
    page_no: int,
    attempt: int,
    max_retries: int,
    exc: Exception,
    payload: Optional[Dict] = None,
    response: Optional[requests.Response] = None,
) -> None:
    print(
        f"[fetch] page {page_no} attempt {attempt}/{max_retries} failed: {exc}",
        flush=True,
    )
    if response is not None:
        print(
            f"[fetch] page {page_no} http_status={response.status_code} "
            f"content_type={response.headers.get('Content-Type', '')}",
            flush=True,
        )
        for header_name in ("x-amzn-requestid", "x-amzn-errortype", "x-cache", "via"):
            header_value = response.headers.get(header_name)
            if header_value:
                print(f"[fetch] page {page_no} header {header_name}={header_value}", flush=True)
    if payload is not None:
        if payload.get("errors"):
            print(
                f"[fetch] page {page_no} graphql_errors={_truncate_json(payload['errors'])}",
                flush=True,
            )
        if payload.get("extensions"):
            print(
                f"[fetch] page {page_no} extensions={_truncate_json(payload['extensions'])}",
                flush=True,
            )
        data = payload.get("data")
        if isinstance(data, dict):
            locate = data.get("locateVehiclesByZip")
            print(
                f"[fetch] page {page_no} locateVehiclesByZip_type={type(locate).__name__}",
                flush=True,
            )
        print(
            f"[fetch] page {page_no} response_snippet={_truncate_json(payload)}",
            flush=True,
        )


class PageFetchError(RuntimeError):
    def __init__(
        self,
        message: str,
        payload: Optional[Dict] = None,
        response: Optional[requests.Response] = None,
    ):
        super().__init__(message)
        self.payload = payload
        self.response = response


class ToyotaInventoryClient:
    def __init__(self, config: ToyotaClientConfig):
        self.config = config
        self.session = requests.Session()
        self._last_waf_refresh_at = 0.0

    def update_waf_token(self, token: str) -> None:
        self.config.x_aws_waf_token = token

    def _parse_json_payload(self, response: requests.Response) -> Dict:
        text = response.text or ""
        if not text.strip():
            raise RuntimeError(
                f"Toyota API returned an empty response (HTTP {response.status_code}). "
                "This usually means the WAF token expired or was blocked."
            )
        try:
            payload = response.json()
        except requests.exceptions.JSONDecodeError as exc:
            snippet = text[:240].replace("\n", " ").strip()
            content_type = response.headers.get("Content-Type", "")
            raise RuntimeError(
                f"Toyota API returned non-JSON (HTTP {response.status_code}, "
                f"Content-Type: {content_type!r}): {snippet!r}"
            ) from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Toyota API returned unexpected JSON payload.")
        return payload

    def _retry_backoff_sec(self, status_code: Optional[int], attempt: int) -> float:
        base = (
            self.config.rate_limit_backoff_sec
            if status_code in {403, 429}
            else self.config.retry_backoff_sec
        )
        return base * (2 ** (attempt - 1))

    def _needs_waf_refresh(self, response: Optional[requests.Response]) -> bool:
        if response is None:
            return False
        if response.status_code == 403:
            return True
        if response.status_code == 200:
            text = (response.text or "").lstrip()
            if not text:
                return True
            return not text.startswith("{") and not text.startswith("[")
        return False

    def _non_json_response_error(self, response: requests.Response) -> RuntimeError:
        text = response.text or ""
        snippet = text[:240].replace("\n", " ").strip()
        content_type = response.headers.get("Content-Type", "")
        if not text.strip():
            message = (
                f"Toyota API returned an empty response (HTTP {response.status_code}). "
                "The WAF token may be missing, expired, or blocked."
            )
        else:
            message = (
                f"Toyota API returned non-JSON (HTTP {response.status_code}, "
                f"Content-Type: {content_type!r}): {snippet!r}"
            )
        return RuntimeError(message)

    def _try_refresh_waf_token(
        self,
        response: Optional[requests.Response],
        refreshes_so_far: int,
    ) -> bool:
        if not self._needs_waf_refresh(response):
            return False
        refresher = self.config.waf_token_refresh
        if not refresher:
            return False
        if refreshes_so_far >= self.config.max_waf_refreshes_per_request:
            return False

        now = time.monotonic()
        if self._last_waf_refresh_at > 0:
            elapsed = now - self._last_waf_refresh_at
            cooldown = self.config.waf_refresh_cooldown_sec
            if elapsed < cooldown:
                wait_sec = cooldown - elapsed
                print(
                    f"[fetch] WAF refresh cooldown ({wait_sec:.1f}s remaining); "
                    "likely rate limited rather than expired token",
                    flush=True,
                )
                time.sleep(wait_sec)

        print("[fetch] WAF challenge detected; fetching fresh WAF token via Playwright...", flush=True)
        new_token = refresher()
        if not new_token:
            return False
        self.update_waf_token(new_token)
        self._last_waf_refresh_at = time.monotonic()
        if self.config.waf_post_refresh_delay_sec > 0:
            print(
                f"[fetch] waiting {self.config.waf_post_refresh_delay_sec:.1f}s "
                "after WAF refresh before retrying",
                flush=True,
            )
            time.sleep(self.config.waf_post_refresh_delay_sec)
        return True

    def _post_graphql(
        self,
        headers: Dict[str, str],
        body: Dict,
        timeout_sec: int = 45,
    ) -> requests.Response:
        payload = json.dumps(body, separators=(",", ":"))
        max_retries = max(1, self.config.max_retries)
        attempt = 0
        waf_refreshes = 0
        last_response: Optional[requests.Response] = None

        while attempt < max_retries:
            attempt += 1
            response = self.session.post(
                GRAPHQL_ENDPOINT,
                headers=headers,
                data=payload,
                timeout=timeout_sec,
            )
            last_response = response
            if self._needs_waf_refresh(response) and self._try_refresh_waf_token(response, waf_refreshes):
                waf_refreshes += 1
                attempt -= 1
                headers = {**headers, "X-Aws-Waf-Token": self.config.x_aws_waf_token}
                continue
            if response.status_code in {403, 408, 425, 429, 500, 502, 503, 504} and attempt < max_retries:
                sleep_sec = self._retry_backoff_sec(response.status_code, attempt)
                reason = "rate limit" if response.status_code in {403, 429} else "transient error"
                print(
                    f"[fetch] GraphQL HTTP {response.status_code} ({reason}); "
                    f"retrying in {sleep_sec:.1f}s (attempt {attempt + 1}/{max_retries})",
                    flush=True,
                )
                time.sleep(sleep_sec)
                continue
            if self._needs_waf_refresh(response):
                raise self._non_json_response_error(response)
            response.raise_for_status()
            return response

        assert last_response is not None
        if self._needs_waf_refresh(last_response):
            raise self._non_json_response_error(last_response)
        last_response.raise_for_status()
        return last_response

    def _headers(self, zip_code: str, series_code: str) -> Dict[str, str]:
        return {
            "User-Agent": self.config.user_agent,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": self.config.referer,
            "x-api-key": self.config.x_api_key,
            "x-cache-key": f"models-{zip_code}-{series_code}",
            "Content-Type": "application/json",
            "X-Aws-Waf-Token": self.config.x_aws_waf_token,
            "Origin": self.config.origin,
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
        }

    def _models_headers(self, zip_code: str) -> Dict[str, str]:
        return {
            "User-Agent": self.config.user_agent,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Referer": self.config.referer,
            "x-api-key": self.config.x_api_key,
            "x-cache-key": f"models-{zip_code}-",
            "Content-Type": "application/json",
            "X-Aws-Waf-Token": self.config.x_aws_waf_token,
            "Origin": self.config.origin,
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "Priority": "u=4",
            "TE": "trailers",
        }

    def fetch_models(
        self,
        zip_code: str,
        brand: str = "T",
        model_codes: Optional[List[str]] = None,
        timeout_sec: int = 45,
    ) -> List[ToyotaModel]:
        variables = {
            "zipCd": zip_code,
            "brand": brand,
            "imageProps": {"wid": "690", "hei": "290"},
            "modelCode": model_codes or [],
        }
        body = {
            "query": GET_MODELS_QUERY,
            "variables": variables,
            "operationName": "getModels",
        }
        response = self._post_graphql(
            headers=self._models_headers(zip_code),
            body=body,
            timeout_sec=timeout_sec,
        )
        payload = self._parse_json_payload(response)
        if payload.get("errors"):
            raise RuntimeError(f"GraphQL errors: {payload['errors']}")

        models = payload.get("data", {}).get("models")
        if not isinstance(models, list):
            raise RuntimeError("Unexpected GraphQL payload: missing `data.models` array")

        results: List[ToyotaModel] = []
        for item in models:
            if not isinstance(item, dict):
                continue
            model_code = item.get("modelCode")
            if not model_code:
                continue
            top_label = item.get("topLabel") or {}
            results.append(
                ToyotaModel(
                    model_code=model_code,
                    series=item.get("series") or model_code,
                    title=item.get("title") or model_code,
                    year=str(item.get("year") or ""),
                    msrp=item.get("msrp"),
                    image=item.get("image"),
                    as_shown=item.get("asShown"),
                    top_label=top_label.get("textField") if isinstance(top_label, dict) else None,
                )
            )
        return results

    def fetch_page(
        self,
        zip_code: str,
        distance: int,
        page_no: int,
        page_size: int,
        series_code: str,
        brand: str = "TOYOTA",
        lead_id: Optional[str] = None,
        interior_media: bool = True,
        timeout_sec: int = 45,
    ) -> Tuple[Dict, requests.Response]:
        if not lead_id:
            lead_id = str(uuid4())
        variables = {
            "zipCode": zip_code,
            "brand": brand,
            "pageNo": page_no,
            "pageSize": page_size,
            "seriesCodes": series_code,
            "distance": distance,
            "leadid": lead_id,
            "interiorMedia": interior_media,
        }
        body = {"query": LOCATE_VEHICLES_QUERY, "variables": variables}
        response = self._post_graphql(
            headers=self._headers(zip_code, series_code),
            body=body,
            timeout_sec=timeout_sec,
        )
        payload = self._parse_json_payload(response)
        if payload.get("errors"):
            raise RuntimeError(f"GraphQL errors: {payload['errors']}")
        return payload, response

    def _extract_page_data(self, payload: Dict, page_no: int) -> Tuple[List[Dict], int]:
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError(
                f"Unexpected GraphQL payload on page {page_no}: missing `data` object."
            )

        locate = data.get("locateVehiclesByZip")
        if isinstance(locate, dict):
            page_vehicles = locate.get("vehicleSummary") or []
            pagination = locate.get("pagination")
            if not isinstance(pagination, dict):
                raise RuntimeError(
                    f"Unexpected GraphQL payload on page {page_no}: missing pagination."
                )
            page_total_pages = int(pagination.get("totalPages") or 1)
            return page_vehicles, page_total_pages

        vin_keyed_vehicles = [
            value for value in data.values() if isinstance(value, dict) and value.get("vin")
        ]
        if vin_keyed_vehicles:
            return vin_keyed_vehicles, 1

        raise RuntimeError(_describe_locate_failure(payload, page_no))

    def _fetch_and_extract_page(
        self,
        zip_code: str,
        distance: int,
        page_no: int,
        page_size: int,
        series_code: str,
        brand: str,
        lead_id: Optional[str],
        interior_media: bool,
        warnings: List[str],
    ) -> Tuple[Dict, List[Dict], int]:
        max_retries = max(1, self.config.max_retries)
        last_exc: Optional[Exception] = None
        last_payload: Optional[Dict] = None
        last_response: Optional[requests.Response] = None
        payload: Optional[Dict] = None
        response: Optional[requests.Response] = None
        retryable = False

        attempt = 0
        while attempt < max_retries:
            attempt += 1
            try:
                payload, response = self.fetch_page(
                    zip_code=zip_code,
                    distance=distance,
                    page_no=page_no,
                    page_size=page_size,
                    series_code=series_code,
                    brand=brand,
                    lead_id=lead_id,
                    interior_media=interior_media,
                )
                page_vehicles, page_total_pages = self._extract_page_data(payload, page_no)
                if attempt > 1:
                    warning = f"page {page_no} recovered on attempt {attempt}/{max_retries}"
                    warnings.append(warning)
                    print(f"[fetch] {warning}", flush=True)
                return payload, page_vehicles, page_total_pages
            except requests.HTTPError as exc:
                last_exc = exc
                last_payload = payload
                last_response = exc.response or response
                retryable = last_response is not None and last_response.status_code in {
                    403,
                    408,
                    425,
                    429,
                    500,
                    502,
                    503,
                    504,
                }
            except (RuntimeError, requests.RequestException) as exc:
                last_exc = exc
                last_payload = payload
                last_response = response
                retryable = True

            if attempt >= max_retries or not retryable:
                break

            sleep_sec = self._retry_backoff_sec(
                last_response.status_code if last_response is not None else None,
                attempt,
            )
            _log_fetch_failure(
                page_no=page_no,
                attempt=attempt,
                max_retries=max_retries,
                exc=last_exc,
                payload=last_payload,
                response=last_response,
            )
            print(
                f"[fetch] page {page_no} retrying in {sleep_sec:.1f}s "
                f"(attempt {attempt + 1}/{max_retries})",
                flush=True,
            )
            time.sleep(sleep_sec)

        assert last_exc is not None
        _log_fetch_failure(
            page_no=page_no,
            attempt=max_retries,
            max_retries=max_retries,
            exc=last_exc,
            payload=last_payload,
            response=last_response,
        )
        raise PageFetchError(str(last_exc), payload=last_payload, response=last_response) from last_exc

    def fetch_all_pages(
        self,
        zip_code: str,
        distance: int,
        page_size: int,
        series_code: str,
        brand: str = "TOYOTA",
        lead_id: Optional[str] = None,
        interior_media: bool = True,
        progress_callback: Optional[PageProgressCallback] = None,
    ) -> FetchResult:
        raw_pages: List[Dict] = []
        vehicles: List[Dict] = []
        total_pages = 1
        last_page_fetched = 0
        fetch_warnings: List[str] = []

        def finish(fetch_error: Optional[str] = None) -> FetchResult:
            return FetchResult(
                raw_pages=raw_pages,
                vehicles=vehicles,
                total_pages=total_pages,
                last_page_fetched=last_page_fetched,
                fetch_error=fetch_error,
                fetch_warnings=fetch_warnings,
            )

        try:
            page, first_page_vehicles, total_pages = self._fetch_and_extract_page(
                zip_code=zip_code,
                distance=distance,
                page_no=1,
                page_size=page_size,
                series_code=series_code,
                brand=brand,
                lead_id=lead_id,
                interior_media=interior_media,
                warnings=fetch_warnings,
            )
            raw_pages.append(page)
            vehicles.extend(first_page_vehicles)
            last_page_fetched = 1
            if progress_callback:
                progress_callback(
                    PageFetchProgress(
                        page_no=1,
                        total_pages=total_pages,
                        vehicles=first_page_vehicles,
                        raw_page=page,
                    )
                )
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch page 1: {exc}") from exc

        for page_no in range(2, total_pages + 1):
            if self.config.page_delay_sec > 0:
                time.sleep(self.config.page_delay_sec)
            try:
                page, page_vehicles, _ = self._fetch_and_extract_page(
                    zip_code=zip_code,
                    distance=distance,
                    page_no=page_no,
                    page_size=page_size,
                    series_code=series_code,
                    brand=brand,
                    lead_id=lead_id,
                    interior_media=interior_media,
                    warnings=fetch_warnings,
                )
                raw_pages.append(page)
                vehicles.extend(page_vehicles)
                last_page_fetched = page_no
                if progress_callback:
                    progress_callback(
                        PageFetchProgress(
                            page_no=page_no,
                            total_pages=total_pages,
                            vehicles=page_vehicles,
                            raw_page=page,
                        )
                    )
            except PageFetchError as exc:
                if exc.payload is not None:
                    raw_pages.append(exc.payload)
                return finish(f"page {page_no} failed after retries: {exc}")
            except Exception as exc:
                return finish(f"page {page_no} failed after retries: {exc}")

        return finish()
