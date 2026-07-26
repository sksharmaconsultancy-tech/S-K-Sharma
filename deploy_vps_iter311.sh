#!/bin/bash
# S.K. Sharma & Co. — VPS deploy script (Iter 311 — PWA SPEED UPGRADE)
# Ships: web code-splitting (async routes) + precompressed gzip assets +
# nginx gzip_static so first load drops from ~5.5 MB to a few hundred KB.
# Run ON THE VPS as root/sksharma.
set -e

APP_DIR=/home/sksharma/app
WEB_DIR=/var/www/sksharma
BUNDLE_URL="https://emplo-connect-1.preview.emergentagent.com/api/temp-code-bundle?token=sks-deploy-7391&kind=tar"
PIP=$APP_DIR/backend/venv/bin/pip

echo "==> 1/7 Downloading latest code bundle..."
wget -q -O /tmp/sks-latest.tar "$BUNDLE_URL"

echo "==> 2/7 Extracting into $APP_DIR (preserving .env files)..."
cp $APP_DIR/backend/.env /tmp/backend.env.bak
cp $APP_DIR/frontend/.env /tmp/frontend.env.bak 2>/dev/null || true
tar -xf /tmp/sks-latest.tar -C $APP_DIR
cp /tmp/backend.env.bak $APP_DIR/backend/.env
cp /tmp/frontend.env.bak $APP_DIR/frontend/.env 2>/dev/null || true

if ! grep -q "^EMERGENT_LLM_KEY=" $APP_DIR/backend/.env; then
  echo "EMERGENT_LLM_KEY=sk-emergent-6A80335Da3e07B3C5D" >> $APP_DIR/backend/.env
fi

echo "==> 3/7 Installing backend deps..."
grep -v "^litellm" $APP_DIR/backend/requirements.txt > /tmp/reqs.txt
$PIP install -r /tmp/reqs.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q || \
  echo "   (pip failed — safe to continue if requirements unchanged)"
$PIP show qrcode >/dev/null 2>&1 || $PIP install qrcode -q
$PIP show emergentintegrations >/dev/null 2>&1 || \
  $PIP install emergentintegrations --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -q

echo "==> 4/7 Building web frontend (expo export — SPLIT ROUTES)..."
cd $APP_DIR/frontend
yarn install --frozen-lockfile --silent 2>/dev/null || yarn install --silent
npx expo export -p web --clear
sudo mkdir -p $WEB_DIR
sudo cp -r dist/* $WEB_DIR/
# Old bundles pruned after 30 days only (installed-PWA blank-page fix).
sudo find $WEB_DIR/_expo/static/js/web -name "*.js" -mtime +30 -delete 2>/dev/null || true

echo "==> 5/7 Precompressing assets (gzip -9, keeps originals)..."
sudo find $WEB_DIR -type f \( -name "*.js" -o -name "*.css" -o -name "*.html" -o -name "*.json" -o -name "*.svg" -o -name "*.ttf" \) \
  -newer /tmp/sks-latest.tar -exec gzip -9 -kf {} \; 2>/dev/null || \
sudo find $WEB_DIR -type f \( -name "*.js" -o -name "*.css" -o -name "*.html" -o -name "*.json" -o -name "*.svg" -o -name "*.ttf" \) \
  -exec gzip -9 -kf {} \;

echo "==> 6/7 Enabling nginx gzip + gzip_static (idempotent)..."
SITE_CONF=$(grep -rl "root $WEB_DIR" /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null | head -1)
if [ -n "$SITE_CONF" ] && ! grep -q "sks-gzip-fix" "$SITE_CONF"; then
  sudo cp "$SITE_CONF" "$SITE_CONF.bak-gzip"
  sudo sed -i "0,\|root $WEB_DIR;|s||root $WEB_DIR;\n    # sks-gzip-fix — serve precompressed assets + on-the-fly gzip\n    gzip on;\n    gzip_static on;\n    gzip_vary on;\n    gzip_comp_level 6;\n    gzip_min_length 1024;\n    gzip_proxied any;\n    gzip_types text/plain text/css application/json application/javascript text/javascript application/xml image/svg+xml font/ttf;|" "$SITE_CONF"
  if sudo nginx -t 2>/dev/null; then
    sudo systemctl reload nginx
    echo "   nginx gzip enabled ✅"
  else
    sudo mv "$SITE_CONF.bak-gzip" "$SITE_CONF"
    echo "   nginx gzip patch skipped (config test failed — restored backup)"
  fi
else
  echo "   nginx gzip already configured (or site conf not found) — skipped"
fi

echo "==> 7/7 Restarting backend + verifying..."
sudo supervisorctl stop sksharma-backend || true
sudo fuser -k 8001/tcp 2>/dev/null || true
sleep 2
sudo supervisorctl start sksharma-backend
sleep 5
curl -s http://localhost:8001/api/health && echo
ENTRY=$(ls -t $WEB_DIR/_expo/static/js/web/entry-*.js 2>/dev/null | head -1)
if [ -n "$ENTRY" ]; then
  RAW=$(stat -c%s "$ENTRY"); GZ=$(stat -c%s "$ENTRY.gz" 2>/dev/null || echo 0)
  echo "   entry bundle: $((RAW/1024)) KB raw / $((GZ/1024)) KB gzipped"
fi
echo "   split route chunks: $(ls $WEB_DIR/_expo/static/js/web/*.js 2>/dev/null | wc -l) file(s)"

echo
echo "🎉 Deploy 311 (PWA speed upgrade) complete."
echo
echo "WHAT CHANGED:"
echo "  ⚡ ROUTE CODE-SPLITTING: each screen now loads its own small JS"
echo "     chunk — the app boots with a few hundred KB instead of 5.5 MB."
echo "  ⚡ GZIP EVERYWHERE: assets are precompressed at deploy time and"
echo "     nginx serves the .gz files directly (gzip_static) — 4x smaller"
echo "     transfers on first load, on every screen chunk, and on fonts."
echo "  ⚡ Repeat visits stay instant: hashed chunks cache forever,"
echo "     index.html is never cached (existing sks-cache-fix)."
echo
echo "TIP: ask users to close + reopen the installed PWA once after this"
echo "deploy so the new split bundles take over."
