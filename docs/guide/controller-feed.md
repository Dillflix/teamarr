# Unified controller feed

This fork exposes a read-only feed for a Fire TV controller or another schedule
consumer. It joins Teamarr's existing event providers, RedZone rules, golf
coverage, and special-competition sessions. It does not start/stop playback,
verify subscriptions, or claim that a listed broadcast is currently playing.

## Query

```http
GET /api/v1/events/feed
```

By default the window is now through the next 24 hours, with NFL, NHL, MLB and
NBA, CFL, UEFA Champions League and Formula 1 sessions plus the enabled RedZone, golf and special-event sources.

For a specific UTC window:

```http
GET /api/v1/events/feed?start=2026-10-04T16:00:00Z&end=2026-10-05T02:00:00Z&limit=100
```

For controller candidates, include unknown-status broadcast windows alongside
scheduled/live sporting events:

```http
GET /api/v1/events/feed?status=scheduled&status=live&status=unknown
```

| Parameter | Contract |
| --- | --- |
| `start`, `end` | ISO timestamps with an explicit offset; half-open window `[start,end)`. Default: now and start + 24 hours. Maximum span: 7 days. |
| `as_of` | Optional offset-aware instant for calculating `window_state`; defaults to request time. It does not fetch historical provider state. |
| `league` | Repeatable league codes, e.g. `league=nfl&league=nhl`. Defaults to NFL/NHL/MLB/NBA/CFL/uefa.champions/f1. Applies to ordinary game discovery; other sources have their own competition configuration. Maximum 20. |
| `source` | Repeatable: `games`, `nfl_redzone`, `golf`, `special_events`. All four by default. |
| `status` | Repeatable: `scheduled`, `live`, `final`, `postponed`, `cancelled`, `unknown`. No filter by default. |
| `window_state` | Repeatable: `upcoming`, `in_window`, `elapsed`, `unknown`. Separate from provider status. |
| `lookback_hours` | Prior start times to discover for ongoing/overnight events, default 48, range 0–168. |
| `limit` | Page size 1–500, default 100. |
| `cursor` | For subsequent pages; send this parameter **alone**. |

Date-based source calls are translated using Teamarr's configured IANA timezone,
Eastern for RedZone, and each configured edition/coverage timezone. Entries are
then filtered by UTC overlap and sorted by `(start_time, id)` across all sources.
An event may have started before the requested window. A provider-reported live
event within the discovery lookback survives even when its estimated end passed.
Explicit multi-day configured sessions/windows are considered even if their start
precedes the lookback. Unknown-end entries are included if their start is within
the discovery range. Providers do not offer an unlimited historical live scan;
increase lookback when needed.

## Response and pagination

```json
{
  "schema_version": 1,
  "query": {
    "start": "2026-10-04T16:00:00Z",
    "end": "2026-10-05T02:00:00Z",
    "as_of": "2026-10-04T18:00:00Z",
    "leagues": ["nfl", "nhl", "mlb", "nba", "cfl", "uefa.champions", "f1"],
    "sources": ["games", "nfl_redzone", "golf", "special_events"],
    "statuses": [],
    "window_states": [],
    "lookback_hours": 48,
    "limit": 100
  },
  "snapshot_created_at": "2026-10-04T18:00:01Z",
  "snapshot_expires_at": "2026-10-04T18:03:01Z",
  "total": 0,
  "count": 0,
  "items": [],
  "next_cursor": null
}
```

The example is illustrative, not an assertion of an empty real schedule.
`total` counts all matching entries before pagination; `count` is this page's
size. Follow `next_cursor` until it is null:

```http
GET /api/v1/events/feed?cursor=RETURNED_CURSOR
```

Pages come from the same immutable snapshot. Schedule changes cannot move a row
between pages, and subsequent pages make no new source fetches. Start a new
query to refresh the feed. Snapshot time is **not** provider fetch/update time;
provider-level freshness and fetch-health metadata remain future scope.

Snapshots expire after 180 seconds, with at most 32 snapshots and 10,000 items per
snapshot. They are process-local: use one worker or sticky routing for pagination
across workers/replicas. Restart, expiry or eviction returns HTTP **410**, requiring
a new first-page query. Invalid filters/cursors return **422**; an oversized result
returns **413** (narrow the query). Configuration/adapter exceptions return **503**.
Existing provider services can still represent a fetch failure as an empty result;
this endpoint does not change that previously deferred upstream behavior.

## Entry contract

| Field | Meaning |
| --- | --- |
| `id` | Opaque, stable identity independent of the scheduled timestamp or title |
| `kind` | `event`, `session`, or `broadcast` |
| `source` | Source family that contributed the row |
| `title`, `provider`, `competition`, `sports` | Display and source identity/context |
| `start_time`, `expected_end_time` | UTC instants; unknown end is null |
| `end_time_estimated`, `timing_basis` | Distinguish sport/default-duration estimates from configured/listed coverage |
| `status`, `status_basis` | Provider or configured sporting status; broadcast windows have unknown live status |
| `window_state` | Time comparison at `query.as_of`; being `in_window` does not establish live action |
| `event` | Enriched event-search object when provider details are available; otherwise null |
| `sessions` | Edition-scoped sessions, including participants/countries/discipline/stage/medal metadata |
| `broadcast` | Original broadcast-session record for coverage entries; null otherwise |
| `related_ids` | Linked feed IDs, possibly outside this page, filter, or window |
| `viewing_options` | App/channel/stream-title candidates with explicit suitability decisions |
| `preferred_option_id` | First eligible option for an active/unknown-status entry with matching rules, or null |
| `selections` | Existing special-event rule decisions and reasons |
| `artwork` | Resolved league/team/matchup/cover URLs where applicable |

