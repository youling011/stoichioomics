param(
    [string]$SourceContainer = "stoichioomics-postgres-docker",
    [string]$TargetContainer = "stoichioomics-postgres-named",
    [string]$TargetVolume = "stoichioomics_pg16_named_data",
    [string]$PostgresImage = "postgres:16",
    [string]$Database = "stoichioomics",
    [string]$User = "postgres",
    [string]$Password = $env:POSTGRES_PASSWORD,
    [int]$HostPort = 5432,
    [string]$DumpDir = "runtime\db_migration",
    [switch]$ReplaceTargetContainer,
    [switch]$AllowExistingTargetVolume,
    [switch]$KeepSourceRunning,
    [switch]$CleanupIncompleteOnly
)

$ErrorActionPreference = "Stop"

$script:TotalSteps = 10
$script:CurrentStep = 0

function Show-Step {
    param(
        [Parameter(Mandatory=$true)][string]$Status,
        [int]$Step = $script:CurrentStep,
        [string]$Activity = "PostgreSQL storage migration"
    )
    $percent = [Math]::Min(100, [Math]::Max(0, [int](($Step / $script:TotalSteps) * 100)))
    Write-Progress -Activity $Activity -Status $Status -PercentComplete $percent
    Write-Host ("[{0}/{1}] {2}" -f $Step, $script:TotalSteps, $Status)
}

function Complete-Progress {
    param([string]$Activity = "PostgreSQL storage migration")
    Write-Progress -Activity $Activity -Completed
}

