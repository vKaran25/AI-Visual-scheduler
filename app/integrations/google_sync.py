"""Availability snapshots and recoverable delivery of committed calendar changes."""

import hashlib
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from googleapiclient.errors import HttpError
from sqlmodel import Session, select

from app.db.models import Block, GoogleConnection, GoogleEventMapping, SyncJob, User, new_id, utc_now
from app.db.session import engine
from app.db.transactions import changed, lock_calendar
from app.integrations import google
from app.runtime.context import LeaseLost
from app.services import scheduler_service


def import_availability(db, user, force=False, start=None, end=None):
    record = db.get(GoogleConnection, user.id)
    if record is None:
        return False
    if (
        not force
        and not start
        and record.last_sync_at
        and utc_now() - record.last_sync_at < timedelta(minutes=5)
    ):
        return True
    revision = record.revision
    # Finish the read transaction before any external network call.
    db.commit()
    try:
        service = google.get_calendar_service(user)
        if not service:
            return False
        zone = ZoneInfo(user.timezone)
        now = utc_now()
        window = {
            "timeMin": start or (now - timedelta(days=1)).isoformat(),
            "timeMax": end or (now + timedelta(days=60)).isoformat(),
            "singleEvents": True,
            "orderBy": "startTime",
        }
        calendar_id = google.get_managed_calendar_id(service, user)
        mapped = set(
            db.exec(
                select(GoogleEventMapping.event_id).where(
                    GoogleEventMapping.user_id == user.id, GoogleEventMapping.imported == False
                )
            ).all()
        )
        db.commit()
        data = []
        for cal in dict.fromkeys(("primary", calendar_id)):
            token = None
            while True:
                page = service.events().list(calendarId=cal, pageToken=token, **window).execute()
                for event in page.get("items", []):
                    if cal == calendar_id and event["id"] in mapped:
                        continue
                    for block in google._event_blocks(event, cal, zone):
                        block["external_key"] = f"{cal}:{event['id']}:{block['date']}"
                        data.append(block)
                token = page.get("nextPageToken")
                if not token:
                    break
        from app.runtime import context as execution

        try:
            execution.current()
        except LookupError:
            pass
        else:
            execution.fence(db)
        owner = lock_calendar(db, user.id)
        connection = db.exec(
            select(GoogleConnection)
            .where(GoogleConnection.user_id == user.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if not connection or connection.revision != revision:
            db.rollback()
            return False
        first_day = (
            google.datetime.fromisoformat(window["timeMin"].replace("Z", "+00:00"))
            .astimezone(zone)
            .date()
            .isoformat()
        )
        last_day = (
            (
                google.datetime.fromisoformat(window["timeMax"].replace("Z", "+00:00")).astimezone(zone)
                - timedelta(microseconds=1)
            )
            .date()
            .isoformat()
        )
        current = list(
            db.exec(
                select(Block).where(
                    Block.user_id == user.id,
                    Block.is_gcal == True,
                    Block.date >= first_day,
                    Block.date <= last_day,
                )
            ).all()
        )
        data = [b for b in data if first_day <= b["date"] <= last_day]
        old_signature = sorted((b.date, b.start, b.end, b.label, b.preset_source) for b in current)
        new_signature = sorted(
            (b["date"], b["start"], b["end"], b["label"], "google_import:" + b["external_key"]) for b in data
        )
        if old_signature != new_signature:
            for block in current:
                db.delete(block)
            db.flush()
            for item in data:
                scheduler_service.create_block(
                    db,
                    user,
                    item,
                    skip_overlap=True,
                    commit=False,
                    preset_source="google_import:" + item["external_key"],
                )
            changed(db, owner)
        connection.last_sync_at = utc_now()
        connection.sync_error = None
        db.add(connection)
        db.commit()
        return True
    except LeaseLost:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        row = db.get(GoogleConnection, user.id)
        if row:
            row.sync_error = "Google availability could not be refreshed. Existing imports were retained."
            db.add(row)
            db.commit()
        return False


def stable_event_id(user_id, block_id):
    return hashlib.sha256(f"predestination:{user_id}:{block_id}".encode()).hexdigest()


def event_body(payload, user_id):
    from datetime import timedelta

    from app.domain.time import event_instants

    repeats = payload.get("repeatDays", [])
    day = payload.get("date")
    if repeats:
        today = (
            date.fromisoformat(payload["anchor_date"])
            if payload.get("anchor_date")
            else google.datetime.now(ZoneInfo(payload["timezone"])).date()
        )
        day = (today + timedelta(days=min((d - today.weekday()) % 7 for d in repeats))).isoformat()
    first, last = event_instants(day, payload["start"], payload["end"], payload["timezone"])
    body = {
        "summary": payload["label"],
        "start": {"dateTime": first.isoformat(), "timeZone": payload["timezone"]},
        "end": {"dateTime": last.isoformat(), "timeZone": payload["timezone"]},
        "extendedProperties": {
            "private": {
                "scheduler_user_id": str(user_id),
                "scheduler_block_id": str(payload["id"]),
                "scheduler_revision": str(payload["revision"]),
            }
        },
    }
    if repeats:
        weekdays = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
        body["recurrence"] = ["RRULE:FREQ=WEEKLY;BYDAY=" + ",".join(weekdays[d] for d in repeats)]
    return body


def same_event(remote, body):
    def instant(value):
        from datetime import datetime

        return datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00"))

    return (
        remote.get("summary") == body.get("summary")
        and instant(remote["start"]) == instant(body["start"])
        and instant(remote["end"]) == instant(body["end"])
        and remote.get("recurrence", []) == body.get("recurrence", [])
    )


def claim_sync():
    with Session(engine) as db:
        now = utc_now()
        job = db.exec(
            select(SyncJob)
            .where(
                ((SyncJob.status == "queued") & (SyncJob.available_at <= now))
                | ((SyncJob.status == "running") & (SyncJob.lease_until < now))
            )
            .order_by(SyncJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        ).first()
        if job is None:
            return None
        job.status, job.lease_token, job.lease_until = "running", new_id(), now + timedelta(seconds=90)
        job.attempts += 1
        db.add(job)
        db.commit()
        db.refresh(job)
        return job.model_dump()


def deliver(job):
    """Stable event IDs recover a remote create that succeeded before local acknowledgement."""
    with Session(engine) as db:
        user = db.get(User, job["user_id"])
        connection = db.get(GoogleConnection, job["user_id"])
        if not user or not connection:
            return "cancelled"
        current = db.get(Block, job["block_id"])
        if job["action"] == "upsert" and (not current or current.revision != job["payload"]["revision"]):
            return "superseded"
        if db.exec(
            select(SyncJob).where(
                SyncJob.block_id == job["block_id"],
                SyncJob.user_id == user.id,
                SyncJob.created_at < job["created_at"],
                SyncJob.status.in_(["queued", "running"]),
            )
        ).first():
            return "queued"
        mapping = db.exec(
            select(GoogleEventMapping).where(
                GoogleEventMapping.user_id == user.id,
                GoogleEventMapping.block_id == job["block_id"],
                GoogleEventMapping.imported == False,
            )
        ).first()
    if job["action"] == "import":
        setup_service = google.get_calendar_service(user)
        if setup_service is None:
            raise ValueError("Google connection needs authorization")
        google.get_managed_calendar_id(setup_service, user, create=True)
        with Session(engine) as db:
            if not import_availability(
                db, user, force=True, start=job["payload"].get("start"), end=job["payload"].get("end")
            ):
                raise ValueError("Google availability could not be refreshed")
        return "completed"
    service = google.get_calendar_service(user)
    if service is None:
        raise ValueError("Google connection needs authorization")
    calendar_id = google.get_managed_calendar_id(service, user)
    remote_id = mapping.event_id if mapping else stable_event_id(user.id, job["block_id"])
    etag = mapping.etag if mapping else None
    if job["action"] == "delete":
        request = service.events().delete(calendarId=calendar_id, eventId=remote_id)
        if etag:
            request.headers["If-Match"] = etag
        try:
            request.execute()
        except HttpError as exc:
            if exc.resp.status not in (404, 410):
                raise
        result = None
    else:
        body = event_body(job["payload"], user.id)
        if mapping:
            remote = service.events().get(calendarId=calendar_id, eventId=remote_id).execute()
            private = remote.get("extendedProperties", {}).get("private", {})
            if private.get("scheduler_revision") == str(job["payload"]["revision"]):
                if not same_event(remote, body):
                    raise ValueError("The Google event was changed externally; review before retrying")
                result = remote
            else:
                if etag and remote.get("etag") != etag:
                    raise ValueError("The Google event was changed externally; review before retrying")
                request = service.events().update(calendarId=calendar_id, eventId=remote_id, body=body)
                if etag:
                    request.headers["If-Match"] = etag
                result = request.execute()
        else:
            try:
                result = (
                    service.events().insert(calendarId=calendar_id, body={**body, "id": remote_id}).execute()
                )
            except HttpError as exc:
                if exc.resp.status != 409:
                    raise
                result = service.events().get(calendarId=calendar_id, eventId=remote_id).execute()
                private = result.get("extendedProperties", {}).get("private", {})
                if private.get("scheduler_block_id") != str(job["block_id"]) or private.get(
                    "scheduler_user_id"
                ) != str(user.id):
                    raise ValueError("Remote event identity conflict")
                if private.get("scheduler_revision") == str(job["payload"]["revision"]) and not same_event(
                    result, body
                ):
                    raise ValueError("The Google event was changed externally; review before retrying")
                if private.get("scheduler_revision") != str(job["payload"]["revision"]):
                    result = (
                        service.events()
                        .update(calendarId=calendar_id, eventId=remote_id, body=body)
                        .execute()
                    )
    with Session(engine) as db:
        row = db.exec(select(SyncJob).where(SyncJob.id == job["id"]).with_for_update()).one()
        if row.lease_token != job["lease_token"] or row.status != "running":
            return "superseded"
        mapping = db.exec(
            select(GoogleEventMapping).where(
                GoogleEventMapping.user_id == user.id,
                GoogleEventMapping.block_id == job["block_id"],
                GoogleEventMapping.imported == False,
            )
        ).first()
        if result:
            if mapping is None:
                mapping = GoogleEventMapping(
                    user_id=user.id, block_id=job["block_id"], calendar_id=calendar_id, event_id=remote_id
                )
            mapping.etag = result.get("etag")
            db.add(mapping)
        elif mapping:
            db.delete(mapping)
        db.commit()
    return "completed"


def sync_once():
    job = claim_sync()
    if not job:
        return False
    error = None
    try:
        status = deliver(job)
    except Exception:
        status = "failed" if job["attempts"] >= 5 else "queued"
        error = "Google synchronization failed; reconnect Google or retry this job."
    with Session(engine) as db:
        row = db.exec(select(SyncJob).where(SyncJob.id == job["id"]).with_for_update()).one()
        if row.lease_token == job["lease_token"] and row.status == "running":
            row.status, row.error = status, error
            row.available_at = utc_now() + timedelta(seconds=min(300, 2 ** job["attempts"]))
            row.lease_token, row.lease_until = None, None
            db.add(row)
            db.commit()
    return True


def refresh_for_dates(db, user, dates):
    from datetime import datetime, timedelta

    if not dates:
        return google.sync_gcal_events(db, user, force=True)
    zone = ZoneInfo(user.timezone)
    start = datetime.fromisoformat(min(dates)).replace(tzinfo=zone)
    end = (datetime.fromisoformat(max(dates)) + timedelta(days=1)).replace(tzinfo=zone)
    return google.sync_gcal_events(db, user, force=True, start=start.isoformat(), end=end.isoformat())


def queue_import(db, user, dates=None):
    from datetime import datetime

    from sqlalchemy.dialects.postgresql import insert

    if db.get(GoogleConnection, user.id) is None:
        return
    payload = {}
    if dates:
        zone = ZoneInfo(user.timezone)
        payload = {
            "start": datetime.fromisoformat(min(dates)).replace(tzinfo=zone).isoformat(),
            "end": (datetime.fromisoformat(max(dates)) + timedelta(days=1)).replace(tzinfo=zone).isoformat(),
        }
    key = (
        "import:"
        + str(user.id)
        + ":"
        + str(int(utc_now().timestamp()) // 300)
        + ":"
        + hashlib.sha256(str(payload).encode()).hexdigest()[:16]
    )
    statement = insert(SyncJob).values(
        id=new_id(),
        user_id=user.id,
        operation_key=key,
        action="import",
        block_id=0,
        payload=payload,
        status="queued",
        attempts=0,
        available_at=utc_now(),
        created_at=utc_now(),
    )
    db.execute(statement.on_conflict_do_nothing(index_elements=["operation_key"]))
    db.commit()
