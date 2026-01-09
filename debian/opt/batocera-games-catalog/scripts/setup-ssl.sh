#!/bin/bash
# Setup SSL certificate with Let's Encrypt using certbot

set -e

DOMAIN="${1:-}"
EMAIL="${2:-}"

if [ -z "$DOMAIN" ]; then
    echo "Usage: $0 <domain> [email]"
    echo "Example: $0 example.com admin@example.com"
    exit 1
fi

if [ -z "$EMAIL" ]; then
    echo "Warning: No email provided. Let's Encrypt recommends providing an email for renewal reminders."
    read -p "Continue without email? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
    EMAIL_OPT=""
else
    EMAIL_OPT="--email $EMAIL"
fi

echo "Setting up SSL certificate for domain: $DOMAIN"

# Check if certbot is installed
if ! command -v certbot &> /dev/null; then
    echo "Installing certbot..."
    apt-get update
    apt-get install -y certbot python3-certbot-nginx
fi

# Check if nginx is installed and running
if ! command -v nginx &> /dev/null; then
    echo "Installing nginx..."
    apt-get update
    apt-get install -y nginx
fi

# Update nginx config with domain name
NGINX_CONF="/etc/nginx/sites-available/batocera-games-catalog"
if [ -f "$NGINX_CONF" ]; then
    echo "Updating nginx configuration with domain: $DOMAIN"
    sed -i "s/server_name _;/server_name $DOMAIN;/g" "$NGINX_CONF"
    sed -i "s|YOUR_DOMAIN|$DOMAIN|g" "$NGINX_CONF"
    
    # Enable site if not already enabled
    if [ ! -L "/etc/nginx/sites-enabled/batocera-games-catalog" ]; then
        ln -s "$NGINX_CONF" /etc/nginx/sites-enabled/batocera-games-catalog
    fi
    
    # Test nginx configuration
    nginx -t
    
    # Reload nginx
    systemctl reload nginx
fi

# Obtain certificate
echo "Obtaining SSL certificate from Let's Encrypt..."
if [ -n "$EMAIL_OPT" ]; then
    certbot --nginx -d "$DOMAIN" $EMAIL_OPT --agree-tos --non-interactive --redirect
else
    certbot --nginx -d "$DOMAIN" --register-unsafely-without-email --agree-tos --non-interactive --redirect
fi

# Setup automatic renewal
echo "Setting up automatic renewal..."
systemctl enable certbot.timer
systemctl start certbot.timer

echo ""
echo "SSL certificate setup complete!"
echo "Certificate location: /etc/letsencrypt/live/$DOMAIN/"
echo ""
echo "To test renewal: sudo certbot renew --dry-run"
echo "To view certificates: sudo certbot certificates"








