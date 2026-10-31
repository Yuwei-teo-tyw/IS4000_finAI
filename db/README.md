# Database seed

`seed.sql` is a full `pg_dump` of the local `fin_ai_agents` database (tables + data, including pgvector embeddings).

Restore into the docker-compose Postgres (drops and recreates the dumped tables):

```bash
docker compose up -d postgres
docker compose exec -T postgres psql -U postgres -d fin_ai_agents < db/seed.sql
```

Regenerate after changing local data:

```bash
docker compose exec -T postgres pg_dump -U postgres --clean --if-exists --no-owner --no-privileges fin_ai_agents > db/seed.sql
```
