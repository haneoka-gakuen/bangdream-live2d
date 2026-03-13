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
LOCAL_LIVE2D_ROOT = Path("live2d")
CHARA_ROOT = LOCAL_LIVE2D_ROOT / "chara"
INFO_FILE = LOCAL_LIVE2D_ROOT / "_info.json"
DATA_ROOT = Path("data")
BESTDORI_BASE_URL = "https://bestdori.com/"
REGIONS = ("jp", "cn")
DIRECTORY_ASSET_TARGETS = (
    {
        "region": "jp",
        "root_path": "stamp",
        "save_layout": "split_region",
    },
    {
        "region": "cn",
        "root_path": "stamp",
        "save_layout": "split_region",
    },
    {
        "region": "jp",
        "root_path": "changedstamp",
        "save_layout": "split_region",
    },
    {
        "region": "cn",
        "root_path": "changedstamp",
        "save_layout": "split_region",
    },
    {
        "region": "jp",
        "root_path": "sdchara",
        "save_layout": "shared",
    },
    {
        "region": "cn",
        "root_path": "sdchara",
        "save_layout": "shared",
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


def collect_local_file_counts(chara_root):
    counts = {}
    if not chara_root.exists():
        chara_root.mkdir(parents=True, exist_ok=True)
        return counts

    for folder in chara_root.iterdir():
        if folder.is_dir():
            counts[folder.name] = sum(1 for path in folder.rglob("*") if path.is_file())
    return counts


def build_related_ids_by_prefix(local_folder_names):
    related_ids = {}
    for folder_name in local_folder_names:
        if not folder_name.endswith("_rip"):
            continue
        chara_id = folder_name[:-4]
        prefix = chara_id.split("_", 1)[0]
        related_ids.setdefault(prefix, set()).add(chara_id)
    return related_ids


def find_models_to_update(chara_data, local_counts):
    missing_models = set()
    related_ids_by_prefix = build_related_ids_by_prefix(local_counts.keys())

    for chara_id, expected_count in chara_data.items():
        local_count = local_counts.get(f"{chara_id}_rip", 0)
        if local_count >= expected_count:
            continue

        missing_models.add(chara_id)
        prefix = chara_id.split("_", 1)[0]
        missing_models.update(related_ids_by_prefix.get(prefix, set()))

    return sorted(missing_models)


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

def write_info_file(chara_data):
    with INFO_FILE.open("w", encoding="utf-8") as file_obj:
        json.dump(chara_data, file_obj, ensure_ascii=False, separators=(",", ":"))
    print(f"Updated `{INFO_FILE.as_posix()}`")


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


def iter_leaf_asset_paths(node, prefix):
    if isinstance(node, dict):
        for name, child in node.items():
            child_prefix = f"{prefix}/{name}" if prefix else name
            yield from iter_leaf_asset_paths(child, child_prefix)
        return

    yield prefix


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
    save_layout = target["save_layout"]
    tree = client.fetch_asset_tree(region)
    node = get_asset_tree_node(tree, root_path)
    if node is None:
        raise ValueError(f"Directory asset target not found: {region}/{root_path}")

    expanded_targets = []
    for leaf_path in iter_leaf_asset_paths(node, root_path):
        expanded_targets.append(
            {
                "region": region,
                "index_path": leaf_path,
                "asset_path": asset_path_for_leaf(leaf_path),
                "save_dir": save_dir_for_leaf(region, leaf_path, save_layout),
            }
        )

    return expanded_targets


def build_indexed_asset_targets(client):
    targets = []
    for target in DIRECTORY_ASSET_TARGETS:
        targets.extend(expand_directory_asset_target(client, target))

    deduped_targets = []
    seen = set()
    for target in targets:
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


def build_live2d_chara_targets(client):
    chara_data = {}
    targets = []

    for region in REGIONS:
        chara_node = get_asset_tree_node(client.fetch_asset_tree(region), "live2d/chara")
        if not isinstance(chara_node, dict):
            raise ValueError(f"Missing live2d/chara asset tree for region: {region}")

        for chara_id, expected_count in sorted(chara_node.items()):
            if chara_id in chara_data:
                continue

            chara_data[chara_id] = expected_count
            targets.append(
                {
                    "region": region,
                    "chara_id": chara_id,
                    "index_path": f"live2d/chara/{chara_id}",
                    "asset_path": f"live2d/chara/{chara_id}_rip",
                    "save_dir": CHARA_ROOT / f"{chara_id}_rip",
                }
            )

    return chara_data, targets


def write_indexed_asset_info_files(info_by_group):
    for group_name, group_info in info_by_group.items():
        write_json_file(Path(group_name) / "_info.json", group_info)


def update_indexed_asset_files(client):
    failed_targets = []
    info_by_group = {}
    indexed_asset_targets = build_indexed_asset_targets(client)

    for target in indexed_asset_targets:
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


def update_live2d_chara_files(client):
    chara_data, chara_targets = build_live2d_chara_targets(client)
    write_info_file(chara_data)

    local_counts = collect_local_file_counts(CHARA_ROOT)
    models_to_update = find_models_to_update(chara_data, local_counts)

    if not models_to_update:
        print("Live2D chara assets are already up to date.")
        return

    print(f"Found {len(models_to_update)} live2d models that need syncing:")
    for chara_id in models_to_update:
        print(chara_id)

    target_by_id = {target["chara_id"]: target for target in chara_targets}
    failed_models = []

    print("Downloading missing live2d files ...")
    for chara_id in models_to_update:
        target = target_by_id.get(chara_id)
        if target is None:
            print(f"[*] Skip: {chara_id} (not present in current asset tree)")
            continue

        label = chara_id
        print(f"\n[*] Begin to download: {label}")
        try:
            remote_files = client.fetch_indexed_directory_files(
                explorer_assets_url(target["region"], f"{target['index_path']}.json"),
                label,
            )
            if client.download_indexed_directory(
                remote_files=remote_files,
                base_url=assets_url(target["region"], f"{target['asset_path']}/"),
                save_dir=target["save_dir"],
                label=label,
            ):
                print(f"[*] Success: {label}")
            else:
                failed_models.append(label)
                print(f"[*] Failed: {label}")
        except Exception as exc:
            failed_models.append(label)
            print(f"[*] Failed: {label} ({exc})")

    if failed_models:
        print("\nFailed live2d models:")
        for chara_id in failed_models:
            print(chara_id)


def main():
    client = BestdoriClient()

    try:
        update_reference_files(client)
        update_indexed_asset_files(client)
        update_live2d_chara_files(client)

    except requests.exceptions.RequestException as exc:
        print(f"Failed to request: {exc}")
    except json.JSONDecodeError as exc:
        print(f"Failed to parse: {exc}")
    except Exception as exc:
        print(f"Error: {exc}")


if __name__ == "__main__":
    main()
