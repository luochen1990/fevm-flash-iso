@echo off

net session >nul 2>nul
IF %ERRORLEVEL% EQU 0 goto :Admin_Run
echo.
echo This CMD needs to be run with administrator privileges.
echo There will be a pop-up window later. Please select "Yes"
TIMEOUT /T 5
mshta vbscript:CreateObject("Shell.Application").ShellExecute("cmd.exe","/c %~s0 ::","","runas",1)(window.close)
exit

:Admin_Run
@cd /d %~dp0
@chcp 65001
cls
set Afu_arg=/CAPSULE /P /B /N /K /L /X /RLC:E
rem set Afu_arg=/RECOVERY /P /B /N /K /L /X /RLC:E
rem set Afu_arg=/P /B /N /K /L /X /RLC:E
set BIOS_Path=.\

FOR /F "tokens=1,* delims=_- " %%A IN ("%~n0") DO (
    rem echo %%A %%B
    IF /I "%%A"=="Flash" set path_In_CMD=%%B
)
IF exist .\%path_In_CMD%\BIOS set BIOS_Path=.\%path_In_CMD%\BIOS\
rem echo BIOS file Path:%BIOS_Path%

echo.
PUSHD %cd%
cd %BIOS_Path%
setlocal enabledelayedexpansion
SET /A file_count=0
FOR /F "tokens=*" %%A IN ('dir *.bin,*.rom /B') DO (
    echo !file_count!   %%A    %%~tA
    set file_name_!file_count!=%%A
    SET /A file_count+=1
)
POPD
IF %file_count% EQU 0 ( 
    echo The BIOS file does not exist
    Goto :ERROR
) ELSE IF %file_count% EQU 1 (
    set BIOS_Name=%file_name_0% 
    Goto :Retry_BIOS
)

:get_num
echo.
SET num=0
SET /P num=Select the BIOS file to upgrade by entering its line number.
echo num=%num%
SET num=%num: =%
rem echo num="%num%"
IF NOT defined file_name_%num% goto :get_num
set BIOS_Name=!file_name_%num%! 

:Retry_BIOS
echo.
echo BIOS_Path:%BIOS_Path%
echo BIOS_Name:%BIOS_Name%
.\Tools\AFUWINx64.exe "%BIOS_Path%%BIOS_Name%" %Afu_arg%
IF %errorlevel%==0 goto :PASS
pause
goto :Retry_BIOS

:ERROR
@ECHO.
@ECHO =======ERROR=======
@ECHO.
pause
goto :EOF

:PASS
@REM cls
@color 0A
@ECHO.
@ECHO.
@ECHO =======PASS=======
@ECHO.
@ECHO.
pause
shutdown -r -t 0