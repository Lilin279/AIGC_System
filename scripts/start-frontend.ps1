$ErrorActionPreference = "Stop"
Set-Location -Path "$PSScriptRoot\..\frontend"
npm.cmd install
npm.cmd run dev
