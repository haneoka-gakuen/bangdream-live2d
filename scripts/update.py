import json
from pathlib import Path
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/134.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
REQUEST_TIMEOUT = 30
DATA_ROOT = Path("data")
BESTDORI_BASE_URL = "https://bestdori.com/"
REGIONS = ("jp", "cn")
DIRECTORY_ASSET_TARGETS = (
    {
        "region": "jp",
        "root_path": "stamp",
        "discovery_mode": "tree_leaves",
        "save_layout": "split_region",
        "dedupe_mode": "full",
        "info_mode": "listing",
        "prefilter": "none",
    },
    {
        "region": "cn",
        "root_path": "stamp",
        "discovery_mode": "tree_leaves",
        "save_layout": "split_region",
        "dedupe_mode": "full",
        "info_mode": "listing",
        "prefilter": "none",
    },
    {
        "region": "jp",
        "root_path": "changedstamp",
        "discovery_mode": "tree_leaves",
        "save_layout": "split_region",
        "dedupe_mode": "full",
        "info_mode": "listing",
        "prefilter": "none",
    },
    {
        "region": "cn",
        "root_path": "changedstamp",
        "discovery_mode": "tree_leaves",
        "save_layout": "split_region",
        "dedupe_mode": "full",
        "info_mode": "listing",
        "prefilter": "none",
    },
    {
        "region": "jp",
        "root_path": "sdchara",
        "discovery_mode": "tree_leaves",
        "save_layout": "shared",
        "dedupe_mode": "full",
        "info_mode": "listing",
        "prefilter": "none",
    },
    {
        "region": "cn",
        "root_path": "sdchara",
        "discovery_mode": "tree_leaves",
        "save_layout": "shared",
        "dedupe_mode": "full",
        "info_mode": "listing",
        "prefilter": "none",
    },
    {
        "region": "jp",
        "root_path": "live2d",
        "discovery_mode": "count_map_branch",
        "discovery_root_path": "live2d/chara",
        "save_layout": "shared",
        "dedupe_mode": "save_dir",
        "info_mode": "count_map",
        "info_root_path": "live2d/chara",
        "prefilter": "count_map_prefix_group",
    },
    {
        "region": "cn",
        "root_path": "live2d",
        "discovery_mode": "count_map_branch",
        "discovery_root_path": "live2d/chara",
        "save_layout": "shared",
        "dedupe_mode": "save_dir",
        "info_mode": "count_map",
        "info_root_path": "live2d/chara",
        "prefilter": "count_map_prefix_group",
    },
)
REFERENCE_FILES = {
    "bands.all.1.json": "api/bands/all.1.json",
    "characters.all.5.json": "api/characters/all.5.json",
    "cards.all.5.json": "api/cards/all.5.json",
    "costumes.all.5.json": "api/costumes/all.5.json",
}


def bestdori_url(path):
    return urljoin(BESTDORI_BASE_URL, path)


def explorer_assets_url(region, path=""):
    return bestdori_url(f"api/explorer/{region}/assets/{path}")


def assets_url(region, path=""):
    return bestdori_url(f"assets/{region}/{path}")


def build_session():
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def collect_local_file_counts(root_dir):
    counts = {}
    if not root_dir.exists():
        root_dir.mkdir(parents=True, exist_ok=True)
        return counts

    for folder in root_dir.iterdir():
        if folder.is_dir():
            counts[folder.name] = sum(1 for path in folder.rglob("*") if path.is_file())
    return counts

