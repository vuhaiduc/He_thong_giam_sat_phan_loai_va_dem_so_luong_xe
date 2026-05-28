@echo off
REM Quick start script for the Vehicle Counter Web Interface

echo.
echo ========================================
echo  YOLO Vehicle Counter - Web Interface
echo ========================================
echo.

REM Check if virtual environment exists
if not exist "myenv\Scripts\activate.bat" (
    echo Creating virtual environment...
    python -m venv myenv
)

REM Activate virtual environment
call myenv\Scripts\activate.bat

REM Install/upgrade dependencies
echo.
echo Installing dependencies...
pip install -r requirements.txt

REM Start the web server
echo.
echo ========================================
echo  Starting Web Server...
echo ========================================
echo.
echo Opening dashboard at: http://localhost:5000
echo Press CTRL+C to stop the server
echo.

start http://localhost:5000
python app.py
