"""Mazda USA REST inventory client (from HAR analysis)."""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

from vehicle_inventory.makes.mazda.session import DEFAULT_USER_AGENT, MAZDA_INVENTORY_URL, resolve_mazda_cookies
from vehicle_inventory.makes.mazda.colors import is_interior_swatch_url, resolve_exterior_color_hex
from vehicle_inventory.makes.mazda.media import classify_mazda_media, normalize_mazda_media_href
from vehicle_inventory.makes.mazda.models import compose_mazda_model_marketing_name
from vehicle_inventory.makes.mazda.stage import resolve_mazda_allocation_stage

MAZDA_ORIGIN = "https://www.mazdausa.com"
MAZDA_INVENTORY_RESULTS_URL = f"{MAZDA_ORIGIN}/shopping-tools/inventory/results"
DEALER_AJAX = f"{MAZDA_ORIGIN}/handlers/dealer.ajax"
ZIP_AJAX = f"{MAZDA_ORIGIN}/handlers/zip.ajax"
INVENTORY_SEARCH = f"{MAZDA_ORIGIN}/api/inventorysearch"
VEHICLE_DETAIL = f"{MAZDA_ORIGIN}/api/inv/detail"


def compose_mazda_listing_url(*, details_url: str = "", vin: str = "") -> str:
    """Build a shopper-facing Mazda inventory listing URL."""
    path = str(details_url or "").strip()
    if path:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if path.startswith("/"):
            return f"{MAZDA_ORIGIN}{path}"
        return f"{MAZDA_ORIGIN}/{path}"
    vin_value = str(vin or "").strip().upper()
    if vin_value:
        query = urllib.parse.urlencode({"vin": vin_value})
        return f"{MAZDA_INVENTORY_RESULTS_URL}?{query}"
    return ""


@dataclass
class MazdaCatalogModel:
    model_code: str
    title: str
    series: str
    year: str = ""
    image: Optional[str] = None
    inventory_count: Optional[int] = None


@dataclass
class MazdaDealer:
    dealer_id: int
    name: str
    city: str
    state: str
    zip_code: str
    distance_mi: float
    lat: float
    lon: float
    web_url: str = ""


@dataclass
class MazdaVehicle:
    vin: str
    carline: str
    price: Optional[float]
    base_msrp: Optional[float]
    year: Optional[int]
    model_name: str
    exterior_color: str
    interior_color: str
    dealer_id: Optional[int]
    details_url: str
    image_url: str
    vehicle_location: str = ""
    status_code: str = ""
    eta_date: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MazdaClientConfig:
    user_agent: str = DEFAULT_USER_AGENT
    referer: str = MAZDA_INVENTORY_URL
    page_size: int = 100
    cookies: Optional[Dict[str, str]] = None


