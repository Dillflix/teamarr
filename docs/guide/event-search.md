# Event search for controllers

```http
GET /api/v1/epg/events/search?league=nfl&target_date=2026-10-04&limit=200
```

The response contains `count`, `target_date`, and `events`. Each event keeps
the existing `event_id`, `event_name`, `league`, `league_name`, `start_time`,
`status`, `home_team`, and `away_team` fields. The last two remain full-name
strings so existing clients continue to work.

`home_team_details` and `away_team_details` provide structured identities.
For example, the home side of a Detroit game includes:

```json
{
  "home_team": "Detroit Lions",
  "home_team_details": {
    "id": "8",
    "provider": "espn",
    "full_name": "Detroit Lions",
    "city": "Detroit",
    "name": "Lions",
    "short_name": "Lions",
    "abbreviation": "DET",
    "logo_url": "https://a.espncdn.com/i/teamlogos/nfl/500/det.png"
  }
}
```

| Field | Meaning |
| --- | --- |
| `id`, `provider` | Provider-scoped team identity; retain the event's league as context |
| `full_name` | Full display name, also returned in the original team string |
| `city` | Provider location label; may be a region, state, school or country |
| `name` | Provider team nickname, such as `Lions` or `Maple Leafs` |
| `short_name` | Provider short display label; not necessarily the nickname |
| `abbreviation` | Provider abbreviation |
| `logo_url` | Original provider logo URL, not a generated game-thumbs image |

Location and nickname come directly from ESPN's `location` and `name`
fields in scoreboard/summary, individual team, and team-list responses.
This supports the initial NFL/NHL/MLB/NBA scope without additional requests
or a game-thumbs dependency. The API uses snake_case (`full_name`), unlike
game-thumbs' `fullName`.

Missing components are `null`; full names are never split or guessed.
Other providers and athlete/tournament placeholders currently leave the new
components `null`. A missing team returns a `null` details object. Old cache
entries still load, with `null` components until their normal provider refresh;
no database migration or global cache purge is required.

## Estimated event end

Each event also exposes a planning estimate:

```json
{
  "start_time": "2026-10-04T17:00:00+00:00",
  "expected_end_time": "2026-10-04T20:30:00+00:00",
  "end_time_estimated": true,
  "timing_basis": "sport_duration"
}
```

The end is the event start plus the configured duration for its sport,
using the same `get_sport_duration` lookup as Teamarr's EPG pipeline.
`GET /api/v1/settings/durations` returns these settings in hours; the existing
PUT endpoint updates them. Settings are read once per search request, so
changes apply even when the event itself comes from cache.

Default estimates are 3.5 hours for football/baseball and 3 hours for
hockey/basketball. Unrecognized sports use the configured global default
and return `timing_basis: "default_duration"`. End timestamps are in UTC;
duration arithmetic accounts for midnight and daylight-saving transitions.
Invalid durations (nonpositive, nonfinite, or overflowing) produce `null`
for all three estimate fields instead of an unusable timestamp.

This estimate is not a broadcaster's scheduled coverage window or an actual
finish time. It does not incorporate per-channel template overrides, delays,
overtime, or live progress, and it never changes the provider's `status`.
Do not stop playback when the estimated time passes. Multi-day tournaments
and multi-segment cards need session-specific coverage from the separate
broadcast/session APIs; a sport-duration estimate does not describe their
full coverage. No event filtering or cache expiry behavior changes here.

The existing query behavior is unchanged: optional `team` filters full names
by substring, `limit` defaults to 50 and is capped at 200, and `target_date`
defaults to the server's current date. Provider statuses are cached, so this
is not a real-time playback confirmation API. RedZone and other broadcast
sessions remain on their separate APIs.

## Additional controller metadata

Event search also returns provider and sport, short display name, status detail,
period/clock, scores, broadcaster names and feed markets, season/week/event notes,
series summary, venue/neutral-site context, tournament/round metadata, and MMA
segment times/bouts when present. `artwork` contains resolved league/team/matchup
logos and a cover URL using the configured game-thumbs integration. These fields
add no per-event network requests.

For time-window queries across games and coverage, chronological pagination and
linked viewing options, use the [unified controller feed](controller-feed.md).
