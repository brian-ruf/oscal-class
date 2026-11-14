@echo off
setlocal
REM release.cmd -- orchestrate a full release on top of tag-release.cmd (Windows CMD
REM equivalent of release.sh).
REM
REM This is the repo-specific wrapper that tag-release.cmd (deliberately generic) is NOT:
REM it knows this project's version file and GitHub workflows, and chains the whole release
REM so a maintainer runs one command instead of babysitting the Actions tab.
REM
REM It does, in order:
REM   1. Sanity-check: the given tag must match __version__ in the version file ON THE RELEASE
REM      BRANCH (the commit that will actually be tagged -- not your current working branch),
REM      mirroring the check publish.yml runs server-side, but failing fast locally.
REM   2. Tag + push via tag-release.cmd (which handles checkout/pull/push/switch-back + guards).
REM   3. Wait for the "Release" workflow (publish.yml) run for that tag to appear, then watch it
REM      to completion -- it builds the wheel/sdist/SBOM and creates the GitHub Release.
REM   4. With --publish, dispatch "Publish to PyPI" (pypi.yml) for the tag once the release is
REM      built. (That workflow still pauses on the `pypi` environment reviewer gate -- approve
REM      it in the Actions tab; that approval stays manual by design.)
REM
REM Steps 3-4 require the GitHub CLI (gh, authenticated). Without it, the tag is still pushed
REM (step 2) and you finish in the Actions tab manually.
REM
REM Usage:
REM   scripts\release.cmd <tag> [--publish]
REM   e.g. scripts\release.cmd v4.2.1 --publish
REM
REM Configurable via environment variables (defaults shown):
REM   RELEASE_BRANCH=main
REM   REMOTE=origin
REM   VERSION_FILE=oscal/_version.py     (forward slashes: it is a git path)
REM   RELEASE_WORKFLOW=publish.yml       tag-triggered build + GitHub Release
REM   PYPI_WORKFLOW=pypi.yml             manually dispatched PyPI publish
REM   START_TIMEOUT=180                  seconds to wait for the Release run to appear
REM   POLL_INTERVAL=5                    seconds between polls while the run is appearing
REM
REM Unlike release.sh there is no RUN_TIMEOUT: CMD cannot time-limit `gh run watch`. If the
REM run hangs, press Ctrl+C -- the tag is already pushed; inspect the run in the Actions tab.

if "%RELEASE_BRANCH%"=="" set "RELEASE_BRANCH=main"
if "%REMOTE%"=="" set "REMOTE=origin"
if "%VERSION_FILE%"=="" set "VERSION_FILE=oscal/_version.py"
if "%RELEASE_WORKFLOW%"=="" set "RELEASE_WORKFLOW=publish.yml"
if "%PYPI_WORKFLOW%"=="" set "PYPI_WORKFLOW=pypi.yml"
if "%START_TIMEOUT%"=="" set "START_TIMEOUT=180"
if "%POLL_INTERVAL%"=="" set "POLL_INTERVAL=5"

REM Capture our own name and folder now: `shift` below also shifts %0.
set "SELF=%~nx0"
set "SCRIPT_DIR=%~dp0"

REM --- argument parsing: <tag> plus optional --publish, in any order ---------
set "TAG="
set "PUBLISH=0"

:parse_args
if "%~1"=="" goto :args_done
if /i "%~1"=="--publish" (
    set "PUBLISH=1"
    shift
    goto :parse_args
)
if /i "%~1"=="-h" goto :usage_ok
if /i "%~1"=="--help" goto :usage_ok
set "ARG=%~1"
if "%ARG:~0,1%"=="-" (
    echo error: unknown option '%~1' 1>&2
    goto :usage_fail
)
if defined TAG (
    echo error: more than one tag given ^('%TAG%' and '%~1'^) 1>&2
    exit /b 1
)
set "TAG=%~1"
shift
goto :parse_args

:args_done
if not defined TAG goto :usage_fail

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
    echo error: not inside a git repository 1>&2
    exit /b 1
)

if not exist "%SCRIPT_DIR%tag-release.cmd" (
    echo error: %SCRIPT_DIR%tag-release.cmd not found. 1>&2
    exit /b 1
)

REM --- 1. sanity-check the tag against the version that will actually be tagged ---------
REM Read __version__ from the version file on the RELEASE branch (not the current checkout):
REM the tag lands on RELEASE_BRANCH, so that is the version publish.yml will compare against.
git fetch %REMOTE% %RELEASE_BRANCH% --quiet
if errorlevel 1 (
    echo error: git fetch %REMOTE% %RELEASE_BRANCH% failed. 1>&2
    exit /b 1
)
git show "%REMOTE%/%RELEASE_BRANCH%:%VERSION_FILE%" >nul 2>&1
if errorlevel 1 (
    echo error: could not read '%VERSION_FILE%' from %REMOTE%/%RELEASE_BRANCH%. 1>&2
    exit /b 1
)
REM The version line looks like:  __version__ = "4.2.4"  -- the 2nd "-delimited token is the
REM version. findstr /b anchors to line start, skipping docstring mentions of __version__.
set "PKG="
for /f tokens^=2^ delims^=^" %%v in ('git show "%REMOTE%/%RELEASE_BRANCH%:%VERSION_FILE%" ^| findstr /b /c:"__version__"') do (
    if not defined PKG set "PKG=%%v"
)
if not defined PKG (
    echo error: could not find __version__ in '%VERSION_FILE%' on %REMOTE%/%RELEASE_BRANCH%. 1>&2
    exit /b 1
)
if not "%TAG%"=="v%PKG%" (
    echo error: tag '%TAG%' does not match %REMOTE%/%RELEASE_BRANCH% %VERSION_FILE% ^(__version__ = %PKG%^). 1>&2
    echo        Merge the version bump to %RELEASE_BRANCH% first, or pass tag 'v%PKG%'. 1>&2
    exit /b 1
)
echo Version check OK: %TAG% matches %REMOTE%/%RELEASE_BRANCH% %VERSION_FILE% (__version__ = %PKG%).

