import { existsSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { randomUUID } from 'node:crypto'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
const local = path.join(root, 'apps/api/.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
const python = process.env.PATHWISE_E2E_PYTHON || (existsSync(local) ? local : '')
if (!python) throw new Error('Python 3.12 environment required; no fallback interpreter')
mkdirSync(path.join(root, '.e2e'), { recursive: true })
const stopFile = path.join(root, '.e2e', `stop_${randomUUID()}`)
const child = spawn(python, [path.join(root, 'apps/web/e2e/environment.py'), ...process.argv.slice(2)], {
  cwd: root, stdio: 'inherit', windowsHide: true,
  env: { ...process.env, PATHWISE_E2E_NODE: process.execPath, PATHWISE_E2E_STOP_FILE: stopFile },
})
child.on('error', () => { console.error('E2E launcher could not start'); process.exitCode = 1 })
child.on('exit', code => { rmSync(stopFile, { force: true }); process.exitCode = code ?? 1 })
// Windows child.kill('SIGINT') terminates immediately and bypasses Python cleanup.
process.on('SIGINT', () => writeFileSync(stopFile, 'stop'))
