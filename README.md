# Instructions

1. [Install uv0](https://docs.astral.sh/uv/getting-started/installation/)
2. Populate tne environment variables: `COGNITO_USERNAME` and `COGNITO_PASSWORD`

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
playwright install
uv run automated_cookie_eval.py https://www.dev.mdps.mcp.nasa.gov:4443/unity/dev/portal/home 3500 60 30 15 120
```
