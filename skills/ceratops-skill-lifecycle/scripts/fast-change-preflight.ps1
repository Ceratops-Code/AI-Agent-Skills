[CmdletBinding()]
param(
    [string]$SkillsRepoRoot,
    [string]$ReleaseBranch = "release/local",
    [Parameter(Mandatory = $true)]
    [string]$SkillName,
    [Parameter(Mandatory = $true)]
    [string]$TargetPath
)

# Fast-change helper for ceratops-skill-lifecycle. It performs the small,
# deterministic evidence bundle required before a direct release-branch edit:
# intended branch, clean worktree, target file existence, and targeted install
# command availability. It does not prepare branches or mutate files.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($SkillsRepoRoot)) {
    $SkillsRepoRoot = (Get-Location).Path
}
if ([string]::IsNullOrWhiteSpace($ReleaseBranch)) {
    throw "ReleaseBranch must not be empty."
}
if ([string]::IsNullOrWhiteSpace($SkillName)) {
    throw "SkillName must not be empty."
}
if ([string]::IsNullOrWhiteSpace($TargetPath)) {
    throw "TargetPath must not be empty."
}

$resolvedSkillsRepoRoot = (Resolve-Path -LiteralPath $SkillsRepoRoot).Path

function Get-GitLines {
    param([string[]]$Arguments)

    $output = & git -C $resolvedSkillsRepoRoot @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git failed: $($Arguments -join ' ')"
    }
    if ($null -eq $output) {
        return @()
    }
    return @($output)
}

function Resolve-RepoTarget {
    param([string]$Path)

    if ([IO.Path]::IsPathRooted($Path)) {
        return (Resolve-Path -LiteralPath $Path).Path
    }
    return (Resolve-Path -LiteralPath (Join-Path $resolvedSkillsRepoRoot $Path)).Path
}

function Test-PathWithin {
    param(
        [string]$Path,
        [string]$Parent
    )

    $normalizedPath = $Path.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    $normalizedParent = $Parent.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    return $normalizedPath.StartsWith($normalizedParent + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
}

$null = Get-GitLines @("rev-parse", "--is-inside-work-tree")
$currentBranch = (Get-GitLines @("branch", "--show-current") | Select-Object -First 1).Trim()
if ($currentBranch -ne $ReleaseBranch) {
    throw "Expected branch '$ReleaseBranch', got '$currentBranch'."
}

$status = @(Get-GitLines @("status", "--porcelain"))
if ($status.Count -gt 0) {
    throw "Expected clean worktree before fast-change patching; found $($status.Count) status entries."
}

$resolvedTarget = Resolve-RepoTarget $TargetPath
if (-not (Test-Path -LiteralPath $resolvedTarget -PathType Leaf)) {
    throw "TargetPath must resolve to an existing file: $TargetPath"
}
if (-not (Test-PathWithin -Path $resolvedTarget -Parent $resolvedSkillsRepoRoot)) {
    throw "TargetPath must stay inside SkillsRepoRoot: $TargetPath"
}

$skillRoot = Join-Path (Join-Path $resolvedSkillsRepoRoot "skills") $SkillName
$skillFile = Join-Path $skillRoot "SKILL.md"
if (-not (Test-Path -LiteralPath $skillFile -PathType Leaf)) {
    throw "SkillName must identify an existing source skill: $SkillName"
}

$installScript = Join-Path $resolvedSkillsRepoRoot "scripts\install-skills.py"
$repoRootForRelative = $resolvedSkillsRepoRoot.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
$relativeTarget = $resolvedTarget.Substring($repoRootForRelative.Length + 1).Replace("\", "/")
$installAvailable = Test-Path -LiteralPath $installScript -PathType Leaf
$result = [ordered]@{
    ok = $true
    branch = $currentBranch
    release_branch = $ReleaseBranch
    skill = $SkillName
    target = $relativeTarget
    clean = $true
    install_command_available = $installAvailable
    install_command = if ($installAvailable) { "python `"$installScript`" --repo-root `"$resolvedSkillsRepoRoot`" --skill `"$SkillName`"" } else { $null }
}

$result | ConvertTo-Json -Compress