class BestdoriClient:
    def __init__(self):
        self.session = build_session()
        self.asset_tree_cache = {}

    def fetch_json(self, url):
        response = self.session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()

    def fetch_asset_tree(self, region):
        if region not in self.asset_tree_cache:
            self.asset_tree_cache[region] = self.fetch_json(
                explorer_assets_url(region, "_info.json")
            )
        return self.asset_tree_cache[region]

    def fetch_indexed_directory_files(self, index_url, label):
        remote_files = self.fetch_json(index_url)
        if not isinstance(remote_files, list):
            raise ValueError(f"Unexpected asset index for {label}")
        return remote_files

    def download_file(self, file_url, save_path):
        with self.session.get(file_url, stream=True, timeout=REQUEST_TIMEOUT) as response:
            response.raise_for_status()

            chunk_iter = response.iter_content(chunk_size=1024 * 1024)
            first_chunk = next(chunk_iter, b"")
            preview = first_chunk[:1024].lower()
            content_type = response.headers.get("Content-Type", "").lower()

            if (
                "text/html" in content_type
                or b"<!doctype" in preview
                or preview.startswith(b"<html")
            ):
                print(f"Skipped HTML response: {file_url}")
                return False

            with save_path.open("wb") as file_obj:
                if first_chunk:
                    file_obj.write(first_chunk)
                for chunk in chunk_iter:
                    if chunk:
                        file_obj.write(chunk)
        return True

    def download_indexed_directory(self, remote_files, base_url, save_dir, label):
        save_dir.mkdir(parents=True, exist_ok=True)
        existing_files = {
            path.relative_to(save_dir).as_posix()
            for path in save_dir.rglob("*")
            if path.is_file()
        }
        missing_files = [
            file_path for file_path in remote_files if file_path not in existing_files
        ]

        if not missing_files:
            print(f"No missing files for {label}")
            return True

        print(f"{label}: {len(missing_files)} files to download")
        all_succeeded = True

        for file_path in missing_files:
            file_url = urljoin(base_url, file_path)
            save_path = save_dir / file_path
            save_path.parent.mkdir(parents=True, exist_ok=True)

            if self.download_file(file_url, save_path):
                print(f"Downloaded: {file_path}")
            else:
                all_succeeded = False

        return all_succeeded


