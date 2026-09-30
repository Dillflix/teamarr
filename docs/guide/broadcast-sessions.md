# Broadcast sessions in this fork

This fork begins with Teamarr 2.18.0, upstream commit
`9e840c74d82e72359101987afab04c9a56bd2f6b`. The initial sports scope is NFL,
NHL, MLB and NBA through Teamarr's existing providers, plus an NFL RedZone
broadcast-session source. This increment adds the RedZone source and its API;
it does not change the existing league/event APIs or add Fire TV control.

Later additions are documented in [golf sessions](golf-sessions.md) and
[special competitions and multi-sport editions](special-events.md). Their
configuration sections coexist with RedZone in `TEAMARR_BROADCAST_CONFIG`.

For league games and structured team identities, see the
[event search API](event-search.md).

## RedZone API

```http
GET /api/v1/broadcast-sessions?target_date=2026-09-27&source=nfl_redzone
```

The response is an array of sessions. `target_date` means the calendar date
in America/New_York, regardless of Teamarr's display timezone. Returned
timestamps are UTC. A session is automatically generated on Sundays when
Teamarr returns at least one regular-season NFL game starting within the
configured coverage window. Preseason, postseason, cancelled and postponed
games do not generate an automatic session. The source delegates schedule
refreshes and caching to Teamarr and does not hardcode season dates or years.

The default window starts at 13:00 Eastern with an estimated duration of
420 minutes. These are configurable planning assumptions, not a verified
channel listing. `expected_end_time` is never a playback-stop instruction.
`timing_basis` is `rule` or `override`, not a live/confirmed status.

An ID such as `nfl_redzone:2026-09-27` stays stable when its same-date time
or associated games change. Related events are referenced by provider and
event ID; no fake teams or games are created. No database migration is needed.

## Configuration

Defaults work without a configuration file. Optionally set
`TEAMARR_BROADCAST_CONFIG=/data/broadcast-sessions.json` and mount that file
when running in Docker. The file is re-read on every request.

```json
{
  "redzone": {
    "enabled": true,
    "start_time": "13:00",
    "duration_minutes": 420,
    "overrides": {
      "2026-09-27": {"start_time": "12:55"},
      "2026-10-04": {"enabled": false}
    }
  }
}
```

Those overrides are examples, not broadcast announcements. An enabled
date-specific override creates a session even on a non-Sunday or when the
event source is empty; use it only for a deliberately configured broadcast.
Set `enabled: false` on a date to suppress that session. The global switch
takes precedence over date overrides. Start times have no offset and are
interpreted in America/New_York, including daylight-saving changes.

An explicitly configured missing or invalid file returns HTTP 503. Invalid
dates or unknown source names return HTTP 422. Successful empty catalogs
return `[]`, retaining upstream schedule behavior.

## Extension boundary and agreed scope

`BroadcastSession` is separate from Teamarr's matchup-oriented `Event` model.
Its `BroadcastSessionSource` interface supports future sources for golf rounds,
fight cards, Olympic sessions and other coverage windows without forcing them
into home/away teams. The API registers `nfl_redzone` and `golf`; see
[golf sessions](golf-sessions.md) for tournament discovery and coverage configuration.
Existing XMLTV generation and frontend screens do not yet consume these
sessions; clients access the new endpoint directly.

For the eventual Fire TV controller, the user's NFL games and RedZone route
to Prime Video. App navigation, playback verification, watch rules and
device-conflict handling belong to subsequent controller integration.

Playoff timing confidence is future scope. Teamarr continues refreshing game
dates, teams and times from its providers as schedules are finalized; the
remaining question is how a future automated controller treats provisional
fixtures before confirmation. No timing-confidence gate is introduced here.

Distinguishing failed schedule fetches from genuinely empty days is also
future scope shared with upstream Teamarr. This source inherits its cache and
empty-result behavior; it does not claim independent source-health reporting
or retain a last-known RedZone session when upstream returns an empty list.

## Unified controller feed

The [controller feed](controller-feed.md) combines these sources with league games
and special-event sessions, while retaining separate event/broadcast identities
and explicit viewing options. Existing source-specific endpoints remain available.