REM --- 2. tag + push (tag-release.cmd runs its own guards + confirmation prompt) ---------
REM RELEASE_BRANCH and REMOTE are inherited by tag-release.cmd through the environment.
call "%SCRIPT_DIR%tag-release.cmd" "%TAG%"
if errorlevel 1 exit /b 1

REM Steps 3-4 need gh. Without it, the tag is pushed; finish manually in the Actions tab.
where gh >nul 2>&1
if errorlevel 1 (
    echo note: GitHub CLI ^(gh^) not found -- tag pushed, but cannot watch the Release run or
    echo       dispatch PyPI from here. Do it in the Actions tab:
    echo         - wait for '%RELEASE_WORKFLOW%' to finish
    echo         - run '%PYPI_WORKFLOW%' with tag=%TAG%
    exit /b 0
)

set "TAG_SHA="
for /f "delims=" %%s in ('git rev-list -n 1 "%TAG%"') do set "TAG_SHA=%%s"
if not defined TAG_SHA (
    echo error: could not resolve the commit for tag %TAG%. 1>&2
    exit /b 1
)

REM --- 3a. wait for the Release run to appear (it starts within seconds of the tag push) ---
echo Waiting up to %START_TIMEOUT%s for the '%RELEASE_WORKFLOW%' run on %TAG% to start...
set /a "MAX_POLLS=START_TIMEOUT / POLL_INTERVAL"
if %MAX_POLLS% lss 1 set "MAX_POLLS=1"
set "POLLS=0"
set "RUN_ID="

:poll_run
set "RUN_ID="
for /f "delims=" %%r in ('gh run list --workflow "%RELEASE_WORKFLOW%" --commit %TAG_SHA% --event push --limit 1 --json databaseId --jq ".[0].databaseId" 2^>nul') do set "RUN_ID=%%r"
if defined RUN_ID if not "%RUN_ID%"=="null" goto :run_found
set /a "POLLS+=1"
if %POLLS% geq %MAX_POLLS% goto :run_not_found
"%SystemRoot%\System32\timeout.exe" /t %POLL_INTERVAL% /nobreak >nul
goto :poll_run

:run_not_found
echo error: no '%RELEASE_WORKFLOW%' run for %TAG% (commit %TAG_SHA:~0,8%) appeared within %START_TIMEOUT%s. 1>&2
echo        The tag is pushed -- check the Actions tab; the workflow may be disabled or slow to queue. 1>&2
echo        Fallback: gh workflow run %RELEASE_WORKFLOW% -f tag=%TAG% 1>&2
exit /b 1

:run_found
REM --- 3b. watch the Release run to completion --------------------------------------------
echo Watching Release run %RUN_ID% (Ctrl+C to stop watching; the run continues on GitHub)...
gh run watch %RUN_ID% --exit-status
if errorlevel 1 (
    echo error: '%RELEASE_WORKFLOW%' run %RUN_ID% failed. 1>&2
    echo        Do NOT publish to PyPI until the release is built. Inspect: gh run view %RUN_ID% --log 1>&2
    exit /b 1
)
echo Release built: the %TAG% GitHub Release now has the wheel, sdist, and SBOM attached.

REM --- 4. optionally dispatch the PyPI publish --------------------------------------------
if "%PUBLISH%"=="1" (
    echo Dispatching '%PYPI_WORKFLOW%' for %TAG%...
    gh workflow run "%PYPI_WORKFLOW%" -f tag=%TAG%
    if errorlevel 1 (
        echo error: failed to dispatch '%PYPI_WORKFLOW%'. Run it from the Actions tab with tag=%TAG%. 1>&2
        exit /b 1
    )
    echo Dispatched. Approve the 'pypi' environment gate in the Actions tab to complete the upload.
) else (
    echo Done. To publish to PyPI: gh workflow run %PYPI_WORKFLOW% -f tag=%TAG%   ^(or re-run with --publish^)
)
exit /b 0

:usage_ok
echo Usage: %SELF% ^<tag^> [--publish]
echo   e.g. %SELF% v4.2.1 --publish
exit /b 0

:usage_fail
echo Usage: %SELF% ^<tag^> [--publish] 1>&2
echo   e.g. %SELF% v4.2.1 --publish 1>&2
exit /b 1
