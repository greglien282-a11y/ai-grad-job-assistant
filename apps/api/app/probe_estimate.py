"""Pinned PUBLIC tokenizer data only. Never executes remote Python/templates."""
import hashlib
import io
import zipfile

from tokenizers import Tokenizer

from app.controlled_probe import TOKENIZER_ARCHIVE_SHA, verify_bytes
from app.deepseek_contract import ProbeError


def count_json(tokenizer_json, body):
    # Raw request JSON is deliberately NOT described as supplier framing.
    tokenizer=Tokenizer.from_str(tokenizer_json)
    return len(tokenizer.encode(body.decode('utf8'),add_special_tokens=True).ids)


def estimate(archive_path, body):
    verify_bytes(body)
    with open(archive_path,'rb') as file: data=file.read(4_000_001)
    if len(data)>4_000_000 or hashlib.sha256(data).hexdigest()!=TOKENIZER_ARCHIVE_SHA:
        raise ProbeError('controlled_tokenizer_archive_changed')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        name='deepseek_v4_tokenizer/tokenizer.json'
        if archive.getinfo(name).file_size>20_000_000:raise ProbeError('controlled_tokenizer_too_large')
        # Read data member, no extraction, trust_remote_code or network lookup.
        return count_json(archive.read(name).decode('utf8'),body)
