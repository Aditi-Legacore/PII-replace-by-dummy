import json
import os
from collections import OrderedDict

def normalize_name(name):
    if ',' in name:
        last, first = name.split(',', 1)
        return f"{first.strip().title()} {last.strip().title()}"
    return name.title()


def combine_pii_files():
    output_dir = "G:\\My Drive\\Legacore Infomatics\\3. Individual Folder\\Aditi\\BF - James Freer"
    combined_names = []
    combined_dobs = []
    combined_addresses = []

    for i in range(1, 36):
        file_path = os.path.join(output_dir, f"2025.01.10 AMR - Mark up and comment done.txt")

        if not os.path.exists(file_path):
            continue

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"❌ Skipping invalid JSON: {file_path}")
            print(f"   {e}")
            continue

        for page in data.get("pages", []):
            combined_names.extend(page.get("person_names", []))
            combined_dobs.extend(page.get("date_of_birth", []))
            combined_addresses.extend(page.get("physical_street_addresses", []))

    def unique(items):
        return list(OrderedDict.fromkeys(items))

    combined_names = unique(combined_names)
    combined_dobs = unique(combined_dobs)
    combined_addresses = unique(combined_addresses)

    output_data = {
        "Name": normalize_name(combined_names[0]) if combined_names else "",
        "DOB": combined_dobs[0] if combined_dobs else "",
        "Address": combined_addresses[0] if combined_addresses else ""
    }

    output_file = os.path.join(output_dir, "combined_pii_ai.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=4)

    print(f"\n✅ Combined PII written to {output_file}")


if __name__ == "__main__":
    combine_pii_files()
