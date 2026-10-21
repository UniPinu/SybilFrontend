<#
.SYNOPSIS
    The Makefile targets, for Windows boxes without `make`.

.EXAMPLE
    .\tasks.ps1 setup
    .\tasks.ps1 pool -Pool 16 -Reference 12
    .\tasks.ps1 dev
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('help', 'setup', 'weights', 'candidates', 'pool', 'dev', 'build', 'serve',
                 'test', 'test-fast', 'test-slow', 'lint', 'clean-cache')]
    [string]$Task = 'help',

    [int]$Pool = 16,
    [int]$Reference = 12,
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'

function Invoke-In([string]$dir, [scriptblock]$block) {
    Push-Location $dir
    try { & $block } finally { Pop-Location }
}

switch ($Task) {
    'help' {
        @'
setup        install everything (uv sync, pnpm install) and check the install
weights      download Sybil's checkpoints and verify against the published scores
candidates   build data/candidates.parquet from the IDC index (no scans downloaded)
pool         prepare the curated pool + reference sample (-Pool 16 -Reference 12)
dev          run uvicorn :8000 and vite :5173 together
build        build the frontend into frontend/dist (the backend serves it)
serve        build, then serve app + API on 0.0.0.0:8000 for the network (-Port 8000)
test        smoke test + unit tests
test-fast    unit tests only (no model, no network)
test-slow    the real-ensemble tests (several minutes)
lint         lint the frontend
clean-cache  drop processed patients (keeps the ~700 MB of model weights)
'@
    }

    'setup' {
        Invoke-In $backend { uv sync --extra dev }
        Invoke-In $frontend { pnpm install }
        & $PSCommandPath weights
        & $PSCommandPath candidates
    }

    'weights' { Invoke-In $backend { uv run python scripts/smoke_test.py } }

    'candidates' { Invoke-In $backend { uv run python scripts/build_candidates.py } }

    'pool' {
        Invoke-In $backend {
            uv run python scripts/prepare_pool.py --pool $Pool --reference $Reference
        }
    }

    'dev' {
        $api = Start-Process -PassThru -NoNewWindow -WorkingDirectory $backend `
            -FilePath 'uv' -ArgumentList 'run', 'uvicorn', 'app.main:app', '--port', '8000', '--reload'
        try {
            Write-Host 'backend  http://localhost:8000' -ForegroundColor Cyan
            Write-Host 'frontend http://localhost:5173' -ForegroundColor Cyan
            Invoke-In $frontend { pnpm dev }
        } finally {
            if ($api -and -not $api.HasExited) { Stop-Process -Id $api.Id -Force }
        }
    }

    'build' { Invoke-In $frontend { pnpm build } }

    # One worker only: the job queue and the loaded ensemble live in this process.
    'serve' {
        Invoke-In $frontend { pnpm build }
        Invoke-In $backend { uv run uvicorn app.main:app --host 0.0.0.0 --port $Port }
    }

    'test' {
        Invoke-In $backend {
            uv run pytest -m "not slow"
            uv run python scripts/smoke_test.py --compare-runner
        }
    }

    'test-fast' { Invoke-In $backend { uv run pytest -m "not slow" } }

    'test-slow' { Invoke-In $backend { uv run pytest -m slow } }

    'lint' { Invoke-In $frontend { pnpm lint } }

    'clean-cache' {
        Invoke-In $backend {
            uv run python -c "import shutil; from app.config import settings; shutil.rmtree(settings.cache_dir, ignore_errors=True); print('cache cleared')"
        }
    }
}
