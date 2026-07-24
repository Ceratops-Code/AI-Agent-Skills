[CmdletBinding()]
param(
    [string]$SkillsRepoRoot,
    [string[]]$ApprovedBranch = @(),
    [string]$MainBranch = "main",
    [string]$ReleaseBranch = "release/local",
    [string]$RemoteName = "origin"
)

# Skill-local helper for deterministic change-promotion work. It prepares the
# reusable release branch, fast-forwards approved branches, validates and
# installs the promoted snapshot, checks pending local work, and emits one
# compact JSON summary on success.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($SkillsRepoRoot)) {
    $SkillsRepoRoot = (Get-Location).Path
}

$resolvedSkillsRepoRoot = (Resolve-Path -LiteralPath $SkillsRepoRoot).Path
$scriptRoot = $PSScriptRoot
$prepareScript = Join-Path $scriptRoot "prepare-release-branch.ps1"
$pendingScript = Join-Path $scriptRoot "check-pending-release-work.ps1"

if (-not (Test-Path -LiteralPath $prepareScript)) {
    throw "Missing helper: $prepareScript"
}
if (-not (Test-Path -LiteralPath $pendingScript)) {
    throw "Missing helper: $pendingScript"
}

function Invoke-QuietNative {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory = $resolvedSkillsRepoRoot
    )

    Push-Location -LiteralPath $WorkingDirectory
    try {
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            $output = & $FilePath @Arguments 2>&1
            $exitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
    } finally {
        Pop-Location
    }

    if ($exitCode -ne 0) {
        $tail = @($output | Select-Object -Last 8) -join "`n"
        if (-not [string]::IsNullOrWhiteSpace($tail)) {
            throw "$FilePath failed: $($Arguments -join ' ')`n$tail"
        }
        throw "$FilePath failed: $($Arguments -join ' ')"
    }
}

function Get-GitLines {
    param([string[]]$Arguments)

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & git -C $resolvedSkillsRepoRoot @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($exitCode -ne 0) {
        throw "git failed: $($Arguments -join ' ')"
    }
    if ($null -eq $output) {
        return @()
    }
    return @($output)
}

function Test-GitSuccess {
    param([string[]]$Arguments)

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $null = & git -C $resolvedSkillsRepoRoot @Arguments *>$null
        return $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Invoke-GitQuiet {
    param([string[]]$Arguments)

    Invoke-QuietNative -FilePath "git" -Arguments (@("-C", $resolvedSkillsRepoRoot) + $Arguments)
}

function Assert-CleanWorktree {
    param([string]$Phase)

    $status = @(Get-GitLines @("status", "--porcelain"))
    if ($status.Count -gt 0) {
        throw "Refusing to continue because the worktree is dirty $Phase."
    }
}

Invoke-QuietNative -FilePath "powershell" -Arguments @(
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    $prepareScript,
    "-SkillsRepoRoot",
    $resolvedSkillsRepoRoot,
    "-MainBranch",
    $MainBranch,
    "-ReleaseBranch",
    $ReleaseBranch,
    "-RemoteName",
    $RemoteName
)

Assert-CleanWorktree "after release branch preparation"

$mergedBranches = @()
foreach ($branch in $ApprovedBranch) {
    if ([string]::IsNullOrWhiteSpace($branch)) {
        throw "ApprovedBranch entries must not be empty."
    }

    $null = Get-GitLines @("rev-parse", "--verify", "$branch^{commit}")
    $base = (Get-GitLines @("merge-base", "HEAD", $branch) | Select-Object -First 1).Trim()
    if ([string]::IsNullOrWhiteSpace($base)) {
        throw "Could not find merge base for $branch."
    }
    if (-not (Test-GitSuccess @("merge-base", "--is-ancestor", "HEAD", $branch))) {
        throw (
            "Approved branch '$branch' must be rebased onto '$ReleaseBranch' " +
            "before promotion; refusing to create a merge commit."
        )
    }

    Invoke-GitQuiet @("diff", "--check", $base, $branch)
    Invoke-GitQuiet @("merge", "--ff-only", $branch)
    Assert-CleanWorktree "after fast-forwarding $branch"
    $mergedBranches += $branch
}

$installScript = Join-Path $resolvedSkillsRepoRoot "scripts\install-skills.py"
if (-not (Test-Path -LiteralPath $installScript -PathType Leaf)) {
    throw "Missing repository skill installer: $installScript"
}
Invoke-QuietNative -FilePath "python" -Arguments @(
    $installScript,
    "--repo-root",
    $resolvedSkillsRepoRoot
)
$validation = "full"
$runtimeInstall = "managed"

$pendingArgs = @(
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    $pendingScript,
    "-SkillsRepoRoot",
    $resolvedSkillsRepoRoot,
    "-MainBranch",
    $MainBranch,
    "-ReleaseBranch",
    $ReleaseBranch
)
$pendingArgs += "-CleanMergedBranches"
Invoke-QuietNative -FilePath "powershell" -Arguments $pendingArgs

$currentBranch = (Get-GitLines @("branch", "--show-current") | Select-Object -First 1).Trim()
$headSha = (Get-GitLines @("rev-parse", "HEAD") | Select-Object -First 1).Trim()
Assert-CleanWorktree "before reporting ready state"

[pscustomobject]@{
    status = "ready"
    release_branch = $currentBranch
    requested_release_branch = $ReleaseBranch
    merged_branches = $mergedBranches
    install = $runtimeInstall
    validation = $validation
    head = $headSha
} | ConvertTo-Json -Compress
