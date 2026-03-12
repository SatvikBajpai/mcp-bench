@echo off
REM ============================================================
REM  MoSPI MCP Benchmark - Full Regression Run (Windows)
REM ============================================================
REM  Usage:
REM    run_regression.bat              (run all 200 queries)
REM    run_regression.bat --start 47   (resume from query 47)
REM
REM  Requirements:
REM    - Python installed and on PATH
REM    - playwright installed: pip install playwright
REM    - chromium installed:   playwright install chromium
REM    - ChatGPT auth saved:   python testers\chatgpt_tester.py --save-auth
REM    - MoSPI server running (separate window)
REM    - ngrok/tunnel running (separate window)
REM ============================================================

cd /d "%~dp0.."

set LOG=C:\temp\mospi_telemetry.log
set CSV=queries\regression_test_queries.csv
set DELAY=30
set START=%2

REM Create log directory
if not exist C:\temp mkdir C:\temp

echo ============================================================
echo  MoSPI Regression Benchmark
echo  Queries: %CSV%
echo  Log:     %LOG%
echo  Delay:   %DELAY%s between queries
echo ============================================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python and add to PATH.
    pause
    exit /b 1
)

REM Check CSV exists
if not exist "%CSV%" (
    echo ERROR: Query file not found: %CSV%
    pause
    exit /b 1
)

REM Step 1: Run the benchmark
echo [1/3] Running benchmark queries...
echo.
if "%START%"=="" (
    python testers\chatgpt_tester.py --dataset REGRESSION --csv "%CSV%" --server-log "%LOG%" --delay %DELAY%
) else (
    python testers\chatgpt_tester.py --dataset REGRESSION --csv "%CSV%" --server-log "%LOG%" --delay %DELAY% --start %START%
)

if errorlevel 1 (
    echo.
    echo ERROR: Benchmark failed. Check output above.
    pause
    exit /b 1
)

REM Step 2: Parse results
echo.
echo [2/3] Parsing results...
python parse_results.py
if errorlevel 1 (
    echo ERROR: parse_results.py failed.
    pause
    exit /b 1
)

REM Step 3: Run judge
echo.
echo [3/3] Running judge...
python judge.py
if errorlevel 1 (
    echo ERROR: judge.py failed.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  DONE! Results saved in responses\YYYY-MM-DD\
echo  - benchmark_results.csv  (raw scores)
echo  - judge_results.csv      (judge scores per dimension)
echo ============================================================
pause
