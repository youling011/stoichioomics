param(
    [ValidateSet('start','status','logs','stop','restart','readonly','build','clear-quality-cache')]
    [string]$Action = 'status'
)
$ErrorActionPreference = 'Stop'
$repository = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
Push-Location $repository
try {
    if (-not (Test-Path -LiteralPath '.env')) { throw 'Copy .env.example to .env and configure the private deployment first.' }
    $compose = @('compose','--env-file','.env','-f','compose.yaml')
    if ($Action -in @('stop','restart','readonly')) {
        & docker @compose exec -T app python -B deploy/tools/task_guard.py
        if ($LASTEXITCODE -ne 0) { throw 'Task guard failed; stop/restart refused.' }
    }
    switch ($Action) {
        'start' { & docker @compose up -d app nginx }
        'status' { & docker @compose ps }
        'logs' { & docker @compose logs --tail 100 app nginx }
        'stop' { & docker @compose stop nginx app }
        'restart' {
            & docker @compose stop nginx app
            if ($LASTEXITCODE -ne 0) { throw 'Stop failed.' }
            & docker @compose up -d app nginx
        }
        'readonly' {
            & docker @compose stop nginx app
            if ($LASTEXITCODE -ne 0) { throw 'Stop failed.' }
            $environmentPath = Join-Path $repository '.env'
            $environmentText = [IO.File]::ReadAllText($environmentPath)
            if ($environmentText -match '(?m)^STOICH_LOCAL_READ_ONLY=') {
                $environmentText = [regex]::Replace($environmentText, '(?m)^STOICH_LOCAL_READ_ONLY=.*$', 'STOICH_LOCAL_READ_ONLY=1')
            } else { $environmentText += "`nSTOICH_LOCAL_READ_ONLY=1`n" }
            [IO.File]::WriteAllText($environmentPath, $environmentText, [Text.UTF8Encoding]::new($false))
            & docker @compose up -d app nginx
        }
        'build' { & docker @compose build app nginx }
        'clear-quality-cache' { & docker @compose exec -T nginx find /var/cache/nginx/stoich_quality -type f -delete }
    }
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose action failed: $Action" }
} finally { Pop-Location }
