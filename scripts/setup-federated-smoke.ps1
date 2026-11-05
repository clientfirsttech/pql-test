# SPDX-License-Identifier: AGPL-3.0-only
#requires -Version 7
<#
.SYNOPSIS
  One-time setup for .github/workflows/federated-smoke.yml.

.DESCRIPTION
  1. Adds a federated credential to the app registration that trusts this repository's
     GitHub Environment (subject repo:<owner>/<repo>:environment:<environment>), Azure CLI.
  2. Creates the GitHub Environment `federated-smoke` (with a required reviewer when the
     plan allows it) and sets the variables PQL_TENANT_ID, PQL_CLIENT_ID, PQL_WORKSPACE_ID
     on it, GitHub CLI. No secret is involved: that is the point of federated credentials.

  Needs: `az login` as an owner of the app registration, and `gh auth login` with admin
  rights on the repository. Run with -DryRun first.

.EXAMPLE
  ./scripts/setup-federated-smoke.ps1 -AppId <client-id> -TenantId <tenant-id> `
      -WorkspaceId <workspace-guid> -Reviewer kerski-cft -DryRun
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $AppId,
    [Parameter(Mandatory)] [string] $TenantId,
    [Parameter(Mandatory)] [string] $WorkspaceId,
    [string] $Repo = 'clientfirsttech/pql-test',
    [string] $Environment = 'federated-smoke',
    [string] $Reviewer,
    [switch] $SkipAzure,
    [switch] $DryRun
)

$ErrorActionPreference = 'Stop'

function Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }
function Run($text, [scriptblock] $action) {
    if ($DryRun) { Write-Host "[dry run] $text" -ForegroundColor Yellow } else { & $action }
}

foreach ($tool in @('gh') + $(if ($SkipAzure) { @() } else { @('az') })) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is not installed or not on PATH." }
}

# 1. Federated credential on the app registration: only jobs running in this Environment.
if (-not $SkipAzure) {
    $subject = "repo:${Repo}:environment:${Environment}"
    Step "Adding a federated credential to app $AppId for subject $subject"
    $parameters = @{
        name      = "github-$($Repo -replace '[^A-Za-z0-9]', '-')-$Environment"
        issuer    = 'https://token.actions.githubusercontent.com'
        subject   = $subject
        audiences = @('api://AzureADTokenExchange')
    } | ConvertTo-Json -Compress
    $file = Join-Path ([IO.Path]::GetTempPath()) "pql-test-federated-$([guid]::NewGuid()).json"
    try {
        Run "az ad app federated-credential create --id $AppId --parameters @<file> ($subject)" {
            Set-Content -Path $file -Value $parameters -NoNewline    # no secret in it
            az ad app federated-credential create --id $AppId --parameters "@$file" --only-show-errors | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'az ad app federated-credential create failed (already exists, or you are not an owner of the app registration?).' }
        }
    } finally {
        Remove-Item -Path $file -Force -ErrorAction SilentlyContinue
    }
}

# 2. GitHub Environment and variables.
Step "Creating the GitHub Environment '$Environment' in $Repo"
$body = @{}
if ($Reviewer) {
    $reviewerId = if ($DryRun) { 0 } else { [int](gh api "users/$Reviewer" --jq .id) }
    $body.reviewers = @(@{ type = 'User'; id = $reviewerId })
}
Run "gh api -X PUT repos/$Repo/environments/$Environment (reviewer: $(if ($Reviewer) { $Reviewer } else { 'none' }))" {
    $body | ConvertTo-Json -Depth 4 | gh api -X PUT "repos/$Repo/environments/$Environment" --input - | Out-Null
    if ($LASTEXITCODE -ne 0 -and $Reviewer) {
        Write-Warning 'Could not set the required reviewer (private repositories need a paid plan for that). Creating the Environment without one.'
        '{}' | gh api -X PUT "repos/$Repo/environments/$Environment" --input - | Out-Null
    }
}

Step 'Setting the variables PQL_TENANT_ID, PQL_CLIENT_ID, PQL_WORKSPACE_ID'
foreach ($pair in @(@('PQL_TENANT_ID', $TenantId), @('PQL_CLIENT_ID', $AppId), @('PQL_WORKSPACE_ID', $WorkspaceId))) {
    Run "gh variable set $($pair[0]) --env $Environment --repo $Repo" {
        gh variable set $pair[0] --body $pair[1] --env $Environment --repo $Repo
        if ($LASTEXITCODE -ne 0) { throw "gh variable set $($pair[0]) failed." }
    }
}

Step 'Done. Run the workflow: Actions > "Federated credential smoke test" > Run workflow.'
