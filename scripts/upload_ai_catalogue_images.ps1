param(
    [string]$ApiBase = "https://tymotors-backend.onrender.com",
    [string]$ImageDirectory = (Join-Path $PSScriptRoot "..\assets\ai-catalogue"),
    [string]$OutputPath = (Join-Path $PSScriptRoot "..\data\product_ai_catalogue_uploads.json")
)

$ErrorActionPreference = "Stop"
$results = @()

if (Test-Path -LiteralPath $OutputPath) {
    $existingManifest = Get-Content -Raw -LiteralPath $OutputPath | ConvertFrom-Json
    if ($existingManifest.images) {
        $results = @($existingManifest.images)
    }
}

function Save-Manifest {
    param([array]$Images)

    [ordered]@{
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        style = "Product-only square catalogue visual on a charcoal studio background"
        count = $Images.Count
        images = $Images
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $OutputPath -Encoding utf8
}

foreach ($file in Get-ChildItem -LiteralPath $ImageDirectory -Filter "*.png" | Sort-Object BaseName) {
    $slug = $file.BaseName
    if ($results.product_slug -contains $slug) {
        Write-Host "Skipping $slug (already uploaded)."
        continue
    }

    Write-Host "Uploading $slug..."

    $uploadJson = & curl.exe --silent --show-error --fail `
        -X POST "$ApiBase/api/admin/upload-image" `
        -F "file=@$($file.FullName);type=image/png"
    if ($LASTEXITCODE -ne 0) {
        throw "Cloudinary upload failed for $slug."
    }

    $upload = $uploadJson | ConvertFrom-Json
    if (-not $upload.url) {
        throw "Upload response for $slug did not contain a URL."
    }

    $body = @{ images = @($upload.url) } | ConvertTo-Json -Compress
    & curl.exe --silent --show-error --fail `
        -X PUT "$ApiBase/api/admin/products/$slug" `
        -H "Content-Type: application/json" `
        --data-raw $body | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Product update failed for $slug."
    }

    $results += [ordered]@{
        product_slug = $slug
        source_file = $file.Name
        delivery_url = $upload.url
        cloudinary_public_id = $upload.public_id
        transformation = "ai_product_isolation_charcoal_studio"
        rights_status = "REQUIRES_MANUAL_REVIEW"
    }

    Save-Manifest -Images $results
}

Save-Manifest -Images $results

Write-Host "Uploaded and assigned $($results.Count) catalogue images."
