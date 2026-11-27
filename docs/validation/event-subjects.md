# Event subjects: one subject while an event moves (ideas#118)

Measured 24 Nov 2026; code in `tools/event_subjects.py`, called from
`tools/feed_history.py` before the history run.

## What went wrong
From the 21 Nov 2026 roll, a jamming event's `subject_id` was the H3 res-2 region at its centre. A res-2 region
averages 86,800 km² (edges about 183 km); an event covers 2 to 10 regions about 300 km across, so its centre moves
between regions from one day to the next. COP's ledger, four daily rolls (21-24 Nov 2026, aircraft days 20-23 Nov):

| | Count |
|---|---|
| New event subjects | 67 |
| ... one region from an event that ended in the same roll | 27 (6, 6, 6, 9 by roll) |
| ... of those, sharing a region with that ended event | 19 |
| Event subjects that kept their key into the next roll ("changed") | 6 |
| Subjects ended and new again one roll later under the same key | 19 |
| Data days with two or more events under one key (19-23 Nov) | 4 of 85 subject-days, 13 of 93 events |

Adjacency alone is no proof (new events sit next to other days' ended events as often, 40%, because the areas
persist), but shared regions are, and so are pairs like Bucharest to Bucharest in neighbouring regions on 24 Nov.
Spoof-place (res 5), spoof-region and region keys showed no such splits and are unchanged.

## The rule
1. A new event takes the subject of an earlier event whose regions it shares, most shared regions first. Earlier means
   open in the history state, or ended within 36 hours, so a one-day gap keeps the subject and a two-day gap does not.
2. One subject per item in a feed. The kit's history keeps a second item of a subject under its own dated id, which
   logs it new and ended every day, so of two events overlapping one earlier subject the one sharing more regions takes
   it and the other takes its next match.
3. No earlier ground: the centre key. If an open subject that has moved away is named for that region, or another item
   of the feed holds the key, the first free `<region>-2`, `<region>-3`.
4. On any failure the keys stay as built (a centre key is always valid).

Rule 2 means a subject never holds several items, for the reason given.

## Replay
COP's 12Z snapshots of 20-24 Nov 2026 run through the kit's history, events only, with the keys as built and with the
rule (the recomputed centre key matched the published one on 77 of 79 events):

| Four rolls, 79 events | As built | With the rule |
|---|---|---|
| New lines | 66 | 42 |
| Ended lines | 72 | 48 |
| Subjects carried into the next roll | 13 | 37 (47%) |
| Of the new lines, a subject back after a gap | 17 | 11 |
| Events sharing a key with another in the same feed | 7 | 0 |

The other half of each day's events have no ground in common with the day before and start a subject of their own.

## Effect on readers
From the first roll with the rule, event subjects in this feed's history and COP's ledger follow the activity, not the
centre region. Past lines are not changed. An event's `subject_id` can name a region the event no longer covers.
