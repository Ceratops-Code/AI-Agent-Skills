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

function Invoke-PromotionMypy {
    # Preserve repository-configured mypy validation while turning its one
    # predictable configuration failure into a compact decision payload.
    try {
        Invoke-QuietNative -FilePath "python" -Arguments @("-m", "mypy")
        return
    } catch {
        $failureMessage = [string]$_.Exception.Message
    }

    $configMarkers = [ordered]@{
        "mypy.ini" = "(?m)^\s*\[mypy\]\s*(?:[#;].*)?$"
        ".mypy.ini" = "(?m)^\s*\[mypy\]\s*(?:[#;].*)?$"
        "pyproject.toml" = "(?m)^\s*\[tool\.mypy\]\s*(?:#.*)?$"
        "setup.cfg" = "(?m)^\s*\[mypy\]\s*(?:[#;].*)?$"
    }
    $configFiles = @(
        foreach ($candidate in $configMarkers.Keys) {
            $candidatePath = Join-Path $resolvedSkillsRepoRoot $candidate
            if (Test-Path -LiteralPath $candidatePath -PathType Leaf) {
                $candidateText = Get-Content -LiteralPath $candidatePath -Raw
                if ($candidateText -match $configMarkers[$candidate]) {
                    $candidate
                }
            }
        }
    )
    if ($failureMessage -match "Missing target module, package, files, or command") {
        $classification = if ($configFiles.Count -eq 0) {
            "mypy_scope_missing"
        } else {
            "mypy_scope_mismatch"
        }
    } else {
        $classification = "mypy_failed"
    }
    $outputTail = @($failureMessage -split "\r?\n" | Select-Object -Last 8) -join "`n"
    $payload = [ordered]@{
        status = "blocked"
        blocker = "promotion_mypy"
        classification = $classification
        command = "python -m mypy"
        config_files = $configFiles
        output_tail = $outputTail
    } | ConvertTo-Json -Compress
    [Console]::Error.WriteLine($payload)
    exit 1
}

function Get-RepositoryInstallerVersion {
    param([string]$InstallerScript)

    $installerText = Get-Content -LiteralPath $InstallerScript -Raw
    $versionMatch = [regex]::Match(
        $installerText,
        "(?m)^INSTALLER_VERSION\s*=\s*(\d+)\s*$"
    )
    if (-not $versionMatch.Success) {
        throw "Repository installer does not declare INSTALLER_VERSION."
    }
    return [int]$versionMatch.Groups[1].Value
}

