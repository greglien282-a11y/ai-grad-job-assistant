"""Disposable A graph -> new read candidate. NOT a formal FactV3 projector."""

from datetime import timezone
from uuid import UUID
from research.g3_choice_protocol.runtime import recover, Refused
from research.g3_choice_protocol.read_candidate import (
    READ_CONTRACT,
    EVENT_CONTRACT,
    SCOPE,
    parse_batch,
)


def _stamp(value):
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def project(db, sid, token, key):
    result = recover(db, sid, token, key, version=3, scheme="A")
    oid = UUID(result["operation_id"])
    rows = db.execute(
        "SELECT * FROM ref_choices WHERE operation_id=%s ORDER BY effect_slot", (oid,)
    ).fetchall()
    views = []
    for choice in rows:
        fact = db.execute(
            "SELECT * FROM ref_facts WHERE id=%s", (choice["fact_id"],)
        ).fetchone()
        turn = db.execute(
            "SELECT * FROM ref_turns WHERE id=%s", (choice["statement_turn_id"],)
        ).fetchone()
        ctx = db.execute(
            "SELECT * FROM ref_auth_contexts WHERE id=%s", (choice["auth_context_id"],)
        ).fetchone()
        labels = {
            k: fact[k]
            for k in ("fact_kind", "progress_stage", "classification_contract")
        }
        cite = dict(
            turn_id=str(turn["id"]),
            start=choice["start_cp"],
            end=choice["end_cp"],
            quote=choice["quote"],
        )
        subject = {k: str(fact[k]) for k in ("session_id", "project_id")}
        subject.update(
            fact_id=str(fact["id"]),
            fact_version=fact["version"],
            statement=fact["statement"],
            status=fact["status"],
            **labels
        )
        auth = {
            k: str(ctx[k])
            for k in (
                "id",
                "session_id",
                "project_id",
                "operation_id",
                "authenticated_subject",
            )
        }
        auth.update(
            source_kind="server_authenticated_session",
            issuer=ctx["issuer"],
            db_login=ctx["db_login"],
            recorded_at=_stamp(ctx["recorded_at"]),
        )
        event = {
            k: str(choice[k])
            for k in (
                "id",
                "session_id",
                "project_id",
                "fact_id",
                "operation_id",
                "change_id",
            )
        }
        event.update(
            event_contract=EVENT_CONTRACT,
            source_kind=choice["source_kind"],
            fact_version=choice["fact_version"],
            effect_slot=choice["effect_slot"],
            classification=labels,
            statement_citations=[cite],
            selection=dict(
                id=str(choice["selection_id"]),
                source_kind="explicit_ui_selection",
                classification=choice["selection"],
            ),
            authentication_context=auth,
            recorded_validation=dict(
                contract=choice["validator_contract"],
                status="eligible_candidate",
                code=choice["validation_result"],
            ),
            recorded_at=_stamp(choice["recorded_at"]),
        )
        views.append(
            dict(
                read_contract=READ_CONTRACT,
                scope=SCOPE,
                subject=subject,
                turns=[
                    dict(
                        source_kind="conversation_turn",
                        id=str(turn["id"]),
                        session_id=str(turn["session_id"]),
                        project_id=str(choice["project_id"]),
                        role=turn["role"],
                        content=turn["content"],
                    )
                ],
                text_provenance=dict(original=[cite], current=[cite]),
                basis=dict(status="event_recorded", event=event),
            )
        )
    checked = parse_batch(views)
    if checked.status != "parsed_candidate":
        raise Refused("reference_projection_unavailable")
    # Even a real DB source does not turn structural parsing into a claim of
    # true facts, a human gesture, semantic independence or writer admission.
    return checked
