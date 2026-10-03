---
title: DAZN Tennis Coverage
parent: User Guide
---

# Continuous tennis coverage through DAZN in Prime Video

The controller feed imports DAZN Canada's public tennis broadcast listings as
`source: dazn_tennis`, `kind: broadcast`, `competition: tennis`. A day, session,
or court tile is one selectable broadcast. ESPN ATP/WTA individual matches
remain separate; they do not define this source's schedule or completion.

The source is enabled by default in this fork. Update Teamarr before updating
the controller, then rebuild both existing Compose deployments. Keep their
configuration files and persistent volumes. No database reset or migration is
required for these additive feed fields.

Existing `TEAMARR_BROADCAST_CONFIG` files inherit the new default. To disable
this source, add the following property to the existing JSON object:

```json
"dazn_tennis": {"enabled": false}
```

Check the source directly (the date is **UTC**):

```bash
curl -fsS 'http://TEAMARR_HOST:9195/api/v1/broadcast-sessions?source=dazn_tennis&target_date=2026-10-03'
curl -fsS 'http://TEAMARR_HOST:9195/api/v1/events/feed?source=dazn_tennis&start=2026-10-03T00:00:00Z&end=2026-10-06T00:00:00Z'
```

Use current dates when checking your deployment. A valid empty day is normal.
Fetch/schema failures return HTTP 503 rather than a successful empty schedule.
The controller retains its last complete catalog and shows degraded feed health.

## Identity, routing, and evidence

- IDs use `broadcast:dazn_tennis%3Aca%3A<DAZN EventId>`. They do not include the
  title, start date, a guessed tournament day, or a player's name. A provider
  reschedule or replacement AssetId therefore retains the commitment.
- The full title, `Competition`/`TournamentCalendar` metadata, DAZN EventId and
  AssetId are preserved. DAZN asset IDs **are not Prime content IDs**. Prime
  search still supplies the actual playback identifier.
- Each viewing option has `app: prime_video`, `channel: DAZN`, and the complete
  DAZN title as `stream_title`. This is the user's configured access route;
  the external listing does not prove Prime entitlement or catalog parity.
- The source imports English Canadian listings. It excludes explicitly
  geo-restricted, linear, named-match, replay, and highlights tiles. It does
  not claim all ATP/WTA tournaments or Grand Slams are available through DAZN.
- `UpComing` is scheduled even when DAZN's placeholder has `VideoType: Vod`.
  Live requires matching explicit `Type`, `DisplayType`, and `VideoType` live
  labels. A clock comparison never changes lifecycle state.
- Missing ends remain null. `ExpirationDate` is not a broadcast end. Supplied
  ends remain planning estimates, and a match result, catch-up tile, elapsed
  estimate, missing tile, stopped playback, or service failure never completes
  the broadcast.
- DAZN image IDs supply the existing `artwork.cover_url`. No fake player/team
  logos or matchup are generated.
- `status_received_at` is Teamarr's acquisition time, retained on cache hits.
  It is **not a provider observation timestamp**. Source caching is 30 seconds;
  the updated controller preserves this timestamp when expiring evidence.

## Validation and limits

On 2026-10-03, the public Canadian EPG returned the screenshot's exact
`Beijing Open: Day 4` title, live, plus Day 5 Session 1, Day 5 Session 2, Day 6,
and Day 7 within the controller's three-day window. The implemented importer
was run against that response and retained five separate broadcasts and their
artwork. Small factual fixtures preserve live/upcoming field behavior.

The endpoint is DAZN's public, undocumented EPG, so schema changes are treated
as failures. Actual court-labelled listings, future changes in DAZN identity,
the installed Teamarr deployment, and Prime playback still need target-account
validation. No TV input or playback occurred during these checks.
