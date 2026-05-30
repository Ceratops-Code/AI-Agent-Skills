[CmdletBinding()]
param(
    [string]$RepoRoot,
    [string]$InstallRoot,
    [string]$PythonCommand
)

# Bootstrap entrypoint for initial Ceratops skill installation.
#
# Routine skill-lifecycle tasks call the skill-local runtime helper and
# validator directly. This repo-root wrapper exists so a fresh checkout still
# has one stable command that validates source consistency and installs managed
# skills into a Codex runtime.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$resolvedRepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$installer = Join-Path $resolvedRepoRoot "skills\ceratops-skill-lifecycle\scripts\runtime\install-managed-skills.ps1"
$validator = Join-Path $resolvedRepoRoot "skills\ceratops-skill-lifecycle\scripts\validation\validate-skills-consistency.py"
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
    throw "Missing skill lifecycle runtime installer: $installer"
}
if (-not (Test-Path -LiteralPath $validator -PathType Leaf)) {
    throw "Missing skill consistency validator: $validator"
}

function Resolve-PythonCommand {
    param([string]$Preferred)

    if (-not [string]::IsNullOrWhiteSpace($Preferred) -and (Test-Path -LiteralPath $Preferred)) {
        return (Resolve-Path -LiteralPath $Preferred).Path
    }

    foreach ($candidate in @($Preferred, "python", "py")) {
        if ([string]::IsNullOrWhiteSpace($candidate)) {
            continue
        }
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($null -ne $command) {
            if ($command.Source) {
                return $command.Source
            }
            if ($command.Path) {
                return $command.Path
            }
            return $command.Name
        }
    }

    throw "Could not find a usable Python command. Install Python or pass -PythonCommand."
}

$python = Resolve-PythonCommand $PythonCommand
$validationOutput = & $python @($validator, "--repo-root", $resolvedRepoRoot, "--mode", "full") 2>&1
if ($LASTEXITCODE -ne 0) {
    if ($validationOutput) {
        $validationOutput | ForEach-Object { Write-Error $_ }
    }
    throw "Skill consistency validation failed."
}
if ($validationOutput) {
    $validationOutput | ForEach-Object { Write-Output $_ }
}

$installerArgs = @{
    RepoRoot = $resolvedRepoRoot
}
if (-not [string]::IsNullOrWhiteSpace($InstallRoot)) {
    $installerArgs["InstallRoot"] = $InstallRoot
}
if (-not [string]::IsNullOrWhiteSpace($PythonCommand)) {
    $installerArgs["PythonCommand"] = $PythonCommand
}

& $installer @installerArgs
