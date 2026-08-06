# Deploying DeckEngine on AWS EC2 (Amazon Linux 2023)

Serves the web UI + API at **fmcg.skyquestinsights.com**. Generation is pure
Python; slide previews use headless LibreOffice (the Windows-only PowerPoint
COM path is auto-swapped out on Linux).

## 1. One-shot setup

```bash
sudo dnf install -y git
git clone https://github.com/addiskers/pptv1.git deckengine
cd deckengine
bash deploy/setup_ec2.sh          # python, fonts, libreoffice, deps + self-check
```

The self-check renders the demo deck and exports previews via LibreOffice; it
prints `SELF-CHECK PASSED` when the box is ready.

## 2. Secrets

```bash
cat > .env <<'EOF'
OPENAI_API_KEY=sk-...            # or ANTHROPIC_API_KEY=...
DECKENGINE_API_KEY=<long-random> # REQUIRED before public exposure
DECKENGINE_PREVIEW=soffice
EOF
```
`.env` is gitignored and auto-loaded by the app.

## 3. Run as a service

```bash
sudo cp deploy/deckengine.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now deckengine
systemctl status deckengine        # should be active (running)
curl -s localhost:8000/themes      # sanity: returns the theme list
```

## 4. Domain + TLS

Point `fmcg.skyquestinsights.com` A-record at the instance's public IP, open
ports 80/443 in the security group, then:

```bash
sudo dnf install -y nginx certbot python3-certbot-nginx
sudo cp deploy/nginx.conf.example /etc/nginx/conf.d/deckengine.conf
sudo systemctl enable --now nginx
sudo certbot --nginx -d fmcg.skyquestinsights.com
```

Visit **https://fmcg.skyquestinsights.com**.

## Notes

- **Fonts** — themes use Georgia + Segoe UI; on Linux they resolve to metric
  clones (Gelasio/Selawik if the download succeeded, else Liberation/DejaVu).
  The output `.pptx` still names the real fonts, so it renders natively on any
  client that has them. Generation fails loudly if no font resolves — the
  setup self-check catches that before you deploy.
- **Previews** — `DECKENGINE_PREVIEW=soffice`. If LibreOffice is missing,
  previews are simply skipped (the deck still downloads); the vision judge
  falls back to its deterministic pick.
- **Updating** — `git pull && source .venv/bin/activate && pip install -e ".[server]" && sudo systemctl restart deckengine`.
- **Auth** — `DECKENGINE_API_KEY` gates the API; send it as the `X-API-Key`
  header. The bundled UI is open at `/`; add your own auth layer (or an nginx
  `auth_basic`) if the page itself must be private.
