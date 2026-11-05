import argparse
import ipaddress
import os

import uvicorn

def trusted_proxy_hosts(value: str) -> str:
    """Only explicitly named proxy IPs may supply client/scheme headers."""
    if not value.strip():
        return ''
    try:
        return ','.join(str(ipaddress.ip_address(host.strip())) for host in value.split(','))
    except ValueError as error:
        raise argparse.ArgumentTypeError('Trusted proxies must be comma-separated IP addresses, without wildcards or networks.') from error


def main(argv=None):
    parser = argparse.ArgumentParser(description='运行内网产品图片库')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', default=8750, type=int)
    parser.add_argument('--trusted-proxies', type=trusted_proxy_hosts,
                        default=os.environ.get('ASSET_TRUSTED_PROXIES', ''),
                        help='反向代理 IP，逗号分隔；默认不信任转发头')
    args = parser.parse_args(argv)
    uvicorn.run('app.main:app', host=args.host, port=args.port, workers=1,
                proxy_headers=bool(args.trusted_proxies), forwarded_allow_ips=args.trusted_proxies)


if __name__ == '__main__':
    main()
