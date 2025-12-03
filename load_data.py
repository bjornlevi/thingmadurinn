import argparse
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urljoin
from xml.etree import ElementTree

import requests


LIST_URL = "https://www.althingi.is/altext/xml/thingmenn/"
THINGSETA_URL_TEMPLATE = "https://www.althingi.is/altext/xml/thingmenn/thingmadur/thingseta/?nr={id}"
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memberships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            thing INTEGER NOT NULL,
            flokkur_id INTEGER,
            flokkur TEXT,
            start_date TEXT,
            end_date TEXT,
            UNIQUE(member_id, thing, flokkur_id, start_date, end_date),
            FOREIGN KEY(member_id) REFERENCES members(id)
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


def normalize_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return datetime.strptime(cleaned, "%d.%m.%Y").date().isoformat()
    except ValueError:
        return cleaned


def parse_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def fetch_member_thingseta(member_id: int) -> list[dict]:
    url = THINGSETA_URL_TEMPLATE.format(id=member_id)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    root = ElementTree.fromstring(resp.content)

    entries = []
    for node in root.findall(".//þingseta"):
        thing_value = parse_int((node.findtext("þing") or "").strip())
        if thing_value is None:
            continue

        flokkur_node = node.find("þingflokkur")
        flokkur_name = (flokkur_node.text or "").strip() if flokkur_node is not None else ""
        flokkur_id = parse_int(flokkur_node.attrib.get("id")) if flokkur_node is not None else None

        timabil_node = node.find("tímabil")
        start_date = normalize_date(timabil_node.findtext("inn") if timabil_node is not None else None)
        end_date = normalize_date(timabil_node.findtext("út") if timabil_node is not None else None)

        entries.append(
            {
                "member_id": member_id,
                "thing": thing_value,
                "flokkur_id": flokkur_id,
                "flokkur": flokkur_name,
                "start_date": start_date,
                "end_date": end_date,
            }
        )

    return entries


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


def persist_member_memberships(conn: sqlite3.Connection, member_id: int, entries: Iterable[dict]) -> int:
    ensure_schema(conn)
    entries_list = list(entries)
    with conn:
        conn.execute("DELETE FROM memberships WHERE member_id = ?", (member_id,))
        for entry in entries_list:
            conn.execute(
                """
                INSERT INTO memberships (member_id, thing, flokkur_id, flokkur, start_date, end_date)
                VALUES (:member_id, :thing, :flokkur_id, :flokkur, :start_date, :end_date)
                """,
                entry,
            )
    return len(entries_list)


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

        print("Sæki þingsetu fyrir hvern þingmann...")
        total_memberships = 0
        total_members = len(members)
        for idx, member in enumerate(members, start=1):
            try:
                entries = fetch_member_thingseta(member["id"])
                total_memberships += persist_member_memberships(conn, member["id"], entries)
            except Exception as exc:  # pragma: no cover - network variability
                print(
                    f"⚠️  Gat ekki sótt þingsetu fyrir {member['name']} ({member['id']}): {exc}",
                    file=sys.stderr,
                )
            if idx % 25 == 0 or idx == total_members:
                print(f"Þingsetur lokið {idx}/{total_members} þingmönnum.")

        print(f"Saved {len(members)} þingmenn and {total_memberships} þingsetur to {args.database}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
