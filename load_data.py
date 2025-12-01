import argparse
import re
import sqlite3
import sys
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urljoin
from xml.etree import ElementTree

import requests


LIST_URL = "https://www.althingi.is/altext/xml/thingmenn/"
IMG_BASE = "https://www.althingi.is/myndir/thingmenn-cache/"
CV_URL_TEMPLATE = "https://www.althingi.is/altext/cv/is/?nfaerslunr={id}"
ROOT_TAG = "þingmannalisti"
ITEM_TAG = "þingmaður"
IMG_PATTERN = re.compile(r'src="(?P<src>/myndir/thingmenn-cache/[^"]+)"')


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            birthdate TEXT,
            image_url TEXT,
            lifshlaup_url TEXT
        )
        """
    )
    conn.commit()


def fetch_member_list() -> ElementTree.Element:
    resp = requests.get(LIST_URL, timeout=30)
    resp.raise_for_status()
    return ElementTree.fromstring(resp.content)


def extract_image_url(html: str) -> Optional[str]:
    match = IMG_PATTERN.search(html)
    if not match:
        return None
    return urljoin("https://www.althingi.is", match.group("src"))


def probe_image(member_id: int) -> Optional[str]:
    sizes = ["-600.jpg", "-400.jpg", "-220.jpg"]
    for suffix in sizes:
        url = f"{IMG_BASE}{member_id}/{member_id}{suffix}"
        try:
            resp = requests.get(url, timeout=15, stream=True)
            if resp.status_code == 200 and resp.headers.get("Content-Type", "").startswith("image/"):
                resp.close()
                return url
            resp.close()
        except Exception:
            continue
    return None


def fetch_members(root: ElementTree.Element) -> Iterable[dict]:
    if root.tag != ROOT_TAG:
        raise ValueError(f"Unexpected root tag {root.tag!r}")

    nodes = root.findall(ITEM_TAG)
    total = len(nodes)
    print(f"Found {total} þingmenn í skránni.")

    for idx, node in enumerate(nodes, start=1):
        member_id = int(node.attrib["id"])
        name = (node.findtext("nafn") or "").strip()
        birthdate = (node.findtext("fæðingardagur") or "").strip()
        # Use the localized CV URL to align with the new image locations.
        lifshlaup_url = CV_URL_TEMPLATE.format(id=member_id)

        image_url = probe_image(member_id)
        if not image_url and lifshlaup_url:
            try:
                resp = requests.get(lifshlaup_url, timeout=30)
                resp.raise_for_status()
                image_url = extract_image_url(resp.text)
            except Exception as exc:  # pragma: no cover - network variability
                print(f"⚠️  Could not fetch image for {name} ({member_id}): {exc}", file=sys.stderr)

        if not image_url:
            print(f"No image found for {name} ({member_id}).")

        if idx % 25 == 0 or idx == total:
            print(f"Processed {idx}/{total}: {name}")

        yield {
            "id": member_id,
            "name": name,
            "birthdate": birthdate,
            "lifshlaup_url": lifshlaup_url,
            "image_url": image_url,
        }


def persist_members(conn: sqlite3.Connection, members: Iterable[dict]) -> None:
    ensure_schema(conn)
    with conn:
        for member in members:
            conn.execute(
                """
                INSERT INTO members (id, name, birthdate, image_url, lifshlaup_url)
                VALUES (:id, :name, :birthdate, :image_url, :lifshlaup_url)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    birthdate=excluded.birthdate,
                    image_url=excluded.image_url,
                    lifshlaup_url=excluded.lifshlaup_url
                """,
                member,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Load þingmenn data into SQLite.")
    parser.add_argument(
        "--database",
        default="data/thingmenn.db",
        help="Path to SQLite database (default: data/thingmenn.db)",
    )
    args = parser.parse_args()

    db_path = Path(args.database)
    if db_path.parent:
        db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    try:
        print(f"Sækir lista: {LIST_URL}")
        root = fetch_member_list()
        members = list(fetch_members(root))
        print("Skrái í gagnagrunn...")
        persist_members(conn, members)
        print(f"Saved {len(members)} þingmenn to {args.database}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
