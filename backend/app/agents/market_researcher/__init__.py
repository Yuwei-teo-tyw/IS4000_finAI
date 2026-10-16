"""
Market researcher agent - fetches current macro, rates, market and news
data, detects notable events, classifies the economic cycle phase, and
writes a structured, cited JSON file for a main agent to synthesize later.

Primary interface is HTTP (app/endpoints/market_researcher.py); in-process
callers use `run_market_research()`.
"""
