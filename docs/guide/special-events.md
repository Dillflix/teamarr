# Special competitions and multi-sport editions

This increment adds a read-only competition catalog, general scheduled sessions,
a bridge to Teamarr league schedules, and repeatable viewing-rule evaluation.
Individual sports and ceremonies do not require home and away teams.

Implementation: `teamarr/core/special_events.py`,
`teamarr/services/special_events.py`, `teamarr/api/routes/special_events.py`.
It does not migrate the database, change Teamarr's existing Event type, create
EPG channels, or operate a Fire TV.

This fork starts at upstream commit `9e840c74d82e72359101987afab04c9a56bd2f6b`.
The exported `teamarr-golf-redzone.patch` contains the full commit series,
including this increment. Apply with `git am` on a clean branch at that baseline;
do not apply the complete series again on top of the earlier RedZone/golf commits.

## Identity and scope

| Entity | Purpose | Example |
| --- | --- | --- |
| Competition | Identity across editions | 4 Nations Face-Off; Winter Olympics |
| Edition | One dated occurrence | 4 Nations Face-Off 2025; Milano Cortina 2026 |
| Child edition | Competition within a larger edition | Olympic women's hockey |
| Scheduled session | One game, race, heat, round or ceremony | Semifinal; downhill race |
| Viewing rule | Criteria applied to current sessions | Canada hockey medal games |
| Broadcast session | App/channel coverage of zero or many contests | Dedicated final stream |

4 Nations Face-Off is separate from NHL league games and from the women's Four
Nations Cup. Use distinct competition IDs. No annual recurrence or future dates
are inferred; register each confirmed edition. An Olympic edition is a container,
not a sport. Sports and disciplines belong on its scheduled sessions; a ceremony
can have no sport.

Scheduled identity is `(edition_id, provider, id)`. Keep it when participants,
stage, title or time change. The edition graph supports multiple levels. Unknown
parents, cycles, duplicate IDs and dangling rule references are rejected.
A competition's optional `sports` list restricts sessions assigned directly to
its editions; an empty list leaves its sports unspecified. Parent competition
sport lists are not inherited by child competitions.

## Configuration and working example

Add `special_events` to the JSON file selected by `TEAMARR_BROADCAST_CONFIG`.
Existing `redzone` and `golf` behavior is retained. The special-events catalog
defaults to empty and performs no imports until configured. Configuration is
reloaded per request.

The complete [example configuration](../examples/special-events.json) uses
fictional editions, competitors and times. It includes a multi-sport parent,
a hockey child, a separate 4 Nations-style tournament, an unresolved hockey
final, and an individual race. Its rules demonstrate tournament, country,
medal and athlete selection.

```bash
export TEAMARR_BROADCAST_CONFIG=/absolute/path/to/docs/examples/special-events.json
```

Start Teamarr using your normal launch command, then query:

```http
GET /api/v1/special-events/competitions
GET /api/v1/special-events/editions
GET /api/v1/special-events/sessions?target_date=2030-02-10
GET /api/v1/special-events/selections?target_date=2030-02-10
GET /api/v1/special-events/selections?target_date=2030-02-10&rule_id=canada-hockey-medals
```

Selections include `rule_id`, the current `session`, `decision` and `reasons`.
The example's Canadian hockey rule returns `pending` for the unresolved final,
with `countries` as its reason. Set that session's `countries` to `["CAN", "USA"]`
and repeat the query: the same identity now matches. No restart is required.

## Reuse Teamarr's international hockey schedules

The inspected upstream catalog includes `olympics-mens-ice-hockey` and
`olympics-womens-ice-hockey`. Bind a dedicated league to a configured edition
using an `imports` row inside `special_events`:

```json
{
  "edition_id": "your-olympic-hockey-edition",
  "league": "olympics-womens-ice-hockey",
  "sport": "hockey",
  "category": "women",
  "team_countries": {
    "espn:REPLACE_WITH_CANADA_TEAM_ID": "CAN",
    "espn:REPLACE_WITH_USA_TEAM_ID": "USA"
  },
  "event_details": {
    "espn:REPLACE_WITH_EVENT_ID": {"stage": "final", "medal_event": true}
  }
}
```

