# Save this file as cleaner.py
# Place it in the same folder as your app.py
# Run it using: python cleaner.py

filename = 'app.py'

try:
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()

    # This replaces the specific invisible non-breaking space (U+00A0) with a standard space
    cleaned_content = content.replace('\u00a0', ' ')

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(cleaned_content)

    print(f"Success! '{filename}' has been cleaned.")

except FileNotFoundError:
    print(f"Error: Could not find '{filename}'. Ensure this script is in the same folder.")
except Exception as e:
    print(f"An error occurred: {e}")
