"""TEST SUPPORT ONLY: no API registration, credentials, ledger or live transport.

Exercises the existing mining executor with an exact HTTPX MockTransport. This
is not a production Provider admission path or evidence of real model quality.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx

from app.cost_ledger import canonical
from app.deepseek_contract import decode_official, ProbeError
from app.deepseek_transport import DeepSeekOfficialTransport
from app.mining import MiningError
from app.mining_context import MiningContext, PRIVATE, within_budget
from app.mining_validation import validate_context_v2
from app.model_adapter import Adapter, Profile

ROOT = Path(__file__).resolve().parents[3]
REQUEST_VERSION = 'deepseek-mining-integration-v1-offline'


@dataclass(frozen=True, repr=False)
class BoundRequest:
    body: bytes
    request_sha: str
    prompt_sha: str
    version: str = REQUEST_VERSION


def build_request(context):
    """Only bounded payload; never MiningInput.content or session credentials.

    Deliberately reuses the v2.1 OFFLINE prompt, including its disclosed example
    contamination. This new dynamic request version is NOT allowlisted for live
    dispatch and does not mutate any historical request/prompt/profile.
    """
    if type(context) is not MiningContext or not within_budget(context):
        raise ValueError('offline_context_invalid')
    texts = [t.content for t in context.user_turns] + [q.content or '' for q in context.questions] + [f.statement or '' for f in context.facts]
    if any(PRIVATE.search(value) for value in texts):
        raise ValueError('offline_context_not_minimized')
    profile = Profile.model_validate(json.loads(
        (ROOT / 'docs/evaluation/m12c2-profile-drafts.json').read_text(encoding='utf-8'))['profiles'][0])
    wire = json.loads((ROOT / 'docs/evaluation/provider-wire-output.schema.json').read_text(encoding='utf-8'))
    request = Adapter(profile, wire).build_request(context)
    prompt = (ROOT / 'docs/evaluation/s03b-prompt-v2.txt').read_text(encoding='utf-8').rstrip()
    request['messages'][0]['content'] = prompt + '\n输出 Schema：\n' + canonical(wire)
    body = canonical(request).encode('utf-8')
    return BoundRequest(body, hashlib.sha256(body).hexdigest(), hashlib.sha256(prompt.encode('utf-8')).hexdigest())


class OfflineDeepSeekMining:
    output_contract_version = 2

    def __init__(self, wire):
        if type(wire) is not httpx.MockTransport:
            raise ValueError('offline_mock_required')
        self.wire = wire
        self.request = None
        self.calls = 0
        self.safe_code = None
        self.usage = None

    def reserve_cost(self):
        # Even accidental injection into the HTTP dependency cannot pass the
        # existing gate. Do not impersonate scripted/synthetic for admission.
        raise MiningError(503, 'ai_provider_unapproved')

    async def mine(self, input):
        request = build_request(input.context)
        self.request = request
        self.calls += 1
        try:
            # Fake constant is internal to the old offline-only transport;
            # there is no secret resolver, paid control or live client here.
            from app.deepseek_contract import FAKE_SECRET
            raw = await DeepSeekOfficialTransport()._post_once(request.body, FAKE_SECRET, self.wire)
            envelope = decode_official(raw, SimpleNamespace(input_upper_bound=12000, output_cap=1200))
            self.usage = envelope.usage
            return validate_context_v2(input.context, envelope.output)
        except ProbeError as error:
            # No raw response or supplier-controlled error text retained.
            code = str(error)
            self.safe_code = code if code in {'timeout', 'transport_error', 'truncated', 'http_429', 'http_5xx',
                'http_4xx', 'redirect_refused', 'body_too_large', 'model_drift', 'refused', 'unexpected_mode',
                'usage_exceeded', 'response_invalid'} else 'offline_output_invalid'
            if self.safe_code in {'timeout', 'transport_error', 'http_429', 'http_5xx', 'http_4xx'}:
                raise TimeoutError('offline_outcome_unknown') from None
            raise ValueError('offline_output_invalid') from None
        except ValueError:
            self.safe_code = 'offline_source_or_schema_invalid'
            raise ValueError('offline_source_or_schema_invalid') from None
