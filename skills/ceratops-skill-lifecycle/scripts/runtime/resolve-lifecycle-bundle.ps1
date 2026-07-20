function Resolve-CeratopsLifecycleBundle {
    <#
    .SYNOPSIS
    Selects one lifecycle helper bundle for a target-repository operation.

    .DESCRIPTION
    A supported installed runtime bundle is authoritative for multi-repository
    work. The caller-provided checkout bundle is the bootstrap fallback. The
    runtime-manifest schema is a capability boundary: legacy installed copies
    are not used for source-scoped installation.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$CheckoutBundleRoot
    )

    $codexHome = $env:CODEX_HOME
    if ([string]::IsNullOrWhiteSpace($codexHome)) {
        foreach ($candidate in @($env:USERPROFILE, $env:HOME)) {
            if (-not [string]::IsNullOrWhiteSpace($candidate)) {
                $codexHome = Join-Path $candidate ".codex"
                break
            }
        }
    }
    if ([string]::IsNullOrWhiteSpace($codexHome)) {
        throw "Could not resolve Codex home. Set CODEX_HOME."
    }

    $installedBundleRoot = Join-Path (Join-Path $codexHome "skills") "ceratops-skill-lifecycle"
    $runtimeManifest = Join-Path $installedBundleRoot ".runtime-manifest.json"
    if (Test-Path -LiteralPath $runtimeManifest -PathType Leaf) {
        try {
            $data = Get-Content -LiteralPath $runtimeManifest -Raw | ConvertFrom-Json
            if ($data.schema -eq "ceratops-runtime-skill.v2" -and $data.skill -eq "ceratops-skill-lifecycle") {
                return $installedBundleRoot
            }
        } catch {
            # An unreadable or legacy installed bundle is not a supported helper
            # source; the explicit checkout remains the bootstrap fallback.
        }
    }

    return $CheckoutBundleRoot
}
