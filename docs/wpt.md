# World Poker Tour TV airings

The default `sportsnet_wpt` broadcast source reads Sportsnet's public
[TV listings](https://watch.sportsnet.ca/schedule/tvlistings). It includes World
Poker Tour programs airing on Sportsnet Ontario, East, One, 360, West, Pacific
and World when listed as live or scheduled linear airings. Recorded tournament
episodes airing on live TV are included. On-demand entries are excluded.

Entries use competition `wpt`, sport `poker`, and coverage type `linear_program`.
Each channel and provider airing ID has its own opaque feed identity, including
consecutive programs with the same title. Program IDs are not airing IDs. The
source does not invent participants or episode subtitles unavailable in the
listings. It does not establish the viewer's Sportsnet/Prime subscription.

`GET /api/v1/broadcast-sessions?source=sportsnet_wpt&target_date=2026-11-23`
returns UTC-day listings. The controller feed includes this source by default,
independently of game league selection. To disable it, add
`"sportsnet_wpt": {"enabled": false}` to the broadcast configuration.

Live status describes the television broadcast, not live tournament action.
Schedule end times remain estimates and do not prove completion. Source errors
fail the request instead of claiming an empty schedule. Cached evidence retains
its original acquisition time.

The public schedule API was verified on November 23, 2026. The fixture preserves
two observed Pacific airings, with unused fields removed. Prime live-TV playback
requires separate validation: this catalog source alone does not implement
Prime's Live TV guide or authorize an on-demand episode.
