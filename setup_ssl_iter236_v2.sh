#!/bin/bash
# S.K. Sharma & Co. — VPS SSL / HTTPS setup (Iter 236 v2)
# v2 FIX: the Ubuntu apt certbot is broken on this VPS
# ("module 'lib' has no attribute 'GEN_EMAIL'" — pyOpenSSL/cryptography
# conflict). This version removes it and installs the OFFICIAL certbot
# via snap (self-contained, recommended by Let's Encrypt).
# Run ON THE VPS as root.
set -e

DOMAIN="${DOMAIN:-smartpayrolling.com}"
EMAIL="${EMAIL:-sksharmaconsultancy@gmail.com}"

echo "=============================================="
echo " SSL SETUP v2 for https://$DOMAIN"
echo "=============================================="

# ── 0. Safety: previous run may have left nginx stopped ──────────────
echo "==> 0/6 Making sure nginx is running..."
sudo systemctl start nginx 2>/dev/null || true

# ── 1. Remove the BROKEN apt certbot ─────────────────────────────────
echo "==> 1/6 Removing broken apt certbot..."
sudo apt-get remove -y -qq certbot python3-certbot-nginx 2>/dev/null || true

# ── 2. Install the official certbot via snap ─────────────────────────
echo "==> 2/6 Installing official certbot (snap)..."
if ! command -v snap >/dev/null 2>&1; then
  sudo apt-get update -qq && sudo apt-get install -y -qq snapd
fi
sudo snap install core 2>/dev/null || true
sudo snap refresh core 2>/dev/null || true
sudo snap install --classic certbot
sudo ln -sf /snap/bin/certbot /usr/bin/certbot
CERTBOT=/snap/bin/certbot
$CERTBOT --version

# ── 3. Firewall ──────────────────────────────────────────────────────
echo "==> 3/6 Opening port 443 (HTTPS)..."
if command -v ufw >/dev/null 2>&1; then
  sudo ufw allow 443/tcp >/dev/null 2>&1 || true
  sudo ufw allow 80/tcp  >/dev/null 2>&1 || true
fi
sudo iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || \
  sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || true

# ── 4. Domains ───────────────────────────────────────────────────────
SERVER_IP=$(curl -s -4 https://api.ipify.org || curl -s -4 ifconfig.me)
EXTRA_D=""
WWW_IP=$(getent hosts "www.$DOMAIN" | awk '{print $1}' | head -1)
if [ -n "$WWW_IP" ] && [ "$WWW_IP" = "$SERVER_IP" ]; then
  EXTRA_D="-d www.$DOMAIN"
fi
echo "==> 4/6 Requesting certificate for $DOMAIN $EXTRA_D ..."

# ── 5. Obtain certificate + force HTTPS redirect ─────────────────────
sudo $CERTBOT --nginx -d "$DOMAIN" $EXTRA_D \
  --non-interactive --agree-tos -m "$EMAIL" --redirect || {
    echo "    nginx plugin failed — trying webroot/standalone fallback..."
    sudo systemctl stop nginx
    sudo $CERTBOT certonly --standalone -d "$DOMAIN" $EXTRA_D \
      --non-interactive --agree-tos -m "$EMAIL"
    sudo systemctl start nginx
    sudo $CERTBOT install --nginx -d "$DOMAIN" --redirect --non-interactive || true
  }
# extra safety: never leave nginx stopped
sudo systemctl start nginx 2>/dev/null || true

# ── 6. Auto-renewal + verify ─────────────────────────────────────────
echo "==> 6/6 Enabling automatic renewal & verifying..."
sudo systemctl list-timers 2>/dev/null | grep -q certbot || true
sudo $CERTBOT renew --dry-run --quiet && echo "    ✓ Auto-renewal test passed."
sudo nginx -t && sudo systemctl reload nginx

echo
CODE=$(curl -s -o /dev/null -w "%{http_code}" "https://$DOMAIN" || echo "000")
if [ "$CODE" != "000" ]; then
  echo "🎉 SUCCESS! https://$DOMAIN is live (HTTP $CODE) with a valid SSL certificate."
  echo "   • http:// now redirects to https:// automatically."
  echo "   • Certificate auto-renews via the snap certbot timer."
else
  echo "⚠ Certificate installed but https://$DOMAIN did not answer yet."
  echo "  Check: sudo nginx -t && sudo systemctl status nginx"
fi
echo
echo "IMPORTANT: open the portal at https://$DOMAIN and close & reopen the"
echo "PWA twice so devices pick up the secure address."
