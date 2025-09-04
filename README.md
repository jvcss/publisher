
# CLI: publishctl
### **Features**

- apply <manifest>: render+write Apache vhost, systemd/docker files; enable services; reload; obtain SSL.

- status [name]: summarize Apache, systemd, docker, and healthcheck.

- remove <name>: disable site and stop services (safe guard).

- logs <name>: tail relevant logs.

Entry script: `/opt/publisher/bin/publishctl`
```sh
#!/usr/bin/env bash
exec python3 /opt/publisher/bin/publishctl.py "$@"
```
> **Run**: `sudo /opt/publisher/bin/publishctl apply /opt/publisher/apps/my-fastapi.yml`

---
## Server bootstrap (one-time)

### Docker Engine + Compose v2 (official Docker repo)
```sh
# 1. Remove any conflicting packages (safe to run even if none installed)
for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
  sudo apt-get remove -y $pkg || true
done

# 2. Prereqs + keyring
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# 3. Add Docker APT repo (auto-detects focal codename)
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" \
| sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 4. Install Docker Engine + Buildx + Compose plugin
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 5. Enable/Start service
sudo systemctl enable --now docker
```

### Apache2 (with firewall profile)
```sh
sudo apt update
sudo apt install -y apache2
sudo systemctl enable --now apache2

# UFW (firewall) — allow HTTP/HTTPS and SSH
sudo ufw allow OpenSSH
sudo ufw allow 'Apache Full'   # opens 80 and 443
sudo ufw status # normally disable

# enable basics
sudo a2enmod proxy proxy_http ssl headers rewrite
sudo systemctl reload apache2
```

### Ubuntu 20.04+ (run as root or with sudo)
```sh
apt update && apt install -y python3-venv python3-pip git rsync jq apache2 certbot python3-certbot-apache
```

### Publisher home
```sh
mkdir -p /opt/publisher/{apps,templates,bin,var}
useradd -r -s /bin/bash publisher || true
chown -R publisher:publisher /opt/publisher
```

### Optional: allow 'publisher' to run a limited set of commands without password
```sh
cat >/etc/sudoers.d/publisher <<'EOF'
publisher ALL=(root) NOPASSWD: \
/usr/bin/systemctl *, \
/usr/sbin/a2ensite, /usr/sbin/a2dissite, /usr/sbin/a2enmod, \
/usr/sbin/service apache2 *, /bin/systemctl *, \
/usr/bin/certbot *, \
/usr/bin/docker *, /usr/bin/docker-compose *, \
/usr/bin/tee, /usr/bin/rm, /usr/bin/mv, /usr/bin/cp
EOF
chmod 440 /etc/sudoers.d/publisher
```

## Directory layout
```bash
/opt/publisher
├─ apps/ # one manifest per app (YAML)
├─ bin/
│ └─ publishctl # CLI entrypoint (Python Typer app)
├─ templates/
│ ├─ apache/
│ │ ├─ fastapi.conf.j2
│ │ ├─ streamlit.conf.j2
│ │ └─ flutter.conf.j2
│ ├─ systemd/
│ │ ├─ fastapi.service.j2
│ │ └─ streamlit.service.j2
│ └─ docker/
│ └─ docker-compose.j2
└─ var/
├─ state.json # registry of applied apps (generated)
└─ logs/
```