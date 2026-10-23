"""Render deployment files only; never installs, starts, migrates, or changes data."""
import argparse
import json
from pathlib import Path, PurePosixPath
import re


def render(config, output, profile='https'):
    config = {'nginx_user': 'www-data', 'nginx_group': 'www-data', **config}
    required = {'project_root', 'venv_root', 'frontend_root', 'static_root', 'domain',
                'environment_file', 'service_user', 'service_group', 'processes', 'threads',
                'upload_body_limit_mib', 'read_timeout_seconds', 'stop_timeout_seconds', 'nginx_user', 'nginx_group'}
    if profile == 'https':
        required |= {'certificate', 'certificate_key'}
    missing = required - config.keys()
    if missing:
        raise ValueError('Missing parameters: ' + ', '.join(sorted(missing)))
    values = {}
    for key in required:
        value = config[key]
        if key in {'processes', 'threads', 'upload_body_limit_mib', 'read_timeout_seconds', 'stop_timeout_seconds'}:
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1048576:
                raise ValueError(f'{key} must be a positive bounded integer')
        elif not isinstance(value, str) or not value or '__REQUIRED_' in value:
            raise ValueError(f'{key} requires an explicit value')
        if key.endswith('_root') or key in {'environment_file', 'certificate', 'certificate_key'}:
            if not PurePosixPath(value).is_absolute() or re.search(r'[\s"\'`;${}\\\x00-\x1f]', value):
                raise ValueError(f'{key} requires a Linux absolute path without shell/config metacharacters')
        if key in {'service_user', 'service_group', 'nginx_user', 'nginx_group'} and not re.fullmatch(r'[a-z_][a-z0-9_-]*', value):
            raise ValueError(f'Invalid {key}')
        values[key.upper()] = str(value)
    domain = values['DOMAIN']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', domain) or '..' in domain:
        raise ValueError('domain must be a single hostname or IPv4 address')
    if profile == 'https' and (domain in {'localhost', 'example.com'} or domain.endswith(('.example', '.invalid'))):
        raise ValueError('Replace the test/placeholder domain before HTTPS deployment')
    if profile == 'http-test' and domain not in {'localhost', '127.0.0.1'}:
        raise ValueError('HTTP test profile only accepts localhost or 127.0.0.1')
    output = Path(output)
    # Generated Linux paths may be rendered on Windows; never embed the host's C: path.
    output_root = config.get('config_root', '/etc/stoichioomics')
    if not PurePosixPath(output_root).is_absolute() or re.search(r'[\s"\'`;${}\\\x00-\x1f]', output_root):
        raise ValueError('config_root must be a safe Linux absolute path')
    values['OUTPUT_ROOT'] = output_root
    if profile == 'https':
        values['LISTEN'] = '443 ssl'
        values['TLS'] = ('ssl_certificate "' + values['CERTIFICATE'] + '";\n'
                         '    ssl_certificate_key "' + values['CERTIFICATE_KEY'] + '";\n'
                         '    ssl_protocols TLSv1.2 TLSv1.3;')
        values['HTTP_REDIRECT'] = ('server {\n    listen 80;\n    server_name ' + domain + ';\n'
            '    return 308 https://' + domain + '$request_uri;\n}\n')
    elif profile == 'http-test':
        values['LISTEN'] = '127.0.0.1:18080'
        values['TLS'] = '# Explicit loopback HTTP test profile; not public HTTPS acceptance.'
        values['HTTP_REDIRECT'] = '# HTTP test profile'
    else:
        raise ValueError('Unknown profile')
    output.mkdir(parents=True, exist_ok=True)
    files = []
    for template in sorted((Path(__file__).parent / 'templates').glob('*.in')):
        content = template.read_text(encoding='utf-8')
        for key, value in values.items():
            content = content.replace('@' + key + '@', value)
        if re.search(r'@[A-Z_]+@|__REQUIRED_', content):
            raise ValueError(f'Unresolved placeholders in {template.name}')
        target = output / template.name.removesuffix('.in')
        target.write_text(content, encoding='utf-8', newline='\n')
        files.append(target.name)
    (output / 'render-manifest.json').write_text(json.dumps({
        'profile': profile, 'files': files, 'linux_config_root': output_root,
        'resources': {k: config[k] for k in ('processes', 'threads', 'upload_body_limit_mib', 'read_timeout_seconds', 'stop_timeout_seconds')},
        'note': 'Resources are initial test values until measured on the target server.'
    }, indent=2), encoding='utf-8')
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--profile', choices=['https', 'http-test'], default='https')
    args = parser.parse_args()
    try:
        files = render(json.loads(Path(args.config).read_text(encoding='utf-8')), args.output, args.profile)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print('Rendered only: ' + ', '.join(files))


if __name__ == '__main__':
    main()
