$pythonPath = "C:\scoop\apps\kicad\current\bin"

Write-Output "Remove all Python paths from environment"
$arrPath = $env:Path -split ";" | Where-Object {$_ -notMatch "Python"}

Write-Output "Add KiCad's python to environment"
$addPaths = $pythonPath,"$pythonPath\Scripts"
$env:Path = ($arrPath + $addPaths) -join ";"

python -c "import pcbnew; print('KiCad version: ' + pcbnew.Version())"

if ($LastExitCode -ne 0) {
  Write-Error "Could not import pcbnew"
}

Write-Output "Creating symbolic link for python3"
New-Item -Path "$pythonPath\python3.exe" `
  -ItemType SymbolicLink `
  -Value "$pythonPath\python.exe" `
  -Force | Out-Null

