# Security Policy

## Reporting a Vulnerability

This project connects to Home Assistant and UniFi controllers within your home network. If you discover a security vulnerability:

1. **Do not** open a public GitHub issue
2. Send details to the project maintainers via a [private vulnerability report](https://github.com/viper1991/Home-AgentOps-Blueprint/security/advisories/new) or email harryzhang_1991@163.com

Please include:
- A description of the vulnerability
- Steps to reproduce
- Potential impact

## Security Best Practices for Users

- **API Tokens**: Store your Home Assistant long-lived access token and DeepSeek API key in environment variables or encrypted storage, never in config files committed to git
- **Network Exposure**: The ops server (`ops_server.py`) binds to all interfaces by default — use `--host 127.0.0.1` or a firewall to restrict access
- **UniFi Credentials**: Use a dedicated read-only UniFi user account with minimal privileges
- **Regular Updates**: Keep dependencies up to date with `pip install --upgrade -r requirements.txt`
