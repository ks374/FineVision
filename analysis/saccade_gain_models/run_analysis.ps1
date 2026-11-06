param(
    [switch]$ForceConvert,
    [double]$BackgroundLuminance = 5.0,
    [double]$MinimumLatencyMs = 80.0,
    [int]$BootstrapRepetitions = 5000
)

$analysisRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = 'D:\Software\Psychopy\python.exe'
$script = Join-Path $analysisRoot 'analyze_saccade_models.py'
$arguments = @(
    $script,
    '--background-luminance', $BackgroundLuminance,
    '--minimum-latency-ms', $MinimumLatencyMs,
    '--bootstrap-repetitions', $BootstrapRepetitions
)
if ($ForceConvert) {
    $arguments += '--force-convert'
}
& $python @arguments
exit $LASTEXITCODE
