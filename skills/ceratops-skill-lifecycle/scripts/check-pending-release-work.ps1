[CmdletBinding()]
param(
    [string]$SkillsRepoRoot,
    [string]$ApprovedBranchData = "",
    [string]$MainBranch = "main",
    [string]$ReleaseBranch = "release/local",
    [string]$PromotionCommit = "",
    [switch]$RecordPromotion,
    [switch]$CleanMergedBranches
)

# Skill-local helper called by change-promotion before installation and by
# ship-to-remote after terminal shipping. It checks only approved branches
# supplied as base64-encoded, newline-delimited UTF-8 data or one exact
# promotion record.
# With -CleanMergedBranches, it removes clean approved task worktrees and
# branches already reachable from the release branch, then deletes only the
# consumed promotion record. Unrelated branches and worktrees are never
# enumerated. -RecordPromotion atomically advances the release branch's exact
# commit while retaining the union of approved sources already in that batch.

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

function Get-GitCommonDirectory {
    $raw = (Get-GitLines @("rev-parse", "--git-common-dir") | Select-Object -First 1).Trim()
    if ([string]::IsNullOrWhiteSpace($raw)) {
        throw "Could not resolve the shared Git directory."
    }
    if ([IO.Path]::IsPathRooted($raw)) {
        return [IO.Path]::GetFullPath($raw)
    }
    return [IO.Path]::GetFullPath((Join-Path $resolvedSkillsRepoRoot $raw))
}

function Decode-ApprovedBranchData {
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

function Get-PromotionRecordPath {
    $recordDirectory = Join-Path (Get-GitCommonDirectory) "codex\skill-lifecycle\promotions"
    # Hash the full UTF-8 branch name so filesystem case folding and replaced
    # punctuation cannot alias two release records.
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $releaseHash = $sha256.ComputeHash(
            [Text.Encoding]::UTF8.GetBytes($ReleaseBranch)
        )
    } finally {
        $sha256.Dispose()
    }
    $releaseKey = -join ($releaseHash | ForEach-Object { $_.ToString("x2") })
    return Join-Path $recordDirectory "sha256-$releaseKey.json"
}

function Read-PromotionRecord {
    param(
        [string]$RecordPath,
        [switch]$RequireExactCommit
    )

    if (-not (Test-Path -LiteralPath $RecordPath -PathType Leaf)) {
        throw "Promotion record not found for $ReleaseBranch."
    }
    try {
        $record = Get-Content -Raw -LiteralPath $RecordPath |
            ConvertFrom-Json
    } catch {
        throw "Promotion record is invalid for $ReleaseBranch."
    }
    if (
        $record.version -ne 1 -or
        $record.release_branch -ne $ReleaseBranch -or
        $record.promotion_commit -notmatch "^[0-9a-f]{40}$" -or
        $null -eq $record.approved_branches
    ) {
        throw "Promotion record identity is invalid for $ReleaseBranch."
    }
    if (
        $RequireExactCommit -and
        $record.promotion_commit -ne $PromotionCommit
    ) {
        throw "Promotion record does not match commit $PromotionCommit."
    }
    return $record
}

