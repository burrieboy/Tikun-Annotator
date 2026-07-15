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
                try: os.remove(font_file)
                except Exception: pass
    if not success:
        raise RuntimeError("Could not obtain a Hebrew font.")

# =========================================================================
# CONFIGURATION
# =========================================================================
SAFETY_GAP_FROM_TEXT = 8    
SCORE_TO_NUM_GAP     = 15   
NUM_TO_CATCH_GAP     = 12   
TOP_CROP_PERCENT    = 0.11  
BOTTOM_CROP_PERCENT = 0.06  
LEFT_CROP_PERCENT   = 0.04  
RIGHT_CROP_PERCENT  = 0.04  
NUMBER_FONT_SIZE    = 9         
NUMBER_COLOR        = (0, 0, 0) 
stretchable_letters = {'ד', 'ר', 'ק', 'ת', 'ל', 'ה'}

# =========================================================================
# UTILITIES
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
            is_run_filler = (len(run_text) >= 5) or (run_text in {"אשרי", "ירשא", "אשריי", "יירשא"})
            if is_run_filler:
                for j in range(start, end): chars[j]["is_biblical"] = False
        else: i += 1

# =========================================================================
# MAIN PROCESSING
# =========================================================================
def generate_annotated_tikun_streamlit(uploaded_file, output_buffer):
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    total_pages = len(doc)
    
    # Calibration
    bucketed_sizes = {}
    for p_num in range(min(20, total_pages)):
        p = doc[p_num]
        for block in p.get_text("rawdict").get("blocks", []):
            if "lines" in block:
                for line in block["lines"]:
                    for span in line["spans"]:
                        sz = span["size"]
                        if 8.0 <= sz <= 30.0:
                            bucket = round(sz)
                            bucketed_sizes[bucket] = bucketed_sizes.get(bucket, 0) + len(span["chars"])
    dominant_bucket = max(bucketed_sizes, key=bucketed_sizes.get) if bucketed_sizes else 16
    min_size_limit, max_size_limit = dominant_bucket - 1.2, dominant_bucket + 1.8

    for page_num in range(total_pages):
        page = doc[page_num]
        page.insert_font(fontname="alef", fontfile=font_file)
        page_data = page.get_text("rawdict")
        page_width, page_height = page.rect.width, page.rect.height
        
        # Crop logic
        left_limit, right_limit = page_width * LEFT_CROP_PERCENT, page_width * (1.0 - RIGHT_CROP_PERCENT)
        top_limit, bottom_limit = page_height * TOP_CROP_PERCENT, page_height * (1.0 - BOTTOM_CROP_PERCENT)
        header_y_boundary = None
        for block in page_data.get("blocks", []):
            if "lines" in block:
                for line in block["lines"]:
                    line_text = "".join([c["c"] for span in line["spans"] for c in span["chars"]])
                    if "רוחב שורה" in line_text or "הרוש בחור" in line_text or len(re.findall(r'[\.\-\_~*·•]{5,}', line_text)) > 0:
                        header_y_boundary = max(header_y_boundary or 0, line["bbox"][3] + 2)
        page_top_limit = max(top_limit, header_y_boundary) if header_y_boundary is not None else top_limit
        
        digit_spans, redactions_to_apply = [], []
        
        # Consolidation Logic
        raw_lines = []
        for block in page_data.get("blocks", []):
            if "lines" in block:
                for line in block["lines"]:
                    all_chars = [c for span in line["spans"] for c in span["chars"]]
                    line_text = "".join([c["c"] for c in all_chars])
                    if not any('\u0590' <= char <= '\u05fe' for char in line_text): continue
                    
                    x0, y0, x1, y1 = line["bbox"]
                    if not (left_limit <= (x0+x1)/2 <= right_limit) or not (page_top_limit <= (y0+y1)/2 <= bottom_limit): continue
                    
                    raw_lines.append({"chars": all_chars, "bbox": line["bbox"], "center_y": (y0+y1)/2})

        consolidated_lines = []
        raw_lines.sort(key=lambda l: l["center_y"])
        for r_line in raw_lines:
            merged = False
            for c_line in consolidated_lines:
                if abs(r_line["center_y"] - c_line["center_y"]) < 6:
                    c_line["parts"].append(r_line)
                    cx0, cy0, cx1, cy1 = c_line["bbox"]
                    rx0, ry0, rx1, ry1 = r_line["bbox"]
                    c_line["bbox"] = (min(cx0, rx0), min(cy0, ry0), max(cx1, rx1), max(cy1, ry1))
                    c_line["center_y"] = (c_line["bbox"][1] + c_line["bbox"][3]) / 2
                    merged = True; break
            if not merged: consolidated_lines.append({"parts": [r_line], "bbox": r_line["bbox"], "center_y": r_line["center_y"]})

        # Density and Block Processing
        valid_blocks = []
        for c_line in consolidated_lines:
            all_chars = [c for part in c_line["parts"] for c in part["chars"] if c["c"].strip()]
            if not all_chars: continue
            for c in all_chars: c["is_biblical"] = True
            flag_fillers_in_line_chars(all_chars)
            all_chars.sort(key=lambda c: c["bbox"][0])
            
            biblical_chars = [c for c in all_chars if c.get("is_biblical", True)]
            
            # --- DENSITY LOGIC START ---
            hebrew_printable_chars = [c for c in all_chars if any('\u0590' <= char <= '\u05fe' for char in c["c"])]
            
            # Identify Hashem
            hashem_clusters = []
            current_c = []
            for c in biblical_chars:
                if not current_c or (c["bbox"][0] - current_c[-1]["bbox"][2]) < 6: current_c.append(c)
                else:
                    txt = re.sub(r'[^\u05d0-\u05ea]', '', strip_nikud("".join([x["c"] for x in current_c])))
                    if txt == "יהוה": hashem_clusters.append(current_c)
                    current_c = [c]
            
            hashem_char_ids = {id(c) for cluster in hashem_clusters for c in cluster}
            non_hashem_biblical_chars = [c for c in hebrew_printable_chars if id(c) not in hashem_char_ids and c.get("is_biblical", True)]
            
            effective_char_count = len(non_hashem_biblical_chars)
            effective_char_count += 4.0 * len(hashem_clusters)
            
            # Filler runs handling
            filler_runs = []
            current_run = []
            for c in hebrew_printable_chars:
                if not c.get("is_biblical", True): current_run.append(c)
                else:
                    if current_run: filler_runs.append(current_run); current_run = []
            if current_run: filler_runs.append(current_run)
            
            for run in filler_runs:
                run_text = "".join([re.sub(r'[^\u05d0-\u05ea]', '', strip_nikud(c["c"]).strip()) for c in run])
                if "אשריאשריאשרי" in run_text: effective_char_count += 11.0
                else: effective_char_count += len(run)
            # --- DENSITY LOGIC END ---
            
            valid_blocks.append({"chars": all_chars, "bbox": c_line["bbox"], "effective_char_count": effective_char_count})

        # Layout Rendering
        max_x1 = max([b["bbox"][2] for b in valid_blocks]) if valid_blocks else 0
        avg_chars = round(sum(b["effective_char_count"] for b in valid_blocks) / len(valid_blocks)) if valid_blocks else 0
        
        for block in valid_blocks:
            line_center_y = (block["bbox"][1] + block["bbox"][3]) / 2
            score_val = avg_chars - block["effective_char_count"]
            score_str = f"ח{int_to_hebrew(round(score_val))}" if round(score_val) > 0 else (f"י{int_to_hebrew(abs(round(score_val)))}" if round(score_val) < 0 else "שת")
            
            page.insert_text(fitz.Point(max_x1 + SAFETY_GAP_FROM_TEXT, line_center_y + 3), fix_rtl(score_str), fontsize=10, fontname="alef", fontfile=font_file)
            
            # Arrow logic
            biblical_chars = sorted([c for c in block["chars"] if c.get("is_biblical", True)], key=lambda c: c["bbox"][0])
            for c in biblical_chars:
                if c["c"] in stretchable_letters:
                    cx = (c["bbox"][0] + c["bbox"][2]) / 2
                    page.draw_line(fitz.Point(cx, c["bbox"][1]+6), fitz.Point(cx, c["bbox"][1]+10), color=(0.8, 0.1, 0.1), width=1)
                    page.draw_line(fitz.Point(cx-1.2, c["bbox"][1]+8.5), fitz.Point(cx, c["bbox"][1]+10), color=(0.8, 0.1, 0.1), width=1)
                    page.draw_line(fitz.Point(cx+1.2, c["bbox"][1]+8.5), fitz.Point(cx, c["bbox"][1]+10), color=(0.8, 0.1, 0.1), width=1)
                    break

    doc.save(output_buffer, garbage=3, deflate=True)
    doc.close()

def main():
    st.title("📜 Hebrew Tikun PDF Annotator")
    uploaded_file = st.file_uploader("Upload Tikun PDF", type=["pdf"])
    if uploaded_file:
        output_buffer = io.BytesIO()
        if st.button("Process"):
            generate_annotated_tikun_streamlit(uploaded_file, output_buffer)
            st.download_button("Download Annotated PDF", output_buffer.getvalue(), "tikun_annotated.pdf", "application/pdf")

if __name__ == "__main__":
    main()