def write_json_file(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file_obj:
        json.dump(data, file_obj, ensure_ascii=False, separators=(",", ":"))
    print(f"Updated `{path.as_posix()}`")


def update_reference_files(client):
    for file_name, url in REFERENCE_FILES.items():
        data = client.fetch_json(bestdori_url(url))
        write_json_file(DATA_ROOT / file_name, data)


def add_indexed_asset_info(info_by_group, target, remote_files):
    parts = target["index_path"].split("/", 1)
    group_name = parts[0]
    asset_id = parts[1] if len(parts) == 2 else "_root"
    group_info = info_by_group.setdefault(group_name, {})

    if target["save_layout"] == "shared":
        entry = group_info.setdefault(
            asset_id,
            {
                "assetPath": target["asset_path"],
                "saveDir": target["save_dir"].as_posix(),
                "fileCount": 0,
                "files": [],
            },
        )
        merged_files = sorted(set(entry["files"]).union(remote_files))
        entry["fileCount"] = len(merged_files)
        entry["files"] = merged_files
        return

    region_info = group_info.setdefault(target["region"], {})
    region_info[asset_id] = {
        "assetPath": target["asset_path"],
        "saveDir": target["save_dir"].as_posix(),
        "fileCount": len(remote_files),
        "files": remote_files,
    }


def get_asset_tree_node(tree, path):
    node = tree
    for part in path.split("/"):
        if not part:
            continue
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def iter_leaf_assets(node, prefix):
    if isinstance(node, dict):
        for name, child in node.items():
            child_prefix = f"{prefix}/{name}" if prefix else name
            yield from iter_leaf_assets(child, child_prefix)
        return

    yield prefix, node


def asset_path_for_leaf(leaf_path):
    return f"{leaf_path}_rip"


def save_dir_for_leaf(region, leaf_path, save_layout):
    asset_path = asset_path_for_leaf(leaf_path)

    if save_layout == "shared":
        return Path(asset_path)

    if save_layout == "split_region":
        if region == "jp":
            return Path(asset_path)

        group_name, rest = leaf_path.split("/", 1)
        return Path(group_name) / region / f"{rest}_rip"

    raise ValueError(f"Unknown save layout: {save_layout}")


def expand_directory_asset_target(client, target):
    region = target["region"]
    root_path = target["root_path"]
    discovery_mode = target["discovery_mode"]
    save_layout = target["save_layout"]
    dedupe_mode = target["dedupe_mode"]
    info_mode = target["info_mode"]
    prefilter = target["prefilter"]
    tree = client.fetch_asset_tree(region)
    expanded_targets = []

    if discovery_mode == "tree_leaves":
        node = get_asset_tree_node(tree, root_path)
        if node is None:
            raise ValueError(f"Directory asset target not found: {region}/{root_path}")
        leaf_entries = iter_leaf_assets(node, root_path)
    elif discovery_mode == "count_map_branch":
        discovery_root_path = target["discovery_root_path"]
        node = get_asset_tree_node(tree, discovery_root_path)
        if not isinstance(node, dict):
            raise ValueError(
                f"Count-map discovery target not found: {region}/{discovery_root_path}"
            )
        leaf_entries = (
            (f"{discovery_root_path}/{leaf_id}", expected_count)
            for leaf_id, expected_count in node.items()
        )
    else:
        raise ValueError(f"Unknown discovery mode: {discovery_mode}")

    for leaf_path, expected_count in leaf_entries:
        expanded_targets.append(
            {
                "region": region,
                "root_path": root_path,
                "index_path": leaf_path,
                "leaf_path": leaf_path,
                "asset_path": asset_path_for_leaf(leaf_path),
                "save_dir": save_dir_for_leaf(region, leaf_path, save_layout),
                "expected_count": expected_count,
                "save_layout": save_layout,
                "dedupe_mode": dedupe_mode,
                "info_mode": info_mode,
                "info_root_path": target.get("info_root_path"),
                "prefilter": prefilter,
            }
        )

    return expanded_targets


def build_asset_targets(client):
    targets = []
    for target in DIRECTORY_ASSET_TARGETS:
        targets.extend(expand_directory_asset_target(client, target))

    deduped_targets = []
    seen = set()
    for target in targets:
        if target["dedupe_mode"] == "save_dir":
            key = ("save_dir", target["save_dir"].as_posix())
        else:
            key = (
                target["region"],
                target["index_path"],
                target["asset_path"],
                target["save_dir"].as_posix(),
            )
        if key in seen:
            continue
        seen.add(key)
        deduped_targets.append(target)

    return deduped_targets


def write_indexed_asset_info_files(info_by_group):
    for group_name, group_info in info_by_group.items():
        write_json_file(Path(group_name) / "_info.json", group_info)


def relative_leaf_id(root_path, leaf_path):
    if leaf_path == root_path:
        return "_root"
    return leaf_path[len(root_path) + 1 :]


def write_count_map_info_files(asset_targets):
    info_outputs = {}

    for target in asset_targets:
        if target["info_mode"] != "count_map":
            continue

        info_root_path = target.get("info_root_path", target["root_path"])
        info_key = relative_leaf_id(info_root_path, target["leaf_path"])
        info_path = Path(target["root_path"]) / "_info.json"
        output = info_outputs.setdefault(info_path.as_posix(), {"path": info_path, "data": {}})
        output["data"][info_key] = max(
            output["data"].get(info_key, 0),
            target["expected_count"],
        )

    for output in info_outputs.values():
        write_json_file(output["path"], output["data"])


def local_target_file_count(target, local_counts_cache):
    parent_dir = target["save_dir"].parent
    parent_key = parent_dir.as_posix()
    if parent_key not in local_counts_cache:
        local_counts_cache[parent_key] = collect_local_file_counts(parent_dir)

    return local_counts_cache[parent_key].get(target["save_dir"].name, 0)


def target_info_key(target):
    info_root_path = target.get("info_root_path", target["root_path"])
    return relative_leaf_id(info_root_path, target["leaf_path"])


def target_group_prefix(target):
    info_key = target_info_key(target)
    if info_key == "_root":
        return info_key
    return info_key.split("_", 1)[0]


def target_needs_sync(target, local_counts_cache, save_dir_occurrences):
    if target["prefilter"] == "none":
        return True

    if target["prefilter"] not in ("count_map", "count_map_prefix_group"):
        raise ValueError(f"Unknown prefilter: {target['prefilter']}")

    save_dir_key = target["save_dir"].as_posix()
    if save_dir_occurrences[save_dir_key] > 1:
        return True

    local_count = local_target_file_count(target, local_counts_cache)
    return local_count < target["expected_count"]


def select_asset_targets_to_update(asset_targets):
    selected_targets = []
    local_counts_cache = {}
    save_dir_occurrences = {}
    selected_group_prefixes = set()

    for target in asset_targets:
        save_dir_key = target["save_dir"].as_posix()
        save_dir_occurrences[save_dir_key] = save_dir_occurrences.get(save_dir_key, 0) + 1

    for target in asset_targets:
        if target["prefilter"] == "none":
            selected_targets.append(target)
            continue

        if target["prefilter"] == "count_map":
            if target_needs_sync(target, local_counts_cache, save_dir_occurrences):
                selected_targets.append(target)
            continue

        if target["prefilter"] == "count_map_prefix_group":
            if target_needs_sync(target, local_counts_cache, save_dir_occurrences):
                selected_group_prefixes.add(
                    (target["root_path"], target_group_prefix(target))
                )
            continue

        raise ValueError(f"Unknown prefilter: {target['prefilter']}")

    for target in asset_targets:
        if target["prefilter"] != "count_map_prefix_group":
            continue

        group_key = (target["root_path"], target_group_prefix(target))
        if group_key in selected_group_prefixes:
            selected_targets.append(target)

    return selected_targets


def update_asset_files(client):
    all_targets = build_asset_targets(client)
    write_count_map_info_files(all_targets)

    targets_to_update = select_asset_targets_to_update(all_targets)
    if not targets_to_update:
        print("All asset targets are already up to date.")
        return

    failed_targets = []
    info_by_group = {}

    print(f"Found {len(targets_to_update)} asset targets that need syncing:")
    for target in targets_to_update:
        print(f"{target['region']}/{target['asset_path']}")

    for target in targets_to_update:
        region = target["region"]
        index_path = target["index_path"]
        asset_path = target["asset_path"]
        save_dir = target["save_dir"]
        label = f"{region}/{asset_path}"
        print(f"\n[*] Begin to download indexed assets: {label}")
        try:
            remote_files = client.fetch_indexed_directory_files(
                explorer_assets_url(region, f"{index_path}.json"),
                label,
            )
            if target["info_mode"] == "listing":
                add_indexed_asset_info(info_by_group, target, remote_files)
            if client.download_indexed_directory(
                remote_files=remote_files,
                base_url=assets_url(region, f"{asset_path}/"),
                save_dir=save_dir,
                label=label,
            ):
                print(f"[*] Success: {label}")
            else:
                failed_targets.append(label)
                print(f"[*] Failed: {label}")
        except Exception as exc:
            failed_targets.append(label)
            print(f"[*] Failed: {label} ({exc})")

    write_indexed_asset_info_files(info_by_group)

    if failed_targets:
        print("\nFailed indexed asset directories:")
        for label in failed_targets:
            print(label)


def main():
    client = BestdoriClient()

    try:
        update_reference_files(client)
        update_asset_files(client)

    except requests.exceptions.RequestException as exc:
        print(f"Failed to request: {exc}")
    except json.JSONDecodeError as exc:
        print(f"Failed to parse: {exc}")
    except Exception as exc:
        print(f"Error: {exc}")


if __name__ == "__main__":
    main()
