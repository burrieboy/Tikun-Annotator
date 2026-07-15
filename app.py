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
        except Exception as e:
            if os.path.exists(font_file):
                try:
                    os.remove(font_file)
                except Exception:
                    pass
    if not success:
        raise RuntimeError("Could not obtain a Hebrew font.")

# =========================================================================
# YOUR MAGIC NUMBERS (Tight & Clean Spacing)
# =========================================================================
SAFETY_GAP_FROM_TEXT = 8    
SCORE_TO_NUM_GAP     = 15   
NUM_TO_CATCH_GAP     = 12   

# =========================================================================
# MARGIN CROP CONFIGURATION
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
# MAIN PROCESSING FUNCTION
# =========================================================================
def generate_annotated_tikun_streamlit(uploaded_file, output_buffer):
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    total_pages = len(doc)
    bucketed_sizes = {}
    
    # Calculate global font size
    for p_num in range(min(20, total_pages)):
        for block in doc[p_num].get_text("rawdict").get("blocks", []):
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
        
        # Header/Margin logic
        header_y_boundary = None
        for block in page_data.get("blocks", []):
            if "lines" in block:
                for line in block["lines"]:
                    line_text = "".join([c["c"] for s in line["spans"] for c in s.get("chars", [])])
                    if "רוחב שורה" in line_text or "הרוש בחור" in line_text or len(re.findall(r'[\.\-\_~*·•]{5,}', line_text)) > 0:
                        header_y_boundary = max(header_y_boundary or 0, line["bbox"][3] + 2)
        
        page_top_limit = max(page_height * TOP_CROP_PERCENT, header_y_boundary or 0)
        
        # Line detection and consolidation
        raw_lines = []
        for block in page_data.get("blocks", []):
            if "lines" in block:
                for line in block["lines"]:
                    all_chars = [c for s in line["spans"] for c in s["chars"]]
                    if not all_chars: continue
                    weighted_size = sum(s["size"] * len(s["chars"]) for s in line["spans"]) / len(all_chars)
                    if not (min_size_limit <= weighted_size <= max_size_limit): continue
                    
                    x0, y0, x1, y1 = line["bbox"]
                    if not (page_width * LEFT_CROP_PERCENT <= (x0+x1)/2 <= page_width * (1.0 - RIGHT_CROP_PERCENT)): continue
                    if not (page_top_limit <= (y0+y1)/2 <= page_height * (1.0 - BOTTOM_CROP_PERCENT)): continue
                    
                    raw_lines.append({"chars": all_chars, "bbox": line["bbox"], "center_y": (y0+y1)/2})

        consolidated = []
        raw_lines.sort(key=lambda l: l["center_y"])
        for r in raw_lines:
            merged = False
            for c in consolidated:
                if abs(r["center_y"] - c["center_y"]) < 6:
                    c["chars"].extend(r["chars"])
                    c["bbox"] = (min(c["bbox"][0], r["bbox"][0]), min(c["bbox"][1], r["bbox"][1]), max(c["bbox"][2], r["bbox"][2]), max(c["bbox"][3], r["bbox"][3]))
                    merged = True; break
            if not merged: consolidated.append(r)
        
        # Process lines
        valid_blocks = []
        for c_line in consolidated:
            c_line["chars"].sort(key=lambda c: c["bbox"][0])
            for c in c_line["chars"]: c["is_biblical"] = True
            
            flag_fillers_in_line_chars(c_line["chars"])
            
            hebrew_printable = [c for c in c_line["chars"] if c["c"].strip() and any('\u0590' <= ch <= '\u05fe' for ch in c["c"])]
            full_line_text = "".join([re.sub(r'[^\u05d0-\u05ea]', '', strip_nikud(c["c"])) for c in hebrew_printable])
            
            # --- OVERRIDE LOGIC: Force high count for triple Ashrei ---
            has_triple_ashrei = "אשריאשריאשרי" in full_line_text
            
            # Count calculation
            biblical_chars = [c for c in hebrew_printable if c.get("is_biblical", True)]
            hashem_count = len([c for c in c_line["chars"] if re.sub(r'[^\u05d0-\u05ea]', '', strip_nikud(c["c"])) == "יהוה"]) // 4
            effective_char_count = (len(biblical_chars) - (4 * hashem_count)) + (4.0 * hashem_count)
            
            # Add non-biblical/filler characters
            fillers = [c for c in hebrew_printable if not c.get("is_biblical", True)]
            if has_triple_ashrei:
                effective_char_count += 48.0
            else:
                effective_char_count += len(fillers)
                
            valid_blocks.append({
                "bbox": c_line["bbox"],
                "effective_char_count": effective_char_count,
                "has_triple_ashrei": has_triple_ashrei,
                "chars": c_line["chars"]
            })

        # Final pass: Scores and Drawings
        avg_chars = round(sum(b["effective_char_count"] for b in valid_blocks) / len(valid_blocks)) if valid_blocks else 0
        
        for block in valid_blocks:
            line_center_y = (block["bbox"][1] + block["bbox"][3]) / 2
            score_val = avg_chars - block["effective_char_count"]
            score_str = f"ח{int_to_hebrew(round(score_val))}" if round(score_val) > 0 else (f"י{int_to_hebrew(abs(round(score_val)))}" if round(score_val) < 0 else "שת")
            
            # Score
            page.insert_text(fitz.Point(block["bbox"][2] + SAFETY_GAP_FROM_TEXT, line_center_y + 3), fix_rtl(score_str), fontsize=10, fontname="alef", fontfile=font_file)
            
            # Debug Dot for triple ashrei
            if block["has_triple_ashrei"]:
                page.draw_circle(fitz.Point(block["bbox"][0] - 5, line_center_y), 1.5, color=(0, 0.7, 0), fill=(0, 0.7, 0))

    doc.save(output_buffer, garbage=3, deflate=True)
    doc.close()

def main():
    st.set_page_config(page_title="Hebrew Tikun Annotator")
    st.title("📜 Hebrew Tikun PDF Annotator")
    uploaded_file = st.file_uploader("Choose a Tikun PDF file", type=["pdf"])
    if uploaded_file is not None:
        output_buffer = io.BytesIO()
        if st.button("Process PDF"):
            with st.spinner("Processing..."):
                generate_annotated_tikun_streamlit(uploaded_file, output_buffer)
                st.success("Done!")
                st.download_button("Download", data=output_buffer.getvalue(), file_name="annotated.pdf", mime="application/pdf")

if __name__ == "__main__":
    main()
