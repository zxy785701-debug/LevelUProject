# Readiness contract: evaluate only the pure probe function with a local response fixture.
$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'start.ps1'
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'Launcher syntax is invalid.' }
$probe = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Test-LevelUpBackend' }, $true)
Invoke-Expression $probe.Extent.Text
function Invoke-RestMethod {
    param($Uri, $TimeoutSec)
    return $script:fixture
}
$script:fixture = [pscustomobject]@{
    info = [pscustomobject]@{ title = 'LevelUp API' }
    paths = [pscustomobject]@{
        '/api/v1/knowledge-map' = @{}
        '/api/v1/analytics' = @{}
        '/api/v1/materials/document' = @{}
        '/api/v1/knowledge/capabilities' = @{}
    }
}
if (Test-LevelUpBackend) { throw 'An old backend without the images endpoint must not be reused.' }
$script:fixture.paths | Add-Member -NotePropertyName '/api/v1/quiz/images/capabilities' -NotePropertyValue @{}
if (-not (Test-LevelUpBackend)) { throw 'The current backend should be reusable.' }
$script:fixture.info.title = 'Unrelated API'
if (Test-LevelUpBackend) { throw 'An unrelated service must not be reused.' }
Write-Output 'Backend readiness: old/current/unrelated service cases PASS'
