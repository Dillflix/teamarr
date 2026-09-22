# Golf: tournament discovery and daily coverage

The agreed scope is PGA TOUR and all four men's majors: the Masters, PGA
Championship, U.S. Open and The Open. They share ESPN's `pga` catalog; that
provider catalog key is not a claim that PGA TOUR organizes each event.
This increment adds tournament discovery and explicit broadcast windows.
RedZone remains available. UFC is deferred.

## Discover a tournament

```http
GET /api/v1/golf/tournaments?target_date=2026-09-20&competition=pga
GET /api/v1/golf/tournaments?season_year=2026
GET /api/v1/golf/tournaments?season_year=2026&majors_only=true
```

Supply exactly one of `target_date` and `season_year`. The response preserves
tournament ID, name, start/end dates, current round, status, season year,
major identity and broadcaster names. It uses Teamarr's existing ESPN
HTTP client and a bounded 30-minute in-memory TTL cache. It parses a golf
calendar directly rather than applying the existing matchup/date filter,
which treats a tournament's initial start as a short single-day event.
Discovery therefore retains tournaments returned by ESPN on later rounds.

Calendar dates preserve the date component of ESPN's markers. They are not
tee times, broadcast times, or a claim about the venue timezone. Broadcaster
names describe the source's market, not the user's subscription or Fire TV app.
The catalog reflects ESPN's response for the requested date or season.
Tournament end dates and rounds can be unknown. The 2026 live season probe
returned 49 entries including all four majors; this is a coverage observation,
not a guarantee that future source responses will always be complete.
`major` is `masters`, `pga_championship`, `us_open`, `the_open`, or null.
These identities use exact normalized title aliases, because the inspected
response had no explicit major flag. Future naming changes may need aliases.
An absent or failed upstream response remains an empty list, consistent with
the agreed deferral of generalized fetch-health handling.

## Configure coverage

Set `TEAMARR_BROADCAST_CONFIG` to a mounted JSON file, as for RedZone.
The following is an illustrative configuration with a fictional tournament
ID and times; replace it with a discovered tournament and actual coverage.

```json
{
  "golf": {
    "enabled": true,
    "playback_target": "your_golf_app",
    "coverage": [
      {
        "key": "round4-main",
        "tournament_id": "123",
        "tournament_name": "Example Championship",
        "competition": "pga",
        "round_number": 4,
        "coverage_type": "main",
        "start_time": "2026-09-20T13:00:00-04:00",
        "end_time": "2026-09-20T19:00:00-04:00",
        "end_time_estimated": true,
        "timezone": "America/New_York"
      }
    ]
  }
}
```

The file can contain both `redzone` and `golf` sections. It is reloaded per
request. With no configured coverage there are no golf sessions; tournament
date markers never generate guessed broadcast starts.

`start_time` must include a UTC offset. `end_time` is optional; omit it when
unknown. `timezone` sets the local start date used for querying, while the
offset-bearing timestamp supplies the actual instant. Specify the correct
offset for that date; no fixed weekly clock or recurrence rule is inferred.
An estimated end is planning metadata and never a stop-playback command.

Use `main` for the initial primary coverage. The schema also allows
`featured_group`, `featured_holes` and `other` as explicitly configured feeds;
it does not discover those feeds or their participating players automatically.
Use distinct keys for separate feeds or broadcaster windows in the same round.
An optional `label` supplies a display name. A per-window `playback_target`
overrides the golf-wide default; both may be omitted. The string is a routing
key for the future controller, not an Android package or a verified entitlement.

The immutable identity is `golf:espn:<competition>:<tournament_id>:<key>`.
Keep the key when start time or date changes, including Monday resumptions.
Use `enabled: false` on a window to cancel it or on `golf` to disable all golf.
Duplicate keys within a tournament, unknown tours, naive timestamps and
end times at or before start are rejected.

## Read coverage sessions

```http
GET /api/v1/broadcast-sessions?source=golf&target_date=2026-09-20
```

The response includes the parent event reference, round segment, coverage
type, optional playback target, UTC start and nullable expected end.
`target_date` selects the session's start date in its configured timezone;
an overnight session is returned on that start date only. Sessions have
`timing_basis: configured` because their windows came from the config file.
The original endpoint default is still RedZone; explicitly pass `source=golf`.

Coverage windows are an independent schedule source. Editing the file is
authoritative; a fresh tournament lookup does not validate, delete or move
them. This allows an explicit resumption outside the original tournament
dates, but also means cancellations and coverage changes must be reflected
in configuration until a coverage-listing importer is added. The API does
not infer daily rounds from weekdays or synthesize four days for every event.

## Remaining integration

This increment is backend discovery and coverage configuration. It does not
automatically ingest broadcaster listings, alter Teamarr's XMLTV or frontend,
or operate a Fire TV. The viewing app still needs to be selected before an
automatic listing importer can be validated for the user's actual coverage.
PGA TOUR and the four majors have been checked in the 2026 ESPN season
response; other tours are outside the initial scope.
The configured-window format gives a future importer a
concrete output contract without changing the consumers.

Focused validation:

```bash
python -m pytest -q tests/services/test_golf_sessions.py tests/services/test_broadcast_sessions.py
```
