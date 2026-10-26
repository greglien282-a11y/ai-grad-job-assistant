"""Real existing HTTP/roles/migrations; explicit synthetic loopback URL only."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/api"))
sys.path.insert(0, str(ROOT / "apps/api/tests"))
from apps.api.tests.conftest import migrated_connection
from test_http_api import api
from test_maintenance_api import service
from test_append_api import append_service
from test_deepseek_mining_integration import offline_guard, test_database_only
from research.g4_trusted_boundary.conftest import boundary
from research.g3_choice_protocol.conftest import model