class MazdaInventoryClient:
    def __init__(self, config: Optional[MazdaClientConfig] = None) -> None:
        self.config = config or MazdaClientConfig()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.config.user_agent,
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "en-US,en;q=0.9",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": MAZDA_ORIGIN,
                "Referer": self.config.referer,
            }
        )
        cookies = self.config.cookies or resolve_mazda_cookies()
        for name, value in cookies.items():
            self.session.cookies.set(name, value, domain="www.mazdausa.com")

    def validate_zip(self, zip_code: str) -> bool:
        response = self.session.get(
            ZIP_AJAX,
            params={"zip": zip_code},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        return str(payload.get("success", "")).lower() == "true"

    def fetch_dealers(self, zip_code: str, *, max_distance: int = 50) -> List[MazdaDealer]:
        """Resolve nearby dealers via ``dealer.ajax`` before inventory search."""
        dealers: List[MazdaDealer] = []
        seen_ids: set[int] = set()
        page = 1
        expected_total: Optional[int] = None

        while True:
            response = self.session.get(
                DEALER_AJAX,
                params={"zip": zip_code, "maxDistance": max_distance, "p": page, "accolades": ""},
                timeout=45,
            )
            response.raise_for_status()
            payload = response.json()
            body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
            if expected_total is None:
                try:
                    expected_total = int(body.get("total") or 0)
                except (TypeError, ValueError):
                    expected_total = 0

            rows = body.get("results") or []
            if not rows:
                break

            for row in rows:
                if not isinstance(row, dict):
                    continue
                dealer_id = row.get("id")
                if dealer_id is None:
                    continue
                dealer_id_int = int(dealer_id)
                if dealer_id_int in seen_ids:
                    continue
                seen_ids.add(dealer_id_int)
                dealers.append(
                    MazdaDealer(
                        dealer_id=dealer_id_int,
                        name=str(row.get("name") or dealer_id),
                        city=str(row.get("city") or ""),
                        state=str(row.get("state") or ""),
                        zip_code=str(row.get("zip") or ""),
                        distance_mi=float(row.get("driveDistMi") or 0.0),
                        lat=float(row.get("lat") or 0.0),
                        lon=float(row.get("long") or 0.0),
                        web_url=str(row.get("webUrl") or "").strip(),
                    )
                )

            if expected_total and len(dealers) >= expected_total:
                break
            page += 1
            if page > 100:
                break

        return dealers

    @staticmethod
    def dealer_row_to_payload(row: Dict[str, Any]) -> Dict[str, Any]:
        dealer_id = row.get("id")
        if dealer_id is None:
            raise ValueError("Dealer row missing id")
        name = str(row.get("name") or "").strip()
        return {
            "dealerCd": str(dealer_id),
            "dealerMarketingName": name or str(dealer_id),
            "dealerWebsite": str(row.get("webUrl") or "").strip() or None,
        }

    def fetch_dealer_by_id(self, dealer_id: int) -> Dict[str, Any]:
        response = self.session.get(
            DEALER_AJAX,
            params={"dealerId": int(dealer_id)},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        header = payload.get("header") or {}
        if str(header.get("status", "")).lower() not in {"", "success"}:
            message = header.get("errorMessage") or header.get("status") or "unknown error"
            raise RuntimeError(f"Mazda dealer API failed for {dealer_id}: {message}")
        rows = payload.get("body", {}).get("results") or []
        if not rows or not isinstance(rows[0], dict):
            raise RuntimeError(f"Mazda dealer {dealer_id} not found")
        return self.dealer_row_to_payload(rows[0])

    @staticmethod
    def results_start_for_page(page_no: int) -> int:
        """Mazda paginates by page number (1, 2, 3...), not row offset."""
        return max(1, int(page_no))

    @staticmethod
    def near_results_start_for_page(page_no: int) -> str:
        """First page sends NearResultsStart=1; later pages send an empty value."""
        return "1" if page_no <= 1 else ""

    def search_inventory(
        self,
        dealer_ids: List[int],
        *,
        results_start: int = 1,
        page_size: Optional[int] = None,
        carlines: Optional[List[str]] = None,
        model_codes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if not dealer_ids:
            raise ValueError("At least one dealer id is required for Mazda inventory search.")
        page_size = page_size or self.config.page_size
        form: List[tuple[str, str]] = [
            ("ResultsPageSize", str(page_size)),
            ("ResultsStart", str(results_start)),
            ("NearResultsStart", self.near_results_start_for_page(results_start)),
            ("Vehicle[DealerId][]", ",".join(str(dealer_id) for dealer_id in dealer_ids)),
            ("Vehicle[Type][]", "n"),
            ("Vehicle[cond][]", "n"),
            ("Vehicle[sortTitle][]", "Distance: Near to Far"),
            ("GetNearMatch", "false"),
            ("IsIntransitDisplay", "true"),
            ("IsEVMarket", "true"),
            ("resultsSortParameter[0][resultsSortAttribute]", "DEALERID"),
            ("resultsSortParameter[0][resultsSortOrder]", "asc"),
            ("resultsSortParameter[1][resultsSortAttribute]", "price"),
            ("resultsSortParameter[1][resultsSortOrder]", "asc"),
            ("resultsSortParameter[2][resultsSortAttribute]", "Year"),
            ("resultsSortParameter[2][resultsSortOrder]", "desc"),
            ("resultsSortParameter[3][resultsSortAttribute]", "Mileage"),
            ("resultsSortParameter[3][resultsSortOrder]", "asc"),
            ("sortVal", "DEALERID|asc,price|asc,Year|desc,Mileage|asc"),
            ("sortTitle", "Distance: Near to Far"),
        ]
        if carlines:
            for code in carlines:
                cleaned = str(code or "").strip()
                if cleaned:
                    form.append(("Vehicle[Carline][]", cleaned))
        for code in model_codes or []:
            form.append(("Vehicle[ModelCode][]", code))

        body = urllib.parse.urlencode(form)
        response = self.session.post(
            INVENTORY_SEARCH,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _year_from_image_url(url: str) -> str:
        match = re.search(r"/vehicles/(20\d{2})/", str(url or ""))
        return match.group(1) if match else ""

    @staticmethod
    def parse_catalog_models(payload: Dict[str, Any]) -> List[MazdaCatalogModel]:
        filters = payload.get("response", {}).get("Filters") if isinstance(payload.get("response"), dict) else {}
        rows = filters.get("Models") if isinstance(filters, dict) else []
        models: List[MazdaCatalogModel] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            code = str(row.get("Code") or "").strip()
            if not code:
                continue
            title = str(row.get("Name") or code).strip()
            image = str(row.get("Image") or "").strip() or None
            if image:
                if image.startswith("/"):
                    image = f"{MAZDA_ORIGIN}{image}"
                image = re.sub(
                    r"^(https://www\.mazdausa\.com):443",
                    r"\1",
                    image,
                    flags=re.IGNORECASE,
                )
            count_raw = row.get("Count")
            try:
                inventory_count = int(count_raw) if count_raw is not None else None
            except (TypeError, ValueError):
                inventory_count = None
            models.append(
                MazdaCatalogModel(
                    model_code=code,
                    title=title,
                    series=code,
                    year=MazdaInventoryClient._year_from_image_url(image or ""),
                    image=image,
                    inventory_count=inventory_count,
                )
            )
        return models

    def fetch_model_catalog(self, dealer_ids: List[int]) -> List[MazdaCatalogModel]:
        payload = self.search_inventory(dealer_ids, results_start=1, page_size=1)
        return self.parse_catalog_models(payload)

    def parse_vehicles(self, payload: Dict[str, Any]) -> List[MazdaVehicle]:
        rows = payload.get("response", {}).get("Vehicles") or []
        vehicles: List[MazdaVehicle] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            vin = str(row.get("Vin") or row.get("VIN") or "").strip()
            if not vin:
                continue
            colors = row.get("Colors") if isinstance(row.get("Colors"), dict) else {}
            images = row.get("ImagesListInfo") or []
            image_url = ""
            if images and isinstance(images[0], dict):
                image_url = str(images[0].get("Url") or "")
            price_raw = row.get("Price") or row.get("BaseMsrp")
            try:
                price = float(price_raw) if price_raw is not None else None
            except (TypeError, ValueError):
                price = None
            base_msrp = row.get("BaseMsrp")
            try:
                msrp = float(base_msrp) if base_msrp is not None else price
            except (TypeError, ValueError):
                msrp = price
            year = None
            details_url = str(row.get("DetailsPageURL") or "")
            year_match = re.search(r"(?<![0-9])(20\d{2})(?![0-9])", details_url)
            if year_match:
                year = int(year_match.group(1))
            else:
                for token in details_url.split("/"):
                    if token.isdigit() and len(token) == 4:
                        year = int(token)
                        break
            vehicles.append(
                MazdaVehicle(
                    vin=vin,
                    carline=str(row.get("Carline") or ""),
                    price=price,
                    base_msrp=msrp,
                    year=year,
                    model_name=str(row.get("ModelName") or row.get("Carline") or row.get("CarlineName") or ""),
                    exterior_color=str(colors.get("ExteriorDescription") or ""),
                    interior_color=str(colors.get("InteriorDescription") or ""),
                    dealer_id=int(row["DealerId"]) if row.get("DealerId") is not None else None,
                    details_url=details_url,
                    image_url=image_url,
                    vehicle_location=str(row.get("VehicleLocation") or "").strip(),
                    status_code=str(row.get("Status") or "").strip(),
                    eta_date=str(row.get("ETADate") or "").strip() or None,
                    raw=row,
                )
            )
        return vehicles

    def total_vehicle_count(self, payload: Dict[str, Any]) -> int:
        try:
            return int(payload.get("response", {}).get("TotalVehicles") or 0)
        except (TypeError, ValueError):
            return 0

    def fetch_vehicle_detail(self, vin: str, *, referer: Optional[str] = None) -> Dict[str, Any]:
        vin = str(vin or "").strip()
        if not vin:
            raise ValueError("VIN is required for Mazda vehicle detail lookup.")
        headers = {"Accept": "*/*"}
        if referer:
            headers["Referer"] = referer
        response = self.session.get(
            VEHICLE_DETAIL,
            params={"vin": vin},
            headers=headers,
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
        header = payload.get("header") or {}
        if str(header.get("status", "")).lower() != "success":
            message = header.get("errorMessage") or header.get("status") or "unknown error"
            raise RuntimeError(f"Mazda detail API failed for {vin}: {message}")
        return payload

    @staticmethod
    def detail_vehicle(detail: Dict[str, Any]) -> Dict[str, Any]:
        body = detail.get("body") if isinstance(detail.get("body"), dict) else {}
        vehicle = body.get("vehicle")
        return vehicle if isinstance(vehicle, dict) else {}

    @staticmethod
    def parse_detail_options(detail: Dict[str, Any]) -> List[Dict[str, Any]]:
        vehicle = MazdaInventoryClient.detail_vehicle(detail)
        options: List[Dict[str, Any]] = []
        seen: set[str] = set()

        def add_option(
            code: object,
            name: object,
            *,
            option_type: str,
            package_ind: bool,
            long_name: object = None,
            price: object = None,
        ) -> None:
            option_cd = str(code or "").strip()
            if not option_cd or option_cd in seen:
                return
            seen.add(option_cd)
            marketing_name = str(name or option_cd).strip()
            marketing_long_name = str(long_name or marketing_name).strip()
            if price is not None:
                try:
                    price_value = float(price)
                except (TypeError, ValueError):
                    price_value = None
                if price_value:
                    marketing_long_name = f"{marketing_long_name} (${price_value:,.0f})"
            options.append(
                {
                    "optionCd": option_cd,
                    "marketingName": marketing_name,
                    "marketingLongName": marketing_long_name,
                    "optionType": option_type,
                    "packageInd": package_ind,
                }
            )

        for accessory in vehicle.get("accessories") or []:
            if not isinstance(accessory, dict):
                continue
            add_option(
                accessory.get("code"),
                accessory.get("name"),
                option_type="accessory",
                package_ind=False,
                long_name=accessory.get("description"),
                price=accessory.get("price"),
            )

        for package in vehicle.get("packages") or []:
            if not isinstance(package, dict):
                continue
            add_option(
                package.get("code"),
                package.get("name"),
                option_type="package",
                package_ind=True,
                long_name=package.get("description"),
                price=package.get("price"),
            )
            nested_options = package.get("options")
            if isinstance(nested_options, list):
                for nested in nested_options:
                    if not isinstance(nested, dict):
                        continue
                    add_option(
                        nested.get("code"),
                        nested.get("name"),
                        option_type="package_option",
                        package_ind=False,
                        long_name=nested.get("description"),
                        price=nested.get("price"),
                    )

        return options

    @staticmethod
    def enrich_vehicle_payload(base: Dict[str, Any], detail: Dict[str, Any]) -> Dict[str, Any]:
        vehicle = MazdaInventoryClient.detail_vehicle(detail)
        if not vehicle:
            return dict(base)

        enriched = dict(base)
        model = dict(enriched.get("model") or {})
        ext = dict(enriched.get("extColor") or {})
        intr = dict(enriched.get("intColor") or {})
        price = dict(enriched.get("price") or {})

        enriched["marketingSeries"] = vehicle.get("carlineName") or enriched.get("marketingSeries")
        trim_name = vehicle.get("trimName") or enriched.get("grade")
        enriched["grade"] = trim_name
        enriched["dealerTrim"] = trim_name
        if vehicle.get("year"):
            enriched["year"] = vehicle.get("year")
        if vehicle.get("modelTitle"):
            model["marketingName"] = vehicle.get("modelTitle")
            model["marketingTitle"] = vehicle.get("modelTitle")
        if vehicle.get("vehicleCode"):
            model["modelCd"] = str(vehicle.get("vehicleCode")).strip()
        enriched["model"] = model

        if vehicle.get("transmission"):
            enriched["transmission"] = {"transmissionType": vehicle.get("transmission")}
        if vehicle.get("engine"):
            enriched["engine"] = {"name": vehicle.get("engine")}
        if vehicle.get("drivetrain"):
            enriched["drivetrain"] = {"title": vehicle.get("drivetrain")}

        engine_fuel = vehicle.get("engineFuelType")
        if isinstance(engine_fuel, dict):
            enriched["fuelType"] = {
                "code": engine_fuel.get("code"),
                "name": engine_fuel.get("title"),
            }

        ext_detail = vehicle.get("extColor")
        if isinstance(ext_detail, dict):
            ext["colorCd"] = ext_detail.get("code") or ext.get("colorCd")
            ext["marketingName"] = ext_detail.get("description") or ext.get("marketingName")

        ext_name = ext.get("marketingName") or ""
        ext_code = ext.get("colorCd") or ""
        ext_hex = resolve_exterior_color_hex(ext_name, ext_code)
        if ext_hex:
            ext["colorHexCd"] = ext_hex

        # images.colorSwatch is the *interior* swatch on Mazda detail responses.
        ext_swatch = vehicle.get("exteriorColorSwatch")
        if ext_swatch and not is_interior_swatch_url(ext_swatch):
            ext["colorSwatch"] = ext_swatch
        elif ext.get("colorSwatch") and is_interior_swatch_url(ext.get("colorSwatch")):
            ext.pop("colorSwatch", None)

        images = vehicle.get("images")
        if isinstance(images, dict):
            vehicle_images = images.get("vehicle") or []
            if vehicle_images and not enriched.get("media"):
                enriched["media"] = [
                    classify_mazda_media(
                        normalize_mazda_media_href(str(url)),
                        image_tag="vehicle",
                    )
                    for url in vehicle_images
                    if url
                ]
        enriched["extColor"] = ext

        int_detail = vehicle.get("intColor")
        if isinstance(int_detail, dict):
            intr["colorCd"] = int_detail.get("code") or intr.get("colorCd")
            intr["marketingName"] = int_detail.get("description") or intr.get("marketingName")
        int_swatch = vehicle.get("interiorColorSwatch")
        if not int_swatch and isinstance(images, dict):
            int_swatch = images.get("colorSwatch")
        if int_swatch:
            intr["colorSwatch"] = int_swatch
        enriched["intColor"] = intr

        if vehicle.get("dealerId") is not None:
            enriched["dealerCd"] = str(vehicle.get("dealerId"))
        if vehicle.get("dealerSiteUrl"):
            # dealerSiteUrl is the dealer's VIN listing page, not the dealer homepage.
            enriched["vdpUrl"] = vehicle.get("dealerSiteUrl")
        if vehicle.get("status"):
            enriched["inventoryStatus"] = vehicle.get("status")

        if vehicle.get("msrp") is not None:
            price["totalMsrp"] = vehicle.get("msrp")
            price["advertizedPrice"] = vehicle.get("msrp")
        if vehicle.get("baseMSRP") is not None:
            price["baseMsrp"] = vehicle.get("baseMSRP")
        if vehicle.get("destinationFee") is not None:
            price["dph"] = vehicle.get("destinationFee")
        enriched["price"] = price
        enriched["options"] = MazdaInventoryClient.parse_detail_options(detail)

        composed_model = compose_mazda_model_marketing_name(
            marketing_series=str(enriched.get("marketingSeries") or ""),
            model_marketing_name=str(model.get("marketingName") or ""),
            grade=str(enriched.get("grade") or ""),
        )
        if composed_model:
            model["marketingName"] = composed_model
            model["marketingTitle"] = composed_model
            enriched["model"] = model

        stage_code, _stage_label = resolve_mazda_allocation_stage(
            vehicle_location=enriched.get("vehicleLocation"),
            detail_location=vehicle.get("location"),
        )
        if stage_code:
            enriched["dealerCategory"] = stage_code
            enriched["vehicleLocation"] = stage_code

        return enriched

    @staticmethod
    def detail_referer(vehicle: MazdaVehicle) -> str:
        listing_url = compose_mazda_listing_url(
            details_url=vehicle.details_url,
            vin=vehicle.vin,
        )
        return listing_url or MAZDA_INVENTORY_URL
