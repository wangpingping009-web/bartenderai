@echo off
cd /d D:\xunlei\BartenderAI
docker compose --profile app build backend > D:\xunlei\BartenderAI\backend\models\docker-build.log 2>&1
echo BUILD_EXIT=%ERRORLEVEL% >> D:\xunlei\BartenderAI\backend\models\docker-build.log
