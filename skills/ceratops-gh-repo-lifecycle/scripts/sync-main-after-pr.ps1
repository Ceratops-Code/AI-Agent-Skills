[CmdletBinding()]
param(
    [string]$RepoRoot,
    [string]$MainBranch = "main",
    [string]$RemoteName = "origin",
    [string[]]$AlignBranch = @()
)

# Skill-local helper for post-merge local repo sync. It fast-forwards the local
# main branch from the remote and, only when explicitly named, moves reusable
# local branches such as release/local to the synced main commit.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (Get-Location).Path
}
$resolvedRepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path

function Invoke-QuietNative {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [switch]$ReturnOutput
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & $FilePath @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($exitCode -ne 0) {
        $tail = @($output | Select-Object -Last 8) -join "`n"
        if (-not [string]::IsNullOrWhiteSpace($tail)) {
            throw "$FilePath failed: $($Arguments -join ' ')`n$tail"
        }
        throw "$FilePath failed: $($Arguments -join ' ')"
    }
    if ($ReturnOutput) {
        return @($output)
    }
}

function Invoke-GitQuiet {
    param([string[]]$Arguments)

    Invoke-QuietNative -FilePath "git" -Arguments (@("-C", $resolvedRepoRoot) + $Arguments)
}

function Get-GitLines {
    param([string[]]$Arguments)

    return @(Invoke-QuietNative -FilePath "git" -Arguments (@("-C", $resolvedRepoRoot) + $Arguments) -ReturnOutput)
}

function Assert-CleanWorktree {
    param([string]$Phase)

    $status = @(Get-GitLines @("status", "--porcelain"))
    if ($status.Count -gt 0) {
        throw "Refusing to sync because the worktree is dirty $Phase."
    }
}

Assert-CleanWorktree "before syncing main"
Invoke-GitQuiet @("fetch", "--prune", $RemoteName)
Invoke-GitQuiet @("switch", $MainBranch)
Invoke-GitQuiet @("merge", "--ff-only", "$RemoteName/$MainBranch")
Assert-CleanWorktree "after fast-forwarding $MainBranch"

$aligned = @()
foreach ($branch in $AlignBranch) {
    if ([string]::IsNullOrWhiteSpace($branch)) {
        throw "AlignBranch entries must not be empty."
    }
    if ($branch -eq $MainBranch) {
        throw "AlignBranch must not include the main branch."
    }
    Invoke-GitQuiet @("branch", "-f", $branch, $MainBranch)
    $aligned += $branch
}

$headSha = (Get-GitLines @("rev-parse", $MainBranch) | Select-Object -First 1).Trim()
[pscustomobject]@{
    status = "synced"
    main = $MainBranch
    remote = $RemoteName
    head = $headSha
    aligned_branches = $aligned
} | ConvertTo-Json -Compress
