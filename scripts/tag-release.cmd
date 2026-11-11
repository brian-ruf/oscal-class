@echo off
setlocal enabledelayedexpansion
REM tag-release.cmd -- safely tag a release and switch back automatically.
REM
REM Encapsulates the one workflow that requires being on the release branch
REM (default: main): tagging a release. Does checkout -> tag -> push ->
REM switch back as one sequence, so "forgot to switch back to the dev
REM branch afterward" stops being a failure mode that exists at all.
REM
REM Generic by design -- copy this file (and tag-release.sh) into any
REM repo's scripts\ folder. Nothing here names a specific repo, remote, or
REM branch beyond the configurable defaults below.
REM
REM Usage:
REM   scripts\tag-release.cmd <tag>
REM   e.g. scripts\tag-release.cmd v2.1.0
REM
REM Configurable via environment variables (defaults shown):
REM   RELEASE_BRANCH=main
REM   REMOTE=origin

if "%RELEASE_BRANCH%"=="" set "RELEASE_BRANCH=main"
if "%REMOTE%"=="" set "REMOTE=origin"

if "%~1"=="" (
    echo Usage: %~nx0 ^<tag^>
    echo   e.g. %~nx0 v2.1.0
    exit /b 1
)
set "TAG=%~1"

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
    echo error: not inside a git repository
    exit /b 1
)

set "ORIGINAL_BRANCH="
for /f "delims=" %%b in ('git symbolic-ref --short HEAD 2^>nul') do set "ORIGINAL_BRANCH=%%b"
if "%ORIGINAL_BRANCH%"=="" (
    echo error: not currently on a branch ^(detached HEAD^) -- aborting
    exit /b 1
)

set "DIRTY="
for /f "delims=" %%s in ('git status --porcelain') do set "DIRTY=1"
if defined DIRTY (
    echo error: you have uncommitted changes. Commit, stash, or discard them first.
    exit /b 1
)

git rev-parse "%TAG%" >nul 2>&1
if not errorlevel 1 (
    echo error: tag "%TAG%" already exists locally.
    exit /b 1
)

echo -------------------------------------------------------------------
echo  About to tag a release:
echo    Tag           : %TAG%
echo    Branch        : %RELEASE_BRANCH%
echo    Remote        : %REMOTE%
echo    Returning to  : %ORIGINAL_BRANCH%
echo -------------------------------------------------------------------
set "CONFIRM="
set /p CONFIRM="Continue? [y/N] "
if /i "%CONFIRM%"=="y" goto :confirmed
if /i "%CONFIRM%"=="yes" goto :confirmed
echo Aborted -- no changes made.
exit /b 1

:confirmed
git fetch %REMOTE% --quiet
if errorlevel 1 goto :fail

git checkout %RELEASE_BRANCH%
if errorlevel 1 goto :fail

git pull --ff-only %REMOTE% %RELEASE_BRANCH%
if errorlevel 1 goto :restore_and_fail

git ls-remote --exit-code %REMOTE% "refs/tags/%TAG%" >nul 2>&1
if not errorlevel 1 (
    echo error: tag "%TAG%" already exists on %REMOTE%.
    goto :restore_and_fail
)

git tag -a "%TAG%" -m "Release %TAG%"
if errorlevel 1 goto :restore_and_fail

git push %REMOTE% "%TAG%"
if errorlevel 1 goto :restore_and_fail

echo -------------------------------------------------------------------
echo  Tagged and pushed %TAG% from %RELEASE_BRANCH%.
echo  Switching back to %ORIGINAL_BRANCH%.
echo -------------------------------------------------------------------
git checkout %ORIGINAL_BRANCH%
exit /b 0

:restore_and_fail
echo Restoring original branch %ORIGINAL_BRANCH% after failure...
git checkout %ORIGINAL_BRANCH% >nul 2>&1

:fail
echo tag-release failed.
exit /b 1
