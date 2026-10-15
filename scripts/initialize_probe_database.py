"""Future explicit Windows operator tool. Development/CI must never run live."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps/api'))
from app.probe_db_bootstrap import initialize, recovery_admin
from app.probe_db_credentials import WindowsDatabaseVault, initialization_mutex, local_private_io


def main():
    parser=argparse.ArgumentParser(description='仅初始化本机 pathwise_probe；无迁移、无收费授权。')
    parser.add_argument('--credential-status', action='store_true',
        help='只读查看两个固定 DB 凭据引用/revision，不连接数据库，不读取恢复文件。')
    args=parser.parse_args()
    # No --yes, configurable target, redirected stdin or environment enable flag.
    if os.name != 'nt' or not sys.stdin.isatty() or not sys.stdout.isatty():
        print('stopped: interactive_windows_terminal_required')
        return 2
    if args.credential_status:
        try:
            from app.probe_db_credentials import ROLES
            with local_private_io(), initialization_mutex():
                vault=WindowsDatabaseVault()
                print(json.dumps({'database_credentials': {role: vault.metadata(role) for role in ROLES}},indent=2))
            return 0
        except BaseException:
            print('stopped: credential_status_unavailable; no database operation')
            return 2
    print('将创建 pathwise_probe、pathwise_probe_owner、pathwise_probe_runner。')
    print('自动生成两个独立随机密码，仅保存到当前用户 Windows Credential Manager。')
    print('部分失败将保留已完成对象和凭据，不自动清理；本工具不执行迁移或收费授权。')
    try:
        with local_private_io(), initialization_mutex():
            path = Path(__file__).resolve().parents[1] / 'apps/api/.venv/postgresql-local.json'
            with recovery_admin(path) as admin:
                result = initialize(admin, WindowsDatabaseVault(),
                    lambda phrase: input('确认时完整输入 ' + phrase + ': ').strip() == phrase)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['success'] else 2
    except BaseException:
        print('stopped: local_operator_failed; 状态需人工核验；不要重试、删除对象或修改凭据及认证规则。')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
