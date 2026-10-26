"""Actual separate PIDs/private JSON pipes. No production identity or sandbox."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from queue import Queue, Empty
import subprocess
import sys
from threading import Lock, Thread
from research.g3_choice_protocol.runtime import Refused
from research.g4_source_binding.binding import Origin
from research.g4_trusted_boundary.runtime import Proof
from research.g4_0e_hardening.execution_pin import inventory, ROOT

EXTRA = ('research/g4_0f_demo/services.py','research/g4_0f_demo/worker.py','research/g4_0f_demo/audit.py','research/g4_0f_demo/server.py','research/g4_disposable_demo/server.py')
def manifest():
    return {'base':inventory(), 'integrated':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in EXTRA}}
def execution_hash(value=None):
    return hashlib.sha256(json.dumps(value or manifest(),sort_keys=True,separators=(',',':')).encode()).hexdigest()


class Service:
    def __init__(self, setup):
        self.process = subprocess.Popen([sys.executable,'-B',str(Path(__file__).with_name('worker.py'))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf8')
        self.queue = Queue(); self.lock = Lock()
        def pump():
            for line in self.process.stdout: self.queue.put(line)
            self.queue.put('')
        self.pump=Thread(target=pump,daemon=True); self.pump.start()
        try:
            self.process.stdin.write(json.dumps(setup)+'\n'); self.process.stdin.flush()
            if self._receive() != {'ready':True}: raise Refused('trusted_validator_unavailable')
        except Exception:
            self.close(); raise

    def _receive(self):
        try:
            line = self.queue.get(timeout=5)
            if not line: raise ValueError()
            return json.loads(line)
        except (Empty, ValueError):
            if self.process.poll() is None: self.process.kill()
            raise Refused('trusted_validator_unavailable') from None

    def request(self, payload):
        with self.lock:
            try:
                self.process.stdin.write(json.dumps(payload)+'\n'); self.process.stdin.flush()
                value = self._receive()
                if 'error' in value: raise Refused(value['error'])
                return value
            except (OSError, ValueError): raise Refused('trusted_validator_unavailable') from None

    def close(self):
        if self.process.poll() is None: self.process.kill()
        self.process.wait(timeout=10)
        self.pump.join(timeout=1)
        try: self.process.stdin.close()
        except OSError as exc:
            if exc.errno not in (22,32): raise
        self.process.stdout.close()


class IngressService(Service):
    def capture(self, key, body):
        result = self.request({'key':key,'body':body})
        return Origin(**{**result,'mac':bytes.fromhex(result['mac'])})


class SignerService(Service):
    def issue(self, graph, source):
        result = self.request({'seal':graph,'source':{**asdict(source),'mac':source.mac.hex()}})
        return Proof(**{**result,'mac':bytes.fromhex(result['mac'])})
