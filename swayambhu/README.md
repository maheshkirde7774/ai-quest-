# Flask application

See the [root README](../README.md) for setup, tests and the complete organizer guides.

Run application commands from this directory. The database schema must first be
migrated with `flask --app app db upgrade`, followed by `flask --app app init-db` to
seed exactly three rounds. Never use development test credentials during the event.

See [Rolling team batches](docs/BATCHES.md) for setup, release rules and coordinator controls.
