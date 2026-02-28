param(
    [string]$OutputDir = "C:\data\pdfsizetest",
    [int]$StartMB = 2,
    [int]$EndMB = 20,
    [int]$StepMB = 1,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($StartMB -lt 1) {
    throw "StartMB は 1 以上を指定してください。"
}
if ($EndMB -lt $StartMB) {
    throw "EndMB は StartMB 以上を指定してください。"
}
if ($StepMB -lt 1) {
    throw "StepMB は 1 以上を指定してください。"
}

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$headerBytes = [System.Text.Encoding]::ASCII.GetBytes("%PDF-1.4`n%aaaa`n")
$footerBytes = [System.Text.Encoding]::ASCII.GetBytes("`n%%EOF`n")

$rand = [System.Random]::new()

for ($mb = $StartMB; $mb -le $EndMB; $mb += $StepMB) {
    $targetSize = $mb * 1MB
    $bodySize = $targetSize - $headerBytes.Length - $footerBytes.Length

    if ($bodySize -lt 0) {
        throw "サイズ計算に失敗しました: ${mb}MB"
    }

    $filePath = Join-Path $OutputDir ("test_{0}MB.pdf" -f $mb)
    if ((-not $Force) -and (Test-Path $filePath)) {
        Write-Host ("skip : {0} (既存)" -f $filePath)
        continue
    }

    $bodyBytes = New-Object byte[] $bodySize
    $rand.NextBytes($bodyBytes)

    $fs = [System.IO.File]::Open($filePath, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    try {
        $fs.Write($headerBytes, 0, $headerBytes.Length)
        $fs.Write($bodyBytes, 0, $bodyBytes.Length)
        $fs.Write($footerBytes, 0, $footerBytes.Length)
    }
    finally {
        $fs.Dispose()
    }

    $actual = (Get-Item $filePath).Length
    Write-Host ("create: {0} ({1} bytes)" -f $filePath, $actual)
}

Write-Host "done"
