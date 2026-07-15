import streamlit as st
import fitz
import io
import os
import re
import urllib.request

# --- [PASTE YOUR EXACT FUNCTION HERE] ---
# Run the program
# Just paste the big function you provided earlier below this line.
# IMPORTANT: Delete the last line "generate_annotated_tikun(...)" 
# because we will call it from the button below.

def generate_annotated_tikun_streamlit(uploaded_file, output_buffer):
    # Use 'stream' to read the uploaded file directly from memory
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    
import fitz
import re
import urllib.request
import os

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
    print(f"Warning: Detected corrupt font file. Re-downloading...")
    os.remove(font_file)

if not os.path.exists(font_file):
    urls = [
        "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/alef/Alef-Regular.ttf",
        "https://github.com/google/fonts/raw/main/ofl/alef/Alef-Regular.ttf"
    ]
    success = False
    for url in urls:
        print(f"Downloading Hebrew font (Alef) from: {url}")
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
                print(f"Font download verified.")
                success = True
                break
        except Exception as e:
            print(f"Failed to download from {url}: {e}")
            if os.path.exists(font_file):
                os.remove(font_file)
    if not success:
        raise RuntimeError("Could not obtain a Hebrew font.")

# =========================================================================
# YOUR MAGIC NUMBERS (Tight & Clean Spacing)
# =========================================================================
SAFETY_GAP_FROM_TEXT = 8    # Distance between the longest Hebrew line and the Scores
SCORE_TO_NUM_GAP     = 15   # Distance between the Scores and the Line Numbers
NUM_TO_CATCH_GAP     = 12   # Distance between the Line Numbers and the Catchwords

# =========================================================================
# MARGIN CROP CONFIGURATION
# =========================================================================
TOP_CROP_PERCENT    = 0.11  
BOTTOM_CROP_PERCENT = 0.06  
LEFT_CROP_PERCENT   = 0.04  
RIGHT_CROP_PERCENT  = 0.04  

# =========================================================================
# LINE NUMBER CONFIGURATION
# =========================================================================
NUMBER_FONT_SIZE    = 9         
NUMBER_COLOR        = (0, 0, 0) 

hebrew_numerals = {1: 'א', 2: 'ב', 3: 'ג', 4: 'ד', 5: 'ה', 6: 'ו', 7: 'ז', 8: 'ח', 9: 'ט'}
stretchable_letters = {'ד', 'ר', 'ק', 'ת', 'ל', 'ה'}

def fix_rtl(text):
    return text[::-1]

