# Container releases

IncidentLab publishes four multi-architecture images to GitHub Container Registry:

| Package | Purpose |
| --- | --- |
| `ghcr.io/rajat-blr/incidentlab-api` | API, database migration, and Temporal worker |
| `ghcr.io/rajat-blr/incidentlab-frontend` | Live API-backed review console |
| `ghcr.io/rajat-blr/incidentlab-verifier` | Trusted verification agent |
| `ghcr.io/rajat-blr/incidentlab-sandbox` | Network-disabled candidate check environment |

Images are built for `linux/amd64` and `linux/arm64`. Each publication includes
OCI source metadata, a software bill of materials, and build provenance.

## Run a published version

Clone the repository so IncidentLab can pin and inspect its Git history:

```sh
git clone https://github.com/rajat-blr/incidentlab.git
cd incidentlab
cp .env.ghcr.example .env.ghcr
```

Set `OPENAI_API_KEY` in `.env.ghcr`, then start a published release:

```sh
docker compose --env-file .env.ghcr -f compose.ghcr.yaml up -d --wait
```

`INCIDENTLAB_VERSION` selects one version across all IncidentLab images. Prefer
an immutable release such as `0.3.0`; `latest` follows the most recent release.
The verifier pulls the matching sandbox image through the trusted Docker socket
instead of rebuilding it locally.

To stop the stack without removing its database and workflow volumes:

```sh
docker compose --env-file .env.ghcr -f compose.ghcr.yaml down
```

## Publish a release

The `Publish container release` workflow runs for semantic version tags:

```sh
git tag -a v0.3.0 -m "IncidentLab v0.3.0"
git push origin v0.3.0
```

A successful workflow publishes these tags for every component:

- `0.3.0`
- `0.3`
- `latest`
- `sha-<commit>`

It then creates the matching GitHub Release with generated notes. A manual
workflow run publishes `edge` and `sha-<commit>` images without creating a
versioned GitHub Release.

After the first publication, confirm that all four packages are public in the
repository package settings. No registry credential is required to pull public
packages; the publishing workflow authenticates with its scoped `GITHUB_TOKEN`.

## Upgrade

Update `INCIDENTLAB_VERSION` in `.env.ghcr`, then run:

```sh
docker compose --env-file .env.ghcr -f compose.ghcr.yaml pull
docker compose --env-file .env.ghcr -f compose.ghcr.yaml up -d --wait
```

Database migrations run as a one-shot service before the API and worker start.

## Trust boundary

The verifier is the only IncidentLab component that receives the Docker socket.
It uses that authority to start the constrained sandbox image with no network,
a read-only filesystem, a non-root user, dropped capabilities, and resource
limits. The API, workflow worker, and frontend do not receive Docker access.
