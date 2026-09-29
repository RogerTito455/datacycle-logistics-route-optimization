"""The download cache keeps only complete, valid files, marked as such, and replaces any other.

A local HTTP server plays the open-data portals, so the tests run offline: it can send a file whole,
cut it off before its announced Content-Length or in the middle of a chunk, answer with an error
page or an HTTP error. A closed port and a server that never answers stand for the network failing.
"""

from __future__ import annotations

import itertools
import socket
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from llobregat_generator import addresses
from llobregat_generator.addresses import DownloadError, check_csv, check_icgc_zip, fetch, fetch_download

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sample_cache  # noqa: E402

CARRERER = addresses.CARRERER
HEADER = b'"codi_via","codi_carrer_ine","tipus_via","nom_curt","nom_oficial","nre_min","nre_max"\n'
ROWS = [
    b'"279407","03164","C","Repartidor","Carrer del Repartidor","0001","0063"',
    b'"169409","01929","G.V.","GV Corts Catalanes","Gran Via de les Corts Catalanes","0111","1198"',
    *(f'"{900000 + n}","{n:05d}","C","Prova {n}","Carrer de Prova {n}","0001","0099"'.encode() for n in range(4000)),
]
# A carrerer file as Open Data BCN publishes it, without a final newline, with a few more streets
# than a complete file has at least.
GOOD_CSV = HEADER + b"\n".join(ROWS)
ERROR_PAGE = b"<!DOCTYPE html><html><body><h1>Service temporarily unavailable</h1></body></html>\n"
NO_LENGTH = -1  # Portal.serve: send no Content-Length header


def cut_after(rows: int) -> bytes:
    """GOOD_CSV cut at a row boundary, after this many data rows."""
    return HEADER + b"".join(row + b"\n" for row in ROWS[:rows])


class Portal:
    """What the local server answers for each path, and the paths it was asked for."""

    def __init__(self):
        # status, body, announced length, and whether the body is sent as a chunk cut in half
        self.answers: dict[str, tuple[int, bytes, int | None, bool]] = {}
        self.requests: list[str] = []

    def serve(
        self, path: str, body: bytes, status: int = 200, announced: int | None = None, cut_chunk: bool = False
    ) -> None:
        """announced is the Content-Length sent: None for the body's own, NO_LENGTH for no header."""
        self.answers[path] = (status, body, announced, cut_chunk)


