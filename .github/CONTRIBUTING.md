# Contributing to HAB (Home-AgentOps-Blueprint)

Thank you for your interest in contributing! This project is a home information dashboard combining Home Assistant, UniFi, and LLM-powered content curation on an e-paper display.

## Project Overview

Before contributing, please read the [README.md](../README.md) to understand the architecture and design philosophy.

## How to Contribute

### 1. Issues

- **Bug reports**: Include hardware model (Raspberry Pi version, e-paper model), Python version, and steps to reproduce
- **Feature requests**: Describe the feature, why it's useful, and any implementation ideas you have
- **Configuration help**: Include sanitized versions of your config files (redact tokens and passwords)

### 2. Pull Requests

1. Fork the repository
2. Create a feature branch from `main`
3. Make your changes
4. Test on your hardware setup if possible
5. Submit a PR describing what you changed and why

### 3. Code Style

- **Python**: Follow PEP 8. Use type hints for function signatures
- **Naming**: Use `snake_case` for functions and variables, `PascalCase` for classes
- **Logging**: Use `logging.getLogger(__name__)` in each module

### 4. Adding a New LLM Provider

1. Create `lib/llm/<provider>.py` implementing the `LLMProvider` ABC from `lib/llm/provider.py`
2. Register it in the refresh script's initialization
3. Update `config.yaml.example` to document the new option

### 5. Adding a New Tool

1. Create `lib/tools/<tool_name>.py` implementing the `Tool` ABC from `lib/tools/base.py`
2. Register the tool in `refresh_heavyweight.py`'s `ToolRegistry()`
3. Add the tool definition to the snapshot's tool list

### 6. Testing

Manual testing on actual hardware is currently the primary testing method. When the scope of a change permits it, include basic unit tests.

## Development Setup

```bash
# Clone your fork
git clone https://github.com/viper1991/Home-AgentOps-Blueprint.git
cd Home-AgentOps-Blueprint

# Install dependencies
pip install -r requirements.txt

# Copy and configure
cp config/config.yaml.example config/config.yaml
# Edit config/config.yaml with your HA and UniFi details

# Run lightweight refresh to test without hardware
# (it will error on DisplayClient but you can validate data fetching)
python3 refresh_lightweight.py
```

## Design Principles

- **One process → one responsibility**: Only `display_server.py` touches GPIO
- **LLM as agent, not orchestrator**: The LLM selects content but doesn't control infrastructure
- **No runtime API discovery**: Entity catalogs are maintained locally for predictability
- **Minimal caching**: Pure real-time data fetches, only working memory for topic dedup

## Code of Conduct

Be respectful and constructive. This is a hobby project — keep it fun.
