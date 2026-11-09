# Routines, quantities, and calendar retries

Automatic planning continues to require explicit preference-list approval. Effort uses quick, moderate, and involved levels; an effort limit excludes meals whose effort is unknown. Deliberate assignments survive draft regeneration, weekly exceptions override routine defaults, and constrained dinner candidates are matched across the whole week so an unconstrained day cannot consume another day's only viable choice.

Grocery requirements use decimal quantities divided by meal yield for each planned diner. Compatible mass and volume units are combined separately; US teaspoons, tablespoons, and cups are volume measures, and custom units combine only with themselves. Missing ingredient records produce visible warnings. A changed or reintroduced generated quantity retains its previous amount, clears purchased/already-owned marks, and requires review; manual shopping items survive plan changes.

Calendar publication uses stable UUID-based event IDs derived from the household installation identity and assignment. Acknowledged mappings survive restart and recovery. Confirmed-plan changes queue durable sync work after initial publication; retries update or remove managed events, never import external edits, and do not discard the local plan. The sync queue is processed independently of local saves.

Schema/data format version 2 adds these records. Version 1 SQLite databases migrate transactionally, version 1 portable exports remain importable, and restoring an older supported database allows migration at startup.