def generate_annotated_tikun(input_pdf, output_pdf):
    doc = fitz.open(input_pdf)
    total_pages = len(doc)
    print(f"Loaded PDF with {total_pages} pages.")
    
    # =========================================================================
    # STEP 1: BUCKETED GLOBAL CALIBRATION
    # =========================================================================
    print("Scanning document to calibrate font sizes...")
    bucketed_sizes = {}
    pages_to_scan = min(20, total_pages)
    
    for p_num in range(pages_to_scan):
        p = doc[p_num]
        p_data = p.get_text("rawdict")
        for block in p_data.get("blocks", []):
            if "lines" in block:
                for line in block["lines"]:
                    for span in line["spans"]:
                        sz = span["size"]
                        if 8.0 <= sz <= 30.0:
                            bucket = round(sz)
                            bucketed_sizes[bucket] = bucketed_sizes.get(bucket, 0) + len(span["chars"])
                        
    if not bucketed_sizes:
        dominant_bucket = 16
    else:
        dominant_bucket = max(bucketed_sizes, key=bucketed_sizes.get)
            
    min_size_limit = dominant_bucket - 1.2
    max_size_limit = dominant_bucket + 1.8

    # =========================================================================
    # STEP 2: PROCESS PAGES
    # =========================================================================
    for page_num in range(total_pages):
        page = doc[page_num]
        page.insert_font(fontname="alef", fontfile=font_file)
        page_data = page.get_text("rawdict")
        
        page_width = page.rect.width
        page_height = page.rect.height
        
        left_limit   = page_width * LEFT_CROP_PERCENT    
        right_limit  = page_width * (1.0 - RIGHT_CROP_PERCENT)    
        top_limit    = page_height * TOP_CROP_PERCENT   
        bottom_limit = page_height * (1.0 - BOTTOM_CROP_PERCENT)   
        
        redactions_to_apply = []
        digit_spans = []
        
        # Gather all independent, numeric spans
        for block in page_data.get("blocks", []):
            if "lines" in block:
                for line in block["lines"]:
                    for span in line["spans"]:
                        span_text = "".join([c["c"] for c in span["chars"]]).strip()
                        match = re.search(r'\b\d+\b', span_text)
                        if match:
                            num_val = int(match.group(0))
                            if 1 <= num_val <= 50:
                                s_x0, s_y0, s_x1, s_y1 = span["bbox"]
                                digit_spans.append({
                                    "text": match.group(0),
                                    "bbox": fitz.Rect(span["bbox"]),
                                    "center_y": (s_y0 + s_y1) / 2
                                })
        
        valid_blocks = []
        for block in page_data.get("blocks", []):
            if "lines" in block:
                for line in block["lines"]:
                    line_text = ""
                    all_chars = []
                    line_sizes = []
                    
                    for span in line["spans"]:
                        for char_obj in span["chars"]:
                            line_text += char_obj["c"]
                            all_chars.append(char_obj)
                        line_sizes.append((span["size"], len(span["chars"])))
                    
                    raw_cleaned = line_text.strip()
                    ignore_indices = set()
                    inline_num_rect = None
                    inline_num_str = ""
                    
                    digit_match = re.match(r'^(\s*)(\d+)(\s*)', line_text)
                    if digit_match:
                        inline_num_str = digit_match.group(2)
                        for idx in range(digit_match.start(1), digit_match.end(3)):
                            ignore_indices.add(idx)
                            
                        bboxes = []
                        for idx in range(digit_match.start(2), digit_match.end(2)):
                            if idx < len(all_chars):
                                bboxes.append(fitz.Rect(all_chars[idx]["bbox"]))
                        if bboxes:
                            inline_num_rect = bboxes[0]
                            for bbox in bboxes[1:]:
                                inline_num_rect.include_rect(bbox)
                    
                    for match in re.finditer(r'(אשרי\s*){2,}', line_text):
                        for idx in range(match.start(), match.end()):
                            ignore_indices.add(idx)
                            
                    for idx, char_obj in enumerate(all_chars):
                        char_obj["is_biblical"] = (idx not in ignore_indices)
                    
                    cleaned_physical = re.sub(r'^\d+\s*', '', raw_cleaned).strip()
                    cleaned_biblical = re.sub(r'(אשרי\s*){2,}', ' ', cleaned_physical)
                    cleaned_biblical = re.sub(r'\s+', ' ', cleaned_biblical).strip()
                    
                    if not cleaned_physical or cleaned_physical.isdigit():
                        continue
                        
                    x0, y0, x1, y1 = line["bbox"]
                    center_x = (x0 + x1) / 2
                    center_y = (y0 + y1) / 2
                    
                    if not (left_limit <= center_x <= right_limit) or not (top_limit <= center_y <= bottom_limit):
                        continue
                        
                    total_chars = sum(count for _, count in line_sizes)
                    if total_chars == 0:
                        continue
                    weighted_size = sum(sz * count for sz, count in line_sizes) / total_chars
                    if not (min_size_limit <= weighted_size <= max_size_limit):
                        continue
                    
                    if not any('\u0590' <= char <= '\u05fe' for char in cleaned_physical):
                        continue
                        
                    is_filler_line = "אשרי" in cleaned_physical and len(cleaned_biblical) == 0
                    if len(cleaned_physical.split()) < 2 and not is_filler_line:
                        continue
                        
                    valid_blocks.append({
                        "physical_text": cleaned_physical,
                        "biblical_text": cleaned_biblical,
                        "chars": all_chars,
                        "bbox": line["bbox"],
                        "inline_num_rect": inline_num_rect,
                        "inline_num_str": inline_num_str
                    })
        
        valid_blocks.sort(key=lambda b: b["bbox"][1])
        biblical_lines = valid_blocks
        
        print(f"Page {page_num + 1}/{total_pages}: Processing {len(biblical_lines)} lines.")
        
        if not biblical_lines:
            continue
            
        for block in biblical_lines:
            x0, y0, x1, y1 = block["bbox"]
            line_center_y = (y0 + y1) / 2
            
            num_str = block["inline_num_str"]
            num_rect = block["inline_num_rect"]
            
            if not num_str and digit_spans:
                best_match = None
                best_dist = 99999
                for span in digit_spans:
                    dist = abs(span["center_y"] - line_center_y)
                    if dist < 20 and dist < best_dist:
                        best_dist = dist
                        best_match = span
                
                if best_match:
                    num_str = best_match["text"]
                    num_rect = best_match["bbox"]
                    digit_spans.remove(best_match)
            
            block["matched_num_str"] = num_str
            block["matched_num_rect"] = num_rect
            
        # =========================================================================
        # STRAIGHT MARGIN GENERATION
        # =========================================================================
        max_x1 = max(b["bbox"][2] for b in biblical_lines)
        
        SCORE_COL_X     = max_x1 + SAFETY_GAP_FROM_TEXT
        LINE_NUM_COL_X  = SCORE_COL_X + SCORE_TO_NUM_GAP
        CATCHWORD_COL_X = LINE_NUM_COL_X + NUM_TO_CATCH_GAP
        # =========================================================================

        avg_chars = round(sum(len(b["physical_text"]) for b in biblical_lines) / len(biblical_lines))
        prev_first_word = "—"
        
        for block in biblical_lines:
            num_rect = block["matched_num_rect"]
            if num_rect:
                padded_rect = fitz.Rect(num_rect.x0 - 2, num_rect.y0 - 2, num_rect.x1 + 2, num_rect.y1 + 2)
                redactions_to_apply.append(padded_rect)
                
        for rect in redactions_to_apply:
            page.add_redact_annot(rect, fill=(1, 1, 1))
        if redactions_to_apply:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            
        for i, block in enumerate(biblical_lines):
            physical_text = block["physical_text"]
            biblical_text = block["biblical_text"]
            chars = block["chars"]
            x0, y0, x1, y1 = block["bbox"]
            line_center_y = (y0 + y1) / 2
            
            SCORE_X       = SCORE_COL_X
            LINE_NUMBER_X = LINE_NUM_COL_X
            CATCHWORD_X   = CATCHWORD_COL_X
            
            baseline_y = line_center_y + 3
            
            score_val = avg_chars - len(physical_text)
            if score_val > 0:
                score_str = f"ח{hebrew_numerals.get(score_val, str(score_val))}"
            elif score_val < 0:
                score_str = f"י{hebrew_numerals.get(abs(score_val), str(abs(score_val)))}"
            else:
                score_str = "שת"     
                
            words = biblical_text.split()
            catch_word = prev_first_word
            
            if words:
                prev_first_word = words[0]
            else:
                prev_first_word = "—"
            
            # Print Score
            page.insert_text(
                fitz.Point(SCORE_X, baseline_y), 
                fix_rtl(score_str), 
                fontsize=10, 
                fontname="alef", 
                fontfile=font_file,
                color=(0, 0, 0),
                overlay=True
            )
            
            # Print Catch-word
            page.insert_text(
                fitz.Point(CATCHWORD_X, baseline_y), 
                fix_rtl(catch_word), 
                fontsize=9, 
                fontname="alef", 
                fontfile=font_file,
                color=(0.4, 0.4, 0.4),
                overlay=True
            )
            
            # Print Shrunk Line Number
            if block["matched_num_str"]:
                page.insert_text(
                    fitz.Point(LINE_NUMBER_X, baseline_y), 
                    block["matched_num_str"], 
                    fontsize=NUMBER_FONT_SIZE, 
                    fontname="alef", 
                    fontfile=font_file,
                    color=NUMBER_COLOR,
                    overlay=True
                )
            
            # =========================================================================
            # PHYSICAL-COORDINATE SORTING FOR ARROWS
            # =========================================================================
            # 1. Filter out non-biblical characters (like original line numbers)
            biblical_chars = [c for c in chars if c.get("is_biblical", True) and c["c"].strip()]
            
            # 2. Sort characters by physical X coordinate (ascending order: left to right).
            # In RTL Hebrew, the END of the line is on the LEFT (lowest x0 coordinate).
            # Sorting ascending means the absolute final letters on the page are at the 
            # beginning of this list.
            biblical_chars_sorted = sorted(biblical_chars, key=lambda c: c["bbox"][0])
            
            # 3. Walk through the sorted characters starting from the end of the line (leftmost)
            for char_obj in biblical_chars_sorted:
                if char_obj["c"] in stretchable_letters:
                    cx0, cy0, cx1, cy1 = char_obj["bbox"]
                    char_center_x = (cx0 + cx1) / 2
                    
                    ARROW_DOWNWARD_SHIFT = 10.0 
                    arrow_tip_y = cy0 + ARROW_DOWNWARD_SHIFT
                    arrow_top_y = arrow_tip_y - 4.5
                    
                    page.draw_line(
                        fitz.Point(char_center_x, arrow_top_y), 
                        fitz.Point(char_center_x, arrow_tip_y), 
                        color=(0.8, 0.1, 0.1), 
                        width=1
                    )
                    page.draw_line(
                        fitz.Point(char_center_x - 1.2, arrow_tip_y - 1.5), 
                        fitz.Point(char_center_x, arrow_tip_y), 
                        color=(0.8, 0.1, 0.1), 
                        width=1
                    )
                    page.draw_line(
                        fitz.Point(char_center_x + 1.2, arrow_tip_y - 1.5), 
                        fitz.Point(char_center_x, arrow_tip_y), 
                        color=(0.8, 0.1, 0.1), 
                        width=1
                    )
                    break # Found the leftmost stretchable letter. Stop looking.
                    
  # DO NOT use a filename string here
    doc.save(output_buffer, garbage=4, deflate=True)
    doc.close()
    print(f"\nSuccess! Your cleaned and fully annotated file '{output_pdf}' is ready.")

# --- STREAMLIT UI ---
st.title("Tikun Annotator")
uploaded_file = st.file_uploader("Upload your PDF", type="pdf")

if uploaded_file is not None:
    if st.button("Annotate PDF"):
        try:
            # Create a buffer in memory
            output_buffer = io.BytesIO()
            
            # Run your logic
            # IMPORTANT: Make sure inside this function, you use:
            # doc.save(output_buffer, garbage=4, deflate=True)
            # NOT: doc.save("annotated_tikun.pdf")
            generate_annotated_tikun_streamlit(uploaded_file, output_buffer)
            
            # Rewind and Check
            output_buffer.seek(0)
            
            if output_buffer.getbuffer().nbytes == 0:
                st.error("The file was processed, but it is empty. Check if the function is saving to the buffer correctly.")
            else:
                st.success(f"Success! File size: {output_buffer.getbuffer().nbytes} bytes")
                st.download_button(
                    label="Download Annotated PDF",
                    data=output_buffer,
                    file_name="annotated_tikun.pdf",
                    mime="application/pdf"
                )
        except Exception as e:
            st.error(f"The program crashed with this error: {e}")
