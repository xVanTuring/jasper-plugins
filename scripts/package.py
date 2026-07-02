#!/usr/bin/env python3
"""Validate a plugin's manifest.toml and package it into dist/<id>-<version>.jplug.

Monorepo variant of jasper-plugin-template's scripts/package.py: takes the plugin
directory as an argument and picks the wasm from the workspace-level target/.

Mirrors the Jasper host's install-time checks (server/src/plugins/manifest.rs +
install.rs) so problems fail here — in CI or locally — instead of at install time.
Also sanity-checks the built wasm's import section: a plugin may import nothing
except `joplin.host_call`; any `__wbindgen_*` import means a wasm-bindgen
dependency leaked in (typically chrono with default features).

Requires Python 3.11+ (tomllib). No third-party packages.

Usage:
  python3 scripts/package.py s3-storage             # validate + package
  python3 scripts/package.py s3-storage --check     # validate manifest only
"""

import argparse
import hashlib
import re
import shutil
import sys
import tomllib
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Host-side limits (install.rs).
MAX_ZIP_BYTES = 32 * 1024 * 1024
MAX_UNPACKED_BYTES = 128 * 1024 * 1024
MAX_FILES = 2000

# Host-side vocabulary (manifest.rs, spec 0.3).
HOST_API_MAJORS = {"0"}
CAPABILITIES = {"settings", "host:http", "notes:read", "notes:write", "host:ai"}
HOOKS = {"before-save"}
FIELD_TYPES = {"string", "multiline", "secret", "bool", "number", "select"}
THEME_BASES = {"light", "dark"}
COMMAND_TARGETS = {"backend", "builtin"}
TOOLBAR_LOCATIONS = {"note-toolbar", "topbar"}
WIDGET_TYPES = {"chat", "list", "tree", "form", "markdown", "button"}

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def fail(msg: str) -> "NoReturn":  # noqa: F821
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


def rel_path_ok(p: str) -> bool:
    """Package-relative path: forward slashes, no escaping the root (spec §2)."""
    return bool(p) and not p.startswith("/") and "\\" not in p and ":" not in p and all(
        seg not in ("", ".", "..") for seg in p.split("/")
    )


def check_schema(schema: dict, where: str) -> None:
    for key, field in schema.items():
        if not isinstance(field, dict) or "type" not in field:
            fail(f"{where}.{key}: field needs a `type`")
        if field["type"] not in FIELD_TYPES:
            fail(f"{where}.{key}: unknown type {field['type']!r} (allowed: {sorted(FIELD_TYPES)})")
        if field["type"] == "select" and not field.get("options"):
            fail(f"{where}.{key}: select fields need `options`")


