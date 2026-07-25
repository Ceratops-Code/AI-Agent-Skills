[CmdletBinding()]
param(
    [string]$SkillsRepoRoot,
    [string]$ApprovedBranchData = "",
    [string]$MainBranch = "main",
    [string]$ReleaseBranch = "release/local",
    [switch]$CleanMergedBranches
)

# Skill-local helper called by the ceratops-skill-lifecycle change-promotion
# action before installation. It checks only the approved branches supplied as
# base64-encoded, newline-delimited UTF-8 data. With -CleanMergedBranches, it
# removes clean approved task worktrees and branches already reachable from the
# release branch. Unrelated branches and worktrees are never enumerated.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($SkillsRepoRoot)) {
    # The installed skill copy lives outside the skills repo checkout, so the safest
    # default is the caller's current checkout. The skill tells agents to run
    # this from the skills repo checkout or pass -SkillsRepoRoot explicitly.
    $SkillsRepoRoot = (Get-Location).Path
}

$resolvedSkillsRepoRoot = (Resolve-Path -LiteralPath $SkillsRepoRoot).Path
function Invoke-Git {
    param([string[]]$Arguments)

    $null = & git -C $resolvedSkillsRepoRoot @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git failed: $($Arguments -join ' ')"
    }
}

function Get-GitLines {
    param([string[]]$Arguments)

    $output = & git -C $resolvedSkillsRepoRoot @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git failed: $($Arguments -join ' ')"
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

function Test-IsProtectedBranch {
    param([string]$BranchName)

    if ([string]::IsNullOrWhiteSpace($BranchName)) {
        return $true
    }
    return $BranchName -eq $MainBranch -or $BranchName -eq $ReleaseBranch
}

function Remove-MergedBranch {
    param([string]$BranchName)

    if (Test-IsProtectedBranch $BranchName) {
        throw "refusing to remove protected branch $BranchName"
    }
    if (-not (Test-GitSuccess @("merge-base", "--is-ancestor", $BranchName, $ReleaseBranch))) {
        throw "refusing to remove branch $BranchName because it is not merged into $ReleaseBranch"
    }
    Invoke-Git @("branch", "-D", $BranchName)
}

function Get-ExpectedWorktreeRoot {
    $projectName = Split-Path -Leaf $resolvedSkillsRepoRoot
    $projectsRoot = Split-Path -Parent $resolvedSkillsRepoRoot
    return Join-Path (Join-Path $projectsRoot "worktrees") $projectName
}

function Test-PathWithin {
    param(
        [string]$Path,
        [string]$Parent
    )

    $resolvedPath = (Resolve-Path -LiteralPath $Path).Path.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    $resolvedParent = (Resolve-Path -LiteralPath $Parent).Path.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    return $resolvedPath.StartsWith($resolvedParent + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
}

function Get-WorktreeStatus {
    param([string]$WorktreePath)

    $status = @(& git -C $WorktreePath status --porcelain)
    if ($LASTEXITCODE -ne 0) {
        throw "git failed: status --porcelain in $WorktreePath"
    }
    return $status
}

function Get-ApprovedBranches {
    if ([string]::IsNullOrWhiteSpace($ApprovedBranchData)) {
        return @()
    }

    try {
        $bytes = [Convert]::FromBase64String($ApprovedBranchData)
        $decoded = [Text.Encoding]::UTF8.GetString($bytes)
    } catch {
        throw "ApprovedBranchData must be base64-encoded UTF-8."
    }

    if ([string]::IsNullOrWhiteSpace($decoded)) {
        return @()
    }
    return @($decoded -split "`n" | ForEach-Object { $_.TrimEnd("`r") })
}

function Get-ApprovedBranchWorktreePath {
    param([string]$BranchName)

    $worktreePath = (
        Get-GitLines @(
            "for-each-ref",
            "--format=%(worktreepath)",
            "refs/heads/$BranchName"
        ) | Select-Object -First 1
    ).Trim()
    return $worktreePath
}

$findings = @()
$removed = @()
$expectedWorktreeRoot = Get-ExpectedWorktreeRoot
$approvedBranches = @()
$approvedBranchSet = @{}

foreach ($branchName in Get-ApprovedBranches) {
    if ([string]::IsNullOrWhiteSpace($branchName)) {
        throw "Approved branch entries must not be empty."
    }
    if (-not $approvedBranchSet.ContainsKey($branchName)) {
        $approvedBranchSet[$branchName] = $true
        $approvedBranches += $branchName
    }
}

Invoke-Git @("rev-parse", "--verify", $ReleaseBranch)

foreach ($branchName in $approvedBranches) {
    if (Test-IsProtectedBranch $branchName) {
        continue
    }

    Invoke-Git @("rev-parse", "--verify", "$branchName^{commit}")
    $worktreePath = Get-ApprovedBranchWorktreePath $branchName
    $worktreeIsClean = $true

    if (-not [string]::IsNullOrWhiteSpace($worktreePath)) {
        $worktreePath = (Resolve-Path -LiteralPath $worktreePath).Path
        if (
            -not (Test-Path -LiteralPath $expectedWorktreeRoot -PathType Container) -or
            -not (Test-PathWithin -Path $worktreePath -Parent $expectedWorktreeRoot)
        ) {
            $findings += [pscustomobject]@{
                Kind = "approved_worktree_outside_expected_root"
                Branch = $branchName
                Path = $worktreePath
                Detail = "not under $expectedWorktreeRoot"
            }
            $worktreeIsClean = $false
        } else {
            $status = @(Get-WorktreeStatus $worktreePath)
            if ($status.Count -gt 0) {
                $findings += [pscustomobject]@{
                    Kind = "dirty_approved_worktree"
                    Branch = $branchName
                    Path = $worktreePath
                    Detail = "$($status.Count) status entr$(if ($status.Count -eq 1) { 'y' } else { 'ies' }); not removed"
                }
                $worktreeIsClean = $false
            }
        }
    }

    if (-not (Test-GitSuccess @("merge-base", "--is-ancestor", $branchName, $ReleaseBranch))) {
        $aheadText = (
            Get-GitLines @("rev-list", "--count", "$ReleaseBranch..$branchName") |
            Select-Object -First 1
        ).Trim()
        $aheadCount = [int]$aheadText
        $findings += [pscustomobject]@{
            Kind = "unmerged_approved_branch_commits"
            Branch = $branchName
            Path = $worktreePath
            Detail = "$aheadCount commit$(if ($aheadCount -eq 1) { '' } else { 's' }) not in $ReleaseBranch"
        }
        continue
    }

    if (-not $CleanMergedBranches -or -not $worktreeIsClean) {
        continue
    }

    if (-not [string]::IsNullOrWhiteSpace($worktreePath)) {
        Invoke-Git @("worktree", "remove", $worktreePath)
        Remove-MergedBranch $branchName
        $removed += [pscustomobject]@{
            Kind = "merged_worktree_branch"
            Branch = $branchName
            Path = $worktreePath
            Detail = "removed; merged into $ReleaseBranch"
        }
        continue
    }

    Remove-MergedBranch $branchName
    $removed += [pscustomobject]@{
        Kind = "merged_branch"
        Branch = $branchName
        Path = ""
        Detail = "removed; merged into $ReleaseBranch"
    }
}

if ($removed.Count -gt 0) {
    Write-Host "Removed approved merged release work:"
    $removed | Sort-Object Kind, Branch, Path | Format-Table -AutoSize
}

if ($findings.Count -eq 0) {
    Write-Host "No pending approved release work was found."
    exit 0
}

Write-Host "Pending approved release work was found:"
$findings | Sort-Object Kind, Branch, Path | Format-Table -AutoSize
exit 2
