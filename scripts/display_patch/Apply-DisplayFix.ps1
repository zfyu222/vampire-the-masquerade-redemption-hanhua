[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('Install', 'Uninstall')][string]$Action,
    [string]$Game
)

$ErrorActionPreference = 'Stop'
if (-not $Game) { $Game = Split-Path -Parent $PSScriptRoot }
$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'DisplayFixManifest.json') -Raw | ConvertFrom-Json
$gamePath = (Get-Item -LiteralPath $Game).FullName
$exe = Join-Path $gamePath 'Vampire.exe'
$stateDir = Join-Path $gamePath '.RedemptionDisplayFix'
$receipt = Join-Path $stateDir 'state.json'
$registryPath = 'Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers'

function Get-Hash([string]$Path) {
    if (-not [IO.File]::Exists($Path)) { return '' }
    $stream = [IO.File]::OpenRead($Path)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        return [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-', '')
    } finally {
        $hasher.Dispose()
        $stream.Dispose()
    }
}

function Copy-Verified([string]$Source, [string]$Destination, [string]$ExpectedHash) {
    $temp = "$Destination.displayfix-$([guid]::NewGuid().ToString('N')).tmp"
    $replaced = "$temp.previous"
    try {
        [IO.File]::Copy($Source, $temp)
        if ((Get-Hash $temp) -ne $ExpectedHash) { throw "Copy verification failed: $Source" }
        if (Test-Path -LiteralPath $Destination) {
            [IO.File]::Replace($temp, $Destination, $replaced)
        } else {
            [IO.File]::Move($temp, $Destination)
        }
    } finally {
        if ([IO.File]::Exists($temp)) { [IO.File]::Delete($temp) }
        if ([IO.File]::Exists($replaced)) { [IO.File]::Delete($replaced) }
    }
}

if ((Get-Hash $exe) -ne $manifest.game.exe_sha256 -or
    (Get-Hash (Join-Path $gamePath 'rlDirect.dll')) -ne $manifest.game.renderer_sha256) {
    throw 'This folder does not contain the supported Steam build. Extract the ZIP next to Vampire.exe.'
}

