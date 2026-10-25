# Contex Games

Games built on [Contex](https://github.com/cahoots-org/contex), the MCP-native context bus. Each game talks to Contex only over its public MCP endpoint, so any Contex server will do.

| Game | What it is |
|---|---|
| [Whispers](whispers/README.md) | A gossip game: you whisper to villagers and win by spreading rumors until the village matches your goals. Live at [whispers.usecontex.com](https://whispers.usecontex.com). |
| [Sleuth](sleuth/README.md) | A small-town deduction game on the Whispers engine, in progress: petty crimes happen live, and you work out who did it. |

## Running a game

Start a Contex server (see the [Contex README](https://github.com/cahoots-org/contex#readme)), then from this repo's root:

```bash
pip install -r whispers/requirements.txt
python -m whispers --web
```

## Tests

```bash
pip install -r requirements-dev.txt
ruff check .
pytest whispers
WHISPERS_CONTEX_URL=http://localhost:8001/mcp pytest whispers/tests/test_contex_integration.py
```

The last run needs a live Contex.
