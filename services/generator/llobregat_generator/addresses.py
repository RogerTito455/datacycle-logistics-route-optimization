"""Real postal addresses: download, parse, convert and assign to zones.

Barcelona: Open Data BCN `taula-direle`, every street number of the city with its district and
WGS84 coordinates, and `carrerer`, the street register that gives the street names.
The five neighbouring municipalities are not in taula-direle. Their addresses come from the ICGC
simplified address register of Catalonia (Adreces simplificat), which publishes coordinates in
ETRS89 UTM zone 31N; they are converted to WGS84 here.

All three are CC BY 4.0. Downloads are cached, so each file is fetched once. Only a complete
download is cached: an HTTP 200 answer with as many bytes as the server announced, and a file that
reads as what it should be (check_csv, check_icgc_zip). A cached file that fails the check is
downloaded again, so an error page or a cut-off download is never reused. A download that fails on
the way, from a refused connection to a timeout, raises DownloadError too, and caches nothing.
"""

from __future__ import annotations

import csv
import http.client
import io
import re
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from pyproj import Transformer

from llobregat_generator.zones import ZoneMap

USER_AGENT = (
    "llobregat-express-datacycle/1.0 "
    "(student project; https://github.com/RogerTito455/datacycle-logistics-route-optimization)"
)
HTTP_TIMEOUT_S = 120
# What urllib raises when the server or the network fails: no connection, a reset or a timeout, an
# answer cut off in the middle of a read, an HTTP error status (HTTPError is a URLError).
NETWORK_ERRORS = (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError)


class DownloadError(RuntimeError):
    """A download that failed, is not complete or is not the file it should be. It is not cached."""


@contextmanager
def download_errors(url: str) -> Iterator[None]:
    """Raise what urllib raises while downloading url as a DownloadError that says why."""
    try:
        yield
    except urllib.error.HTTPError as exc:
        raise DownloadError(f"{url} answered HTTP {exc.code} {exc.reason}") from exc
    except NETWORK_ERRORS as exc:
        reason = getattr(exc, "reason", None) or exc
        raise DownloadError(f"{url} could not be downloaded: {str(reason) or type(reason).__name__}") from exc


@dataclass(frozen=True)
class Download:
    source_id: str
    url: str
    filename: str
    columns: tuple[str, ...] = ()  # columns the header of the CSV must have


# CSV column (as published) -> bronze column.
TAULA_DIRELE_COLUMNS = {
    "codi_carrer": "street_code",
    "numpost": "street_number",
    "llepost": "number_letter",
    "tipusnum": "number_type",
    "districte": "district_code",
    "barri": "neighbourhood_code",
    "secc_est": "statistical_section",
    "secc_cens": "census_section",
    "dist_post": "postal_district",
    "x_ed50": "x_ed50",
    "y_ed50": "y_ed50",
    "x_etrs89": "x_etrs89",
    "y_etrs89": "y_etrs89",
    "longitud_wgs84": "lon",
    "latitud_wgs84": "lat",
}
CARRERER_COLUMNS = {
    "codi_via": "street_code",
    "codi_carrer_ine": "ine_street_code",
    "tipus_via": "street_type",
    "nom_curt": "short_name",
    "nom_oficial": "official_name",
    "nre_min": "number_min",
    "nre_max": "number_max",
}
ICGC_COLUMNS = {
    "idadrvia": "address_id",
    "codmuni": "municipality_code",
    "nommuni": "municipality",
    "idvia": "street_id",
    "tipvia": "street_type",
    "nexevia": "street_article",
    "nomvia": "street_name",
    "tipusadr": "address_type",
    "numini": "number_from",
    "comini": "number_from_suffix",
    "numfi": "number_to",
    "comfi": "number_to_suffix",
    "bloc": "block",
    "codpostal": "postcode",
    "coor_utmx": "x_etrs89",
    "coor_utmy": "y_etrs89",
}

