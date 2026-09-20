# AI features in Azure databases

Live demo material from the session **"Building the Frontier for AI with Databases"**,
Oslo, 22 September 2026.

One synthetic dataset of a thousand support tickets, held three ways, with every
query run live against Azure:

- **Azure Cosmos DB for NoSQL** — full text, vector, filtered vector, and hybrid
  search fused with `RRF` inside a single `ORDER BY RANK` clause
- **Azure Database for PostgreSQL** — `pgvector` with DiskANN, plus the
  `azure_ai` extension calling a Foundry model from inside SQL
- **Apache AGE** — a property graph in that same PostgreSQL server, including an
  edge derived from the embeddings rather than from a foreign key

The argument the demo makes, in one line:

> Cosmos DB is where your application does AI to your data.
> PostgreSQL is where your data does AI to itself.

## What it shows

**Cosmos DB.** Keyword search finds an exact fault code perfectly and a
paraphrased symptom not at all. Vector search does the opposite. Hybrid fuses
both rankings in the database. The last panel puts the same model, with the same
prompt, behind two different retrievals: one finds nothing and truthfully reports
that there is no record, the other names eight tickets and the fixes that worked.
The model was never the variable. The search was.

**PostgreSQL.** The question goes into the query as plain English, and the
database calls the embedding model itself using its own managed identity. A
similarity search is an ordinary result set, so ordinary SQL can `GROUP BY` over
it. One statement does retrieval and generation together, with no application
tier in the loop.

**The graph.** Walking the fault code is a `GROUP BY` wearing a costume, and the
demo says so. The `SIMILAR_TO` edge is not: it is computed from the embeddings,
so it reaches assets that share no fault code, no component and no domain with
the question. A checkout terminal that freezes mid sale and a ship's bridge
display that freezes on watch are the same sentence written by different people.

## Running it

You need the Azure CLI, Terraform and Python 3.12, and a subscription you can
create resources in.

```bash
git clone https://github.com/Hanifff/ai-features-in-azure-databases.git
cd ai-features-in-azure-databases

az login
./scripts/setup.sh
```

That script reads your current `az` context, writes
`infra/terraform/terraform.tfvars` from it, applies the Terraform, writes `.env`
from the outputs, creates the virtual environment, installs the dependencies,
loads all three stores, runs the preflight check, and then starts the demo on
<http://127.0.0.1:5000>. Nothing is prompted for and nothing is hard coded.

```bash
./scripts/setup.sh --location westeurope     # somewhere else
./scripts/setup.sh --prefix contoso          # different resource names
./scripts/setup.sh --open-firewall           # presenting from an unknown network
./scripts/setup.sh --infra-only              # stop after terraform
./scripts/setup.sh --no-run                  # set everything up, do not start the app
```

Afterwards:

```bash
python -m app.app            # http://127.0.0.1:5000
python -m tools.smoke        # exercise every panel from the command line
python -m tools.preflight    # check the environment is still demo-ready
```

`src/ai-db-demos.ipynb` runs the same functions the web pages call, with outputs
committed, so there is something true to show even with no network at all.

### Cost

The PostgreSQL flexible server dominates the bill and is the one thing worth
stopping between sessions:

```bash
az postgres flexible-server stop -g <resource-group> -n <server-name>
```

Everything else is consumption priced. To remove all of it:

```bash
terraform -chdir=infra/terraform destroy
```

## Layout

| Path | What it is |
| --- | --- |
| `app/` | Flask app, four pages, every query executed live |
| `app/cosmos_store.py` | Every Cosmos query in the talk |
| `app/postgres_store.py` | Every PostgreSQL query, including generation in SQL |
| `app/graph_store.py` | The Cypher, and the layout the diagram is drawn from |
| `app/grounding.py` | The two-retrieval comparison, with citations verified |
| `tools/generate_tickets.py` | Dataset generator, fixed seed |
| `tools/load_*.py` | Loaders for Cosmos, PostgreSQL and the graph |
| `tools/preflight.py` | Checks that the demo will actually work |
| `tools/smoke.py` | Every endpoint against every dropdown option |
| `data/tickets.csv` | The dataset |
| `src/ai-db-demos.ipynb` | Notebook fallback with committed outputs |
| `infra/terraform/` | The Azure resources, and only these |

## The dataset

A thousand synthetic operations tickets across maritime, energy, payments and
retail. No real customer data and no personal data. Generated deterministically
from a fixed seed, so the committed CSV, the loaded databases and the notebook
outputs cannot drift apart.

The wording is the point. The same fault is described as shuddering, juddering,
trembling and knocking by different people, and the fault code is deliberately
excluded from the embedded text, so that keyword search and vector search each
keep a job the other cannot do.

## Authentication

There is no key, password or connection string anywhere in this repository, and
the setup script creates none.

- PostgreSQL has password authentication **disabled** and accepts a short-lived
  Entra token as the password
- Cosmos DB has local authentication **disabled**, so account keys do not exist
- The Foundry account has local authentication **disabled**
- PostgreSQL reaches the embedding and chat models as its own **system-assigned
  managed identity**, which is what makes `azure_openai.create_embeddings()` and
  `azure_ai.generate()` work from inside SQL without a key

Data-plane roles are assigned separately from control-plane roles. That is
usually why a subscription Owner still gets `403` from the Cosmos SDK.

## Read this before reusing anything

This is **demonstration code written for a stage**, not a reference
architecture. Two things are tuned for a live session and are wrong for
production:

- **Public endpoints.** A real deployment would use private endpoints and no
  public network access at all.
- **The firewall can be opened wide.** `--open-firewall` exists because a venue
  network address cannot be known in advance. It is defensible only because
  authentication is Entra-only with no keys, the data is synthetic and the
  environment is disposable. The default is your own address only.

What is worth copying: Entra-only authentication throughout, the database
calling the model with its own managed identity, data-plane roles kept separate
from control-plane roles, and retrieval quality treated as the thing that
decides what an AI answer is allowed to know.

## Licence

BSD 2-Clause. See [LICENSE](LICENSE).
