"""The download cache keeps only complete, valid files, marked as such, and replaces any other.

A local HTTP server plays the open-data portals, so the tests run offline: it can send a file whole,
cut it off before its announced Content-Length or in the middle of a chunk, answer with an error
page or an HTTP error. A closed port and a server that never answers stand for the network failing.
"""

from __future__ import annotations

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
GOOD_CSV = b'"codi_via","codi_carrer_ine","tipus_via","nom_curt","nom_oficial","nre_min","nre_max"\n' + (
    b'"279407","03164","C","Repartidor","Carrer del Repartidor","0001","0063"\n'
    b'"169409","01929","G.V.","GV Corts Catalanes","Gran Via de les Corts Catalanes","0111","1198"'
)
ERROR_PAGE = b"<!DOCTYPE html><html><body><h1>Service temporarily unavailable</h1></body></html>\n"


class Portal:
    """What the local server answers for each path, and the paths it was asked for."""

    def __init__(self):
        # status, body, announced length, and whether the body is sent as a chunk cut in half
        self.answers: dict[str, tuple[int, bytes, int | None, bool]] = {}
        self.requests: list[str] = []

    def serve(
        self, path: str, body: bytes, status: int = 200, announced: int | None = None, cut_chunk: bool = False
    ) -> None:
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


def carrerer_check(path: Path) -> str | None:
    return check_csv(path, CARRERER.columns)


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
        (200, GOOD_CSV[:150], len(GOOD_CSV), "cut off"),  # the connection closed early
        (200, ERROR_PAGE, None, "header has no codi_via"),  # an error page with status 200
        (200, GOOD_CSV.split(b"\n")[0] + b"\n", None, "no data rows"),  # the header only
        (503, ERROR_PAGE, None, "HTTP 503"),
    ],
    ids=["cut-off", "error-page", "header-only", "http-error"],
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


def test_an_icgc_listing_that_fails_is_a_download_error(portal, tmp_path, monkeypatch):
    portal.serve("/icgc/", ERROR_PAGE, status=503)
    monkeypatch.setattr(addresses, "ICGC_LISTING_URL", f"{portal.url}/icgc/")
    with pytest.raises(DownloadError, match="HTTP 503"):
        addresses.fetch_icgc(tmp_path)
    portal.serve("/icgc/", b"<html>no zip here</html>")
    with pytest.raises(DownloadError, match="no adreces-simplificat zip listed"):
        addresses.fetch_icgc(tmp_path)


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


def test_the_published_files_pass_their_checks(tmp_path):
    """The loader's checks accept the files as the registers publish them, with or without a final
    newline, and the sample cache that CI loads."""
    no_newline = tmp_path / "carrerer.csv"
    no_newline.write_bytes(GOOD_CSV)
    assert check_csv(no_newline, CARRERER.columns) is None
    sample_cache.main(tmp_path / "cache")
    cache = tmp_path / "cache"
    assert check_csv(cache / addresses.TAULA_DIRELE.filename, addresses.TAULA_DIRELE.columns) is None
    assert check_csv(cache / CARRERER.filename, CARRERER.columns) is None
    (zip_path,) = cache.glob("adreces-simplificat-*.zip")
    assert check_icgc_zip(zip_path, full=True) is None
    assert all(addresses.is_marked_complete(path) for path in cache.iterdir() if path.suffix != ".ok")
    assert fetch_download(CARRERER, cache) == cache / CARRERER.filename  # reused, no request made
    assert addresses.fetch_icgc(cache) == zip_path


def test_a_cut_off_icgc_zip_is_replaced_by_the_current_one(portal, tmp_path, monkeypatch):
    sample_cache.main(tmp_path / "sample")
    (good,) = (tmp_path / "sample").glob("adreces-simplificat-*.zip")
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
    assert addresses.fetch_icgc(cache) == cache / name
    assert not cut.exists() and not addresses.marker(cut).exists()
    assert addresses.is_marked_complete(cache / name)
    assert portal.requests == ["/icgc/", f"/icgc/{name}"]


def test_a_zip_without_the_address_files_is_not_the_icgc_register(tmp_path):
    other = tmp_path / "adreces-simplificat-other.zip"
    with zipfile.ZipFile(other, "w") as archive:
        archive.writestr("readme.txt", "not the address register")
    assert "no municipi file" in check_icgc_zip(other)
