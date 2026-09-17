# Deploying to the shared Hetzner box

A push to `dev` that passes every check deploys itself. `main` is never deployed
automatically. See [ADR-0016](../docs/adr/0016-hetzner-vps-for-the-dev-deployment.md)
for why a VPS, and what it is not suitable for.

```
  push to dev
      ↓
  CI: lint · types · tests · schema · image      ← all four must pass
      ↓
  build API image → GitHub Container Registry
  build review client → static files
      ↓
  ssh deploy@<box> → deploy/release.sh
      ↓
  migrate, then start
      ↓
  https://stackprep.binaax.app                   ← Caddy, TLS, password
```

Nothing of ours is published to the internet. The API listens on `127.0.0.1:8010`;
PostgreSQL and Redis are not published at all. Caddy, which was already on the box
for another project, is the only thing facing outward.

## One-time setup

Steps 1–2 need `sudo` and a human. Everything afterwards runs unattended, which is
the point: `sudo` on that box requires a password, so the pipeline is built to
never need it.

### 1 · Docker, and the deploy user's access to it

```sh
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo usermod -aG docker deploy
```

Log out and back in, then check it worked without sudo:

```sh
docker run --rm hello-world
```

Docker writes its own iptables rules and can bypass a host firewall. Every
container here binds to `127.0.0.1` or publishes nothing, so that does not apply —
but do not add a `ports:` entry without a host IP in front of it.

### 2 · The project directory and its secrets

```sh
sudo mkdir -p /opt/score-pilot
sudo chown deploy:deploy /opt/score-pilot

umask 077
cat > /opt/score-pilot/.env.local <<'ENV'
POSTGRES_PASSWORD=<generate one: openssl rand -base64 32>
ANTHROPIC_API_KEY=
ENV
```

The same convention the other project on this box uses: a `.env.local` inside the
project directory. It is never in git and never leaves the server.

### 3 · A key for GitHub Actions

Generate a keypair **dedicated to deploying** — do not reuse a personal key:

```sh
ssh-keygen -t ed25519 -f ~/.ssh/score_pilot_deploy -N '' -C 'github-actions deploy'
cat ~/.ssh/score_pilot_deploy.pub >> ~/.ssh/authorized_keys
cat ~/.ssh/score_pilot_deploy          # the private half — copy this
```

Add three repository secrets on GitHub (Settings → Secrets and variables → Actions):

| Secret | Value |
| --- | --- |
| `SSH_HOST` | the server's IP |
| `SSH_USER` | `deploy` |
| `SSH_PRIVATE_KEY` | the whole private key, `BEGIN` and `END` lines included |

Then delete the private key from the server — it belongs on GitHub, not here:

```sh
rm ~/.ssh/score_pilot_deploy
```

### 4 · The Caddy site block

Choose a password for the review tool and hash it:

```sh
caddy hash-password --plaintext 'the-password-you-chose'
```

Paste the contents of [`Caddyfile.snippet`](Caddyfile.snippet) onto the end of
`/etc/caddy/Caddyfile`, replacing `REPLACE_WITH_HASH` with that hash. Then:

```sh
sudo caddy validate --config /etc/caddy/Caddyfile   # check before reloading
sudo systemctl reload caddy
```

`validate` first, always. A reload with a broken config takes the other project
offline as well as ours.

## Everyday use

- **Deploy:** push to `dev`. That is the whole procedure.
- **Watch it:** the Actions tab, or `gh run watch`.
- **Logs:** `cd /opt/score-pilot && docker compose -f compose.yml logs -f api`
- **What is running:** `cat /opt/score-pilot/.deployed-image`
- **Roll back:** `IMAGE=<older tag from .deployed-image> docker compose --env-file .env.local -f compose.yml up -d`

## Backups

There are none yet. The database holds reviewed questions, which represent real
human effort and are not reproducible from the repository. Before anyone reviews
content here in earnest, add a dump to cron:

```sh
docker compose -f compose.yml exec -T postgres \
  pg_dump -U scorepilot scorepilot | gzip > backup-$(date +%F).sql.gz
```

## What this is not

A production deployment. One small shared box, no failover, no backups yet, and a
password in place of real authentication. Fine for content review during the
pilot; revisit [ADR-0011](../docs/adr/0011-hosting-and-delivery.md) before students
depend on it.
