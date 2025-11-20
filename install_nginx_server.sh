#!/bin/bash
# =============================================
# Nginx安装和配置脚本（在远程服务器上执行）
# =============================================

echo "【1/4】安装nginx..."
sudo apt update -qq && sudo apt install -y nginx

echo ""
echo "【2/4】配置nginx反向代理..."
sudo tee /etc/nginx/sites-available/default > /dev/null << 'NGINXCONF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    # Gzip压缩（优化传输）
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml text/javascript;
    gzip_comp_level 6;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket支持
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # CORS头（允许跨域）
        add_header Access-Control-Allow-Origin *;
        add_header Access-Control-Allow-Methods 'GET, POST, OPTIONS';
        add_header Access-Control-Allow-Headers 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range';
        
        # 代理缓冲优化
        proxy_buffering on;
        proxy_buffer_size 4k;
        proxy_buffers 8 4k;
        proxy_busy_buffers_size 8k;
        
        # 超时设置
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
NGINXCONF

echo ""
echo "【3/4】测试nginx配置..."
sudo nginx -t

echo ""
echo "【4/4】启动nginx..."
sudo systemctl start nginx
sudo systemctl enable nginx

echo ""
echo "【5/5】验证端口监听..."
sleep 2
sudo netstat -tlnp | grep -E ":80|:8000"

echo ""
echo "=========================================="
echo "✅ Nginx安装配置完成！"
echo "  📡 外网访问: http://43.100.52.142"
echo "  🔧 Gunicorn: 127.0.0.1:8000"
echo "  🔄 Nginx代理: 0.0.0.0:80 -> 127.0.0.1:8000"
echo ""
echo "现在可以通过 http://43.100.52.142 访问前端了！"
echo "=========================================="

