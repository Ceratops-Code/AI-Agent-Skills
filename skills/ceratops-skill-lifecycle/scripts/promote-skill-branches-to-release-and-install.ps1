[CmdletBinding()]
param(
    [string]$SkillsRepoRoot,
    [string[]]$ApprovedBranch = @(),
    [string]$MainBranch = "main",
    [string]$ReleaseBranch = "release/local",
    [string]$RemoteName = "origin"
)

# Skill-local helper for deterministic change-promotion work. It refreshes main,
# prepares the reusable release branch, fast-forwards and checks only approved
# branches, type-checks the assembled candidate, retains approved clean
# worktrees through remote review, then validates and installs the promoted
# snapshot and emits one compact JSON summary on success.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($SkillsRepoRoot)) {
    $SkillsRepoRoot = (Get-Location).Path
}
if ([string]::IsNullOrWhiteSpace($RemoteName)) {
    throw "RemoteName must not be empty."
}

$resolvedSkillsRepoRoot = (Resolve-Path -LiteralPath $SkillsRepoRoot).Path
$scriptRoot = $PSScriptRoot
$managePendingScript = Join-Path $scriptRoot "manage-pending-release-work.ps1"

if (-not (Test-Path -LiteralPath $managePendingScript)) {
    throw "Missing helper: $managePendingScript"
}

function Invoke-CapturedNative {
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
    return @($output)
}

function Invoke-QuietNative {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory = $resolvedSkillsRepoRoot
    )

    $null = Invoke-CapturedNative `
        -FilePath $FilePath `
        -Arguments $Arguments `
        -WorkingDirectory $WorkingDirectory
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

function Test-RefExists {
    param([string]$RefName)

    return Test-GitSuccess @("show-ref", "--verify", "--quiet", $RefName)
}

function Assert-BranchCheckedOut {
    param([string]$BranchName)

    $currentBranch = Get-GitLines @("branch", "--show-current") |
        Select-Object -First 1
    if ($null -eq $currentBranch) {
        $currentBranch = ""
    } else {
        $currentBranch = $currentBranch.Trim()
    }
    if ($currentBranch -ne $BranchName) {
        throw "Expected branch '$BranchName' after release preparation, got '$currentBranch'."
    }
}

$remoteMainRef = "refs/remotes/$RemoteName/$MainBranch"
$remoteMain = "$RemoteName/$MainBranch"

$null = Get-GitLines @("rev-parse", "--is-inside-work-tree")
Assert-CleanWorktree "before switching branches"
$null = Get-GitLines @("remote", "get-url", $RemoteName)
Invoke-GitQuiet @("fetch", "--prune", $RemoteName)
if (-not (Test-RefExists "refs/heads/$MainBranch")) {
    throw "Missing local main branch '$MainBranch'."
}
if (-not (Test-RefExists $remoteMainRef)) {
    throw "Missing remote main branch '$remoteMain'."
}

Invoke-GitQuiet @("switch", $MainBranch)
Assert-CleanWorktree "after switching to $MainBranch"
Invoke-GitQuiet @("merge", "--ff-only", $remoteMain)
Assert-CleanWorktree "after fast-forwarding $MainBranch from $remoteMain"
if (Test-RefExists "refs/heads/$ReleaseBranch") {
    # Existing release commits are the authoritative unpublished batch. Branch
    # preparation checks out that batch without merging current main into it.
    Invoke-GitQuiet @("switch", $ReleaseBranch)
} else {
    Invoke-GitQuiet @("switch", "-c", $ReleaseBranch, $MainBranch)
}
Assert-CleanWorktree "after preparing $ReleaseBranch"
Assert-BranchCheckedOut $ReleaseBranch

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

Invoke-QuietNative -FilePath "python" -Arguments @("-m", "mypy")

$headSha = (Get-GitLines @("rev-parse", "HEAD") | Select-Object -First 1).Trim()
$managePendingArgs = @(
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    $managePendingScript,
    "-SkillsRepoRoot",
    $resolvedSkillsRepoRoot,
    "-MainBranch",
    $MainBranch,
    "-ReleaseBranch",
    $ReleaseBranch,
    "-PromotionCommit",
    $headSha,
    "-RecordPromotion"
)
if ($mergedBranches.Count -gt 0) {
    $approvedBranchData = [Convert]::ToBase64String(
        [Text.Encoding]::UTF8.GetBytes(($mergedBranches -join "`n"))
    )
    $managePendingArgs += "-ApprovedBranchData"
    $managePendingArgs += $approvedBranchData
}
$managePendingOutput = @(
    Invoke-CapturedNative `
        -FilePath "powershell" `
        -Arguments $managePendingArgs
)
$managePendingJson = (
    $managePendingOutput |
    Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } |
    Select-Object -Last 1
)
if ([string]::IsNullOrWhiteSpace([string]$managePendingJson)) {
    throw "Pending-release manager returned no promotion result."
}
try {
    $managePendingResult = $managePendingJson | ConvertFrom-Json
} catch {
    throw "Pending-release manager returned invalid promotion JSON."
}
if ($managePendingResult.status -ne "ready") {
    throw "Pending-release manager did not report ready promotion state."
}

Invoke-QuietNative -FilePath "python" -Arguments @(
    $installScript,
    "--repo-root",
    $resolvedSkillsRepoRoot
)
$validation = "full"
$runtimeInstall = "managed"

$currentBranch = (Get-GitLines @("branch", "--show-current") | Select-Object -First 1).Trim()
Assert-CleanWorktree "before reporting ready state"

[pscustomobject]@{
    status = "ready"
    release_branch = $currentBranch
    requested_release_branch = $ReleaseBranch
    merged_branches = $mergedBranches
    install = $runtimeInstall
    validation = $validation
    head = $headSha
    retained_approved_branches = @($managePendingResult.approved_branches)
    promotion_record = $managePendingResult.promotion_record
} | ConvertTo-Json -Compress
