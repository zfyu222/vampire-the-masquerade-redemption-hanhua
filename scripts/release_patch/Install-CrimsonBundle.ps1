param(
    [string]$ModZip,
    [string]$Game,
    [switch]$Uninstall
)
$ErrorActionPreference = 'Stop'
if (-not $Game) { $Game = Split-Path -Parent $PSScriptRoot }
$root = (Get-Item -LiteralPath $Game).FullName
$exe = Join-Path $root 'Vampire.exe'
$state = Join-Path $root '.CrimsonBundleBackup'
$journal = Join-Path $state 'baseline.json'
$dpiReceipt = Join-Path $state 'dpi.json'
$patch = Join-Path $PSScriptRoot 'Apply-CrimsonChinese.ps1'
$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'manifest.json') -Raw | ConvertFrom-Json
$prefix = 'MODS/VTMR Crimson Edition/'
$modDigest = 'd65dd1cc22f1d317a1faf81f12699b068ab8148cce9fcc5f0b490b8b165b7f1a'
$steamDigest = '383f80768cc502044cfa64e242940a44dc72632b988440ef53bfac92fd4f387e'
$renderKeys = 'ScreenWidth','ScreenHeight','ScreenDepth'
$iniEncoding = [Text.Encoding]::GetEncoding(28591)

function Hash([string]$Path) {
    if (-not [IO.File]::Exists($Path)) { return '' }
    $stream = [IO.File]::OpenRead($Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '') }
    finally { $stream.Dispose(); $sha.Dispose() }
}

function Copy-Checked([string]$From, [string]$To, [string]$Expected) {
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($To)) | Out-Null
    $temp = "$To.crimson-$([guid]::NewGuid().ToString('N')).tmp"
    try {
        [IO.File]::Copy($From, $temp)
        if ((Hash $temp) -ne $Expected) { throw "Copy verification failed: $To" }
        if ([IO.File]::Exists($To)) { [IO.File]::Replace($temp, $To, "$temp.old") }
        else { [IO.File]::Move($temp, $To) }
    } finally {
        [IO.File]::Delete($temp)
        [IO.File]::Delete("$temp.old")
    }
}

function Restore-Baseline($Entries) {
    foreach ($entry in $Entries) {
        $file = Join-Path $root $entry.name
        if (((Hash $file) -notin @($entry.before, $entry.after) -and $entry.name -ine 'masquerade.ini') -or
            ($entry.before -and (Hash (Join-Path "$state/original" $entry.name)) -ne $entry.before)) {
            throw "File changed or backup missing: $($entry.name)"
        }
    }
    foreach ($entry in $Entries) {
        $file = Join-Path $root $entry.name
        if ($entry.name -ieq 'masquerade.ini' -and (Hash $file) -notin @($entry.before, $entry.after)) {
            if (-not $entry.before) { continue }
            $original = Join-Path "$state/original" $entry.name
            $old = $iniEncoding.GetString([IO.File]::ReadAllBytes($original))
            $current = $iniEncoding.GetString([IO.File]::ReadAllBytes($file))
            foreach ($key in $renderKeys) {
                $rx = "(?im)^($key=)(\d+)"
                $value = [regex]::Match($old, $rx).Groups[2].Value
                if ($value -and [regex]::Matches($current, $rx).Count -eq 1) {
                    $current = [regex]::Replace($current, $rx, ('${1}' + $value))
                }
            }
            $temp = Join-Path $state ([guid]::NewGuid().ToString('N') + '.ini')
            try {
                [IO.File]::WriteAllBytes($temp, $iniEncoding.GetBytes($current))
                Copy-Checked $temp $file (Hash $temp)
            } finally { [IO.File]::Delete($temp) }
            continue
        }
        if ($entry.before) {
            if ((Hash $file) -ne $entry.before) { Copy-Checked (Join-Path "$state/original" $entry.name) $file $entry.before }
        } else { [IO.File]::Delete($file) }
    }
}

