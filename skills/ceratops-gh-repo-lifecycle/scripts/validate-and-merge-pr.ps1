[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Pr,
    [string]$RepoRoot,
    [string]$Repo,
    [ValidateSet("merge", "squash", "rebase")]
    [string]$MergeMethod = "merge",
    [switch]$Admin,
    [switch]$Auto,
    [switch]$DeleteBranch,
    [int]$WaitSeconds = 260,
    [int]$IntervalSeconds = 10
)

# Skill-local helper for the deterministic merge-pr path. It runs the readiness
# validator, waits for the Codex review gate, performs the requested gh merge,
# verifies the live PR state, and emits one compact JSON summary.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (Get-Location).Path
}
$resolvedRepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path

function Resolve-ValidationScript {
    param([string]$Name)

    $scriptPath = Join-Path $PSScriptRoot $Name
    if (Test-Path -LiteralPath $scriptPath) {
        return $scriptPath
    }
    throw "Missing validation script: $Name"
}

function Invoke-QuietNative {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory = $resolvedRepoRoot,
        [switch]$ReturnOutput
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
    if ($ReturnOutput) {
        return @($output)
    }
}

$readinessScript = Resolve-ValidationScript "github-validate-pr-readiness-contract.py"
$reviewGateScript = Resolve-ValidationScript "github-codex-review-gate.py"

$readinessArgs = @($readinessScript, "--pr", $Pr)
if ($Admin) {
    $readinessArgs += "--allow-admin-review-bypass"
}
Invoke-QuietNative -FilePath "python" -Arguments $readinessArgs

Invoke-QuietNative -FilePath "python" -Arguments @(
    $reviewGateScript,
    "wait",
    "--pr",
    $Pr,
    "--wait-seconds",
    [string]$WaitSeconds,
    "--interval-seconds",
    [string]$IntervalSeconds,
    "--json"
)

# The PR head or checks can change while the review gate waits. Revalidate the
# live head immediately before issuing the merge mutation.
Invoke-QuietNative -FilePath "python" -Arguments $readinessArgs

$ghArgs = @("pr", "merge", $Pr, "--$MergeMethod")
if ($Admin) {
    $ghArgs += "--admin"
}
if ($Auto) {
    $ghArgs += "--auto"
}
if ($DeleteBranch) {
    $ghArgs += "--delete-branch"
}
if (-not [string]::IsNullOrWhiteSpace($Repo)) {
    $ghArgs += @("--repo", $Repo)
}

$mergeWorkingDirectory = $resolvedRepoRoot
if (-not [string]::IsNullOrWhiteSpace($Repo) -and -not [string]::IsNullOrWhiteSpace($env:CODEX_HOME) -and (Test-Path -LiteralPath $env:CODEX_HOME)) {
    $mergeWorkingDirectory = $env:CODEX_HOME
}
Invoke-QuietNative -FilePath "gh" -Arguments $ghArgs -WorkingDirectory $mergeWorkingDirectory

$viewArgs = @("pr", "view", $Pr, "--json", "number,url,state,mergedAt,mergeCommit")
if (-not [string]::IsNullOrWhiteSpace($Repo)) {
    $viewArgs += @("--repo", $Repo)
}
$prState = (Invoke-QuietNative -FilePath "gh" -Arguments $viewArgs -WorkingDirectory $mergeWorkingDirectory -ReturnOutput | Out-String | ConvertFrom-Json)

if (-not $Auto -and $prState.state -ne "MERGED") {
    throw "PR merge was not verified; live state is $($prState.state)."
}

$status = if ($prState.state -eq "MERGED") { "merged" } else { "auto_merge_enabled" }
[pscustomobject]@{
    status = $status
    pr = $prState.number
    url = $prState.url
    state = $prState.state
    merged_at = $prState.mergedAt
    merge_commit = if ($null -ne $prState.mergeCommit) { $prState.mergeCommit.oid } else { $null }
} | ConvertTo-Json -Compress
