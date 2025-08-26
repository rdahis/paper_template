REM Run the .bat file path in Command Prompt as Administrator

REM -- Folder -- 
@echo off 
set NON_VERSIONED_PATH=C:\path\to\source_folder 
set REPO_PATH=C:\path\to\link_folder 

mklink /D "%REPO_PATH%" "%NON_VERSIONED_PATH%" 
pause

REM -- File --
@echo off 
set NON_VERSIONED_FILE_PATH=C:\path\to\source_file.csv 
set REPO_PATH=C:\path\to\link_folder 

REM Delete existing symlink if it exists (for file)
if exist %REPO_PATH%\%FILENAME (
    del %REPO_PATH%\%FILENAME
)

mklink "%REPO_PATH%\%FILENAME%" "%NON_VERSIONED_FILE_PATH%" 
pause