@pytest.fixture
def portal():
    state = Portal()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802, the name http.server calls
            state.requests.append(self.path)
            status, body, announced, cut_chunk = state.answers[self.path]
            self.send_response(status)
            if cut_chunk:  # one chunk announced whole, half of it sent
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                self.wfile.write(f"{len(body):x}\r\n".encode() + body[: len(body) // 2])
                return
            if announced != NO_LENGTH:
                self.send_header("Content-Length", str(len(body) if announced is None else announced))
            self.end_headers()
            self.wfile.write(body)  # then the connection closes, even when fewer bytes than announced

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state.url = f"http://127.0.0.1:{server.server_port}"
    yield state
    server.shutdown()
    server.server_close()


carrerer_check = CARRERER.check


def icgc_zip(path: Path, per_town: int, short_town: str = "") -> Path:
    """An ICGC zip in the published format with per_town street addresses in each of the five towns,
    one fewer in the town whose name contains short_town; the sample rows are repeated."""
    towns: dict[str, list[dict]] = {}
    for row in sample_cache.icgc_sample():
        towns.setdefault(row["nommuni"], []).append(row)
    rows = []
    for name, sample in towns.items():
        count = per_town - 1 if short_town and short_town in name else per_town
        rows += itertools.islice(itertools.cycle(sample), count)
    sample_cache.write_icgc_zip(path, rows)
    return path


def test_a_complete_download_is_cached_and_reused(portal, tmp_path):
    portal.serve("/carrerer.csv", GOOD_CSV)
    target = tmp_path / "carrerer.csv"
    assert fetch(f"{portal.url}/carrerer.csv", target, carrerer_check) == target
    assert target.read_bytes() == GOOD_CSV
    assert sorted(p.name for p in tmp_path.iterdir()) == ["carrerer.csv", "carrerer.csv.ok"]
    assert addresses.is_marked_complete(target)
    fetch(f"{portal.url}/carrerer.csv", target, carrerer_check)
    assert portal.requests == ["/carrerer.csv"]  # the second call read the cache


@pytest.mark.parametrize(
    ("status", "body", "announced", "reason"),
    [
        # The connection closed before the announced length, at a row boundary and with more rows
        # than the minimum: only the Content-Length check catches it.
        (200, cut_after(len(ROWS) - 1), len(GOOD_CSV), f"sent {len(cut_after(len(ROWS) - 1))} of the .* announced"),
        # Cut at a row boundary without a Content-Length: only the row minimum catches it.
        (200, cut_after(3000), NO_LENGTH, "3,000 data rows, fewer than the 4,000 of a complete file"),
        (200, ERROR_PAGE, None, "header has no codi_via"),  # an error page with status 200
        (200, HEADER, None, "no data rows"),  # the header only
        (503, ERROR_PAGE, None, "HTTP 503"),
    ],
    ids=["cut-before-its-length", "cut-at-a-row-boundary-without-a-length", "error-page", "header-only", "http-error"],
)
def test_a_bad_download_is_not_cached(portal, tmp_path, status, body, announced, reason):
    portal.serve("/carrerer.csv", body, status, announced)
    target = tmp_path / "carrerer.csv"
    with pytest.raises(DownloadError, match=reason):
        fetch(f"{portal.url}/carrerer.csv", target, carrerer_check)
    assert list(tmp_path.iterdir()) == []  # neither the file nor a partial one is left


def test_a_chunk_cut_off_is_a_download_error(portal, tmp_path):
    """http.client raises IncompleteRead when a chunked answer stops in the middle of a chunk."""
    portal.serve("/carrerer.csv", GOOD_CSV, cut_chunk=True)
    with pytest.raises(DownloadError, match="could not be downloaded: IncompleteRead"):
        fetch(f"{portal.url}/carrerer.csv", tmp_path / "carrerer.csv", carrerer_check)
    assert list(tmp_path.iterdir()) == []


def test_a_refused_connection_is_a_download_error(tmp_path):
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]  # nothing listens on it once the socket is closed
    with pytest.raises(DownloadError, match="could not be downloaded: .*[Rr]efused"):
        fetch(f"http://127.0.0.1:{port}/carrerer.csv", tmp_path / "carrerer.csv", carrerer_check)
    assert list(tmp_path.iterdir()) == []


def test_a_server_that_never_answers_is_a_download_error(tmp_path, monkeypatch):
    monkeypatch.setattr(addresses, "HTTP_TIMEOUT_S", 0.2)
    with socket.socket() as silent:
        silent.bind(("127.0.0.1", 0))
        silent.listen()  # the connection is accepted, the request never answered
        url = f"http://127.0.0.1:{silent.getsockname()[1]}/carrerer.csv"
        with pytest.raises(DownloadError, match="could not be downloaded: timed out"):
            fetch(url, tmp_path / "carrerer.csv", carrerer_check)
    assert list(tmp_path.iterdir()) == []


def test_an_icgc_listing_that_fails_is_a_download_error(portal, tmp_path, monkeypatch, zone_map):
    portal.serve("/icgc/", ERROR_PAGE, status=503)
    monkeypatch.setattr(addresses, "ICGC_LISTING_URL", f"{portal.url}/icgc/")
    with pytest.raises(DownloadError, match="HTTP 503"):
        addresses.fetch_icgc(tmp_path, zone_map)
    portal.serve("/icgc/", b"<html>no zip here</html>")
    with pytest.raises(DownloadError, match="no adreces-simplificat zip listed"):
        addresses.fetch_icgc(tmp_path, zone_map)


@pytest.mark.parametrize(
    "cached",
    [
        GOOD_CSV[:150],  # cut in the middle of a row
        GOOD_CSV[: GOOD_CSV.rindex(b"\n") + 1],  # cut at a row boundary: it would pass the check
    ],
    ids=["cut-mid-row", "cut-at-a-row-boundary"],
)
def test_a_cached_file_without_its_marker_is_downloaded_again(portal, tmp_path, cached):
    """A file cached before downloads were checked has no marker, and is replaced on the next run,
    whatever its content."""
    target = tmp_path / CARRERER.filename
    target.write_bytes(cached)
    portal.serve("/carrerer", GOOD_CSV)
    fetch(f"{portal.url}/carrerer", target, carrerer_check)
    assert portal.requests == ["/carrerer"]
    assert target.read_bytes() == GOOD_CSV
    assert addresses.is_marked_complete(target)


def test_a_cached_file_that_no_longer_matches_its_marker_is_downloaded_again(portal, tmp_path):
    portal.serve("/carrerer", GOOD_CSV)
    target = tmp_path / CARRERER.filename
    fetch(f"{portal.url}/carrerer", target, carrerer_check)
    target.write_bytes(GOOD_CSV.replace(b"Repartidor", b"Repartidora"))  # changed after it was marked
    assert not addresses.is_marked_complete(target)
    fetch(f"{portal.url}/carrerer", target, carrerer_check)
    assert portal.requests == ["/carrerer", "/carrerer"]
    assert target.read_bytes() == GOOD_CSV
    addresses.marker(target).write_text('{"bytes": 1', encoding="utf-8")  # a marker cut off
    assert not addresses.is_marked_complete(target)


def test_the_published_formats_pass_the_checks_and_the_marked_sample_cache_is_reused(tmp_path, zone_map):
    """The loader's checks accept the files as the registers publish them, with or without a final
    newline. The sample cache that CI loads has their formats but not their size, so the row
    minimums would reject it as a download; it is marked complete instead, and reused."""
    no_newline = tmp_path / "carrerer.csv"
    no_newline.write_bytes(GOOD_CSV)
    assert CARRERER.check(no_newline) is None
    with_newline = tmp_path / "carrerer-newline.csv"
    with_newline.write_bytes(GOOD_CSV + b"\n")
    assert CARRERER.check(with_newline) is None
    assert check_icgc_zip(icgc_zip(tmp_path / "icgc.zip", addresses.MIN_ROWS_ICGC_PER_MUNICIPALITY), zone_map) is None

    sample_cache.main(tmp_path / "cache")
    cache = tmp_path / "cache"
    direle, carrerer = cache / addresses.TAULA_DIRELE.filename, cache / CARRERER.filename
    (zip_path,) = cache.glob("adreces-simplificat-*.zip")
    assert check_csv(direle, addresses.TAULA_DIRELE.columns) is None
    assert check_csv(carrerer, CARRERER.columns) is None
    assert check_icgc_zip(zip_path) is None
    assert "fewer than the 100,000" in addresses.TAULA_DIRELE.check(direle)
    assert "fewer than the 4,000" in CARRERER.check(carrerer)
    assert "fewer than the 1,000" in check_icgc_zip(zip_path, zone_map)
    assert all(addresses.is_marked_complete(path) for path in (direle, carrerer, zip_path))
    assert fetch_download(CARRERER, cache) == carrerer  # reused, no request made
    assert addresses.fetch_icgc(cache, zone_map) == zip_path


def test_an_icgc_zip_with_too_few_addresses_in_a_town_is_rejected(tmp_path, zone_map):
    short = icgc_zip(tmp_path / "short.zip", addresses.MIN_ROWS_ICGC_PER_MUNICIPALITY, short_town="Hospitalet")
    problem = check_icgc_zip(short, zone_map)
    assert problem == "addresses in L'Hospitalet de Llobregat 999, fewer than the 1,000 of a complete register"
    assert check_icgc_zip(short) is None  # the structure alone is fine


def test_a_cut_off_icgc_zip_is_replaced_by_the_current_one(portal, tmp_path, monkeypatch, zone_map):
    good = icgc_zip(tmp_path / "good.zip", addresses.MIN_ROWS_ICGC_PER_MUNICIPALITY)
    addresses.mark_complete(good)
    cache = tmp_path / "cache"
    cache.mkdir()
    cut = cache / "adreces-simplificat-v1r0-20260101.zip"
    cut.write_bytes(good.read_bytes()[:-200])  # the central directory of a zip is at its end
    assert "not a complete zip file" in check_icgc_zip(cut)
    addresses.marker(cut).write_text(addresses.marker(good).read_text(encoding="utf-8"), encoding="utf-8")

    name = "adreces-simplificat-v1r0-20260410.zip"
    portal.serve("/icgc/", f'<a href="{name}">{name}</a>'.encode())
    portal.serve(f"/icgc/{name}", good.read_bytes())
    monkeypatch.setattr(addresses, "ICGC_LISTING_URL", f"{portal.url}/icgc/")
    assert addresses.fetch_icgc(cache, zone_map) == cache / name
    assert not cut.exists() and not addresses.marker(cut).exists()
    assert addresses.is_marked_complete(cache / name)
    assert portal.requests == ["/icgc/", f"/icgc/{name}"]


def test_a_zip_without_the_address_files_is_not_the_icgc_register(tmp_path):
    other = tmp_path / "adreces-simplificat-other.zip"
    with zipfile.ZipFile(other, "w") as archive:
        archive.writestr("readme.txt", "not the address register")
    assert "no municipi file" in check_icgc_zip(other)
