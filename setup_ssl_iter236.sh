#!/bin/bash
# S.K. Sharma & Co. — VPS SSL / HTTPS setup (Iter 236)
# Installs a FREE Let's Encrypt SSL certificate for the portal, forces
# HTTPS (padlock 🔒 in the browser) and sets up automatic renewal every
# ~60 days so the certificate never expires.
# Run ON THE VPS as root (or a sudo user).
set -e

DOMAIN="${DOMAIN:-smartpayrolling.com}"
EMAIL="${EMAIL:-sksharmaconsultancy@gmail.com}"

echo "=============================================="
echo " SSL SETUP for https://$DOMAIN"
echo "=============================================="

# ── 1. Pre-checks ────────────────────────────────────────────────────
echo "==> 1/6 Checking DNS points to this server..."
SERVER_IP=$(curl -s -4 https://api.ipify.org || curl -s -4 ifconfig.me)
DOMAIN_IP=$(getent hosts "$DOMAIN" | awk '{print $1}' | head -1)
echo "    Server IP : $SERVER_IP"
echo "    $DOMAIN -> $DOMAIN_IP"
if [ -n "$DOMAIN_IP" ] && [ "$DOMAIN_IP" != "$SERVER_IP" ]; then
  echo "    ⚠ WARNING: DNS does not point to this server. Certificate"
  echo "      issuance may fail. Fix the A-record at your domain registrar"
  echo "      to $SERVER_IP and re-run this script."
fi

# Include www.<domain> only if its DNS also points here
EXTRA_D=""
WWW_IP=$(getent hosts "www.$DOMAIN" | awk '{print $1}' | head -1)
if [ -n "$WWW_IP" ] && [ "$WWW_IP" = "$SERVER_IP" ]; then
  EXTRA_D="-d www.$DOMAIN"
  echo "    www.$DOMAIN also points here — will be included in the certificate."
fi

# ── 2. Open firewall for HTTPS ───────────────────────────────────────
echo "==> 2/6 Opening port 443 (HTTPS) in the firewall..."
if command -v ufw >/dev/null 2>&1; then
  sudo ufw allow 443/tcp  >/dev/null 2>&1 || true
  sudo ufw allow 80/tcp   >/dev/null 2>&1 || true
fi
sudo iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || \
  sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || true

# ── 3. Install certbot ───────────────────────────────────────────────
echo "==> 3/6 Installing certbot (Let's Encrypt client)..."
if ! command -v certbot >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq certbot python3-certbot-nginx
else
  # make sure the nginx plugin is present even if certbot already exists
  sudo apt-get install -y -qq python3-certbot-nginx 2>/dev/null || true
fi

# ── 4. Make sure nginx knows the domain name ─────────────────────────
echo "==> 4/6 Checking nginx configuration..."
sudo nginx -t
if ! grep -rl "server_name.*$DOMAIN" /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null | head -1 | grep -q .; then
  echo "    server_name $DOMAIN not found in nginx — adding it to the default site..."
  CONF=$(grep -rl "root /var/www/sksharma" /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null | head -1)
  CONF=${CONF:-/etc/nginx/sites-enabled/default}
  sudo sed -i "s/server_name .*/server_name $DOMAIN www.$DOMAIN;/" "$CONF"
  sudo nginx -t && sudo systemctl reload nginx
fi

# ── 5. Obtain certificate + force HTTPS redirect ─────────────────────
echo "==> 5/6 Requesting the SSL certificate from Let's Encrypt..."
sudo certbot --nginx -d "$DOMAIN" $EXTRA_D \
  --non-interactive --agree-tos -m "$EMAIL" --redirect || {
    echo "    nginx plugin failed — trying standalone mode (brief nginx stop)..."
    sudo systemctl stop nginx
    sudo certbot certonly --standalone -d "$DOMAIN" $EXTRA_D \
      --non-interactive --agree-tos -m "$EMAIL"
    sudo systemctl start nginx
    # Wire the cert into nginx manually
    sudo certbot install --nginx -d "$DOMAIN" --redirect --non-interactive || true
  }

# ── 6. Auto-renewal + verify ─────────────────────────────────────────
echo "==> 6/6 Enabling automatic renewal & verifying..."
sudo systemctl enable --now certbot.timer 2>/dev/null || true
sudo certbot renew --dry-run --quiet && echo "    ✓ Auto-renewal test passed."
sudo nginx -t && sudo systemctl reload nginx

echo
CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://$DOMAIN" || echo "000")
if [ "$CODE" != "000" ]; then
  echo "🎉 SUCCESS! https://$DOMAIN is live (HTTP $CODE) with a valid SSL certificate."
  echo "   • All http:// traffic now redirects to https:// automatically."
  echo "   • The certificate renews automatically — nothing more to do."
else
  echo "⚠ Certificate installed but https://$DOMAIN did not answer yet."
  echo "  Check: sudo nginx -t && sudo systemctl status nginx"
fi
echo
echo "IMPORTANT: open the portal at https://$DOMAIN (with the S), close &"
echo "reopen the PWA twice so devices pick up the secure address."
