# Special-event broadcast matching

Special competition sessions now have a configured broadcast source and a
viewing-options API. A contest can have multiple feeds; a feed can cover multiple
contests or a broader Olympic edition. No app is inferred from the sport.

This implements the join and planning behavior. It does not fetch CBC, TSN or
Sportsnet Olympic listings, verify subscriptions, or start Fire TV playback.
Listing data is explicit configuration, with `timing_basis: configured`.

## Configure listings

Inside `special_events`, add `coverage` with:

- `windows`: broadcast listings with stable IDs, edition, title, timestamps,
  IANA timezone and app routing key. Optional channel, stream title and listing
  URL provide navigation and provenance metadata.
- `allowed_apps`: optional eligibility restriction. Omission permits any listed
  app; an empty array permits none. This restriction is specific to special events.
- `preferred_apps`: ordered app preferences among eligible options. Omission
  leaves ties ordered by broadcast start and ID. Preferences never change a
  listing's app or establish availability.

Each window has `coverage_type: dedicated` (default) or `multi_event`, and
`presentation: live` (default) or `replay`. Its `sports` array may contain several
sports. An empty array means unspecified sports, not a new sport called Olympics.
The legacy singular `sport` response field is null for unspecified/multiple sports.

Dedicated coverage requires exactly one `related_sessions` reference containing
`edition_id`, `provider` and `id`. Multi-event coverage accepts zero or many.
References must belong to the broadcast edition or its descendants. Never use
similar titles or coincident times as proof that two events are identical.

A reference can point to an imported session that is not yet present in a daily
query. Its edition must exist, but catalog loading does not require fetching all
future provider sessions. Missing references simply yield no exact match.

Windows require offset-bearing starts; ends are optional except for unlinked
multi-event coverage, which needs a bounded time window. Known ends must follow
starts. Preserve a window's ID when its time, date or title changes; set
`enabled: false` to withdraw it. Duplicate IDs/references and invalid edition
relationships are rejected. Configuration reloads per request.

The complete [example](../examples/special-events.json) includes fictional
dedicated hockey coverage, broad Olympic coverage and a replay. All dates,
availability and navigation targets in that example are illustrative.

## Read the broadcast inventory

```http
GET /api/v1/broadcast-sessions?source=special_events&target_date=2030-02-10
```

The inventory selects the broadcast's start date in its own timezone, consistent
with the existing RedZone/golf API convention. It includes enabled replays and
apps outside the allowlist so callers can inspect them. The viewing-options
endpoint separately reports their eligibility. Disabled windows/catalogs return
no inventory. Existing endpoint default remains RedZone.

Additional broadcast response fields are `edition_id`, `sports`,
`related_sessions`, `presentation` and `stream_title`. Existing RedZone/golf
responses retain their behavior and gain empty/null defaults for these fields.
The older `related_events` field is populated for compatibility, but special-event
consumers should use the complete edition-scoped `related_sessions` identities.

## Resolve viewing options

```http
GET /api/v1/special-events/viewing-options?target_date=2030-02-10&rule_id=canada-hockey-medals
```

This date selects sporting session starts in their edition timezone. The join
checks all configured coverage windows, including broadcasts starting on a
previous local date. Matching broadcasts are not restricted to the inventory's
same-date results. This avoids dropping overnight coverage.

The response contains one result per session/rule, like `/selections`:

- `selection`: current rule decision, sporting session and reasons.
- `options`: matching coverage candidates, each containing a broadcast, decision
  and reason codes.
- `preferred_broadcast_id`: the highest-ranked eligible option, present only
  when the viewing rule itself returns `match`.

| Option decision | Meaning |
| --- | --- |
| `eligible` | Dedicated, explicitly linked live coverage on an allowed app; its time window includes the contest start and has no known early cutoff |
| `review` | Partial/uncertain timing or multi-event coverage; not selected automatically |
| `excluded` | Replay, disallowed app, or a window ending at/before the contest starts |

Reason codes include `app_not_allowed`, `replay`, `ends_before_event`,
`starts_after_event`, `end_time_unknown`, `ends_during_event`,
`multi_event_coverage` and `event_coverage_unconfirmed`. Exclusion reasons take
precedence over review reasons. Unrelated identities, scopes and known sports
are omitted entirely. Unlinked broad coverage is considered only when its time
window contains the contest start; it always requires review.

Several explicit references do not make a mixed broadcast dedicated. Conversely,
a dedicated ceremony broadcast may reference its ceremony just like a game.
Replay options remain excluded for this live-viewing workflow.

An eligible option is a planning result, not a runtime entitlement check or proof
that a channel is currently showing the contest. Ends may be marked estimated;
this metadata is preserved and never becomes a stop-playback command. When a
contest end is unknown, the resolver cannot guarantee full-duration coverage.
When a broadcast end is unknown, it requires review: an old open-ended listing
must not silently remain preferred after a contest moves to a later date.

The example's hockey final initially has unknown countries. Its dedicated feed
is eligible, but the Canadian viewing rule is pending, so no broadcast is
preferred. Set the session's countries to `["CAN", "USA"]` and repeat: the
dedicated example CBC Gem feed becomes preferred. Neither the mixed feed nor
the replay substitutes for it automatically.

## Remaining integration

Automatic special-event listing ingestion should emit this validated window
contract with explicit event bindings. Country/participant schedule adapters,
listing freshness policies, a natural-language rule interface and a controller
that arbitrates overlapping events are separate work. The endpoint does not
poll, schedule background jobs, request purchases or operate devices.

Focused validation covers identity/provider/edition isolation, multiple feeds,
mixed sports, replays, preferences/allowlists, pending selections, overnight
coverage, reschedules and configuration reloads, alongside RedZone/golf regression
tests. It uses fixtures, not authenticated app or live broadcast tests.
