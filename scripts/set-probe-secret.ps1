param(
  [Parameter(Mandatory=$true)][ValidatePattern('\A[A-Za-z0-9_-]{1,64}\z')][string]$AccountRef,
  [switch]$Rotate,
  [UInt64]$ExpectedRevision = 0
)
# Manual operator tool only. No key arguments, environment lookup or HTTP.
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class PathwiseCredential {
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
  public struct Credential {
    public UInt32 Flags, Type;
    public string TargetName, Comment;
    public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
    public UInt32 CredentialBlobSize;
    public IntPtr CredentialBlob;
    public UInt32 Persist, AttributeCount;
    public IntPtr Attributes;
    public string TargetAlias, UserName;
  }
  [DllImport("advapi32.dll", EntryPoint="CredWriteW", CharSet=CharSet.Unicode, SetLastError=true)]
  public static extern bool Write(ref Credential value, UInt32 flags);
  [DllImport("advapi32.dll", EntryPoint="CredReadW", CharSet=CharSet.Unicode, SetLastError=true)]
  public static extern bool Read(string target, UInt32 type, UInt32 flags, out IntPtr credential);
  [DllImport("advapi32.dll")] public static extern void CredFree(IntPtr ptr);
}
'@

function Assert-PathwiseInteractive {
  if ([Environment]::OSVersion.Platform -ne 'Win32NT' -or
      -not [Environment]::UserInteractive -or [Console]::IsInputRedirected) {
    throw 'controlled_interactive_windows_required'
  }
}

function Get-PathwiseLockName([string]$Target,[string]$Sid) {
  $sha = [Security.Cryptography.SHA256]::Create()
  try { $hash = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Sid+'|'+$Target.ToUpperInvariant()))).Replace('-','') }
  finally { $sha.Dispose() }
  return 'Global\PathwiseDeepSeekCredential_'+$hash
}

function Enter-PathwiseLock([string]$Target) {
  $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  $name = Get-PathwiseLockName $Target $sid
  $mutex = New-Object Threading.Mutex($false, $name)
  try {
    try { $acquired = $mutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] {
      $mutex.ReleaseMutex()
      throw 'controlled_secret_lock_abandoned'
    }
    if (-not $acquired) { throw 'controlled_secret_lock_busy' }
    return $mutex
  } catch { $mutex.Dispose(); throw }
}

function Exit-PathwiseLock($Mutex) {
  try { $Mutex.ReleaseMutex() } finally { $Mutex.Dispose() }
}

function Clear-PathwiseReadBuffer([IntPtr]$Pointer) {
  if ($Pointer -eq [IntPtr]::Zero) { return }
  try {
    $entry = [Runtime.InteropServices.Marshal]::PtrToStructure($Pointer,[type][PathwiseCredential+Credential])
    if ($entry.CredentialBlob -ne [IntPtr]::Zero) {
      for ($i=0; $i -lt $entry.CredentialBlobSize; $i++) {
        [Runtime.InteropServices.Marshal]::WriteByte($entry.CredentialBlob,$i,0)
      }
    }
  } finally { [PathwiseCredential]::CredFree($Pointer) }
}

function Get-PathwiseMetadata([string]$Target,[string]$Account) {
  $pointer = [IntPtr]::Zero
  try {
    if (-not [PathwiseCredential]::Read($Target,1,0,[ref]$pointer)) {
      $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
      if ($errorCode -eq 1168) { return $null }
      throw 'controlled_secret_access_failed'
    }
    if ($pointer -eq [IntPtr]::Zero) { throw 'controlled_secret_binding_changed' }
    $entry = [Runtime.InteropServices.Marshal]::PtrToStructure($pointer,[type][PathwiseCredential+Credential])
    if ($entry.Type -ne 1 -or $entry.TargetName -cne $Target -or $entry.UserName -cne $Account) {
      throw 'controlled_secret_binding_changed'
    }
    $high = [BitConverter]::ToUInt32([BitConverter]::GetBytes([int32]$entry.LastWritten.dwHighDateTime),0)
    $low = [BitConverter]::ToUInt32([BitConverter]::GetBytes([int32]$entry.LastWritten.dwLowDateTime),0)
    $revision = ([uint64]$high -shl 32) -bor $low
    if ($revision -eq 0) { throw 'controlled_secret_binding_changed' }
    # No decoding or copying the existing Key into a managed string.
    return @{revision=$revision; bytes=$entry.CredentialBlobSize}
  } finally { Clear-PathwiseReadBuffer $pointer }
}

function New-PathwisePointer($Secure) {
  return [Runtime.InteropServices.Marshal]::SecureStringToGlobalAllocUnicode($Secure)
}
function Clear-PathwisePointer([IntPtr]$Pointer) {
  [Runtime.InteropServices.Marshal]::ZeroFreeGlobalAllocUnicode($Pointer)
}
function Dispose-PathwiseSecure($Secure) { $Secure.Dispose() }

