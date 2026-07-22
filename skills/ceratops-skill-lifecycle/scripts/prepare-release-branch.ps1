[CmdletBinding()]
param(
    [string]$SkillsRepoRoot,
    [string]$MainBranch = "main",
    [string]$ReleaseBranch = "release/local",
    [string]$RemoteName = "origin"
)

# Skill-local helper called by the ceratops-skill-lifecycle change-promotion
# action before branch merges. It centralizes PowerShell-safe git exit-code
# handling for the branch preparation sequence.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($SkillsRepoRoot)) {
    # The installed skill copy may run outside the skills repo checkout, but the
    # source-checkout path defaults to the caller's current directory.
    $SkillsRepoRoot = (Get-Location).Path
}

if ([string]::IsNullOrWhiteSpace($RemoteName)) {
    throw "RemoteName must not be empty."
}

$resolvedSkillsRepoRoot = (Resolve-Path -LiteralPath $SkillsRepoRoot).Path

function Invoke-Git {
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
        if ($output) {
            $output | ForEach-Object { Write-Error -Message $_ -ErrorAction Continue }
        }
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

function Assert-CleanWorktree {
    param([string]$Phase)

    $status = @(Invoke-Git @("status", "--porcelain"))
    if ($status.Count -gt 0) {
        throw "Refusing to prepare release branch because the worktree is dirty $Phase."
    }
}

function Assert-BranchCheckedOut {
    param([string]$BranchName)

    $currentBranch = Invoke-Git @("branch", "--show-current") | Select-Object -First 1
    if ($null -eq $currentBranch) {
        $currentBranch = ""
    } else {
        $currentBranch = $currentBranch.Trim()
    }
    if ($currentBranch -ne $BranchName) {
        throw "Expected branch '$BranchName' after release preparation, got '$currentBranch'."
    }
}

function Test-RefExists {
    param([string]$RefName)

    return Test-GitSuccess @("show-ref", "--verify", "--quiet", $RefName)
}

$remoteMainRef = "refs/remotes/$RemoteName/$MainBranch"
$remoteMain = "$RemoteName/$MainBranch"

$null = Invoke-Git @("rev-parse", "--is-inside-work-tree")
Assert-CleanWorktree "before switching branches"
$null = Invoke-Git @("remote", "get-url", $RemoteName)
$null = Invoke-Git @("fetch", "--prune", $RemoteName)

if (-not (Test-RefExists "refs/heads/$MainBranch")) {
    throw "Missing local main branch '$MainBranch'."
}
if (-not (Test-RefExists $remoteMainRef)) {
    throw "Missing remote main branch '$remoteMain'."
}

$null = Invoke-Git @("switch", $MainBranch)
Assert-CleanWorktree "after switching to $MainBranch"
$null = Invoke-Git @("merge", "--ff-only", $remoteMain)
Assert-CleanWorktree "after fast-forwarding $MainBranch from $remoteMain"

if (Test-RefExists "refs/heads/$ReleaseBranch") {
    # Existing release commits are the authoritative unpublished batch. Branch
    # preparation checks out that batch without merging current main into it.
    $null = Invoke-Git @("switch", $ReleaseBranch)
} else {
    $null = Invoke-Git @("switch", "-c", $ReleaseBranch, $MainBranch)
}

Assert-CleanWorktree "after preparing $ReleaseBranch"
Assert-BranchCheckedOut $ReleaseBranch
Write-Output "prepared:$ReleaseBranch"
