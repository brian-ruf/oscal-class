@echo off
setlocal enabledelayedexpansion
REM release.cmd -- orchestrate a full release, end to end (Windows CMD equivalent of
REM release.sh).
REM
REM This is the single sanctioned entry point for cutting a release. It absorbs what used to
REM be a separate tag-release.cmd primitive: there is intentionally no standalone tagging
REM script, so a release tag is never created outside this orchestration (and its guards).
REM
REM It does, in order:
REM   1. Sanity-check: the given tag must match __version__ in the version file ON THE RELEASE
REM      BRANCH (the commit that will actually be tagged -- not your current working branch),
REM      mirroring the check publish.yml runs server-side, but failing fast locally.
REM   2. TIMING GUARD: wait until the post-merge asset-refresh workflows on the release branch
REM      (CI Pipeline's support-DB refresh + Docs' API-doc refresh) have finished and their
REM      commits have landed, so the tag lands on the fully-refreshed commit -- not on a
REM      pre-refresh commit whose wheel would ship a stale support database. (Requires gh; see
REM      --force for the escape hatch. The same staleness is also enforced server-side in
REM      publish.yml, which rejects a stale tag outright.)
REM   3. Tag + push: checkout the release branch, fast-forward it, tag the settled HEAD, push
REM      the tag, and switch back to the branch you started on.
REM   4. Wait for the "Release" workflow (publish.yml) run for that tag to appear, then watch it
REM      to completion -- it builds the wheel/sdist/SBOM and creates the GitHub Release.
REM   5. With --publish, dispatch "Publish to PyPI" (pypi.yml) for the tag once the release is
REM      built. (That workflow still pauses on the `pypi` environment reviewer gate -- approve
REM      it in the Actions tab; that approval stays manual by design.)
REM
REM Steps 2, 4, 5 require the GitHub CLI (gh, authenticated). Without gh the timing guard
REM cannot run: the script refuses unless you pass --force (then the server-side guard in
REM publish.yml is your only protection), and after tagging you finish in the Actions tab.
REM
REM Usage:
REM   scripts\release.cmd <tag> [--publish] [--force] [--yes]
REM   e.g. scripts\release.cmd v4.3.1 --publish
REM
REM Flags:
REM   --publish   after the Release is built, dispatch the PyPI publish workflow for the tag.
REM   --force     skip the timing guard (use only when you have confirmed the release branch
REM               has fully settled; the server-side guard still applies).
REM   --yes       skip the interactive confirmation prompt before tagging.
REM
REM Configurable via environment variables (defaults shown):
REM   RELEASE_BRANCH=main
REM   REMOTE=origin
REM   VERSION_FILE=oscal/_version.py     (forward slashes: it is a git path)
REM   RELEASE_WORKFLOW=publish.yml       tag-triggered build + GitHub Release ("Release")
REM   PYPI_WORKFLOW=pypi.yml             manually dispatched PyPI publish ("Publish to PyPI")
REM   SETTLE_TIMEOUT=1800               seconds to wait for the branch to settle (30 min)
REM   SETTLE_GRACE=15                   seconds of quiet to confirm no asset run is pending
REM   START_TIMEOUT=180                 seconds to wait for the Release run to appear
REM   POLL_INTERVAL=5                   seconds between polls
REM
REM The asset-refresh workflows are ci.yml and docs.yml (hard-coded in the :active_asset sub).
REM Unlike release.sh there is no RUN_TIMEOUT: CMD cannot time-limit `gh run watch`. If the
REM run hangs, press Ctrl+C -- the tag is already pushed; inspect the run in the Actions tab.

if "%RELEASE_BRANCH%"=="" set "RELEASE_BRANCH=main"
if "%REMOTE%"=="" set "REMOTE=origin"
if "%VERSION_FILE%"=="" set "VERSION_FILE=oscal/_version.py"
if "%RELEASE_WORKFLOW%"=="" set "RELEASE_WORKFLOW=publish.yml"
if "%PYPI_WORKFLOW%"=="" set "PYPI_WORKFLOW=pypi.yml"
if "%SETTLE_TIMEOUT%"=="" set "SETTLE_TIMEOUT=1800"
if "%SETTLE_GRACE%"=="" set "SETTLE_GRACE=15"
if "%START_TIMEOUT%"=="" set "START_TIMEOUT=180"
if "%POLL_INTERVAL%"=="" set "POLL_INTERVAL=5"

REM Capture our own name now: `shift` below also shifts %0.
set "SELF=%~nx0"

