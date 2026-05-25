[CmdletBinding()]
param(
    [string]$SkillsRepoRoot,
    [string]$ReleaseBranch = "release/local",
    [string]$BaseBranch = "main",
    [string]$RemoteName = "origin",
    [string]$Title,
    [string]$Body
)

# Skill-local helper for the deterministic publication part of ship-to-remote.
# It pushes the staged release branch, creates the PR when absent, reuses it
# when present, and emits only a compact PR summary on success.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($SkillsRepoRoot)) {
    $SkillsRepoRoot = (Get-Location).Path
}

$resolvedSkillsRepoRoot = (Resolve-Path -LiteralPath $SkillsRepoRoot).Path

function Invoke-QuietNative {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory = $resolvedSkillsRepoRoot,
        [switch]$ReturnOutput,
        [switch]$AllowFailure
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

    if ($exitCode -ne 0 -and -not $AllowFailure) {
        $tail = @($output | Select-Object -Last 8) -join "`n"
        if (-not [string]::IsNullOrWhiteSpace($tail)) {
            throw "$FilePath failed: $($Arguments -join ' ')`n$tail"
        }
        throw "$FilePath failed: $($Arguments -join ' ')"
    }

    if ($AllowFailure) {
        return [pscustomobject]@{
            ExitCode = $exitCode
            Output = @($output)
        }
    }
    if ($ReturnOutput) {
        return @($output)
    }
}

function Get-GitLines {
    param([string[]]$Arguments)

    return @(Invoke-QuietNative -FilePath "git" -Arguments (@("-C", $resolvedSkillsRepoRoot) + $Arguments) -ReturnOutput)
}

function Assert-CleanWorktree {
    $status = @(Get-GitLines @("status", "--porcelain"))
    if ($status.Count -gt 0) {
        throw "Refusing to publish because the worktree is dirty."
    }
}

function Get-CheckSummary {
    param($StatusCheckRollup)

    $summary = [ordered]@{}
    foreach ($check in @($StatusCheckRollup)) {
        $state = $null
        foreach ($propertyName in @("conclusion", "status", "state")) {
            if ($check.PSObject.Properties.Name -contains $propertyName) {
                $value = [string]$check.$propertyName
                if (-not [string]::IsNullOrWhiteSpace($value)) {
                    $state = $value
                    break
                }
            }
        }
        if ([string]::IsNullOrWhiteSpace($state)) {
            $state = "UNKNOWN"
        }
        if (-not $summary.Contains($state)) {
            $summary[$state] = 0
        }
        $summary[$state] += 1
    }
    return [pscustomobject]$summary
}

$currentBranch = (Get-GitLines @("branch", "--show-current") | Select-Object -First 1).Trim()
if ($currentBranch -ne $ReleaseBranch) {
    throw "Expected active branch '$ReleaseBranch', got '$currentBranch'."
}
Assert-CleanWorktree

$aheadCount = [int]((Get-GitLines @("rev-list", "--count", "$BaseBranch..HEAD") | Select-Object -First 1).Trim())
if ($aheadCount -le 0) {
    throw "Release branch '$ReleaseBranch' is not ahead of '$BaseBranch'."
}

Invoke-QuietNative -FilePath "git" -Arguments @("-C", $resolvedSkillsRepoRoot, "push", "-u", $RemoteName, "$ReleaseBranch`:$ReleaseBranch")

$viewArgs = @(
    "pr",
    "view",
    $ReleaseBranch,
    "--json",
    "number,url,headRefOid,changedFiles,state,isDraft,statusCheckRollup"
)
$viewResult = Invoke-QuietNative -FilePath "gh" -Arguments $viewArgs -ReturnOutput -AllowFailure
if ($viewResult.ExitCode -ne 0) {
    if ([string]::IsNullOrWhiteSpace($Title)) {
        $Title = "Ship staged skill release"
    }
    if ([string]::IsNullOrWhiteSpace($Body)) {
        $Body = "Staged skill lifecycle release branch."
    }
    Invoke-QuietNative -FilePath "gh" -Arguments @(
        "pr",
        "create",
        "--base",
        $BaseBranch,
        "--head",
        $ReleaseBranch,
        "--title",
        $Title,
        "--body",
        $Body
    )
} elseif (-not [string]::IsNullOrWhiteSpace($Title) -or -not [string]::IsNullOrWhiteSpace($Body)) {
    $editArgs = @("pr", "edit", $ReleaseBranch)
    if (-not [string]::IsNullOrWhiteSpace($Title)) {
        $editArgs += @("--title", $Title)
    }
    if (-not [string]::IsNullOrWhiteSpace($Body)) {
        $editArgs += @("--body", $Body)
    }
    Invoke-QuietNative -FilePath "gh" -Arguments $editArgs
}

$pr = (Invoke-QuietNative -FilePath "gh" -Arguments $viewArgs -ReturnOutput | Out-String | ConvertFrom-Json)
[pscustomobject]@{
    status = "pr_ready"
    pr = $pr.number
    url = $pr.url
    head = $pr.headRefOid
    changed_files = $pr.changedFiles
    state = $pr.state
    draft = $pr.isDraft
    checks = Get-CheckSummary $pr.statusCheckRollup
} | ConvertTo-Json -Compress
