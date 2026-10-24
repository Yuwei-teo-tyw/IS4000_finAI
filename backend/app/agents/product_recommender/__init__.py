"""
Product Recommender agent (Product Specialist capability).

Owns the single product shelf and the curated CIO house view. For a client,
it runs a hard suitability gate, then ranks the eligible products by fit
with the client's objective and the house view. Fees are attached to every
product for display only and are never part of the ranking.

The Portfolio Agent reads the same shelf in-process
(portfolio_agent/upstream/product_specialist.py), so the PS screen and the
Portfolio Agent work from one product list.

HTTP: served by the main app under /agents/product-recommender
(app/endpoints/product_recommender.py). Proposal-only: nothing here
approves a product list (the PS does, at gate G3) or executes trades.
"""
