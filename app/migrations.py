"""One-way cleanup for retired features in older databases and backups."""
import re


def remove_retired_agent_state(connection, data_directory=None):
    # These tables only held temporary permissions and import previews/results.
    # Products, images, sessions, read-only tokens and audit records are separate.
    connection.execute('DROP TABLE IF EXISTS local_ai_batches')
    connection.execute('DROP TABLE IF EXISTS local_ai_grants')
    if data_directory is not None:
        (data_directory / '.local-ai-credential.json').unlink(missing_ok=True)
        for path in data_directory.glob('.local-ai-*.tmp'):
            if re.fullmatch(r'\.local-ai-[a-f0-9]{32}\.tmp', path.name) and path.is_file():
                path.unlink()
