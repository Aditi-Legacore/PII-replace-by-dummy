import json
import os

def combine_pii_files():
    combined_data = {}
    output_dir = 'output'

    for i in range(1, 36):  # From 1 to 35
        file_path = os.path.join(output_dir, f'pii_page_{i}.json')
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                data = json.load(f)
                combined_data.update(data)
        else:
            print(f"Warning: {file_path} not found")

    # Write the combined data to a new file
    output_file = os.path.join(output_dir, 'combined_pii.json')
    with open(output_file, 'w') as f:
        json.dump(combined_data, f, indent=4)

    print(f"Combined PII data written to {output_file}")

if __name__ == "__main__":
    combine_pii_files()
