param(
    [Parameter(Mandatory=$true)][string]$Previous,
    [Parameter(Mandatory=$true)][string]$PreviousResources,
    [Parameter(Mandatory=$true)][string]$PreviousArchive,
    [Parameter(Mandatory=$true)][string]$Revision,
    [Parameter(Mandatory=$true)][string]$Output
)
$ErrorActionPreference = 'Stop'
$out = [IO.Directory]::CreateDirectory($Output).FullName
$payload = Join-Path $out 'CrimsonChinese'
if (Test-Path -LiteralPath $payload) { throw 'Use a fresh staging directory.' }
$previousPath = (Get-Item -LiteralPath $Previous).FullName
$resources = (Get-Item -LiteralPath $PreviousResources).FullName
$revisionPath = (Get-Item -LiteralPath $Revision).FullName
Copy-Item -LiteralPath (Join-Path $previousPath 'CrimsonChinese') -Destination $payload -Recurse
Copy-Item -LiteralPath (Join-Path $previousPath '安装汉化.cmd'), (Join-Path $previousPath '卸载汉化.cmd'), (Join-Path $previousPath 'MinHook-LICENSE.txt') -Destination $out
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Apply-CrimsonChinese.ps1') -Destination $payload -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Delta.cs') -Destination $payload -Force
Add-Type -Path (Join-Path $payload 'Delta.cs')
function Digest([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
$manifest = Get-Content -LiteralPath (Join-Path $payload 'manifest.json') -Raw | ConvertFrom-Json
foreach ($entry in $manifest.files) {
    if (-not $entry.target) { continue }
    if ((Digest (Join-Path $payload $entry.payload)) -ne $entry.payload_sha256) {
        throw "Previous payload failed verification: $($entry.name)"
    }
    switch ($entry.name) {
        'Local_Eng.nob' {
            $old = (Get-Item -LiteralPath $PreviousArchive).FullName
            $new = Join-Path $revisionPath $entry.name
        }
        'NodChinese/glyphs.bin' {
            $old = Join-Path $payload $entry.payload
            $new = Join-Path $revisionPath 'glyphs/glyphs.bin'
        }
        default {
            $old = Join-Path $resources "overlay/translated/$($entry.name)"
            $new = Join-Path $revisionPath "overlay/translated/$($entry.name)"
        }
    }
    if (-not (Test-Path -LiteralPath $new -PathType Leaf)) { continue }
    if ((Digest $old) -ne $entry.target) { throw "Previous installed target differs: $($entry.name)" }
    $target = Digest $new
    if ($target -eq $entry.target) { continue }

    $sourceHash = $entry.target
    if ($entry.delta) {
        $name = 'v11-' + $entry.payload
        $delta = Join-Path $payload $name
        if ($entry.name -eq 'Local_Eng.nob') {
            & python (Join-Path $PSScriptRoot 'zip_member_delta.py') $old $new $delta
            if ($LASTEXITCODE) { throw 'Nod ZIP member delta generation failed.' }
        } else {
            [RedemptionDelta]::Run($old, $new, $delta, $true)
        }
        $test = Join-Path $revisionPath "$name.replayed"
        [RedemptionDelta]::Run($old, $delta, $test, $false)
        if ((Digest $test) -ne $target) { throw "Delta replay failed: $($entry.name)" }
        [IO.File]::Delete($test)
        $step = @{source=$sourceHash; payload=$name; payload_sha256=(Digest $delta)}
        $entry | Add-Member -MemberType NoteProperty -Name next -Value $step
    } else {
        Copy-Item -LiteralPath $new -Destination $old -Force
        $entry.payload_sha256 = $target
        $step = @{source=$sourceHash; payload=$entry.payload; payload_sha256=$target}
    }
    $entry | Add-Member -MemberType NoteProperty -Name upgrade -Value $step
    $entry.target = $target
    Write-Output "Verified revision target: $($entry.name)"
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $payload 'manifest.json') -Encoding UTF8