TAULA_DIRELE = Download(
    "opendata-bcn/taula-direle",
    "https://opendata-ajuntament.barcelona.cat/data/dataset/6b5cfa7b-1d8d-45f0-990a-d1844d43ffd1"
    "/resource/50c9b17f-d297-4668-bad4-e1c217580747/download",
    "adreces_postals_elementals.csv",
    tuple(TAULA_DIRELE_COLUMNS),
)
CARRERER = Download(
    "opendata-bcn/carrerer",
    "https://opendata-ajuntament.barcelona.cat/data/dataset/d7802fd1-cdfb-4562-9148-d18722d7e2d8"
    "/resource/2b010e59-6952-4b27-9c4e-47fcaf64c916/download",
    "carrerer.csv",
    tuple(CARRERER_COLUMNS),
)
ICGC_SOURCE_ID = "icgc/adreces-simplificat"
ICGC_LISTING_URL = "https://datacloud.icgc.cat/datacloud/adreces-simplificat/csv/"
ICGC_ZIP_RE = re.compile(r'href="(?:[^"]*/)?(adreces-simplificat-[^"/]+\.zip)"', re.IGNORECASE)

# ETRS89 / UTM zone 31N to WGS84, longitude first.
_TO_WGS84 = Transformer.from_crs("EPSG:25831", "EPSG:4326", always_xy=True)


@dataclass(frozen=True)
class Address:
    """A delivery address the order generator can draw."""

    address_ref: str
    zone_id: str
    street_address: str
    postcode: str
    municipality: str
    lat: float
    lon: float


def check_csv(path: Path, columns: tuple[str, ...] = (), delimiter: str = ",") -> str | None:
    """Why the file is not a complete CSV with these header columns; None when it is.

    An error page has another header, an empty answer no data row, and a cut-off download a row
    with fewer fields than the header or an open quote at the end. The published files may end
    without a final newline, so every row is parsed rather than the last byte looked at.
    """
    rows = 0
    try:
        with path.open(encoding="utf-8", newline="") as f:
            reader = csv.reader(f, delimiter=delimiter, strict=True)
            header = next(reader, None)
            if header is None:
                return "the file is empty"
            missing = [c for c in columns if c not in header]
            if missing:
                return f"the header has no {', '.join(missing)} column"
            for row in reader:
                if not row:
                    continue
                if len(row) != len(header):
                    fields = f"line {reader.line_num} has {len(row)} fields, the header {len(header)}"
                    return f"{fields}: the file is cut off"
                rows += 1
    except (csv.Error, UnicodeDecodeError) as exc:
        return f"not a complete CSV file ({exc})"
    return None if rows else "no data rows"


def check_icgc_zip(path: Path, full: bool = False) -> str | None:
    """Why the file is not a complete ICGC address zip; None when it is.

    A cut-off zip has no central directory at its end and does not open. The municipality and street
    address files must be in it, the address file with the columns the loader reads. With full, the
    checksum of every member is verified too, which reads the whole archive (done once, on download).
    """
    try:
        with zipfile.ZipFile(path) as archive:
            for kind in ("municipi", "adrecavia"):
                _zip_member(archive, kind)
            with archive.open(_zip_member(archive, "adrecavia")) as raw:
                header = next(csv.reader(io.TextIOWrapper(raw, encoding="utf-8", newline=""), delimiter=";"), [])
            missing = [c for c in ICGC_COLUMNS if c not in header]
            if missing:
                return f"the address file has no {', '.join(missing)} column"
            if full and (bad := archive.testzip()) is not None:
                return f"{bad} is damaged"
    except (zipfile.BadZipFile, EOFError) as exc:
        return f"not a complete zip file ({exc})"
    except (RuntimeError, csv.Error, UnicodeDecodeError) as exc:  # _zip_member finds no such file
        return f"not the ICGC address zip ({exc})"
    return None


def fetch(url: str, target: Path, check: Callable[[Path], str | None]) -> Path:
    """Download url to target once; later calls reuse the cached file while it passes `check`.

    `check` returns why a file is not what the url should give, or None. A download is cached only
    when the server answered 200, sent as many bytes as its Content-Length announced and the file
    passes the check; otherwise, or when the connection fails or times out, nothing is cached and
    DownloadError says why. A cached file that fails the check, such as a cut-off file cached
    before this rule, is downloaded again.
    """
    if target.exists():
        problem = check(target)
        if problem is None:
            return target
        print(f"  cached {target} is not a complete download ({problem}); downloading it again")
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    print(f"  downloading {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with (
            download_errors(url),
            urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response,
            partial.open("wb") as out,
        ):
            if response.status != 200:
                raise DownloadError(f"{url} answered HTTP {response.status}, not 200")
            announced = response.headers.get("Content-Length")
            while chunk := response.read(1 << 20):
                out.write(chunk)
        received = partial.stat().st_size
        if announced is not None and received != int(announced):
            raise DownloadError(f"{url} sent {received} of the {announced} bytes it announced: the download is cut off")
        if (problem := check(partial)) is not None:
            raise DownloadError(f"{url} did not send the expected file: {problem}")
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    partial.rename(target)
    print(f"  cached {target} ({target.stat().st_size / 1e6:.1f} MB)")
    return target


