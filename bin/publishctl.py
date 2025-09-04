#!/usr/bin/env python3

from __future__ import annotations
import os, sys, subprocess, json, time
from pathlib import Path
import typer, yaml, jinja2, requests

app = typer.Typer()

BASE = Path('/opt/publisher')
TPL = BASE / 'templates'
APACHE_SITES = Path('/etc/apache2/sites-available')
STATE = BASE / 'var/state.json'

class Sh:
    @staticmethod
    def run(cmd: list[str], check=True, capture=False):
        """Run a shell command."""
        print('+', ' '.join(cmd))
        return subprocess.run(cmd, check=check, capture_output=capture, text=True)

def render(template_rel: str, ctx: dict) -> str:
    """Render a jinja2 template from the TPL directory."""
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(TPL))
    tpl = env.get_template(template_rel)
    return tpl.render(**ctx)

def write_file(path: Path, content: str, mode=0o644):
    """Write content to a file atomically, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(content)
    os.chmod(tmp, mode)
    tmp.replace(path)

def load_manifest(manifest_path: Path) -> dict:
    """Load a YAML manifest file and return its contents as a dictionary."""
    data = yaml.safe_load(manifest_path.read_text())
    data['__manifest_path'] = str(manifest_path)
    return data

def ensure_ssl(fqdn: str):
    Sh.run(['sudo', 'certbot', '--apache', '-n', '--agree-tos', '-m', 'admin@' + fqdn.split('.',1)[-1], '-d', fqdn, '--redirect'])

def apache_apply(m: dict):
    """Render and apply an Apache virtual host configuration, then enable the site and reload Apache."""
    vhost = render(f"apache/{m['apache']['template']}", {
        'fqdn': m['fqdn'],
        'backend_host': m.get('backend', {}).get('host', '127.0.0.1'),
        'backend_port': m.get('backend', {}).get('port', 8000),
        'docroot': m.get('flutter', {}).get('document_root', '/var/www/html'),
        'log_prefix': m['apache'].get('log_prefix', m['name'])
    })
    vhost_path = APACHE_SITES / f"{m['fqdn']}.conf"
    write_file(vhost_path, vhost)
    Sh.run(['sudo', 'a2ensite', f"{m['fqdn']}.conf"]) # idempotent
    Sh.run(['sudo', 'service', 'apache2', 'reload'])

def systemd_apply(m: dict):
    """Render and apply a systemd service file, then enable and start the service."""
    template = m['service']['template']
    svc_name = m['name'] + '.service'
    unit = render(f'systemd/{template}', {
        'user': m['service']['user'],
        'group': m['service']['group'],
        'workdir': m['backend']['working_dir'],
        'uvicorn_module': m.get('backend', {}).get('entrypoint', {}).get('module', ''),
        'uvicorn_args': m.get('backend', {}).get('entrypoint', {}).get('extra_args', ''),
        'venv': m.get('backend', {}).get('entrypoint', {}).get('venv', ''),
        'cmd': m.get('backend', {}).get('entrypoint', {}).get('cmd', ''),
        'port': m.get('backend', {}).get('port', 8000),
    })
    write_file(Path('/etc/systemd/system') / svc_name, unit, 0o644)
    Sh.run(['sudo', 'systemctl', 'daemon-reload'])
    Sh.run(['sudo', 'systemctl', 'enable', '--now', svc_name])

def docker_apply(m: dict):
    """Render and apply a docker-compose file, then bring up the stack."""
    compose = render('docker/docker-compose.j2', m)
    write_file(Path(m['docker']['compose_path']), compose)
    Sh.run(['sudo', 'docker', 'compose', '-f', m['docker']['compose_path'], '-p', m['docker']['project'], 'up', '-d'])

def deploy_code(m: dict):
    """Clone or update the code repository and run preinstall commands."""
    wd = Path(m['backend']['working_dir']) if 'backend' in m else Path('/srv')/m['name']
    wd.mkdir(parents=True, exist_ok=True)
    if 'scm' in m:
        repo = m['scm']['repo']; branch = m['scm'].get('branch','main')
        if not (wd/'.git').exists():
            Sh.run(['git', 'clone', '--depth=1', '--branch', branch, repo, str(wd)])
    else:
        Sh.run(['git', '-C', str(wd), 'fetch', 'origin', branch, '--depth=1'])
        Sh.run(['git', '-C', str(wd), 'reset', '--hard', f'origin/{branch}'])
    for cmd in m.get('deploy',{}).get('preinstall', []):
        Sh.run(['bash','-lc', f"cd {wd} && {cmd}"])


@app.command()
def apply(manifest: Path):
    """Apply (create/update) an app from manifest."""
    m = load_manifest(manifest)
    kind = m['kind']

    if kind in ('fastapi','streamlit'):
        deploy_code(m)
        systemd_apply(m)
        apache_apply(m)
    elif kind == 'flutter':
        # flutter artifacts should already be present or delivered by CI
        apache_apply(m)
        docroot = Path(m['flutter']['document_root'])
        docroot.mkdir(parents=True, exist_ok=True)
    elif kind == 'docker':
        deploy_code(m)
        docker_apply(m)
        # apache reverse proxy to published host:port
        if 'apache' in m:
            m.setdefault('backend', {})
            hp = m['docker']['publish']['http_target']
            host, port = hp.split(':')
            m['backend']['host'] = host
            m['backend']['port'] = int(port)
            apache_apply(m)
    else:
        typer.echo(f"Unsupported kind: {kind}")
        raise typer.Exit(2)

    if m.get('ssl'):
        ensure_ssl(m['fqdn']) # fqdn = fully qualified domain name

    # healthcheck
    h = m.get('healthcheck',{})
    if h.get('url'):
        try:
            r = requests.get(h['url'], timeout=h.get('timeout',5))
            typer.echo(f"Health: {r.status_code}")
        except Exception as e:
            typer.echo(f"Healthcheck failed: {e}")

@app.command()
def status(name: str = ''):
    """Show status for all apps or one app."""
    apps = sorted(Path('/opt/publisher/apps').glob('*.yml'))
    for path in apps:
        m = load_manifest(path)
        if name and m['name'] != name:
            continue
        svc = m['name'] + '.service'
        print(f"\n[{m['name']}] {m['fqdn']} ({m['kind']})")
        # apache site enabled?
        site = (APACHE_SITES / f"{m['fqdn']}.conf").exists()
        print(' apache site:', 'present' if site else 'missing')
        # systemd/docker
        if m['kind'] in ('fastapi','streamlit'):
            rc = subprocess.call(['systemctl','is-active','--quiet',svc])
            print(' service:', 'active' if rc==0 else 'inactive')
        if m['kind']=='docker':
            subprocess.call(['docker','ps'])
        # health
        url = m.get('healthcheck',{}).get('url')
        if url:
            try:
                r = requests.get(url, timeout=3)
                print(' health:', r.status_code)
            except Exception:
                print(' health: failed')

if __name__ == '__main__':
    app()
