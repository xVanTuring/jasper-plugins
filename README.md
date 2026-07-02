# jasper-plugins

Official plugins for [Jasper](https://github.com/xVanTuring/jasper), the
lightweight Joplin-compatible client. Each plugin lives in its own directory
and is released as a `.jplug` package (zip of `manifest.toml` + `plugin.wasm`)
on this repo's [Releases](https://github.com/xVanTuring/jasper-plugins/releases) page.

| Plugin | What it does | Capabilities |
|---|---|---|
| [`s3-storage`](s3-storage) | S3-compatible object storage as a sync source (AWS S3 / MinIO / Cloudflare R2, path-style, pure-Rust SigV4) | `host:http` |
| [`ai-polish`](ai-polish) | One-click AI polish button in the source editor (Anthropic Messages or OpenAI Chat Completions format) | `settings`, `host:http` |

## Installing

Download the `.jplug` from a release, then in Jasper: top bar → plug icon →
Install → pick the file → enable (you'll be asked to consent to the declared
capabilities). A browsable in-app market backed by
[jasper-plugin-registry](https://github.com/xVanTuring/jasper-plugin-registry)
is on the roadmap.

## Development

Cargo workspace; plugins depend on
[`jasper-plugin-sdk`](https://crates.io/crates/jasper-plugin-sdk) from crates.io.

```sh
cargo test --workspace
cargo build --release --target wasm32-unknown-unknown --workspace
python3 scripts/package.py s3-storage        # -> dist/s3-storage-<version>.jplug
```

Tests use the SDK's `native-host` feature (dev-dependency), so integration
tests run without the wasm sandbox — `ai-polish` exercises its full
settings→request→parse flow against a local stub, and `s3-storage` does a live
round-trip against MinIO when `JASPER_TEST_S3_URL` is set (skipped otherwise):

```sh
docker compose -f docker-compose.dev.yml up -d
JASPER_TEST_S3_URL=http://127.0.0.1:9000 cargo test --workspace
docker compose -f docker-compose.dev.yml down -v
```

`scripts/package.py` mirrors the host's install-time validation and checks the
wasm import section (only `joplin.host_call` is allowed). Zips are built
deterministically, so the sha256 is reproducible from source.

Writing your own plugin? Start from
[jasper-plugin-template](https://github.com/xVanTuring/jasper-plugin-template).

## Releasing (maintainers)

Bump `version` in `<plugin>/manifest.toml` (+ `Cargo.toml`), then:

```sh
git tag s3-storage-v0.2.0 && git push origin s3-storage-v0.2.0
```

CI verifies the tag against the manifest, tests, builds, and attaches the
`.jplug` + `.sha256` to a GitHub Release. Then update the entry in
[jasper-plugin-registry](https://github.com/xVanTuring/jasper-plugin-registry).

Note: the main Jasper repo keeps copies of these plugins under
`plugins-examples/` as **host-test fixtures** (they exercise the plugin host's
command/storage integration in server CI, built against the in-repo SDK). This
repo is the source of truth for what users install; sync fixture copies
opportunistically when behavior changes matter to host tests.

## License

MIT OR Apache-2.0, at your option.
