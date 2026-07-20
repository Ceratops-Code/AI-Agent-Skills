[CmdletBinding()]
param(
    [string]$RepoRoot,
    [string]$InstallRoot,
    [string]$PythonCommand
)

# Bootstrap entrypoint for managed skill installation.
#
# Prefer a supported installed lifecycle helper bundle so one installation can
# manage multiple compatible repos. A fresh or legacy installation falls back
# to the target checkout's bundle for bootstrap.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$resolvedRepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$checkoutBundleRoot = Join-Path $resolvedRepoRoot "skills\ceratops-skill-lifecycle"
$bundleResolver = Join-Path $PSScriptRoot "..\skills\ceratops-skill-lifecycle\scripts\runtime\resolve-lifecycle-bundle.ps1"
if (-not (Test-Path -LiteralPath $bundleResolver -PathType Leaf)) {
    throw "Missing lifecycle helper-bundle resolver: $bundleResolver"
}
. $bundleResolver
$bundleRoot = Resolve-CeratopsLifecycleBundle -CheckoutBundleRoot $checkoutBundleRoot

$installer = Join-Path $bundleRoot "scripts\runtime\install-managed-skills.ps1"
$validator = Join-Path $bundleRoot "scripts\validation\validate-skills-consistency.py"
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
