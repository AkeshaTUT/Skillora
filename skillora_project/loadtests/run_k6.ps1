param(
    [string]$BaseUrl = "http://localhost:8080",
    [string]$OutFile = "k6-results.json"
)

$scriptPath = Join-Path $PSScriptRoot "k6_courses.js"

Write-Host "Running k6 against $BaseUrl"
Write-Host "Output: $OutFile"

k6 run --env BASE_URL=$BaseUrl --summary-export $OutFile $scriptPath
