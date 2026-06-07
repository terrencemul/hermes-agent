#!/bin/sh
set -e

# Generate htpasswd from environment variables
if [ -z "$NGINX_AUTH_USER" ] || [ -z "$NGINX_AUTH_PASSWORD" ]; then
    echo "Error: NGINX_AUTH_USER and NGINX_AUTH_PASSWORD environment variables must be set"
    exit 1
fi

# Create htpasswd file
htpasswd -c -b /etc/nginx/.htpasswd "$NGINX_AUTH_USER" "$NGINX_AUTH_PASSWORD"

# Substitute HERMES_HOST in nginx.conf
if [ -z "$HERMES_HOST" ]; then
    echo "Error: HERMES_HOST environment variable must be set"
    exit 1
fi

envsubst '$HERMES_HOST' < /etc/nginx/nginx.conf > /etc/nginx/nginx.conf.tmp
mv /etc/nginx/nginx.conf.tmp /etc/nginx/nginx.conf

# Start nginx
exec nginx -g "daemon off;"