Game IDs include provider, league and provider event ID. Special-session IDs
include edition, provider and session ID. Broadcasts have their own IDs. Treat
all IDs as opaque; component values are escaped. Imported special-event games
merge with ordinary games only through an unambiguous configured import binding
and exact provider ID. The same ID is retained even if a configured reschedule
has no provider details in the fetched date buckets. Names and coincident start
times never establish identity. Configured
special-session overrides apply before filtering, including reschedules out of the
requested window. A merged row retains ordinary-game source when that source was
requested; its `sessions` array carries the additional competition membership.

Golf tournament calendar spans are not manufactured into timed broadcasts.
Golf feed entries come from actual configured/imported coverage windows and link
to their parent tournament identity. Tournament discovery remains available at
`/api/v1/golf/tournaments`; a parent reference need not have a row in this feed.

Never infer completion from an estimated end, `window_state=elapsed`, or absence
from a later filtered feed. Provider live status can outlast the estimate. Clock
values are source display strings, not a countdown the controller should extrapolate.

## Viewing options and routing

Options expose `app`, `channel`, `stream_title`, `listing_url`, `broadcast_id`,
coverage start/end, `coverage_type`, `presentation`, `basis`, `decision`, and
`reasons`. The option's `broadcast_id`, when present, is a feed ID; the nested
broadcast record still contains its original source ID. Listing URLs are source
attribution, not assumed playback/deep links.

- `eligible`: suitable according to configuration and known coverage metadata.
- `review`: incomplete/partial/multi-event coverage or an unknown app/end time.
- `excluded`: replay, disallowed app, or coverage incompatible with the event.

These decisions do not verify regional availability or subscription entitlement.
A preferred option is a planning choice, not an instruction to start playback now.
Special-event app preferences, selection rules and coverage checks reuse the
existing special-coverage service. RedZone is an eligible viewing target in its own
right with the configured Prime Video route, but its link from an individual NFL
game is marked `review: multi_event_coverage_not_full_game`.

Extend the same `TEAMARR_BROADCAST_CONFIG` JSON file used by existing sources:

```json
{
  "controller": {
    "league_apps": {
      "nfl": "prime_video", "nhl": "prime_video", "mlb": "prime_video",
      "nba": "prime_video", "cfl": "prime_video",
      "uefa.champions": "prime_video", "f1": "prime_video"
    },
    "source_apps": {"nfl_redzone": "prime_video"}
  }
}
```

Those defaults reflect this deployment's subscriptions: DAZN, Sportsnet and TSN
are accessed exclusively within **Prime Video**. NBA, CFL, Champions League and
F1 therefore use `prime_video`, not the broadcasters' standalone apps. This is
configured access, not a claim that every game is included in a base Prime
subscription. Regional availability and subscribed channels still apply.

An explicit `controller.league_apps` object replaces the complete default mapping;
include every desired league or set it to `{}` to disable game/session routes.
Each configured league supplies an eligible `route:<league>:prime_video` option
with `basis: "configured_route"`. Provider broadcaster names remain attribution
and are never automatically converted into app routes. Golf and special-event
coverage retain their own configured routing rules.

## Formula 1 sessions

Each provider competition becomes its own `kind: "session"`, `source: "games"`
entry: practice, sprint qualifying, sprint, qualifying or race. IDs include the
provider, league, weekend ID and provider session ID; rescheduling or renaming
never changes that identity. `event.tournament_id`/`tournament_name` identify the
weekend and `event.round_name` identifies the session. The parent weekend is a
related ID, not an additional playable weekend-long event. Home/away fields are
null because the provider's racing placeholders are not teams.

Session status comes from that session's provider data. A completed practice
cannot finish Sunday's race, and a start time cannot prove a session is live.
Expected ends remain sport-duration estimates. Sessions without provider IDs
are omitted; legacy ESPN F1 cache records missing the new identity/status fields
are refreshed through the existing cache service.

## Metadata and artwork

The old `/api/v1/epg/events/search` endpoint remains compatible and shares the
same event serializer. It now includes provider/sport, detailed status/period/clock,
scores, broadcasters/markets, season/week/postseason notes, series context, venue,
neutral-site status, tournament/round context, and MMA segment times/bouts when
available. Missing optional data remains null or empty rather than inferred.

Artwork uses Teamarr's configured Game-Thumbs Base URL, database league-ID mapping,
existing PascalCase filters and base-URL helper. It returns absolute URLs without
fetching game-thumbs. Without a configured base, original provider logos remain
available, but generated matchup/cover URLs are null. The controller feed has no
per-channel EPG template selection; standard matchup styles are used. League-only
broadcasts can use league artwork; no fake teams are constructed.

## Extension boundary

The feed separates sporting identity, coverage, app routing and controller action.
Additional sports can use existing Teamarr league providers; new coverage sources
should produce `BroadcastSession` records with exact parent/session references.
UFC segments and later Olympic disciplines fit this contract without adding
home/away teams to events that do not have them. Automatic app navigation,
playback verification, provider freshness, fetch-health and additional broadcaster
importers remain separate work.
