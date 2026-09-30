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

The existing query behavior is unchanged: optional `team` filters full names
by substring, `limit` defaults to 50 and is capped at 200, and `target_date`
defaults to the server's current date. Provider statuses are cached, so this
is not a real-time playback confirmation API. RedZone and other broadcast
sessions remain on their separate APIs.