def validate(m: dict) -> list[str]:
    """Returns package-relative asset paths referenced by the manifest."""
    for key in ("id", "name", "version", "apiVersion"):
        if not str(m.get(key, "")).strip():
            fail(f"manifest.toml: `{key}` is required")
    if not ID_RE.match(m["id"]):
        fail(f"id {m['id']!r} must match ^[a-z0-9][a-z0-9-]*$")
    major = str(m["apiVersion"]).split(".")[0]
    if major not in HOST_API_MAJORS:
        fail(f"apiVersion {m['apiVersion']!r}: major version unsupported by the host (supported majors: {sorted(HOST_API_MAJORS)})")

    assets: list[str] = []
    backend = m.get("backend")
    if backend:
        wasm = backend.get("wasm", "")
        if not rel_path_ok(wasm):
            fail(f"backend.wasm {wasm!r} is not a valid package-relative path")
        assets.append(wasm)
        for cap in backend.get("capabilities", []):
            if cap not in CAPABILITIES:
                fail(f"unknown capability {cap!r} (allowed: {sorted(CAPABILITIES)})")
        for hook in backend.get("hooks", []):
            if hook not in HOOKS:
                fail(f"unknown hook {hook!r} (allowed: {sorted(HOOKS)})")

    contributes = m.get("contributes", {})
    for theme in contributes.get("theme", []):
        if not ID_RE.match(theme.get("id", "")):
            fail(f"theme id {theme.get('id')!r} invalid")
        if theme.get("base") not in THEME_BASES:
            fail(f"theme {theme['id']}: base must be one of {sorted(THEME_BASES)}")
        if not rel_path_ok(theme.get("css", "")):
            fail(f"theme {theme['id']}: css path invalid")
        assets.append(theme["css"])
    for storage in contributes.get("storage", []):
        if not ID_RE.match(storage.get("id", "")):
            fail(f"storage id {storage.get('id')!r} invalid")
        if not backend:
            fail(f"storage {storage['id']} needs a [backend] section (it runs in wasm)")
        check_schema(storage.get("config_schema", {}), f"storage {storage['id']} config_schema")
    command_ids = set()
    backend_command_ids = set()
    for cmd in contributes.get("command", []):
        if not ID_RE.match(cmd.get("id", "")):
            fail(f"command id {cmd.get('id')!r} invalid")
        if cmd.get("target") not in COMMAND_TARGETS:
            fail(f"command {cmd['id']}: target must be one of {sorted(COMMAND_TARGETS)}")
        if cmd["target"] == "backend" and not backend:
            fail(f"command {cmd['id']}: target=backend needs a [backend] section")
        command_ids.add(cmd["id"])
        if cmd["target"] == "backend":
            backend_command_ids.add(cmd["id"])
    for tb in contributes.get("toolbar", []):
        if tb.get("location") not in TOOLBAR_LOCATIONS:
            fail(f"toolbar: location must be one of {sorted(TOOLBAR_LOCATIONS)}")
        if tb.get("command") not in command_ids:
            fail(f"toolbar references unknown command {tb.get('command')!r}")
    sidebar_ids = set()
    for sb in contributes.get("sidebar", []):
        if not ID_RE.match(sb.get("id", "")):
            fail(f"sidebar id {sb.get('id')!r} invalid")
        if sb["id"] in sidebar_ids:
            fail(f"sidebar id {sb['id']!r} duplicated")
        sidebar_ids.add(sb["id"])
        if not str(sb.get("title", "")).strip():
            fail(f"sidebar {sb['id']}: title is required")
        if sb.get("widget") not in WIDGET_TYPES:
            fail(f"sidebar {sb['id']}: widget must be one of {sorted(WIDGET_TYPES)}")
        if (sb.get("command") or sb.get("view")) and not backend:
            fail(f"sidebar {sb['id']}: command/view needs a [backend] section")
        if sb.get("command") and sb["command"] not in backend_command_ids:
            fail(f"sidebar {sb['id']} references unknown backend command {sb['command']!r}")
        if "view" in sb and not str(sb["view"]).strip():
            fail(f"sidebar {sb['id']}: view must not be empty")
        if sb["widget"] == "chat" and not sb.get("view") and not sb.get("command"):
            fail(f"sidebar {sb['id']}: widget=chat without view requires a command")

    check_schema(m.get("settings", {}).get("schema", {}), "settings.schema")
    return assets


# --- wasm import-section sanity check (spec §6: only `joplin.host_call` allowed) ---

