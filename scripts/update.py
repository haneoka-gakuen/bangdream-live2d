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
CHARA_ROOT = Path("chara")
INFO_FILE = Path("_info.json")
DATA_ROOT = Path("data")
BESTDORI_BASE_URL = "https://bestdori.com/"
REGIONS = ("jp", "cn")
REFERENCE_FILES = {
    "bands.all.1.json": "api/bands/all.1.json",
    "characters.all.5.json": "api/characters/all.5.json",
    "cards.all.5.json": "api/cards/all.5.json",
    "costumes.all.5.json": "api/costumes/all.5.json",
}


def is_bili_chara(chara_id):
    return (
        chara_id.startswith("bili_")
        or chara_id.endswith("_2018_halloween")
        or "_2019af" in chara_id
    )


def bestdori_url(path):
    return urljoin(BESTDORI_BASE_URL, path)


def explorer_assets_url(region, path=""):
    return bestdori_url(f"api/explorer/{region}/assets/{path}")


def live2d_chara_assets_url(region, path=""):
    return bestdori_url(f"assets/{region}/live2d/chara/{path}")


def chara_region(chara_id):
    return "cn" if is_bili_chara(chara_id) else "jp"


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

    def fetch_json(self, url):
        response = self.session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()

    def fetch_all_chara_info(self):
        chara_data = {}
        for region in REGIONS:
            data = self.fetch_json(explorer_assets_url(region, "_info.json"))
            for key, value in data.get("live2d", {}).get("chara", {}).items():
                chara_data.setdefault(key, value)

        return chara_data

    def model_info_url(self, chara_id):
        return explorer_assets_url(chara_region(chara_id), f"live2d/chara/{chara_id}.json")

    def model_file_url(self, chara_id, file_path):
        return live2d_chara_assets_url(chara_region(chara_id), f"{chara_id}_rip/{file_path}")

    def fetch_model_index(self, chara_id):
        index_data = self.fetch_json(self.model_info_url(chara_id))
        if not isinstance(index_data, list):
            raise ValueError(f"Unexpected model index for {chara_id}")
        return index_data

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

    def download_model(self, chara_id, save_root):
        try:
            chara_dir = save_root / f"{chara_id}_rip"
            chara_dir.mkdir(parents=True, exist_ok=True)

            remote_files = self.fetch_model_index(chara_id)
            existing_files = {
                path.relative_to(chara_dir).as_posix()
                for path in chara_dir.rglob("*")
                if path.is_file()
            }
            missing_files = [
                file_path for file_path in remote_files if file_path not in existing_files
            ]

            if not missing_files:
                print(f"No missing files for {chara_id}")
                return True

            print(f"{chara_id}: {len(missing_files)} files to download")
            all_succeeded = True

            for file_path in missing_files:
                file_url = self.model_file_url(chara_id, file_path)
                save_path = chara_dir / file_path
                save_path.parent.mkdir(parents=True, exist_ok=True)

                if self.download_file(file_url, save_path):
                    print(f"Downloaded: {file_path}")
                else:
                    all_succeeded = False

            return all_succeeded
        except Exception as exc:
            print(f"Failed to download {chara_id}: {exc}")
            return False


def write_info_file(chara_data):
    with INFO_FILE.open("w", encoding="utf-8") as file_obj:
        json.dump(chara_data, file_obj, ensure_ascii=False, separators=(",", ":"))
    print("Updated latest `_info.json`")


def write_json_file(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file_obj:
        json.dump(data, file_obj, ensure_ascii=False, separators=(",", ":"))
    print(f"Updated `{path.as_posix()}`")


def update_reference_files(client):
    for file_name, url in REFERENCE_FILES.items():
        data = client.fetch_json(bestdori_url(url))
        write_json_file(DATA_ROOT / file_name, data)


def main():
    client = BestdoriClient()

    try:
        update_reference_files(client)

        chara_data = client.fetch_all_chara_info()
        write_info_file(chara_data)

        local_counts = collect_local_file_counts(CHARA_ROOT)
        models_to_update = find_models_to_update(chara_data, local_counts)

        if not models_to_update:
            print("Already up to date.")
            return

        print(f"Found {len(models_to_update)} models that need syncing:")
        for chara_id in models_to_update:
            print(chara_id)

        failed_models = []
        print("Downloading missing files ...")
        for chara_id in models_to_update:
            print(f"\n[*] Begin to download: {chara_id}")
            if client.download_model(chara_id, CHARA_ROOT):
                print(f"[*] Success: {chara_id}")
            else:
                failed_models.append(chara_id)
                print(f"[*] Failed: {chara_id}")

        if failed_models:
            print("\nFailed models:")
            for chara_id in failed_models:
                print(chara_id)

    except requests.exceptions.RequestException as exc:
        print(f"Failed to request: {exc}")
    except json.JSONDecodeError as exc:
        print(f"Failed to parse: {exc}")
    except Exception as exc:
        print(f"Error: {exc}")


if __name__ == "__main__":
    main()
