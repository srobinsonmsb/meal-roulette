# Local operation and household data ownership

Each household will initially run its own open-source Meal Roulette server, used by web and future iOS clients, and retain ownership of its data. Initial access will rely on the trusted household network, with a local password or login allowed later; the product will not use external authentication platforms or centrally collect household data. Tailscale is the recommended route for remote access.

A device-only iOS edition is a possible later direction, subject to feasibility and storage needs; it is not required for the initial iOS client.

Households must be able to export all their data in a documented, portable format and restore a complete backup onto another installation. Automated cloud backups will be optional and use a provider chosen by the household; backup mechanics remain open decisions.

The storage choice was deferred during the vision interview. Phase 1 selects SQLite for the local household server; see [the storage and durable-edit decision](0003-sqlite-and-durable-plan-edits.md).
