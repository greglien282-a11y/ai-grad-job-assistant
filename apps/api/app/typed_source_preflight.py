"""Unrouted synthetic read-only experiment. No persistence or truth authority.

The explicit factory is test infrastructure, not a configurable runtime factory.
All results expire with their snapshot; none is a token usable by a writer.
"""
from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import facts
from app.experience_read import Projection
from app.maintenance_errors import ConversationError
from app.read_permissions import check_reader
from app.typed_semantic_spike import CONTRACT as LANGUAGE_CONTRACT, validate_candidate

CONTRACT = 'typed-source-preflight-v1'


@dataclass(frozen=True)
class Result:
    status: str
    code: str
    source_binding: str = 'not_checked'
    language_status: str = 'not_checked'
    language_code: str = 'not_checked'
    history_status: str = 'not_checked'
    history_flags: tuple[str, ...] = ()
    context_revision: int | None = None
    preflight_contract: str = CONTRACT
    semantic_independence: str = 'unproven'
    transaction_review_required: bool = True
    truth_verified: bool = False
    persistence_authorized: bool = False


def preflight(factory, *, session_id: UUID, project_id: UUID, turn_id: UUID,
              token: str, request: object) -> Result:
    """Bind caller quotes to one saved User Turn on an authenticated snapshot.

    No raw_text parameter, operation key, default factory, HTTP or side effect.
    synthetic=true is a scope declaration, never proof that data is synthetic.
    """
    try:
        with factory() as db:
            db.connection(execution_options={
                'isolation_level': 'REPEATABLE READ', 'postgresql_readonly': True})
            if (db.scalar(text('SHOW transaction_read_only')) != 'on'
                    or db.scalar(text('SHOW transaction_isolation')) != 'repeatable read'):
                return Result('permission_rejected', 'readonly_identity_required')
            if type(session_id) is not UUID or type(token) is not str or not token:
                return Result('authorization_denied', 'session_unavailable')
            session = facts.authorize(db, session_id, token)
            # Authentication precedes schema, candidate/version and typed disclosure.
            check_reader(db)
            if (type(request) is not dict or set(request) != {
                    'preflight_contract', 'synthetic', 'context_revision', 'items'}):
                return Result('rejected', 'request_invalid')
            if type(request['preflight_contract']) is not str or request['preflight_contract'] != CONTRACT:
                return Result('version_rejected', 'preflight_contract_unsupported')
            if request['synthetic'] is not True:
                return Result('rejected', 'synthetic_input_required')
            revision = request['context_revision']
            if type(revision) is not int or revision < 1:
                return Result('rejected', 'context_revision_invalid')
            if revision != session.context_revision:
                return Result('version_rejected', 'context_revision_conflict')
            projection = Projection(db, session)
            if (type(project_id) is not UUID or type(turn_id) is not UUID
                    or project_id not in {p.id for p in projection.projects}
                    or turn_id not in projection.turn_map):
                return Result('source_rejected', 'source_unavailable')
            turn = projection.turn_map[turn_id]
            if turn.role != 'user':
                return Result('source_rejected', 'user_turn_required')
            # Only the database supplies raw_text. The unchanged c3a function
            # validates exact CP slices, whole sentences, coverage and language.
            language = validate_candidate(dict(validation_contract=LANGUAGE_CONTRACT,
                synthetic=True, raw_text=turn.content, items=request['items']))
            binding = 'bound' if language.citations_valid is True else 'not_bound'
            flags = set()
            snapshots = [snap for c in projection.history for snap in (c.before, c.after) if snap is not None]
            if any(f.status == 'rejected' for f in projection.facts):flags.add('current_rejected')
            if any(snap['status'] == 'rejected' for snap in snapshots):flags.add('historical_rejected')
            # Only inspect structurally validated quotes. Never normalize digits,
            # synonyms or regard a new Turn as proof of a new independent claim.
            if language.citations_valid is True:
                statements = {turn.content, *(item['quote'] for item in request['items'])}
                if statements & ({f.statement for f in projection.facts} | {s['statement'] for s in snapshots}):
                    flags.add('exact_text_reuse')
            if any(s.turn_id == turn_id for s in projection.sources):flags.add('original_source_reuse')
            if (any(s.turn_id == turn_id for s in projection.fcs)
                    or any(str(turn_id) in snap.get('source_turn_ids', [])
                           or str(turn_id) in snap.get('original_source_turn_ids', []) for snap in snapshots)):
                flags.add('historical_source_reuse')
            common = dict(source_binding=binding, language_status=language.status,
                language_code=language.code, history_flags=tuple(sorted(flags)),
                history_status='requires_review' if flags else 'independence_unproven',
                context_revision=session.context_revision)
            if language.status != 'eligible_candidate':
                return Result('candidate_rejected', 'language_or_quote_rejected', **common)
            if flags:
                return Result('requires_review', 'history_requires_review', **common)
            return Result('candidate_only', 'source_bound_finite_rule_match', **common)
    except PermissionError:
        return Result('authorization_denied', 'session_unavailable')
    except ConversationError as exc:
        if exc.code == 'experience_read_runtime_unapproved':
            return Result('permission_rejected', 'reader_identity_unapproved')
        return Result('integrity_unavailable', 'read_integrity_unavailable')
    except SQLAlchemyError as exc:
        if getattr(getattr(exc, 'orig', None), 'sqlstate', None) == '42501':
            return Result('permission_rejected', 'select_permission_required')
        return Result('integrity_unavailable', 'read_integrity_unavailable')
    except (ValidationError, KeyError, TypeError, ValueError):
        return Result('integrity_unavailable', 'read_integrity_unavailable')
