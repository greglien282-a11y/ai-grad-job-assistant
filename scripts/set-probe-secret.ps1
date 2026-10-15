param([Parameter(Mandatory=$true)][ValidatePattern('^[a-zA-Z0-9_-]{1,64}$')][string]$AccountRef)
# Run manually ONLY after review and explicit local key-configuration approval.
# No key command-line parameter, env lookup, plaintext file or network request.
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
$secure = Read-Host '仅在本机输入 DeepSeek Key（不回显，不粘贴到聊天）' -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToGlobalAllocUnicode($secure)
$readPointer = [IntPtr]::Zero
try {
  if ($secure.Length -lt 8 -or $secure.Length -gt 1024) { throw 'Invalid credential length' }
  $credential = New-Object PathwiseCredential+Credential
  $credential.Type = 1
  $credential.TargetName = "Pathwise/DeepSeek/$AccountRef"
  $credential.UserName = $AccountRef
  $credential.CredentialBlobSize = $secure.Length * 2
  $credential.CredentialBlob = $pointer
  $credential.Persist = 2
  if (-not [PathwiseCredential]::Write([ref]$credential,0)) { throw 'Credential write failed' }
  if (-not [PathwiseCredential]::Read($credential.TargetName,1,0,[ref]$readPointer)) { throw 'Credential metadata unavailable' }
  $saved = [Runtime.InteropServices.Marshal]::PtrToStructure($readPointer,[type][PathwiseCredential+Credential])
  $high = [BitConverter]::ToUInt32([BitConverter]::GetBytes([int32]$saved.LastWritten.dwHighDateTime),0)
  $low = [BitConverter]::ToUInt32([BitConverter]::GetBytes([int32]$saved.LastWritten.dwLowDateTime),0)
  $revision = ([uint64]$high -shl 32) -bor $low
  @{secret_ref=$credential.TargetName; secret_revision=$revision; account_ref=$AccountRef} | ConvertTo-Json
} finally {
  if ($readPointer -ne [IntPtr]::Zero) {
    $copy = [Runtime.InteropServices.Marshal]::PtrToStructure($readPointer,[type][PathwiseCredential+Credential])
    for ($index = 0; $index -lt $copy.CredentialBlobSize; $index++) {
      [Runtime.InteropServices.Marshal]::WriteByte($copy.CredentialBlob,$index,0)
    }
    [PathwiseCredential]::CredFree($readPointer)
  }
  [Runtime.InteropServices.Marshal]::ZeroFreeGlobalAllocUnicode($pointer)
  $secure.Dispose()
}