if (Get-Process Vampire -ErrorAction SilentlyContinue) { throw 'Exit the game before installing or uninstalling.' }
$version = Hash $exe
if ($version -notin @($steamDigest, $manifest.executable)) { throw 'Run this installer from the Steam Redemption game folder.' }
$null = [IO.Directory]::CreateDirectory($state)
$lock = [IO.File]::Open((Join-Path $state 'install.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
$layers = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers')
try {
    if ($Uninstall) {
        if ($version -eq $manifest.executable) { & $patch -Game $root -Uninstall }
        if ([IO.File]::Exists($dpiReceipt)) {
            $dpi = Get-Content -LiteralPath $dpiReceipt -Raw | ConvertFrom-Json
            if ($layers.GetValue($exe) -cne $dpi.after) { throw 'Game DPI settings changed since install.' }
            if ($null -eq $dpi.before) { $layers.DeleteValue($exe, $false) }
            else { $layers.SetValue($exe, $dpi.before, [Microsoft.Win32.RegistryValueKind]::String) }
            [IO.File]::Delete($dpiReceipt)
        }
        if ([IO.File]::Exists($journal)) {
            Restore-Baseline (Get-Content -LiteralPath $journal -Raw | ConvertFrom-Json)
            [IO.File]::Delete($journal)
        }
        Write-Output 'Crimson Chinese bundle uninstalled.'
        return
    }

    if ($version -eq $steamDigest) {
        if ([IO.File]::Exists($journal)) { throw 'A previous installation was interrupted. Run Uninstall before retrying.' }
        if (-not $ModZip) {
            $candidate = Join-Path $root 'VTMR Crimson Edition-12-1-0-1726673430.zip'
            $ModZip = if ([IO.File]::Exists($candidate)) { $candidate } else { (Read-Host 'Paste or drag the original Crimson Edition 1.0 ZIP here').Trim().Trim('"') }
        }
        if ((Hash $ModZip) -ne $modDigest) { throw 'The original Nexus Crimson Edition 1.0 ZIP is required.' }
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $archive = [IO.Compression.ZipFile]::OpenRead((Get-Item -LiteralPath $ModZip).FullName)
        $stage = Join-Path $state ([guid]::NewGuid().ToString('N'))
        $entries = [Collections.Generic.List[object]]::new()
        try {
            foreach ($member in $archive.Entries) {
                if (-not $member.FullName.StartsWith($prefix, [StringComparison]::Ordinal) -or -not $member.Name) { continue }
                $name = $member.FullName.Substring($prefix.Length)
                if ($name -ieq 'ReShade.log') { continue }
                $temp = Join-Path $stage $name
                $file = Join-Path $root $name
                [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($temp)) | Out-Null
                [IO.Compression.ZipFileExtensions]::ExtractToFile($member, $temp)
                $before = Hash $file
                if ($name -ieq 'masquerade.ini' -and $before) {
                    $current = $iniEncoding.GetString([IO.File]::ReadAllBytes($file))
                    $stock = $iniEncoding.GetString([IO.File]::ReadAllBytes($temp))
                    foreach ($key in $renderKeys) {
                        $rx = "(?im)^($key=)(\d+)"
                        $value = [regex]::Match($stock, $rx).Groups[2].Value
                        if ([regex]::Matches($current, $rx).Count -ne 1 -or -not $value) { throw "Unexpected render setting: $key" }
                        $current = [regex]::Replace($current, $rx, ('${1}' + $value))
                    }
                    [IO.File]::WriteAllBytes($temp, $iniEncoding.GetBytes($current))
                }
                $after = Hash $temp
                if ($before -ne $after) {
                    if ($before) { Copy-Checked $file (Join-Path "$state/original" $name) $before }
                    $entries.Add(@{name=$name; before=$before; after=$after})
                }
            }
        } finally { $archive.Dispose() }
        $entries = @($entries | Sort-Object { $_.name -ieq 'Vampire.exe' })
        if ((Hash (Join-Path $stage 'Vampire.exe')) -ne $manifest.executable) { throw 'Unexpected Crimson executable after unpacking.' }
        ConvertTo-Json -InputObject $entries -Depth 4 | Set-Content -LiteralPath "$journal.pending" -Encoding UTF8
        [IO.File]::Move("$journal.pending", $journal)
        foreach ($entry in $entries) {
            $file = Join-Path $root $entry.name
            if ((Hash $file) -ne $entry.before) { throw "File changed during installation: $($entry.name)" }
            Copy-Checked (Join-Path $stage $entry.name) $file $entry.after
            [IO.File]::Delete((Join-Path $stage $entry.name))
        }
    }
    & $patch -Game $root
    if (-not [IO.File]::Exists($dpiReceipt)) {
        $before = $layers.GetValue($exe)
        $flags = @($before -split '\s+' | Where-Object { $_ -and $_ -notmatch '^(~|[+-]?(HIGHDPIAWARE|DPIUNAWARE|GDIDPISCALING))$' })
        $after = (@('~') + $flags + 'HIGHDPIAWARE') -join ' '
        @{before=$before; after=$after} | ConvertTo-Json | Set-Content -LiteralPath $dpiReceipt -Encoding UTF8
        $layers.SetValue($exe, $after, [Microsoft.Win32.RegistryValueKind]::String)
    }
    Write-Output 'Crimson Chinese bundle installed. Remove -window from Steam launch options if you added it.'
} finally { $layers.Dispose(); $lock.Dispose() }
