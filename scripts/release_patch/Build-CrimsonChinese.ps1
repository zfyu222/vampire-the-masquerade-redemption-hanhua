param(
    [Parameter(Mandatory=$true)][string]$Prepared,
    [Parameter(Mandatory=$true)][string]$Glyphs
)
$ErrorActionPreference = 'Stop'
$project = (Get-Item (Join-Path $PSScriptRoot '../..')).FullName
$preparedPath = (Get-Item -LiteralPath $Prepared).FullName
$stage = Join-Path $project 'Dispatch/Files/CrimsonChinese-preview'
$payload = Join-Path $stage 'CrimsonChinese'
New-Item -Path $payload -ItemType Directory -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Apply-CrimsonChinese.ps1'), (Join-Path $PSScriptRoot 'Install-CrimsonBundle.ps1'), (Join-Path $PSScriptRoot 'Delta.cs') -Destination $payload
Add-Type -Path (Join-Path $PSScriptRoot 'Delta.cs')
function Digest([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }

$overlay = Get-Content -LiteralPath (Join-Path $preparedPath 'result.json') -Raw | ConvertFrom-Json
$files = @()
function New-DeltaEntry($Name,$Source,$Target,$Index,$Existing) {
    $file = "$Index.delta"
    $delta = Join-Path $payload $file
    if ($Existing) { Copy-Item -LiteralPath $Existing -Destination $delta -Force }
    elseif (-not (Test-Path -LiteralPath $delta)) { [RedemptionDelta]::Run($Source, $Target, $delta, $true) }
    $roundtrip = Join-Path $preparedPath ("$Index-" + [guid]::NewGuid().ToString('N') + ".roundtrip")
    [RedemptionDelta]::Run($Source, $delta, $roundtrip, $false)
    if ((Digest $roundtrip) -ne (Digest $Target)) { throw "Round-trip failed: $Name" }
    [IO.File]::Delete($roundtrip)
    @{name=$Name; sources=@((Digest $Source)); target=(Digest $Target); delta=$true; payload=$file; payload_sha256=(Digest $delta)}
}

foreach ($name in 'Local_Eng.nob','LMaterials.nob') {
    $source = Join-Path $project "ImagePatch/original-archives-v3/$name"
    $target = Join-Path $project "Game/$name"
    $files += New-DeltaEntry $name $source $target $files.Count (Join-Path $project "Analysis/release-v1/$name.delta")
}
$files += @{name='Miles/FontFix.asi'; sources=@((Digest (Join-Path $preparedPath '../FontFix.asi'))); target=''}
foreach ($item in $overlay.resources) {
    $name = $item.name
    $files += New-DeltaEntry $name (Join-Path $preparedPath "original/$name") (Join-Path $preparedPath "translated/$name") $files.Count
}
foreach ($name in 'winmm.dll','NodChinese/glyphs.bin') {
    $old = Join-Path $project "Game/$name"
    $file = Split-Path -Leaf $name
    $source = if ($file -eq 'glyphs.bin') { $Glyphs } else { $old }
    $target = Digest $source
    Copy-Item -LiteralPath $source -Destination (Join-Path $payload $file)
    $files += @{name=$name; sources=@('',(Digest $old)); target=$target; delta=$false; payload=$file; payload_sha256=$target}
}
@{executable=$overlay.supported_exe_sha256; files=$files} |
    ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $payload 'manifest.json') -Encoding UTF8

$install = '@echo off', 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0CrimsonChinese\Install-CrimsonBundle.ps1"'
$finish = 'set "patch_status=%errorlevel%"','pause','exit /b %patch_status%'
Set-Content -LiteralPath (Join-Path $stage '安装Crimson汉化.cmd') -Value ($install + $finish) -Encoding ascii
Set-Content -LiteralPath (Join-Path $stage '卸载Crimson汉化.cmd') -Value (@($install[0],($install[1]+' -Uninstall')) + $finish) -Encoding ascii
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Crimson汉化说明.txt') -Destination $stage
Compress-Archive -Path "$stage/*" -DestinationPath (Join-Path $project 'Dispatch/VTMR Crimson Edition_汉化整合测试版.zip') -Force
