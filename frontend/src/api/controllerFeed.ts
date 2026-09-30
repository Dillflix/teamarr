import { api } from "./client"
import type { EventArtwork, EventSearchResult } from "./epg"

export type FeedSource = "games" | "nfl_redzone" | "golf" | "special_events"
export type FeedStatus = "scheduled" | "live" | "final" | "postponed" | "cancelled" | "unknown"
export type WindowState = "upcoming" | "in_window" | "elapsed" | "unknown"

export interface FeedQuery {
  start: string
  end: string
  as_of: string
  leagues: string[]
  sources: FeedSource[]
  statuses: FeedStatus[]
  window_states: WindowState[]
  lookback_hours: number
  limit: number
}

export interface FeedViewingOption {
  id: string
  app: string | null
  channel: string | null
  stream_title: string | null
  listing_url: string | null
  broadcast_id: string | null
  start_time: string | null
  expected_end_time: string | null
  coverage_type: string | null
  presentation: string | null
  basis: string
  decision: "eligible" | "review" | "excluded"
  reasons: string[]
}

export interface ScheduledSession {
  id: string
  provider: string
  edition_id: string
  title: string
  sport: string | null
  kind: "game" | "race" | "heat" | "round" | "ceremony" | "other"
  start_time: string
  end_time: string | null
  status: Exclude<FeedStatus, "unknown">
  discipline: string | null
  category: string | null
  stage: string | null
  participants: string[] | null
  countries: string[] | null
  medal_event: boolean | null
}

export interface BroadcastSession {
  id: string
  source: string
  title: string
  kind: string
  sport: string | null
  sports: string[]
  competition: string
  session_date: string
  timezone: string
  start_time: string
  expected_end_time: string | null
  timing_basis: string
  end_time_estimated: boolean
  related_events: { provider: string; event_id: string }[]
  parent_event: { provider: string; event_id: string } | null
  related_sessions: { edition_id: string; provider: string; id: string }[]
  segment: string | null
  coverage_type: string | null
  playback_target: string | null
  channel: string | null
  listing_url: string | null
  edition_id: string | null
  presentation: string | null
  stream_title: string | null
}

export interface FeedEntry {
  id: string
  kind: "event" | "session" | "broadcast"
  source: FeedSource
  title: string
  provider: string | null
  competition: string
  sports: string[]
  start_time: string
  expected_end_time: string | null
  end_time_estimated: boolean | null
  timing_basis: string | null
  status: FeedStatus
  status_basis: "provider" | "configured" | "unknown"
  window_state: WindowState
  event: EventSearchResult | null
  sessions: ScheduledSession[]
  broadcast: BroadcastSession | null
  related_ids: string[]
  viewing_options: FeedViewingOption[]
  preferred_option_id: string | null
  selections: { rule_id: string; decision: "match" | "pending" | "no_match"; reasons: string[] }[]
  artwork: EventArtwork
}

export interface FeedResponse {
  schema_version: number
  query: FeedQuery
  snapshot_created_at: string
  snapshot_expires_at: string
  total: number
  count: number
  items: FeedEntry[]
  next_cursor: string | null
}

export async function getControllerFeed(query: Partial<FeedQuery> = {}): Promise<FeedResponse> {
  const params = new URLSearchParams()
  for (const key of ["start", "end", "as_of", "lookback_hours", "limit"] as const) {
    const value = query[key]
    if (value !== undefined) params.set(key, String(value))
  }
  for (const [key, values] of [
    ["league", query.leagues], ["source", query.sources],
    ["status", query.statuses], ["window_state", query.window_states],
  ] as const) {
    for (const value of values ?? []) params.append(key, value)
  }
  return api.get(`/events/feed?${params}`)
}

export async function getControllerFeedPage(cursor: string): Promise<FeedResponse> {
  return api.get(`/events/feed?${new URLSearchParams({ cursor })}`)
}
