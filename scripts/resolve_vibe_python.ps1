Set-StrictMode -Version Latest

function Get-VibePython {
    [CmdletBinding()]
    param(
        [string]$PythonPath = ""
    )

    if ($PythonPath) {
        if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
            throw "Configured Python interpreter does not exist: $PythonPath"
        }
        return (Resolve-Path -LiteralPath $PythonPath).Path
    }

    # Do not prefer the repository .venv here.  Windows Application Control can
    # block that executable for scheduled tasks; the workstation's registered
    # Python is the supported runtime and has the scanner dependencies installed.
    $command = Get-Command python -CommandType Application -All -ErrorAction Stop |
        Where-Object {
            $_.Source -and
            $_.Source -notlike "*\WindowsApps\python.exe" -and
            (Test-Path -LiteralPath $_.Source -PathType Leaf)
        } |
        Select-Object -First 1
    if (-not $command -or -not $command.Source) {
        throw "No runnable system Python interpreter was found on PATH."
    }
    return [string]$command.Source
}
