# SQLite and durable household plan edits

Use SQLite on the household server's local disk while retaining Flask and its HTTP interface. The agreed single-household workload and local operation favor avoiding a separate database service; clients access the server through HTTP and do not open a shared database file over the network. PostgreSQL remains a read-only migration source, with a portable export/import path preserving existing records rather than converting the live installation in place.

All plan mutations use a SQLite write transaction and an expected plan revision. Stale edits return a conflict instead of overwriting another household member's changes; confirmed plans stay confirmed when deliberately edited, while whole-plan regeneration is restricted to drafts. Meal/eater removal archives records so saved assignments and exports retain their history.

Use the SQLite online backup mechanism for database backups, and restore to a new destination only. Portable exports use a versioned JSON format; imports are atomic and require an empty household database. The database carries an application identifier and schema version, and refuses unknown or newer formats.

References: [SQLite application-server guidance](https://www.sqlite.org/whentouse.html), [Python SQLite backup API](https://docs.python.org/3.11/library/sqlite3.html#sqlite3.Connection.backup), [Flask application factories](https://flask.palletsprojects.com/en/stable/patterns/appfactories/).
