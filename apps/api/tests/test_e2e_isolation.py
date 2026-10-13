import importlib.util
from pathlib import Path

import pytest

path = Path(__file__).parents[2] / 'web/e2e/environment.py'
spec = importlib.util.spec_from_file_location('e2e_environment', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize('url', [None, '', 'sqlite:///test.db',
    'postgresql://pathwise_dev:x@127.0.0.1/pathwise_dev',
    'postgresql://pathwise_test:x@127.0.0.1/pathwise_dev',
    'postgresql://postgres:x@127.0.0.1/pathwise_test',
    'postgresql://pathwise_test:x@remote.example/pathwise_test',
    'postgresql://pathwise_test:x@127.0.0.1/pathwise_test?options=-csearch_path=public',
])
def test_e2e_refuses_unsafe_database_without_connecting(url):
    with pytest.raises(ValueError):
        module.validate_url(url)


def test_e2e_accepts_explicit_loopback_non_admin_test_database():
    url = module.validate_url('postgresql://pathwise_test:synthetic@127.0.0.1/pathwise_test')
    assert url.database == 'pathwise_test' and url.drivername == 'postgresql+psycopg'