function Assert-PathwiseInput($Secure,[IntPtr]$Pointer) {
  if ($Secure.Length -lt 8 -or $Secure.Length -gt 1024 -or $Pointer -eq [IntPtr]::Zero) {
    throw 'controlled_secret_invalid'
  }
  for ($i=0; $i -lt $Secure.Length; $i++) {
    $code = [Runtime.InteropServices.Marshal]::ReadInt16($Pointer,$i*2)
    if ($code -lt 33 -or $code -gt 126) { throw 'controlled_secret_invalid' }
  }
}

function Write-PathwiseEntry([string]$Target,[string]$Account,$Secure,[IntPtr]$Pointer) {
  $entry = New-Object PathwiseCredential+Credential
  $entry.Type=1; $entry.TargetName=$Target; $entry.UserName=$Account
  $entry.CredentialBlobSize=$Secure.Length*2; $entry.CredentialBlob=$Pointer; $entry.Persist=2
  if (-not [PathwiseCredential]::Write([ref]$entry,0)) { throw 'controlled_secret_write_failed' }
}

function Invoke-PathwiseSecret([string]$Account,[bool]$Rotation,[UInt64]$Revision) {
  $mutex=$null; $secure=$null; $pointer=[IntPtr]::Zero
  $attempted=$false; $cleanupFailed=$false; $result=$null
  $target='Pathwise/DeepSeek/'+$Account
  try {
    if ($Account -cnotmatch '\A[A-Za-z0-9_-]{1,64}\z' -or ($Rotation -ne ($Revision -gt 0))) {
      throw 'controlled_secret_binding_changed'
    }
    Assert-PathwiseInteractive
    $mutex=Enter-PathwiseLock $target
    $old=Get-PathwiseMetadata $target $Account
    if ($Rotation) {
      if ($null -eq $old -or $old.revision -ne $Revision) { throw 'controlled_secret_binding_changed' }
      $confirmation=Read-Host "输入 ROTATE $Account $Revision 确认轮换"
      if ($confirmation -cne "ROTATE $Account $Revision") { throw 'controlled_confirmation_cancelled' }
    } elseif ($null -ne $old) { throw 'controlled_secret_exists' }
    $secure=Read-Host '仅在本机输入 Key（不回显）' -AsSecureString
    # Allocation is inside the cleanup scope: SecureString is disposed even on failure.
    $pointer=New-PathwisePointer $secure
    Assert-PathwiseInput $secure $pointer
    # Recheck immediately before write, while holding the cooperative mutex.
    $current=Get-PathwiseMetadata $target $Account
    if (($Rotation -and ($null -eq $current -or $current.revision -ne $Revision)) -or
        (-not $Rotation -and $null -ne $current)) { throw 'controlled_secret_binding_changed' }
    # CredWrite has no atomic create-if-absent/CAS. Non-cooperating same-user
    # processes remain a trust boundary despite the mutex and second check.
    $attempted=$true
    Write-PathwiseEntry $target $Account $secure $pointer
    $saved=Get-PathwiseMetadata $target $Account
    if ($null -eq $saved -or $saved.bytes -ne $secure.Length*2 -or
        ($Rotation -and $saved.revision -eq $Revision)) { throw 'controlled_secret_binding_changed' }
    $result=@{status='stored'; secret_ref=$target; secret_revision=$saved.revision; account_ref=$Account}
  } catch {
    $code='controlled_secret_stopped'
    $allowed=@('controlled_interactive_windows_required','controlled_secret_lock_abandoned',
      'controlled_secret_lock_busy','controlled_secret_access_failed','controlled_secret_binding_changed',
      'controlled_confirmation_cancelled','controlled_secret_exists','controlled_secret_invalid')
    if ($allowed -ccontains $_.Exception.Message) { $code=$_.Exception.Message }
    $result=@{status=$(if($attempted){'outcome_unknown'}else{'stopped'}); safe_code=$code;
      automatic_retry=$false; instruction='stop_and_review'}
  } finally {
    # Independent nested cleanup: failure of one resource cannot skip the rest.
    try {
      if ($pointer -ne [IntPtr]::Zero) { Clear-PathwisePointer $pointer }
    } catch { $cleanupFailed=$true }
    finally {
      try { if ($null -ne $secure) { Dispose-PathwiseSecure $secure } }
      catch { $cleanupFailed=$true }
      finally {
        try { if ($null -ne $mutex) { Exit-PathwiseLock $mutex } }
        catch { $cleanupFailed=$true }
      }
    }
  }
  if ($cleanupFailed) {
    $result=@{status=$(if($attempted){'outcome_unknown'}else{'stopped'});
      safe_code='controlled_secret_cleanup_failed'; automatic_retry=$false; instruction='stop_and_review'}
  }
  return $result
}

$result=Invoke-PathwiseSecret $AccountRef ([bool]$Rotate) $ExpectedRevision
$result | ConvertTo-Json -Compress
if ($result.status -ne 'stored') { exit 2 }
