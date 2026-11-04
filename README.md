# Dependency Steward demo · Northstar

An operator-owned public React/TypeScript fixture for a dependency-upgrade engineering assessment. It is not a production product.

The invitation form currently uses Zod 3.24.2 and its `ZodError.errors` interface. A Zod 4 upgrade exercises a real compatibility change: the application needs to use `issues`. Four fixed behavioral tests protect the validation contract. The steward must adapt the source without editing tests.

## Run

Node 24.6.0, npm 11.8.0. `npm ci --ignore-scripts`, then `npm run --ignore-scripts test:ci`, `npm run --ignore-scripts typecheck`, `npm run --ignore-scripts build`.

The reviewed execution workflow lives in `.github/workflows/steward-execute.yml`; its stdlib helper is `.steward/execute.py`. Execution receives only a read-only workflow token and bounded plan inputs. No backend secrets are configured in this repository.
