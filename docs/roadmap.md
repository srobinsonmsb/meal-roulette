# Product direction and delivery phases

Meal Roulette is a private, locally run household planner. The household owns its data, the core workflow requires no external account, and optional integrations are chosen by the owner. Dinner is the initial planning focus.

| Phase | Outcome |
| --- | --- |
| 1. Backend foundation | Durable shared plans, SQLite, revision conflicts, portable export, recovery, and legacy-data conversion. |
| 2. Household planning | Preference-aware group/solo choices, effort, weekly routines/exceptions, labels, deliberate choices, and reliable one-way Calendar updates. |
| 3. Ingredients and groceries | Meal yields, ingredient quantities, compatible-unit totals, a shared checklist, and reconciliation of plan changes. |
| 4. Self-hosted operation | MIT licensing, documented installation/upgrades/recovery, managed services, optional automated backups, and private remote access. |
| 5. Native iOS | A SwiftUI client of the same server, with a local readable cache and explicit handling of stale edits. |

The server-connected iOS edition comes first. Device-only iOS is a conditional future direction. Recipe instructions/imports, nutrition, more external calendar/planner destinations, direct notifications, and local access controls remain later branches; pantry and leftover-portion inventory are outside the core scope.

This public document summarizes the approved product direction. Development records and acceptance remain in the project owner's issue tracker.
