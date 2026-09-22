# Golf: tournament discovery and daily coverage

The agreed scope is PGA TOUR and all four men's majors: the Masters, PGA
Championship, U.S. Open and The Open. They share ESPN's `pga` catalog; that
provider catalog key is not a claim that PGA TOUR organizes each event.
Golf playback is limited to TSN and Sportsnet according to the user's setup.
This increment adds tournament discovery, automatic TSN broadcast-window
import, and explicit coverage windows for overrides or Sportsnet listings.
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

Automatic TSN import is enabled by default. With no configuration file,
`GET /api/v1/broadcast-sessions?source=golf&target_date=2026-09-24` fetches
the current [TSN golf schedule](https://www.tsn.ca/golf/article/golf-on-tsn-broadcast-schedule/),
matches its table rows to the ESPN season catalog and returns listed coverage.
The verified 2026-09-22 page produced five Presidents Cup playing-coverage
windows for September 24-27, all on TSN1. The opening ceremony was excluded.
There are two distinct Saturday rows in that source; both are preserved.

The importer uses exact normalized tournament names and a small set of major
aliases. It skips ambiguous/unmatched tournaments, cancelled/postponed catalog
events, ceremonies, replays and TBD/unsupported time formats. It reads explicit
year-bearing dates and Eastern start times, and handles daylight-saving changes.
It preserves the TSN channel, source URL and day/round label. It does not infer
end times or convert a team competition's "Day One" into "Round 1".
The current page is cached for 15 minutes; the catalog for 30 minutes.

The allowlist (`allowed_apps`, default `["tsn", "sportsnet"]`) is not availability
evidence. Imported TSN listings explicitly select `tsn`; a global preference
for Sportsnet cannot redirect them. A CTV-only row does not establish TSN
availability. A `TSN+` designation, when listed, is preserved as the channel
within the TSN destination. App authentication/subscription checks belong to
the later playback controller.

Set `import_tsn_schedule: false` for configuration-only operation. Sportsnet
is currently supported through explicit windows with `playback_target:
"sportsnet"`; an automatic Sportsnet schedule adapter is not yet validated.

Set `TEAMARR_BROADCAST_CONFIG` to a mounted JSON file, as for RedZone.
The following is an illustrative configuration with a fictional tournament
ID and times; replace it with a discovered tournament and actual coverage.

```json
{
  "golf": {
    "enabled": true,
    "allowed_apps": ["tsn", "sportsnet"],
    "import_tsn_schedule": true,
    "playback_target": "tsn",
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
request. Configured windows supplement imported listings, or override a
listing when their complete session IDs match. Tournament date markers
never generate guessed broadcast starts. Neither app is assumed available
for a date without an imported or configured window.

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
overrides the golf-wide default; both may be omitted. Windows targeting an
app outside `allowed_apps` are excluded. The string is a routing
key for the future controller, not an Android package or a verified entitlement.

The immutable identity is `golf:espn:<competition>:<tournament_id>:<key>`.
Keep the key when start time or date changes, including Monday resumptions.
Use `enabled: false` on a window to cancel it or on `golf` to disable all golf.
Duplicate keys within a tournament, unknown tours, naive timestamps and
end times at or before start are rejected.

Imported keys use the tournament, normalized day/round label, TSN channel and
occurrence number for repeated rows. They remain stable across time edits
while that structure is unchanged. TSN does not supply persistent row IDs;
changes to labels, channels or repeated-row order can change generated IDs.
Copy an imported window's key to override its time or disable it. A configured
window with `enabled: false` suppresses its matching imported session. A
different key creates a separate session and does not override a listing.

## Read coverage sessions

```http
GET /api/v1/broadcast-sessions?source=golf&target_date=2026-09-20
```

The response includes the parent event reference, round segment, coverage
type, optional playback target, channel, listing URL, UTC start and nullable expected end.
`target_date` selects the session's start date in its configured timezone;
an overnight session is returned on that start date only. Sessions have
`timing_basis: listing` for imported windows and `configured` for manual windows.
The original endpoint default is still RedZone; explicitly pass `source=golf`.

Imported windows follow the current source table on refresh. Manual windows
remain authoritative until edited; a fresh tournament lookup does not validate,
delete or move them. This allows an explicit resumption outside the original
tournament dates. The API does not infer rounds from weekdays or synthesize
four days for every event. Failures and an empty source still produce no
imported windows; generalized source-health handling remains deferred.

## Remaining integration

This increment supplies backend discovery and TSN schedule ingestion. It does
not alter Teamarr's XMLTV or frontend or operate a Fire TV. The source adapter
has been validated against the current TSN table layout, not every historical
or future table variation. It cannot retrieve a complete season's broadcast
windows when TSN only publishes the upcoming events. Its parser needs updates
if TSN changes the page structure or tournament titles.
PGA TOUR and the four majors have been checked in the 2026 ESPN season
response; other tours are outside the initial scope.
The configured-window format gives a future importer a
concrete output contract without changing the consumers.

Focused validation:

```bash
python -m pytest -q tests/services/test_golf_sessions.py tests/services/test_tsn_golf.py tests/services/test_broadcast_sessions.py
```
