import streamlit as st
import yaml, subprocess, json
from pathlib import Path


APPS = Path('/opt/publisher/apps')


st.set_page_config(page_title='Publisher', layout='wide')
st.title('Publisher — Apps')


col1, col2 = st.columns([2,1])
with col1:
    files = sorted(APPS.glob('*.yml'))
    sel = st.selectbox('Aplicações', files, format_func=lambda p: p.stem)
    if sel:
        code = sel.read_text()
        st.code(code, language='yaml')
        if st.button('Apply manifest'):
            r = subprocess.run(['sudo','/opt/publisher/bin/publishctl','apply',str(sel)], capture_output=True, text=True)
            st.text(r.stdout or r.stderr)


with col2:
    st.header('Nova aplicação')
    kind = st.selectbox('Tipo', ['fastapi','streamlit','flutter','docker'])
    name = st.text_input('Name')
    fqdn = st.text_input('Domain (FQDN)')
    if st.button('Criar manifest'):
        base = {
            'name': name, 'kind': kind, 'fqdn': fqdn,
            'ssl': True,
            'apache': {'template': f'{kind if kind!="flutter" else "flutter"}.conf.j2', 'http_to_https': True, 'log_prefix': name},
            'scm': {'repo': 'git@github.com:org/repo.git', 'branch': 'main'}
        }
        if kind in ('fastapi','streamlit'):
            base.update({
            'backend': {'host':'127.0.0.1','port': 8000 if kind=='fastapi' else 8501,
            'working_dir': f'/srv/{name}',
            'entrypoint': {'venv': f'/srv/{name}/.venv', 'module': 'main:app'}},
            'service': {'template': f'{kind}.service.j2', 'user':'ubuntu','group':'ubuntu'},
            'deploy': {'strategy': 'native','preinstall': ['python3 -m venv .venv','./.venv/bin/pip install -U pip wheel','./.venv/bin/pip install -r requirements.txt']}
            })
        elif kind=='flutter':
            base.update({'flutter': {'document_root': f'/var/www/{name}', 'artifact_dir': 'build/web'}, 'deploy': {'strategy':'native'}})
        elif kind=='docker':
            base.update({'docker': {'compose_path': f'/srv/{name}/docker-compose.yml', 'project': name, 'publish': {'http_target': '127.0.0.1:9000'}}, 'deploy': {'strategy':'docker'}})
        out = APPS / f'{name}.yml'
        out.write_text(yaml.safe_dump(base, sort_keys=False))
        st.success(f'Manifesto criado: {out}')
