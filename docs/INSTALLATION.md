# RadMon Installation Manual

## Windows PC

1. Install Python 3 and Docker Desktop.
2. Clone the repository and switch to `main`.
3. Copy `.env.example` to `.env` and fill only local deployment credentials/configuration.
4. For detector/dummy desktop use `RADMON.bat` or `RUN_DUMMY.bat`.
5. On central PC3 LAN use `RUN_LAN.bat`; LAN ingestion is owned by `central_server.py` and the desktop must not start a second collector.

The Windows runners create/update `.venv` automatically and install `requirements.txt`, including the `tzdata` package required for WIB/IANA timezones on Windows.

## Central LAN safety

Production source databases are read-only to normal RadMon ingestion. The only approved production mutation is the secured ACK/Response write-through. Quarterly archive, Reports, station display configuration, and cleanup operate on the central system only.

## First login

If no users exist, RadMon opens the bootstrap Administrator dialog. Set a strong Administrator password and a separate sensitive-action PIN. Later logins use username/password; sensitive Administrator/Operator actions request the PIN separately.
