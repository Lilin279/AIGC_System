$ErrorActionPreference = "Stop"
try {
  $loginBody = @{ username = "admin"; password = "Admin123!" } | ConvertTo-Json
  $session = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/auth/login" -ContentType "application/json" -Body $loginBody
  $headers = @{ Authorization = "Bearer $($session.token)" }
  Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/admin/reset-demo" -Headers $headers
  Write-Host "Demo data reset."
} catch {
  Write-Host "Reset failed. Confirm that the backend is running and the demo administrator account is available."
  throw
}
