"""Clean local PowerShell 5.1 host; no inherited provider credentials/profile."""
import base64
import os
from pathlib import Path
import subprocess


def powershell(code):
    env={k:os.environ[k] for k in ('SystemRoot','SystemDrive','TEMP','TMP','USERPROFILE','LOCALAPPDATA','APPDATA','COMSPEC','PATH') if k in os.environ}
    home=Path(env['SystemRoot'])/'System32/WindowsPowerShell/v1.0'
    # A parent PowerShell7 PSModulePath can break Security in a 5.1 child.
    env['PSModulePath']=str(home/'Modules')
    return subprocess.run([str(home/'powershell.exe'),'-NoProfile','-NonInteractive','-EncodedCommand',
        base64.b64encode(code.encode('utf-16-le')).decode('ascii')],env=env,capture_output=True)
