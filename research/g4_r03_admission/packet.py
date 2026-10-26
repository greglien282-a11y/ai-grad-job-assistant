"""Read-only review evidence from the reviewed full-history projector.

Does not decide that a claim is independent. No issuer, permit, writer or key.
The M2 family hints are reused unchanged, never upgraded to semantic proof.
"""

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from app import facts
from app.experience_read import Projection, raw
from app.read_permissions import check_reader
from app.typed_semantic_spike import validate_candidate
from app.maintenance_errors import ConversationError
from overnight_research.r03 import Claim, Source, Record, assess

CONTRACT = "g4-r03-review-packet-v1"


def review(factory, *, sid, pid, tid, token, request):
    denied = dict(
        status="unavailable",
        code="review_integrity_unavailable",
        truth_verified=False,
        persistence_authorized=False,
        semantic_independence="NOT_PROVEN",
    )
    try:
        with factory() as db:
            db.connection(
                execution_options={
                    "isolation_level": "REPEATABLE READ",
                    "postgresql_readonly": True,
                }
            )
            session = facts.authorize(db, sid, token)
            check_reader(db)
            if (
                set(request) != {"contract", "revision", "items"}
                or request["contract"] != CONTRACT
            ):
                return {**denied, "code": "review_contract_unsupported"}
            if (
                type(request["revision"]) is not int
                or request["revision"] != session.context_revision
            ):
                return {**denied, "code": "review_context_conflict"}
            p = Projection(db, session)
            if (
                pid not in {v.id for v in p.projects}
                or tid not in p.turn_map
                or p.turn_map[tid].role != "user"
            ):
                return {**denied, "code": "review_source_unavailable"}
            original = p.turn_map[tid]
            language = validate_candidate(
                dict(
                    validation_contract="typed-semantic-spike-v1",
                    synthetic=True,
                    raw_text=original.content,
                    items=request["items"],
                )
            )
            if language.status != "eligible_candidate":
                return {**denied, "code": "review_language_or_quote_refused"}
            conflicts = []
            for f in p.facts:
                changes = p.hist[f.id]
                snapshots = tuple(
                    (snap["statement"], snap["status"])
                    for c in changes
                    for snap in (c.before, c.after)
                    if snap is not None
                )
                rejected = [
                    snap
                    for c in changes
                    for snap in (c.before, c.after)
                    if snap is not None and snap["status"] == "rejected"
                ]
                if f.status != "rejected" and not rejected:
                    continue
                sources = []
                for src in p.orig[f.id]:
                    if src.citations:
                        sources.extend(
                            Source(str(src.turn_id), q["start"], q["end"])
                            for q in src.citations
                        )
                    else:
                        sources.append(Source(str(src.turn_id)))
                sources.extend(
                    Source(str(src.turn_id), src.start_cp, src.end_cp)
                    for src in p.audit[f.id]
                )
                record = Record(f.statement, f.status, snapshots, tuple(sources))
                labels = set()
                for item in request["items"]:
                    labels.update(
                        assess(
                            Claim(
                                item["quote"],
                                Source(str(tid), item["start"], item["end"]),
                            ),
                            (record,),
                        ).labels
                    )
                known = bool(
                    labels & {"EXACT_REUSE", "SOURCE_REUSE", "SEMANTICALLY_SUSPECTED"}
                )
                conflicts.append(
                    dict(
                        fact_id=str(f.id),
                        version=f.version,
                        reason=(
                            "known_reassertion_risk"
                            if known
                            else "distinct_literal_source_argument_only"
                        ),
                        labels=sorted(labels),
                        rejected_snapshots=rejected,
                        history=[raw(c) for c in changes],
                        original_sources=[raw(s) for s in p.orig[f.id]],
                        change_sources=[raw(s) for s in p.audit[f.id]],
                    )
                )
            # Full validated saved Turn and history are review material, not a
            # transferable proof usable by G4 issuer/writer. No token in result.
            return dict(
                status="requires_review",
                code="independent_decision_not_authorized",
                contract=CONTRACT,
                revision=session.context_revision,
                original=raw(original),
                items=request["items"],
                conflicts=conflicts,
                source_binding="VALIDATED_SAVED_USER_TURN",
                history_binding="VALIDATED_FULL_PROJECTION",
                language="finite_rule_match",
                semantic_independence="NOT_PROVEN",
                truth_verified=False,
                persistence_authorized=False,
            )
    except PermissionError:
        return {**denied, "code": "session_unavailable"}
    except (ConversationError, SQLAlchemyError, KeyError, TypeError, ValueError):
        return denied
