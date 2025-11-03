@echo off
cd /d "D:\Projektit\Pricecheck"
echo [%date% %time%] Starting >> elec_log.txt
call venv\Scripts\activate
python bot_fetch.py >> elec_log.txt 2>&1
echo [%date% %time%] Finising >> elec_log.txt