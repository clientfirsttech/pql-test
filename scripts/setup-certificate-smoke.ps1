#requires -Version 7
<#
.SYNOPSIS
  One-time setup for .github/workflows/certificate-smoke.yml.

.DESCRIPTION
  1. Creates a self-signed certificate in memory (the private key is never written to disk).
  2. Uploads the public certificate to the app registration (Azure CLI).
  3. Creates the GitHub Environment `certificate-smoke` (with a required reviewer when the
     plan allows it) and sets the secret PQL_CERT_PEM and the variables PQL_TENANT_ID,
     PQL_CLIENT_ID, PQL_WORKSPACE_ID on it (GitHub CLI).

  Needs: `az login` as an owner of the app registration, and `gh auth login` with admin
  rights on the repository. Run with -DryRun first to see what it would do.

.EXAMPLE
  ./scripts/setup-certificate-smoke.ps1 -AppId <client-id> -TenantId <tenant-id> `
      -WorkspaceId <workspace-guid> -Repo clientfirsttech/pql-test -Reviewer kerski-cft -DryRun

.EXAMPLE
  # Test the expiry warning: a certificate that is valid for 10 days.
  ./scripts/setup-certificate-smoke.ps1 -AppId ... -TenantId ... -WorkspaceId ... -DaysValid 10
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $AppId,        # the app registration's application (client) ID
    [Parameter(Mandatory)] [string] $TenantId,
    [Parameter(Mandatory)] [string] $WorkspaceId,
    [string] $Repo = 'clientfirsttech/pql-test',
    [string] $Environment = 'certificate-smoke',
    [string] $Reviewer,                            # GitHub login that must approve runs (optional)
    [int] $DaysValid = 365,
    [switch] $SkipAzure,                           # only do the GitHub half (certificate already uploaded)
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

# 1. Certificate, in memory only.
Step "Creating a self-signed certificate valid for $DaysValid day(s)"
$rsa = [System.Security.Cryptography.RSA]::Create(2048)
$request = [System.Security.Cryptography.X509Certificates.CertificateRequest]::new(
    'CN=pql-test-ci', $rsa,
    [System.Security.Cryptography.HashAlgorithmName]::SHA256,
    [System.Security.Cryptography.RSASignaturePadding]::Pkcs1)
$certificate = $request.CreateSelfSigned([DateTimeOffset]::UtcNow.AddMinutes(-5), [DateTimeOffset]::UtcNow.AddDays($DaysValid))
$publicPem = $certificate.ExportCertificatePem()
$privatePem = $rsa.ExportPkcs8PrivateKeyPem() + "`n" + $publicPem    # key + certificate, no password
Write-Host "    thumbprint $($certificate.Thumbprint), expires $($certificate.NotAfter.ToUniversalTime().ToString('yyyy-MM-dd')) UTC"

# 2. Upload the PUBLIC certificate to the app registration.
if (-not $SkipAzure) {
    Step "Adding the public certificate to app $AppId (existing credentials are kept)"
    $publicFile = Join-Path ([IO.Path]::GetTempPath()) "pql-test-ci-$($certificate.Thumbprint).cer.pem"
    try {
        Run "az ad app credential reset --id $AppId --append --cert @<public certificate file>" {
            Set-Content -Path $publicFile -Value $publicPem -NoNewline
            az ad app credential reset --id $AppId --append --cert "@$publicFile" --only-show-errors | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'az ad app credential reset failed (are you an owner of the app registration?).' }
        }
    } finally {
        Remove-Item -Path $publicFile -Force -ErrorAction SilentlyContinue
    }
}

# 3. GitHub Environment, secret, variables.
Step "Creating the GitHub Environment '$Environment' in $Repo"
$body = @{}
if ($Reviewer) {
    $reviewerId = if ($DryRun) { 0 } else { [int](gh api "users/$Reviewer" --jq .id) }
    $body.reviewers = @(@{ type = 'User'; id = $reviewerId })
}
Run "gh api -X PUT repos/$Repo/environments/$Environment (reviewer: $(if ($Reviewer) { $Reviewer } else { 'none' }))" {
    $json = $body | ConvertTo-Json -Depth 4
    $json | gh api -X PUT "repos/$Repo/environments/$Environment" --input - | Out-Null
    if ($LASTEXITCODE -ne 0 -and $Reviewer) {
        Write-Warning 'Could not set the required reviewer (private repositories need a paid plan for that). Creating the Environment without one.'
        '{}' | gh api -X PUT "repos/$Repo/environments/$Environment" --input - | Out-Null
    }
}

Step 'Setting the secret PQL_CERT_PEM (piped to gh; never written to disk or printed)'
Run "gh secret set PQL_CERT_PEM --env $Environment --repo $Repo" {
    $privatePem | gh secret set PQL_CERT_PEM --env $Environment --repo $Repo
    if ($LASTEXITCODE -ne 0) { throw 'gh secret set failed.' }
}

Step 'Setting the variables PQL_TENANT_ID, PQL_CLIENT_ID, PQL_WORKSPACE_ID'
foreach ($pair in @(@('PQL_TENANT_ID', $TenantId), @('PQL_CLIENT_ID', $AppId), @('PQL_WORKSPACE_ID', $WorkspaceId))) {
    Run "gh variable set $($pair[0]) --env $Environment --repo $Repo" {
        gh variable set $pair[0] --body $pair[1] --env $Environment --repo $Repo
        if ($LASTEXITCODE -ne 0) { throw "gh variable set $($pair[0]) failed." }
    }
}

$privatePem = $null
Step 'Done. Run the workflow: Actions > "Certificate smoke test" > Run workflow (it must be on the default branch).'
if ($DaysValid -le 30) { Write-Host "    The certificate expires in $DaysValid day(s), so 'auth status' should print the expiry warning." }
