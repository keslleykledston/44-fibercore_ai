# Cabeçalhos para o upstream do FiberCore. X-Forwarded-For é SOBRESCRITO (não anexado): o cliente não forja IP.
proxy_http_version 1.1;
proxy_set_header Connection "";
proxy_set_header Host $host;
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-Forwarded-Host $host;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Real-IP $remote_addr;
proxy_read_timeout 30s;
# o nginx é a única fonte dos cabeçalhos de segurança (evita duplicata com Next/Caddy)
proxy_hide_header X-Frame-Options;
proxy_hide_header Referrer-Policy;
proxy_hide_header Permissions-Policy;
proxy_hide_header X-Content-Type-Options;
proxy_hide_header Content-Security-Policy;
proxy_hide_header Strict-Transport-Security;
