[CmdletBinding()]
param(
    [string]$RepoRoot,
    [string]$InstallRoot,
    [string]$PythonCommand,
    [string[]]$Skill,
    [ValidateSet("none", "sections", "full", "governance")]
    [string]$Validate = "none",
    [switch]$SkipInstall
)

# Single public entrypoint for Ceratops skill install/update checks.
#
# This PowerShell layer owns user-facing orchestration: resolving the source
# repo, choosing Python, validating requested skill names, optionally rebuilding
# installed skill copies, and optionally running consistency validation. The
# Python files remain narrow implementation modules: render-runtime-skills.py
# renders/copies runtime skills, and validate-skills-consistency.py checks the
# source model. Keeping those modules separate avoids one large script while
# preserving one command for humans and skills.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Resolve the source checkout first. Installed runtime copies may contain this
# wrapper as a payload, but callers can still point -RepoRoot at the checkout
# whose skills should be rendered.
if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

# An install destination is needed only when copying skills. Validation-only
# runs can skip it so CI and maintenance checks do not touch live skills.
if (-not $SkipInstall -and [string]::IsNullOrWhiteSpace($InstallRoot)) {
    $codexHome = $env:CODEX_HOME
    if ([string]::IsNullOrWhiteSpace($codexHome)) {
        $homeRoot = $env:USERPROFILE
        if ([string]::IsNullOrWhiteSpace($homeRoot)) {
            $homeRoot = $env:HOME
        }
        if ([string]::IsNullOrWhiteSpace($homeRoot)) {
            throw "Could not resolve a home directory. Set CODEX_HOME or pass -InstallRoot."
        }
        $codexHome = Join-Path $homeRoot ".codex"
    }
    $InstallRoot = Join-Path $codexHome "skills"
}

function Resolve-PythonCommand {
    param([string]$Preferred)

    # Prefer a caller-provided interpreter, then normal launcher names. The
    # skill installer intentionally avoids environment activation so the runtime
    # copy can be rebuilt from a plain shell or automation task.
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

$resolvedRepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$skillsRoot = Join-Path $resolvedRepoRoot "skills"
$renderer = Join-Path $resolvedRepoRoot "scripts\render-runtime-skills.py"
$validator = Join-Path $resolvedRepoRoot "scripts\validation\validate-skills-consistency.py"
# Fail early on missing repo components. The create/update skills may skip this
# wrapper for non-Ceratops repos, but once this script is invoked it owns a
# complete Ceratops runtime build or validation path.
if (-not (Test-Path -LiteralPath $skillsRoot -PathType Container)) {
    throw "Missing skills directory: $skillsRoot"
}
if (-not (Test-Path -LiteralPath $renderer -PathType Leaf)) {
    throw "Missing runtime skill renderer: $renderer"
}
if ($Validate -ne "none" -and -not (Test-Path -LiteralPath $validator -PathType Leaf)) {
    throw "Missing skill consistency validator: $validator"
}

$python = Resolve-PythonCommand $PythonCommand
# Source skill names are derived from actual folders, not from the section
# manifest, so stale manifest entries are caught by the Python validator/renderer
# instead of silently deciding the install set.
$sourceSkillNames = Get-ChildItem -LiteralPath $skillsRoot -Directory |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "SKILL.md") } |
    Sort-Object Name |
    ForEach-Object { $_.Name }

$buildSkillNames = @()
if ($null -ne $Skill -and $Skill.Count -gt 0) {
    # Targeted installs are intentionally strict: misspelling a skill should not
    # fall back to a full install or create a new runtime directory by accident.
    $known = @{}
    foreach ($skillName in $sourceSkillNames) {
        $known[$skillName] = $true
    }
    foreach ($skillName in $Skill) {
        if (-not $known.ContainsKey($skillName)) {
            throw "Unknown skill: $skillName"
        }
        $buildSkillNames += $skillName
    }
} else {
    $buildSkillNames = $sourceSkillNames
}

if (-not $SkipInstall) {
    # Render selected skills through Python so shared-section rendering, payload
    # copying, managed-folder replacement, and stale cleanup share one source of
    # truth across direct CLI use and skill-invoked runtime refreshes.
    if (-not (Test-Path -LiteralPath $InstallRoot)) {
        New-Item -ItemType Directory -Path $InstallRoot | Out-Null
    }

    $rendererArgs = @($renderer, "--install-root", $InstallRoot)
    foreach ($skillName in $buildSkillNames) {
        $rendererArgs += @("--skill", $skillName)
    }
    if ($buildSkillNames.Count -eq $sourceSkillNames.Count) {
        # Full installs can remove stale folders previously generated by the renderer.
        # Targeted installs leave unrelated managed skills alone for active previews.
        $rendererArgs += "--remove-stale"
    }

    $buildOutput = & $python @rendererArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        if ($buildOutput) {
            $buildOutput | ForEach-Object { Write-Error $_ }
        }
        throw "Runtime skill build failed."
    }

    Write-Output "installed"
}

if ($Validate -ne "none") {
    # Validation is opt-in. Regular targeted runtime refreshes do not pay the
    # cost of repository-wide consistency checks unless the caller asks.
    $validatorArgs = @($validator, "--mode", $Validate)

    $validationOutput = & $python @validatorArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        if ($validationOutput) {
            $validationOutput | ForEach-Object { Write-Error $_ }
        }
        throw "Skill consistency validation failed."
    }
    if ($validationOutput) {
        $validationOutput | ForEach-Object { Write-Output $_ }
    }
    Write-Output "validated:$Validate"
}
