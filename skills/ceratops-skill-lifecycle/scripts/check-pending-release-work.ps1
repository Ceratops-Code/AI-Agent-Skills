[CmdletBinding()]
param(
    [string]$SkillsRepoRoot,
    [string]$MainBranch = "main",
    [string]$ReleaseBranch = "release/local",
    [switch]$CleanMergedBranches
)

# Skill-local helper called by the ceratops-skill-lifecycle change-promotion
# action before a staged skills repo release is treated as ready to ship. By
# default it reports dirty worktrees or local branches that have commits not
# reachable from the release branch. With -CleanMergedBranches, it first removes
# clean task worktrees and local branches whose commits are already reachable
# from the release branch.

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

function Get-WorktreeRecords {
    # Parse porcelain output into records so the staged-release skill can detect
    # other local worktrees that still carry dirty or unstaged work.
    $records = @()
    $current = @{}

    foreach ($line in Get-GitLines @("worktree", "list", "--porcelain")) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            if ($current.ContainsKey("worktree")) {
                $records += [pscustomobject]$current
            }
            $current = @{}
            continue
        }

        $parts = $line.Split(" ", 2)
        if ($parts.Count -lt 2) {
            continue
        }
        $current[$parts[0]] = $parts[1]
    }

    if ($current.ContainsKey("worktree")) {
        $records += [pscustomobject]$current
    }

    return $records
}

function Get-CurrentBranch {
    return (Get-GitLines @("branch", "--show-current") | Select-Object -First 1).Trim()
}