def _leb128(buf: bytes, i: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7


def wasm_imports(path: Path) -> list[str]:
    buf = path.read_bytes()
    if buf[:4] != b"\0asm":
        fail(f"{path} is not a wasm binary")
    i = 8
    while i < len(buf):
        section_id = buf[i]
        size, i = _leb128(buf, i + 1)
        if section_id != 2:  # import section
            i += size
            continue
        count, j = _leb128(buf, i)
        imports = []
        for _ in range(count):
            n, j = _leb128(buf, j)
            module = buf[j : j + n].decode()
            j += n
            n, j = _leb128(buf, j)
            name = buf[j : j + n].decode()
            j += n
            kind = buf[j]
            j += 1
            if kind == 0x00:  # func -> typeidx
                _, j = _leb128(buf, j)
            elif kind == 0x03:  # global -> valtype + mutability
                j += 2
            else:  # table/memory -> (reftype +) limits
                if kind == 0x01:
                    j += 1
                flags = buf[j]
                _, j = _leb128(buf, j + 1)
                if flags & 1:
                    _, j = _leb128(buf, j)
            imports.append(f"{module}.{name}")
        return imports
    return []


def check_wasm(path: Path) -> None:
    bad = [imp for imp in wasm_imports(path) if imp != "joplin.host_call"]
    if bad:
        hint = ""
        if any("wbindgen" in b for b in bad):
            hint = " — a wasm-bindgen dependency leaked in (chrono default features?)"
        fail(f"unexpected wasm imports {bad}{hint}; only joplin.host_call is allowed")


def crate_artifact(plugin_dir: Path) -> Path | None:
    """Workspace target first, then a per-crate target (crate name: dashes -> underscores)."""
    try:
        cargo = tomllib.loads((plugin_dir / "Cargo.toml").read_text())
        name = cargo["package"]["name"].replace("-", "_")
    except Exception:
        return None
    for base in (REPO, plugin_dir):
        p = base / "target" / "wasm32-unknown-unknown" / "release" / f"{name}.wasm"
        if p.exists():
            return p
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("plugin", help="plugin directory (repo-relative), e.g. s3-storage")
    ap.add_argument("--check", action="store_true", help="validate manifest only")
    ap.add_argument("--include", action="append", default=[], help="extra plugin-relative files to ship")
    args = ap.parse_args()

    root = (REPO / args.plugin).resolve()
    manifest_path = root / "manifest.toml"
    if not manifest_path.exists():
        fail(f"{args.plugin}/manifest.toml not found")
    m = tomllib.loads(manifest_path.read_text())
    if m["id"] != Path(args.plugin).name:
        warn(f"manifest id {m['id']!r} != directory name {Path(args.plugin).name!r}")
    assets = validate(m)
    print(f"manifest ok: {m['id']} {m['version']} (apiVersion {m['apiVersion']})")
    if args.check:
        return

    # Refresh the wasm from the cargo artifact when it exists.
    if m.get("backend"):
        artifact = crate_artifact(root)
        wasm_dest = root / m["backend"]["wasm"]
        if artifact:
            wasm_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(artifact, wasm_dest)
        if not wasm_dest.exists():
            fail(f"{wasm_dest.name} missing — run: cargo build --release --target wasm32-unknown-unknown -p {m['id']}")
        check_wasm(wasm_dest)

    try:
        cargo_ver = tomllib.loads((root / "Cargo.toml").read_text())["package"]["version"]
        if cargo_ver != m["version"]:
            warn(f"Cargo.toml version {cargo_ver} != manifest version {m['version']} (manifest wins)")
    except Exception:
        pass

    files = ["manifest.toml", *assets, *args.include]
    seen = set()
    files = [f for f in files if not (f in seen or seen.add(f))]
    total = 0
    for f in files:
        p = root / f
        if not p.exists():
            fail(f"packaged file missing: {f}")
        total += p.stat().st_size
    if len(files) > MAX_FILES:
        fail(f"too many files ({len(files)} > {MAX_FILES})")
    if total > MAX_UNPACKED_BYTES:
        fail(f"unpacked size {total} exceeds host limit {MAX_UNPACKED_BYTES}")

    dist = REPO / "dist"
    dist.mkdir(exist_ok=True)
    out = dist / f"{m['id']}-{m['version']}.jplug"
    # Deterministic zip (fixed timestamps, sorted entries) -> reproducible sha256.
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(files):
            info = zipfile.ZipInfo(f, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, (root / f).read_bytes())
    size = out.stat().st_size
    if size > MAX_ZIP_BYTES:
        fail(f"package size {size} exceeds host limit {MAX_ZIP_BYTES}")
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    (dist / f"{out.name}.sha256").write_text(f"{digest}  {out.name}\n")
    print(f"packaged: {out.relative_to(REPO)} ({size} bytes, {len(files)} files)")
    print(f"sha256: {digest}")


if __name__ == "__main__":
    main()
