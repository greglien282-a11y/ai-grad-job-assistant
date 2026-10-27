"""Public UI samples match the frozen finite rule; this is NOT a trusted reader."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'apps/api'))
from app.typed_semantic_spike import CONTRACT, validate_candidate


def test_public_typed_samples_replay_existing_finite_rule_without_new_templates():
    text = (ROOT / 'apps/web/src/features/jd-lab/fixtures.ts').read_text(encoding='utf8')
    samples = re.findall(r"sample\(\d+, '([^']+)'(?:, '([^']+)', '([^']+)')?", text)
    assert len(samples) == 10
    checked = 0
    for quote, kind, stage in samples:
        if kind == 'legacy_unspecified':
            continue
        result = validate_candidate({'validation_contract': CONTRACT, 'synthetic': True, 'raw_text': quote,
            'items': [{'fact_kind': kind or 'personal_action', 'progress_stage': stage or 'completed',
                'classification_contract': 'explicit-typed-v1', 'quote': quote, 'start': 0, 'end': len(quote)}]})
        assert result.status == 'eligible_candidate', (quote, result)
        assert result.truth_verified is False and result.persistence_authorized is False
        checked += 1
    assert checked == 9