REM --- argument parsing: <tag> plus optional flags, in any order -----------------------------
set "TAG="
set "PUBLISH=0"
set "FORCE=0"
set "ASSUME_YES=0"

:parse_args
if "%~1"=="" goto :args_done
if /i "%~1"=="--publish" ( set "PUBLISH=1" & shift & goto :parse_args )
if /i "%~1"=="--force"   ( set "FORCE=1"   & shift & goto :parse_args )
if /i "%~1"=="--yes"     ( set "ASSUME_YES=1" & shift & goto :parse_args )
if /i "%~1"=="-y"        ( set "ASSUME_YES=1" & shift & goto :parse_args )
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

set "ORIGINAL_BRANCH="
for /f "delims=" %%b in ('git symbolic-ref --short HEAD 2^>nul') do set "ORIGINAL_BRANCH=%%b"
if not defined ORIGINAL_BRANCH (
    echo error: not currently on a branch ^(detached HEAD^) -- aborting 1>&2
    exit /b 1
)

REM Refuse with uncommitted changes.
set "DIRTY="
for /f "delims=" %%s in ('git status --porcelain') do set "DIRTY=1"
if defined DIRTY (
    echo error: you have uncommitted changes. Commit, stash, or discard them first. 1>&2
    exit /b 1
)

git rev-parse "%TAG%" >nul 2>&1
if not errorlevel 1 (
    echo error: tag "%TAG%" already exists locally. 1>&2
    exit /b 1
)

set "HAVE_GH=0"
where gh >nul 2>&1
if not errorlevel 1 set "HAVE_GH=1"

REM --- 1. sanity-check the tag against the version that will actually be tagged --------------
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
REM The version line looks like:  __version__ = "4.3.1"  -- the 2nd "-delimited token is the
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

REM --- 2. TIMING GUARD: wait for the release branch to settle after the merge ----------------
if "%FORCE%"=="1" (
    echo WARNING: --force given; skipping the timing guard. Ensure %RELEASE_BRANCH% has fully
    echo          settled ^(support DB + API docs refreshed and committed^). The server-side
    echo          guard in %RELEASE_WORKFLOW% will still reject a stale tag.
    goto :guard_done
)
if not "%HAVE_GH%"=="1" (
    echo error: GitHub CLI ^(gh^) not found -- cannot verify %RELEASE_BRANCH% has settled after the 1>&2
    echo        merge, so tagging now risks shipping a stale support database. Install/auth gh, 1>&2
    echo        or re-run with --force only after confirming the asset-refresh workflows have 1>&2
    echo        finished ^(the server-side guard in %RELEASE_WORKFLOW% still applies^). 1>&2
    exit /b 1
)

echo Timing guard: waiting for %REMOTE%/%RELEASE_BRANCH% to settle (no active CI Pipeline / Docs runs)...
set /a "SETTLE_POLLS=SETTLE_TIMEOUT / POLL_INTERVAL"
if %SETTLE_POLLS% lss 1 set "SETTLE_POLLS=1"
set "SP=0"

:settle_loop
git fetch %REMOTE% %RELEASE_BRANCH% --quiet
call :active_asset ACTIVE
if "%ACTIVE%"=="0" (
    REM No active runs; confirm it stays that way AND the tip is stable across a grace window.
    set "HEAD_BEFORE="
    for /f "delims=" %%h in ('git rev-parse "%REMOTE%/%RELEASE_BRANCH%"') do set "HEAD_BEFORE=%%h"
    "%SystemRoot%\System32\timeout.exe" /t %SETTLE_GRACE% /nobreak >nul
    git fetch %REMOTE% %RELEASE_BRANCH% --quiet
    call :active_asset ACTIVE2
    set "HEAD_AFTER="
    for /f "delims=" %%h in ('git rev-parse "%REMOTE%/%RELEASE_BRANCH%"') do set "HEAD_AFTER=%%h"
    if "!ACTIVE2!"=="0" if "!HEAD_AFTER!"=="!HEAD_BEFORE!" (
        echo Branch settled at !HEAD_AFTER:~0,8!; no asset refresh pending.
        goto :guard_done
    )
)
set /a "SP+=1"
if %SP% geq %SETTLE_POLLS% goto :settle_timeout
echo   ...asset refresh still in flight; re-checking in %POLL_INTERVAL%s.
"%SystemRoot%\System32\timeout.exe" /t %POLL_INTERVAL% /nobreak >nul
goto :settle_loop

