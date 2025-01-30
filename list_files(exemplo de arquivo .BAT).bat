@echo off
echo ls /from_uber/trips | sftp -i "C:\Users\keys\private.pem" -oPort=2222 "seu_username"@sftp.uber.com