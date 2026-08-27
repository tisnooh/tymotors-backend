param(
    [string]$ApiBase = "https://tymotors-backend.onrender.com",
    [string]$ImageDirectory = (Join-Path $PSScriptRoot "..\assets\catalogue-gallery"),
    [string]$MainManifestPath = (Join-Path $PSScriptRoot "..\data\product_ai_catalogue_uploads.json"),
    [string]$OutputPath = (Join-Path $PSScriptRoot "..\data\product_gallery_uploads.json"),
    [switch]$ReplaceExisting
)

$ErrorActionPreference = "Stop"
$mainManifest = Get-Content -Raw -LiteralPath $MainManifestPath | ConvertFrom-Json
$results = @()
if (Test-Path -LiteralPath $OutputPath) {
    $existing = Get-Content -Raw -LiteralPath $OutputPath | ConvertFrom-Json
    if ($existing.images) { $results = @($existing.images) }
}

function Save-Manifest {
    [ordered]@{
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        count = $results.Count
        strategy = "main_exact_product_plus_real_source_context"
        rights_status = "REQUIRES_MANUAL_REVIEW"
        images = $results
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $OutputPath -Encoding utf8
}

foreach ($file in Get-ChildItem -LiteralPath $ImageDirectory -Filter "*-context.png" | Sort-Object BaseName) {
    $slug = $file.BaseName -replace '-context$', ''
    $main = $mainManifest.images | Where-Object { $_.product_slug -eq $slug } | Select-Object -First 1
    if (-not $main) { throw "Missing main image for $slug" }
    if (($results.product_slug -contains $slug) -and -not $ReplaceExisting) {
        Write-Host "Skipping $slug (already uploaded)."
        continue
    }
    if ($ReplaceExisting) { $results = @($results | Where-Object { $_.product_slug -ne $slug }) }

    Write-Host "Uploading context image for $slug..."
    $uploadJson = & curl.exe --silent --show-error --fail `
        -X POST "$ApiBase/api/admin/upload-image" `
        -F "file=@$($file.FullName);type=image/png"
    if ($LASTEXITCODE -ne 0) { throw "Cloudinary upload failed for $slug" }
    $upload = $uploadJson | ConvertFrom-Json
    if (-not $upload.url) { throw "Upload response did not contain a URL for $slug" }

    $body = @{ images = @($main.delivery_url, $upload.url) } | ConvertTo-Json -Compress
    & curl.exe --silent --show-error --fail -X PUT "$ApiBase/api/admin/products/$slug" `
        -H "Content-Type: application/json" --data-raw $body | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Product gallery update failed for $slug" }

    $results += [ordered]@{
        product_slug = $slug
        main_url = $main.delivery_url
        context_url = $upload.url
        context_public_id = $upload.public_id
        source_file = $file.Name
    }
    Save-Manifest
}

Save-Manifest
Write-Host "Uploaded and assigned $($results.Count) realistic product galleries."
