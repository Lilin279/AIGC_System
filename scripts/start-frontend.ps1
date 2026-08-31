$ErrorActionPreference = "Stop"
Set-Location -Path "$PSScriptRoot\..\frontend"
npm.cmd install
# 直接调用 vite 的 JS 入口，绕过 node_modules/.bin 下的 .cmd 壳脚本。
# 原因：项目路径含中文和 "&" 字符，cmd.exe 会把 "&" 当命令分隔符，导致 .cmd shim 解析失败。
& node "node_modules\vite\bin\vite.js" --host 127.0.0.1
