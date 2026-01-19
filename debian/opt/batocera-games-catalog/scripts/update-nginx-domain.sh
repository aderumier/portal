#!/bin/bash
# Update nginx configuration with domain name

set -e

DOMAIN="${1:-}"

if [ -z "$DOMAIN" ]; then
    echo "Usage: $0 <domain>"
    echo "Example: $0 example.com"
    exit 1
fi

NGINX_CONF="/etc/nginx/sites-available/batocera-games-catalog"

if [ ! -f "$NGINX_CONF" ]; then
    echo "Error: Nginx configuration not found at $NGINX_CONF"
    exit 1
fi

echo "Updating nginx configuration with domain: $DOMAIN"

# Update server_name directives
sed -i "s/server_name _;/server_name $DOMAIN;/g" "$NGINX_CONF"

# Update SSL certificate paths
sed -i "s|YOUR_DOMAIN|$DOMAIN|g" "$NGINX_CONF"

# Test nginx configuration
echo "Testing nginx configuration..."
nginx -t

# Reload nginx if test passes
if [ $? -eq 0 ]; then
    echo "Reloading nginx..."
    systemctl reload nginx
    echo "Nginx configuration updated successfully!"
else
    echo "Error: Nginx configuration test failed. Please check the configuration."
    exit 1
fi