function Get-DefaultRuntimeSkillsRoot {
    # Match the Python runtime installer's default while making the rollback
    # target explicit for both bootstrap and full-install commands.
    if (-not [string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
        $codexHome = $env:CODEX_HOME
        if (-not [IO.Path]::IsPathRooted($codexHome)) {
            $codexHome = Join-Path $resolvedSkillsRepoRoot $codexHome
        }
    } else {
        $codexHome = Join-Path (
            [Environment]::GetFolderPath(
                [Environment+SpecialFolder]::UserProfile
            )
        ) ".codex"
    }
    return [IO.Path]::GetFullPath((Join-Path $codexHome "skills"))
}

function New-LifecycleRuntimeRollback {
    param([string]$RuntimeSkillsRoot)

    # Keep the recoverable snapshot under the repository's declared task-temp
    # hierarchy and reject filesystem indirection before copying runtime state.
    $projectName = Split-Path -Leaf $resolvedSkillsRepoRoot
    $projectParent = Split-Path -Parent $resolvedSkillsRepoRoot
    $rollbackParent = Join-Path (
        Join-Path $projectParent "tmp"
    ) $projectName
    $rollbackRoot = Join-Path $rollbackParent (
        "promotion-runtime-rollback-$([guid]::NewGuid().ToString('N'))"
    )
    $installedPath = Join-Path `
        $RuntimeSkillsRoot `
        "ceratops-skill-lifecycle"
    $backupPath = Join-Path $rollbackRoot "ceratops-skill-lifecycle"
    $hadPriorRuntime = Test-Path -LiteralPath $installedPath

    $null = New-Item -ItemType Directory -Force -Path $rollbackRoot
    try {
        if ($hadPriorRuntime) {
            if (-not (Test-Path -LiteralPath $installedPath -PathType Container)) {
                throw "Installed lifecycle runtime is not a directory: $installedPath"
            }
            $installedItem = Get-Item -LiteralPath $installedPath -Force
            if (
                ($installedItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
            ) {
                throw "Refusing to snapshot a reparse-point lifecycle runtime: $installedPath"
            }
            Copy-Item `
                -LiteralPath $installedPath `
                -Destination $backupPath `
                -Recurse
        }
    } catch {
        Remove-Item -LiteralPath $rollbackRoot -Recurse -Force
        throw
    }

    return [pscustomobject]@{
        RuntimeSkillsRoot = $RuntimeSkillsRoot
        InstalledPath = $installedPath
        BackupRoot = $rollbackRoot
        BackupPath = $backupPath
        HadPriorRuntime = $hadPriorRuntime
    }
}

function Remove-LifecycleRuntimeRollback {
    param([pscustomobject]$Rollback)

    if (Test-Path -LiteralPath $Rollback.BackupRoot) {
        Remove-Item -LiteralPath $Rollback.BackupRoot -Recurse -Force
    }
}

function Restore-LifecycleRuntimeRollback {
    param([pscustomobject]$Rollback)

    # The target and backup paths are created by New-LifecycleRuntimeRollback;
    # retain the backup and emit its exact path if recovery cannot complete.
    try {
        if (Test-Path -LiteralPath $Rollback.InstalledPath) {
            Remove-Item `
                -LiteralPath $Rollback.InstalledPath `
                -Recurse `
                -Force
        }
        if ($Rollback.HadPriorRuntime) {
            Move-Item `
                -LiteralPath $Rollback.BackupPath `
                -Destination $Rollback.InstalledPath
        }
        Remove-LifecycleRuntimeRollback $Rollback
    } catch {
        throw (
            "Lifecycle runtime rollback failed; recoverable state remains at " +
            "$($Rollback.BackupRoot): $($_.Exception.Message)"
        )
    }
}

function Invoke-LifecycleSourceBootstrap {
    param(
        [string]$ReleaseStartSha,
        [string]$PromotionHeadSha,
        [string]$InstallerScript,
        [string]$RuntimeSkillsRoot
    )

    # A lifecycle validator cannot validate its own replacement. When this
    # promotion changed lifecycle sources, install only that managed skill from
    # the staged source bundle before the ordinary installed-bundle full pass.
    $lifecycleSourcePath = "skills/ceratops-skill-lifecycle"
    $changedLifecyclePaths = @(
        Get-GitLines @(
            "diff",
            "--name-only",
            $ReleaseStartSha,
            $PromotionHeadSha,
            "--",
            $lifecycleSourcePath
        )
    )
    if ($changedLifecyclePaths.Count -eq 0) {
        return $null
    }

    $sourceRuntimeInstaller = Join-Path `
        $resolvedSkillsRepoRoot `
        "$lifecycleSourcePath\scripts\runtime\install-managed-skills.py"
    if (-not (Test-Path -LiteralPath $sourceRuntimeInstaller -PathType Leaf)) {
        throw "Missing staged lifecycle runtime installer: $sourceRuntimeInstaller"
    }
    $installerVersion = Get-RepositoryInstallerVersion $InstallerScript
    $rollback = New-LifecycleRuntimeRollback $RuntimeSkillsRoot
    try {
        Invoke-QuietNative -FilePath "python" -Arguments @(
            $sourceRuntimeInstaller,
            "--repo-root",
            $resolvedSkillsRepoRoot,
            "--install-root",
            $RuntimeSkillsRoot,
            "--installer-version",
            [string]$installerVersion,
            "--skill",
            "ceratops-skill-lifecycle"
        )
    } catch {
        $bootstrapFailure = $_
        Restore-LifecycleRuntimeRollback $rollback
        throw $bootstrapFailure
    }
    return $rollback
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

$releaseStartSha = (Get-GitLines @("rev-parse", "HEAD") |
    Select-Object -First 1).Trim()
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

Invoke-PromotionMypy

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

$runtimeSkillsRoot = Get-DefaultRuntimeSkillsRoot
$lifecycleRollback = Invoke-LifecycleSourceBootstrap `
    -ReleaseStartSha $releaseStartSha `
    -PromotionHeadSha $headSha `
    -InstallerScript $installScript `
    -RuntimeSkillsRoot $runtimeSkillsRoot
try {
    Invoke-QuietNative -FilePath "python" -Arguments @(
        $installScript,
        "--repo-root",
        $resolvedSkillsRepoRoot,
        "--install-root",
        $runtimeSkillsRoot
    )
} catch {
    $installFailure = $_
    if ($null -ne $lifecycleRollback) {
        Restore-LifecycleRuntimeRollback $lifecycleRollback
    }
    throw $installFailure
}
if ($null -ne $lifecycleRollback) {
    Remove-LifecycleRuntimeRollback $lifecycleRollback
}
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
