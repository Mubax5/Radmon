"""Transaction visibility fix for AlarmPolicyStore suppression creation.

When a detector transaction supplies an existing SQLite connection, the newly
inserted suppression is not visible from a second connection until commit.
Read it back through the same transaction instead of opening a new connection.
"""
from __future__ import annotations

import uuid


def apply() -> None:
    from . import alarm_policy_store as module

    def start_suppression(
        self,
        serid,
        started_at,
        expires_at,
        auto_resume_on_normal,
        pic,
        reason,
        started_by,
        *,
        connection=None,
    ):
        suppression_id = str(uuid.uuid4())
        own = connection is None
        db = connection or self.security._connection()
        row = None
        try:
            if own:
                self._begin(db)
            db.execute(
                """
INSERT INTO alarm_suppression
  (suppression_id, serid, started_at, expires_at, auto_resume_on_normal, pic, reason,
   started_by, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""",
                (
                    suppression_id,
                    int(serid),
                    module._iso(started_at),
                    module._iso(expires_at),
                    1 if auto_resume_on_normal else 0,
                    str(pic),
                    str(reason),
                    str(started_by),
                    module._iso(started_at),
                    module._iso(started_at),
                ),
            )
            row = db.execute(
                """
SELECT suppression_id, serid, started_at, expires_at, auto_resume_on_normal, pic, reason,
       started_by, ended_at, ended_reason, first_suppressed_alarm_at, created_at, updated_at
FROM alarm_suppression WHERE suppression_id = ?
""",
                (suppression_id,),
            ).fetchone()
            if own:
                db.commit()
        except Exception:
            if own:
                db.rollback()
            raise
        finally:
            if own:
                db.close()

        item = self._suppression_from_row(row)
        if item is None:
            raise RuntimeError("suppression gagal dibuat")
        return item

    module.AlarmPolicyStore.start_suppression = start_suppression
