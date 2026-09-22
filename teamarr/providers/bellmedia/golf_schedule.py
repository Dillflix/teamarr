"""Parse the public TSN golf broadcast table; no account or video-stream access."""

import re
from dataclasses import dataclass
from datetime import date, datetime, time
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

TSN_GOLF_SCHEDULE_URL = "https://www.tsn.ca/golf/article/golf-on-tsn-broadcast-schedule/"


@dataclass(frozen=True)
class TSNGolfListing:
    tournament: str
    date: date
    label: str
    start_time: datetime
    channel: str


class _Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables: list[tuple[str, list[list[str]]]] = []
        self._heading = ""
        self._heading_parts: list[str] | None = None
        self._rows: list[list[str]] | None = None
        self._row: list[str] = []
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading_parts = []
        elif tag == "table":
            self._rows = []
        elif self._rows is not None:
            if tag == "tr":
                self._row = []
            elif tag in {"td", "th"}:
                self._cell = []
            elif tag == "br" and self._cell is not None:
                self._cell.append(" ")

    def handle_data(self, data):
        if self._heading_parts is not None:
            self._heading_parts.append(data)
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading = " ".join("".join(self._heading_parts or []).split())
            self._heading_parts = None
        elif tag in {"td", "th"} and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._rows is not None:
            self._rows.append(self._row)
        elif tag == "table" and self._rows is not None:
            self.tables.append((self._heading, self._rows))
            self._rows = None


def _start_time(day: date, value: str) -> datetime | None:
    value = re.sub(r"[\s.]", "", value.casefold()).removesuffix("et")
    if value == "noon":
        clock = time(12)
    elif value == "midnight":
        clock = time(0)
    else:
        match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(am|pm)", value)
        if not match:
            return None
        hour, minute = int(match[1]), int(match[2] or 0)
        if not 1 <= hour <= 12 or not 0 <= minute <= 59:
            return None
        clock = time(hour % 12 + (12 if match[3] == "pm" else 0), minute)
    return datetime.combine(day, clock, ZoneInfo("America/New_York"))


def parse_tsn_golf_listings(html: str) -> list[TSNGolfListing]:
    parser = _Tables()
    parser.feed(html)
    listings: list[TSNGolfListing] = []
    seen = set()
    for heading, rows in parser.tables:
        tournament = re.sub(r"\s+Broadcast Schedule$", "", heading, flags=re.I)
        metadata_next = False
        columns: list[str] = []
        for row in rows:
            lower = [value.casefold() for value in row]
            if lower[:2] == ["event", "location"]:
                metadata_next = True
                continue
            if lower[:2] == ["date", "event"]:
                columns = lower
                metadata_next = False
                continue
            if metadata_next:
                tournament = row[0] if row else ""
                metadata_next = False
                continue
            if not columns or not tournament or len(row) != len(columns):
                continue
            cells = dict(zip(columns, row, strict=True))
            label = cells.get("event", "")
            if not label:
                continue
            if re.search(r"ceremony|preview|highlights|replay|encore|recap|practice", label, re.I):
                continue
            day = None
            for fmt in ("%A, %B %d, %Y", "%B %d, %Y", "%a, %b %d, %Y"):
                try:
                    day = datetime.strptime(cells.get("date", ""), fmt).date()
                    break
                except ValueError:
                    continue
            if day is None:
                continue
            start = _start_time(day, cells.get("time (et)", ""))
            if start is None:
                continue
            # A CTV-only row is not evidence that it can be watched in TSN.
            networks = cells.get("network", "")
            channels = re.findall(r"(?<!\w)TSN(?:\+|\s*[1-5])?(?!\w)", networks, re.I)
            for channel in dict.fromkeys(re.sub(r"\s", "", c.upper()) for c in channels):
                signature = (tournament, day, label, start, channel)
                if signature not in seen:
                    seen.add(signature)
                    listings.append(TSNGolfListing(tournament, day, label, start, channel))
    return listings
