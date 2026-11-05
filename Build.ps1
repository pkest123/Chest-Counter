$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    py -3.11 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 environment setup failed.' }
}
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& '.\.venv\Scripts\python.exe' -m unittest discover -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; build stopped.' }
& '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm --onedir --windowed --name ChestCounter --distpath dist --workpath build\pyinstaller --specpath build --collect-all rapidocr_onnxruntime --collect-all onnxruntime (Join-Path $PSScriptRoot 'app.py')
if ($LASTEXITCODE -ne 0) { throw 'Windows build failed.' }
Copy-Item -LiteralPath README.md -Destination dist\ChestCounter\README.md
Compress-Archive -Path dist\ChestCounter -DestinationPath dist\ChestCounter-Classic-Windows.zip -Force
Write-Output 'Built dist\ChestCounter-Classic-Windows.zip'
