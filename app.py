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
SAFETY_GAP_FROM_TEXT = 8    # Distance between the longest Hebrew line and the Scores
SCORE_TO_NUM_GAP     = 15   # Distance between the Scores and the Line Numbers
NUM_TO_CATCH_GAP     = 12   # Distance between the Line Numbers and the Catchwords

# =========================================================================
# MARGIN CROP CONFIGURATION (Fallback Defaults)
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

# =========================================================================
# THE MAIN PROCESSING FUNCTION
# =========================================================================
def generate_annotated_tikun_streamlit(uploaded_file, output_buffer):
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    total_pages = len(doc)
    
    # =========================================================================
    # STEP 1: BUCKETED GLOBAL CALIBRATION
    # =========================================================================
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

        # ---------------------------------------------------------------------
        # DYNAMIC HEADER BOUNDARY DETECTION
        # ---------------------------------------------------------------------
        header_y_boundary = None
        for block in page_data.get("blocks", []):
            if "lines" in block:
                for line in block["lines"]:
                    line_text = ""
                    for span in line["spans"]:
                        if "chars" in span:
                            line_text += "".join([c["c"] for c in span["chars"]])
                    
                    has_keyword = "רוחב שורה" in line_text or "הרוש בחור" in line_text
                    has_dots = len(re.findall(r'[\.\-\_~*·•]{5,}', line_text)) > 0
                    
                    if has_keyword or has_dots:
                        lx0, ly0, lx1, ly1 = line["bbox"]
                        current_boundary = ly1 + 2  
                        if header_y_boundary is None or current_boundary > header_y_boundary:
                            header_y_boundary = current_boundary
                            
        page_top_limit = max(top_limit, header_y_boundary) if header_y_boundary is not None else top_limit
        
        redactions_to_apply = []
        digit_spans = []
        
        # Gather independent digit/number spans
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
        
        # ---------------------------------------------------------------------
        # DETECT AND CONSOLIDATE SPLIT HORIZONTAL LINES
        # ---------------------------------------------------------------------
        raw_lines = []
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
                    
                    total_chars = sum(count for _, count in line_sizes)
                    if total_chars == 0:
                        continue
                    weighted_size = sum(sz * count for sz, count in line_sizes) / total_chars
                    if not (min_size_limit <= weighted_size <= max_size_limit):
                        continue
                    
                    x0, y0, x1, y1 = line["bbox"]
                    center_x = (x0 + x1) / 2
                    center_y = (y0 + y1) / 2
                    
                    if not (left_limit <= center_x <= right_limit) or not (page_top_limit <= center_y <= bottom_limit):
                        continue
                        
                    cleaned_physical = line_text.strip()
                    if not any('\u0590' <= char <= '\u05fe' for char in cleaned_physical):
                        continue
                        
                    raw_lines.append({
                        "text": line_text,
                        "chars": all_chars,
                        "spans": line["spans"], 
                        "bbox": line["bbox"],
                        "center_y": center_y,
                        "x0": x0
                    })
        
        # Group lines with vertical centers within 6px of each other
        consolidated_lines = []
        raw_lines.sort(key=lambda l: l["center_y"])
        
        for r_line in raw_lines:
            merged = False
            for c_line in consolidated_lines:
                if abs(r_line["center_y"] - c_line["center_y"]) < 6:
                    c_line["parts"].append(r_line)
                    cx0, cy0, cx1, cy1 = c_line["bbox"]
                    rx0, ry0, rx1, ry1 = r_line["bbox"]
                    c_line["bbox"] = (
                        min(cx0, rx0),
                        min(cy0, ry0),
                        max(cx1, rx1),
                        max(cy1, ry1)
                    )
                    c_line["center_y"] = (c_line["bbox"][1] + c_line["bbox"][3]) / 2
                    merged = True
                    break
            if not merged:
                consolidated_lines.append({
                    "parts": [r_line],
                    "bbox": r_line["bbox"],
                    "center_y": r_line["center_y"]
                })
        
        # Process and clean consolidated rows
        valid_blocks = []
        for c_line in consolidated_lines:
            # 1. Gather all raw characters from this consolidated row
            all_chars = []
            for part in c_line["parts"]:
                all_chars.extend(part["chars"])
            
            # Filter out spacing characters, keeping only printable ones
            printable_chars = [c for c in all_chars if c["c"].strip()]
            
            if not printable_chars:
                continue
                
            # Sort printable characters physically Left-to-Right (LTR) by their left coordinate x0
            printable_chars.sort(key=lambda c: c["bbox"][0])
            
            # 2. Group characters into physical "word clusters" based on visual gaps
            word_clusters = []
            current_cluster = []
            
            for char_obj in printable_chars:
                if not current_cluster:
                    current_cluster.append(char_obj)
                else:
                    prev_char = current_cluster[-1]
                    # Calculate visual gap between previous character's right edge and current's left
                    gap = char_obj["bbox"][0] - prev_char["bbox"][2]
                    
                    font_size = char_obj.get("size", 12)
                    gap_threshold = max(3.5, font_size * 0.24)
                    
                    if gap > gap_threshold:
                        word_clusters.append(current_cluster)
                        current_cluster = [char_obj]
                    else:
                        current_cluster.append(char_obj)
            if current_cluster:
                word_clusters.append(current_cluster)
                
            # Sort characters inside each cluster RTL (descending x0) for correct spelling
            processed_words = []
            for cluster in word_clusters:
                cluster.sort(key=lambda c: c["bbox"][0], reverse=True)
                word_text = "".join([c["c"] for c in cluster])
                
                wx0 = min(c["bbox"][0] for c in cluster)
                wy0 = min(c["bbox"][1] for c in cluster)
                wx1 = max(c["bbox"][2] for c in cluster)
                wy1 = max(c["bbox"][3] for c in cluster)
                
                processed_words.append({
                    "text": word_text,
                    "chars": cluster,
                    "bbox": (wx0, wy0, wx1, wy1)
                })
                
            # 3. Sort the completed words RTL (descending by their right edge x1)
            processed_words.sort(key=lambda w: w["bbox"][2], reverse=True)
            
            # Synchronize reconstructed combined text and characters list
            combined_text = ""
            combined_chars = []
            
            for idx, w in enumerate(processed_words):
                combined_text += w["text"]
                combined_chars.extend(w["chars"])
                
                # Insert physical visual spaces between words
                if idx < len(processed_words) - 1:
                    combined_text += " "
                    next_word = processed_words[idx + 1]
                    dummy_space = {
                        "c": " ",
                        "bbox": (next_word["bbox"][2], w["bbox"][1], w["bbox"][0], w["bbox"][3]),
                        "size": w["chars"][0].get("size", 12),
                        "font": w["chars"][0].get("font", "")
                    }
                    combined_chars.append(dummy_space)
            
            raw_cleaned = combined_text.strip()
            ignore_indices = set()
            inline_num_rect = None
            inline_num_str = ""
            
            digit_match = re.match(r'^(\s*)(\d+)(\s*)', combined_text)
            if digit_match:
                inline_num_str = digit_match.group(2)
                for idx in range(digit_match.start(1), digit_match.end(3)):
                    ignore_indices.add(idx)
                    
                bboxes = []
                for idx in range(digit_match.start(2), digit_match.end(2)):
                    if idx < len(combined_chars):
                        bboxes.append(fitz.Rect(combined_chars[idx]["bbox"]))
                if bboxes:
                    inline_num_rect = bboxes[0]
                    for bbox in bboxes[1:]:
                        inline_num_rect.include_rect(bbox)
            
            for match in re.finditer(r'(אשרי\s*){2,}', combined_text):
                for idx in range(match.start(), match.end()):
                    ignore_indices.add(idx)
                    
            for idx, char_obj in enumerate(combined_chars):
                char_obj["is_biblical"] = (idx not in ignore_indices)
            
            cleaned_physical = re.sub(r'^\d+\s*', '', raw_cleaned).strip()
            cleaned_biblical = re.sub(r'(אשרי\s*){2,}', ' ', cleaned_physical)
            cleaned_biblical = re.sub(r'\s+', ' ', cleaned_biblical).strip()
            
            if not cleaned_physical or cleaned_physical.isdigit():
                continue
                
            if len(cleaned_biblical) == 0:
                continue
                
            if len(cleaned_physical.split()) < 2:
                continue
                
            valid_blocks.append({
                "physical_text": cleaned_physical,
                "biblical_text": cleaned_biblical,
                "chars": combined_chars,
                "bbox": c_line["bbox"],
                "inline_num_rect": inline_num_rect,
                "inline_num_str": inline_num_str
            })
        
        valid_blocks.sort(key=lambda b: b["bbox"][1])
        biblical_lines = valid_blocks
        
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
            biblical_chars = [c for c in chars if c.get("is_biblical", True) and c["c"].strip()]
            biblical_chars_sorted = sorted(biblical_chars, key=lambda c: c["bbox"][0])
            
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
                    break 
                    
    # Save the output directly to the stream buffer
    doc.save(output_buffer, garbage=4, deflate=True)
    doc.close()

# --- STREAMLIT UI ---
st.title("Tikun Annotator")
uploaded_file = st.file_uploader("Upload your PDF", type="pdf")

if uploaded_file is not None:
    if st.button("Annotate PDF"):
        try:
            output_buffer = io.BytesIO()
            
            with st.spinner("Processing... Please wait."):
                generate_annotated_tikun_streamlit(uploaded_file, output_buffer)
            
            output_buffer.seek(0)
            
            if output_buffer.getbuffer().nbytes == 0:
                st.error("The file was processed, but it is empty.")
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
