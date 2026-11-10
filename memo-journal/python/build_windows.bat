@echo off
chcp 65001 >nul
rem 메모+일지를 윈도우 실행 파일(exe)로 묶는다.
rem   build_windows.bat          exe 하나 (dist\MemoJournal.exe)
rem   build_windows.bat folder   폴더 형태 (dist\MemoJournal\MemoJournal.exe, 시작이 더 빠름)
setlocal
cd /d "%~dp0"

set MODE=--onefile
set OUT=dist\MemoJournal.exe
if /i "%~1"=="folder" (
  set MODE=--onedir
  set OUT=dist\MemoJournal\MemoJournal.exe
)

python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto fail
python make_icon.py build\app.ico
if errorlevel 1 goto fail
python -m PyInstaller --noconfirm --clean --windowed %MODE% --name MemoJournal --icon build\app.ico main.py
if errorlevel 1 goto fail

echo.
echo 완료: %OUT%
echo 이 파일(또는 폴더)만 다른 PC로 복사하면 파이썬 없이 실행됩니다.
exit /b 0

:fail
echo.
echo 빌드 실패. 위의 오류 내용을 확인해 주세요.
exit /b 1
