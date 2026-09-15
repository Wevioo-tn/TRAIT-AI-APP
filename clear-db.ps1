# Clear traite records and dependent data while preserving IMX and users.
param(
    [string]$Database = "trait_ai",
    [string]$DatabaseUser = "trait"
)

$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    'TRUNCATE TABLE public.traites RESTART IDENTITY CASCADE;' |
        docker compose exec -T postgres psql -U $DatabaseUser -d $Database -v ON_ERROR_STOP=1
    if ($LASTEXITCODE -ne 0) {
        throw "Database clearing failed (exit code $LASTEXITCODE)."
    }
    Write-Output "Traite data cleared. IMX records and users were preserved."
}
finally {
    Pop-Location
}
