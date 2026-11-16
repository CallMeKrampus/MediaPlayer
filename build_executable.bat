@echo off
setlocal
title BOOB Player - Standalone Executable Builder

echo ===============================================================================
echo   BOOB Player - Standalone Portable Executable Packaging Tool (cx_Freeze)
echo ===============================================================================
echo.

cd /d "%~dp0"

:: 1. Run Pre-flight packaging check
echo [1/3] Running pre-flight verification check...
python build_exe.py --check
if errorlevel 1 (
    echo.
    echo [ERROR] Pre-flight verification failed! See error output above.
    goto :fail
)

echo.
echo [2/3] Building standalone portable executable in dist/BOOBPlayer...
python build_exe.py --build --archive
if errorlevel 1 (
    echo.
    echo [ERROR] Build execution failed!
    goto :fail
)

echo.
echo ===============================================================================
echo   [SUCCESS] Standalone portable package created successfully in dist/BOOBPlayer!
echo ===============================================================================
echo.
goto :done

:fail
echo.
echo ===============================================================================
echo   [BUILD FAILED] Please resolve the issues above and try again.
echo ===============================================================================
echo.

:done
if "%~1"=="" pause
endlocal
