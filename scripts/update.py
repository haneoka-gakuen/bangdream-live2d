import os
import json

chara_folder = "chara"
output_file = "_info.json"


def update(folder_path, output_path):
    folder_names = sorted([name.replace("_rip", "") for name in os.listdir(
        folder_path) if os.path.isdir(os.path.join(folder_path, name))])
    data = {name: 0 for name in folder_names}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


update(chara_folder, output_file)
