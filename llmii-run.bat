@echo off
setlocal enabledelayedexpansion

REM Set the name of your virtual environment
set "VENV_NAME=llmii_env"

REM Set the path to your Python installation (update this if needed)
set "PYTHON_PATH=python"

REM Check if Python is installed and in PATH
%PYTHON_PATH% --version >nul 2>&1
if errorlevel 1 (
    echo Python is not found. Please ensure Python is installed and added to your PATH.
    pause
    exit /b 1
)

REM Check if exiftool is installed and in PATH
where exiftool >nul 2>&1
if errorlevel 1 (
    echo exiftool is not found. Attempting to install using winget...
    winget install -e --id OliverBetz.ExifTool
    if errorlevel 1 (
        echo Failed to install exiftool. Please install it manually.
        pause
        exit /b 1
    )
    echo exiftool has been installed. Please restart this script for the changes to take effect.
    pause
    exit /b 0
) else (
    echo exiftool is already installed.
)

REM Check if the virtual environment exists, create if it doesn't
if not exist "%VENV_NAME%\Scripts\activate.bat" (
    echo Creating new virtual environment: %VENV_NAME%
    %PYTHON_PATH% -m venv %VENV_NAME%
    if errorlevel 1 (
        echo Failed to create virtual environment. Please check your Python installation.
        pause
        exit /b 1
    )
) else (
    echo Virtual environment %VENV_NAME% already exists.
)

REM Activate the virtual environment
call "%VENV_NAME%\Scripts\activate.bat"

REM Check if requirements.txt exists
if not exist requirements.txt (
    echo requirements.txt not found. Please create a requirements.txt file in the same directory as this script.
    pause
    exit /b 1
)

REM Upgrade pip to the latest version
python -m pip install --upgrade pip

REM Install packages from requirements.txt
echo Installing packages from requirements.txt...
pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install some packages. Please check your internet connection and requirements.txt file.
    pause
    exit /b 1
)

REM Download NLTK data
echo Downloading NLTK data...
python -c "import nltk; nltk.download('wordnet')"
cls


set "TEXT_MODEL=https://huggingface.co/bartowski/Qwen2-VL-7B-Instruct-GGUF/blob/main/Qwen2-VL-7B-Instruct-Q4_K_M.gguf"
set "IMAGE_PROJECTOR=https://huggingface.co/bartowski/Qwen2-VL-7B-Instruct-GGUF/blob/main/mmproj-Qwen2-VL-7B-Instruct-f16.gguf"


REM Check if koboldcpp.exe exists, if not, check for koboldcpp_cu12.exe
if exist koboldcpp.exe (
    set "KOBOLD_EXE=koboldcpp.exe"
) else if exist koboldcpp_cu12.exe (
    set "KOBOLD_EXE=koboldcpp_cu12.exe"
) else (
    echo Neither koboldcpp.exe nor koboldcpp_cu12.exe found. Please ensure one of these files exists.
    pause
    exit /b 1
)

REM Launch KoboldCPP with selected model
start %KOBOLD_EXE% %TEXT_MODEL% --mmproj %IMAGE_PROJECTOR% --flashattention --contextsize 4096

:Load
REM Launch your Python script
python llmii-gui.py
pause

REM Deactivate the virtual environment
deactivate

pause