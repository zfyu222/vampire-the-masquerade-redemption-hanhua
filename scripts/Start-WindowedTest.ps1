param([string]$GamePath = (Join-Path $PSScriptRoot '..\Game'))

$ErrorActionPreference = 'Stop'
$gameDirectory = (Resolve-Path -LiteralPath $GamePath).Path
$gameExecutable = Join-Path $gameDirectory 'Vampire.exe'
if (-not (Test-Path -LiteralPath $gameExecutable -PathType Leaf)) {
    throw "Vampire.exe was not found in $gameDirectory"
}
if (-not (Get-Process -Name steam -ErrorAction SilentlyContinue)) {
    throw 'Start Steam before running this test.'
}
if (Get-Process -Name Vampire -ErrorAction SilentlyContinue) {
    throw 'Close the running game before starting another test.'
}

$previousApp = $env:SteamAppId
$previousGame = $env:SteamGameId
try {
    $env:SteamAppId = '559680'
    $env:SteamGameId = '559680'
    Start-Process -FilePath $gameExecutable -ArgumentList '-window' -WorkingDirectory $gameDirectory
}
finally {
    $env:SteamAppId = $previousApp
    $env:SteamGameId = $previousGame
}