:settle_timeout
echo error: %REMOTE%/%RELEASE_BRANCH% did not settle within %SETTLE_TIMEOUT%s. 1>&2
echo        An asset-refresh run ^(CI Pipeline / Docs^) is still active. Wait for it in the 1>&2
echo        Actions tab, then re-run; or --force if you have confirmed it is done. 1>&2
exit /b 1

:guard_done

REM --- 3. tag + push (with confirmation + switch-back) --------------------------------------
echo -------------------------------------------------------------------
echo  About to tag a release:
echo    Tag           : %TAG%
echo    Branch        : %RELEASE_BRANCH%
echo    Remote        : %REMOTE%
echo    Returning to  : %ORIGINAL_BRANCH%
echo -------------------------------------------------------------------
if not "%ASSUME_YES%"=="1" (
    set "REPLY="
    set /p "REPLY=Continue? [y/N] "
    if /i not "!REPLY!"=="y" if /i not "!REPLY!"=="yes" (
        echo Aborted -- no changes made.
        exit /b 1
    )
)

git checkout %RELEASE_BRANCH%
if errorlevel 1 ( echo error: could not checkout %RELEASE_BRANCH%. 1>&2 & goto :switch_back_fail )
git pull --ff-only %REMOTE% %RELEASE_BRANCH%
if errorlevel 1 ( echo error: could not fast-forward %RELEASE_BRANCH%. 1>&2 & goto :switch_back_fail )

git ls-remote --exit-code %REMOTE% "refs/tags/%TAG%" >nul 2>&1
if not errorlevel 1 ( echo error: tag "%TAG%" already exists on %REMOTE%. 1>&2 & goto :switch_back_fail )

git tag -a "%TAG%" -m "Release %TAG%"
if errorlevel 1 ( echo error: git tag failed. 1>&2 & goto :switch_back_fail )
git push %REMOTE% "%TAG%"
if errorlevel 1 ( echo error: git push of tag failed. 1>&2 & goto :switch_back_fail )
echo Tagged and pushed %TAG% from %RELEASE_BRANCH%.

REM Switch back to the branch we started on now that tagging succeeded.
git checkout %ORIGINAL_BRANCH% >nul 2>&1

REM Steps 4-5 need gh. Without it, the tag is pushed; finish manually in the Actions tab.
if not "%HAVE_GH%"=="1" (
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

REM --- 4a. wait for the Release run to appear ------------------------------------------------
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
REM --- 4b. watch the Release run to completion -----------------------------------------------
echo Watching Release run %RUN_ID% (Ctrl+C to stop watching; the run continues on GitHub)...
gh run watch %RUN_ID% --exit-status
if errorlevel 1 (
    echo error: '%RELEASE_WORKFLOW%' run %RUN_ID% failed. 1>&2
    echo        Do NOT publish to PyPI until the release is built. Inspect: gh run view %RUN_ID% --log 1>&2
    exit /b 1
)
echo Release built: the %TAG% GitHub Release now has the wheel, sdist, and SBOM attached.

REM --- 5. optionally dispatch the PyPI publish ----------------------------------------------
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

:switch_back_fail
git checkout %ORIGINAL_BRANCH% >nul 2>&1
exit /b 1

REM --- subroutine: count active (not-completed) asset-refresh runs on the release branch ----
REM Usage: call :active_asset <outvar>   -> sets <outvar> to the total count (0 if none/err).
REM Filters by workflow FILENAME (ci.yml/docs.yml) via --workflow and emits a bare status per
REM line (jq ".[].status", no embedded quotes -- which do not survive a CMD for /f reliably);
REM any status other than "completed" counts as active.
:active_asset
set "_AA_TOTAL=0"
for %%F in (ci.yml docs.yml) do (
    for /f "delims=" %%s in ('gh run list --workflow %%F --branch "%RELEASE_BRANCH%" --limit 40 --json status --jq ".[].status" 2^>nul') do (
        if /i not "%%s"=="completed" set /a "_AA_TOTAL+=1"
    )
)
set "%~1=%_AA_TOTAL%"
goto :eof

:usage_ok
echo Usage: %SELF% ^<tag^> [--publish] [--force] [--yes]
echo   e.g. %SELF% v4.3.1 --publish
exit /b 0

:usage_fail
echo Usage: %SELF% ^<tag^> [--publish] [--force] [--yes] 1>&2
echo   e.g. %SELF% v4.3.1 --publish 1>&2
exit /b 1
