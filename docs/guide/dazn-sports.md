# DAZN squash and MMA broadcasts

The `dazn_sports` source imports National Squash League (`nsl`, sport `squash`)
and Beatdown MMA (`beatdown`, sport `mma`) from DAZN Canada's public daily EPG.
The competition IDs were verified against the Philadelphia Freedom–Seattle
Freeze and Beatdown 15 listings on 2026-10-29. Other squash competitions and
MMA promotions are not included by this source.

It is included in the default controller feed alongside `dazn_tennis`, independent
of ESPN/game league selections. It requires no database migration, credentials,
or `controller.league_apps` additions. The existing broadcast configuration inherits:

```json
{
  "dazn_sports": {
    "enabled": true,
    "competitions": ["nsl", "beatdown"]
  }
}
```

Merge that section into an existing configuration only if overriding defaults.
Set `enabled` to false or `competitions` to an empty list to opt out; select one
competition to import only that competition. Explicit feed source filters must
include `dazn_sports`. `/api/v1/broadcast-sessions?source=dazn_sports&target_date=2026-10-30`
uses the same configuration and parser.

Each listing is a `kind: broadcast` entry with `provider: dazn`, source metadata,
artwork and a Prime Video/DAZN viewing option. Stable identity uses DAZN EventId,
not title, scheduled time or AssetId. Beatdown is a whole fight-card broadcast,
not a separate event per bout. Squash listings currently lack structured team
IDs; no team identities or rankings are fabricated from their display titles.

Only Live/UpComing presentations are admitted. Replays, linear channels,
highlights, previews, press conferences, weigh-ins, face-offs and geo-restricted
listings are excluded. Matching requires the known competition ID and sport.
Live status requires agreement between DAZN's Type, DisplayType and VideoType;
upcoming Vod stubs remain scheduled. Elapsed dates or missing entries never imply
completion. End times remain estimates and missing ends stay unknown.

Source failures fail feed assembly rather than publishing a false empty day.
Cached status retains its original acquisition time. Prime availability and
entitlement are checked separately; DAZN IDs are not Amazon content IDs.
Update Teamarr before the controller so explicit queries for the new source
are accepted. This update does not change saved plans or discovery preferences.