function Run-Docker {
    param([Parameter(Mandatory=$true)][string[]]$Args)
    & docker @Args
    if ($LASTEXITCODE -ne 0) {
        throw "docker $($Args -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Run-DockerWithElapsed {
    param(
        [Parameter(Mandatory=$true)][string[]]$Args,
        [Parameter(Mandatory=$true)][string]$Status,
        [int]$Step = $script:CurrentStep,
        [string]$Activity = "PostgreSQL storage migration",
        [string]$MonitorContainer = "",
        [string]$MonitorPath = ""
    )
    $job = Start-Job -ScriptBlock {
        param([string[]]$DockerArgs)
        $outputLines = & docker @DockerArgs 2>&1 | ForEach-Object { $_.ToString() }
        $code = $LASTEXITCODE
        [pscustomobject]@{
            ExitCode = $code
            Output = ($outputLines -join [Environment]::NewLine)
        }
    } -ArgumentList (,$Args)
    $startedAt = Get-Date
    while ($job.State -eq "Running") {
        $elapsedSeconds = [int]((Get-Date) - $startedAt).TotalSeconds
        $percent = [Math]::Min(99, [Math]::Max(1, [int](($Step / $script:TotalSteps) * 100)))
        $detail = "$Status; elapsed ${elapsedSeconds}s"
        if ($MonitorContainer -and $MonitorPath -and ($elapsedSeconds % 10 -eq 0)) {
            $sizeText = & docker exec $MonitorContainer sh -c "if [ -f '$MonitorPath' ]; then du -h '$MonitorPath' | cut -f1; fi" 2>$null
            if ($LASTEXITCODE -eq 0 -and "$sizeText".Trim()) {
                $detail = "$detail; file size $("$sizeText".Trim())"
            }
        }
        Write-Progress -Activity $Activity -Status $detail -PercentComplete $percent
        Start-Sleep -Seconds 2
        $job = Get-Job -Id $job.Id
    }
    $jobState = $job.State
    $result = Receive-Job -Job $job -Wait
    Remove-Job -Job $job -Force
    if ($jobState -eq "Failed") {
        throw "docker $($Args -join ' ') failed in background job"
    }
    if ($result.Output) {
        Write-Host $result.Output.TrimEnd()
    }
    $exitCode = $result.ExitCode
    if ($null -eq $exitCode) {
        $exitCode = 1
    }
    if ($exitCode -ne 0) {
        throw "docker $($Args -join ' ') failed with exit code $exitCode"
    }
}

function Docker-Output {
    param([Parameter(Mandatory=$true)][string[]]$Args)
    $output = & docker @Args
    if ($LASTEXITCODE -ne 0) {
        throw "docker $($Args -join ' ') failed with exit code $LASTEXITCODE"
    }
    return $output
}

function Wait-Postgres {
    param(
        [Parameter(Mandatory=$true)][string]$Container,
        [Parameter(Mandatory=$true)][string]$DatabaseName,
        [Parameter(Mandatory=$true)][string]$DbUser,
        [int]$TimeoutSeconds = 90
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        & docker exec $Container pg_isready -U $DbUser -d $DatabaseName | Out-Null
        if ($LASTEXITCODE -eq 0) {
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "PostgreSQL in container '$Container' did not become ready within $TimeoutSeconds seconds."
}

function Get-ContainerState {
    param([Parameter(Mandatory=$true)][string]$Container)
    try {
        $state = & docker inspect -f "{{.State.Status}}" $Container 2>$null
    } catch {
        return $null
    }
    if ($LASTEXITCODE -ne 0) {
        return $null
    }
    return "$state".Trim()
}

function Test-DockerVolumeExists {
    param([Parameter(Mandatory=$true)][string]$Volume)
    try {
        & docker volume inspect $Volume *> $null
    } catch {
        return $false
    }
    return ($LASTEXITCODE -eq 0)
}

function Remove-IncompleteTarget {
    param(
        [Parameter(Mandatory=$true)][string]$Container,
        [Parameter(Mandatory=$true)][string]$Volume,
        [Parameter(Mandatory=$true)][string]$DumpRoot
    )
    $state = Get-ContainerState $Container
    if ($state) {
        Write-Host "Stopping/removing incomplete target container: $Container"
        & docker stop $Container *> $null
        & docker rm $Container *> $null
    } else {
        Write-Host "No incomplete target container found: $Container"
    }

    if (Test-DockerVolumeExists $Volume) {
        Write-Host "Removing incomplete target volume: $Volume"
        & docker volume rm $Volume
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to remove target volume '$Volume'. Make sure no container is using it."
        }
    } else {
        Write-Host "No incomplete target volume found: $Volume"
    }

    if (Test-Path $DumpRoot) {
        Get-ChildItem $DumpRoot -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '\.(tmp|partial|restore_in_progress)$' -or $_.Length -eq 0 } |
            Remove-Item -Force
    }
}

function Get-ExactCounts {
    param(
        [Parameter(Mandatory=$true)][string]$Container,
        [Parameter(Mandatory=$true)][string]$DatabaseName,
        [Parameter(Mandatory=$true)][string]$DbUser
    )
    $tableSql = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name;"
    $tables = Docker-Output @("exec", $Container, "psql", "-U", $DbUser, "-d", $DatabaseName, "-At", "-c", $tableSql)
    $rows = New-Object System.Collections.Generic.List[string]
    foreach ($table in $tables) {
        $tableName = "$table".Trim()
        if (-not $tableName) {
            continue
        }
        $quotedTableName = $tableName.Replace('"', '""')
        $countSql = "SELECT COUNT(*) FROM public.`"$quotedTableName`";"
        $count = Docker-Output @("exec", $Container, "psql", "-U", $DbUser, "-d", $DatabaseName, "-At", "-c", $countSql)
        $rows.Add("$tableName,$("$count".Trim())")
    }
    return $rows
}

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$dumpRoot = Join-Path $projectRoot $DumpDir
New-Item -ItemType Directory -Force -Path $dumpRoot | Out-Null

if ($CleanupIncompleteOnly) {
    $script:CurrentStep = 1
    Show-Step -Activity "PostgreSQL storage migration cleanup" -Status "Cleaning incomplete migration target artifacts"
    Remove-IncompleteTarget -Container $TargetContainer -Volume $TargetVolume -DumpRoot $dumpRoot
    Complete-Progress -Activity "PostgreSQL storage migration cleanup"
    Write-Host "Cleanup complete. Source container and bind-mounted PGDATA were not modified."
    return
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$containerDumpPath = "/tmp/${Database}_${timestamp}.dump"
$hostDumpPath = Join-Path $dumpRoot "${Database}_${timestamp}.dump"
$sourceCountsPath = Join-Path $dumpRoot "${Database}_${timestamp}.source_counts.csv"
$targetCountsPath = Join-Path $dumpRoot "${Database}_${timestamp}.target_counts.csv"

$sourceState = Get-ContainerState $SourceContainer
if (-not $sourceState) {
    throw "Source container '$SourceContainer' does not exist."
}
if ($sourceState -ne "running") {
    $script:CurrentStep = 1
    Show-Step -Status "Starting source container $SourceContainer"
    Run-Docker @("start", $SourceContainer)
}
$script:CurrentStep = 2
Show-Step -Status "Waiting for source PostgreSQL readiness"
Wait-Postgres -Container $SourceContainer -DatabaseName $Database -DbUser $User

$script:CurrentStep = 3
Show-Step -Status "Dumping source database from $SourceContainer"
Run-DockerWithElapsed -Args @("exec", $SourceContainer, "pg_dump", "-U", $User, "-d", $Database, "-Fc", "--no-owner", "--no-acl", "-f", $containerDumpPath) -Status "pg_dump is running" -Step $script:CurrentStep -MonitorContainer $SourceContainer -MonitorPath $containerDumpPath

$script:CurrentStep = 4
Show-Step -Status "Copying dump to host runtime directory"
Run-DockerWithElapsed -Args @("cp", "${SourceContainer}:${containerDumpPath}", $hostDumpPath) -Status "Copying dump file" -Step $script:CurrentStep
Run-Docker @("exec", $SourceContainer, "rm", "-f", $containerDumpPath)

$script:CurrentStep = 5
Show-Step -Status "Collecting source row counts"
"table,row_count" | Set-Content -Encoding ascii $sourceCountsPath
Get-ExactCounts -Container $SourceContainer -DatabaseName $Database -DbUser $User | Add-Content -Encoding ascii $sourceCountsPath

if (-not $KeepSourceRunning) {
    $script:CurrentStep = 6
    Show-Step -Status "Stopping source container $SourceContainer before target startup to free host port $HostPort"
    Write-Host "Stopping source container $SourceContainer before target startup to free host port $HostPort ..."
    Run-Docker @("stop", $SourceContainer)
}

$targetState = Get-ContainerState $TargetContainer
if ($targetState) {
    if (-not $ReplaceTargetContainer) {
        throw "Target container '$TargetContainer' already exists. Re-run with -ReplaceTargetContainer if it is a disposable target container."
    }
    Show-Step -Status "Replacing existing target container $TargetContainer" -Step 6
    Run-Docker @("stop", $TargetContainer)
    Run-Docker @("rm", $TargetContainer)
}

if ((Test-DockerVolumeExists $TargetVolume) -and (-not $AllowExistingTargetVolume)) {
    throw "Target volume '$TargetVolume' already exists. Use a new -TargetVolume name, or re-run with -AllowExistingTargetVolume only if it is empty/disposable."
}
if (-not (Test-DockerVolumeExists $TargetVolume)) {
    Show-Step -Status "Creating target named volume $TargetVolume" -Step 6
    Run-Docker @("volume", "create", $TargetVolume)
}

$script:CurrentStep = 7
Show-Step -Status "Starting target PostgreSQL container $TargetContainer with named volume $TargetVolume"
Run-DockerWithElapsed -Args @(
    "run", "-d",
    "--name", $TargetContainer,
    "--restart", "unless-stopped",
    "-e", "POSTGRES_DB=$Database",
    "-e", "POSTGRES_USER=$User",
    "-e", "POSTGRES_PASSWORD=$Password",
    "-p", "${HostPort}:5432",
    "-v", "${TargetVolume}:/var/lib/postgresql/data",
    $PostgresImage
) -Status "Creating named-volume PostgreSQL container" -Step $script:CurrentStep
Wait-Postgres -Container $TargetContainer -DatabaseName $Database -DbUser $User

$script:CurrentStep = 8
Show-Step -Status "Restoring dump into $TargetContainer"
Run-Docker @("cp", $hostDumpPath, "${TargetContainer}:/tmp/restore.dump")
Run-DockerWithElapsed -Args @("exec", $TargetContainer, "pg_restore", "-U", $User, "-d", $Database, "--clean", "--if-exists", "--no-owner", "--no-acl", "/tmp/restore.dump") -Status "pg_restore is running" -Step $script:CurrentStep
Run-Docker @("exec", $TargetContainer, "rm", "-f", "/tmp/restore.dump")

$script:CurrentStep = 9
Show-Step -Status "Collecting target row counts"
"table,row_count" | Set-Content -Encoding ascii $targetCountsPath
Get-ExactCounts -Container $TargetContainer -DatabaseName $Database -DbUser $User | Add-Content -Encoding ascii $targetCountsPath

$script:CurrentStep = 10
Show-Step -Status "Comparing source and target counts"
$sourceCounts = Get-Content $sourceCountsPath
$targetCounts = Get-Content $targetCountsPath
if (Compare-Object $sourceCounts $targetCounts) {
    Write-Warning "Source and target count files differ. Inspect:"
    Write-Warning "  $sourceCountsPath"
    Write-Warning "  $targetCountsPath"
} else {
    Write-Host "Source and target row-count checks match."
}

Complete-Progress
Write-Host "Migration dump: $hostDumpPath"
Write-Host "Source counts:  $sourceCountsPath"
Write-Host "Target counts:  $targetCountsPath"
Write-Host "Target DSN:     postgresql://${User}:<password>@127.0.0.1:${HostPort}/${Database}"