def fetch_download(download: Download, cache_dir: Path) -> Path:
    return fetch(download.url, cache_dir / download.filename, lambda path: check_csv(path, download.columns))


def fetch_icgc(cache_dir: Path) -> Path:
    """The ICGC zip in the cache, or the current one from the ICGC download folder.

    A cached zip that is not complete is removed and the current one downloaded instead.
    """
    for cached in sorted(cache_dir.glob("adreces-simplificat-*.zip"), reverse=True):
        problem = check_icgc_zip(cached)
        if problem is None:
            return cached
        print(f"  cached {cached} is not a complete download ({problem}); removing it")
        cached.unlink()
    request = urllib.request.Request(ICGC_LISTING_URL, headers={"User-Agent": USER_AGENT})
    with download_errors(ICGC_LISTING_URL), urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
        listing = response.read().decode("utf-8", "replace")
    names = sorted(set(ICGC_ZIP_RE.findall(listing)))
    if not names:
        raise DownloadError(f"no adreces-simplificat zip listed at {ICGC_LISTING_URL}")
    return fetch(ICGC_LISTING_URL + names[-1], cache_dir / names[-1], lambda path: check_icgc_zip(path, full=True))


def _read_csv(path: Path, columns: Mapping[str, str]) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return [{column: row[field] for field, column in columns.items()} for row in csv.DictReader(f)]


def read_taula_direle(path: Path) -> list[dict]:
    """Rows of taula-direle with bronze.addresses column names and the published values."""
    return _read_csv(path, TAULA_DIRELE_COLUMNS)


def read_carrerer(path: Path) -> list[dict]:
    """Rows of carrerer with bronze.streets column names and the published values."""
    return _read_csv(path, CARRERER_COLUMNS)


def _zip_member(archive: zipfile.ZipFile, kind: str) -> str:
    for name in archive.namelist():
        if re.search(rf"-{kind}-\d{{8}}\.csv$", name):
            return name
    raise RuntimeError(f"no {kind} file in {archive.filename}")


def _icgc_csv(archive: zipfile.ZipFile, kind: str) -> Iterator[list[str]]:
    """Rows of one CSV of the ICGC zip, header first. Plain lists: the address file has 1.7 million rows."""
    with archive.open(_zip_member(archive, kind)) as raw:
        yield from csv.reader(io.TextIOWrapper(raw, encoding="utf-8", newline=""), delimiter=";")


def read_icgc(zip_path: Path, zone_map: ZoneMap) -> tuple[list[dict], int]:
    """Street addresses of the zone municipalities, with bronze.icgc_addresses column names.

    The register covers all of Catalonia; only the municipalities of the zones in company.json are
    kept, and that subset is cached next to the zip, because reading the whole file takes a minute.
    Returns the rows and the number of rows skipped for having no coordinates (read_icgc_subset).
    """
    return read_icgc_subset(icgc_subset(zip_path, zone_map))


def icgc_subset(zip_path: Path, zone_map: ZoneMap) -> Path:
    """The address rows of the zone municipalities, extracted once from the zip to a CSV beside it."""
    with zipfile.ZipFile(zip_path) as archive:
        municipalities = _icgc_csv(archive, "municipi")
        header = next(municipalities)
        code, name = header.index("codmuni"), header.index("nommuni")
        codes = sorted(row[code] for row in municipalities if zone_map.for_municipality(row[name]))
        if len(codes) != len(zone_map.by_municipality):
            raise RuntimeError(f"expected {len(zone_map.by_municipality)} municipalities in the ICGC file: {codes}")
        subset = zip_path.with_name(f"{zip_path.stem}-{'-'.join(codes)}.csv")
        if not subset.exists():
            addresses = _icgc_csv(archive, "adrecavia")
            header = next(addresses)
            column = header.index("codmuni")
            partial = subset.with_suffix(".part")
            with partial.open("w", encoding="utf-8", newline="") as out:
                writer = csv.writer(out)
                writer.writerow(header)
                writer.writerows(row for row in addresses if row[column] in codes)
            partial.rename(subset)
    return subset


