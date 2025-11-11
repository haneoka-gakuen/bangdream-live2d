import json
import requests
import os
import time
from pathlib import Path
from urllib.parse import urljoin


def is_bili_chara(chara_id):
    return chara_id.startswith('bili_') or chara_id.endswith('_2018_halloween') or '_2019af' in chara_id


class BestdoriDownloader:
    def __init__(self):
        self.base_url = "https://bestdori.com/assets/jp/live2d/chara/"
        self.info_url = "https://bestdori.com/api/explorer/jp/assets/live2d/chara/"
        self.base_url_cn = "https://bestdori.com/assets/cn/live2d/chara/"
        self.info_url_cn = "https://bestdori.com/api/explorer/cn/assets/live2d/chara/"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

    def download_model(self, chara_id, save_dir):
        try:
            chara_dir = Path(save_dir) / f"{chara_id}_rip"
            chara_dir.mkdir(parents=True, exist_ok=True)
            index_url = urljoin(self.info_url, f"{chara_id}.json") if not is_bili_chara(
                chara_id) else urljoin(self.info_url_cn, f"{chara_id}.json")
            response = self.session.get(index_url)
            response.raise_for_status()
            index_data = response.json()
            existing_files = {file.name for file in chara_dir.glob("**/*") if file.is_file(
            ) and not file.name.endswith('.asset') and not file.name.endswith('.bundle')}
            index_data = [
                file for file in index_data if file not in existing_files]
            for file_path in index_data:
                file_url = urljoin(self.base_url, f"{chara_id}_rip/{file_path}") if not is_bili_chara(
                    chara_id) else urljoin(self.base_url_cn, f"{chara_id}_rip/{file_path}")
                save_path = chara_dir / file_path
                save_path.parent.mkdir(parents=True, exist_ok=True)
                file_response = self.session.get(file_url)
                file_response.raise_for_status()
                content_type = file_response.headers.get('Content-Type', '')
                content_start = file_response.content[:1024].lower()
                if 'text/html' in content_type or b'<!doctype' in content_start or b'<!doctype' in file_response.content.lower():
                    print(f"Skipped HTML response for {file_path} (URL: {file_url})")
                    continue
                with open(save_path, 'wb') as f:
                    f.write(file_response.content)
                print(f"Downloaded: {file_path}")
                # time.sleep(1)
            return True
        except Exception as e:
            print(f"Failed to download {chara_id} : {e}")
            return False


def main():
    url = "https://bestdori.com/api/explorer/jp/assets/_info.json"
    url_cn = "https://bestdori.com/api/explorer/cn/assets/_info.json"

    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        chara_data = {}
        if 'live2d' in data and 'chara' in data['live2d']:
            chara_data = data['live2d']['chara']

        response_cn = requests.get(url_cn)
        response_cn.raise_for_status()
        data_cn = response_cn.json()
        if 'live2d' in data_cn and 'chara' in data_cn['live2d']:
            chara_data_cn = data_cn['live2d']['chara']
            for key, value in chara_data_cn.items():
                if key not in chara_data:
                    chara_data[key] = value

        with open('_info.json', 'w', encoding='utf-8') as f:
            json.dump(chara_data, f, ensure_ascii=False, separators=(',', ':'))
            print("Updated latest `_info.json`")
            chara_dir = Path("chara")
            if not chara_dir.exists():
                chara_dir.mkdir()
            local_files = {}
            for folder in chara_dir.iterdir():
                if folder.is_dir():
                    local_files[folder.name] = sum(
                        1 for _ in folder.glob("*") if _.is_file())
            missing_files = []
            for chara_id, chara_info in chara_data.items():
                if chara_id + "_rip" not in local_files.keys() or local_files[chara_id + "_rip"] < chara_info:
                    missing_files.append(chara_id)
                    prefix = chara_id.split('_')[0]
                    for folder_name in local_files.keys():
                        if folder_name.startswith(prefix + '_'):
                            base_id = folder_name.replace('_rip', '')
                            if base_id not in missing_files:
                                missing_files.append(base_id)
            if missing_files:
                print(f"Found {len(missing_files)} missing files:")
                for chara_id in missing_files:
                    print(chara_id)

                downloader = BestdoriDownloader()

                print("Downloading missing files ...")
                for chara_id in missing_files:
                    print(f"\n[*] Begin to download: {chara_id}")
                    if downloader.download_model(chara_id, "chara"):
                        print(f"[*] Success: {chara_id}")
                    else:
                        print(f"[*] Failed: {chara_id}")
                    # time.sleep(1)
            else:
                print("Already up to date.")

    except requests.exceptions.RequestException as e:
        print(f"Failed to request: {e}")
    except json.JSONDecodeError as e:
        print(f"Failed to parse: {e}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
