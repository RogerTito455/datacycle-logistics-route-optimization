"""Write a download cache made of the committed test addresses, so load-reference runs offline.

The files get the names and formats of the real downloads, so the loader reads them through its
usual path: taula-direle and carrerer as CSV, the ICGC register as a zip with its municipality and
address files, which the loader filters to the five towns and converts to WGS84. The sample is
far smaller than the registers, so as a download it would fail the loader's row minimums; each file
is marked complete instead, as the loader marks a download that passed its checks, and reused. Point
GENERATOR_CACHE_DIR at the directory and load-reference loads the 560 sample addresses instead of
downloading about 70 MB. The CI integration test does this (scripts/generator-db-test.sh --sample)
on a fresh stack.

Usage:
    uv run --project services/generator --frozen python services/generator/scripts/sample_cache.py DIR
"""

from __future__ import annotations

import csv
import io
import shutil
import sys
import zipfile
from pathlib import Path

from llobregat_generator import addresses

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
ICGC_NAME = "adreces-simplificat-sample"
ICGC_VERSION = "20260410"


def semicolon_csv(rows: list[dict]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, list(rows[0]), delimiter=";", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def icgc_sample() -> list[dict]:
    """The committed ICGC sample rows, 40 per town, with the columns the register publishes."""
    with (FIXTURES / "icgc_sample.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_icgc_zip(path: Path, rows: list[dict]) -> None:
    """An ICGC zip in the published format: the municipality file and the street address file."""
    municipalities = sorted({(r["codmuni"], r["nommuni"]) for r in rows})
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            f"{ICGC_NAME}-municipi-{ICGC_VERSION}.csv",
            semicolon_csv([{"codmuni": code, "nommuni": name} for code, name in municipalities]),
        )
        archive.writestr(f"{ICGC_NAME}-adrecavia-{ICGC_VERSION}.csv", semicolon_csv(rows))


def main(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    direle, carrerer, icgc = (
        target / addresses.TAULA_DIRELE.filename,
        target / addresses.CARRERER.filename,
        target / f"{ICGC_NAME}.zip",
    )
    shutil.copyfile(FIXTURES / "taula_direle_sample.csv", direle)
    shutil.copyfile(FIXTURES / "carrerer_sample.csv", carrerer)
    towns = icgc_sample()
    write_icgc_zip(icgc, towns)
    for path in (direle, carrerer, icgc):
        addresses.mark_complete(path)
    municipalities = len({r["codmuni"] for r in towns})
    print(f"sample download cache in {target}: {len(towns)} ICGC addresses in {municipalities} towns")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
