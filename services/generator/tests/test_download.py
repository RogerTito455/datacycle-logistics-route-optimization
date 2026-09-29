"""The download cache keeps only complete, valid files, and replaces a bad cached one.

A local HTTP server plays the open-data portals, so the tests run offline: it can send a file whole,
cut it off before its announced Content-Length, answer with an error page or an HTTP error.
"""

from __future__ import annotations

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
        self.answers: dict[str, tuple[int, bytes, int | None]] = {}  # status, body, announced length
        self.requests: list[str] = []

    def serve(self, path: str, body: bytes, status: int = 200, announced: int | None = None) -> None:
        self.answers[path] = (status, body, announced)


@pytest.fixture
def portal():
    state = Portal()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802, the name http.server calls
            state.requests.append(self.path)
            status, body, announced = state.answers[self.path]
            self.send_response(status)
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


def test_a_bad_cached_file_is_downloaded_again(portal, tmp_path):
    """A cut-off file cached before downloads were checked is replaced on the next run."""
    target = tmp_path / CARRERER.filename
    target.write_bytes(GOOD_CSV[:150])
    portal.serve("/carrerer", GOOD_CSV)
    fetch(f"{portal.url}/carrerer", target, carrerer_check)
    assert portal.requests == ["/carrerer"]
    assert target.read_bytes() == GOOD_CSV


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

    name = "adreces-simplificat-v1r0-20260410.zip"
    portal.serve("/icgc/", f'<a href="{name}">{name}</a>'.encode())
    portal.serve(f"/icgc/{name}", good.read_bytes())
    monkeypatch.setattr(addresses, "ICGC_LISTING_URL", f"{portal.url}/icgc/")
    assert addresses.fetch_icgc(cache) == cache / name
    assert not cut.exists()
    assert portal.requests == ["/icgc/", f"/icgc/{name}"]


def test_a_zip_without_the_address_files_is_not_the_icgc_register(tmp_path):
    other = tmp_path / "adreces-simplificat-other.zip"
    with zipfile.ZipFile(other, "w") as archive:
        archive.writestr("readme.txt", "not the address register")
    assert "no municipi file" in check_icgc_zip(other)
