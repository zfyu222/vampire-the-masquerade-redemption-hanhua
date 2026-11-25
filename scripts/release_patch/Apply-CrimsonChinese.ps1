param(
    [string]$Game,
    [switch]$Uninstall
)
$ErrorActionPreference = 'Stop'
if (-not $Game) { $Game = Split-Path -Parent $PSScriptRoot }
$gamePath = (Get-Item -LiteralPath $Game).FullName
$exe = Join-Path $gamePath 'Vampire.exe'
$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'manifest.json') -Raw | ConvertFrom-Json
$backup = Join-Path $gamePath '.CrimsonChineseBackup'
$receipt = Join-Path $backup 'state.json'

function Hash([string]$Path) {
    if (-not [IO.File]::Exists($Path)) { return '' }
    $sha = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($Path)
    try { [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '') }
    finally { $stream.Dispose(); $sha.Dispose() }
}

function Copy-Atomic([string]$Source, [string]$Target) {
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Target)) | Out-Null
    $pending = "$Target.chinese-$([guid]::NewGuid().ToString('N')).tmp"
    [IO.File]::Copy($Source, $pending)
    if ([IO.File]::Exists($Target)) {
        [IO.File]::Replace($pending, $Target, "$pending.old")
        [IO.File]::Delete("$pending.old")
    } else { [IO.File]::Move($pending, $Target) }
}

if ((Hash $exe) -ne $manifest.executable) { throw 'Install VTMR Crimson Edition 1.0 (standard 16:9 profile) first.' }
if (Get-Process Vampire -ErrorAction SilentlyContinue) { throw 'Exit the game before applying the Chinese patch.' }
[IO.Directory]::CreateDirectory($backup) | Out-Null
$lock = [IO.File]::Open((Join-Path $backup 'install.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
try {
    if ($Uninstall) {
        if (-not [IO.File]::Exists($receipt)) { Write-Output 'Chinese patch is already uninstalled.'; return }
        $entries = Get-Content -LiteralPath $receipt -Raw | ConvertFrom-Json
        foreach ($entry in $entries) {
            $target = Join-Path $gamePath $entry.name
            $original = Join-Path $backup $entry.name
            if ((Hash $target) -notin @($entry.before, $entry.after, $entry.previous) -or
                ($entry.before -and (Hash $original) -ne $entry.before)) { throw "File changed or backup missing: $($entry.name)" }
        }
        foreach ($entry in $entries) {
            $target = Join-Path $gamePath $entry.name
            if ($entry.before) {
                if ((Hash $target) -ne $entry.before) { Copy-Atomic (Join-Path $backup $entry.name) $target }
            } else { [IO.File]::Delete($target) }
            if ((Hash $target) -ne $entry.before) { throw "Restore failed: $target" }
        }
        [IO.File]::Delete($receipt)
        Write-Output 'Crimson Chinese patch uninstalled.'
        return
    }

    $stage = Join-Path $backup ([guid]::NewGuid().ToString('N'))
    Add-Type -Path (Join-Path $PSScriptRoot 'Delta.cs')
    $owned = [ordered]@{}
    if ([IO.File]::Exists($receipt)) {
        foreach ($entry in (Get-Content -LiteralPath $receipt -Raw | ConvertFrom-Json)) {
            $owned[$entry.name] = $entry
        }
    }
    $changes = @()
    foreach ($entry in $manifest.files) {
        $target = Join-Path $gamePath $entry.name
        $before = Hash $target
        if ($before -eq $entry.target) { continue }
        $prior = $owned[$entry.name]
        if ($prior -and $before -notin @($prior.before, $prior.after, $prior.previous)) {
            throw "Installed file differs: $($entry.name)"
        }
        $fromLegacy = $entry.upgrade -and $before -eq $entry.upgrade.source
        if (-not $fromLegacy -and $before -notin @($entry.sources)) { throw "Unexpected original file: $($entry.name)" }
        $changes += [pscustomobject]@{name=$entry.name; before=$before; after=$entry.target}
        if (-not $entry.target) { continue }
        $step = if ($fromLegacy) { $entry.upgrade } else { $entry }
        $payload = Join-Path $PSScriptRoot $step.payload
        if ((Hash $payload) -ne $step.payload_sha256) { throw "Patch data failed verification: $($step.payload)" }
        $prepared = Join-Path $stage $entry.name
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($prepared)) | Out-Null
        if ($entry.delta -and -not $fromLegacy -and $entry.next) {
            $intermediate = "$prepared.intermediate"
            [RedemptionDelta]::Run($target, $payload, $intermediate, $false)
            $followup = Join-Path $PSScriptRoot $entry.next.payload
            if ((Hash $intermediate) -ne $entry.next.source -or
                (Hash $followup) -ne $entry.next.payload_sha256) { throw "Invalid intermediate: $($entry.name)" }
            [RedemptionDelta]::Run($intermediate, $followup, $prepared, $false)
            [IO.File]::Delete($intermediate)
        } elseif ($entry.delta) { [RedemptionDelta]::Run($target, $payload, $prepared, $false) }
        else { [IO.File]::Copy($payload, $prepared) }
        if ((Hash $prepared) -ne $entry.target) { throw "Patched file failed verification: $($entry.name)" }
    }
    if ($changes.Count) {
        foreach ($entry in $changes) {
            $prior = $owned[$entry.name]
            if ($prior) {
                $original = $prior.before
                if ($original -and (Hash (Join-Path $backup $entry.name)) -ne $original) {
                    throw "Original backup failed verification: $($entry.name)"
                }
            } else {
                $original = $entry.before
                if ($original) { Copy-Atomic (Join-Path $gamePath $entry.name) (Join-Path $backup $entry.name) }
            }
            $owned[$entry.name] = @{name=$entry.name; before=$original; previous=$entry.before; after=$entry.after}
        }
        $pending = Join-Path $stage 'state.json'
        [IO.Directory]::CreateDirectory($stage) | Out-Null
        ConvertTo-Json -InputObject @($owned.Values) -Depth 4 | Set-Content -LiteralPath $pending -Encoding UTF8
        Copy-Atomic $pending $receipt
        [IO.File]::Delete($pending)
        foreach ($entry in $changes) {
            $target = Join-Path $gamePath $entry.name
            if ((Hash $target) -ne $entry.before) { throw "Target changed during install: $target" }
            if ($entry.after) { Copy-Atomic (Join-Path $stage $entry.name) $target }
            else { [IO.File]::Delete($target) }
            if ((Hash $target) -ne $entry.after) { throw "Install failed: $target" }
            if ($entry.after) { [IO.File]::Delete((Join-Path $stage $entry.name)) }
        }
    }
    Write-Output 'Crimson Chinese patch verified. Start the game as usual.'
} finally { $lock.Dispose() }
