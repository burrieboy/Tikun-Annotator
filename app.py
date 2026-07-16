import streamlit as st
import fitz
import io
import os
import re
import urllib.request

# =========================================================================
# SELF-HEALING & ABSOLUTE FONT PATH RESOLUTION
# =========================================================================
font_file = os.path.abspath("Alef-Regular.ttf")

def is_valid_ttf(filepath):
    if not os.path.exists(filepath):
        return False
    if os.path.getsize(filepath) < 50000:
        return False
    try:
        with open(filepath, 'rb') as f:
            sig = f.read(4)
            return sig in (b'\x00\x01\x00\x00', b'OTTO')
    except Exception:
        return False

if os.path.exists(font_file) and not is_valid_ttf(font_file):
    try:
        os.remove(font_file)
    except Exception:
        pass

if not os.path.exists(font_file):
    urls = [
        "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/alef/Alef-Regular.ttf",
        "https://github.com/google/fonts/raw/main/ofl/alef/Alef-Regular.ttf"
    ]
    success = False
    for url in urls:
        try:
            req = urllib.request.Request(
                url, 
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                data = response.read()
                with open(font_file, 'wb') as out_file:
                    out_file.write(data)
            if is_valid_ttf(font_file):
                success = True
                break
        except Exception:
            if os.path.exists(font_file):
                try:
                    os.remove(font_file)
                except Exception:
                    pass
    if not success:
        raise RuntimeError("Could not obtain a Hebrew font.")

# =========================================================================
# CONFIGURATION
# =========================================================================
TOP_CROP_PERCENT    = 0.11  
BOTTOM_CROP_PERCENT = 0.06  
LEFT_CROP_PERCENT   = 0.04  
RIGHT_CROP_PERCENT  = 0.04  
NUMBER_FONT_SIZE    = 9        
NUMBER_COLOR        = (0, 0, 0) 
stretchable_letters = {'ד', 'ר', 'ק', 'ת', 'ל', 'ה'}

# =========================================================================
# UTILITY FUNCTIONS
# =========================================================================
def strip_nikud(text):
    return re.sub(r'[\u0591-\u05c7]', '', text)

def int_to_hebrew(n):
    if n <= 0: return ""
    if n == 15: return "טו"
    if n == 16: return "טז"
    tens = {10: 'י', 20: 'כ', 30: 'ל', 40: 'מ', 50: 'נ'}
    ones = {1: 'א', 2: 'ב', 3: 'ג', 4: 'ד', 5: 'ה', 6: 'ו', 7: 'ז', 8: 'ח', 9: 'ט'}
    result = ""
    t_val = (n // 10) * 10
    if t_val in tens: result += tens[t_val]
    o_val = n % 10
    if o_val in ones: result += ones[o_val]
    return result

def fix_rtl(text):
    return text[::-1]

def flag_fillers_in_line_chars(chars):
    filler_letters = {'א', 'ש', 'ר', 'י'}
    n = len(chars)
    i = 0
    while i < n:
        c_text = chars[i]["c"]
        base = strip_nikud(c_text).strip()
        base_clean = re.sub(r'[^\u05d0-\u05ea]', '', base)
        if base_clean and all(char in filler_letters for char in base_clean):
            start = i
            while i < n:
                next_c_text = chars[i]["c"]
                next_base = strip_nikud(next_c_text).strip()
                next_base_clean = re.sub(r'[^\u05d0-\u05ea]', '', next_base)
                if next_base_clean and any(char not in filler_letters for char in next_base_clean):
                    break
                i += 1
            end = i
            run_chars = [chars[j] for j in range(start, end) if chars[j]["c"].strip()]
            run_text = "".join([re.sub(r'[^\u05d0-\u05ea]', '', strip_nikud(c["c"]).strip()) for c in run_chars])
            is_run_filler = False
            if len(run_text) >= 5: is_run_filler = True
            elif run_text in {"אשרי", "ירשא", "אשריי", "יירשא"}: is_run_filler = True
            if is_run_filler:
                for j in range(start, end): chars[j]["is_biblical"] = False
        else:
            i += 1

# =========================================================================
# MAIN PROCESSING
# =========================================================================
def generate_annotated_tikun_streamlit(uploaded_file, output_buffer, gap_val, arrow_val):
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    total_pages = len(doc)
    # ... (Note: Ensure the rest of your logic remains here) ...
    # Due to length constraints, keep your existing logic below this point, 
    # ensuring no indentation has those hidden chars.
    doc.save(output_buffer, garbage=3, deflate=True)
    doc.close()

# =========================================================================
# UI
# =========================================================================
def main():
    st.set_page_config(page_title="Hebrew Tikun Annotator", layout="wide")
    st.title("📜 Hebrew Tikun PDF Annotator")
    # ... (Keep your existing UI logic here) ...

if __name__ == "__main__":
    main()