def read_icgc_subset(path: Path) -> tuple[list[dict], int]:
    """Rows of an ICGC address CSV with bronze.icgc_addresses column names, and WGS84 coordinates.

    lon and lat are converted from the published ETRS89 UTM 31N easting and northing and rounded to
    7 decimals, like taula-direle. A row without an easting or a northing cannot be placed on a
    map, so it is skipped; the second value returned counts those rows.
    """
    rows, skipped = [], 0
    for row in _read_csv(path, ICGC_COLUMNS):
        if not row["x_etrs89"].strip() or not row["y_etrs89"].strip():
            skipped += 1
            continue
        row["x_etrs89"], row["y_etrs89"] = float(row["x_etrs89"]), float(row["y_etrs89"])
        rows.append(row)
    lons, lats = _TO_WGS84.transform([r["x_etrs89"] for r in rows], [r["y_etrs89"] for r in rows])
    for row, lon, lat in zip(rows, lons, lats, strict=True):
        row["lon"], row["lat"] = round(lon, 7), round(lat, 7)
    return rows, skipped


def barcelona_ref(row: Mapping) -> str:
    """The address_ref bronze.addresses generates: street code, number and letter."""
    return f"{row['street_code']}-{row['street_number']}{row['number_letter'].strip()}"


def barcelona_address(row: Mapping, street_name: str | None, zone_map: ZoneMap) -> Address | None:
    """A taula-direle row as a delivery address; None when it has no street name or zone."""
    zone_id = zone_map.for_district(row["district_code"])
    if zone_id is None or not street_name:
        return None
    number = (row["street_number"].lstrip("0") or "0") + row["number_letter"].strip()
    return Address(
        address_ref=row.get("address_ref") or barcelona_ref(row),
        zone_id=zone_id,
        street_address=f"{street_name}, {number}",
        postcode=f"080{row['postal_district']}",
        municipality=zone_map.municipality(zone_id),
        lat=float(row["lat"]),
        lon=float(row["lon"]),
    )


def icgc_address(row: Mapping, zone_map: ZoneMap) -> Address | None:
    """An ICGC street address as a delivery address; None for blocks and unknown municipalities."""
    zone_id = zone_map.for_municipality(row["municipality"])
    if zone_id is None or row["address_type"].strip() != "vianum":
        return None
    name, article = row["street_name"].strip(), row["street_article"].strip()
    if article:  # "de l'" joins the name directly, "del" with a space
        name = f"{article}{'' if article.endswith("'") else ' '}{name}"
    street = f"{row['street_type'].strip()} {name}".strip()
    number = row["number_from"].strip() + row["number_from_suffix"].strip()
    if row["number_to"].strip() not in ("", "0"):
        number += f"-{row['number_to'].strip()}{row['number_to_suffix'].strip()}"
    return Address(
        address_ref=row["address_id"],
        zone_id=zone_id,
        street_address=f"{street}, {number if number not in ('', '0') else 's/n'}",
        postcode=row["postcode"].strip(),
        municipality=zone_map.municipality(zone_id),
        lat=float(row["lat"]),
        lon=float(row["lon"]),
    )


def build_pool(
    barcelona_rows: list[Mapping], street_names: Mapping[str, str], icgc_rows: list[Mapping], zone_map: ZoneMap
) -> dict[str, list[Address]]:
    """Addresses per zone, sorted by address_ref so a draw by position is reproducible."""
    pool: dict[str, list[Address]] = {}
    for row in barcelona_rows:
        address = barcelona_address(row, street_names.get(row["street_code"]), zone_map)
        if address:
            pool.setdefault(address.zone_id, []).append(address)
    for row in icgc_rows:
        address = icgc_address(row, zone_map)
        if address:
            pool.setdefault(address.zone_id, []).append(address)
    return {zone_id: sorted(addresses, key=lambda a: a.address_ref) for zone_id, addresses in sorted(pool.items())}
