# AI features in Azure databases

Live demo material from the session **"Building the Frontier for AI with Databases"**,
Oslo, 22 September 2026.

The same dataset, held three ways, with every query run live:

- **Azure Cosmos DB for NoSQL** — vector, full text and hybrid search with `RRF`
- **Azure Database for PostgreSQL** — `pgvector`, DiskANN, and the `azure_ai`
  extension calling a model from inside SQL
- **Apache AGE** — a graph in that same PostgreSQL server

The argument the demo makes, in one line:

> Cosmos is where your application does AI to your data.
> PostgreSQL is where your data does AI to itself.

## Status

Scaffolding only. The demo application, notebook, loaders and dataset are added
here deliberately, a piece at a time, once each one is finished. Nothing is
copied over wholesale.

| Coming | What it is |
| --- | --- |
| `app/` | Flask app, four pages, every query live |
| `tools/` | Dataset generator, loaders, preflight check |
| `data/` | The synthetic ticket dataset |
| `src/` | Notebook fallback with committed outputs |
| `infra/` | Terraform for the Azure resources |

## The dataset

Synthetic operations tickets across maritime, energy, payments and retail. No
real customer data, no personal data. Generated deterministically from a fixed
seed so the committed files and the notebook outputs cannot drift apart.

## Read this before reusing anything

This is **demonstration code written for a stage**, not a reference
architecture. Two things in particular are tuned for a live session and are
wrong for production:

- **Networking is open.** The demo runs from several networks that cannot be
  predicted, so both databases accept connections from anywhere. It is defensible
  only because authentication is Entra-only with no keys anywhere, and because the
  data is synthetic and the environment is disposable.
- **Everything is public-endpoint.** A real deployment would use private endpoints
  and no public network access at all.

What *is* worth copying: Entra-only authentication, no API keys, the database
calling the model with its own managed identity, and data-plane role assignments
kept separate from control-plane roles.

## Licence

BSD 2-Clause. See [LICENSE](LICENSE).