$sha = [Security.Cryptography.SHA256]::Create()
try {
    $lockHash = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($exe.ToUpperInvariant()))
} finally {
    $sha.Dispose()
}
$lockName = 'Local\RedemptionDisplayFix-' + [BitConverter]::ToString($lockHash).Replace('-', '')
$lock = [Threading.Mutex]::new($false, $lockName)
$locked = $false
try {
    try { $locked = $lock.WaitOne(0) } catch [Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { throw 'Another display patch installer is running.' }
    $running = Get-Process -Name Vampire -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $exe -or -not $_.Path }
    if ($running) { throw 'Exit Vampire before running the display patch installer.' }
    if ($Action -eq 'Uninstall' -and -not (Test-Path -LiteralPath $receipt)) {
        Write-Output 'Display patch is already uninstalled.'
        return
    }

    $layers = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($registryPath)
    try {
        $dpiBefore = $layers.GetValue($exe)
        if ($null -ne $dpiBefore -and $layers.GetValueKind($exe) -ne [Microsoft.Win32.RegistryValueKind]::String) {
            throw 'The existing Windows compatibility entry is not a string.'
        }

        if (Test-Path -LiteralPath $receipt) {
            $state = Get-Content -LiteralPath $receipt -Raw | ConvertFrom-Json
            if ($state.version -ne $manifest.version -or $state.user -ne [Security.Principal.WindowsIdentity]::GetCurrent().User.Value) {
                throw 'Use the same patch version and Windows account that installed the display patch.'
            }
        } else {
            $fileState = foreach ($file in $manifest.files) {
                $target = Join-Path $gamePath $file.name
                if (Test-Path -LiteralPath $target -PathType Container) { throw "Expected a file: $target" }
                $oldHash = Get-Hash $target
                if ($oldHash -and $oldHash -ne $file.sha256 -and $file.name -ne 'dgVoodoo.conf') {
                    throw "Another DirectDraw wrapper is installed ($($file.name)). Uninstall it before applying this patch."
                }
                [ordered]@{ name = $file.name; original = $oldHash; installed = $file.sha256 }
            }
            $flags = @($dpiBefore -split '\s+' | Where-Object {
                $_ -and $_ -notmatch '^(~|[+-]?(HIGHDPIAWARE|DPIUNAWARE|GDIDPISCALING))$'
            })
            $dpiAfter = (@('~') + $flags + 'HIGHDPIAWARE') -join ' '
            $state = [pscustomobject]@{
                version = $manifest.version
                user = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
                dpi_original = $dpiBefore
                dpi_installed = $dpiAfter
                files = $fileState
            }
        }

        if ($dpiBefore -cne $state.dpi_original -and $dpiBefore -cne $state.dpi_installed) {
            throw 'The Windows compatibility entry changed since installation. Restore it before continuing.'
        }
        foreach ($file in $manifest.files) {
            $item = $state.files | Where-Object name -eq $file.name
            if (@($item).Count -ne 1 -or $item.installed -ne $file.sha256) { throw "Invalid installation record: $($file.name)" }
            $target = Join-Path $gamePath $file.name
            $current = Get-Hash $target
            if ((Test-Path -LiteralPath $target -PathType Container) -or
                ($current -and $current -ne $item.installed -and $current -ne $item.original)) {
                throw "The file has changed since installation: $($file.name)"
            }
            if ($Action -eq 'Install' -and (Get-Hash (Join-Path $PSScriptRoot $file.name)) -ne $file.sha256) {
                throw "The extracted patch file failed verification: $($file.name)"
            }
            if ((Test-Path -LiteralPath $receipt) -and $item.original -and $item.original -ne $item.installed -and
                (Get-Hash (Join-Path $stateDir ($file.name + '.original'))) -ne $item.original) {
                throw "The original file backup failed verification: $($file.name)"
            }
        }

        if ($Action -eq 'Install') {
            if (-not (Test-Path -LiteralPath $receipt)) {
                New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
                foreach ($file in $state.files) {
                    if ($file.original -and $file.original -ne $file.installed) {
                        Copy-Verified (Join-Path $gamePath $file.name) (Join-Path $stateDir ($file.name + '.original')) $file.original
                    }
                }
                $pending = Join-Path $stateDir 'state.pending.json'
                $state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $pending -Encoding UTF8
                [IO.File]::Move($pending, $receipt)
            }
            foreach ($file in $manifest.files) {
                $target = Join-Path $gamePath $file.name
                if ((Get-Hash $target) -ne $file.sha256) {
                    Copy-Verified (Join-Path $PSScriptRoot $file.name) $target $file.sha256
                }
            }
            $layers.SetValue($exe, $state.dpi_installed, [Microsoft.Win32.RegistryValueKind]::String)
            foreach ($file in $manifest.files) {
                if ((Get-Hash (Join-Path $gamePath $file.name)) -ne $file.sha256) { throw "Installation verification failed: $($file.name)" }
            }
            if ($layers.GetValue($exe) -cne $state.dpi_installed) { throw 'DPI verification failed.' }
            Write-Output 'Display patch installed. Clear -window from the Steam launch options, then launch the game normally.'
        } else {
            foreach ($file in $state.files) {
                $target = Join-Path $gamePath $file.name
                if ($file.original -and (Get-Hash $target) -ne $file.original) {
                    $source = if ($file.original -eq $file.installed) { Join-Path $PSScriptRoot $file.name } else { Join-Path $stateDir ($file.name + '.original') }
                    Copy-Verified $source $target $file.original
                } elseif (-not $file.original) {
                    [IO.File]::Delete($target)
                }
            }
            if ($null -eq $state.dpi_original) {
                $layers.DeleteValue($exe, $false)
            } else {
                $layers.SetValue($exe, $state.dpi_original, [Microsoft.Win32.RegistryValueKind]::String)
            }
            foreach ($file in $state.files) {
                if ((Get-Hash (Join-Path $gamePath $file.name)) -ne $file.original) { throw "Restoration verification failed: $($file.name)" }
            }
            if ($layers.GetValue($exe) -cne $state.dpi_original) { throw 'DPI restoration verification failed.' }
            [IO.File]::Delete($receipt)
            foreach ($file in $state.files) { [IO.File]::Delete((Join-Path $stateDir ($file.name + '.original'))) }
            if (-not (Get-ChildItem -LiteralPath $stateDir -Force)) { [IO.Directory]::Delete($stateDir) }
            Write-Output 'Display patch uninstalled.'
        }
    } finally {
        $layers.Dispose()
    }
} finally {
    if ($locked) { $lock.ReleaseMutex() }
    $lock.Dispose()
}