function Write-PromotionRecord {
    param(
        [string]$RecordPath,
        [string[]]$Branches
    )

    $recordDirectory = Split-Path -Parent $RecordPath
    $null = New-Item -ItemType Directory -Force -Path $recordDirectory
    $temporaryPath = "$RecordPath.tmp"
    $payload = [ordered]@{
        version = 1
        promotion_commit = $PromotionCommit
        release_branch = $ReleaseBranch
        approved_branches = @($Branches)
    } | ConvertTo-Json -Compress
    [IO.File]::WriteAllText(
        $temporaryPath,
        $payload,
        [Text.UTF8Encoding]::new($false)
    )
    Move-Item -Force -LiteralPath $temporaryPath -Destination $RecordPath
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
$promotionRecordPath = ""

if ($RecordPromotion -and $CleanMergedBranches) {
    throw "RecordPromotion and CleanMergedBranches are mutually exclusive."
}
if (
    -not $RecordPromotion -and
    -not [string]::IsNullOrWhiteSpace($PromotionCommit) -and
    -not [string]::IsNullOrWhiteSpace($ApprovedBranchData)
) {
    throw "ApprovedBranchData requires RecordPromotion when PromotionCommit is set."
}
if (
    ($RecordPromotion -or -not [string]::IsNullOrWhiteSpace($PromotionCommit)) -and
    $PromotionCommit -notmatch "^[0-9a-f]{40}$"
) {
    throw "PromotionCommit must be a full Git SHA."
}

Invoke-Git @("rev-parse", "--verify", $ReleaseBranch)
$requestedBranches = @(Decode-ApprovedBranchData)
$retainedBranches = @()
if ($RecordPromotion -or -not [string]::IsNullOrWhiteSpace($PromotionCommit)) {
    $promotionRecordPath = Get-PromotionRecordPath
}
if ($RecordPromotion) {
    $releaseHead = (
        Get-GitLines @("rev-parse", $ReleaseBranch) |
        Select-Object -First 1
    ).Trim()
    if ($releaseHead -ne $PromotionCommit) {
        throw "PromotionCommit must match the exact release branch head."
    }
    if (Test-Path -LiteralPath $promotionRecordPath -PathType Leaf) {
        $existingRecord = Read-PromotionRecord -RecordPath $promotionRecordPath
        $retainedBranches = @($existingRecord.approved_branches)
    }
} elseif (-not [string]::IsNullOrWhiteSpace($PromotionCommit)) {
    $existingRecord = Read-PromotionRecord `
        -RecordPath $promotionRecordPath `
        -RequireExactCommit
    if (
        -not (
            Test-GitSuccess @(
                "merge-base",
                "--is-ancestor",
                $PromotionCommit,
                $ReleaseBranch
            )
        )
    ) {
        throw "PromotionCommit is not merged into $ReleaseBranch."
    }
    $retainedBranches = @($existingRecord.approved_branches)
}

foreach ($branchName in @($retainedBranches) + @($requestedBranches)) {
    if ([string]::IsNullOrWhiteSpace($branchName)) {
        throw "Approved branch entries must not be empty."
    }
    if (-not $approvedBranchSet.ContainsKey($branchName)) {
        $approvedBranchSet[$branchName] = $true
        $approvedBranches += $branchName
    }
}

foreach ($branchName in $approvedBranches) {
    if (Test-IsProtectedBranch $branchName) {
        continue
    }

    if (-not (Test-GitSuccess @("rev-parse", "--verify", "$branchName^{commit}"))) {
        continue
    }
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

if ($findings.Count -eq 0) {
    if ($RecordPromotion -and $approvedBranches.Count -gt 0) {
        Write-PromotionRecord `
            -RecordPath $promotionRecordPath `
            -Branches $approvedBranches
    }
    if (
        $CleanMergedBranches -and
        -not [string]::IsNullOrWhiteSpace($promotionRecordPath)
    ) {
        Remove-Item -LiteralPath $promotionRecordPath
    }
    $reportedPromotionRecord = ""
    if (
        -not [string]::IsNullOrWhiteSpace($promotionRecordPath) -and
        (Test-Path -LiteralPath $promotionRecordPath -PathType Leaf)
    ) {
        $reportedPromotionRecord = $promotionRecordPath
    }
    [pscustomobject]@{
        status = "ready"
        approved_branches = $approvedBranches
        removed = @($removed | ForEach-Object { $_.Branch })
        promotion_record = $reportedPromotionRecord
    } | ConvertTo-Json -Compress -Depth 4
    exit 0
}

[pscustomobject]@{
    status = "blocked"
    findings = $findings
    promotion_record = $promotionRecordPath
} | ConvertTo-Json -Compress -Depth 4
exit 2