function Convert-BranchRefToName {
    param([string]$BranchRef)

    $prefix = "refs/heads/"
    if ($BranchRef.StartsWith($prefix, [StringComparison]::Ordinal)) {
        return $BranchRef.Substring($prefix.Length)
    }
    return $BranchRef
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

function Test-IsExcludedBranch {
    param([string]$BranchName)

    if ([string]::IsNullOrWhiteSpace($BranchName)) {
        return $false
    }
    # Main and the active release branch are expected. Every other branch is
    # suspicious if it has commits that are not reachable from the release branch.
    if (Test-IsProtectedBranch $BranchName) {
        return $true
    }
    return $false
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

$findings = @()
$removed = @()
$reportedDirtyWorktrees = @{}
$skillsRepoPath = $resolvedSkillsRepoRoot.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
$expectedWorktreeRoot = Get-ExpectedWorktreeRoot

if ($CleanMergedBranches) {
    Invoke-Git @("rev-parse", "--verify", $ReleaseBranch)
    if (Test-Path -LiteralPath $expectedWorktreeRoot) {
        foreach ($record in Get-WorktreeRecords) {
            $worktreePath = (Resolve-Path -LiteralPath $record.worktree).Path
            $normalizedWorktreePath = $worktreePath.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
            if ($normalizedWorktreePath -ieq $skillsRepoPath) {
                continue
            }
            if (-not ($record.PSObject.Properties.Name -contains "branch")) {
                continue
            }

            $branchName = Convert-BranchRefToName $record.branch
            if (Test-IsProtectedBranch $branchName) {
                continue
            }
            if (-not (Test-GitSuccess @("merge-base", "--is-ancestor", $branchName, $ReleaseBranch))) {
                continue
            }
            if (-not (Test-PathWithin -Path $worktreePath -Parent $expectedWorktreeRoot)) {
                $findings += [pscustomobject]@{
                    Kind = "merged_worktree_outside_expected_root"
                    Branch = $branchName
                    Path = $worktreePath
                    Detail = "merged into $ReleaseBranch but not under $expectedWorktreeRoot"
                }
                continue
            }

            $status = @(Get-WorktreeStatus $worktreePath)
            if ($status.Count -gt 0) {
                $findings += [pscustomobject]@{
                    Kind = "dirty_merged_worktree"
                    Branch = $branchName
                    Path = $worktreePath
                    Detail = "$($status.Count) status entr$(if ($status.Count -eq 1) { 'y' } else { 'ies' }); not removed"
                }
                $reportedDirtyWorktrees[$normalizedWorktreePath] = $true
                continue
            }

            Invoke-Git @("worktree", "remove", $worktreePath)
            Remove-MergedBranch $branchName
            $removed += [pscustomobject]@{
                Kind = "merged_worktree_branch"
                Branch = $branchName
                Path = $worktreePath
                Detail = "removed; merged into $ReleaseBranch"
            }
        }
    }

    $checkedOutBranches = @(
        foreach ($record in Get-WorktreeRecords) {
            if ($record.PSObject.Properties.Name -contains "branch") {
                Convert-BranchRefToName $record.branch
            }
        }
    )
    foreach ($branchName in Get-GitLines @("for-each-ref", "--format=%(refname:short)", "refs/heads")) {
        if (Test-IsProtectedBranch $branchName) {
            continue
        }
        # Worktree-backed branches were either removed above or intentionally
        # retained; the branch-only pass must not try to delete retained work.
        if ($checkedOutBranches -contains $branchName) {
            continue
        }
        if (Test-GitSuccess @("merge-base", "--is-ancestor", $branchName, $ReleaseBranch)) {
            Remove-MergedBranch $branchName
            $removed += [pscustomobject]@{
                Kind = "merged_branch"
                Branch = $branchName
                Path = ""
                Detail = "removed; merged into $ReleaseBranch"
            }
        }
    }
}

if (-not (Test-GitSuccess @("rev-parse", "--verify", $ReleaseBranch))) {
    if ($removed.Count -gt 0) {
        Write-Host "Removed merged local release work:"
        $removed | Sort-Object Kind, Branch, Path | Format-Table -AutoSize
    }
    if ($findings.Count -gt 0) {
        Write-Host "Pending local work outside '$ReleaseBranch' was found:"
        $findings | Sort-Object Kind, Branch, Path | Format-Table -AutoSize
        exit 2
    }
    Invoke-Git @("rev-parse", "--verify", $ReleaseBranch)
}

foreach ($record in Get-WorktreeRecords) {
    $worktreePath = (Resolve-Path -LiteralPath $record.worktree).Path
    $normalizedWorktreePath = $worktreePath.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    if ($normalizedWorktreePath -ieq $skillsRepoPath) {
        continue
    }

    $branchName = "(detached)"
    if ($record.PSObject.Properties.Name -contains "branch") {
        $branchName = Convert-BranchRefToName $record.branch
    }

    # Dirty worktrees outside the skills repo checkout are reported before shipping
    # so they are either staged, intentionally retained, or cleaned up.
    $status = @(Get-WorktreeStatus $worktreePath)
    if ($status.Count -gt 0 -and -not $reportedDirtyWorktrees.ContainsKey($normalizedWorktreePath)) {
        $findings += [pscustomobject]@{
            Kind = "dirty_worktree"
            Branch = $branchName
            Path = $worktreePath
            Detail = "$($status.Count) status entr$(if ($status.Count -eq 1) { 'y' } else { 'ies' })"
        }
    }
}

foreach ($branchName in Get-GitLines @("for-each-ref", "--format=%(refname:short)", "refs/heads")) {
    if (Test-IsExcludedBranch $branchName) {
        continue
    }

    # Count commits that would be left behind if the release branch shipped now.
    $aheadText = (Get-GitLines @("rev-list", "--count", "$ReleaseBranch..$branchName") | Select-Object -First 1).Trim()
    $aheadCount = [int]$aheadText
    if ($aheadCount -gt 0) {
        $findings += [pscustomobject]@{
            Kind = "unmerged_branch_commits"
            Branch = $branchName
            Path = ""
            Detail = "$aheadCount commit$(if ($aheadCount -eq 1) { '' } else { 's' }) not in $ReleaseBranch"
        }
    }
}

if ($removed.Count -gt 0) {
    Write-Host "Removed merged local release work:"
    $removed | Sort-Object Kind, Branch, Path | Format-Table -AutoSize
}

if ($findings.Count -eq 0) {
    Write-Host "No pending local work outside '$ReleaseBranch' was found."
    exit 0
}

Write-Host "Pending local work outside '$ReleaseBranch' was found:"
$findings | Sort-Object Kind, Branch, Path | Format-Table -AutoSize
exit 2
