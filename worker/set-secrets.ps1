param()

$ErrorActionPreference = "Stop"

function Require-Command {
    param([string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Command not found: $Name"
    }
}

function Read-SecretValue {
    param(
        [string]$Name,
        [string]$Prompt,
        [string]$Default = ""
    )

    if ($Default) {
        $fullPrompt = "$Prompt [$Default]"
    }
    else {
        $fullPrompt = $Prompt
    }

    $value = Read-Host $fullPrompt
    if ([string]::IsNullOrWhiteSpace($value)) {
        return $Default
    }

    return $value.Trim()
}

function Set-WranglerSecret {
    param(
        [string]$Name,
        [string]$Value
    )

    if ($null -eq $Value) {
        $Value = ""
    }

    $Value | npx wrangler secret put $Name
}

Require-Command "npx"

$secrets = @(
    @{
        Name = "GH_TOKEN"
        Prompt = "GitHub fine-grained token"
        Default = ""
    },
    @{
        Name = "GH_OWNER"
        Prompt = "GitHub owner (user or org)"
        Default = ""
    },
    @{
        Name = "GH_REPO"
        Prompt = "GitHub repository name"
        Default = "roblox-top100-fetcher"
    },
    @{
        Name = "GH_WORKFLOW_FILE"
        Prompt = "GitHub workflow file"
        Default = "roblox_rank_sync.yml"
    },
    @{
        Name = "GH_REF"
        Prompt = "GitHub branch/ref"
        Default = "main"
    },
    @{
        Name = "FEISHU_APP_ID"
        Prompt = "Feishu App ID"
        Default = ""
    },
    @{
        Name = "FEISHU_APP_SECRET"
        Prompt = "Feishu App Secret"
        Default = ""
    },
    @{
        Name = "FEISHU_VERIFICATION_TOKEN"
        Prompt = "Feishu Verification Token"
        Default = ""
    },
    @{
        Name = "ALLOWED_CHAT_IDS"
        Prompt = "Allowed chat IDs (comma separated, blank means allow all)"
        Default = ""
    },
    @{
        Name = "ALLOWED_OPEN_IDS"
        Prompt = "Allowed user open IDs (comma separated, blank means allow all)"
        Default = ""
    }
)

Write-Host "Setting Wrangler secrets for roblox-top100-feishu-trigger"
Write-Host "Make sure you already ran: npx wrangler login"

foreach ($item in $secrets) {
    $value = Read-SecretValue -Name $item.Name -Prompt $item.Prompt -Default $item.Default
    Set-WranglerSecret -Name $item.Name -Value $value
}

Write-Host ""
Write-Host "Secrets updated."
Write-Host "Next step: run 'npx wrangler deploy'"
