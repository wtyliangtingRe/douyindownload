param(
    [string]$ProfileUrl = 'https://www.douyin.com/user/MS4wLjABAAAAFu86FkpJPIXePsIHnQ2dQgf8eJ9ZIOryBZhoHwU0tOQ',
    [string]$OutputRoot = 'E:\0\laobaiSave',
    [switch]$RunAfterInstall
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
if ($PSVersionTable.PSVersion.Major -lt 7 -or -not $IsWindows) {
    throw 'Please run this script in Windows PowerShell 7+.'
}
if ($ProfileUrl -notmatch '^https://www\.douyin\.com/user/[^?/#]+') {
    throw 'ProfileUrl must be a full Douyin profile URL: https://www.douyin.com/user/....'
}

$Tool = Join-Path $OutputRoot '_tool'
$Media = Join-Path $OutputRoot 'media'
$UpstreamRev = 'f7ec48f9cfe1fc80b0093440c62c0c60425c31b2'
$Upstream = Join-Path $Tool "douyin-downloader-$UpstreamRev"
$Venv = Join-Path $Tool '.venv'
$Py = Join-Path $Venv 'Scripts\python.exe'
$Runner = Join-Path $Tool 'laobai-browser-v23.py'
$Original = Join-Path $Tool 'download-laobai.py'

New-Item -ItemType Directory -Force -Path $OutputRoot, $Tool, $Media | Out-Null

$Utf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $Utf8
[Console]::OutputEncoding = $Utf8
$OutputEncoding = $Utf8
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:UV_CACHE_DIR = Join-Path $Tool 'uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Tool 'python'
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $Tool 'browsers'

function Assert-Native([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed (exit code $LASTEXITCODE)." }
}

Write-Host '[1/5] Preparing portable Python environment...'
$UvDir = Join-Path $Tool 'uv-0.12.17'
$Uv = Get-ChildItem $UvDir -Filter uv.exe -File -Recurse -ErrorAction SilentlyContinue |
      Select-Object -First 1 -ExpandProperty FullName
if (-not $Uv) {
    $Arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
    $Target = switch ($Arch) {
        'X64'   { 'x86_64-pc-windows-msvc' }
        'Arm64' { 'aarch64-pc-windows-msvc' }
        default { throw "Unsupported Windows architecture: $Arch" }
    }
    $UvZip = Join-Path $Tool 'uv.zip'
    Invoke-WebRequest "https://github.com/astral-sh/uv/releases/download/0.12.17/uv-$Target.zip" -OutFile $UvZip
    Expand-Archive $UvZip -DestinationPath $UvDir -Force
    $Uv = Get-ChildItem $UvDir -Filter uv.exe -File -Recurse | Select-Object -First 1 -ExpandProperty FullName
    if (-not $Uv) { throw 'uv.exe was not found after extraction.' }
}
if (-not (Test-Path -LiteralPath $Py -PathType Leaf)) {
    & $Uv --no-config venv --managed-python --python 3.11 $Venv
    Assert-Native 'Create Python environment'
}

Write-Host '[2/5] Fetching pinned upstream downloader source...'
if (-not (Test-Path -LiteralPath (Join-Path $Upstream 'run.py') -PathType Leaf)) {
    $Zip = Join-Path $Tool 'source.zip'
    Invoke-WebRequest "https://github.com/jiji262/douyin-downloader/archive/$UpstreamRev.zip" -OutFile $Zip
    Expand-Archive $Zip -DestinationPath $Tool -Force
}
if (-not (Test-Path -LiteralPath (Join-Path $Upstream 'run.py') -PathType Leaf)) {
    throw 'Pinned upstream source extraction failed.'
}

Write-Host '[3/5] Installing Python dependencies and Playwright Chromium...'
& $Uv --no-config pip install --python $Py -r (Join-Path $Upstream 'requirements.txt') playwright
Assert-Native 'Install Python dependencies'
& $Py -m playwright install chromium
Assert-Native 'Install Playwright Chromium'

Write-Host '[4/5] Installing the tested v2.3 browser pagination runner...'
$BundledRunner = Join-Path $PSScriptRoot 'src\browser_runner_v23.py'
if (-not (Test-Path -LiteralPath $BundledRunner -PathType Leaf)) {
    throw "Bundled runner not found: $BundledRunner"
}
Copy-Item -LiteralPath $BundledRunner -Destination $Runner -Force
& $Py -m py_compile $Runner
Assert-Native 'Validate v2.3 runner'

Write-Host '[5/5] Writing local profile configuration wrapper...'
$EscapedProfile = $ProfileUrl.Replace('\\','\\\\').Replace('"','\\"')
$EscapedTool = $Tool.Replace('\\','\\\\').Replace('"','\\"')
$EscapedRoot = $OutputRoot.Replace('\\','\\\\').Replace('"','\\"')
$EscapedMedia = $Media.Replace('\\','\\\\').Replace('"','\\"')
$EscapedUpstream = $Upstream.Replace('\\','\\\\').Replace('"','\\"')

$Code = @"
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
import yaml

REVISION = "$UpstreamRev"
URL = "$EscapedProfile"
TOOL = Path(r"$EscapedTool")
ROOT = Path(r"$EscapedRoot")
MEDIA = Path(r"$EscapedMedia")
SRC = Path(r"$EscapedUpstream")
CONFIG = TOOL / "laobai.yml"

def make_config() -> dict:
    previous = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    if previous is not None and not isinstance(previous, dict):
        raise RuntimeError("laobai.yml is not a configuration mapping.")
    return {
        "link": [URL], "path": str(MEDIA), "mode": ["post"],
        "video": True, "cover": True, "json": True,
        "music": False, "avatar": False,
        "download_pinned": True, "author_url": True,
        "homepage_screenshot": False,
        "start_time": "", "end_time": "", "number": {"post": 0},
        "increase": {"post": True}, "redownload_missing_files": True,
        "folderstyle": True, "author_dir": "sec_uid",
        "filename_template": "{date}_{id}", "folder_template": "{id}",
        "video_quality": "highest", "thread": 2, "retry_times": 3,
        "proxy": "", "database": True,
        "database_path": str(TOOL / "history.db"),
        "progress": {"quiet_logs": False},
        "browser_fallback": {"enabled": True, "headless": False, "max_scrolls": 10000,
                             "idle_rounds": 20, "wait_timeout_seconds": 7200},
        "transcript": {"enabled": False}, "comments": {"enabled": False},
        "notifications": {"enabled": False},
        "cookies": (previous or {}).get("cookies") or {},
    }

def run_tool(*args: str) -> int:
    return subprocess.run([sys.executable, "-u", *args], cwd=SRC, check=False).returncode

def audit(media: Path, root: Path, exit_code: int) -> dict:
    all_videos = sorted(media.rglob("*.mp4"))
    videos = [p for p in all_videos if "_live_" not in p.stem]
    empty, missing = [], []
    for video in videos:
        if video.stat().st_size == 0:
            empty.append(str(video.relative_to(root)))
        cover = video.with_name(video.stem + "_cover.jpg")
        if not cover.is_file() or cover.stat().st_size == 0:
            missing.append(str(video.relative_to(root)))
    covers = [p for p in media.rglob("*_cover.jpg") if p.stat().st_size > 0]
    report = {
        "checked_at": datetime.now().astimezone().isoformat(),
        "downloader_exit_code": exit_code,
        "local_video_files": len(videos),
        "local_nonempty_cover_files": len(covers),
        "empty_video_files": empty,
        "videos_missing_covers": missing,
        "scope": "Local file existence/size only; not proof of complete profile or valid media playback.",
    }
    (root / "check-result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n========== LOCAL FILE CHECK ==========", flush=True)
    print(f"Video files: {len(videos)} | Cover files: {len(covers)}", flush=True)
    print(f"Empty videos: {len(empty)} | Videos missing covers: {len(missing)}", flush=True)
    print(f"Report: {root / 'check-result.json'}", flush=True)
    return report

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    MEDIA.mkdir(parents=True, exist_ok=True)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(TOOL / "browsers")
    os.environ["PYTHONUTF8"] = "1"
    if args.check:
        report = audit(MEDIA, ROOT, 0)
        return 3 if not report["local_video_files"] or report["videos_missing_covers"] or report["empty_video_files"] else 0
    if not (SRC / "run.py").is_file():
        raise RuntimeError("Pinned upstream source is missing; rerun setup.ps1.")
    config = make_config()
    CONFIG.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
"@
[System.IO.File]::WriteAllText($Original, $Code, $Utf8)

Write-Host ''
Write-Host 'Install complete.'
Write-Host "Download root: $OutputRoot"
Write-Host "Profile: $ProfileUrl"
Write-Host "Run:   & '$Py' '$Runner'"
Write-Host "Check: & '$Py' '$Original' --check"
Write-Host 'The browser may require manual login/verification; cookies and browser state stay local.'

if ($RunAfterInstall) {
    & $Py -u $Runner
    exit $LASTEXITCODE
}
