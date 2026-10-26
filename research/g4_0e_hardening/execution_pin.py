"""Finite research execution inventory, not supply-chain attestation.

Provisioner supplies the approved inventory; never learn it in a request.
Callable pins detect the tested accidental/in-process substitution only. A root
that changes both this check and execution can still forge. No code sandbox.
"""
import hashlib
import marshal
from pathlib import Path
import platform
from research.g3_choice_protocol.runtime import Refused
import research.g3_choice_protocol.runtime as graph
import research.g4_trusted_boundary.runtime as boundary
import research.g4_source_binding.binding as binding

ROOT = Path(__file__).resolve().parents[2]
FILES = ('apps/api/app/typed_semantic_spike.py', 'research/g3_choice_protocol/runtime.py',
    'research/g3_choice_protocol/schema.sql', 'research/g4_trusted_boundary/runtime.py',
    'research/g4_trusted_boundary/schema.sql', 'research/g4_source_binding/binding.py',
    'research/g4_0e_hardening/guard.py', 'research/g4_0e_hardening/execution_pin.py')


def inventory(root=ROOT):
    return {'python': platform.python_version(), 'files': {p: hashlib.sha256((root/p).read_bytes()).hexdigest() for p in FILES}}


def callables():
    return (binding.BoundIssuer.issue, binding.Ingress.capture, boundary.Issuer.issue,
        boundary.semantic.validate_candidate, graph.validate_candidate, graph.apply)


class ExecutionPin:
    def __init__(self, approved, loaded=None):
        self.approved = approved
        self.loaded = loaded if loaded is not None else tuple(hashlib.sha256(marshal.dumps(fn.__code__)).hexdigest() for fn in callables())

    def verify(self, root=ROOT):
        now = tuple(hashlib.sha256(marshal.dumps(fn.__code__)).hexdigest() for fn in callables())
        if inventory(root) != self.approved or now != self.loaded:
            raise Refused('execution_chain_unapproved')