Replace edition and provider IDs with actual values. This fragment is not a
standalone configuration. Do not bind an entire NHL schedule to an international
tournament: date overlap does not establish tournament membership. Automatic
4 Nations discovery is not implemented; use configured sessions until a
dedicated source or event-ID mapping is verified.

The bridge delegates fetching/caching to `SportsDataService.get_events`, preserving
provider IDs, refreshed starts, status and participant names. It imports only the
specified league and sport within the edition's configured date bounds. Include
competition days before the opening ceremony in those bounds. Edition-local
days are converted to the days required by Teamarr's user timezone, then filtered
back to the edition-local day and deduplicated. DST is handled using IANA zones.

Country codes are explicit provider-scoped team mappings, not name deductions.
Until both teams have mappings, countries remain unknown. Optional `event_details`
supplies stage, medal status or other metadata not normalized by Teamarr. Only
explicitly supplied fields override imported details. These configured supplements
remain authoritative until edited; medal status and national-team mappings are
not automatically discovered.

Configured sessions supplement imports. A row with the same full identity
overrides an import, including moving it to another date or cancelling it.
A different identity adds a session. Explicit reschedules can be outside the
original import bounds; extend those bounds if provider discovery should also
cover the new dates. Each query evaluates current data; there is no persistent
selection snapshot to become stale.

## Selection semantics

Filters: edition IDs, competition IDs, kinds, sports, disciplines, categories,
stages, countries, participants and medal-event status. Criteria combine with
AND; multiple values within a criterion combine with OR. Matching is exact and
case-sensitive. Use consistent codes such as CAN, USA, SWE, FIN; code standards
are not silently translated. Participant filters currently use exact display
names; provider athlete-ID matching remains future work.

Edition and competition scopes include descendants by default. Set
`include_descendants: false` for only the immediate edition/competition. Both
scope filters apply if both are specified.

- `match`: every criterion passes and the contest is scheduled/live.
- `pending`: no known mismatch, but required metadata is unknown.
- `no_match`: a criterion fails, the rule is disabled, or the contest is final,
  postponed or cancelled.

Unknown metadata is `null`; empty participants/countries explicitly means none.
A known mismatch takes precedence over unknown metadata. Reasons identify failed
criteria for `no_match` or missing criteria for `pending`. Rules with no filters
match all scheduled/live sessions in this catalog; scope rules intentionally.

Disabled catalogs return no sessions or selections, but definitions remain
inspectable. Unknown rule IDs return 404, invalid query dates 422, and invalid or
missing configured files 503. Query dates select session starts in the edition's
timezone, not all sessions overlapping that day. Offset-bearing start times are
required in this first version; unknown end times are allowed.

## Broadcast and playback boundary

Sporting start times do not establish broadcast start times or app availability.
Olympic hockey is not automatically routed through the user's NHL app. The
TSN/Sportsnet restriction remains golf-specific; Olympic routing can later include
CBC Gem according to listings and installed apps.

The next broadcaster adapter should link listings by edition and provider event
identity, support several feeds for one contest and several contests per feed,
and distinguish dedicated live coverage, mixed coverage, ceremonies and replays.
Mixed coverage alone cannot establish that a requested final will be shown.
This increment does not expose a special-events broadcast source or turn matches
into playback jobs. Existing RedZone/golf broadcast endpoints remain available.

A later controller consumes matched sessions and verified broadcast options,
checks entitlement, and arbitrates overlaps on one Fire TV. Priority, interruption
permission and queues belong there; this read-only endpoint does not infer them
or poll automatically.

Full Olympic ingestion, automatic 4 Nations discovery, athlete IDs, broadcaster
joins, natural-language rule authoring, UI and device control remain integration
work. Imports inherit Teamarr's coverage and refresh behavior. General fetch-health
reporting and playoff TBD handling remain deferred as agreed.

## Validation

```bash
python -m pytest -q tests/services/test_special_events.py tests/services/test_golf_sessions.py tests/services/test_tsn_golf.py tests/services/test_broadcast_sessions.py
```

Tests cover hierarchy isolation, unknown participation followed by resolution,
individual sessions and ceremonies, provider identity, timezones/DST, reschedules,
cancellations, invalid graphs and configuration reloads. Controlled provider
fixtures validate the adapter; these are not live Olympic feed coverage tests.
