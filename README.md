# Atlas

Shizuha Atlas is its own application. It stores organization maps and publishes the system catalog. `https://shizuha.com/atlas/` is the library of every map the signed-in caller can open. Opening a map is a separate screen, and Maps returns to that library.

Wiki can link to a map and can embed a document it already contains. Wiki does not own this API, this catalog, or this screen.

Origin CI (`.forgejo/workflows/deploy.yml`) builds the multi-arch image and rolls `shizuha-atlas` in the `shizuha` namespace. The edge should proxy `https://shizuha.com/atlas/` here only after that deployment is ready.

Maps live in this service's volume. Membership comes from the Shizuha ID token. A caller sees the maps of every organization they belong to, and nothing from the others.

## Deployment and development

For a complete platform installation, use the [platform deployment repository](https://github.com/shizuha-labs/deploy).
Atlas is a separate FastAPI service with its own map database and React frontend.
Configure Shizuha ID verification and persistent `ATLAS_DB` storage for your
installation. `ATLAS_CATALOG` selects the catalog JSON; only distribute a catalog
whose diagrams and topology are intended for your users.

Python dependencies are listed in `requirements.txt` and test dependencies in
`requirements-dev.txt`. The frontend uses `frontend/package.json` and its lockfile.
The reusable diagram engine is the separately versioned `@shizuha/atlas` package;
this repository is the hosted application, not a Confluence marketplace app.

## License

Original code is available under the [MIT License](LICENSE). Third-party
components retain their respective licenses and notices, including dependencies
installed by Python and npm and the separately distributed Atlas package.
