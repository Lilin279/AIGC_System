$ErrorActionPreference = "Stop"
try {
  Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/admin/reset-demo"
  Write-Host "Demo data reset."
} catch {
  Write-Host "Backend is not running. Delete backend\data manually after stopping the server, or start the backend first."
  throw
}
