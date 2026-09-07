from __future__ import annotations

from radmon.config import Settings
from radmon.db import connect_mariadb


def main() -> int:
    settings = Settings.from_env()
    serid = 5202
    name = "IS-1 Koridor"
    location = "Gd.52"
    warnlevel = 8.0
    alarmlevel = 10.0
    maxidlemin = 5
    connection = connect_mariadb(settings)
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
INSERT INTO device
  (serid, name, location, maxidlemin, warnlevel, alarmlevel, unit,
   audiopath, hwaddress, hwtype, description)
VALUES (?, ?, ?, ?, ?, ?, 'uSv/h', '', ?, 'serial', ?)
ON DUPLICATE KEY UPDATE
  name = VALUES(name), location = VALUES(location), maxidlemin = VALUES(maxidlemin),
  warnlevel = VALUES(warnlevel), alarmlevel = VALUES(alarmlevel), unit = VALUES(unit),
  description = VALUES(description)
""", (serid, name, location, maxidlemin, warnlevel, alarmlevel, "DPFK-5202", "Demo detector Gedung 52 / IS-1 Koridor"))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    print("Registered demo station 5202 - IS-1 Koridor - Gd.52")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
