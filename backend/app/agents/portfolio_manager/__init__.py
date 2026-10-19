"""
Portfolio Manager agent.

Combines an RM-updated client profile with the Market Researcher's output
(currently an illustrative mock in that agent's own format) and Product
Specialist candidates (mocked) to construct, evaluate and compare the six
SAA templates A-F as concrete portfolio options for review. It never
executes trades or modifies real client holdings.

HTTP: served by the main app under /agents/portfolio-manager
(app/endpoints/portfolio_manager.py). For dev without the full stack:

    cd backend
    python -m app.agents.portfolio_manager serve
"""
